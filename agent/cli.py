import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config import PROJECT_CONFIG, get_llm_config, get_project_config
from agent.route_structure_agent import RouteStructureAgent, RouteStructureAgentConfig


def _parse_args(argv: list[str]) -> tuple[str, str]:
    tokens = [a.lstrip("-") for a in (argv or []) if a and a.strip()]
    provider = (tokens[0] if len(tokens) >= 1 else "deepseek") or "deepseek"
    project_in = (tokens[1] if len(tokens) >= 2 else "HarmoneyOpenEye") or "HarmoneyOpenEye"

    project = project_in
    for k in PROJECT_CONFIG.keys():
        if k.lower() == project_in.lower():
            project = k
            break

    return provider, project


def main() -> None:
    load_dotenv(dotenv_path=_REPO_ROOT / ".env")

    provider, project_key = _parse_args(sys.argv[1:])

    llm_cfg = get_llm_config(provider)
    proj = get_project_config(project_key)

    agent = RouteStructureAgent(
        config=RouteStructureAgentConfig(
            project_name=proj["projectName"],
            project_path=proj["projectPath"],
            main_pages_json_path=proj["projectMainPagePath"],
            llm_provider_config=llm_cfg,
            llm_model_name=llm_cfg["model"],
        )
    )

    ptg = agent.run_sync()
    print(ptg)


if __name__ == "__main__":
    main()