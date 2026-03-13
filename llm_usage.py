from __future__ import annotations

from typing import Any, Tuple


def extract_token_usage(msg: Any) -> Tuple[int, int, int]:
    """从 LangChain 消息对象中提取 token 使用量。

    优先读取:
    - usage_metadata: input_tokens / output_tokens / total_tokens
    兜底读取:
    - response_metadata.token_usage: prompt_tokens / completion_tokens / total_tokens
    """
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0

    usage_meta = getattr(msg, "usage_metadata", None) or {}
    if isinstance(usage_meta, dict):
        prompt_tokens = int(usage_meta.get("input_tokens") or 0)
        completion_tokens = int(usage_meta.get("output_tokens") or 0)
        total_tokens = int(usage_meta.get("total_tokens") or 0)

    if total_tokens <= 0:
        resp_meta = getattr(msg, "response_metadata", None) or {}
        token_usage = resp_meta.get("token_usage") if isinstance(resp_meta, dict) else {}
        if isinstance(token_usage, dict):
            prompt_tokens = int(token_usage.get("prompt_tokens") or prompt_tokens or 0)
            completion_tokens = int(token_usage.get("completion_tokens") or completion_tokens or 0)
            total_tokens = int(token_usage.get("total_tokens") or 0)

    return prompt_tokens, completion_tokens, total_tokens

