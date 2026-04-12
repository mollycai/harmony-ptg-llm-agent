from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def _safe_dir(name: str, fallback: str = "default") -> str:
    """将字符串标准化为安全目录名。"""
    s = (name or "").strip() or fallback
    s = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", s)
    s = re.sub(r"[. ]+$", "", s).strip() or fallback
    if re.fullmatch(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])", s, flags=re.IGNORECASE):
        s = "_" + s
    return s


def _safe_file_token(name: str, fallback: str = "model") -> str:
    """将字符串标准化为安全文件名片段。"""
    s = (name or "").strip() or fallback
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("._-")
    return s or fallback


def sync_test_ptg_ets(ptg_obj: Dict[str, List[Dict[str, Any]]], *, repo_root: Path) -> None:
    """同步更新 test/PTG.ets 中 PTGJson/PTGJSON 常量。"""
    ptg_ets_path = repo_root / "test" / "PTG.ets"
    if not ptg_ets_path.exists():
        print(f"[Workflow] test/PTG.ets not found, skip sync: {str(ptg_ets_path)}")
        return

    ptg_json_text = json.dumps(ptg_obj, ensure_ascii=False, indent=2)
    try:
        text = ptg_ets_path.read_text(encoding="utf-8")
    except Exception as ex:
        print(f"[Workflow] Failed to read test/PTG.ets: {ex}")
        return

    pattern = re.compile(r"(const\s+(PTGJson|PTGJSON)\s*=\s*)`[\s\S]*?`;", flags=re.MULTILINE)
    m = pattern.search(text)
    if m:
        prefix = m.group(1)
        new_block = f"{prefix}`{ptg_json_text}`;"
        new_text = pattern.sub(new_block, text, count=1)
    else:
        new_text = f"const PTGJson = `{ptg_json_text}`;\nexport default PTGJson;\n"

    try:
        ptg_ets_path.write_text(new_text, encoding="utf-8")
        print(f"[Workflow] PTG synced to test/PTG.ets: {str(ptg_ets_path)}")
    except Exception as ex:
        print(f"[Workflow] Failed to write test/PTG.ets: {ex}")


def finalize_validated_outputs(
    *,
    validated_ptg: Dict[str, List[Dict[str, Any]]],
    snapshot: Dict[str, Any],
    output_dir: str,
    project_name: str,
    model_name: str,
    repo_root: Path,
) -> str:
    """打印汇总信息并将 validated_ptg 统一落盘。"""
    unresolved_summary = snapshot.get("unresolved_imports_summary") or []
    if unresolved_summary:
        print(
            "[RouteStructureAgent] Unresolved imports summary (top 20): "
            + json.dumps(unresolved_summary, ensure_ascii=False)
        )
    else:
        print("[RouteStructureAgent] Unresolved imports summary: []")

    token_usage = snapshot.get("token_usage") or {}
    print(
        "[RouteStructureAgent] Token usage summary: "
        f"calls={int(token_usage.get('calls') or 0)}, "
        f"prompt={int(token_usage.get('prompt') or 0)}, "
        f"completion={int(token_usage.get('completion') or 0)}, "
        f"total={int(token_usage.get('total') or 0)}"
    )
    state_summary = snapshot.get("state_summary") or {}
    print(
        "[RouteStructureAgent] State summary: "
        f"coverage_calls={int(state_summary.get('coverage_calls') or 0)}, "
        f"constructed_edges={int(state_summary.get('constructed_edges') or 0)}, "
        f"invalid_target_dropped={int(state_summary.get('invalid_target_dropped') or 0)}"
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(output_dir) / _safe_dir(project_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_token = _safe_file_token(model_name, fallback="model")
    out_path = out_dir / f"ptg_route_structure_{model_token}_{stamp}.json"
    out_path.write_text(json.dumps(validated_ptg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Workflow] Validated PTG saved: {str(out_path)}")
    sync_test_ptg_ets(validated_ptg, repo_root=repo_root)
    return str(out_path)

