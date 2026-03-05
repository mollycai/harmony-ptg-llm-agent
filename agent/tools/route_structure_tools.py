from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.tools.import_resolver import ImportResolver
from agent.tools.project_reader import ProjectReader
from agent.tools.route_constant_resolver import RouteConstantResolver


def load_main_pages(main_pages_json_path: str) -> List[str]:
    return ProjectReader.load_main_pages(main_pages_json_path)


def read_source_file(file_path: str) -> str:
    return ProjectReader.read_source_file(file_path)


def should_explore_file(file_path: str, *, ets_root: str) -> bool:
    return ProjectReader(ets_root=ets_root).should_explore_file(file_path)


def extract_imports(source_code: str) -> Dict[str, str]:
    # 兼容层：仅提取 import/export 依赖，不做路径解析
    reader = ProjectReader(ets_root=".")
    resolver = ImportResolver(reader=reader)
    return resolver.extract_imports(source_code)


def resolve_imports_to_files(
    imports: Dict[str, str],
    current_file_path: str,
    ets_root: str,
    import_alias_map: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    reader = ProjectReader(ets_root=ets_root)
    resolver = ImportResolver(reader=reader, import_alias_map=import_alias_map)
    return resolver.resolve_imports_to_files(imports=imports, current_file_path=current_file_path)


def find_nested_component_files(
    imports: Dict[str, str],
    current_file_path: str,
    ets_root: str,
    import_alias_map: Optional[Dict[str, str]] = None,
) -> List[str]:
    reader = ProjectReader(ets_root=ets_root)
    resolver = ImportResolver(reader=reader, import_alias_map=import_alias_map)
    return resolver.find_nested_component_files(imports=imports, current_file_path=current_file_path)


def scan_route_constant_files(
    ets_root: str,
    max_files: int = 400,
    head_chars: int = 8192,
) -> List[str]:
    # 兼容层：保留旧函数名。当前返回包含路由常量符号的候选文件列表。
    resolver = RouteConstantResolver(ets_root=ets_root, max_files=max_files, max_chars_per_file=head_chars)
    symbols = resolver.symbols
    out: List[str] = []
    root = Path(ets_root)
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".ets", ".ts"}:
            continue
        try:
            head = p.read_text(encoding="utf-8", errors="ignore")[: int(head_chars)]
        except Exception:
            continue
        if head and any(s in head for s in symbols):
            out.append(str(p))
            if len(out) >= int(max_files):
                break
    return out


def save_json(obj: Any, output_path: str) -> str:
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(p)
