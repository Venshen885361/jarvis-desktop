"""Provider 工廠。單例，讓 tools 層可以反向呼叫目前這顆模型做影像分析。"""

from __future__ import annotations

from ..config import settings
from .base import Provider

_provider: Provider | None = None


def get_provider() -> Provider:
    global _provider
    if _provider is None:
        if settings.provider == "gemini":
            from .gemini import GeminiProvider

            _provider = GeminiProvider()
        elif settings.provider == "claude":
            from .claude import ClaudeProvider

            _provider = ClaudeProvider()
        else:
            raise RuntimeError(
                f"未知的 JARVIS_PROVIDER：{settings.provider}（可用：claude / gemini）"
            )
    return _provider


def describe_image(data: bytes, media_type: str, prompt: str) -> str:
    return get_provider().describe_image(data, media_type, prompt)


def locate_element(description: str) -> tuple[int, int] | None:
    return get_provider().locate_element(description)


__all__ = ["Provider", "describe_image", "get_provider", "locate_element"]
