from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List


class ProjectReader:
    def __init__(self, *, ets_root: str) -> None:
        # ets_root 是本项目主模块源码根目录
        self.ets_root = Path(ets_root)

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
