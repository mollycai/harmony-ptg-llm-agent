from __future__ import annotations

# 路由结构抽取主流程（RouteStructureAgent）：
# 1) 从 main_pages 出发递归读取可达的 .ets 文件；
# 2) 对通过“LLM 准入门”的文件执行三阶段抽取：
#    - census：先统计调用点
#    - extract：主抽取边
#    - recover：按缺口补漏
# 3) 做 target 合法性过滤后写入 PTGMemory。

import asyncio
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from langchain_openai import ChatOpenAI
from llm_usage import extract_token_usage

from agent.memory import PTGMemory
from agent.prompt.route_structure_prompt import (
    CENSUS_SYSTEM_PROMPT,
    COVERAGE_RETRY_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_coverage_retry_user_prompt,
    build_census_user_prompt,
    build_user_prompt,
)
from agent.tools.import_resolver import ImportResolver
from agent.tools.project_reader import ProjectReader
from agent.tools.route_constant_resolver import RouteConstantResolver
from agent.tools.route_tool_calling import RouteToolCallingResolver
from agent.utils.llm_json import parse_llm_json_list
from agent.utils.route_utils import is_invalid_target, normalize_path, strip_ets
from llm_server import build_chat_model

_ACTIONABLE_ROUTER_CALL_RE = re.compile(
    r"""\brouter\s*\.\s*(?:pushUrl|replaceUrl|push|replace|back)\s*\(""",
    flags=re.IGNORECASE,
)
# 仅把明确的路由动作 API 视作可执行线索，避免普通 router 文本误触发分析。


def _ensure_ets(p: str) -> str:
    """
    规范化页面路径并确保以 .ets 结尾。

    Args:
        p: 原始页面路径（可能无扩展名）。

    Returns:
        规范化后的页面路径；若原始为空则返回空字符串。
    """
    t = normalize_path(p)
    return t if (not t or t.endswith(".ets")) else f"{t}.ets"


def _safe_dir(name: str, fallback: str = "default") -> str:
    """
    将任意字符串转换为可安全创建目录的名称。

    Args:
        name: 目录名候选字符串。
        fallback: name 无效时的回退目录名。

    Returns:
        过滤非法字符后的安全目录名。
    """
    s = (name or "").strip() or fallback
    s = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", s)
    s = re.sub(r"[. ]+$", "", s).strip() or fallback
    if re.fullmatch(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])", s, flags=re.IGNORECASE):
        s = "_" + s
    return s


@dataclass
class RouteStructureAgentConfig:
    """RouteStructureAgent 的运行配置。"""
    project_name: str
    project_path: str
    main_pages_json_path: str
    llm_provider_config: dict
    llm_model_name: str
    import_alias_map: Optional[Dict[str, str]] = None

    ets_root: Optional[str] = None
    output_dir: str = str(Path(__file__).resolve().parent / "result")
    max_files: int = 2000
    max_depth: int = 30
    max_route_files: int = 120
    max_route_file_chars: int = 40000
    chunk_trigger_lines: int = 320
    chunk_size_lines: int = 220
    chunk_overlap_lines: int = 50
    enable_router_census_probe: bool = True
    llm_skip_dirs: Optional[List[str]] = None


class RouteStructureAgent:
    """路由结构抽取 Agent。"""

    def __init__(self, config: RouteStructureAgentConfig) -> None:
        self.config = config
        self.llm: ChatOpenAI = build_chat_model(config.llm_provider_config, config.llm_model_name)

        ets_root = config.ets_root or str(Path(config.project_path) / "src" / "main" / "ets")
        self.ets_root = Path(ets_root)
        self.project_root = Path(config.project_path)
        self.import_alias_map = self._normalize_import_alias_map(config.import_alias_map)

        if self.import_alias_map:
            print(
                "[RouteStructureAgent] Import alias map loaded: "
                + json.dumps(self.import_alias_map, ensure_ascii=False)
            )
        else:
            print("[RouteStructureAgent] Import alias map is empty.")

        self.memory = PTGMemory()
        self.reader = ProjectReader(ets_root=str(self.ets_root))
        self.import_resolver = ImportResolver(reader=self.reader, import_alias_map=self.import_alias_map)
        self.route_const_resolver = RouteConstantResolver(
            ets_root=str(self.ets_root),
            max_files=int(self.config.max_route_files),
            max_chars_per_file=int(self.config.max_route_file_chars),
        )
        # tool-calling 仅用于“表达式/常量补解析”，不负责主抽取。
        self.tool_calling_resolver = RouteToolCallingResolver(
            llm=self.llm,
            import_resolver=self.import_resolver,
            route_const_resolver=self.route_const_resolver,
            token_reporter=self._record_token_usage_numbers,
        )
        # 仅针对 LLM 分析的目录跳过名单（不影响 import 解析与递归依赖发现）。
        skip_dirs = config.llm_skip_dirs or ["http", "route"]
        self._llm_skip_dirs: Set[str] = {str(x).strip().lower() for x in skip_dirs if str(x).strip()}

        self.dependency_graph: Dict[str, List[str]] = {}
        self._visited: Set[str] = set()
        self._count = 0
        self._main_page_ids: Set[str] = set()
        self._token_prompt = 0
        self._token_completion = 0
        self._token_total = 0
        self._token_calls = 0

    def _record_token_usage_numbers(self, stage: str, prompt: int, completion: int, total: int) -> None:
        """记录并打印一次 LLM 交互 token。"""
        self._token_calls += 1
        self._token_prompt += int(prompt or 0)
        self._token_completion += int(completion or 0)
        self._token_total += int(total or 0)
        print(
            f"[RouteStructureAgent] Token usage | {stage}: "
            f"prompt={int(prompt or 0)}, completion={int(completion or 0)}, total={int(total or 0)}"
        )

    def _record_token_usage(self, *, stage: str, msg: Any) -> None:
        """从 LangChain 消息对象提取并记录 token。"""
        prompt, completion, total = extract_token_usage(msg)
        self._record_token_usage_numbers(stage, prompt, completion, total)

    def _normalize_import_alias_map(self, raw_map: Optional[Dict[str, str]]) -> Dict[str, str]:
        """
        把 import alias 映射标准化为绝对路径。

        Args:
            raw_map: 原始 alias 映射，键为 alias 前缀，值为目录路径（可相对/绝对）。

        Returns:
            标准化后的 alias 映射（全部是绝对路径）。
        """
        out: Dict[str, str] = {}
        for k, v in (raw_map or {}).items():
            alias = (k or "").strip()
            base = (v or "").strip()
            if not alias or not base:
                continue
            p = Path(base)
            if not p.is_absolute():
                p = (self.project_root / p).resolve()
            out[alias] = str(p)
        return out

    def _is_readable_ets_file(self, file_path: str) -> bool:
        """
        判断路径是否为可读取的 .ets 文件。

        Args:
            file_path: 待检测文件路径。

        Returns:
            可读取且后缀为 .ets 时返回 True，否则返回 False。
        """
        p = Path(file_path)
        try:
            return p.exists() and p.is_file() and p.suffix.lower() == ".ets"
        except Exception:
            return False

    @staticmethod
    def _has_router_hints(code: str) -> bool:
        """
        判断代码里是否包含可执行的路由动作调用。

        Args:
            code: 源码文本。

        Returns:
            命中 router.push/replace/back 相关调用时返回 True。
        """
        return bool(_ACTIONABLE_ROUTER_CALL_RE.search(code or ""))

    @staticmethod
    def _to_runtime_code_for_admission(code: str) -> str:
        """
        准入门预处理：移除注释与 import/export，降低误判。

        Args:
            code: 原始源码文本。

        Returns:
            清洗后的运行时代码文本。
        """
        src = code or ""
        src = re.sub(r"/\*[\s\S]*?\*/", "", src)
        src = re.sub(r"//.*$", "", src, flags=re.MULTILINE)
        lines = []
        for ln in src.splitlines():
            s = ln.lstrip()
            if s.startswith("import ") or s.startswith("export "):
                continue
            lines.append(ln)
        return "\n".join(lines)

    def _is_llm_admissible_file(self, *, file_path: Path, code: str) -> bool:
        """
        判断文件是否允许进入 LLM 分析。

        Args:
            file_path: 当前文件路径（建议为规范绝对路径）。
            code: 当前文件源码。

        Returns:
            True 表示允许进入 LLM 分析；False 表示仅做依赖递归，不进行 LLM 抽取。
        """
        try:
            rel = file_path.resolve().relative_to(self.ets_root.resolve())
            if any((part or "").lower() in self._llm_skip_dirs for part in rel.parts):
                print(f"[RouteStructureAgent] LLM admission skip (dir): {normalize_path(str(file_path))}")
                return False
        except Exception:
            pass

        runtime_code = self._to_runtime_code_for_admission(code)
        ok = self._has_router_hints(runtime_code)
        if not ok:
            print(f"[RouteStructureAgent] LLM admission skip (no actionable router call): {normalize_path(str(file_path))}")
        return ok

    def _split_code_chunks(self, code: str) -> List[str]:
        """
        长文件按行分块，降低单轮上下文过长造成的漏检。

        Args:
            code: 文件完整源码。

        Returns:
            分块后的代码列表；短文件返回单元素列表 [code]。
        """
        lines = (code or "").splitlines()
        total = len(lines)
        trigger = max(1, int(self.config.chunk_trigger_lines))
        if total <= trigger:
            return [code]

        size = max(50, int(self.config.chunk_size_lines))
        overlap = max(0, min(int(self.config.chunk_overlap_lines), size - 1))
        step = max(1, size - overlap)

        chunks: List[str] = []
        i = 0
        while i < total:
            chunk = "\n".join(lines[i : i + size])
            if chunk.strip():
                chunks.append(chunk)
            i += step
        print(
            "[RouteStructureAgent] Long file chunking: "
            f"lines={total}, trigger={trigger}, chunk_size={size}, overlap={overlap}, chunks={len(chunks)}"
        )
        return chunks

    async def _extract_edges_by_llm(
        self,
        *,
        file_path: Path,
        code: str,
        imports: Dict[str, str],
        resolved_map: Dict[str, str],
        main_pages: List[str],
        chain: List[str],
        resolved_files: List[str],
    ) -> List[Dict[str, Any]]:
        """
        主抽取：按分块调用 LLM，并叠加 tool-calling 补解析结果。

        Args:
            file_path: 当前分析文件路径。
            code: 当前文件源码。
            imports: 当前文件提取出的 import 映射（符号 -> 模块路径）。
            resolved_map: import 解析后的文件映射（符号 -> 绝对文件路径）。
            main_pages: main_pages 入口页面列表（去 .ets 后）。
            chain: 当前依赖链，用于提示模型上下文。
            resolved_files: 当前文件可解析到的依赖文件列表。

        Returns:
            当前文件抽取到的边列表（未入库，可能含需二次过滤项）。
        """
        file_key = normalize_path(str(file_path))
        chunks = self._split_code_chunks(code)
        all_edges: List[Dict[str, Any]] = []
        for idx, chunk in enumerate(chunks, start=1):
            if not self._has_router_hints(chunk):
                continue
            if len(chunks) > 1:
                print(f"[RouteStructureAgent] Analyze chunk {idx}/{len(chunks)}: {file_key}")

            user_prompt = build_user_prompt(
                file_path=file_key,
                code=chunk,
                main_pages=main_pages,
                dependency_chain=chain,
                resolved_import_files=resolved_files,
                route_constant_map=self.route_const_resolver.full_map,
            )
            edges: List[Dict[str, Any]] = []
            print(f"[RouteStructureAgent] LLM Reading & analyzing file: {file_key}")
            try:
                msg = await self.llm.ainvoke([("system", SYSTEM_PROMPT), ("user", user_prompt)])
                self._record_token_usage(stage="extract", msg=msg)
                edges = parse_llm_json_list(str(getattr(msg, "content", "") or ""))
            except Exception as ex:
                print(f"[RouteStructureAgent] LLM analyze failed: {ex}")

            supplement_edges = await self.tool_calling_resolver.supplement_edges(
                file_path=file_key,
                imports=imports,
                resolved_imports=resolved_map,
                llm_edges=edges,
            )
            all_edges.extend(edges)
            all_edges.extend(supplement_edges)
        return all_edges

    async def _extract_router_census(
        self,
        *,
        file_path: Path,
        code: str,
        chain: List[str],
        resolved_files: List[str],
    ) -> List[Dict[str, str]]:
        """
        调用点普查：先找出 router 调用证据，为补漏提供锚点。

        Args:
            file_path: 当前分析文件路径。
            code: 当前文件源码。
            chain: 当前依赖链。
            resolved_files: 当前文件可解析依赖文件列表。

        Returns:
            调用点列表。每项包含 call_id/method/line_hint/snippet。
        """
        file_key = normalize_path(str(file_path))
        if not bool(self.config.enable_router_census_probe):
            return []
        if not self._has_router_hints(code):
            return []

        chunks = self._split_code_chunks(code)
        calls: List[Dict[str, str]] = []
        for idx, chunk in enumerate(chunks, start=1):
            if not self._has_router_hints(chunk):
                continue
            user_prompt = build_census_user_prompt(
                file_path=file_key,
                code=chunk,
                chunk_index=idx,
                chunk_total=len(chunks),
                dependency_chain=chain,
                resolved_import_files=resolved_files,
            )
            try:
                msg = await self.llm.ainvoke([("system", CENSUS_SYSTEM_PROMPT), ("user", user_prompt)])
                self._record_token_usage(stage="census", msg=msg)
                rows = parse_llm_json_list(str(getattr(msg, "content", "") or ""))
            except Exception as ex:
                print(f"[RouteStructureAgent] Census failed: {ex}")
                rows = []
            for i, r in enumerate(rows, start=1):
                method = str(r.get("method") or "").strip() or "other_router"
                line_hint = str(r.get("line_hint") or "").strip() or "unknown"
                snippet = str(r.get("snippet") or "").strip()
                call_id = str(r.get("call_id") or "").strip() or f"c{idx}_{i}"
                if not snippet:
                    continue
                calls.append(
                    {
                        "call_id": call_id,
                        "method": method,
                        "line_hint": line_hint,
                        "snippet": snippet,
                    }
                )

        seen = set()
        out: List[Dict[str, str]] = []
        for c in calls:
            k = (c["method"], c["line_hint"], c["snippet"])
            if k in seen:
                continue
            seen.add(k)
            out.append(c)
        return out

    @staticmethod
    def _is_actionable_census_call(call: Dict[str, str]) -> bool:
        """
        过滤掉不应转成 PTG 边的调用（如 back）。

        Args:
            call: census 返回的一条调用记录。

        Returns:
            True 表示该调用可参与补漏；False 表示应忽略。
        """
        method = str(call.get("method") or "").strip().lower()
        snippet = str(call.get("snippet") or "").strip().lower()
        if "back" in method:
            return False
        if "router.back" in snippet or ".back(" in snippet:
            return False
        return True

    @staticmethod
    def _edge_key_for_merge(edge: Dict[str, Any]) -> tuple[str, str, str]:
        """
        构造边去重键：组件类型 + 事件 + 目标页面。

        Args:
            edge: 路由边对象。

        Returns:
            用于集合去重的三元组 key。
        """
        return (
            str(edge.get("component_type") or "__Common__").strip() or "__Common__",
            str(edge.get("event") or "onClick").strip() or "onClick",
            str(edge.get("target") or "").strip(),
        )

    async def _recover_edges_by_census_gap(
        self,
        *,
        file_path: Path,
        code: str,
        imports: Dict[str, str],
        resolved_map: Dict[str, str],
        main_pages: List[str],
        chain: List[str],
        resolved_files: List[str],
        actionable_census_calls: List[Dict[str, str]],
        existing_edges: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        缺口补漏：
        - 当 census 可执行调用数 > 当前抽取边数时触发；
        - 用 call_id、target 合法性、源码弱证据收紧补漏结果；
        - 最终通过去重和 gap 上限控制，避免补漏放大误检。
        """
        file_key = normalize_path(str(file_path))
        if not actionable_census_calls:
            return []
        extracted_edges_count = len(existing_edges or [])
        gap = len(actionable_census_calls) - extracted_edges_count
        if gap <= 0:
            return []
        # 当前策略：仅在“主抽取为 0”时补漏，避免已有边时继续补导致噪声增长。
        if extracted_edges_count != 0:
            return []

        print(
            "[RouteStructureAgent] Coverage retry start: "
            f"calls={len(actionable_census_calls)}, edges={extracted_edges_count}, gap={gap}, file: {file_key}"
        )
        user_prompt = build_coverage_retry_user_prompt(
            file_path=file_key,
            code=code,
            main_pages=main_pages,
            dependency_chain=chain,
            resolved_import_files=resolved_files,
            route_constant_map=self.route_const_resolver.full_map,
            census_calls=actionable_census_calls,
        )
        try:
            msg = await self.llm.ainvoke([("system", COVERAGE_RETRY_SYSTEM_PROMPT), ("user", user_prompt)])
            self._record_token_usage(stage="recover", msg=msg)
            retry_edges = parse_llm_json_list(str(getattr(msg, "content", "") or ""))
        except Exception as ex:
            print(f"[RouteStructureAgent] Coverage retry failed: {ex}")
            retry_edges = []

        actionable_ids = {str(x.get("call_id") or "").strip() for x in actionable_census_calls}
        existing_keys = {self._edge_key_for_merge(x) for x in (existing_edges or [])}
        filtered_retry: List[Dict[str, Any]] = []
        seen = set()
        invalid_targets = 0
        invalid_call_id = 0
        for e in retry_edges:
            call_id = str(e.get("call_id") or "").strip()
            if not call_id or call_id not in actionable_ids:
                invalid_call_id += 1
                continue
            target = str(e.get("target") or "").strip()
            if is_invalid_target(target):
                invalid_targets += 1
                continue
            target_expr = str(e.get("target_expr") or "").strip()
            # 弱证据命中：target_expr 命中源码，或 target 命中源码，或 target 形似页面路径。
            has_evidence = (target_expr and target_expr in code) or (target and target in code) or ("/" in target)
            if not has_evidence:
                continue
            k = self._edge_key_for_merge(e)
            if not k[2] or k in existing_keys or k in seen:
                continue
            seen.add(k)
            filtered_retry.append(e)
        if invalid_targets > 0 or invalid_call_id > 0:
            print(
                "[RouteStructureAgent] Coverage retry filtered: "
                f"file={file_key}, invalid_call_id={invalid_call_id}, invalid_target={invalid_targets}"
            )

        retry_patch = await self.tool_calling_resolver.supplement_edges(
            file_path=file_key,
            imports=imports,
            resolved_imports=resolved_map,
            llm_edges=filtered_retry,
        )
        out: List[Dict[str, Any]] = []
        merged_seen = set(existing_keys)
        for e in [*filtered_retry, *retry_patch]:
            t = str(e.get("target") or "").strip()
            if is_invalid_target(t):
                continue
            k = self._edge_key_for_merge(e)
            if not k[2] or k in merged_seen:
                continue
            merged_seen.add(k)
            out.append(e)
            if len(out) >= gap:
                break
        print(
            "[RouteStructureAgent] Coverage retry done: "
            f"raw={len(retry_edges)}, filtered={len(filtered_retry)}, recovered={len(out)}, gap={gap}, file: {file_key}"
        )
        return out

    async def _analyze_file(
        self,
        *,
        main_page_key: str,
        file_path: Path,
        main_pages: List[str],
        depth: int,
        chain: List[str],
    ) -> None:
        """
        递归分析单个文件，并把合法边写入 memory。

        Args:
            main_page_key: 当前归属的入口页面 key（source_page）。
            file_path: 当前待分析文件路径。
            main_pages: main_pages 列表（去 .ets 后）。
            depth: 当前递归深度。
            chain: 当前依赖链。

        Returns:
            无返回值。副作用：更新 memory / dependency_graph / visited。
        """
        if self._count >= int(self.config.max_files):
            return
        if depth > int(self.config.max_depth):
            return

        try:
            canonical_file = file_path.resolve()
        except Exception:
            canonical_file = Path(normalize_path(str(file_path)))
        fp = normalize_path(str(canonical_file))
        if fp in self._visited:
            return
        self._visited.add(fp)
        self._count += 1

        code = self.reader.read_source_file(str(canonical_file))
        if not code.strip():
            return

        imports = self.import_resolver.extract_imports(code)
        resolved_map = self.import_resolver.resolve_imports_to_files(
            imports=imports,
            current_file_path=str(canonical_file),
        )
        resolved_files = [str(x) for x in resolved_map.values()]
        resolved_files = [f for f in resolved_files if self._is_readable_ets_file(f)]

        self.dependency_graph[fp] = [normalize_path(x) for x in resolved_files]

        # 仅对通过准入门的文件执行 LLM；其余文件只参与 import 递归。
        merged_edges: List[Dict[str, Any]] = []
        if self._is_llm_admissible_file(file_path=canonical_file, code=code):
            census_calls = await self._extract_router_census(
                file_path=canonical_file,
                code=code,
                chain=chain,
                resolved_files=resolved_files,
            )
            actionable_census_calls = [c for c in census_calls if self._is_actionable_census_call(c)]
            print(
                "[RouteStructureAgent] Router census summary: "
                f"total_calls={len(census_calls)}, actionable_calls={len(actionable_census_calls)}, file: {fp}"
            )

            merged_edges = await self._extract_edges_by_llm(
                file_path=canonical_file,
                code=code,
                imports=imports,
                resolved_map=resolved_map,
                main_pages=main_pages,
                chain=chain,
                resolved_files=resolved_files,
            )
            print(
                "[RouteStructureAgent] Coverage probe: "
                f"actionable_calls={len(actionable_census_calls)}, extracted_edges={len(merged_edges)}, file: {fp}"
            )
            recovered_edges = await self._recover_edges_by_census_gap(
                file_path=canonical_file,
                code=code,
                imports=imports,
                resolved_map=resolved_map,
                main_pages=main_pages,
                chain=chain,
                resolved_files=resolved_files,
                actionable_census_calls=actionable_census_calls,
                existing_edges=merged_edges,
            )
            if recovered_edges:
                merged_edges = [*merged_edges, *recovered_edges]
                print(
                    "[RouteStructureAgent] Coverage probe merged: "
                    f"merged_edges={len(merged_edges)}, file: {fp}"
                )

        # 入库前统一做 target 合法性过滤，避免脏边进入最终 PTG。
        invalid_target_dropped = 0
        for e in merged_edges:
            component_type = str(e.get("component_type") or "__Common__")
            event = str(e.get("event") or "onClick")
            raw_target = str(e.get("target") or "").strip()
            target_expr = str(e.get("target_expr") or raw_target).strip()

            target = self.route_const_resolver.resolve_target_by_symbol(
                target=raw_target,
                target_expr=target_expr,
                imports=imports,
                resolved_imports=resolved_map,
            )
            if is_invalid_target(target) or not target:
                invalid_target_dropped += 1
                continue

            if self.memory.add_edge(
                source_page=main_page_key,
                component_type=component_type,
                event=event,
                target=target,
            ):
                print(f"Found route: {main_page_key} -> {target}")
        if invalid_target_dropped > 0:
            print(
                "[RouteStructureAgent] Invalid target dropped: "
                f"dropped={invalid_target_dropped}, merged_edges={len(merged_edges)}, file: {fp}"
            )

        nested = self.import_resolver.find_nested_component_files(
            imports=imports,
            current_file_path=str(canonical_file),
        )
        nested = [nf for nf in nested if self._is_readable_ets_file(nf)]
        next_chain = [*chain, fp]
        for nf in nested:
            await self._analyze_file(
                main_page_key=main_page_key,
                file_path=Path(nf),
                main_pages=main_pages,
                depth=depth + 1,
                chain=next_chain,
            )

    async def run(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        项目入口：遍历 main_pages，执行抽取并保存结果。

        Returns:
            PTG 的 JSON 对象表示（source_page -> edges）。
        """
        main_pages = ProjectReader.load_main_pages(self.config.main_pages_json_path)
        main_pages = [str(x) for x in (main_pages or []) if str(x).strip()]
        main_page_ids = [strip_ets(p) for p in main_pages]

        self._main_page_ids = {p for p in main_page_ids if p}
        self.memory.init_from_main_pages(sorted(self._main_page_ids))
        self.route_const_resolver.build()

        for mp_raw, mp_id in zip(main_pages, main_page_ids):
            if not mp_id:
                continue
            mp_file = self.ets_root / _ensure_ets(mp_raw)
            if not mp_file.exists():
                print(f"[RouteStructureAgent] Main page file not found: {str(mp_file)}")
                continue

            self._visited = set()
            self._count = 0

            await self._analyze_file(
                main_page_key=mp_id,
                file_path=mp_file,
                main_pages=main_page_ids,
                depth=0,
                chain=[mp_id],
            )

        unresolved_summary = self.import_resolver.get_unresolved_imports_summary(top_n=20)
        if unresolved_summary:
            print(
                "[RouteStructureAgent] Unresolved imports summary (top 20): "
                + json.dumps(unresolved_summary, ensure_ascii=False)
            )
        else:
            print("[RouteStructureAgent] Unresolved imports summary: []")

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path(self.config.output_dir) / _safe_dir(self.config.project_name)
        ptg_path = out_dir / f"ptg_route_structure_{stamp}.json"
        self.memory.save_json(str(ptg_path))
        print(f"[RouteStructureAgent] PTG saved: {str(ptg_path)}")
        print(
            "[RouteStructureAgent] Token usage summary: "
            f"calls={self._token_calls}, prompt={self._token_prompt}, "
            f"completion={self._token_completion}, total={self._token_total}"
        )

        return self.memory.to_json_obj()

    def run_sync(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        同步包装，兼容 Windows 事件循环策略。

        Returns:
            PTG 的 JSON 对象表示。
        """
        if sys.platform.startswith("win"):
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            except Exception:
                pass
        return asyncio.run(self.run())
