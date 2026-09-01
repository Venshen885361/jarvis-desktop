"""基本 GUI／系統操作工具。

這些是 Gemini provider 的工具清單，也是本機路由（完全不打 API）會直接呼叫的函式。
Claude provider 走的是官方 computer toolset，不需要這一組視覺定位工具。
"""

from __future__ import annotations

import shlex
import subprocess

from ..config import settings
from ..platform_ import get_platform

# execute_shell 的白名單。預設模式下只准跑這些明顯無害的指令，
# 想放行全部要自己設 JARVIS_ALLOW_SHELL=1，並且知道自己在做什麼。
_SAFE_SHELL_PREFIXES = (
    "echo", "date", "whoami", "hostname", "uptime", "df", "free",
    "ls", "dir", "pwd", "cat", "type", "ping", "ipconfig", "ip",
)


def switch_input_method(mode: str = "english") -> str:
    """切換輸入法模式。

    Args:
        mode: 'english' / 'chinese' / 'toggle_lang'
    """
    return get_platform().set_input_method(mode)


def control_gui(action: str, x: int = 0, y: int = 0, text: str = "", key: str = "") -> str:
    """直接操控滑鼠與鍵盤。

    Args:
        action: 'click' / 'double_click' / 'right_click' / 'type' / 'press' / 'shortcut' / 'scroll'
        x: 點擊的螢幕 X 座標（0 表示用目前游標位置）
        y: 點擊的螢幕 Y 座標
        text: action 為 'type' 時要輸入的文字
        key: action 為 'press' 時的按鍵名，或 'shortcut' 時的組合鍵如 'ctrl+s'
    """
    try:
        import pyautogui

        pyautogui.FAILSAFE = True
        if action == "click":
            pyautogui.click(x, y) if (x > 0 and y > 0) else pyautogui.click()
        elif action == "double_click":
            pyautogui.doubleClick()
        elif action == "right_click":
            pyautogui.rightClick()
        elif action == "scroll":
            pyautogui.scroll(y or 300)
        elif action == "type":
            import pyperclip

            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
        elif action == "press":
            pyautogui.press(key)
        elif action == "shortcut":
            pyautogui.hotkey(*[k.strip() for k in key.split("+")])
        else:
            return f"不支援的動作：{action}"
        return f"GUI 動作 '{action}' 已完成。"
    except Exception as e:
        return f"GUI 動作失敗：{e}"


def locate_and_type(target_description: str, text_to_type: str, auto_enter: bool = False) -> str:
    """看一眼目前螢幕，找出使用者描述的輸入位置，點下去並輸入文字。

    Args:
        target_description: 位置描述，例如「網址列」「Google 搜尋框」「記事本編輯區」
        text_to_type: 要輸入的文字
        auto_enter: 輸入完是否按 Enter
    """
    from ..providers import locate_element

    try:
        import pyautogui
        import pyperclip

        pyautogui.press("escape")
        point = locate_element(target_description)
        if point is None:
            return (
                f"Sir, 畫面上找不到「{target_description}」，"
                "可能視窗還沒開好或不在畫面上。"
            )
        pyautogui.click(*point)
        pyautogui.sleep(0.2)
        pyperclip.copy(text_to_type)
        pyautogui.hotkey("ctrl", "v")
        pyautogui.sleep(0.2)
        if auto_enter:
            pyautogui.press("enter")
        return f"Sir, 已在「{target_description}」輸入並執行。"
    except Exception as e:
        return f"輸入失敗：{e}"


def execute_shell(command: str) -> str:
    """在本機執行一行 shell 指令。

    預設只允許白名單內的唯讀指令；要完全放行必須自行設定 JARVIS_ALLOW_SHELL=1。

    Args:
        command: 要執行的指令
    """
    cmd = command.strip()
    if not settings.allow_shell:
        head = cmd.split()[0].lower() if cmd.split() else ""
        if head not in _SAFE_SHELL_PREFIXES:
            return (
                f"Sir, 基於安全考量，「{head}」不在預設白名單內。"
                "要放行完整 shell 權限請設定環境變數 JARVIS_ALLOW_SHELL=1。"
            )
    try:
        args = cmd if get_platform().name == "windows" else shlex.split(cmd)
        r = subprocess.run(
            args,
            shell=(get_platform().name == "windows"),
            capture_output=True,
            text=True,
            timeout=20,
        )
        out = (r.stdout or r.stderr or "").strip()
        return out[:2000] if out else "指令執行完成（沒有輸出）。"
    except Exception as e:
        return f"指令執行失敗：{e}"


def set_volume(action: str, amount: int = 10) -> str:
    """調整系統音量。

    Args:
        action: 'up' / 'down' / 'mute'
        amount: 調整幅度（百分比）
    """
    return get_platform().set_volume(action, amount)


def lock_screen() -> str:
    """鎖定螢幕。"""
    return get_platform().lock_screen()


def read_clipboard() -> str:
    """讀取目前剪貼簿的內容。"""
    try:
        import pyperclip

        content = pyperclip.paste()
        return f"剪貼簿內容：{content[:1000]}" if content else "剪貼簿是空的。"
    except Exception as e:
        return f"讀取剪貼簿失敗：{e}"


def write_clipboard(text: str) -> str:
    """把文字寫進剪貼簿。

    Args:
        text: 要複製的文字
    """
    try:
        import pyperclip

        pyperclip.copy(text)
        return "Sir, 已複製到剪貼簿。"
    except Exception as e:
        return f"寫入剪貼簿失敗：{e}"
