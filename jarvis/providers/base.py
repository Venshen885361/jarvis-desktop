"""Provider 介面 + 共用的歷史壓縮邏輯。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import settings


class Provider(ABC):
    name: str = "base"
    model: str = ""

    @abstractmethod
    def run_turn(self, user_text: str) -> str:
        """處理一輪使用者指令（可能包含多次工具呼叫），回傳最終語音回覆文字。"""

    @abstractmethod
    def describe_image(self, data: bytes, media_type: str, prompt: str) -> str:
        """單次影像問答（鏡頭 / 手勢框選用）。不進對話歷史。"""

    def locate_element(self, description: str) -> tuple[int, int] | None:
        """在目前畫面上定位一個元素，回傳真實螢幕座標。不支援時回傳 None。"""
        return None

    def remember(self, user_text: str, reply: str) -> None:  # noqa: B027
        """本機路由處理掉的指令也要進歷史，後續的「接續指令」才接得上。

        刻意不是 abstractmethod：provider 不實作也只是少了記憶，不該擋住它被實例化。
        """

    # ---- 共用的節流工具 ----
    @staticmethod
    def truncate_tool_result(text: str) -> str:
        limit = settings.tool_result_max_chars
        if len(text) <= limit:
            return text
        return text[:limit] + f"…（已截斷，原長度 {len(text)}）"
