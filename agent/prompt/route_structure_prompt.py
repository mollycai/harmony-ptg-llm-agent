from __future__ import annotations

import json
from typing import Iterable, Mapping, Sequence


SYSTEM_PROMPT = """Role: You are an expert static-analysis assistant for HarmonyOS ArkTS/ETS projects.

Goal: Given ONE ArkTS/ETS file (and small structured context), extract ALL navigation transitions triggered in this file.

Hard requirements:
- Use ONLY evidence from the provided code and provided context.
- Identify explicit and implicit navigation calls (router.push / router.replace / pushUrl / replaceUrl / back / Navigation.* / NavPathStack.* / wrappers).
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
