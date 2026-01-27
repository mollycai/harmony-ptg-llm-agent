from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Sequence

from langchain_core.tools import tool


_IMPORT_RE = re.compile(r"""import\s+(.+?)\s+from\s+(['"])(.+?)\2\s*;?""", re.IGNORECASE)


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/").strip()


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="ignore")


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8", errors="ignore"))


def _resolve_import_to_ets(
    import_path: str, *, current_file_path: str, ets_root: str
) -> Optional[str]:
    ip = _norm(import_path)
    if not ip:
        return None
    if ip.startswith("@") or ip.startswith("ohos:") or ip.startswith("arkui") or ip.startswith("ets/"):
        return None

    cur = Path(current_file_path)
    base = (cur.parent / ip) if (ip.startswith("./") or ip.startswith("../")) else (Path(ets_root) / ip)

    candidates = [
        base,
        base.with_suffix(".ets"),
        base / "index.ets",
        base.with_suffix("") / "index.ets",
    ]
    for c in candidates:
        try:
            if c.exists() and c.is_file() and c.suffix.lower() == ".ets":
                return str(c)
        except Exception:
            continue
    return None


@tool("load_main_pages")
def load_main_pages(main_pages_json_path: str) -> List[str]:
    """Load main pages from HarmonyOS main_pages.json (dict{src/pages} or list)."""
    data = _load_json(main_pages_json_path)
    if isinstance(data, dict):
        if isinstance(data.get("src"), list):
            return [str(x) for x in data["src"] if str(x).strip()]
        if isinstance(data.get("pages"), list):
            return [str(x) for x in data["pages"] if str(x).strip()]
    if isinstance(data, list):
        return [str(x) for x in data if str(x).strip()]
    raise ValueError("Unsupported mainPages.json format.")


@tool("read_source_file")
def read_source_file(file_path: str) -> str:
    """Read a source file as text (utf-8, ignore errors)."""
    return _read_text(file_path)


@tool("extract_imports")
def extract_imports(source_code: str) -> Dict[str, str]:
    """Extract import aliases -> module path from TS/ArkTS source.

    Supports:
    - import Foo from './Foo'
    - import { A, B as C } from './mod'
    - import Foo, { A, B as C } from './mod'
    - import * as NS from './mod'
    """
    code = source_code or ""
    out: Dict[str, str] = {}

    for m in _IMPORT_RE.finditer(code):
        left = (m.group(1) or "").strip()
        mod = (m.group(3) or "").strip()
        if not left or not mod:
            continue

        if left.startswith("*") and " as " in left:
            _, alias = [x.strip() for x in left.split(" as ", 1)]
            if alias:
                out[alias] = mod
            continue

        if "," in left and "{" in left and "}" in left:
            default_part, rest = left.split(",", 1)
            default_alias = default_part.strip()
            if default_alias:
                out[default_alias] = mod
            left = rest.strip()

        if left.startswith("{") and left.endswith("}"):
            inner = left[1:-1].strip()
            parts = [p.strip() for p in inner.split(",") if p.strip()]
            for p in parts:
                if " as " in p:
                    _, alias = [x.strip() for x in p.split(" as ", 1)]
                    if alias:
                        out[alias] = mod
                else:
                    out[p] = mod
            continue

        if " as " in left:
            _, alias = [x.strip() for x in left.split(" as ", 1)]
            if alias:
                out[alias] = mod
            continue

        out[left] = mod

    return out


def _resolve_imports_to_files_impl(
    *,
    imports: Dict[str, str],
    current_file_path: str,
    ets_root: str,
) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for alias, mod in (imports or {}).items():
        if not alias or not mod:
            continue
        resolved = _resolve_import_to_ets(mod, current_file_path=current_file_path, ets_root=ets_root)
        if resolved:
            out[alias] = resolved
    return out


@tool("resolve_imports_to_files")
def resolve_imports_to_files(
    imports: Dict[str, str],
    current_file_path: str,
    ets_root: str,
) -> Dict[str, str]:
    """Resolve import alias -> absolute .ets file path (local imports only)."""
    return _resolve_imports_to_files_impl(imports=imports, current_file_path=current_file_path, ets_root=ets_root)


@tool("find_nested_component_files")
def find_nested_component_files(
    imports: Dict[str, str],
    current_file_path: str,
    ets_root: str,
) -> List[str]:
    """Resolve ALL local imported ETS files from this file (depth traversal is handled by the agent)."""
    resolved_map = _resolve_imports_to_files_impl(
        imports=imports,
        current_file_path=current_file_path,
        ets_root=ets_root,
    )

    out: List[str] = []
    seen: Set[str] = set()
    for _, f in sorted(resolved_map.items(), key=lambda kv: kv[0]):
        k = _norm(f)
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(f)
    return out


@tool("scan_route_constant_files")
def scan_route_constant_files(
    ets_root: str,
    symbols: Sequence[str] = ("RoutePath", "RouterPath", "NavPath", "NavigationPath"),
    max_files: int = 400,
    head_chars: int = 8192,
) -> List[str]:
    """Scan ets_root recursively and return candidate files containing any route-constant symbols.

    Only .ets and .ts files are considered. The scan reads only the first head_chars characters per file.
    """
    root = Path(ets_root)
    if not root.exists():
        return []

    out: List[str] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".ets", ".ts"}:
            continue
        try:
            head = p.read_text(encoding="utf-8", errors="ignore")[: int(head_chars)]
        except Exception:
            continue
        if not head:
            continue
        if any(s in head for s in (symbols or [])):
            out.append(str(p))
            if len(out) >= int(max_files):
                break

    return out


@tool("save_json")
def save_json(obj: Any, output_path: str) -> str:
    """Save obj to output_path as pretty JSON."""
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(p)