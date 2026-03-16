from __future__ import annotations

import json
from typing import Iterable, Mapping, Sequence


SYSTEM_PROMPT = """Role: You are an expert static-analysis assistant for HarmonyOS ArkTS/ETS projects.

Goal: Given ONE ArkTS/ETS file (and small structured context), extract ALL navigation transitions triggered in this file.

Hard requirements:
- Use ONLY evidence from the provided code and provided context.
- Identify explicit and implicit navigation calls (e.g., router.push / router.replace / pushUrl / replaceUrl / Navigation.* / NavPathStack.* / wrappers).
- Resolve route-constant identifiers when possible, using the provided Route Constant Map.
- Return STRICT JSON only (no markdown, no code fences, no extra text).

Output schema (JSON array):
[
  {
    "component_type": "string",
    "event": "string",
    "target": "string",
    "target_expr": "string"
  }
]

Field rules:
- component_type:
  - Must be a UI component or trigger owner name (e.g., Button, ListItem, Image, CommodityList, "__Common__").
  - Do NOT output API or function names as component_type (e.g., router.pushUrl, router.push, this.xxx, console.xxx).
- event:
  - Must be an event name in the form onXxx.
  - Never output "unknown".
  - If the event cannot be confidently identified, use "onClick" as the default fallback.
- target:
  - Prefer an actual main page path string (e.g., pages/xxx/DetailPage.ets).
  - If the code uses an identifier like RoutePath.TopicDetailPage, and the Route Constant Map contains it, output the resolved string value.
  - If it cannot be resolved, output the identifier text as-is.
  - NEVER output back-navigation expression as target (e.g., router.back(), back()).
  - NEVER output "unknown" as target.
- target_expr:
  - The original expression in code used as navigation destination (e.g., RoutePath.TopicDetailPage, item.url, "pages/Index").
  - If target is a direct string literal, target_expr can be the same value.
- For back navigation without explicit destination, return [] for that call.
- If there is no navigation, return [].
- Before final output, self-check every edge:
  - component_type is not an API/method name.
  - event matches onXxx; if uncertain, set event to onClick.
  - target is not a back-navigation expression and not "unknown".
"""

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
  - nearest UI component / trigger owner candidate (e.g., Button, Image, ListItem, CommodityList, "__Common__").
  - never output API/method names (e.g., router.pushUrl, this.xxx, console.xxx).
- event_hint:
  - should be in onXxx form whenever possible.
  - if unclear, use onClick as fallback.
  - never output unknown.
- Do not fabricate line_hint/snippet; if uncertain, still provide best nearby evidence from code text.
"""

COVERAGE_RETRY_SYSTEM_PROMPT = """Role: You are a route edge recovery assistant for HarmonyOS ArkTS/ETS projects.

Goal: Given router call census items that may have been missed, recover PTG edges.

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


def build_user_prompt(
    *,
    file_path: str,
    code: str,
    main_pages: Iterable[str],
    dependency_chain: Sequence[str] | None = None,
    resolved_import_files: Sequence[str] | None = None,
    route_constant_map: Mapping[str, str] | None = None,
) -> str:
    pages = [_p for _p in (main_pages or []) if str(_p).strip()]
    chain = [str(x) for x in (dependency_chain or []) if str(x).strip()]
    imports = [str(x) for x in (resolved_import_files or []) if str(x).strip()]
    rc_map = dict(route_constant_map or {})

    context_obj = {
        "file_path": file_path,
        "dependency_chain": chain,
        "resolved_import_files": imports,
        "main_pages": pages,
        "route_constant_map": rc_map,
    }

    return (
        "Task: Extract navigation transitions from the given ArkTS/ETS file.\n"
        "Return ONLY a JSON array.\n\n"
        "Context (JSON):\n"
        f"{json.dumps(context_obj, ensure_ascii=False)}\n\n"
        "Source code:\n<code>\n"
        f"{code}\n"
        "</code>\n"
    )


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
        "Task: Recover missing navigation edges based on the provided census calls.\n"
        "Return ONLY a JSON array.\n\n"
        "Context (JSON):\n"
        f"{json.dumps(context_obj, ensure_ascii=False)}\n\n"
        "Source code:\n<code>\n"
        f"{code}\n"
        "</code>\n"
    )
