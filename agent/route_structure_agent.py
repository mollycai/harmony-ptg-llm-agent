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
from agent.tools.route_structure_tools import (
    extract_imports,
    find_nested_component_files,
    load_main_pages,
    read_source_file,
    resolve_imports_to_files,
    save_json,
)
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


def _read_text_limit(path: Path, *, limit_chars: int) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[: max(0, int(limit_chars))]
    except Exception:
        return ""


def _build_route_constant_maps(
    *,
    ets_root: Path,
    max_files: int,
    max_chars_per_file: int,
) -> tuple[Dict[str, str], Dict[str, str]]:
    full_map: Dict[str, str] = {}
    short_map: Dict[str, str] = {}
    short_seen: Dict[str, int] = {}

    if not ets_root.exists():
        return full_map, short_map

    symbols = ("RoutePath", "RouterPath", "NavPath", "NavigationPath")
    candidates: List[Path] = []

    for p in ets_root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".ets", ".ts"}:
            continue
        head = _read_text_limit(p, limit_chars=8192)
        if not head:
            continue
        if any(s in head for s in symbols):
            candidates.append(p)
            if len(candidates) >= int(max_files):
                break

    enum_entry_re = re.compile(r"\b(\w+)\s*=\s*(['\"])(.+?)\2")
    obj_entry_re = re.compile(r"\b(\w+)\s*:\s*(['\"])(.+?)\2")
    class_static_entry_re = re.compile(r"\bstatic\s+(?:readonly\s+)?(\w+)\s*=\s*(['\"])(.+?)\2")

    for f in candidates:
        src = _read_text_limit(f, limit_chars=max_chars_per_file)
        if not src:
            continue

        for sym in symbols:
            if sym not in src:
                continue

            for m in re.finditer(rf"\b(?:export\s+)?enum\s+{re.escape(sym)}\s*\{{([\s\S]*?)\}}", src):
                body = m.group(1) or ""
                for em in enum_entry_re.finditer(body):
                    k = em.group(1)
                    v = _norm(em.group(3))
                    full_map[f"{sym}.{k}"] = v
                    short_seen[k] = short_seen.get(k, 0) + 1
                    if short_seen[k] == 1:
                        short_map[k] = v
                    else:
                        short_map.pop(k, None)

            for m in re.finditer(rf"\b(?:export\s+)?const\s+{re.escape(sym)}\s*=\s*\{{([\s\S]*?)\}}", src):
                body = m.group(1) or ""
                for om in obj_entry_re.finditer(body):
                    k = om.group(1)
                    v = _norm(om.group(3))
                    full_map[f"{sym}.{k}"] = v
                    short_seen[k] = short_seen.get(k, 0) + 1
                    if short_seen[k] == 1:
                        short_map[k] = v
                    else:
                        short_map.pop(k, None)

            for m in re.finditer(rf"\b(?:export\s+)?class\s+{re.escape(sym)}\s*\{{([\s\S]*?)\}}", src):
                body = m.group(1) or ""
                for cm in class_static_entry_re.finditer(body):
                    k = cm.group(1)
                    v = _norm(cm.group(3))
                    full_map[f"{sym}.{k}"] = v
                    short_seen[k] = short_seen.get(k, 0) + 1
                    if short_seen[k] == 1:
                        short_map[k] = v
                    else:
                        short_map.pop(k, None)

    return full_map, short_map


@dataclass
class RouteStructureAgentConfig:
    project_name: str
    project_path: str
    main_pages_json_path: str
    llm_provider_config: dict
    llm_model_name: str

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

        self.memory = PTGMemory()
        self.dependency_graph: Dict[str, List[str]] = {}

        self._visited: Set[str] = set()
        self._count = 0

        self._main_page_ids: Set[str] = set()
        self._route_const_full: Dict[str, str] = {}
        self._route_const_short: Dict[str, str] = {}

    def _resolve_target(self, target: str) -> str:
        t = (target or "").strip()
        if not t:
            return t

        if (t.startswith("\"") and t.endswith("\"")) or (t.startswith("'") and t.endswith("'")):
            t = t[1:-1].strip()

        original = _norm(t)

        mapped = self._route_const_full.get(t)
        if mapped:
            t = mapped
        else:
            m = re.fullmatch(r"(\w+)\.(\w+)", t)
            if m:
                mapped2 = self._route_const_short.get(m.group(2))
                if mapped2:
                    t = mapped2

        t = _strip_ets(t)

        if t and t != original:
            print(f"[RouteStructureAgent] Resolved target: {original} -> {t}")

        return t

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

        code = read_source_file.invoke({"file_path": str(file_path)})
        if not code.strip():
            return

        imports = extract_imports.invoke({"source_code": code})
        resolved_map = resolve_imports_to_files.invoke(
            {"imports": imports, "current_file_path": str(file_path), "ets_root": str(self.ets_root)}
        )
        resolved_files = [str(x) for x in resolved_map.values()]
        self.dependency_graph[_norm(str(file_path))] = [_norm(x) for x in resolved_files]

        print(f"[RouteStructureAgent] Reading & analyzing file: {str(file_path)}")
        user_prompt = build_user_prompt(
            file_path=str(file_path),
            code=code,
            main_pages=main_pages,
            dependency_chain=chain,
            resolved_import_files=resolved_files,
            route_constant_map=self._route_const_full,
        )
        msg = await self.llm.ainvoke([("system", SYSTEM_PROMPT), ("user", user_prompt)])
        edges = _parse_llm_json_list(str(getattr(msg, "content", "") or ""))

        for e in edges:
            component_type = str(e.get("component_type") or "unknown")
            event = str(e.get("event") or "unknown")
            raw_target = str(e.get("target") or "").strip()
            target = self._resolve_target(raw_target)
            if not target:
                continue
            if self.memory.add_edge(
                source_page=main_page_key,
                component_type=component_type,
                event=event,
                target=target,
            ):
                print(f"Found route: {main_page_key} -> {target}")

        nested = find_nested_component_files.invoke(
            {"imports": imports, "current_file_path": str(file_path), "ets_root": str(self.ets_root)}
        )
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
        main_pages = load_main_pages.invoke({"main_pages_json_path": self.config.main_pages_json_path})
        main_pages = [str(x) for x in (main_pages or []) if str(x).strip()]
        main_page_ids = [_strip_ets(p) for p in main_pages]

        self._main_page_ids = {p for p in main_page_ids if p}
        self.memory.init_from_main_pages(sorted(self._main_page_ids))

        self._route_const_full, self._route_const_short = _build_route_constant_maps(
            ets_root=self.ets_root,
            max_files=int(self.config.max_route_files),
            max_chars_per_file=int(self.config.max_route_file_chars),
        )

        for mp_raw, mp_id in zip(main_pages, main_page_ids):
            if not mp_id:
                continue
            mp_file = self.ets_root / _ensure_ets(mp_raw)
            if not mp_file.exists():
                print(f"[RouteStructureAgent] Main page file not found: {str(mp_file)}")
                continue
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
        save_json.invoke({"obj": self.memory.to_json_obj(), "output_path": str(ptg_path)})
        print(f"[RouteStructureAgent] PTG saved: {str(ptg_path)}")

        return self.memory.to_json_obj()

    def run_sync(self) -> Dict[str, List[Dict[str, Any]]]:
        if sys.platform.startswith("win"):
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            except Exception:
                pass
        return asyncio.run(self.run())