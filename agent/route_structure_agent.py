from __future__ import annotations

# 路由结构抽取主流程（RouteStructureAgent）：
# 1) 从 main_pages 出发递归读取可达的 .ets 文件；
# 2) 对通过“LLM 准入门”的文件执行多阶段抽取：
#    - census：先统计调用点
#    - trigger_refine：按需做一次跨文件摘要补解析
#    - construct：基于 census 调用点直接构建边
# 3) 做 target 合法性过滤后写入 PTGMemory。

import asyncio
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, TypedDict

from langchain_openai import ChatOpenAI
from llm_usage import extract_token_usage

from agent.memory import PTGMemory
from agent.prompt.route_structure_prompt import (
    CENSUS_SYSTEM_PROMPT,
    COVERAGE_RETRY_SYSTEM_PROMPT,
    TRIGGER_REFINE_SYSTEM_PROMPT,
    build_coverage_retry_user_prompt,
    build_census_user_prompt,
    build_trigger_refine_user_prompt,
)
from agent.tools.import_resolver import ImportResolver
from agent.tools.project_reader import ProjectReader
from agent.tools.route_constant_resolver import RouteConstantResolver
from agent.tools.route_tool_calling import RouteToolCallingResolver
from agent.utils.llm_json import parse_llm_json_list
from agent.utils.route_utils import is_invalid_target, normalize_path, strip_ets
from llm_server import build_chat_model

try:
    from langgraph.graph import END, StateGraph

    _HAS_LANGGRAPH = True
except Exception:
    END = None
    StateGraph = None
    _HAS_LANGGRAPH = False

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
    max_llm_calls: int = 3000
    token_budget_total: int = 0
    llm_call_pause_seconds: float = 2.0


class RouteState(str, Enum):
    """RouteStructureAgent 的状态机状态。"""

    INIT = "INIT"
    DISCOVER_MAIN_PAGE = "DISCOVER_MAIN_PAGE"
    EXPAND_IMPORTS = "EXPAND_IMPORTS"
    ADMISSION_CHECK = "ADMISSION_CHECK"
    ROUTER_CENSUS = "ROUTER_CENSUS"
    TRIGGER_REFINE = "TRIGGER_REFINE"
    EDGE_CONSTRUCT = "EDGE_CONSTRUCT"
    NORMALIZE_AND_FILTER = "NORMALIZE_AND_FILTER"
    WRITE_PTG = "WRITE_PTG"
    FINALIZE = "FINALIZE"


@dataclass
class AgentGoal:
    """Agent 目标与预算约束。"""

    maximize_recall: bool = True
    minimize_hallucination: bool = True
    max_llm_calls: int = 3000
    token_budget_total: int = 0


@dataclass
class StateContext:
    """运行时状态上下文，用于可观测性与回放。"""

    current_state: str = RouteState.INIT.value
    current_main_page: str = ""
    current_file: str = ""
    llm_calls: int = 0
    token_prompt: int = 0
    token_completion: int = 0
    token_total: int = 0
    coverage_calls: int = 0
    constructed_edges: int = 0
    invalid_target_dropped: int = 0


class RouteGraphState(TypedDict, total=False):
    """LangGraph 运行时状态。"""

    main_pages: List[str]
    main_page_ids: List[str]
    main_idx: int
    current_main_page_raw: str
    current_main_page_id: str
    current_main_page_file: str
    skip_current: bool
    done: bool
    ptg: Dict[str, List[Dict[str, Any]]]


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
        self.goal = AgentGoal(
            max_llm_calls=int(self.config.max_llm_calls),
            token_budget_total=int(self.config.token_budget_total),
        )
        self.state_ctx = StateContext()
        self._token_prompt = 0
        self._token_completion = 0
        self._token_total = 0
        self._token_calls = 0

    def _set_state(self, state: RouteState, *, main_page: str = "", file_path: str = "") -> None:
        """状态切换并打印运行日志。"""
        self.state_ctx.current_state = state.value
        if main_page:
            self.state_ctx.current_main_page = main_page
        if file_path:
            self.state_ctx.current_file = normalize_path(file_path)
        print(
            "[RouteStructureAgent] State => "
            f"{self.state_ctx.current_state} | main_page={self.state_ctx.current_main_page or '-'} "
            f"| file={self.state_ctx.current_file or '-'}"
        )

    def _record_decision(self, *, state: RouteState, action: str, detail: Dict[str, Any]) -> None:
        """记录局部自主决策轨迹（用于复盘与论文分析）。"""
        row = {
            "state": state.value,
            "action": action,
            "detail": detail,
        }
        print(
            "[RouteStructureAgent] Decision: "
            + json.dumps(row, ensure_ascii=False)
        )

    def _llm_budget_exhausted(self) -> bool:
        """检查是否触达 LLM 调用预算。"""
        if self.goal.max_llm_calls > 0 and self._token_calls >= self.goal.max_llm_calls:
            return True
        if self.goal.token_budget_total > 0 and self._token_total >= self.goal.token_budget_total:
            return True
        return False

    def _record_token_usage_numbers(self, stage: str, prompt: int, completion: int, total: int) -> None:
        """记录并打印一次 LLM 交互 token。"""
        self._token_calls += 1
        self._token_prompt += int(prompt or 0)
        self._token_completion += int(completion or 0)
        self._token_total += int(total or 0)
        self.state_ctx.llm_calls = self._token_calls
        self.state_ctx.token_prompt = self._token_prompt
        self.state_ctx.token_completion = self._token_completion
        self.state_ctx.token_total = self._token_total
        print(
            f"[RouteStructureAgent] Token usage | {stage}: "
            f"prompt={int(prompt or 0)}, completion={int(completion or 0)}, total={int(total or 0)}"
        )

    def _record_token_usage(self, *, stage: str, msg: Any) -> None:
        """从 LangChain 消息对象提取并记录 token。"""
        prompt, completion, total = extract_token_usage(msg)
        self._record_token_usage_numbers(stage, prompt, completion, total)

    async def _ainvoke_with_state(
        self,
        *,
        stage: str,
        state: RouteState,
        messages: List[tuple[str, str]],
    ) -> Any:
        """带状态与预算检查的统一 LLM 调用入口。"""
        if self._llm_budget_exhausted():
            self._record_decision(
                state=state,
                action="skip_llm_by_budget",
                detail={
                    "max_llm_calls": self.goal.max_llm_calls,
                    "token_budget_total": self.goal.token_budget_total,
                    "llm_calls": self._token_calls,
                    "token_total": self._token_total,
                },
            )
            raise RuntimeError("LLM budget exhausted")
        msg = await self.llm.ainvoke(messages)
        self._record_token_usage(stage=stage, msg=msg)
        pause_sec = max(0.0, float(self.config.llm_call_pause_seconds))
        if pause_sec > 0:
            await asyncio.sleep(pause_sec)
        return msg

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

    @staticmethod
    def _normalize_bool_flag(v: Any) -> bool:
        if isinstance(v, bool):
            return v
        t = str(v or "").strip().lower()
        return t in {"1", "true", "yes", "y"}

    @staticmethod
    def _is_valid_component_hint(v: str) -> bool:
        t = str(v or "").strip()
        if not t or t == "__Common__":
            return False
        low = t.lower()
        bad_prefixes = ("router.", "this.", "console.")
        bad_values = {"onclick", "ontap", "onitemclick", "itembuilder", "builditem", "handleclick"}
        if low in bad_values:
            return False
        if any(low.startswith(x) for x in bad_prefixes):
            return False
        return True

    @staticmethod
    def _is_valid_event_hint(v: str) -> bool:
        t = str(v or "").strip()
        return bool(t) and t.lower() != "unknown"

    def _resolve_component_ref_file(
        self,
        *,
        component_ref_symbol: str,
        imports: Dict[str, str],
        resolved_map: Dict[str, str],
        current_file_path: str,
    ) -> str:
        sym = str(component_ref_symbol or "").strip()
        if not sym:
            return ""
        direct = str(resolved_map.get(sym) or "").strip()
        if direct and self._is_readable_ets_file(direct):
            return direct
        mod = str(imports.get(sym) or "").strip()
        if not mod:
            return ""
        resolved = self.import_resolver.resolve_import_path(
            import_path=mod,
            current_file_path=current_file_path,
            symbol_alias=sym,
        )
        if resolved and self._is_readable_ets_file(resolved):
            return resolved
        return ""

    @staticmethod
    def _normalize_census_snippet(snippet: str) -> str:
        src = str(snippet or "").strip()
        if not src:
            return ""
        src = re.sub(r"\s+", " ", src)
        return src.strip()

    @staticmethod
    def _extract_target_expr_from_census_snippet(snippet: str) -> str:
        src = str(snippet or "").strip()
        if not src:
            return ""
        obj_match = re.search(r"""\b(?:url|uri)\s*:\s*([^,}\n]+)""", src)
        if obj_match:
            return str(obj_match.group(1) or "").strip()
        call_match = re.search(
            r"""\brouter\s*\.\s*(?:pushUrl|replaceUrl|push|replace)\s*\(\s*([^,\)\n]+)""",
            src,
            flags=re.IGNORECASE,
        )
        if call_match:
            return str(call_match.group(1) or "").strip()
        return ""

    def _score_census_call(self, call: Dict[str, str]) -> tuple[int, int, int, int]:
        component_hint = str(call.get("component_hint") or "").strip()
        event_hint = str(call.get("event_hint") or "").strip()
        needs_cross = 1 if self._normalize_bool_flag(call.get("needs_cross_file_resolution")) else 0
        has_component = 1 if self._is_valid_component_hint(component_hint) else 0
        has_event = 1 if self._is_valid_event_hint(event_hint) else 0
        snippet_len = len(self._normalize_census_snippet(str(call.get("snippet") or "")))
        return (has_component, has_event, needs_cross, snippet_len)

    def _normalize_and_dedupe_census_calls(
        self,
        *,
        file_key: str,
        calls: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        merged: Dict[tuple[str, str, str], Dict[str, str]] = {}
        order: List[tuple[str, str, str]] = []
        for idx, call in enumerate(calls, start=1):
            method = str(call.get("method") or "").strip() or "other_router"
            norm_snippet = self._normalize_census_snippet(str(call.get("snippet") or ""))
            target_expr = self._extract_target_expr_from_census_snippet(norm_snippet)
            dedupe_key = (method, target_expr, norm_snippet)
            candidate = dict(call)
            candidate["snippet"] = norm_snippet or str(call.get("snippet") or "").strip()
            prev = merged.get(dedupe_key)
            if prev is None or self._score_census_call(candidate) > self._score_census_call(prev):
                merged[dedupe_key] = candidate
            if dedupe_key not in order:
                order.append(dedupe_key)

        out: List[Dict[str, str]] = []
        for i, key in enumerate(order, start=1):
            row = dict(merged[key])
            digest = hashlib.md5(f"{file_key}|{key[0]}|{key[1]}|{key[2]}".encode("utf-8")).hexdigest()[:10]
            row["call_id"] = f"rc_{i}_{digest}"
            out.append(row)
        if len(out) != len(calls):
            print(
                "[RouteStructureAgent] Census dedupe summary: "
                f"raw={len(calls)}, deduped={len(out)}, file={file_key}"
            )
        return out

    async def _refine_cross_file_census_calls(
        self,
        *,
        file_path: Path,
        code: str,
        imports: Dict[str, str],
        resolved_map: Dict[str, str],
        chain: List[str],
        census_calls: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        file_key = normalize_path(str(file_path))
        traced: List[Dict[str, str]] = []
        for call in census_calls:
            merged = dict(call)
            component_ref_symbol = str(call.get("component_ref_symbol") or "").strip()
            needs_cross = self._normalize_bool_flag(call.get("needs_cross_file_resolution"))
            if not needs_cross or not component_ref_symbol:
                traced.append(merged)
                continue
            component_file = self._resolve_component_ref_file(
                component_ref_symbol=component_ref_symbol,
                imports=imports,
                resolved_map=resolved_map,
                current_file_path=file_key,
            )
            if not component_file:
                traced.append(merged)
                continue
            try:
                component_code = self.reader.read_source_file(component_file)
            except Exception:
                traced.append(merged)
                continue
            if not component_code.strip():
                traced.append(merged)
                continue
            user_prompt = build_trigger_refine_user_prompt(
                file_path=file_key,
                call=merged,
                component_file_path=normalize_path(component_file),
                component_code=component_code,
                dependency_chain=chain,
            )
            try:
                self._set_state(RouteState.TRIGGER_REFINE, file_path=file_key)
                msg = await self._ainvoke_with_state(
                    stage="trigger_refine",
                    state=RouteState.TRIGGER_REFINE,
                    messages=[("system", TRIGGER_REFINE_SYSTEM_PROMPT), ("user", user_prompt)],
                )
                rows = parse_llm_json_list(str(getattr(msg, "content", "") or ""))
            except Exception as ex:
                print(f"[RouteStructureAgent] Trigger refine failed: {ex}")
                rows = []
            row = rows[0] if rows else {}
            refined_component = str(row.get("component_hint") or "").strip()
            refined_event = str(row.get("event_hint") or "").strip()
            resolved = self._normalize_bool_flag(row.get("resolved"))
            if self._is_valid_component_hint(refined_component):
                merged["component_hint"] = refined_component
            if self._is_valid_event_hint(refined_event):
                merged["event_hint"] = refined_event
            if resolved:
                merged["needs_cross_file_resolution"] = False
                merged["resolved"] = True
                merged["resolution_kind"] = "cross_file_refine"
                print(
                    "[RouteStructureAgent] Trigger refine resolved: "
                    f"call_id={str(merged.get('call_id') or '').strip()}, "
                    f"symbol={component_ref_symbol}, "
                    f"component={merged.get('component_hint')}, event={merged.get('event_hint')}"
                )
            else:
                merged["resolved"] = False
                merged["resolution_kind"] = ""
            traced.append(merged)
        for call in traced:
            if "resolved" not in call:
                call["resolved"] = False
            if "resolution_kind" not in call:
                call["resolution_kind"] = ""
        print(
            "[RouteStructureAgent] Trigger refine summary: "
            f"calls={len(traced)}, resolved={sum(1 for x in traced if self._normalize_bool_flag(x.get('resolved')))}, file={file_key}"
        )
        return traced

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
            self._set_state(RouteState.ROUTER_CENSUS, file_path=file_key)
            user_prompt = build_census_user_prompt(
                file_path=file_key,
                code=chunk,
                chunk_index=idx,
                chunk_total=len(chunks),
                dependency_chain=chain,
                resolved_import_files=resolved_files,
            )
            try:
                msg = await self._ainvoke_with_state(
                    stage="census",
                    state=RouteState.ROUTER_CENSUS,
                    messages=[("system", CENSUS_SYSTEM_PROMPT), ("user", user_prompt)],
                )
                rows = parse_llm_json_list(str(getattr(msg, "content", "") or ""))
                print('[RouteStructureAgent] Census rows', rows)
            except Exception as ex:
                print(f"[RouteStructureAgent] Census failed: {ex}")
                rows = []
            for i, r in enumerate(rows, start=1):
                method = str(r.get("method") or "").strip() or "other_router"
                line_hint = str(r.get("line_hint") or "").strip() or "unknown"
                snippet = str(r.get("snippet") or "").strip()
                component_hint = str(r.get("component_hint") or "").strip() or "__Common__"
                event_hint = str(r.get("event_hint") or "").strip() or "onClick"
                needs_cross_file_resolution = self._normalize_bool_flag(r.get("needs_cross_file_resolution"))
                component_ref_symbol = str(r.get("component_ref_symbol") or "").strip()
                callback_ref = str(r.get("callback_ref") or "").strip()
                cross_file_reason = str(r.get("cross_file_reason") or "").strip()
                if not snippet:
                    continue
                calls.append(
                    {
                        "call_id": f"chunk_{idx}_row_{i}",
                        "method": method,
                        "line_hint": line_hint,
                        "snippet": snippet,
                        "component_hint": component_hint,
                        "event_hint": event_hint,
                        "needs_cross_file_resolution": needs_cross_file_resolution,
                        "component_ref_symbol": component_ref_symbol,
                        "callback_ref": callback_ref,
                        "cross_file_reason": cross_file_reason,
                    }
                )
        return self._normalize_and_dedupe_census_calls(file_key=file_key, calls=calls)

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

    async def _construct_edges_from_census(
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
    ) -> List[Dict[str, Any]]:
        """
        基于 census 调用点直接构建边：
        - 仅处理 actionable census calls（已剔除 back）；
        - 用 call_id、target 合法性、源码弱证据收紧构边结果；
        - 结合 tool-calling 做 target_expr 补解析后再去重合并。
        """
        file_key = normalize_path(str(file_path))
        if not actionable_census_calls:
            return []

        print(
            "[RouteStructureAgent] Edge construct start: "
            f"calls={len(actionable_census_calls)}, file: {file_key}"
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
            self._set_state(RouteState.EDGE_CONSTRUCT, file_path=file_key)
            msg = await self._ainvoke_with_state(
                stage="construct",
                state=RouteState.EDGE_CONSTRUCT,
                messages=[("system", COVERAGE_RETRY_SYSTEM_PROMPT), ("user", user_prompt)],
            )
            print('[RouteStructureAgent] Edge construct raw', str(getattr(msg, "content", "") or ""))
            constructed_edges = parse_llm_json_list(str(getattr(msg, "content", "") or ""))
        except Exception as ex:
            print(f"[RouteStructureAgent] Edge construct failed: {ex}")
            constructed_edges = []

        actionable_ids = {str(x.get("call_id") or "").strip() for x in actionable_census_calls}
        prefiltered_edges: List[Dict[str, Any]] = []
        pre_seen = set()
        invalid_targets = 0
        invalid_call_id = 0
        for e in constructed_edges:
            call_id = str(e.get("call_id") or "").strip()
            if not call_id or call_id not in actionable_ids:
                invalid_call_id += 1
                continue
            target = str(e.get("target") or "").strip()
            if is_invalid_target(target):
                invalid_targets += 1
                continue
            k = self._edge_key_for_merge(e)
            if not k[2] or k in pre_seen:
                continue
            pre_seen.add(k)
            prefiltered_edges.append(e)
        if invalid_targets > 0 or invalid_call_id > 0:
            print(
                "[RouteStructureAgent] Edge construct filtered: "
                f"file={file_key}, invalid_call_id={invalid_call_id}, invalid_target={invalid_targets}"
            )

        patched_edges = await self.tool_calling_resolver.supplement_edges(
            file_path=file_key,
            imports=imports,
            resolved_imports=resolved_map,
            llm_edges=prefiltered_edges,
            actionable_census_calls=actionable_census_calls,
        )
        out: List[Dict[str, Any]] = []
        merged_seen = set()
        for e in [*prefiltered_edges, *patched_edges]:
            t = str(e.get("target") or "").strip()
            if is_invalid_target(t):
                continue
            target_expr = str(e.get("target_expr") or "").strip()
            # 弱证据命中：target_expr 命中源码，或 target 命中源码，或 target 形似页面路径。
            has_evidence = (target_expr and target_expr in code) or (t and t in code) or ("/" in t)
            if not has_evidence:
                continue
            k = self._edge_key_for_merge(e)
            if not k[2] or k in merged_seen:
                continue
            merged_seen.add(k)
            out.append(e)
        print(
            "[RouteStructureAgent] Edge construct done: "
            f"raw={len(constructed_edges)}, prefiltered={len(prefiltered_edges)}, "
            f"patched={len(patched_edges)}, constructed={len(out)}, file: {file_key}"
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
        self._set_state(RouteState.EXPAND_IMPORTS, main_page=main_page_key, file_path=fp)

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
        self._set_state(RouteState.ADMISSION_CHECK, main_page=main_page_key, file_path=fp)
        admissible = self._is_llm_admissible_file(file_path=canonical_file, code=code)
        self._record_decision(
            state=RouteState.ADMISSION_CHECK,
            action="llm_admission",
            detail={"admissible": admissible, "file": fp},
        )
        if admissible:
            census_calls = await self._extract_router_census(
                file_path=canonical_file,
                code=code,
                chain=chain,
                resolved_files=resolved_files,
            )
            census_calls = await self._refine_cross_file_census_calls(
                file_path=canonical_file,
                code=code,
                imports=imports,
                resolved_map=resolved_map,
                chain=chain,
                census_calls=census_calls,
            )
            actionable_census_calls = [c for c in census_calls if self._is_actionable_census_call(c)]
            self.state_ctx.coverage_calls += len(actionable_census_calls)
            print(
                "[RouteStructureAgent] Router census summary: "
                f"total_calls={len(census_calls)}, actionable_calls={len(actionable_census_calls)}, file: {fp}"
            )

            merged_edges = await self._construct_edges_from_census(
                file_path=canonical_file,
                code=code,
                imports=imports,
                resolved_map=resolved_map,
                main_pages=main_pages,
                chain=chain,
                resolved_files=resolved_files,
                actionable_census_calls=actionable_census_calls,
            )
            self.state_ctx.constructed_edges += len(merged_edges)

        # 入库前统一做 target 合法性过滤，避免脏边进入最终 PTG。
        self._set_state(RouteState.NORMALIZE_AND_FILTER, main_page=main_page_key, file_path=fp)
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
            self.state_ctx.invalid_target_dropped += invalid_target_dropped
            print(
                "[RouteStructureAgent] Invalid target dropped: "
                f"dropped={invalid_target_dropped}, merged_edges={len(merged_edges)}, file: {fp}"
            )

        self._set_state(RouteState.WRITE_PTG, main_page=main_page_key, file_path=fp)
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

    def _prepare_main_pages(self) -> tuple[List[str], List[str]]:
        """读取 main_pages 并完成运行前初始化。"""
        self._set_state(RouteState.INIT)
        main_pages = ProjectReader.load_main_pages(self.config.main_pages_json_path)
        main_pages = [str(x) for x in (main_pages or []) if str(x).strip()]
        main_page_ids = [strip_ets(p) for p in main_pages]
        self._main_page_ids = {p for p in main_page_ids if p}
        self.memory.init_from_main_pages(sorted(self._main_page_ids))
        self.route_const_resolver.build()
        return main_pages, main_page_ids

    def get_finalize_snapshot(self) -> Dict[str, Any]:
        """提供 workflow 最终落盘所需的汇总信息。"""
        unresolved_summary = self.import_resolver.get_unresolved_imports_summary(top_n=20)
        self._set_state(RouteState.FINALIZE)
        return {
            "unresolved_imports_summary": unresolved_summary,
            "token_usage": {
                "calls": self._token_calls,
                "prompt": self._token_prompt,
                "completion": self._token_completion,
                "total": self._token_total,
            },
            "state_summary": {
                "coverage_calls": self.state_ctx.coverage_calls,
                "constructed_edges": self.state_ctx.constructed_edges,
                "invalid_target_dropped": self.state_ctx.invalid_target_dropped,
            },
        }

    async def _run_legacy(self) -> Dict[str, List[Dict[str, Any]]]:
        """原始顺序编排执行器（LangGraph 不可用时回退）。"""
        main_pages, main_page_ids = self._prepare_main_pages()
        for mp_raw, mp_id in zip(main_pages, main_page_ids):
            if not mp_id:
                continue
            self._set_state(RouteState.DISCOVER_MAIN_PAGE, main_page=mp_id)
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
        return self.memory.to_json_obj()

    async def _graph_node_init(self, _: RouteGraphState) -> RouteGraphState:
        main_pages, main_page_ids = self._prepare_main_pages()
        return {
            "main_pages": main_pages,
            "main_page_ids": main_page_ids,
            "main_idx": 0,
            "done": False,
            "skip_current": False,
        }

    async def _graph_node_discover(self, state: RouteGraphState) -> RouteGraphState:
        main_pages = state.get("main_pages", [])
        main_page_ids = state.get("main_page_ids", [])
        idx = int(state.get("main_idx", 0))
        if idx >= len(main_pages):
            return {"done": True}

        mp_raw = str(main_pages[idx])
        mp_id = str(main_page_ids[idx]) if idx < len(main_page_ids) else ""
        mp_file = self.ets_root / _ensure_ets(mp_raw)
        self._set_state(RouteState.DISCOVER_MAIN_PAGE, main_page=mp_id, file_path=str(mp_file))
        skip_current = (not mp_id) or (not mp_file.exists())
        if not mp_id:
            print(f"[RouteStructureAgent] Empty main page id at index={idx}, skip.")
        elif not mp_file.exists():
            print(f"[RouteStructureAgent] Main page file not found: {str(mp_file)}")
        return {
            "current_main_page_raw": mp_raw,
            "current_main_page_id": mp_id,
            "current_main_page_file": str(mp_file),
            "skip_current": skip_current,
            "done": False,
        }

    async def _graph_node_process(self, state: RouteGraphState) -> RouteGraphState:
        if bool(state.get("skip_current", False)):
            return {}
        mp_id = str(state.get("current_main_page_id", ""))
        mp_file = str(state.get("current_main_page_file", ""))
        main_page_ids = [str(x) for x in (state.get("main_page_ids") or [])]
        if not mp_id or not mp_file:
            return {}

        self._visited = set()
        self._count = 0
        await self._analyze_file(
            main_page_key=mp_id,
            file_path=Path(mp_file),
            main_pages=main_page_ids,
            depth=0,
            chain=[mp_id],
        )
        return {}

    async def _graph_node_advance(self, state: RouteGraphState) -> RouteGraphState:
        idx = int(state.get("main_idx", 0))
        return {"main_idx": idx + 1}

    async def _graph_node_finalize(self, _: RouteGraphState) -> RouteGraphState:
        return {"ptg": self.memory.to_json_obj()}

    def _graph_route_after_discover(self, state: RouteGraphState) -> str:
        if bool(state.get("done", False)):
            return "finalize"
        if bool(state.get("skip_current", False)):
            return "advance"
        return "process"

    def _graph_route_after_advance(self, state: RouteGraphState) -> str:
        idx = int(state.get("main_idx", 0))
        main_pages = state.get("main_pages", []) or []
        return "finalize" if idx >= len(main_pages) else "discover"

    def _build_state_graph(self):
        if not _HAS_LANGGRAPH or StateGraph is None or END is None:
            raise RuntimeError("LangGraph is not available.")
        graph = StateGraph(RouteGraphState)
        graph.add_node("init", self._graph_node_init)
        graph.add_node("discover", self._graph_node_discover)
        graph.add_node("process", self._graph_node_process)
        graph.add_node("advance", self._graph_node_advance)
        graph.add_node("finalize", self._graph_node_finalize)
        graph.set_entry_point("init")
        graph.add_edge("init", "discover")
        graph.add_conditional_edges(
            "discover",
            self._graph_route_after_discover,
            {"process": "process", "advance": "advance", "finalize": "finalize"},
        )
        graph.add_edge("process", "advance")
        graph.add_conditional_edges(
            "advance",
            self._graph_route_after_advance,
            {"discover": "discover", "finalize": "finalize"},
        )
        graph.add_edge("finalize", END)
        return graph.compile()

    async def run(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        项目入口：优先使用 LangGraph 编排；不可用时回退顺序编排。

        Returns:
            PTG 的 JSON 对象表示（source_page -> edges）。
        """
        if _HAS_LANGGRAPH:
            try:
                app = self._build_state_graph()
                out = await app.ainvoke({})
                if isinstance(out, dict) and isinstance(out.get("ptg"), dict):
                    return out.get("ptg") or {}
                return self.memory.to_json_obj()
            except Exception as ex:
                print(f"[RouteStructureAgent] LangGraph run failed, fallback to legacy: {ex}")
        else:
            print("[RouteStructureAgent] LangGraph not installed, use legacy runner.")
        return await self._run_legacy()

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
