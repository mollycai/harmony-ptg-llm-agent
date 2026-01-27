import os
from langchain_openai import ChatOpenAI

# 构建ChatOpenAI模型
def build_chat_model(config: dict, model_name: str) -> ChatOpenAI:
    api_key = os.environ.get(config["apiKeyEnv"])
    if not api_key:
        raise RuntimeError(f"Missing env {config['apiKeyEnv']}")
    return ChatOpenAI(
        api_key=api_key,
        model=model_name,
        temperature=0,
        base_url=config.get("baseURL", ""),
    )