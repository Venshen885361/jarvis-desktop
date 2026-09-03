"""Device：一台「可以被 JARVIS 操作的裝置」。

大腦（語音、路由、LLM）和手腳（截圖、點擊、開程式）從此分家：
大腦只認識這個介面，不在乎手腳是本機、Tailscale 另一端的電腦，還是 ADB 連著的手機。

工具名稱慣例：
- "computer:<action>"  → Anthropic computer toolset 的 17 個動作（screenshot / left_click / type …）
- 其他名稱             → tools/ 裡的高階工具（open_application / set_volume …）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ImageResult:
    """截圖類動作的回傳。座標換算已經在裝置端做完，大腦只要原樣轉給模型。"""

    b64: str
    media_type: str
    width: int
    height: int


ToolOutput = str | ImageResult


class Device(ABC):
    name: str = "device"
    kind: str = "unknown"      # "local" | "remote" | "android"
    platform: str = "unknown"  # "windows" | "linux" | "android"

    @abstractmethod
    def call(self, tool: str, args: dict) -> ToolOutput:
        """執行一個工具。失敗請丟例外，讓上層照官方規範標成 NOT_EXECUTED。"""

    def ping(self) -> bool:
        return True

    def describe(self) -> str:
        return f"{self.name}（{self.kind} / {self.platform}）"

    def close(self) -> None:  # noqa: B027 — 有些裝置沒有連線要關
        pass
