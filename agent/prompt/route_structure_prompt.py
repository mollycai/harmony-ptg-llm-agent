from __future__ import annotations

import json
from typing import Iterable, Mapping, Sequence

CENSUS_SYSTEM_PROMPT = """Role: You are a route-call census assistant for HarmonyOS ArkTS/ETS projects.

Goal: From the given code, list EVERY router/navigation call occurrence. Do not convert to PTG edges.

Hard requirements:
- Return STRICT JSON array only.
- Do not skip calls. Prefer over-reporting to under-reporting.
- Include only direct evidence from code.
- Do NOT infer PTG edges in this step.
- Keep each snippet short but must include the real invocation (e.g., router.pushUrl(...)).
- For each call, capture trigger context hints for later recovery:
  - nearest trigger owner/component (component_hint)
  - nearest trigger event (event_hint)

Output schema (JSON array):
[
  {
    "call_id": "string",
    "method": "string",
    "line_hint": "string",
    "snippet": "string",
    "component_hint": "string",
    "event_hint": "string"
  }
]

Field rules:
- method: one of pushUrl, replaceUrl, push, replace, back, Navigation, NavPathStack, other_router.
- line_hint: a short hint like "around line 128".
- snippet:
  - short original code snippet containing the call;
  - should also include nearby trigger evidence when available (e.g., .onClick(...), onItemClick(...), callback name).
- call_id: stable id inside this chunk, e.g., c1, c2, c3.
- component_hint:
  - trigger owner candidate / nearest UI component (e.g., Button, Image, ListItem, CommodityList, "__Common__").
  - never output API/method names (e.g., router.pushUrl, this.xxx, console.xxx).
- event_hint:
 	- The event/callback that directly triggers this navigation call.  - should be in onXxx form whenever possible.
  - should be in onXxx form whenever possible.
  - if unclear, use onClick as fallback.
  - never output unknown.
- Do not fabricate line_hint/snippet; if uncertain, still provide best nearby evidence from code text.
"""

COVERAGE_RETRY_SYSTEM_PROMPT = """Role: You are a route edge construction assistant for HarmonyOS ArkTS/ETS projects.

Goal: Given router call census items, construct PTG edges directly from call evidence.

Hard requirements:
- Return STRICT JSON array only.
- For each provided NON-back census call, try to output one edge.
- Prefer resolving target to a page-like destination (e.g., pages/xxx or RouteConst.xxx mapped by context).
- Do not output back-navigation as target.
- If a call only yields runtime values and cannot map to a concrete page-like destination, SKIP that call.
- component_type and event must be evidence-driven, not guessed.

Output schema (JSON array):
[
  {
    "call_id": "string",
    "component_type": "string",
    "event": "string",
    "target": "string",
    "target_expr": "string"
  }
]

Field rules:
- call_id:
  - Must come from input `census_calls`.
  - Do not output edges with unknown/new call_id.
- component_type:
  - Use this priority:
    1) `census_calls.component_hint` if valid
    2) nearest component evidence in source code around the call snippet
    3) "__Common__" fallback
  - must be a component/trigger owner, not API/method/function name.
- event:
  - Use this priority:
    1) `census_calls.event_hint` if valid
    2) nearest event evidence in source code around the call snippet
    3) onClick fallback
  - must be onXxx form.
  - never output unknown.
- target:
  - Must be page-like target only.
  - Forbidden values/forms: "url", "uri", "target", "name", "routeName",
    "router.getParams(...)", "getParams(...)", "params[...]",
    and any back-navigation expression.
- target_expr: original destination expression in code.
- If target violates forbidden forms, do not output that edge.
- If component/event has no evidence and fallback is used, keep edge only when target is clearly page-like.
"""


def build_census_user_prompt(
    *,
    file_path: str,
    code: str,
    chunk_index: int,
    chunk_total: int,
    dependency_chain: Sequence[str] | None = None,
    resolved_import_files: Sequence[str] | None = None,
) -> str:
    chain = [str(x) for x in (dependency_chain or []) if str(x).strip()]
    imports = [str(x) for x in (resolved_import_files or []) if str(x).strip()]
    context_obj = {
        "file_path": file_path,
        "chunk_index": int(chunk_index),
        "chunk_total": int(chunk_total),
        "dependency_chain": chain,
        "resolved_import_files": imports,
    }
    return (
        "Task: Build a router/navigation call census for this code chunk.\n"
        "Include trigger context hints for each call: component_hint and event_hint.\n"
        "Return ONLY a JSON array.\n\n"
        "Context field semantics:\n"
        "- file_path: current file being analyzed.\n"
        "- chunk_index/chunk_total: current chunk position in this file.\n"
        "- dependency_chain: import/component traversal chain from source page to current file.\n"
        "- resolved_import_files: deterministically resolved dependency files for symbol grounding.\n\n"
        "Context (JSON):\n"
        f"{json.dumps(context_obj, ensure_ascii=False)}\n\n"
        "Source code:\n<code>\n"
        f"{code}\n"
        "</code>\n"
    )


def build_coverage_retry_user_prompt(
    *,
    file_path: str,
    code: str,
    main_pages: Iterable[str],
    dependency_chain: Sequence[str] | None = None,
    resolved_import_files: Sequence[str] | None = None,
    route_constant_map: Mapping[str, str] | None = None,
    census_calls: Sequence[Mapping[str, str]] | None = None,
) -> str:
    pages = [_p for _p in (main_pages or []) if str(_p).strip()]
    chain = [str(x) for x in (dependency_chain or []) if str(x).strip()]
    imports = [str(x) for x in (resolved_import_files or []) if str(x).strip()]
    rc_map = dict(route_constant_map or {})
    calls = [dict(x) for x in (census_calls or []) if isinstance(x, Mapping)]

    context_obj = {
        "file_path": file_path,
        "dependency_chain": chain,
        "resolved_import_files": imports,
        "main_pages": pages,
        "route_constant_map": rc_map,
        "census_calls": calls,
    }

    return (
        "Task: Construct navigation edges based on the provided census calls.\n"
        "Return ONLY a JSON array.\n\n"
        "Context field semantics:\n"
        "- file_path: current file being analyzed.\n"
        "- dependency_chain: import/component traversal chain from source page to current file.\n"
        "- resolved_import_files: deterministically resolved dependency files for symbol grounding.\n"
        "- main_pages: allowed page namespace for target validation.\n"
        "- route_constant_map: known route constant -> page path mappings.\n"
        "- census_calls: evidence anchors to construct one edge per actionable call when possible.\n\n"
        "Context (JSON):\n"
        f"{json.dumps(context_obj, ensure_ascii=False)}\n\n"
        "Source code:\n<code>\n"
        f"{code}\n"
        "</code>\n"
    )
