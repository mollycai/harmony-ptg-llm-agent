from __future__ import annotations

import json
import re
from typing import Any, Dict, List


def parse_llm_json_list(text: str) -> List[Dict[str, Any]]:
    """把 LLM 输出解析为 JSON 对象数组，兼容 ```json 包裹与轻微噪声。"""
    t = (text or "").strip()
    t = re.sub(r"^```(?:\s*json)?\s*\n?", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\n?```\s*$", "", t, flags=re.IGNORECASE).strip()
    if not t:
        return []
    try:
        v = json.loads(t)
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []
    except Exception:
        m = re.search(r"(\[\s*{[\s\S]*?}\s*\])", t)
        if not m:
            return []
        try:
            v = json.loads(m.group(1))
            return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []
        except Exception:
            return []
