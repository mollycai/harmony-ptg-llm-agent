from __future__ import annotations

import json
from typing import Iterable, Mapping, Sequence


SYSTEM_PROMPT = """Role: You are an expert static-analysis assistant for HarmonyOS ArkTS/ETS projects.

Goal: Given ONE ArkTS/ETS file (and small structured context), extract ALL navigation transitions that eventually lead to a main page.

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
    "target": "string"
  }
]

Field rules:
- component_type: the UI component or trigger (e.g., Button, ListItem, onClick, router.push). Use "__Common__" if trigger is inside a nested component and the exact UI component is unclear.
- event: event name that triggers navigation (e.g., onClick, onTap). Use "unknown" if unclear.
- target:
  - Prefer an actual main page path string (e.g., pages/xxx/DetailPage.ets).
  - If the code uses an identifier like RoutePath.TopicDetailPage, and the Route Constant Map contains it, output the resolved string value.
  - If it cannot be resolved, output the identifier text as-is.
- If there is no navigation, return [].
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