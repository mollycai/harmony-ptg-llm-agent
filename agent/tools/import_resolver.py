from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.tools.project_reader import ProjectReader

try:
    from tree_sitter import Parser  # type: ignore
    from tree_sitter_typescript import language_typescript  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Parser = None  # type: ignore
    language_typescript = None  # type: ignore


_IMPORT_RE = re.compile(r"""import\s+(.+?)\s+from\s+(['"])(.+?)\2\s*;?""", re.IGNORECASE | re.DOTALL)
_EXPORT_FROM_RE = re.compile(
    r"""export\s+(type\s+)?(\*|\{[\s\S]*?\})\s+from\s+(['"])(.+?)\3\s*;?""",
    re.IGNORECASE | re.DOTALL,
)


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/").strip()


def _build_ts_parser() -> Optional[Any]:
    if Parser is None or language_typescript is None:
        return None
    try:
        parser = Parser()
        ts_lang = language_typescript()
        if hasattr(parser, "language"):
            parser.language = ts_lang
        else:
            parser.set_language(ts_lang)
        return parser
    except Exception:
        return None


class ImportResolver:
    def __init__(self, *, reader: ProjectReader, import_alias_map: Optional[Dict[str, str]] = None) -> None:
        self.reader = reader
        self.import_alias_map = dict(import_alias_map or {})
        self._ts_parser = _build_ts_parser()

    def extract_imports(self, source_code: str) -> Dict[str, str]:
        code = source_code or ""
        statements = self._extract_import_statements_ast(code)
        if statements is None:
            return self._extract_imports_regex(code)

        out: Dict[str, str] = {}
        seq = [0]
        for stmt in statements:
            left, mod = self._split_import_from_clause(stmt)
            if mod:
                self._apply_import_clause(left, mod, out)
                continue
            left, mod = self._split_export_from_clause(stmt)
            if mod:
                self._apply_export_clause(left, mod, out, seq=seq)
        return out

    def resolve_imports_to_files(self, *, imports: Dict[str, str], current_file_path: str) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for alias, mod in (imports or {}).items():
            if not alias or not mod:
                continue
            resolved = self._resolve_import_to_ets(mod, current_file_path=current_file_path)
            if resolved and self.reader.should_explore_file(resolved):
                out[alias] = resolved
        return out

    def find_nested_component_files(self, *, imports: Dict[str, str], current_file_path: str) -> List[str]:
        resolved_map = self.resolve_imports_to_files(imports=imports, current_file_path=current_file_path)
        out: List[str] = []
        seen = set()
        for _, file_path in sorted(resolved_map.items(), key=lambda kv: kv[0]):
            k = _norm(file_path)
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(file_path)
        return out

    def _extract_import_statements_ast(self, source_code: str) -> Optional[List[str]]:
        if self._ts_parser is None:
            return None
        src_bytes = (source_code or "").encode("utf-8", errors="ignore")
        try:
            tree = self._ts_parser.parse(src_bytes)
        except Exception:
            return None
        if tree is None or tree.root_node is None:
            return None

        statements: List[str] = []
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            if node.type in {"import_statement", "export_statement"}:
                statements.append(src_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="ignore"))
                continue
            children = getattr(node, "children", None) or []
            stack.extend(reversed(children))
        return statements

    @staticmethod
    def _split_import_from_clause(stmt: str) -> tuple[str, str]:
        s = (stmt or "").strip().rstrip(";").strip()
        if not s.startswith("import"):
            return "", ""
        body = s[len("import") :].strip()
        if not body:
            return "", ""

        if (body.startswith('"') and body.endswith('"')) or (body.startswith("'") and body.endswith("'")):
            return "", body[1:-1].strip()

        idx = body.rfind(" from ")
        if idx < 0:
            return "", ""
        left = body[:idx].strip()
        right = body[idx + len(" from ") :].strip()
        if len(right) >= 2 and right[0] in {"'", '"'} and right[-1] == right[0]:
            return left, right[1:-1].strip()
        return left, ""

    @staticmethod
    def _split_export_from_clause(stmt: str) -> tuple[str, str]:
        s = (stmt or "").strip().rstrip(";").strip()
        if not s.startswith("export"):
            return "", ""
        m = _EXPORT_FROM_RE.search(s)
        if not m:
            return "", ""
        left = (m.group(2) or "").strip()
        if (m.group(1) or "").strip():
            left = f"type {left}"
        mod = (m.group(4) or "").strip()
        return left, mod

    @staticmethod
    def _apply_import_clause(left: str, mod: str, out: Dict[str, str]) -> None:
        if not left or not mod:
            return
        if left.startswith("type "):
            left = left[len("type ") :].strip()
        if left.startswith("*") and " as " in left:
            _, alias = [x.strip() for x in left.split(" as ", 1)]
            if alias:
                out[alias] = mod
            return
        if "," in left and "{" in left and "}" in left:
            default_part, rest = left.split(",", 1)
            default_alias = default_part.strip()
            if default_alias and default_alias != "type":
                out[default_alias] = mod
            left = rest.strip()
        if left.startswith("{") and left.endswith("}"):
            inner = left[1:-1].strip()
            parts = [p.strip() for p in inner.split(",") if p.strip()]
            for p in parts:
                if p.startswith("type "):
                    p = p[len("type ") :].strip()
                if " as " in p:
                    _, alias = [x.strip() for x in p.split(" as ", 1)]
                    if alias:
                        out[alias] = mod
                else:
                    out[p] = mod
            return
        if " as " in left:
            _, alias = [x.strip() for x in left.split(" as ", 1)]
            if alias:
                out[alias] = mod
            return
        out[left] = mod

    @staticmethod
    def _apply_export_clause(left: str, mod: str, out: Dict[str, str], *, seq: List[int]) -> None:
        if not left or not mod:
            return
        l = left.strip()
        if l.startswith("type "):
            l = l[len("type ") :].strip()
        if l.startswith("*"):
            key = f"__reexport_all__{seq[0]}"
            seq[0] += 1
            out[key] = mod
            return
        if l.startswith("{") and l.endswith("}"):
            inner = l[1:-1].strip()
            parts = [p.strip() for p in inner.split(",") if p.strip()]
            if not parts:
                key = f"__reexport_empty__{seq[0]}"
                seq[0] += 1
                out[key] = mod
                return
            for p in parts:
                if p.startswith("type "):
                    p = p[len("type ") :].strip()
                if " as " in p:
                    _, alias = [x.strip() for x in p.split(" as ", 1)]
                else:
                    alias = p.strip()
                if alias:
                    out[f"__reexport__{alias}"] = mod
            return
        key = f"__reexport__{seq[0]}"
        seq[0] += 1
        out[key] = mod

    def _extract_imports_regex(self, code: str) -> Dict[str, str]:
        out: Dict[str, str] = {}
        seq = [0]
        for m in _IMPORT_RE.finditer(code or ""):
            left = (m.group(1) or "").strip()
            mod = (m.group(3) or "").strip()
            self._apply_import_clause(left, mod, out)
        for m in _EXPORT_FROM_RE.finditer(code or ""):
            left = (m.group(2) or "").strip()
            if (m.group(1) or "").strip():
                left = f"type {left}"
            mod = (m.group(4) or "").strip()
            self._apply_export_clause(left, mod, out, seq=seq)
        return out

    def _resolve_import_to_ets(self, import_path: str, *, current_file_path: str) -> Optional[str]:
        ip = _norm(import_path)
        if not ip:
            return None
        if ip.startswith("ohos:") or ip.startswith("arkui") or ip.startswith("ets/"):
            return None

        cur = Path(current_file_path)
        alias_hit = ""
        matched = None
        for prefix in sorted(self.import_alias_map.keys(), key=len, reverse=True):
            if prefix and ip.startswith(prefix):
                matched = prefix
                break

        if matched:
            alias_hit = matched
            tail = ip[len(matched) :].lstrip("/")
            base = Path(self.import_alias_map[matched]) / tail
        elif ip.startswith("@/"):
            alias_hit = "@/"
            base = self.reader.ets_root / ip[2:]
        elif ip.startswith("./") or ip.startswith("../"):
            base = cur.parent / ip
        elif ip.startswith("@"):
            return None
        else:
            base = self.reader.ets_root / ip

        candidates = [
            base,
            base.with_suffix(".ets"),
            base / "index.ets",
            base.with_suffix("") / "index.ets",
        ]
        for c in candidates:
            try:
                if c.exists() and c.is_file() and c.suffix.lower() == ".ets":
                    if alias_hit:
                        print(f"[ImportResolver] Alias hit: {alias_hit} | {ip} -> {str(c)}")
                    return str(c)
            except Exception:
                continue

        if alias_hit:
            print(f"[ImportResolver] Alias hit but unresolved: {alias_hit} | {ip}")
        return None
