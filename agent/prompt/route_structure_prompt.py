from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

_PROMPT_DIR = Path(__file__).resolve().parent


def _read_prompt_md(filename: str) -> str:
    p = _PROMPT_DIR / filename
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError(f"Prompt file is empty: {str(p)}")
    return text


CENSUS_SYSTEM_PROMPT = _read_prompt_md("census_system_prompt.md")
COVERAGE_RETRY_SYSTEM_PROMPT = _read_prompt_md("edge_construct_system_prompt.md")
TRIGGER_REFINE_SYSTEM_PROMPT = _read_prompt_md("trigger_refine_system_prompt.md")


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
        "Extract every route call and the best local trigger clues for each call.\n"
        "If the final trigger owner is not fully visible here, keep unresolved trace clues instead of guessing.\n"
        "When cross-file refinement seems needed, preserve the next component/callback clue if it is visible in this chunk.\n"
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
        "Treat census call trigger hints as the primary source unless the code clearly contradicts them.\n"
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


def build_trigger_refine_user_prompt(
    *,
    file_path: str,
    call: Mapping[str, str],
    component_file_path: str,
    component_code: str,
    dependency_chain: Sequence[str] | None = None,
) -> str:
    chain = [str(x) for x in (dependency_chain or []) if str(x).strip()]
    context_obj = {
        "file_path": file_path,
        "dependency_chain": chain,
        "call": dict(call),
        "component_file_path": component_file_path,
    }
    return (
        "Task: Refine one router census call using the first-pass census summary and the imported component code.\n"
        "Decide the best final component_hint and event_hint from the provided evidence only.\n"
        "Return ONLY a JSON array.\n\n"
        "Context field semantics:\n"
        "- file_path: file where the original route call was found.\n"
        "- dependency_chain: import/component traversal chain from source page to current file.\n"
        "- call: the first-pass census summary for this route call.\n"
        "- component_file_path: imported component file to inspect.\n\n"
        "Context (JSON):\n"
        f"{json.dumps(context_obj, ensure_ascii=False)}\n\n"
        "First-pass route call snippet:\n<route_call_snippet>\n"
        f"{str(call.get('snippet') or '')}\n"
        "</route_call_snippet>\n\n"
        "Source code of imported component file:\n<component_code>\n"
        f"{component_code}\n"
        "</component_code>\n"
    )
