from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/").strip()


def _strip_ets(p: str) -> str:
    t = _norm(p)
    return t[:-4] if t.endswith(".ets") else t


class RouteConstantResolver:
    def __init__(
        self,
        *,
        ets_root: str,
        max_files: int = 120,
        max_chars_per_file: int = 40000,
    ) -> None:
        self.ets_root = Path(ets_root)
        self.max_files = int(max_files)
        self.max_chars_per_file = int(max_chars_per_file)
        self.symbols: Tuple[str, ...] = ("RoutePath", "RouterPath", "NavPath", "NavigationPath")
        self.full_map: Dict[str, str] = {}
        self.short_map: Dict[str, str] = {}

    def build(self) -> tuple[Dict[str, str], Dict[str, str]]:
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
            head = self._read_text_limit(p, limit_chars=8192)
            if not head:
                continue
            if any(s in head for s in self.symbols):
                candidates.append(p)
                if len(candidates) >= self.max_files:
                    break

        enum_entry_re = re.compile(r"\b(\w+)\s*=\s*(['\"])(.+?)\2")
        obj_entry_re = re.compile(r"\b(\w+)\s*:\s*(['\"])(.+?)\2")
        class_static_entry_re = re.compile(r"\bstatic\s+(?:readonly\s+)?(\w+)\s*=\s*(['\"])(.+?)\2")

        for f in candidates:
            src = self._read_text_limit(f, limit_chars=self.max_chars_per_file)
            if not src:
                continue
            for sym in self.symbols:
                if sym not in src:
                    continue
                for m in re.finditer(rf"\b(?:export\s+)?enum\s+{re.escape(sym)}\s*\{{([\s\S]*?)\}}", src):
                    body = m.group(1) or ""
                    for em in enum_entry_re.finditer(body):
                        self._add_const(sym, em.group(1), _norm(em.group(3)), full_map, short_map, short_seen)
                for m in re.finditer(rf"\b(?:export\s+)?const\s+{re.escape(sym)}\s*=\s*\{{([\s\S]*?)\}}", src):
                    body = m.group(1) or ""
                    for om in obj_entry_re.finditer(body):
                        self._add_const(sym, om.group(1), _norm(om.group(3)), full_map, short_map, short_seen)
                for m in re.finditer(rf"\b(?:export\s+)?class\s+{re.escape(sym)}\s*\{{([\s\S]*?)\}}", src):
                    body = m.group(1) or ""
                    for cm in class_static_entry_re.finditer(body):
                        self._add_const(sym, cm.group(1), _norm(cm.group(3)), full_map, short_map, short_seen)

        self.full_map = full_map
        self.short_map = short_map
        return full_map, short_map

    def resolve_target(self, target: str) -> str:
        t = (target or "").strip()
        if not t:
            return t
        if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
            t = t[1:-1].strip()
        original = _norm(t)
        mapped = self.full_map.get(t)
        if mapped:
            t = mapped
        else:
            m = re.fullmatch(r"(\w+)\.(\w+)", t)
            if m:
                mapped2 = self.short_map.get(m.group(2))
                if mapped2:
                    t = mapped2
        t = _strip_ets(t)
        if t and t != original:
            print(f"[RouteConstantResolver] Resolved target: {original} -> {t}")
        return t

    @staticmethod
    def _read_text_limit(path: Path, *, limit_chars: int) -> str:
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
        full_map[f"{sym}.{key}"] = value
        short_seen[key] = short_seen.get(key, 0) + 1
        if short_seen[key] == 1:
            short_map[key] = value
        else:
            short_map.pop(key, None)
