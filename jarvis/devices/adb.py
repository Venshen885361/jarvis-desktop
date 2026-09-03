"""AdbDevice：用 ADB 操作 Android 手機。手機上不用裝任何 agent。

Android 11+ 內建「無線偵錯」：開發人員選項 → 無線偵錯 → 配對一次，之後
`adb connect <ip>:<port>` 就能連。Anthropic computer toolset 的動作幾乎能
一對一翻成 `adb shell input ...`：

  screenshot        → adb exec-out screencap -p
  left_click        → input tap x y
  left_click_drag   → input swipe x1 y1 x2 y2 600
  scroll            → input swipe（反方向）
  type              → input text（ASCII）/ ADBKeyboard 廣播（中文）
  key               → input keyevent KEYCODE_*

座標：截圖會被壓到長邊 1024 才給模型，模型回的座標要乘回真實解析度，
邏輯跟 tools/computer.py 一樣，只是這裡的「真實解析度」是手機的。

已知限制（誠實版）：
- `input text` 不吃非 ASCII。中文輸入要裝 ADBKeyboard 這個 IME
  （https://github.com/senzhk/ADBKeyBoard）並設成目前輸入法，沒裝會明確報錯。
- 沒有 hover / 右鍵 / 滾輪的概念；right_click 對應長按，scroll 用滑動模擬。
"""

from __future__ import annotations

import base64
import io
import re
import shutil
import subprocess
import time

from ..config import settings
from .base import Device, ImageResult, ToolOutput

# X11 keysym（模型用的）→ Android KEYCODE
_KEYCODES = {
    "return": "KEYCODE_ENTER", "enter": "KEYCODE_ENTER", "kp_enter": "KEYCODE_ENTER",
    "escape": "KEYCODE_BACK", "back": "KEYCODE_BACK",
    "home": "KEYCODE_HOME", "super": "KEYCODE_HOME", "win": "KEYCODE_HOME",
    "tab": "KEYCODE_TAB", "space": "KEYCODE_SPACE",
    "backspace": "KEYCODE_DEL", "delete": "KEYCODE_FORWARD_DEL",
    "up": "KEYCODE_DPAD_UP", "down": "KEYCODE_DPAD_DOWN",
    "left": "KEYCODE_DPAD_LEFT", "right": "KEYCODE_DPAD_RIGHT",
    "page_up": "KEYCODE_PAGE_UP", "page_down": "KEYCODE_PAGE_DOWN",
    "volumeup": "KEYCODE_VOLUME_UP", "volumedown": "KEYCODE_VOLUME_DOWN",
    "volumemute": "KEYCODE_VOLUME_MUTE", "power": "KEYCODE_POWER",
    "playpause": "KEYCODE_MEDIA_PLAY_PAUSE", "nexttrack": "KEYCODE_MEDIA_NEXT",
    "prevtrack": "KEYCODE_MEDIA_PREVIOUS", "menu": "KEYCODE_MENU",
    "app_switch": "KEYCODE_APP_SWITCH",
}

# 常見 App 的口語名稱 → package。找不到會退回 pm list packages 的模糊比對。
_APP_ALIASES = {
    "line": "jp.naver.line.android",
    "youtube": "com.google.android.youtube",
    "chrome": "com.android.chrome",
    "地圖": "com.google.android.apps.maps",
    "maps": "com.google.android.apps.maps",
    "google map": "com.google.android.apps.maps",
    "instagram": "com.instagram.android",
    "ig": "com.instagram.android",
    "discord": "com.discord",
    "spotify": "com.spotify.music",
    "gmail": "com.google.android.gm",
    "設定": "com.android.settings",
    "settings": "com.android.settings",
    "相機": "com.android.camera",
    "camera": "com.android.camera",
    "telegram": "org.telegram.messenger",
    "twitter": "com.twitter.android",
    "x": "com.twitter.android",
    "threads": "com.instagram.barcelona",
}


class AdbDevice(Device):
    kind = "android"
    platform = "android"

    def __init__(self, name: str, target: str = "") -> None:
        """target: 'ip:port'（無線）或 USB 序號；空字串 = 唯一一台連著的裝置。"""
        self.name = name
        self.target = target
        self._last_scale = 1.0
        self._last_offset = (0, 0)
        self._screen_size: tuple[int, int] | None = None
        if not shutil.which("adb"):
            raise RuntimeError("找不到 adb，請安裝 Android platform-tools 並加入 PATH。")
        if target and ":" in target:
            code, out = self._run_adb(["connect", target], serial=False, timeout=15)
            if "connected" not in out.lower():
                raise ConnectionError(f"adb connect {target} 失敗：{out}")

    # ------------------------------------------------------------------ 基礎
    def _run_adb(self, args: list[str], serial: bool = True, timeout: float = 20,
                 binary: bool = False):
        cmd = ["adb"]
        if serial and self.target:
            cmd += ["-s", self.target]
        cmd += args
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if binary:
            return r.returncode, r.stdout
        out = (r.stdout or r.stderr or b"").decode("utf-8", "replace").strip()
        return r.returncode, out

    def _shell(self, *args: str, timeout: float = 20) -> str:
        code, out = self._run_adb(["shell", *args], timeout=timeout)
        if code != 0:
            raise RuntimeError(f"adb shell {' '.join(args)} 失敗：{out}")
        return out

    def ping(self) -> bool:
        try:
            return self._shell("echo", "ok") == "ok"
        except Exception:
            return False

    def _size(self) -> tuple[int, int]:
        if self._screen_size is None:
            out = self._shell("wm", "size")  # "Physical size: 1080x2400"
            m = re.search(r"(\d+)x(\d+)", out)
            self._screen_size = (int(m.group(1)), int(m.group(2))) if m else (1080, 2400)
        return self._screen_size

    def _coord(self, value) -> tuple[int, int]:
        """模型座標（壓縮後的截圖空間）→ 手機真實像素。"""
        x = int(round(value[0] / self._last_scale)) + self._last_offset[0]
        y = int(round(value[1] / self._last_scale)) + self._last_offset[1]
        return x, y

    # ------------------------------------------------------------------ 截圖
    def _screenshot(self, region=None) -> ImageResult:
        from PIL import Image

        from ..screen import compress

        code, png = self._run_adb(["exec-out", "screencap", "-p"], binary=True, timeout=30)
        if code != 0 or not png:
            raise RuntimeError("adb screencap 失敗，手機可能已斷線或螢幕鎖定。")
        img = Image.open(io.BytesIO(png)).convert("RGB")
        offset = (0, 0)
        if region:
            x0, y0 = self._coord(region[0:2])
            x1, y1 = self._coord(region[2:4])
            img = img.crop((x0, y0, x1, y1))
            offset = (x0, y0)
        shot = compress(img, offset)
        self._last_scale = shot.scale
        self._last_offset = shot.offset
        return ImageResult(shot.b64, shot.media_type, shot.width, shot.height)

    # ------------------------------------------------------------------ computer 動作
    def _computer(self, action: str, p: dict) -> ToolOutput:
        time.sleep(settings.action_delay)

        if action == "screenshot":
            return self._screenshot()
        if action == "zoom":
            return self._screenshot(region=p.get("region"))

        if action in ("left_click", "double_click", "triple_click", "middle_click"):
            x, y = self._coord(p["coordinate"]) if p.get("coordinate") else self._center()
            taps = {"double_click": 2, "triple_click": 3}.get(action, 1)
            for _ in range(taps):
                self._shell("input", "tap", str(x), str(y))
                time.sleep(0.08)
            return "OK"

        if action == "right_click":  # Android 沒有右鍵，對應長按
            x, y = self._coord(p["coordinate"]) if p.get("coordinate") else self._center()
            self._shell("input", "swipe", str(x), str(y), str(x), str(y), "800")
            return "OK"

        if action == "left_click_drag":
            x1, y1 = self._coord(p["start_coordinate"])
            x2, y2 = self._coord(p["coordinate"])
            self._shell("input", "swipe", str(x1), str(y1), str(x2), str(y2), "600")
            return "OK"

        if action == "scroll":
            x, y = self._coord(p["coordinate"]) if p.get("coordinate") else self._center()
            amount = int(p.get("scroll_amount", 3)) * 250
            d = p.get("scroll_direction", "down")
            # 內容往下捲 = 手指往上滑
            dx, dy = {"down": (0, -amount), "up": (0, amount),
                      "left": (-amount, 0), "right": (amount, 0)}.get(d, (0, -amount))
            self._shell("input", "swipe", str(x), str(y), str(x + dx), str(y + dy), "300")
            return "OK"

        if action == "mouse_move":
            return "OK（Android 沒有游標，已略過）"

        if action == "cursor_position":
            return "[0, 0]（Android 沒有游標）"

        if action == "type":
            return self._type(p.get("text", ""))

        if action == "key":
            keys = [k.strip().lower() for k in str(p.get("text", "")).split("+") if k.strip()]
            repeat = max(1, min(int(p.get("repeat", 1) or 1), 100))
            for _ in range(repeat):
                for k in keys:
                    code = _KEYCODES.get(k)
                    if code is None and len(k) == 1 and k.isalnum():
                        code = f"KEYCODE_{k.upper()}"
                    if code is None:
                        raise ValueError(f"Android 不支援按鍵：{k}")
                    self._shell("input", "keyevent", code)
            return "OK"

        if action in ("hold_key", "wait"):
            time.sleep(min(float(p.get("duration", 1)), 300))
            return "OK"

        if action in ("left_mouse_down", "left_mouse_up"):
            return "OK（Android 以 swipe 取代按住/放開，已略過）"

        raise ValueError(f"不支援的 computer action：{action}")

    def _center(self) -> tuple[int, int]:
        w, h = self._size()
        return w // 2, h // 2

    def _type(self, text: str) -> str:
        if not text:
            return "OK"
        if text.isascii():
            # input text 用 %s 代表空白，其他 shell 特殊字元要跳脫
            escaped = re.sub(r"([\\\"'`$&|;()<>])", r"\\\1", text).replace(" ", "%s")
            self._shell("input", "text", escaped)
            return "OK"
        # 非 ASCII：需要 ADBKeyboard 這個 IME
        ime_list = self._shell("ime", "list", "-s")
        if "com.android.adbkeyboard/.AdbIME" not in ime_list:
            raise RuntimeError(
                "輸入中文需要在手機上安裝 ADBKeyboard（github.com/senzhk/ADBKeyBoard）"
                "並在設定裡啟用；目前沒偵測到。"
            )
        self._shell("ime", "set", "com.android.adbkeyboard/.AdbIME")
        b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        self._shell("am", "broadcast", "-a", "ADB_INPUT_B64", "--es", "msg", b64)
        return "OK"

    # ------------------------------------------------------------------ 高階工具
    def _find_package(self, query: str) -> str | None:
        q = query.strip().lower()
        if q in _APP_ALIASES:
            return _APP_ALIASES[q]
        out = self._shell("pm", "list", "packages", "-3")
        pkgs = [line.replace("package:", "").strip() for line in out.splitlines()]
        hits = [p for p in pkgs if q.replace(" ", "") in p.lower()]
        if hits:
            hits.sort(key=len)
            return hits[0]
        return None

    def _tool(self, tool: str, a: dict) -> str:
        if tool == "open_application":
            pkg = self._find_package(a.get("app_name", ""))
            if not pkg:
                return f"Sir, 手機上找不到「{a.get('app_name')}」這個 App。"
            self._shell("monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1")
            return f"Sir, 已在手機上開啟 {pkg.split('.')[-1]}。"
        if tool == "open_url":
            url = a.get("url", "")
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            self._shell("am", "start", "-a", "android.intent.action.VIEW", "-d", url)
            return f"Sir, 已在手機上開啟 {url}。"
        if tool == "set_volume":
            key = {"up": "KEYCODE_VOLUME_UP", "down": "KEYCODE_VOLUME_DOWN"}.get(
                a.get("action", "up"), "KEYCODE_VOLUME_MUTE"
            )
            for _ in range(max(1, int(a.get("amount", 10)) // 5)):
                self._shell("input", "keyevent", key)
            return "Sir, 手機音量已調整。"
        if tool == "lock_screen":
            self._shell("input", "keyevent", "KEYCODE_SLEEP")
            return "Sir, 手機螢幕已關閉。"
        if tool == "list_windows":
            out = self._shell("dumpsys", "activity", "activities")
            m = re.search(r"mResumedActivity.*?\s(\S+)/(\S+)", out)
            return f"手機目前前景 App：{m.group(1)}" if m else "無法判斷手機前景 App。"
        if tool == "focus_window":
            return self._tool("open_application", {"app_name": a.get("keyword", "")})
        if tool == "read_clipboard":
            return "Sir, Android 10 以上不允許背景讀取剪貼簿。"
        if tool == "write_clipboard":
            return "Sir, 這台手機沒有可用的剪貼簿寫入通道（需要 ADBKeyboard）。"
        if tool == "switch_input_method":
            return "Sir, 手機的輸入法切換請直接在鍵盤上操作。"
        if tool == "execute_shell":
            if not settings.allow_shell:
                return "Sir, 手機 shell 預設關閉（JARVIS_ALLOW_SHELL=1 才放行）。"
            return self._shell(*a.get("command", "").split())[:2000]
        if tool in ("analyze_camera_view", "camera_search", "lens_search", "open_gesture_selector"):
            return "Sir, 鏡頭類工具請切回電腦或 Pi 本機執行。"
        return f"Sir, 手機不支援工具 {tool}。"

    # ------------------------------------------------------------------
    def call(self, tool: str, args: dict) -> ToolOutput:
        if tool.startswith("computer:"):
            return self._computer(tool.split(":", 1)[1], args or {})
        return self._tool(tool, args or {})
