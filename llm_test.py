from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, AuthenticationError

from config import get_llm_config
from llm_server import build_chat_model
from llm_usage import extract_token_usage


REPO_ROOT = Path(__file__).resolve().parent
load_dotenv(REPO_ROOT / ".env")


def _parse_args(argv: list[str]) -> tuple[str, str]:
    if not argv:
        return "deepseek", "你好"

    provider = "deepseek"
    prompt_parts: list[str] = []

    for index, arg in enumerate(argv):
        if index == 0 and arg.startswith("--"):
            provider = (arg[2:] or "deepseek").strip().lower() or "deepseek"
            continue

        prompt_parts.append(arg[2:] if arg.startswith("--") else arg)

    prompt = " ".join(part for part in prompt_parts if part.strip()).strip() or "你好"
    return provider, prompt


def main() -> int:
    provider, prompt = _parse_args(sys.argv[1:])
    llm_config = get_llm_config(provider)
    model = build_chat_model(llm_config, llm_config["model"])

    try:
        response = model.invoke([("user", prompt)])
    except AuthenticationError as exc:
        print(f"LLM authentication failed: provider={provider}, error={exc}")
        return 1
    except APIConnectionError as exc:
        print(
            "LLM connection failed: "
            f"provider={provider}, base_url={llm_config.get('baseURL', '')}, error={exc}"
        )
        return 1
    except APIStatusError as exc:
        print(f"LLM API returned an error: provider={provider}, error={exc}")
        return 1
    except Exception as exc:
        print(f"LLM invoke failed: provider={provider}, error={exc}")
        return 1

    content = response.content
    if isinstance(content, list):
        text = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        ).strip()
    else:
        text = str(content).strip()

    prompt_tokens, completion_tokens, total_tokens = extract_token_usage(response)

    print(f"provider: {provider}")
    print(f"model: {llm_config['model']}")
    print(f"prompt: {prompt}")
    print(
        "token_usage: "
        f"prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}"
    )
    print("response:")
    print(text)

    return 0 if text else 1


if __name__ == "__main__":
    raise SystemExit(main())
