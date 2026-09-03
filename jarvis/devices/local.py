"""LocalDevice：手腳就在這台機器上。桌面單機模式與 agent daemon 都用它。"""

from __future__ import annotations

import sys

from .base import Device, ImageResult, ToolOutput


class LocalDevice(Device):
    kind = "local"

    def __init__(self, name: str = "local") -> None:
        self.name = name
        self.platform = "windows" if sys.platform.startswith("win") else "linux"

    def call(self, tool: str, args: dict) -> ToolOutput:
        if tool.startswith("computer:"):
            from ..tools import computer

            out = computer.execute(tool.split(":", 1)[1], args or {})
            if hasattr(out, "b64"):  # screen.Shot
                return ImageResult(out.b64, out.media_type, out.width, out.height)
            return str(out)

        from ..tools import dispatch

        return dispatch(tool, args or {})
