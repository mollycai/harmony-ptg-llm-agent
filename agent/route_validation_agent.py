from __future__ import annotations

"""PTG 结果校验与重写。

职责：
1) 统一清洗 route_structure 输出格式；
2) 丢弃明显无效边；
3) 去重并补齐 main_pages 空节点；
4) 输出可观测报告（含 drop reason 细分）。
"""

import re
from typing import Any, Dict, List, Tuple

from agent.utils.route_utils import is_invalid_target, normalize_path, strip_ets


def _strip_quotes(s: str) -> str:
    """去掉字符串外层引号。"""
    t = (s or "").strip()
    if len(t) >= 2 and ((t[0] == '"' and t[-1] == '"') or (t[0] == "'" and t[-1] == "'")):
        return t[1:-1].strip()
    return t


def _edge_key(edge: Dict[str, Any]) -> Tuple[str, str, str]:
    """构造边去重键：(component_type, event, target)。"""
    component_type = str(((edge.get("component") or {}).get("type")) or "")
    event = str(edge.get("event") or "")
    target = str(edge.get("target") or "")
    return component_type, event, target


# 事件名称只接受 onXxx 形式。
_EVENT_RE = re.compile(r"^on[A-Z]\w*$")
# 组件类型中明显是 API/方法名的值会被降级为 __Common__。
_BAD_COMPONENT_RE = re.compile(r"^(router\.|this\.|console\.|pushUrl$|replaceUrl$|push$|replace$)", re.IGNORECASE)


def _normalize_component_type(raw: Any) -> str:
    """规范化组件类型。"""
    c = str(raw or "").strip()
    if not c or _BAD_COMPONENT_RE.search(c):
        return "__Common__"
    return c


def _normalize_event(raw: Any) -> str:
    """规范化事件名，不合法时回退 onClick。"""
    e = str(raw or "").strip()
    if _EVENT_RE.fullmatch(e):
        return e
    return "onClick"


class RouteValidationAgent:
    """对 PTG 执行规则层校验与重写。"""

    def __init__(self, *, main_pages: List[str]) -> None:
        """初始化主页面集合（统一去引号与 .ets 后缀）。"""
        main_page_ids = [strip_ets(_strip_quotes(str(p))) for p in (main_pages or []) if str(p).strip()]
        self.main_pages: List[str] = [p for p in main_page_ids if p]
        self._main_set = set(self.main_pages)

    def validate_and_rewrite(self, ptg: Any) -> tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Any]]:
        """校验并重写 PTG。

        Args:
            ptg: route_structure 阶段输出（预期为 dict）。

        Returns:
            (validated_ptg, report)
        """
        report: Dict[str, Any] = {
            "main_pages_count": len(self.main_pages),
            "sources_count": 0,
            "edges_in": 0,
            "edges_out": 0,
            "edges_dropped_schema": 0,
            "edges_dropped_invalid_target": 0,
            "edges_deduped": 0,
            "edges_fixed_component": 0,
            "edges_fixed_event": 0,
            "drop_reasons": {
                "schema": 0,
                "invalid_target": 0,
                "dedup": 0,
            },
            "empty_pages": [],
            "missing_main_pages": [],
        }

        out: Dict[str, List[Dict[str, Any]]] = {}

        # 输入结构异常时，直接返回 main_pages 空图。
        if not isinstance(ptg, dict):
            for p in sorted(self._main_set):
                out[p] = []
            report["sources_count"] = len(out)
            report["missing_main_pages"] = sorted(self._main_set)
            report["empty_pages"] = sorted(self._main_set)
            return out, report

        for raw_src, raw_edges in ptg.items():
            src = strip_ets(_strip_quotes(normalize_path(str(raw_src))))
            if not src:
                continue

            edges_list = raw_edges if isinstance(raw_edges, list) else []
            report["edges_in"] += len(edges_list)

            normalized: List[Dict[str, Any]] = []
            seen = set()

            for e in edges_list:
                if not isinstance(e, dict):
                    report["edges_dropped_schema"] += 1
                    report["drop_reasons"]["schema"] += 1
                    continue

                raw_component = ((e.get("component") or {}).get("type")) or e.get("component_type")
                raw_event = e.get("event")
                component_type = _normalize_component_type(raw_component)
                # event = _normalize_event(raw_event)

                target_raw = str(e.get("target") or "")
                target = strip_ets(_strip_quotes(normalize_path(target_raw)))
                if is_invalid_target(target):
                    report["edges_dropped_invalid_target"] += 1
                    report["drop_reasons"]["invalid_target"] += 1
                    continue

                # 记录字段修正次数，便于回归观察。
                if component_type != str(raw_component or "").strip():
                    report["edges_fixed_component"] += 1
                # if event != str(raw_event or "").strip():
                #     report["edges_fixed_event"] += 1

                ne: Dict[str, Any] = {
                    "component": {"type": component_type},
                    "event": raw_event,
                    "target": target,
                }

                k = _edge_key(ne)
                if k in seen:
                    report["edges_deduped"] += 1
                    report["drop_reasons"]["dedup"] += 1
                    continue
                seen.add(k)
                normalized.append(ne)

            out[src] = normalized

        # 保障 main_pages 全部出现在 PTG 中，即使没有边也保留空数组。
        for p in sorted(self._main_set):
            if p not in out:
                out[p] = []

        report["sources_count"] = len(out)
        report["missing_main_pages"] = sorted([p for p in self._main_set if p not in out])
        report["empty_pages"] = sorted([k for k, v in out.items() if k in self._main_set and not (v or [])])
        report["edges_out"] = sum(len(v or []) for v in out.values())

        return out, report
