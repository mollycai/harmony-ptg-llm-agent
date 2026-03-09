from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from agent.tools.import_project_index import ImportProjectIndex
from agent.tools.project_reader import ProjectReader
from agent.utils.route_utils import normalize_path

try:
    from tree_sitter import Language, Parser  # type: ignore
    from tree_sitter_typescript import language_typescript  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Language = None  # type: ignore
    Parser = None  # type: ignore
    language_typescript = None  # type: ignore


_IMPORT_RE = re.compile(r"""import\s+(.+?)\s+from\s+(['\"])(.+?)\2\s*;?""", re.IGNORECASE | re.DOTALL)
_EXPORT_FROM_RE = re.compile(
    r"""export\s+(type\s+)?(\*|\{[\s\S]*?\})\s+from\s+(['\"])(.+?)\3\s*;?""",
    re.IGNORECASE | re.DOTALL,
)


def _build_ts_parser() -> Optional[Any]:
    """构造 TS/ArkTS AST 解析器，失败时返回 None。"""
    if Parser is None or language_typescript is None:
        return None
    try:
        parser = Parser()
        ts_lang = language_typescript()
        if Language is not None:
            try:
                ts_lang = Language(ts_lang)  # tree-sitter>=0.25: capsule -> Language
            except Exception:
                pass
        if hasattr(parser, "language"):
            parser.language = ts_lang
        else:
            parser.set_language(ts_lang)
        return parser
    except Exception:
        return None


class ImportResolver:
    """导入解析器：提取 import/export，并解析为可分析的 .ets 文件。"""

    def __init__(self, *, reader: ProjectReader, import_alias_map: Optional[Dict[str, str]] = None) -> None:
        """初始化解析器与项目索引。"""
        self.reader = reader
        self.import_alias_map = dict(import_alias_map or {})
        self._project_index = ImportProjectIndex(ets_root=str(reader.ets_root), manual_alias_map=self.import_alias_map)
        self._auto_alias_map = dict(self._project_index.auto_alias_map)
        self._all_alias_map = dict(self._project_index.all_alias_map)
        self._unresolved_log_once: Set[str] = set()
        self._unresolved_stats: Dict[str, Tuple[int, Set[str]]] = {}
        if self._auto_alias_map:
            print("[ImportResolver] Auto alias discovered: " + ", ".join(sorted(self._auto_alias_map.keys())))
        self._ts_parser = _build_ts_parser()

    def extract_imports(self, source_code: str) -> Dict[str, str]:
        """从源码提取导入符号映射：symbol_alias -> module_path。"""
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
        """把导入映射解析成文件映射：symbol_alias -> .ets 文件路径。"""
        out: Dict[str, str] = {}
        for alias, mod in (imports or {}).items():
            if not alias or not mod:
                continue
            resolved = self._resolve_import_to_ets(mod, current_file_path=current_file_path)
            if not resolved:
                resolved = self._resolve_import_by_symbol(
                    symbol_alias=alias,
                    import_path=mod,
                    current_file_path=current_file_path,
                )
            if resolved:
                out[alias] = resolved
            elif self._should_track_unresolved_import(mod):
                self._record_unresolved_import(mod, current_file_path=current_file_path)
        return out

    def resolve_import_path(
        self,
        *,
        import_path: str,
        current_file_path: str,
        symbol_alias: str = "",
    ) -> Optional[str]:
        """解析单个 import_path 到 .ets 文件，可选结合 symbol_alias 做符号反查。"""
        ip = normalize_path(import_path)
        sa = (symbol_alias or "").strip()
        if not ip:
            return None
        resolved = self._resolve_import_to_ets(ip, current_file_path=current_file_path)
        if resolved:
            return resolved
        if sa:
            return self._resolve_import_by_symbol(
                symbol_alias=sa,
                import_path=ip,
                current_file_path=current_file_path,
            )
        return None

    def find_nested_component_files(self, *, imports: Dict[str, str], current_file_path: str) -> List[str]:
        """返回当前文件可递归进入的依赖文件列表（去重）。"""
        resolved_map = self.resolve_imports_to_files(imports=imports, current_file_path=current_file_path)
        out: List[str] = []
        seen = set()
        for _, file_path in sorted(resolved_map.items(), key=lambda kv: kv[0]):
            k = normalize_path(file_path)
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(file_path)
        return out

    def get_unresolved_imports_summary(self, *, top_n: int = 20) -> List[Dict[str, Any]]:
        """获取未解析 import 的统计摘要。"""
        rows: List[Dict[str, Any]] = []
        for ip, (cnt, files) in self._unresolved_stats.items():
            rows.append(
                {
                    "import_path": ip,
                    "count": int(cnt),
                    "files_count": len(files),
                    "sample_files": sorted(list(files))[:3],
                }
            )
        rows.sort(key=lambda x: (-int(x["count"]), str(x["import_path"])))
        return rows[: max(1, int(top_n))]

    @staticmethod
    def _should_track_unresolved_import(import_path: str) -> bool:
        """判断某个 import_path 是否应该纳入未解析统计。"""
        ip = normalize_path(import_path)
        if not ip:
            return False
        if ip.startswith("ohos:") or ip.startswith("arkui") or ip.startswith("ets/"):
            return False
        if ip.startswith("@ohos/"):
            return not ImportProjectIndex.is_system_ohos_import(ip)
        if ip.startswith("@/") or ip.startswith("@entry/") or ip.startswith("@common/"):
            return True
        if ip.startswith("./") or ip.startswith("../"):
            return True
        return False

    def _record_unresolved_import(self, import_path: str, *, current_file_path: str) -> None:
        """记录一次未解析 import（含出现文件）。"""
        ip = normalize_path(import_path)
        fp = normalize_path(current_file_path)
        if not ip:
            return
        cnt, files = self._unresolved_stats.get(ip, (0, set()))
        cnt += 1
        if fp:
            files.add(fp)
        self._unresolved_stats[ip] = (cnt, files)

    def _resolve_import_to_ets(self, import_path: str, *, current_file_path: str) -> Optional[str]:
        """按路径规则直接解析 import 到 .ets 文件。"""
        ip = normalize_path(import_path)
        if not ip:
            return None
        if ip.startswith("ohos:") or ip.startswith("arkui") or ip.startswith("ets/"):
            return None

        cur = Path(current_file_path)
        alias_hit = ""
        matched = None
        tail = ""
        alias_base: Optional[Path] = None
        for prefix in sorted(self._all_alias_map.keys(), key=len, reverse=True):
            if prefix and ip.startswith(prefix):
                matched = prefix
                break

        if matched:
            alias_hit = matched
            tail = ip[len(matched) :].lstrip("/")
            alias_base = Path(self._all_alias_map[matched])
            if tail.startswith("src/main/ets/") and normalize_path(str(alias_base)).endswith("/src/main/ets"):
                tail = tail[len("src/main/ets/") :]
            elif tail == "src/main/ets" and normalize_path(str(alias_base)).endswith("/src/main/ets"):
                tail = ""
            base = alias_base / tail if tail else alias_base
        elif ip.startswith("@/"):
            alias_hit = "@/"
            base = self.reader.ets_root / ip[2:]
        elif ip.startswith("./") or ip.startswith("../"):
            base = cur.parent / ip
        elif ip.startswith("@ohos/"):
            local_mod = self._project_index.resolve_ohos_local_module(ip)
            if local_mod:
                return local_mod
            if ImportProjectIndex.is_system_ohos_import(ip):
                return None
            return None
        elif ip.startswith("@"):
            return None
        else:
            base = self.reader.ets_root / ip

        resolved = ImportProjectIndex.probe_ets_file(base)
        if resolved:
            if alias_hit:
                print(f"[ImportResolver] Alias hit: {alias_hit} | {ip} -> {resolved}")
            return resolved

        # 命中模块目录但没有 index.ets：后续交给符号级解析，不算错误。
        if alias_hit and alias_base is not None:
            module_dir = alias_base / tail if tail else alias_base
            if module_dir.exists() and module_dir.is_dir():
                return None

        if alias_hit:
            log_key = f"{alias_hit}|{ip}"
            if log_key not in self._unresolved_log_once:
                self._unresolved_log_once.add(log_key)
                print(f"[ImportResolver] Alias hit but unresolved: {alias_hit} | {ip}")
        return None

    def _resolve_import_by_symbol(
        self,
        *,
        symbol_alias: str,
        import_path: str,
        current_file_path: str,
    ) -> Optional[str]:
        """按导入符号反查文件：import { Foo } from 'mod' -> Foo 定义文件。"""
        sym = (symbol_alias or "").strip()
        ip = normalize_path(import_path)
        if not sym or not ip or sym.startswith("__reexport"):
            return None

        module_dir = self._project_index.resolve_module_dir(ip, current_file_path=current_file_path)
        if not module_dir:
            return None

        export_map = self._project_index.build_module_export_map(module_dir)
        hit = export_map.get(sym)
        if hit:
            print(f"[ImportResolver] Symbol resolve: {sym} <- {ip} -> {hit}")
            return hit

        # 文件名兜底
        for p in Path(module_dir).rglob("*.ets"):
            if p.stem == sym:
                print(f"[ImportResolver] Symbol fallback by filename: {sym} <- {ip} -> {str(p)}")
                return str(p)
        return None

    def _extract_import_statements_ast(self, source_code: str) -> Optional[List[str]]:
        """用 AST 提取 import/export 语句文本，失败返回 None。"""
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
        """拆分 import 语句为 (左侧符号子句, 模块路径)。"""
        s = (stmt or "").strip().rstrip(";").strip()
        if not s.startswith("import"):
            return "", ""
        m = re.match(r"""^import\s+([\s\S]*?)\s+from\s+(['\"])(.+?)\2$""", s, flags=re.IGNORECASE)
        if m:
            return (m.group(1) or "").strip(), (m.group(3) or "").strip()

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
        """拆分 export ... from 语句为 (左侧符号子句, 模块路径)。"""
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
        """把 import 子句展开并写入 symbol_alias -> module_path。"""
        if not left or not mod:
            return
        if left.startswith("type "):
            left = left[len("type ") :].strip()
        if left.startswith("*") and " as " in left:
            _, alias = [x.strip() for x in left.split(" as ", 1)]
            if alias:
                out[alias] = mod
            return
        if (not left.lstrip().startswith("{")) and "," in left and "{" in left and "}" in left:
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
        """把 export-from 子句展开成可追踪的符号映射。"""
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
        """当 AST 不可用时，使用正则兜底提取 import/export。"""
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
