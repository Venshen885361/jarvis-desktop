"""平台抽象層。

Windows 與 Linux 的「找出已安裝程式 / 啟動 / 視窗操作 / 輸入法 / 音量」實作差異很大，
全部收斂到這個介面，上層 tools/ 只認識這個介面，不再散落 winreg、os.startfile 之類
的平台專屬呼叫（原版直接 import winreg，在 Linux 上連 import 都會炸）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class AppEntry:
    """一個可啟動的程式：display 是拿去做模糊比對的人類可讀名稱，target 是實際啟動目標。"""

    display: str
    target: str


class WindowRef(ABC):
    """一個看得到的視窗。刻意只暴露我們真的會用到的操作。"""

    title: str

    @abstractmethod
    def activate(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...


class Platform(ABC):
    name: str = "unknown"

    # ---- 應用程式 ----
    @abstractmethod
    def list_apps(self) -> list[AppEntry]:
        """掃描系統上所有可啟動的程式。結果會在上層被快取。"""

    @abstractmethod
    def launch(self, target: str) -> None: ...

    def is_process_running(self, target: str) -> bool:
        return False

    # ---- 視窗 ----
    @abstractmethod
    def find_visible_window(self, keyword: str) -> WindowRef | None: ...

    def list_window_titles(self) -> list[str]:
        return []

    # ---- 系統動作（本機路由用，這些全都不需要打 API）----
    @abstractmethod
    def open_url(self, url: str) -> None: ...

    @abstractmethod
    def set_volume(self, action: str, amount: int = 10) -> str:
        """action: 'up' | 'down' | 'mute'"""

    @abstractmethod
    def lock_screen(self) -> str: ...

    def set_input_method(self, mode: str) -> str:
        return f"Sir, 這個平台（{self.name}）沒有實作輸入法切換。"
