from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, TextIO


class _TeeStream:
    """将输出同时写入原始流与内存缓冲。"""

    def __init__(self, origin: TextIO, chunks: List[str]) -> None:
        self._origin = origin
        self._chunks = chunks

    def write(self, data: str) -> int:
        s = str(data or "")
        if s:
            self._chunks.append(s)
            self._origin.write(s)
        return len(s)

    def flush(self) -> None:
        self._origin.flush()

    def isatty(self) -> bool:
        return bool(getattr(self._origin, "isatty", lambda: False)())


def _safe_token(s: str, fallback: str = "default") -> str:
    t = (s or "").strip() or fallback
    t = re.sub(r"[^A-Za-z0-9._-]+", "_", t).strip("._-")
    return t or fallback


class RuntimeLogCapture:
    """运行期日志采集器：控制台实时打印，流程结束后统一写文件。"""

    def __init__(
        self,
        *,
        enabled: bool,
        output_dir: str,
        project_name: str,
        model_name: str,
        prefix: str = "agent_workflow_log",
    ) -> None:
        self.enabled = bool(enabled)
        self.output_dir = Path(output_dir)
        self.project_name = project_name
        self.model_name = model_name
        self.prefix = prefix
        self._chunks: List[str] = []
        self._stdout_origin: Optional[TextIO] = None
        self._stderr_origin: Optional[TextIO] = None
        self._started = False

    def start(self) -> None:
        if not self.enabled or self._started:
            return
        self._stdout_origin = sys.stdout
        self._stderr_origin = sys.stderr
        sys.stdout = _TeeStream(self._stdout_origin, self._chunks)  # type: ignore[assignment]
        sys.stderr = _TeeStream(self._stderr_origin, self._chunks)  # type: ignore[assignment]
        self._started = True

    def stop_and_save(self) -> str:
        if not self.enabled:
            return ""
        if self._started:
            if self._stdout_origin is not None:
                sys.stdout = self._stdout_origin
            if self._stderr_origin is not None:
                sys.stderr = self._stderr_origin
            self._started = False

        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pn = _safe_token(self.project_name, fallback="project")
        mn = _safe_token(self.model_name, fallback="model")
        fp = self.output_dir / f"{self.prefix}_{pn}_{mn}_{stamp}.log"
        fp.write_text("".join(self._chunks), encoding="utf-8")
        return str(fp)

