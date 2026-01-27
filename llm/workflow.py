import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

from config import get_llm_config, get_project_config
from llm.llm_server import build_chat_model
from llm.utils import run_long_prompt_conversation

# 解析命令行参数，获取LLM提供程序和项目键
def _parse_args(argv: list[str]) -> tuple[str, str]:
    llm = (argv[0].lstrip("-") if len(argv) >= 1 and argv[0] else "deepseek") or "deepseek"
    project = (argv[1].lstrip("-") if len(argv) >= 2 and argv[1] else "HarmoneyOpenEye") or "HarmoneyOpenEye"
    return llm, project

# 异步运行LLM服务器，处理项目代码并生成PTG输出
async def run(provider: str, project_key: str) -> None:
    llm_config = get_llm_config(provider)
    project_config = get_project_config(project_key)

    llm = build_chat_model(llm_config, llm_config["model"])
    preprocess_llm = build_chat_model(llm_config, llm_config["preprocessModel"])

    result = await run_long_prompt_conversation(
        {
            "llm": llm,
            "preprocessLlm": preprocess_llm,
            "projectName": project_config["projectName"],
            "projectPath": project_config["projectPath"],
            "projectMainPagePath": project_config["projectMainPagePath"],
            "chunkSize": 1500,
            "model": llm_config["model"],
            "preprocessModel": llm_config["preprocessModel"],
            "enablePreprocess": True,
        }
    )

    if result.get("fullPromptPath"):
        print("完整提示已保存到:", result["fullPromptPath"], "长度：", result["fullPromptLength"])
    print(result["completionText"])


def main() -> None:
    load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")
    provider, project_key = _parse_args(list(sys.argv[1:]))

    if sys.platform.startswith("win"):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except AttributeError:
            pass

    asyncio.run(run(provider, project_key))


if __name__ == "__main__":
    main()