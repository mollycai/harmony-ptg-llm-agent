from __future__ import annotations

import re
from typing import Any, Dict, List

from agent.tools.project_reader import ProjectReader
from agent.tools.route_constant_resolver import RouteConstantResolver
from agent.utils.route_utils import is_invalid_target


def extract_target_exprs_from_args(args: str) -> List[str]:
    """从 router 调用参数中提取 target 表达式。"""
    out: List[str] = []
    s = args or ""
    kv = re.finditer(r"\b(?:url|routeName|name|uri)\s*:\s*([^\n,}]+)", s)
    for m in kv:
        t = (m.group(1) or "").strip()
        if t:
            out.append(t)
    if out:
        return out
    first = (s.split(",", 1)[0] or "").strip()
    return [first] if first else []


def find_router_calls(code: str) -> List[Dict[str, Any]]:
    """扫描 router.push/replace 系列调用，返回调用片段位置与参数。"""
    out: List[Dict[str, Any]] = []
    if not code:
        return out
    pat = re.compile(r"router\.(pushUrl|replaceUrl|push|replace)\s*\(", re.IGNORECASE)
    for m in pat.finditer(code):
        method = (m.group(1) or "").strip()
        start = m.end()
        depth = 1
        i = start
        while i < len(code):
            ch = code[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if i <= start:
            continue
        out.append({"method": method, "args": code[start:i], "start": m.start(), "end": i})
    return out


def extract_event_near_call(code: str, call_start: int) -> str:
    """在调用点附近提取事件名，如 onClick/onTap。"""
    left = code[max(0, int(call_start) - 220) : int(call_start)]
    m = re.search(r"\.(on[A-Za-z0-9_]+)\s*\(", left)
    if m:
        return str(m.group(1) or "").strip() or "unknown"
    return "unknown"


def extract_component_near_call(code: str, call_start: int) -> str:
    """在调用点附近提取组件名，如 Button/Image/自定义组件。"""
    left = code[max(0, int(call_start) - 320) : int(call_start)]
    m = re.search(r"\b([A-Z][A-Za-z0-9_]*)\s*\(", left)
    if m:
        return str(m.group(1) or "").strip() or "__Common__"
    return "__Common__"


def resolve_dynamic_target_exprs(
    *,
    expr: str,
    code: str,
    imports: Dict[str, str],
    resolved_imports: Dict[str, str],
    reader: ProjectReader,
    route_const_resolver: RouteConstantResolver,
) -> List[str]:
    """轻量追踪 item.url 这类动态表达式，尝试回溯到常量页面路径。"""
    e = (expr or "").strip()
    m = re.fullmatch(r"([A-Za-z_]\w*)\.url", e)
    if not m:
        return []
    item_var = m.group(1)

    foreach_re = re.compile(
        rf"ForEach\(\s*this\.([A-Za-z_]\w*)\s*,\s*\(\s*{re.escape(item_var)}\b",
        re.MULTILINE,
    )
    fm = foreach_re.search(code or "")
    if not fm:
        return []
    list_var = str(fm.group(1) or "").strip()
    if not list_var:
        return []

    init_re = re.compile(
        rf"\b{re.escape(list_var)}\b[^=\n]*=\s*([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*\(",
        re.MULTILINE,
    )
    im = init_re.search(code or "")
    if not im:
        return []
    symbol = str(im.group(1) or "").strip()
    method = str(im.group(2) or "").strip()
    if not symbol or not method:
        return []

    vm_file = resolved_imports.get(symbol)
    if not vm_file:
        return []
    vm_code = reader.read_source_file(vm_file)
    if not vm_code.strip():
        return []

    mm = re.search(
        rf"\b{re.escape(method)}\s*\([^)]*\)\s*\{{([\s\S]*?)\n\}}",
        vm_code,
        flags=re.MULTILINE,
    )
    body = mm.group(1) if mm else vm_code
    args: List[str] = []
    for pm in re.finditer(r"(['\"])(pages\/[^'\"]+)\1", body):
        raw = str(pm.group(2) or "").strip()
        if not raw:
            continue
        v = route_const_resolver.resolve_target_by_symbol(
            target=raw,
            target_expr=raw,
            imports=imports,
            resolved_imports=resolved_imports,
        )
        if v and ("/" in v) and not is_invalid_target(v):
            args.append(v)
    seen = set()
    out: List[str] = []
    for x in args:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def extract_deterministic_edges(
    *,
    code: str,
    imports: Dict[str, str],
    resolved_imports: Dict[str, str],
    reader: ProjectReader,
    route_const_resolver: RouteConstantResolver,
) -> List[Dict[str, str]]:
    """提取确定性可解析的路由边，作为 LLM 结果补充。"""
    out: List[Dict[str, str]] = []
    for call in find_router_calls(code):
        exprs = extract_target_exprs_from_args(str(call.get("args") or ""))
        if not exprs:
            continue
        for expr in exprs:
            target = route_const_resolver.resolve_target_by_symbol(
                target=expr,
                target_expr=expr,
                imports=imports,
                resolved_imports=resolved_imports,
            )
            targets = [target] if (target and "/" in target and not is_invalid_target(target)) else []
            if not targets:
                targets = resolve_dynamic_target_exprs(
                    expr=expr,
                    code=code,
                    imports=imports,
                    resolved_imports=resolved_imports,
                    reader=reader,
                    route_const_resolver=route_const_resolver,
                )
            for t in targets:
                if not t or is_invalid_target(t):
                    continue
                out.append(
                    {
                        "component_type": extract_component_near_call(code, int(call.get("start") or 0)),
                        "event": extract_event_near_call(code, int(call.get("start") or 0)),
                        "target": t,
                        "target_expr": expr,
                    }
                )
    return out
