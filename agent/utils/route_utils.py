from __future__ import annotations


def normalize_path(path: str) -> str:
    return (path or "").replace("\\", "/").strip()


def strip_ets(path: str) -> str:
    p = normalize_path(path)
    return p[:-4] if p.endswith(".ets") else p


def is_invalid_target(target: str) -> bool:
    t = (target or "").strip().lower()
    if not t:
        return True
    if t in {"unknown", "router.back()", "back()", "router.back", "back"}:
        return True
    return t.startswith("router.back(") or t.startswith("back(")
