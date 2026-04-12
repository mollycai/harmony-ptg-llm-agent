from __future__ import annotations
import json
import re
from typing import Any, Callable, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from llm_usage import extract_token_usage

from agent.tools.import_resolver import ImportResolver
from agent.tools.route_constant_resolver import RouteConstantResolver
from agent.utils.llm_json import parse_llm_json_list
from agent.utils.route_utils import is_invalid_target, normalize_path, strip_ets


def target_looks_resolved(target: str) -> bool:
    """判断 target 是否已被解析为有效页面路径。"""
    t = normalize_path(strip_ets(target or ""))
    return bool(t) and ("/" in t) and (not is_invalid_target(t))


class RouteToolCallingResolver:
    """对 LLM 初次抽取的未解析边执行一次工具调用补解析。"""

    def __init__(
        self,
        *,
        llm: ChatOpenAI,
        import_resolver: ImportResolver,
        route_const_resolver: RouteConstantResolver,
        token_reporter: Optional[Callable[[str, int, int, int], None]] = None,
    ) -> None:
        self.llm = llm
        self.import_resolver = import_resolver
        self.route_const_resolver = route_const_resolver
        self._token_reporter = token_reporter

    def _report_usage(self, *, stage: str, msg: Any) -> None:
        """上报本次 LLM 交互 token。"""
        p, c, t = extract_token_usage(msg)
        if p <= 0 and c <= 0 and t <= 0:
            return
        if self._token_reporter is not None:
            self._token_reporter(stage, p, c, t)
        else:
            print(f"[RouteStructureAgent] Token usage | {stage}: prompt={p}, completion={c}, total={t}")

    async def supplement_edges(
        self,
        *,
        file_path: str,
        imports: Dict[str, str],
        resolved_imports: Dict[str, str],
        llm_edges: List[Dict[str, Any]],
        actionable_census_calls: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, Any]]:
        seeded_edges = self._build_seed_edges_from_census(actionable_census_calls or [])
        candidate_edges = [*(llm_edges or []), *seeded_edges]

        unresolved: List[Dict[str, Any]] = []
        resolved_directly: List[Dict[str, Any]] = []
        for e in candidate_edges:
            raw_target = str(e.get("target") or "").strip()
            target_expr = str(e.get("target_expr") or raw_target).strip()
            resolved = self.route_const_resolver.resolve_target_by_symbol(
                target=raw_target,
                target_expr=target_expr,
                imports=imports,
                resolved_imports=resolved_imports,
            )
            if target_looks_resolved(resolved):
                resolved_directly.append({**e, "target": resolved})
                continue
            if not target_expr:
                continue
            unresolved.append(
                {
                    "call_id": str(e.get("call_id") or "").strip(),
                    "component_type": str(e.get("component_type") or "unknown"),
                    "event": str(e.get("event") or "onClick"),
                    "target": raw_target,
                    "target_expr": target_expr,
                }
            )

        if not unresolved:
            print(
                "[RouteStructureAgent] Tool-calling supplement skipped: "
                f"no unresolved edges, resolved={len(resolved_directly)}"
            )
            return resolved_directly

        print(f"[RouteStructureAgent] Tool-calling supplement start: unresolved_edges={len(unresolved)}")
        tools = self._build_tools(file_path=file_path, imports=imports, resolved_imports=resolved_imports)
        tool_llm = self.llm.bind_tools(tools)

        messages: List[Any] = [
            SystemMessage(
                content=(
                    "You are a route-repair assistant.\n"
                    "Given unresolved navigation edges, call tools to resolve import paths and target expressions.\n"
                    "Return ONLY a JSON array, where each item has: component_type, event, target, target_expr."
                )
            ),
            HumanMessage(
                content=json.dumps(
                    {
                        "file_path": file_path,
                        "imports": imports,
                        "resolved_imports": resolved_imports,
                        "unresolved_edges": unresolved,
                    },
                    ensure_ascii=False,
                )
            ),
        ]

        final_text = "[]"
        for _ in range(4):
            ai_msg = await tool_llm.ainvoke(messages)
            self._report_usage(stage="tool_calling", msg=ai_msg)
            if not isinstance(ai_msg, AIMessage):
                final_text = str(getattr(ai_msg, "content", "") or "[]")
                break
            if not ai_msg.tool_calls:
                final_text = str(ai_msg.content or "[]")
                break

            messages.append(ai_msg)
            for tc in ai_msg.tool_calls:
                out = self._run_tool_call(
                    tc=tc,
                    file_path=file_path,
                    imports=imports,
                    resolved_imports=resolved_imports,
                )
                messages.append(ToolMessage(content=str(out), tool_call_id=str(tc.get("id") or "")))

        patched = parse_llm_json_list(final_text)
        if not patched:
            print("[RouteStructureAgent] Tool-calling supplement result is empty.")
        merged = [*resolved_directly, *patched]
        print(
            "[RouteStructureAgent] Tool-calling supplement done: "
            f"seeded={len(seeded_edges)}, resolved={len(resolved_directly)}, "
            f"patched={len(patched)}, total={len(merged)}"
        )
        return merged

    def _build_tools(
        self,
        *,
        file_path: str,
        imports: Dict[str, str],
        resolved_imports: Dict[str, str],
    ) -> List[StructuredTool]:
        """构造供 LLM 调用的最小工具集。"""

        def _tool_resolve_import_path(module_path: str, symbol_alias: str = "") -> str:
            return self._resolve_import_path(
                module_path=module_path,
                symbol_alias=symbol_alias,
                file_path=file_path,
            )

        def _tool_resolve_target_expr(target_expr: str) -> str:
            return self._resolve_target_expr(
                target_expr=target_expr,
                imports=imports,
                resolved_imports=resolved_imports,
            )

        return [
            StructuredTool.from_function(
                func=_tool_resolve_import_path,
                name="resolve_import_path",
                description="Resolve an import path or symbol alias to an absolute .ets file path.",
            ),
            StructuredTool.from_function(
                func=_tool_resolve_target_expr,
                name="resolve_target_expr",
                description="Resolve a route target_expr into a page path (for example, pages/xx).",
            ),
        ]

    def _resolve_import_path(self, *, module_path: str, symbol_alias: str, file_path: str) -> str:
        """工具实现：解析 import 到实际文件。"""
        mp = normalize_path(module_path)
        sa = (symbol_alias or "").strip()
        if not mp:
            return ""
        try:
            out = self.import_resolver.resolve_import_path(
                import_path=mp,
                current_file_path=file_path,
                symbol_alias=sa,
            )
            return str(out or "")
        except Exception:
            return ""

    def _resolve_target_expr(
        self,
        *,
        target_expr: str,
        imports: Dict[str, str],
        resolved_imports: Dict[str, str],
    ) -> str:
        """工具实现：解析 target_expr 到页面路径。"""
        te = (target_expr or "").strip()
        if not te:
            return ""
        try:
            out = self.route_const_resolver.resolve_target_by_symbol(
                target=te,
                target_expr=te,
                imports=imports,
                resolved_imports=resolved_imports,
            )
            return str(out or "")
        except Exception:
            return ""

    @staticmethod
    def _extract_target_expr_from_snippet(snippet: str) -> str:
        src = str(snippet or "").strip()
        if not src:
            return ""

        obj_match = re.search(r"""\b(?:url|uri)\s*:\s*([^,}\n]+)""", src)
        if obj_match:
            return str(obj_match.group(1) or "").strip()

        call_match = re.search(
            r"""\brouter\s*\.\s*(?:push|replace)\s*\(\s*([^,\)\n]+)""",
            src,
            flags=re.IGNORECASE,
        )
        if call_match:
            return str(call_match.group(1) or "").strip()
        return ""

    def _build_seed_edges_from_census(self, actionable_census_calls: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        seeds: List[Dict[str, Any]] = []
        for call in actionable_census_calls:
            target_expr = self._extract_target_expr_from_snippet(str(call.get("snippet") or ""))
            if not target_expr:
                continue
            seeds.append(
                {
                    "call_id": str(call.get("call_id") or "").strip(),
                    "component_type": str(call.get("component_hint") or "__Common__").strip() or "__Common__",
                    "event": str(call.get("event_hint") or "onClick").strip() or "onClick",
                    "target": self.route_const_resolver._strip_wrappers(target_expr),
                    "target_expr": target_expr,
                }
            )
        if seeds:
            print(f"[RouteStructureAgent] Seed edges built from census: count={len(seeds)}")
        return seeds

    def _run_tool_call(
        self,
        *,
        tc: Dict[str, Any],
        file_path: str,
        imports: Dict[str, str],
        resolved_imports: Dict[str, str],
    ) -> str:
        """执行一次模型工具调用。"""
        name = str(tc.get("name") or "")
        args = tc.get("args") or {}
        try:
            if name == "resolve_import_path":
                return self._resolve_import_path(
                    module_path=str(args.get("module_path") or ""),
                    symbol_alias=str(args.get("symbol_alias") or ""),
                    file_path=file_path,
                )
            if name == "resolve_target_expr":
                return self._resolve_target_expr(
                    target_expr=str(args.get("target_expr") or ""),
                    imports=imports,
                    resolved_imports=resolved_imports,
                )
        except Exception:
            return ""
        return ""
