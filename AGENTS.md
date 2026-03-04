# Repository Guidelines

## Project Structure & Module Organization
Core logic is split into two pipelines:
- `llm/`: single-model PTG generation flow (`workflow.py`, prompt builders, utility helpers, and generated outputs under `llm/result/`).
- `agent/`: multi-agent PTG extraction and validation (`workflow.py`, route agents, tools, prompt modules, and outputs under `agent/result/`).

Repository-level files:
- `config.py`: model/provider and target-project mappings.
- `clone_projects.py`: clones benchmark HarmonyOS apps into a local `projects/` directory.
- `static_analysis/`: baseline PTG JSON artifacts from static parsing.

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate`: create and activate local environment.
- `pip install -r requirements.txt`: install runtime dependencies.
- `python clone_projects.py /path/to/base`: clone benchmark app repos to `/path/to/base/projects`.
- `python llm/workflow.py --deepseek --HarmoneyOpenEye`: run the pure LLM PTG pipeline.
- `python agent/workflow.py --deepseek --HarmoneyOpenEye`: run route-structure + validation agent pipeline.

## Coding Style & Naming Conventions
- Target Python 3.10+ and keep 4-space indentation.
- Use type hints on public functions (`def run(provider: str, project_key: str) -> None`).
- Naming: `snake_case` for variables/functions/modules, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.
- Keep modules focused: prompts in `*/prompt/`, orchestration in `*/workflow.py`, output data in `*/result/`.
- No enforced formatter/linter is currently configured; match existing style and keep imports/grouping clean.

## Testing Guidelines
There is no dedicated test suite yet (`tests/` is absent). Before opening a PR, run at least:
- `python llm/workflow.py --<provider> --<project>`
- `python agent/workflow.py --<provider> --<project>`

Validate that output JSON is produced and structurally correct (PTG keys are page paths; values are edge arrays).

## Commit & Pull Request Guidelines
- Follow Conventional Commit style used in history: `feat: ...`, `docs: ...`, `fix: ...`.
- Keep commits scoped to one logical change (config, agent logic, prompts, docs).
- PRs should include:
  - purpose and affected pipeline (`llm` or `agent`);
  - config/environment changes (`.env` keys, `config.py` entries);
  - sample output path(s) (for example `agent/result/<Project>/...json`).

## Security & Configuration Tips
- Never commit secrets; keep API keys in `.env` only.
- Treat `config.py` paths as local-machine defaults; prefer updating to your own absolute paths before running workflows.
