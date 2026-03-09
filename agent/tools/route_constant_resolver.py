from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.utils.route_utils import normalize_path, strip_ets

try:
    from tree_sitter import Language, Parser  # type: ignore
    from tree_sitter_typescript import language_typescript  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Language = None  # type: ignore
    Parser = None  # type: ignore
    language_typescript = None  # type: ignore


def _build_ts_parser() -> Optional[Any]:
    """构造 TS/ArkTS AST 解析器。"""
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


class RouteConstantResolver:
    def __init__(
        self,
        *,
        ets_root: str,
        max_files: int = 120,
        max_chars_per_file: int = 40000,
    ) -> None:
        """初始化路由常量解析器。"""
        self.ets_root = Path(ets_root)
        self.max_files = int(max_files)
        self.max_chars_per_file = int(max_chars_per_file)
        self.full_map: Dict[str, str] = {}
        self.short_map: Dict[str, str] = {}
        self._cache: Dict[str, Dict[str, str]] = {}
        self._ts_parser = _build_ts_parser()

    def build(self) -> tuple[Dict[str, str], Dict[str, str]]:
        # 扫描候选常量文件并构建 symbol.member -> page_path 映射
        full_map: Dict[str, str] = {}
        short_map: Dict[str, str] = {}
        short_seen: Dict[str, int] = {}
        if not self.ets_root.exists():
            self.full_map = full_map
            self.short_map = short_map
            return full_map, short_map

        candidates: List[Path] = []
        for p in self.ets_root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in {".ets", ".ts"}:
                continue
            head = self._read_text_limit(p, limit_chars=8192).lower()
            if not head:
                continue
            if any(k in head for k in ("pages/", "router", "route", "urlconstants", "pageconstants")):
                candidates.append(p)
                if len(candidates) >= self.max_files:
                    break

        for f in candidates:
            parsed = self._parse_file_constants(str(f))
            for k, v in parsed.items():
                if "." not in k:
                    continue
                sym, key = k.split(".", 1)
                self._add_const(sym, key, v, full_map, short_map, short_seen)

        self.full_map = full_map
        self.short_map = short_map
        return full_map, short_map

    def resolve_target(self, target: str) -> str:
        """把 target 文本按常量映射解析成页面路径。"""
        t = self._strip_wrappers(target)
        if not t:
            return t

        original = normalize_path(t)
        mapped = self.full_map.get(t)
        if mapped:
            t = mapped
        else:
            sym, key = self._split_symbol_member(t)
            if sym and key:
                mapped2 = self.short_map.get(key)
                if mapped2:
                    t = mapped2
        t = strip_ets(t)
        if t and t != original:
            print(f"[RouteConstantResolver] Resolved target: {original} -> {t}")
        return t

    def resolve_target_by_symbol(
        self,
        *,
        target: str,
        target_expr: str,
        imports: Dict[str, str],
        resolved_imports: Dict[str, str],
    ) -> str:
        # 优先尝试全局常量映射，再按 imports 定位符号定义文件做精确解析
        resolved = self.resolve_target(target)
        if self._looks_like_page_path(resolved):
            return resolved

        expr = self._strip_wrappers(target_expr or target)
        if not expr:
            return resolved

        symbol, key = self._split_symbol_member(expr)
        if not symbol or not key:
            return resolved

        symbol_file = resolved_imports.get(symbol)
        if not symbol_file:
            mod = (imports or {}).get(symbol, "")
            if mod:
                print(f"[RouteConstantResolver] Symbol import unresolved: {symbol} <- {mod}")
            return resolved

        value = self._resolve_from_symbol_file(symbol_file, symbol=symbol, key=key)
        if not value:
            return resolved
        out = strip_ets(normalize_path(value))
        if out:
            print(f"[RouteConstantResolver] Resolved by symbol: {expr} -> {out}")
        return out or resolved

    @staticmethod
    def _strip_wrappers(s: str) -> str:
        """去掉字符串外层引号。"""
        t = (s or "").strip()
        if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
            t = t[1:-1].strip()
        return t

    @staticmethod
    def _looks_like_page_path(target: str) -> bool:
        """判断文本是否像页面路径。"""
        t = strip_ets(normalize_path(target))
        return bool(t) and ("/" in t) and not t.startswith("router.")

    @staticmethod
    def _split_symbol_member(expr: str) -> tuple[str, str]:
        """把 Symbol.Member 拆成 (Symbol, Member)。"""
        parts = (expr or "").split(".", 1)
        if len(parts) != 2:
            return "", ""
        symbol, key = (parts[0] or "").strip(), (parts[1] or "").strip()
        if not symbol or not key:
            return "", ""
        if not symbol.replace("_", "a").isalnum() or not key.replace("_", "a").isalnum():
            return "", ""
        return symbol, key

    def _resolve_from_symbol_file(self, file_path: str, *, symbol: str, key: str) -> str:
        """在符号定义文件中解析 symbol.key 的字符串值。"""
        fp = str(Path(file_path).resolve())
        parsed = self._cache.get(fp)
        if parsed is None:
            parsed = self._parse_file_constants(fp)
            self._cache[fp] = parsed
        return parsed.get(f"{symbol}.{key}", "")

    @staticmethod
    def _read_text_limit(path: Path, *, limit_chars: int) -> str:
        """按字符上限读取文件。"""
        try:
            return path.read_text(encoding="utf-8", errors="ignore")[: max(0, int(limit_chars))]
        except Exception:
            return ""

    @staticmethod
    def _add_const(
        sym: str,
        key: str,
        value: str,
        full_map: Dict[str, str],
        short_map: Dict[str, str],
        short_seen: Dict[str, int],
    ) -> None:
        """写入 full_map/short_map，并维护短键冲突。"""
        full_map[f"{sym}.{key}"] = value
        short_seen[key] = short_seen.get(key, 0) + 1
        if short_seen[key] == 1:
            short_map[key] = value
        else:
            short_map.pop(key, None)

    def _parse_file_constants(self, file_path: str) -> Dict[str, str]:
        """解析单个常量文件，返回 symbol.member -> value。"""
        src = self._read_text_limit(Path(file_path), limit_chars=self.max_chars_per_file)
        if not src:
            return {}
        # AST 优先，正则兜底
        out = self._parse_file_constants_ast(src)
        if out:
            return out
        return self._parse_file_constants_regex(src)

    def _parse_file_constants_ast(self, src: str) -> Dict[str, str]:
        """使用 AST 解析 enum/object/class static 常量。"""
        if self._ts_parser is None:
            return {}
        src_bytes = src.encode("utf-8", errors="ignore")
        try:
            tree = self._ts_parser.parse(src_bytes)
        except Exception:
            return {}
        if tree is None or tree.root_node is None:
            return {}

        out: Dict[str, str] = {}
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            children = getattr(node, "children", None) or []
            stack.extend(reversed(children))

            if node.type == "enum_declaration":
                self._collect_enum_constants(node, src_bytes, out)
            elif node.type in {"lexical_declaration", "variable_statement"}:
                self._collect_object_constants(node, src_bytes, out)
            elif node.type == "class_declaration":
                self._collect_class_constants(node, src_bytes, out)
        return out

    def _collect_enum_constants(self, node: Any, src_bytes: bytes, out: Dict[str, str]) -> None:
        """收集 enum 成员常量。"""
        sym = self._node_symbol_name(node, src_bytes)
        if not sym:
            return
        for child in self._iter_descendants(node):
            if child.type != "enum_assignment":
                continue
            key_node = child.child_by_field_name("name")
            val_node = child.child_by_field_name("value")
            key = self._identifier_text(key_node, src_bytes)
            val = self._string_value(val_node, src_bytes)
            if key and val:
                out[f"{sym}.{key}"] = normalize_path(val)

    def _collect_object_constants(self, node: Any, src_bytes: bytes, out: Dict[str, str]) -> None:
        """收集对象字面量常量。"""
        for decl in self._iter_descendants(node):
            if decl.type != "variable_declarator":
                continue
            sym = self._identifier_text(decl.child_by_field_name("name"), src_bytes)
            value_node = decl.child_by_field_name("value") or decl.child_by_field_name("initializer")
            if not sym or value_node is None:
                continue
            if value_node.type not in {"object", "object_literal"}:
                continue
            for prop in getattr(value_node, "named_children", []) or []:
                if prop.type not in {"pair", "property_assignment"}:
                    continue
                key_node = prop.child_by_field_name("key")
                val_node = prop.child_by_field_name("value")
                key = self._property_key_text(key_node, src_bytes)
                val = self._string_value(val_node, src_bytes)
                if key and val:
                    out[f"{sym}.{key}"] = normalize_path(val)

    def _collect_class_constants(self, node: Any, src_bytes: bytes, out: Dict[str, str]) -> None:
        """收集 class static 字段常量。"""
        sym = self._node_symbol_name(node, src_bytes)
        if not sym:
            return
        for child in self._iter_descendants(node):
            if child.type not in {"public_field_definition", "field_definition"}:
                continue
            if not self._is_static_field(child, src_bytes):
                continue
            key = self._identifier_text(child.child_by_field_name("name"), src_bytes)
            val_node = child.child_by_field_name("value") or child.child_by_field_name("initializer")
            val = self._string_value(val_node, src_bytes)
            if key and val:
                out[f"{sym}.{key}"] = normalize_path(val)

    @staticmethod
    def _iter_descendants(node: Any) -> List[Any]:
        """DFS 获取节点及其所有子孙节点。"""
        out: List[Any] = []
        stack = [node]
        while stack:
            cur = stack.pop()
            out.append(cur)
            children = getattr(cur, "children", None) or []
            stack.extend(reversed(children))
        return out

    def _node_symbol_name(self, node: Any, src_bytes: bytes) -> str:
        """提取声明节点的符号名。"""
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            name = self._identifier_text(name_node, src_bytes)
            if name:
                return name
        for child in getattr(node, "children", None) or []:
            name = self._identifier_text(child, src_bytes)
            if name:
                return name
        return ""

    @staticmethod
    def _identifier_text(node: Any, src_bytes: bytes) -> str:
        """获取节点文本并做基础清理。"""
        if node is None:
            return ""
        t = src_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="ignore").strip()
        if not t:
            return ""
        if t.startswith('"') and t.endswith('"'):
            return t[1:-1].strip()
        if t.startswith("'") and t.endswith("'"):
            return t[1:-1].strip()
        return t

    def _property_key_text(self, node: Any, src_bytes: bytes) -> str:
        """提取对象属性键名。"""
        return self._identifier_text(node, src_bytes)

    @staticmethod
    def _string_value(node: Any, src_bytes: bytes) -> str:
        """提取字符串字面量值。"""
        if node is None:
            return ""
        t = src_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="ignore").strip()
        if len(t) >= 2 and ((t[0] == '"' and t[-1] == '"') or (t[0] == "'" and t[-1] == "'")):
            return t[1:-1].strip()
        return ""

    @staticmethod
    def _is_static_field(node: Any, src_bytes: bytes) -> bool:
        """判断 class 字段是否包含 static 修饰。"""
        for child in getattr(node, "children", None) or []:
            t = src_bytes[child.start_byte : child.end_byte].decode("utf-8", errors="ignore").strip()
            if t == "static":
                return True
        return False

    @staticmethod
    def _parse_file_constants_regex(src: str) -> Dict[str, str]:
        """AST 失败时使用正则兜底解析常量。"""
        out: Dict[str, str] = {}
        enum_entry_re = re.compile(r"\b(\w+)\s*=\s*(['\"])(.+?)\2")
        obj_entry_re = re.compile(r"\b(\w+)\s*:\s*(['\"])(.+?)\2")
        class_static_entry_re = re.compile(r"\bstatic\s+(?:readonly\s+)?(\w+)\s*(?::[^=;]+)?=\s*(['\"])(.+?)\2")

        for m in re.finditer(r"\b(?:export\s+)?enum\s+(\w+)\s*\{([\s\S]*?)\}", src):
            sym, body = m.group(1), m.group(2) or ""
            for em in enum_entry_re.finditer(body):
                out[f"{sym}.{em.group(1)}"] = normalize_path(em.group(3))

        for m in re.finditer(r"\b(?:export\s+)?const\s+(\w+)\s*=\s*\{([\s\S]*?)\}", src):
            sym, body = m.group(1), m.group(2) or ""
            for om in obj_entry_re.finditer(body):
                out[f"{sym}.{om.group(1)}"] = normalize_path(om.group(3))

        for m in re.finditer(r"\b(?:export\s+)?class\s+(\w+)\s*\{([\s\S]*?)\}", src):
            sym, body = m.group(1), m.group(2) or ""
            for cm in class_static_entry_re.finditer(body):
                out[f"{sym}.{cm.group(1)}"] = normalize_path(cm.group(3))
        return out
