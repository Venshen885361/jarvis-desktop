"""Anthropic computer-use toolset 的本機執行器。

模型會回傳 member action（left_click / type / key / scroll ...），這裡負責真的
用 pyautogui 做出來。兩個關鍵細節：

1. 座標系：computer_toolset_20260801 不再接受 display_width_px，模型完全依
   「牠看到的那張截圖」的像素座標下指令。我們為了省 token 會把截圖縮小，
   所以每張送出去的截圖都記在 _last_shot，動作座標一律經過 Shot.to_screen()
   換算回真實螢幕像素，否則點擊會整個偏掉。
2. 按鍵名稱：模型用 X11 命名（Return / Escape / Page_Down / ctrl+s），
   pyautogui 用自己的一套，中間需要對照表。

工具規格來源：
https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool
"""

from __future__ import annotations

import time

from ..config import settings
from ..screen import Shot, capture

_last_shot: Shot | None = None

# X11 keysym -> pyautogui 鍵名
_KEY_MAP = {
    "return": "enter",
    "kp_enter": "enter",
    "escape": "esc",
    "prior": "pageup",
    "next": "pagedown",
    "page_up": "pageup",
    "page_down": "pagedown",
    "bracketleft": "[",
    "bracketright": "]",
    "minus": "-",
    "equal": "=",
    "plus": "+",
    "comma": ",",
    "period": ".",
    "slash": "/",
    "backslash": "\\",
    "semicolon": ";",
    "apostrophe": "'",
    "grave": "`",
    "super": "win",
    "super_l": "win",
    "meta": "win",
    "control": "ctrl",
    "control_l": "ctrl",
    "alt_l": "alt",
    "shift_l": "shift",
    "kp_add": "add",
    "kp_subtract": "subtract",
}


def _map_keys(text: str) -> list[str]:
    parts = [p.strip() for p in str(text).split("+") if p.strip()]
    return [_KEY_MAP.get(p.lower(), p.lower()) for p in parts]


def _pg():
    import pyautogui

    pyautogui.FAILSAFE = True  # 滑鼠移到左上角 = 緊急中斷
    return pyautogui


def _coord(value) -> tuple[int, int]:
    """把模型座標換算成真實螢幕座標。"""
    x, y = value[0], value[1]
    if _last_shot is not None:
        return _last_shot.to_screen(x, y)
    return int(x), int(y)


def _with_modifiers(pg, modifiers: str | None):
    """text 參數在點擊類動作裡代表「按住的修飾鍵」。"""
    keys = _map_keys(modifiers) if modifiers else []
    return keys


def take_screenshot(region: tuple[int, int, int, int] | None = None) -> Shot:
    """擷取畫面並記住縮放比例，供後續座標換算使用。"""
    global _last_shot
    shot = capture(region=region)
    _last_shot = shot
    return shot


def execute(name: str, params: dict):
    """執行一個 computer member action。

    Returns:
        Shot（截圖類動作）或 str（其他動作）。丟出例外代表失敗，
        上層會照官方規範把後續動作標成 NOT_EXECUTED。
    """
    pg = _pg()
    time.sleep(settings.action_delay)

    if name == "screenshot":
        return take_screenshot()

    if name == "zoom":
        region = params.get("region") or []
        if len(region) != 4:
            raise ValueError("zoom 需要 region=[x0,y0,x1,y1]")
        # region 是模型座標，換算回真實螢幕座標再擷取（並且不縮放，才叫 zoom）
        x0, y0 = _coord(region[0:2])
        x1, y1 = _coord(region[2:4])
        return take_screenshot(region=(x0, y0, x1, y1))

    if name in ("left_click", "right_click", "middle_click", "double_click", "triple_click"):
        mods = _with_modifiers(pg, params.get("text"))
        coord = params.get("coordinate")
        if coord:
            pg.moveTo(*_coord(coord))
        for k in mods:
            pg.keyDown(k)
        try:
            button = {"right_click": "right", "middle_click": "middle"}.get(name, "left")
            clicks = {"double_click": 2, "triple_click": 3}.get(name, 1)
            pg.click(button=button, clicks=clicks, interval=0.06)
        finally:
            for k in reversed(mods):
                pg.keyUp(k)
        return "OK"

    if name == "left_click_drag":
        start = params.get("start_coordinate")
        end = params.get("coordinate")
        if not start or not end:
            raise ValueError("left_click_drag 需要 start_coordinate 與 coordinate")
        pg.moveTo(*_coord(start))
        pg.mouseDown()
        pg.moveTo(*_coord(end), duration=0.25)
        pg.mouseUp()
        return "OK"

    if name == "mouse_move":
        pg.moveTo(*_coord(params["coordinate"]))
        return "OK"

    if name == "left_mouse_down":
        pg.mouseDown()
        return "OK"

    if name == "left_mouse_up":
        pg.mouseUp()
        return "OK"

    if name == "cursor_position":
        x, y = pg.position()
        if _last_shot is not None:
            # 回報成模型座標系，牠才對得起來
            x = int(round((x - _last_shot.offset[0]) * _last_shot.scale))
            y = int(round((y - _last_shot.offset[1]) * _last_shot.scale))
        return f"[{x}, {y}]"

    if name == "scroll":
        coord = params.get("coordinate")
        if coord:
            pg.moveTo(*_coord(coord))
        mods = _with_modifiers(pg, params.get("text"))
        for k in mods:
            pg.keyDown(k)
        try:
            amount = int(params.get("scroll_amount", 3))
            direction = params.get("scroll_direction", "down")
            if direction in ("up", "down"):
                pg.scroll(amount * 120 * (1 if direction == "up" else -1))
            else:
                pg.hscroll(amount * 120 * (1 if direction == "right" else -1))
        finally:
            for k in reversed(mods):
                pg.keyUp(k)
        return "OK"

    if name == "type":
        text = params.get("text", "")
        # 走剪貼簿貼上而不是逐字模擬按鍵：中文 / emoji 在 pyautogui.write 下會漏字，
        # 而且貼上是一次完成，比逐字快非常多。
        try:
            import pyperclip

            backup = None
            try:
                backup = pyperclip.paste()
            except Exception:
                pass
            pyperclip.copy(text)
            pg.hotkey("ctrl", "v")
            time.sleep(0.15)
            if backup is not None:
                try:
                    pyperclip.copy(backup)
                except Exception:
                    pass
        except Exception:
            pg.write(text, interval=0.01)
        return "OK"

    if name == "key":
        keys = _map_keys(params.get("text", ""))
        repeat = int(params.get("repeat", 1) or 1)
        for _ in range(max(1, min(repeat, 100))):
            if len(keys) == 1:
                pg.press(keys[0])
            else:
                pg.hotkey(*keys)
        return "OK"

    if name == "hold_key":
        keys = _map_keys(params.get("text", ""))
        duration = min(float(params.get("duration", 1)), 300.0)
        for k in keys:
            pg.keyDown(k)
        time.sleep(duration)
        for k in reversed(keys):
            pg.keyUp(k)
        return "OK"

    if name == "wait":
        time.sleep(min(float(params.get("duration", 1)), 300.0))
        return "OK"

    raise ValueError(f"不支援的 computer action：{name}")
