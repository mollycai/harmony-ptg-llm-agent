from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Set

from agent.utils.route_utils import normalize_path

_OH_PACKAGE_DEP_FILE_RE = re.compile(
    r"""["'](@ohos/[^"']+)["']\s*:\s*["'](?:file:)?([^"']+)["']""",
    re.IGNORECASE,
)

# 常见系统 SDK 包名（不是项目内源码模块）
_SYSTEM_OHOS_MODULES = {
    "router",
    "promptaction",
    "hypium",
    "hilog",
    "abilityaccessctrl",
    "app.ability.common",
    "net.http",
}


class ImportProjectIndex:
    """维护项目级导入索引：alias 映射、模块目录定位、导出符号索引。"""

    def __init__(self, *, ets_root: str, manual_alias_map: Optional[Dict[str, str]] = None) -> None:
        """初始化项目索引，构建自动 alias 与统一 alias 视图。"""
        self.ets_root = Path(ets_root)
        self.manual_alias_map = dict(manual_alias_map or {})
        self.project_roots = self._discover_project_roots(self.ets_root)
        self.auto_alias_map = self._discover_alias_map_from_project(self.project_roots)
        self.all_alias_map = dict(self.auto_alias_map)
        # 手工配置优先级更高
        self.all_alias_map.update(self.manual_alias_map)
        self._module_export_cache: Dict[str, Dict[str, str]] = {}

    @staticmethod
    def is_system_ohos_import(import_path: str) -> bool:
        """判断 @ohos/* 是否属于系统 SDK 包。"""
        ip = normalize_path(import_path)
        if not ip.startswith("@ohos/"):
            return False
        parts = ip.split("/", 2)
        if len(parts) < 2:
            return False
        mod = (parts[1] or "").strip().lower()
        return mod in _SYSTEM_OHOS_MODULES

    @staticmethod
    def probe_ets_file(base: Path) -> Optional[str]:
        """按常见候选规则探测 .ets 文件。"""
        candidates = [
            base,
            base.with_suffix(".ets"),
            base / "index.ets",
            base.with_suffix("") / "index.ets",
        ]
        for c in candidates:
            try:
                if c.exists() and c.is_file() and c.suffix.lower() == ".ets":
                    return str(c)
            except Exception:
                continue
        return None

    def resolve_module_dir(self, import_path: str, *, current_file_path: str) -> Optional[str]:
        """把 import 路径解析为“模块目录”，供符号级查找使用。"""
        ip = normalize_path(import_path)
        cur = Path(current_file_path)

        matched = None
        for prefix in sorted(self.all_alias_map.keys(), key=len, reverse=True):
            if prefix and ip.startswith(prefix):
                matched = prefix
                break
        if matched:
            tail = ip[len(matched) :].lstrip("/")
            alias_base = Path(self.all_alias_map[matched])
            if tail.startswith("src/main/ets/") and normalize_path(str(alias_base)).endswith("/src/main/ets"):
                tail = tail[len("src/main/ets/") :]
            elif tail == "src/main/ets" and normalize_path(str(alias_base)).endswith("/src/main/ets"):
                tail = ""
            base = alias_base / tail if tail else alias_base
            if base.is_file():
                return str(base.parent)
            if base.exists() and base.is_dir():
                return str(base)
            return str(base.parent if tail else base)

        if ip.startswith("./") or ip.startswith("../"):
            base = (cur.parent / ip).resolve()
            if base.is_file():
                return str(base.parent)
            if base.exists() and base.is_dir():
                return str(base)
            return str(base.parent)

        if ip.startswith("@ohos/"):
            body = ip[len("@ohos/") :]
            mod = (body.split("/", 1)[0] or "").strip()
            if not mod:
                return None
            for root in self.project_roots:
                for base in [root / "feature" / mod, root / "features" / mod, root / mod]:
                    if not base.exists() or not base.is_dir():
                        continue
                    ets_base = base / "src" / "main" / "ets"
                    if ets_base.exists() and ets_base.is_dir():
                        return str(ets_base)
                    return str(base)
        return None

    def resolve_ohos_local_module(self, import_path: str) -> Optional[str]:
        """仅针对 @ohos/<module>，尝试按 feature/features 目录回退定位文件。"""
        ip = normalize_path(import_path)
        if not ip.startswith("@ohos/"):
            return None
        body = ip[len("@ohos/") :]
        if not body:
            return None
        segs = body.split("/", 1)
        module = (segs[0] or "").strip()
        tail = (segs[1] if len(segs) > 1 else "").lstrip("/")
        if not module:
            return None

        for root in self.project_roots:
            for base in [root / "feature" / module, root / "features" / module, root / module]:
                if not base.exists() or not base.is_dir():
                    continue
                ets_base = base / "src" / "main" / "ets"
                b = ets_base if (ets_base.exists() and ets_base.is_dir()) else base

                norm_tail = tail
                if norm_tail.startswith("src/main/ets/"):
                    norm_tail = norm_tail[len("src/main/ets/") :]
                target_base = b / norm_tail if norm_tail else b
                resolved = self.probe_ets_file(target_base)
                if resolved:
                    return resolved
        return None

    def build_module_export_map(self, module_dir: str) -> Dict[str, str]:
        """扫描模块目录，建立导出符号到文件路径的索引。"""
        key = normalize_path(module_dir)
        cached = self._module_export_cache.get(key)
        if cached is not None:
            return cached

        out: Dict[str, str] = {}
        root = Path(module_dir)
        if not root.exists() or not root.is_dir():
            self._module_export_cache[key] = out
            return out

        files = list(root.rglob("*.ets"))[:800]
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for sym in self._extract_exported_symbols(text):
                if sym and sym not in out:
                    out[sym] = str(f)
        self._module_export_cache[key] = out
        return out

    @staticmethod
    def _extract_exported_symbols(text: str) -> Set[str]:
        """从文件文本提取 export 出来的符号名集合。"""
        src = text or ""
        out: Set[str] = set()

        decl_re = re.compile(
            r"""\bexport\s+(?:default\s+)?(?:class|struct|function|const|let|var|enum|interface|type)\s+([A-Za-z_]\w*)""",
            re.IGNORECASE,
        )
        for m in decl_re.finditer(src):
            out.add(str(m.group(1) or "").strip())

        block_re = re.compile(r"""\bexport\s*\{([^}]+)\}""", re.IGNORECASE | re.DOTALL)
        for m in block_re.finditer(src):
            inner = str(m.group(1) or "")
            for part in [x.strip() for x in inner.split(",") if x.strip()]:
                if " as " in part:
                    _, alias = [x.strip() for x in part.split(" as ", 1)]
                    if alias:
                        out.add(alias)
                else:
                    out.add(part)
        return {x for x in out if x}

    @staticmethod
    def _discover_project_roots(ets_root: Path) -> List[Path]:
        """从 ets_root 向上推导候选项目根目录。"""
        roots: List[Path] = []
        module_root = ets_root
        if len(ets_root.parts) >= 3 and ets_root.name == "ets":
            try:
                module_root = ets_root.parents[2]
            except Exception:
                module_root = ets_root
        for p in [module_root, *module_root.parents[:6]]:
            if p.exists() and p.is_dir():
                roots.append(p)

        seen: Set[str] = set()
        out: List[Path] = []
        for r in roots:
            k = normalize_path(str(r))
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
        return out

    def _discover_alias_map_from_project(self, project_roots: List[Path]) -> Dict[str, str]:
        """从工程配置文件自动发现 alias 映射。"""
        alias_map: Dict[str, str] = {}
        for root in project_roots:
            self._merge_alias_map(alias_map, self._parse_build_profile_aliases(root / "build-profile.json5"))
            self._merge_alias_map(alias_map, self._parse_oh_package_aliases(root / "oh-package.json5"))
        return alias_map

    @staticmethod
    def _merge_alias_map(dst: Dict[str, str], src: Dict[str, str]) -> None:
        """合并 alias 映射（空键/空值自动跳过）。"""
        for k, v in (src or {}).items():
            if not k or not v:
                continue
            dst[k] = v

    def _parse_build_profile_aliases(self, file_path: Path) -> Dict[str, str]:
        """解析 build-profile.json5 的 modules 列表为 alias。"""
        out: Dict[str, str] = {}
        if not file_path.exists():
            return out
        try:
            txt = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return out

        for obj in self._extract_modules_object_blocks(txt):
            m_name = re.search(r"""["']?name["']?\s*:\s*["']([^"']+)["']""", obj, flags=re.IGNORECASE)
            m_src = re.search(r"""["']?srcPath["']?\s*:\s*["']([^"']+)["']""", obj, flags=re.IGNORECASE)
            mod_name = str(m_name.group(1) if m_name else "").strip()
            src_path = str(m_src.group(1) if m_src else "").strip()
            if not mod_name or not src_path:
                continue
            base = (file_path.parent / src_path).resolve()
            ets_base = (base / "src" / "main" / "ets").resolve()
            target = ets_base if ets_base.exists() else base
            out[f"@ohos/{mod_name}"] = str(target)
            out[f"@ohos/{mod_name}/"] = str(target)
        return out

    def _parse_oh_package_aliases(self, file_path: Path) -> Dict[str, str]:
        """解析 oh-package.json5 的 dependencies 为 alias。"""
        out: Dict[str, str] = {}
        if not file_path.exists():
            return out
        try:
            txt = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return out

        for m in _OH_PACKAGE_DEP_FILE_RE.finditer(txt):
            alias = str(m.group(1) or "").strip()
            rel = str(m.group(2) or "").strip()
            if not alias or not rel:
                continue
            base = (file_path.parent / rel).resolve()
            ets_base = (base / "src" / "main" / "ets").resolve()
            target = ets_base if ets_base.exists() else base
            out[alias] = str(target)
            out[f"{alias}/"] = str(target)
        return out

    @staticmethod
    def _extract_modules_object_blocks(txt: str) -> List[str]:
        """提取 modules: [] 内部的对象块文本。"""
        src = txt or ""
        m = re.search(r"""["']?modules["']?\s*:\s*\[""", src, flags=re.IGNORECASE)
        if not m:
            return []
        i = m.end() - 1
        depth = 0
        end = -1
        for idx in range(i, len(src)):
            ch = src[idx]
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end = idx
                    break
        if end <= i:
            return []
        arr = src[i + 1 : end]

        blocks: List[str] = []
        b_depth = 0
        start = -1
        for idx, ch in enumerate(arr):
            if ch == "{":
                if b_depth == 0:
                    start = idx
                b_depth += 1
            elif ch == "}":
                b_depth -= 1
                if b_depth == 0 and start >= 0:
                    blocks.append(arr[start : idx + 1])
                    start = -1
        return blocks
