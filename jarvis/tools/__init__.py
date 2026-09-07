"""工具註冊表。

Gemini provider 直接吃 GEMINI_TOOLS（google-genai SDK 會從 type hint + docstring
自動產生 schema），Claude provider 則把這些包成 Anthropic 的 custom tool，
跟官方 computer toolset 並存 —— computer toolset 負責通用 GUI 操作，
這裡的工具負責「用一次呼叫取代十次點擊」的高階捷徑（開程式、切視窗、調音量），
本身就是一種 token 節流。
"""

from __future__ import annotations

from ..hud import emit_tool
from .apps import (
    focus_window,
    list_windows,
    open_application,
    open_folder,
    open_url,
    refresh_app_index,
)
from .gestures import open_gesture_selector
from .gui import (
    control_gui,
    execute_shell,
    locate_and_type,
    lock_screen,
    read_clipboard,
    set_volume,
    switch_input_method,
    write_clipboard,
)
from .home import home_control, home_list, home_status
from .vision import analyze_camera_view, camera_search, lens_search


def switch_device(name: str) -> str:
    """切換接下來要操作的裝置（電腦 / 手機 / 本機）。

    Args:
        name: 裝置名稱或口語別名，例如「手機」「電腦」「pc」「phone」「local」。
    """
    from ..devices import get_devices

    return get_devices().switch(name)


def list_devices() -> str:
    """列出目前可以控制的裝置，以及現在正在控制哪一台。"""
    from ..devices import get_devices

    return get_devices().describe_all()


def get_ui_tree() -> str:
    """讀取目前控制的手機畫面上的 UI 元件清單（文字、id、座標、可否點擊）。

    比截圖便宜非常多而且精準：先用這個找到目標元件的中心座標再點，
    只有在畫面是圖片 / 遊戲 / 自繪內容、UI 樹讀不到東西時才截圖。
    只有裝了 JARVIS App 的 Android 手機支援；電腦上會回報不支援。
    """
    from ..devices import get_devices

    return str(get_devices().run_tool("get_ui_tree", {}))


def phone_command(command: str) -> str:
    """對 iPhone 下一個捷徑指令（iPhone 無法被看畫面或點擊，只能做這些預先定義的動作）。

    Args:
        command: 第一個字是動詞，其餘是參數：
            "url youtube://"（開 App，常見 App 的 URL scheme：youtube:// line:// instagram:// spotify: maps://）、
            "url https://…"、"message 媽媽 我晚點到"、"call 爸爸"、"navigate 台北車站"、
            "volume 30"、"timer 10"（分鐘）、"say 該出門了"、"shortcut 捷徑名稱 輸入"。
    """
    from ..devices import get_devices

    return str(get_devices().run_tool("phone_command", {"command": command}))


# Claude provider 用：computer toolset 已涵蓋滑鼠鍵盤，這裡只給牠做不到 / 做起來很貴的事
CLAUDE_TOOLS = [
    switch_device,
    list_devices,
    get_ui_tree,
    phone_command,
    open_application,
    open_folder,
    focus_window,
    list_windows,
    open_url,
    switch_input_method,
    set_volume,
    lock_screen,
    read_clipboard,
    write_clipboard,
    execute_shell,
    analyze_camera_view,
    camera_search,
    lens_search,
    open_gesture_selector,
    refresh_app_index,
    home_control,
    home_status,
    home_list,
]

# Gemini provider 用：沒有官方 computer toolset，需要自己的視覺定位與 GUI 工具
GEMINI_TOOLS = CLAUDE_TOOLS + [locate_and_type, control_gui]

_REGISTRY = {fn.__name__: fn for fn in GEMINI_TOOLS}


def dispatch(name: str, args: dict) -> str:
    """依名稱執行工具。未知工具回傳明確錯誤，不要靜默成功。"""
    emit_tool(name, args)
    fn = _REGISTRY.get(name)
    if fn is None:
        return f"未知的工具：{name}"
    try:
        return str(fn(**(args or {})))
    except TypeError as e:
        return f"工具 {name} 參數錯誤：{e}"
    except Exception as e:
        return f"工具 {name} 執行失敗：{e}"


__all__ = ["CLAUDE_TOOLS", "GEMINI_TOOLS", "dispatch"]
