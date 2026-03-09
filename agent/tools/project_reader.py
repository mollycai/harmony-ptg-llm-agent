from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, List, Optional, Set

from agent.utils.route_utils import normalize_path


class ProjectReader:
    def __init__(self, *, ets_root: str, skip_dir_names: Optional[Iterable[str]] = None) -> None:
        # ets_root 是本项目主模块源码根目录，用于路径基准判断
        self.ets_root = Path(ets_root)
        skip = set(skip_dir_names or {"http", "https", "util", "utils", "constant", "constants"})
        self._skip_dir_names: Set[str] = {str(x).lower() for x in skip if str(x).strip()}

    @staticmethod
    def load_main_pages(main_pages_json_path: str) -> List[str]:
        """读取 main_pages.json，返回入口页面列表。"""
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
        """读取源码文件文本。"""
        return Path(file_path).read_text(encoding="utf-8", errors="ignore")

    def should_explore_file(self, file_path: str) -> bool:
        # 仅在 ets_root 下且不在跳过目录中的文件才继续深入
        fp = normalize_path(file_path)
        if not fp:
            return False
        try:
            rel = Path(fp).resolve().relative_to(self.ets_root.resolve())
        except Exception:
            return False
        return not any((part or "").lower() in self._skip_dir_names for part in rel.parts)
