from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/").strip()


class ProjectReader:
    def __init__(self, *, ets_root: str, skip_dir_names: Optional[Iterable[str]] = None) -> None:
        self.ets_root = Path(ets_root)
        skip = set(skip_dir_names or {"http", "https", "util", "utils", "constant", "constants"})
        self._skip_dir_names: Set[str] = {str(x).lower() for x in skip if str(x).strip()}

    @staticmethod
    def load_main_pages(main_pages_json_path: str) -> List[str]:
        data: Any = json.loads(Path(main_pages_json_path).read_text(encoding="utf-8", errors="ignore"))
        if isinstance(data, dict):
            if isinstance(data.get("src"), list):
                return [str(x) for x in data["src"] if str(x).strip()]
            if isinstance(data.get("pages"), list):
                return [str(x) for x in data["pages"] if str(x).strip()]
        if isinstance(data, list):
            return [str(x) for x in data if str(x).strip()]
        raise ValueError("Unsupported mainPages.json format.")

    @staticmethod
    def read_source_file(file_path: str) -> str:
        return Path(file_path).read_text(encoding="utf-8", errors="ignore")

    def should_explore_file(self, file_path: str) -> bool:
        fp = _norm(file_path)
        if not fp:
            return False
        try:
            rel = Path(fp).resolve().relative_to(self.ets_root.resolve())
        except Exception:
            return False
        return not any((part or "").lower() in self._skip_dir_names for part in rel.parts)

    def list_source_files(
        self,
        *,
        suffixes: Optional[Set[str]] = None,
        max_files: Optional[int] = None,
    ) -> List[str]:
        exts = suffixes or {".ets", ".ts"}
        out: List[str] = []
        if not self.ets_root.exists():
            return out
        for p in self.ets_root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in exts:
                continue
            out.append(str(p))
            if max_files is not None and len(out) >= int(max_files):
                break
        return out
