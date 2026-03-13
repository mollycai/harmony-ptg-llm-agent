import os
from langchain_openai import ChatOpenAI


def build_chat_model(config: dict, model_name: str) -> ChatOpenAI:
    api_key = os.environ.get(config["apiKeyEnv"])
    if not api_key:
        raise RuntimeError(f"Missing env {config['apiKeyEnv']}")

    # 稳定性优先：默认低随机性，支持按 provider 配置覆盖
    options = dict(config.get("chatOptions") or {})
    temperature = float(options.get("temperature", 0))
    top_p = float(options.get("top_p", 1))
    max_tokens = int(options.get("max_tokens", 4096))
    timeout = int(options.get("timeout", 180))
    max_retries = int(options.get("max_retries", 2))
    stream_usage = bool(options.get("stream_usage", True))

    return ChatOpenAI(
        api_key=api_key,
        model=model_name,
        base_url=config.get("baseURL", ""),
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=max_retries,
        stream_usage=stream_usage,
    )
