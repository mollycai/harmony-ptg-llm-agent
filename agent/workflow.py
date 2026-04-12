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
from agent.tools.project_reader import ProjectReader
from agent.utils.output_writer import finalize_validated_outputs
from agent.utils.runtime_log_capture import RuntimeLogCapture

ENABLE_SAVE_RUN_LOG = True
RUN_LOG_OUTPUT_DIR = str(_REPO_ROOT / "agent" / "result" / "_logs")


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
            import_alias_map=proj.get("importAliasMap"),
        )
    )
    log_capture = RuntimeLogCapture(
        enabled=ENABLE_SAVE_RUN_LOG,
        output_dir=RUN_LOG_OUTPUT_DIR,
        project_name=structure_agent.config.project_name,
        model_name=structure_agent.config.llm_model_name,
    )
    log_path = ""
    try:
        log_capture.start()

        ptg = structure_agent.run_sync()

        main_pages = ProjectReader.load_main_pages(proj["projectMainPagePath"])
        main_pages = [str(x) for x in (main_pages or []) if str(x).strip()]

        validator = RouteValidationAgent(main_pages=main_pages)
        validated_ptg, report = validator.validate_and_rewrite(ptg)
        output_path = finalize_validated_outputs(
            validated_ptg=validated_ptg,
            snapshot=structure_agent.get_finalize_snapshot(),
            output_dir=structure_agent.config.output_dir,
            project_name=structure_agent.config.project_name,
            model_name=structure_agent.config.llm_model_name,
            repo_root=_REPO_ROOT,
        )

        print(
            json.dumps(
                {"report": report, "output_path": output_path, "ptg": validated_ptg},
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        log_path = log_capture.stop_and_save()
        if log_path:
            print(f"[Workflow] Run log saved: {log_path}")


if __name__ == "__main__":
    main()
