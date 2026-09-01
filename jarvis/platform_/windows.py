"""Windows 實作：開始功能表 .lnk + 登錄檔 App Paths + pygetwindow。"""

from __future__ import annotations

import ctypes
import os
import subprocess

from .base import AppEntry, Platform, WindowRef

_FALLBACK_BUILTIN = [
    ("記事本", "notepad.exe"),
    ("Notepad", "notepad.exe"),
    ("小算盤", "calc.exe"),
    ("計算機", "calc.exe"),
    ("Calculator", "calc.exe"),
    ("命令提示字元", "cmd.exe"),
    ("Command Prompt", "cmd.exe"),
    ("檔案總管", "explorer.exe"),
    ("File Explorer", "explorer.exe"),
]


class _WinWindow(WindowRef):
    def __init__(self, w):
        self._w = w
        self.title = w.title

    def activate(self) -> None:
        try:
            self._w.activate()
        except Exception:
            # 有些視窗需要先還原才能 activate
            try:
                self._w.restore()
                self._w.activate()
            except Exception:
                pass

    def close(self) -> None:
        try:
            self._w.close()
        except Exception:
            pass


class WindowsPlatform(Platform):
    name = "windows"

    # ---- 應用程式 ----
    def list_apps(self) -> list[AppEntry]:
        entries: list[AppEntry] = []
        entries.extend(self._start_menu_shortcuts())
        try:
            entries.extend(self._app_paths_registry())
        except Exception as e:
            print(f"[app index] 讀取 App Paths 失敗（略過）：{e}")
        entries.extend(AppEntry(n, t) for n, t in _FALLBACK_BUILTIN)
        return entries

    @staticmethod
    def _start_menu_shortcuts() -> list[AppEntry]:
        roots = []
        # PROGRAMDATA = 所有使用者的開始功能表，APPDATA = 目前使用者的
        for env in ("PROGRAMDATA", "APPDATA"):
            base = os.environ.get(env)
            if base:
                roots.append(
                    os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs")
                )
        out: list[AppEntry] = []
        for root in roots:
            if not os.path.isdir(root):
                continue
            for dirpath, _dirs, files in os.walk(root):
                for fname in files:
                    if fname.lower().endswith(".lnk"):
                        out.append(
                            AppEntry(
                                os.path.splitext(fname)[0],
                                os.path.join(dirpath, fname),
                            )
                        )
        return out

    @staticmethod
    def _app_paths_registry() -> list[AppEntry]:
        import winreg

        out: list[AppEntry] = []
        key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    i = 0
                    while True:
                        try:
                            sub = winreg.EnumKey(key, i)
                        except OSError:
                            break
                        i += 1
                        try:
                            with winreg.OpenKey(key, sub) as subkey:
                                path, _ = winreg.QueryValueEx(subkey, "")
                                if path:
                                    out.append(
                                        AppEntry(os.path.splitext(sub)[0], path)
                                    )
                        except OSError:
                            continue
            except OSError:
                continue
        return out

    def launch(self, target: str) -> None:
        os.startfile(target)  # type: ignore[attr-defined]

    def is_process_running(self, target: str) -> bool:
        exe = os.path.basename(target).lower()
        if not exe.endswith(".exe"):
            return False
        try:
            r = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {exe}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return exe in r.stdout.lower()
        except Exception:
            return False

    # ---- 視窗 ----
    def find_visible_window(self, keyword: str) -> WindowRef | None:
        try:
            import pygetwindow as gw

            for w in gw.getAllWindows():
                if (
                    w.title
                    and keyword.lower() in w.title.lower()
                    and w.visible
                    and not w.isMinimized
                ):
                    return _WinWindow(w)
        except Exception:
            pass
        return None

    def list_window_titles(self) -> list[str]:
        try:
            import pygetwindow as gw

            return [w.title for w in gw.getAllWindows() if w.title and w.visible]
        except Exception:
            return []

    # ---- 系統動作 ----
    def open_url(self, url: str) -> None:
        os.startfile(url)  # type: ignore[attr-defined]

    def set_volume(self, action: str, amount: int = 10) -> str:
        import pyautogui

        if action == "mute":
            pyautogui.press("volumemute")
            return "Sir, 已切換靜音。"
        key = "volumeup" if action == "up" else "volumedown"
        pyautogui.press(key, presses=max(1, amount // 2))
        return f"Sir, 音量已調{'高' if action == 'up' else '低'}。"

    def lock_screen(self) -> str:
        ctypes.windll.user32.LockWorkStation()  # type: ignore[attr-defined]
        return "Sir, 螢幕已鎖定。"

    def set_input_method(self, mode: str) -> str:
        import pyautogui

        try:
            pyautogui.press("escape")
            pyautogui.sleep(0.1)
            if mode == "toggle_lang":
                pyautogui.hotkey("win", "space")
                return "Sir, 已切換系統輸入語言。"

            hwnd = ctypes.windll.user32.GetForegroundWindow()  # type: ignore[attr-defined]
            himc = ctypes.windll.imm32.ImmGetContext(hwnd)  # type: ignore[attr-defined]
            if himc:
                ctypes.windll.imm32.ImmSetConversionStatus(  # type: ignore[attr-defined]
                    himc, 1 if mode == "chinese" else 0, 0
                )
                ctypes.windll.imm32.ImmReleaseContext(hwnd, himc)  # type: ignore[attr-defined]
                return f"Sir, 輸入法已切換為 {mode}。"
            pyautogui.press("shift")
            return f"Sir, 已切換輸入法為 {mode}。"
        except Exception as e:
            return f"輸入法切換失敗：{e}"
