"""Linux 實作。

對照 Windows 版的四個來源：
- 已安裝程式：freedesktop .desktop 檔（等同開始功能表捷徑），讀 Name / Name[zh_TW] / Exec
- 啟動：gio launch <desktop file>，退回 xdg-open / 直接跑 Exec
- 視窗：Hyprland 走 hyprctl -j，其餘 X11/wlroots 走 wmctrl
- 輸入法：fcitx5-remote，退回 ibus

刻意不硬綁任何一種 WM：偵測得到什麼就用什麼，偵測不到就誠實回報做不到，
而不是假裝成功（原版最容易騙人的地方就是工具「有回應」就當成任務完成）。
"""

from __future__ import annotations

import configparser
import json
import os
import shutil
import subprocess

from .base import AppEntry, Platform, WindowRef

_DESKTOP_DIRS = [
    "/usr/share/applications",
    "/usr/local/share/applications",
    "/var/lib/flatpak/exports/share/applications",
    os.path.expanduser("~/.local/share/applications"),
    os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
]


def _run(cmd: list[str], timeout: float = 5.0) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or r.stderr or "").strip()
    except Exception as e:
        return 1, str(e)


def _has(binary: str) -> bool:
    return shutil.which(binary) is not None


def _is_hyprland() -> bool:
    return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) and _has("hyprctl")


class _HyprWindow(WindowRef):
    def __init__(self, address: str, title: str):
        self.address = address
        self.title = title

    def activate(self) -> None:
        _run(["hyprctl", "dispatch", "focuswindow", f"address:{self.address}"])

    def close(self) -> None:
        _run(["hyprctl", "dispatch", "closewindow", f"address:{self.address}"])


class _WmctrlWindow(WindowRef):
    def __init__(self, wid: str, title: str):
        self.wid = wid
        self.title = title

    def activate(self) -> None:
        _run(["wmctrl", "-i", "-a", self.wid])

    def close(self) -> None:
        _run(["wmctrl", "-i", "-c", self.wid])


class LinuxPlatform(Platform):
    name = "linux"

    # ---- 應用程式 ----
    def list_apps(self) -> list[AppEntry]:
        out: list[AppEntry] = []
        seen: set[str] = set()
        for d in _DESKTOP_DIRS:
            if not os.path.isdir(d):
                continue
            for fname in os.listdir(d):
                if not fname.endswith(".desktop"):
                    continue
                path = os.path.join(d, fname)
                if fname in seen:
                    continue
                seen.add(fname)
                entry = self._parse_desktop(path)
                if entry:
                    out.extend(entry)
        return out

    @staticmethod
    def _parse_desktop(path: str) -> list[AppEntry]:
        parser = configparser.RawConfigParser(strict=False, interpolation=None)
        try:
            parser.read(path, encoding="utf-8")
        except Exception:
            return []
        if "Desktop Entry" not in parser:
            return []
        sec = parser["Desktop Entry"]
        if sec.get("NoDisplay", "false").lower() == "true":
            return []
        if sec.get("Type", "Application") != "Application":
            return []

        names = []
        for key in ("Name[zh_TW]", "Name[zh_CN]", "Name", "GenericName[zh_TW]"):
            v = sec.get(key)
            if v and v not in names:
                names.append(v)
        if not names:
            return []
        # target 統一用 .desktop 路徑，啟動時交給 gio/xdg 處理 Exec 裡的 %U %f 佔位符
        return [AppEntry(n, path) for n in names]

    def launch(self, target: str) -> None:
        if target.endswith(".desktop"):
            if _has("gio"):
                code, _ = _run(["gio", "launch", target], timeout=10)
                if code == 0:
                    return
            if _has("gtk-launch"):
                code, _ = _run(
                    ["gtk-launch", os.path.basename(target)], timeout=10
                )
                if code == 0:
                    return
            # 最後手段：自己解析 Exec，去掉 freedesktop 的 %f %u %U %i %c %k 佔位符
            parser = configparser.RawConfigParser(strict=False, interpolation=None)
            parser.read(target, encoding="utf-8")
            exec_line = parser["Desktop Entry"].get("Exec", "")
            argv = [
                a
                for a in exec_line.split()
                if not (len(a) == 2 and a.startswith("%"))
            ]
            if argv:
                subprocess.Popen(
                    argv, start_new_session=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            return
        subprocess.Popen(
            [target], start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def is_process_running(self, target: str) -> bool:
        base = os.path.basename(target).replace(".desktop", "")
        code, _ = _run(["pgrep", "-x", base])
        return code == 0

    # ---- 視窗 ----
    def _hypr_clients(self) -> list[dict]:
        code, out = _run(["hyprctl", "-j", "clients"])
        if code != 0:
            return []
        try:
            return json.loads(out)
        except Exception:
            return []

    def find_visible_window(self, keyword: str) -> WindowRef | None:
        k = keyword.lower()
        if _is_hyprland():
            for c in self._hypr_clients():
                title = c.get("title", "") or ""
                cls = c.get("class", "") or ""
                if c.get("mapped") and (k in title.lower() or k in cls.lower()):
                    return _HyprWindow(c.get("address", ""), title)
            return None
        if _has("wmctrl"):
            code, out = _run(["wmctrl", "-l"])
            if code == 0:
                for line in out.splitlines():
                    parts = line.split(None, 3)
                    if len(parts) == 4 and k in parts[3].lower():
                        return _WmctrlWindow(parts[0], parts[3])
        return None

    def list_window_titles(self) -> list[str]:
        if _is_hyprland():
            return [c.get("title", "") for c in self._hypr_clients() if c.get("mapped")]
        if _has("wmctrl"):
            code, out = _run(["wmctrl", "-l"])
            if code == 0:
                return [
                    line.split(None, 3)[3]
                    for line in out.splitlines()
                    if len(line.split(None, 3)) == 4
                ]
        return []

    # ---- 系統動作 ----
    def open_url(self, url: str) -> None:
        subprocess.Popen(
            ["xdg-open", url], start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def set_volume(self, action: str, amount: int = 10) -> str:
        if _has("wpctl"):
            sink = "@DEFAULT_AUDIO_SINK@"
            if action == "mute":
                _run(["wpctl", "set-mute", sink, "toggle"])
                return "Sir, 已切換靜音。"
            delta = f"{amount}%{'+' if action == 'up' else '-'}"
            _run(["wpctl", "set-volume", "-l", "1.5", sink, delta])
            return f"Sir, 音量已調{'高' if action == 'up' else '低'} {amount}%。"
        if _has("pactl"):
            sink = "@DEFAULT_SINK@"
            if action == "mute":
                _run(["pactl", "set-sink-mute", sink, "toggle"])
                return "Sir, 已切換靜音。"
            delta = f"{'+' if action == 'up' else '-'}{amount}%"
            _run(["pactl", "set-sink-volume", sink, delta])
            return f"Sir, 音量已調{'高' if action == 'up' else '低'} {amount}%。"
        return "Sir, 這台機器上找不到 wpctl 或 pactl，音量控制無法執行。"

    def lock_screen(self) -> str:
        for cmd in (["loginctl", "lock-session"], ["hyprlock"], ["swaylock"]):
            if _has(cmd[0]):
                subprocess.Popen(
                    cmd, start_new_session=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return "Sir, 螢幕已鎖定。"
        return "Sir, 找不到可用的鎖定指令（loginctl / hyprlock / swaylock）。"

    def set_input_method(self, mode: str) -> str:
        if _has("fcitx5-remote"):
            if mode == "english":
                _run(["fcitx5-remote", "-c"])
                return "Sir, 輸入法已切換為英文。"
            if mode == "chinese":
                _run(["fcitx5-remote", "-o"])
                return "Sir, 輸入法已切換為中文。"
            _run(["fcitx5-remote", "-t"])
            return "Sir, 已切換輸入法狀態。"
        if _has("ibus"):
            engine = "xkb:us::eng" if mode == "english" else "chewing"
            code, out = _run(["ibus", "engine", engine])
            if code == 0:
                return f"Sir, 輸入法已切換為 {mode}。"
            return f"Sir, ibus 切換失敗：{out}"
        return "Sir, 找不到 fcitx5-remote 或 ibus，無法切換輸入法。"
