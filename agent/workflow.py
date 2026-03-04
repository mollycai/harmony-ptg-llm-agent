import json
import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config import PROJECT_CONFIG, get_llm_config, get_project_config
from agent.route_structure_agent import RouteStructureAgent, RouteStructureAgentConfig
from agent.route_validation_agent import RouteValidationAgent
from agent.tools.route_structure_tools import load_main_pages


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

    structure_agent = RouteStructureAgent(
        config=RouteStructureAgentConfig(
            project_name=proj["projectName"],
            project_path=proj["projectPath"],
            main_pages_json_path=proj["projectMainPagePath"],
            llm_provider_config=llm_cfg,
            llm_model_name=llm_cfg["model"],
        )
    )

    ptg = structure_agent.run_sync()

    main_pages = load_main_pages.invoke({"main_pages_json_path": proj["projectMainPagePath"]})
    main_pages = [str(x) for x in (main_pages or []) if str(x).strip()]

    validator = RouteValidationAgent(main_pages=main_pages)
    validated_ptg, report = validator.validate_and_rewrite(ptg)

    print(json.dumps({"report": report, "ptg": validated_ptg}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()