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

        # 這幾個是「目標裝置」專屬工具，不能走 dispatch（會再呼叫 run_tool → 本機 → 無限遞迴）
        if tool == "get_ui_tree":
            return "這台是電腦，沒有 UI 樹可讀；請用 computer 的 screenshot 看畫面。"
        if tool == "phone_command":
            return "目前控制的是電腦，不是 iPhone；先用 switch_device 切到 iphone。"

        from ..tools import dispatch

        return dispatch(tool, args or {})
