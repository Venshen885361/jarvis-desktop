"""依當前作業系統挑選平台實作。import 時不碰任何平台專屬模組。"""

from __future__ import annotations

import sys

from .base import AppEntry, Platform, WindowRef

_platform: Platform | None = None


def get_platform() -> Platform:
    global _platform
    if _platform is None:
        if sys.platform.startswith("win"):
            from .windows import WindowsPlatform

            _platform = WindowsPlatform()
        elif sys.platform.startswith("linux"):
            from .linux import LinuxPlatform

            _platform = LinuxPlatform()
        else:
            raise RuntimeError(
                f"目前只支援 Windows 與 Linux，偵測到的平台是 {sys.platform}。"
            )
    return _platform


__all__ = ["AppEntry", "Platform", "WindowRef", "get_platform"]
