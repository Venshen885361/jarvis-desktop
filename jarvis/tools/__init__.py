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
from .vision import analyze_camera_view

# Claude provider 用：computer toolset 已涵蓋滑鼠鍵盤，這裡只給牠做不到 / 做起來很貴的事
CLAUDE_TOOLS = [
    open_application,
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
    open_gesture_selector,
    refresh_app_index,
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
