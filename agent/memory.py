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
    route_constant_full: Dict[str, str] = field(default_factory=dict)
    route_constant_short: Dict[str, str] = field(default_factory=dict)
    unresolved_targets: List[str] = field(default_factory=list)

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

    def merge_edges(self, *, source_page: str, edges: Iterable[Dict[str, Any]]) -> int:
        added = 0
        for e in edges:
            component_type = str((e.get("component") or {}).get("type") or e.get("component_type") or "unknown")
            event = str(e.get("event") or "unknown")
            target = str(e.get("target") or "")
            if self.add_edge(source_page=source_page, component_type=component_type, event=event, target=target):
                added += 1
        return added

    def update_route_constants(self, *, full_map: Dict[str, str], short_map: Dict[str, str]) -> None:
        self.route_constant_full = dict(full_map or {})
        self.route_constant_short = dict(short_map or {})

    def record_unresolved_target(self, target: str) -> None:
        t = (target or "").strip()
        if not t:
            return
        if t not in self.unresolved_targets:
            self.unresolved_targets.append(t)

    def rewrite_targets(self, resolver) -> int:
        changed = 0
        new_ptg: PTG = {}
        for src, edges in (self.ptg or {}).items():
            out: List[PTGEdge] = []
            seen = set()
            for e in edges or []:
                target = str(e.get("target") or "")
                new_target = str(resolver(target) or "").strip()
                if new_target and new_target != target:
                    e = {**e, "target": new_target}
                    changed += 1
                k = _edge_key(e)
                if k in seen:
                    continue
                seen.add(k)
                out.append(e)
            new_ptg[src] = out
        self.ptg = new_ptg
        return changed

    def to_json_obj(self) -> PTG:
        return self.ptg

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.ptg, ensure_ascii=False, indent=indent)

    def save_json(self, output_path: str) -> str:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json(indent=2), encoding="utf-8")
        return str(p)