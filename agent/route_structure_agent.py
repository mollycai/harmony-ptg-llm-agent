from __future__ import annotations

import asyncio
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from langchain_openai import ChatOpenAI

from agent.memory import PTGMemory
from agent.prompt.route_structure_prompt import SYSTEM_PROMPT, build_user_prompt
from agent.tools.import_resolver import ImportResolver
from agent.tools.project_reader import ProjectReader
from agent.tools.route_constant_resolver import RouteConstantResolver
from llm_server import build_chat_model


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/").strip()


def _ensure_ets(p: str) -> str:
    t = _norm(p)
    return t if (not t or t.endswith(".ets")) else f"{t}.ets"


def _strip_ets(p: str) -> str:
    t = _norm(p)
    return t[:-4] if t.endswith(".ets") else t


def _safe_dir(name: str, fallback: str = "default") -> str:
    s = (name or "").strip() or fallback
    s = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", s)
    s = re.sub(r"[. ]+$", "", s).strip() or fallback
    if re.fullmatch(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])", s, flags=re.IGNORECASE):
        s = "_" + s
    return s


def _parse_llm_json_list(text: str) -> List[Dict[str, Any]]:
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


@dataclass
class RouteStructureAgentConfig:
    project_name: str
    project_path: str
    main_pages_json_path: str
    llm_provider_config: dict
    llm_model_name: str
    import_alias_map: Optional[Dict[str, str]] = None

    ets_root: Optional[str] = None
    output_dir: str = str(Path(__file__).resolve().parent / "result")
    max_files: int = 2000
    max_depth: int = 30
    max_route_files: int = 120
    max_route_file_chars: int = 40000


class RouteStructureAgent:
    def __init__(self, config: RouteStructureAgentConfig) -> None:
        self.config = config
        self.llm: ChatOpenAI = build_chat_model(config.llm_provider_config, config.llm_model_name)

        ets_root = config.ets_root or str(Path(config.project_path) / "src" / "main" / "ets")
        self.ets_root = Path(ets_root)
        self.project_root = Path(config.project_path)
        self.import_alias_map = self._normalize_import_alias_map(config.import_alias_map)

        if self.import_alias_map:
            print(
                "[RouteStructureAgent] Import alias map loaded: "
                + json.dumps(self.import_alias_map, ensure_ascii=False)
            )
        else:
            print("[RouteStructureAgent] Import alias map is empty.")

        self.memory = PTGMemory()
        self.reader = ProjectReader(ets_root=str(self.ets_root))
        self.import_resolver = ImportResolver(reader=self.reader, import_alias_map=self.import_alias_map)
        self.route_const_resolver = RouteConstantResolver(
            ets_root=str(self.ets_root),
            max_files=int(self.config.max_route_files),
            max_chars_per_file=int(self.config.max_route_file_chars),
        )

        self.dependency_graph: Dict[str, List[str]] = {}
        self._visited: Set[str] = set()
        self._count = 0
        self._main_page_ids: Set[str] = set()

    def _normalize_import_alias_map(self, raw_map: Optional[Dict[str, str]]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for k, v in (raw_map or {}).items():
            alias = (k or "").strip()
            base = (v or "").strip()
            if not alias or not base:
                continue
            p = Path(base)
            if not p.is_absolute():
                p = (self.project_root / p).resolve()
            out[alias] = str(p)
        return out

    async def _analyze_file(
        self,
        *,
        main_page_key: str,
        file_path: Path,
        main_pages: List[str],
        depth: int,
        chain: List[str],
    ) -> None:
        if self._count >= int(self.config.max_files):
            return
        if depth > int(self.config.max_depth):
            return

        fp = _norm(str(file_path.resolve()))
        if fp in self._visited:
            return
        self._visited.add(fp)
        self._count += 1

        code = self.reader.read_source_file(str(file_path))
        if not code.strip():
            return

        imports = self.import_resolver.extract_imports(code)
        resolved_map = self.import_resolver.resolve_imports_to_files(
            imports=imports,
            current_file_path=str(file_path),
        )
        resolved_files = [str(x) for x in resolved_map.values()]
        resolved_files = [f for f in resolved_files if self.reader.should_explore_file(f)]

        self.dependency_graph[_norm(str(file_path))] = [_norm(x) for x in resolved_files]

        print(f"[RouteStructureAgent] Reading & analyzing file: {str(file_path)}")
        user_prompt = build_user_prompt(
            file_path=str(file_path),
            code=code,
            main_pages=main_pages,
            dependency_chain=chain,
            resolved_import_files=resolved_files,
            route_constant_map=self.route_const_resolver.full_map,
        )
        msg = await self.llm.ainvoke([("system", SYSTEM_PROMPT), ("user", user_prompt)])
        edges = _parse_llm_json_list(str(getattr(msg, "content", "") or ""))

        for e in edges:
            component_type = str(e.get("component_type") or "unknown")
            event = str(e.get("event") or "unknown")
            raw_target = str(e.get("target") or "").strip()

            target = self.route_const_resolver.resolve_target(raw_target)
            if not target:
                continue

            if self.memory.add_edge(
                source_page=main_page_key,
                component_type=component_type,
                event=event,
                target=target,
            ):
                print(f"Found route: {main_page_key} -> {target}")

        nested = self.import_resolver.find_nested_component_files(
            imports=imports,
            current_file_path=str(file_path),
        )
        nested = [nf for nf in nested if self.reader.should_explore_file(nf)]
        next_chain = [*chain, _norm(str(file_path))]
        for nf in nested:
            await self._analyze_file(
                main_page_key=main_page_key,
                file_path=Path(nf),
                main_pages=main_pages,
                depth=depth + 1,
                chain=next_chain,
            )

    async def run(self) -> Dict[str, List[Dict[str, Any]]]:
        main_pages = ProjectReader.load_main_pages(self.config.main_pages_json_path)
        main_pages = [str(x) for x in (main_pages or []) if str(x).strip()]
        main_page_ids = [_strip_ets(p) for p in main_pages]

        self._main_page_ids = {p for p in main_page_ids if p}
        self.memory.init_from_main_pages(sorted(self._main_page_ids))
        self.route_const_resolver.build()

        for mp_raw, mp_id in zip(main_pages, main_page_ids):
            if not mp_id:
                continue
            mp_file = self.ets_root / _ensure_ets(mp_raw)
            if not mp_file.exists():
                print(f"[RouteStructureAgent] Main page file not found: {str(mp_file)}")
                continue

            self._visited = set()
            self._count = 0

            await self._analyze_file(
                main_page_key=mp_id,
                file_path=mp_file,
                main_pages=main_page_ids,
                depth=0,
                chain=[mp_id],
            )

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path(self.config.output_dir) / _safe_dir(self.config.project_name)
        ptg_path = out_dir / f"ptg_route_structure_{stamp}.json"
        self.memory.save_json(str(ptg_path))
        print(f"[RouteStructureAgent] PTG saved: {str(ptg_path)}")

        return self.memory.to_json_obj()

    def run_sync(self) -> Dict[str, List[Dict[str, Any]]]:
        if sys.platform.startswith("win"):
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            except Exception:
                pass
        return asyncio.run(self.run())
