import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from langchain_openai import ChatOpenAI

from llm.prompt.prompt import GLOBAL_PROMPT, RESTRICTIVE_PROMPT, TASK_PROMPT
from llm.prompt.preprocess_prompt import get_preprocess_prompt

# 归一化base_url，确保以/v1结尾
def _normalize_base_url(base_url: str) -> str:
    u = (base_url or "").strip().rstrip("/")
    if not u:
        return u
    lower = u.lower()
    if "/api/" in lower or "/api/v" in lower or re.search(r"/v\d+$", lower):
        return u
    return u + "/v1"

# 构建ChatOpenAI模型
def build_chat_model(config: dict, model_name: str) -> ChatOpenAI:
    api_key = os.environ.get(config["apiKeyEnv"])
    if not api_key:
        raise RuntimeError(f"Missing env {config['apiKeyEnv']}")
    return ChatOpenAI(
        api_key=api_key,
        model=model_name,
        temperature=0,
        base_url=_normalize_base_url(config.get("baseURL", "")),
    )

# 从文本中提取JSON代码块
def _strip_json_code_fence(text: str) -> str:
    if not isinstance(text, str):
        return ""
    t = text.strip()
    t = re.sub(r"^```(?:\s*json)?\s*\n?", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\n?```\s*$", "", t, flags=re.IGNORECASE)
    return t.strip()

# 从main_pages.json中提取所有页面名称
def extract_page_names_from_main_pages(main_pages_file_path: str) -> str:
    p = Path(main_pages_file_path)
    data = json.loads(p.read_text(encoding="utf-8"))
    src = data.get("src")
    if not isinstance(src, list):
        raise ValueError("main_pages.json格式不正确，缺少src数组")
    return ", ".join([str(x) for x in src])

# 安全处理目录名，替换无效字符
def _safe_dir(name: str, fallback: str = "default") -> str:
    s = (name or "").strip() or fallback
    s = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", s)
    s = re.sub(r"[. ]+$", "", s).strip() or fallback
    if re.fullmatch(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])", s, flags=re.IGNORECASE):
        s = "_" + s
    return s

# 写入完整提示到文件
def write_full_prompt_to_file(full_prompt: str, *, project_name: str, model: str) -> str:
    base = Path(__file__).resolve().parent / "prompt" / _safe_dir(project_name)
    base.mkdir(parents=True, exist_ok=True)
    out = base / f"full_prompt_{model}.txt"
    out.write_text(full_prompt, encoding="utf-8")
    return str(out)

# 写入PTG结果到文件
def write_ptg_result_to_file(raw_text: str, *, project_name: str, model_name: str) -> dict[str, str]:
    completion_text = _strip_json_code_fence(raw_text)
    base = Path(__file__).resolve().parent / "result" / _safe_dir(project_name)
    base.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = base / f"ptg_{model_name}_{stamp}.json"

    text_to_write = completion_text
    try:
        parsed = json.loads(completion_text)
        text_to_write = json.dumps(parsed, ensure_ascii=False, indent=2)
    except Exception:
        pass

    out.write_text(text_to_write, encoding="utf-8")
    return {"ptgOutputPath": str(out), "completionText": completion_text}

# 检查文件是否为ETS文件，且路径中包含目标目录
def _is_target_ets(relative_path: str) -> bool:
    targets = ("pages", "route", "viewModel", "formview", "view", "components")
    rp = (relative_path or "").replace("\\", "/")
    return rp.endswith(".ets") and any(t in rp for t in targets)

# 递归扫描HarmonyOS项目目录，异步处理ETS文件
async def scan_harmonyos_project(
    project_path: str,
    *,
    preprocess_ets: Optional[Callable[[str, dict[str, Any]], Awaitable[str]]] = None,
) -> dict[str, Any]:
    base = Path(project_path) / "src" / "main" / "ets"
    if not base.exists():
        raise RuntimeError(f"目标目录不存在: {base}")

    async def walk(p: Path, rel: str) -> Any:
        if p.is_file():
            if _is_target_ets(rel):
                content = p.read_text(encoding="utf-8", errors="ignore")
                return await preprocess_ets(content, {"filePath": str(p), "relativePath": rel}) if preprocess_ets else content
            return ""
        out: dict[str, Any] = {}
        for child in p.iterdir():
            child_rel = f"{rel}/{child.name}" if rel else child.name
            out[child.name] = await walk(child, child_rel)
        return out

    return await walk(base, "")

# 异步预处理提示，使用LLM对ETS代码进行格式化预处理
async def preprocess_prompt(llm: ChatOpenAI, code: str, model: str) -> str:
    if not code or not code.strip():
        return ""

    prompt = get_preprocess_prompt(code)
    try:
        started_at = time.perf_counter()
        msg = await llm.ainvoke([("user", prompt)])
        duration_ms = int((time.perf_counter() - started_at) * 1000)

        result = str(getattr(msg, "content", "") or "")
        if "```" in result:
            result = re.sub(r"^```(?:typescript|ts)?\s*", "", result, flags=re.IGNORECASE).strip()
            result = re.sub(r"\s*```$", "", result).strip()

        print(
            f"[preprocessPrompt] 完成一次预处理：model={model}, inputChars={len(code)}, outputChars={len(result)}, durationMs={duration_ms}"
        )
        return result
    except Exception as error:
        print(f"Error in preprocessPrompt: {error}")
        return f"// [PREPROCESS ERROR] {error}"

# 递归展平上下文，将嵌套字典转换为路径-代码对列表
def _flatten_context(node: Any, prefix: str = "") -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if isinstance(node, str):
        if node.strip() and prefix:
            out.append({"path": prefix, "code": node})
        return out
    if isinstance(node, dict):
        for k in sorted(node.keys()):
            child = node[k]
            child_prefix = f"{prefix}/{k}" if prefix else str(k)
            out.extend(_flatten_context(child, child_prefix))
    return out

# 上下文分块，将文件列表按字符数分块（注意按文件边界chunk）
def _chunk_context(files: list[dict[str, str]], max_chars: int) -> list[str]:
    chunks: list[list[dict[str, str]]] = []
    cur: list[dict[str, str]] = []
    cur_chars = 0
    for f in files:
        item = {"path": f.get("path", ""), "code": f.get("code", "")}
        item_chars = len(item["path"]) + len(item["code"]) + 64
        if cur and cur_chars + item_chars > max_chars:
            chunks.append(cur)
            cur = []
            cur_chars = 0
        cur.append(item)
        cur_chars += item_chars
    if cur:
        chunks.append(cur)
    return [json.dumps(c, ensure_ascii=False) for c in chunks]

# 异步运行长提示对话
async def run_long_prompt_conversation(options: dict) -> dict[str, Any]:
    llm: ChatOpenAI = options["llm"]
    preprocess_llm: Optional[ChatOpenAI] = options.get("preprocessLlm")
    project_name: str = options["projectName"]
    project_path: str = options["projectPath"]
    main_pages_path: str = options["projectMainPagePath"]
    chunk_size: int = int(options.get("chunkSize", 8000))
    model: str = options.get("model", "deepseek-chat")
    preprocess_model: str = options.get("preprocessModel", "deepseek-chat")
    enable_preprocess: bool = bool(options.get("enablePreprocess", True))

    async def preprocess_ets(code: str, meta: dict[str, Any]) -> str:
        _ = meta
        return await preprocess_prompt(preprocess_llm or llm, code, preprocess_model)

    directory = await scan_harmonyos_project(project_path, preprocess_ets=preprocess_ets if enable_preprocess else None)
    files = _flatten_context(directory)
    context_chunks = _chunk_context(files, chunk_size)

    pages = extract_page_names_from_main_pages(main_pages_path)
    filled_global = GLOBAL_PROMPT.replace("<N>", project_name).replace("<X>", pages)
    filled_restrict = RESTRICTIVE_PROMPT.replace("<X>", pages)

    system_content = f"{filled_global}\n\n{filled_restrict}"
    messages: list[tuple[str, str]] = [("system", system_content), ("user", TASK_PROMPT)]
    for i, c in enumerate(context_chunks):
        messages.append(("user", f"<context_chunk {i+1}/{len(context_chunks)}>\n{c}\n</context_chunk>"))

    full_prompt = "\n\n".join([filled_global, TASK_PROMPT, filled_restrict, *[f"<context_chunk {i+1}/{len(context_chunks)}>\n{c}\n</context_chunk>" for i, c in enumerate(context_chunks)]])
    full_prompt_path = write_full_prompt_to_file(full_prompt, project_name=project_name, model=model)

    resp = await llm.ainvoke(messages)
    raw = str(getattr(resp, "content", "") or "")
    saved = write_ptg_result_to_file(raw, project_name=project_name, model_name=model)

    return {
        "completionText": saved["completionText"],
        "fullPromptPath": full_prompt_path,
        "fullPromptLength": len(full_prompt),
        "messageCount": len(messages),
        "ptgOutputPath": saved["ptgOutputPath"],
    }