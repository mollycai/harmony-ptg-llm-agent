from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


PTGEdge = Dict[str, Any]
PTG = Dict[str, List[PTGEdge]]


def _normalize_page_key(page_path: str) -> str:
    return (page_path or "").replace("\\", "/").strip()


def _edge_key(edge: PTGEdge) -> Tuple[str, str, str]:
    component_type = str(((edge.get("component") or {}).get("type")) or "")
    event = str(edge.get("event") or "")
    target = str(edge.get("target") or "")
    return component_type, event, target


@dataclass
class PTGMemory:
    ptg: PTG = field(default_factory=dict)

    def init_from_main_pages(self, main_pages: Iterable[str]) -> None:
        for p in main_pages:
            k = _normalize_page_key(str(p))
            if k and k not in self.ptg:
                self.ptg[k] = []

    def ensure_page(self, page_path: str) -> None:
        k = _normalize_page_key(page_path)
        if k and k not in self.ptg:
            self.ptg[k] = []

    def add_edge(self, *, source_page: str, component_type: str, event: str, target: str) -> bool:
        src = _normalize_page_key(source_page)
        if not src:
            return False
        self.ensure_page(src)

        edge: PTGEdge = {
            "component": {"type": str(component_type or "").strip() or "unknown"},
            "event": str(event or "").strip() or "unknown",
            "target": str(target or "").strip(),
        }
        if not edge["target"]:
            return False

        existing = self.ptg.get(src, [])
        keys = {_edge_key(e) for e in existing}
        k = _edge_key(edge)
        if k in keys:
            return False

        existing.append(edge)
        self.ptg[src] = existing
        return True

    def to_json_obj(self) -> PTG:
        return self.ptg

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.ptg, ensure_ascii=False, indent=indent)

    def save_json(self, output_path: str) -> str:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json(indent=2), encoding="utf-8")
        return str(p)
