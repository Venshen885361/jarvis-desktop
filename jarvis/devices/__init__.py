"""裝置註冊表：哪些裝置可以被操作、現在對哪一台說話。

設定格式（.env）：
  JARVIS_DEVICES=pc=ws://100.101.102.103:8770?token=abc,phone=hub://phone
  JARVIS_DEFAULT_DEVICE=pc

  ws://   大腦去連跑著 jarvis.agent 的電腦
  hub://  裝了 JARVIS Android App 的手機主動連進大腦（名稱要跟 App 內填的一樣）
  adb://  ADB 無線偵錯（auto = 自動找），不裝 App 的備案
  ios://  iPhone：寄信觸發捷徑自動化（ios://you@icloud.com），只能跑預先定義的動作

沒設 JARVIS_DEVICES 就只有一台 "local"（現在的單機模式），行為跟以前完全一樣。
"""

from __future__ import annotations

import os
import threading
from urllib.parse import parse_qs, urlparse

from ..config import settings
from .base import Device, ImageResult, ToolOutput

# 這幾個名稱不是「某台裝置上的工具」，而是大腦自己的：切換目標、列出裝置。
CORE_TOOLS = ("switch_device", "list_devices")

# 大腦本機（Pi 或桌機）才有鏡頭 / 才連得到 Home Assistant，這些不轉發到目標裝置
LOCAL_ONLY_TOOLS = (
    "analyze_camera_view", "camera_search", "lens_search", "open_gesture_selector",
    "home_control", "home_status", "home_list",
)

_ALIASES = {
    "電腦": "pc", "桌機": "pc", "筆電": "pc", "computer": "pc", "desktop": "pc", "laptop": "pc",
    "手機": "phone", "android": "phone", "mobile": "phone", "iphone": "phone", "蘋果": "phone",
    "本機": "local", "這台": "local", "自己": "local",
}


def _is_pi() -> bool:
    """Raspberry Pi 當大腦時，「電腦」不該指 Pi 自己。"""
    try:
        with open("/proc/device-tree/model", "rb") as f:
            return b"Raspberry Pi" in f.read()
    except OSError:
        return False


class DeviceRegistry:
    def __init__(self) -> None:
        self._devices: dict[str, Device] = {}
        self._specs: dict[str, str] = {}
        self._lock = threading.Lock()
        self.current_name = "local"
        self._parse(os.environ.get("JARVIS_DEVICES", ""))
        default = os.environ.get("JARVIS_DEFAULT_DEVICE", "").strip()
        if default and default in self._specs:
            self.current_name = default

    def _parse(self, raw: str) -> None:
        for item in raw.split(","):
            item = item.strip()
            if not item or "=" not in item:
                continue
            name, _, spec = item.partition("=")
            self._specs[name.strip()] = spec.strip()

    # ------------------------------------------------------------------
    def names(self) -> list[str]:
        return ["local", *self._specs.keys()]

    def resolve_name(self, text: str) -> str | None:
        t = text.strip().lower()
        if t in self.names():
            return t
        alias = _ALIASES.get(t)
        if alias and alias in self.names():
            return alias
        # 「手機」但註冊名叫 "pixel"：找 kind 是 android 的
        if alias == "phone":
            for n, spec in self._specs.items():
                if spec.startswith(("adb://", "hub://", "ios://")):
                    return n
        if alias == "pc":
            for n, spec in self._specs.items():
                if spec.startswith(("ws://", "wss://")):
                    return n
            # 沒有註冊遠端電腦、而大腦本身就是一台電腦（Windows / Linux 桌機）：「電腦」= 本機。
            # 手機遙控時常見：大腦跑在電腦上，使用者說「切換到電腦」指的就是它。
            import sys

            if sys.platform in ("win32", "linux", "darwin") and not _is_pi():
                return "local"
        return None

    def get(self, name: str) -> Device:
        with self._lock:
            if name in self._devices:
                return self._devices[name]
            dev = self._build(name)
            self._devices[name] = dev
            return dev

    def _build(self, name: str) -> Device:
        if name == "local":
            from .local import LocalDevice

            return LocalDevice("local")
        spec = self._specs.get(name)
        if spec is None:
            raise KeyError(f"沒有叫「{name}」的裝置。可用：{'、'.join(self.names())}")
        u = urlparse(spec)
        if u.scheme in ("ws", "wss"):
            from .remote import RemoteDevice

            token = parse_qs(u.query).get("token", [""])[0] or settings.agent_token
            url = f"{u.scheme}://{u.netloc}{u.path or '/'}"
            return RemoteDevice(name, url, token)
        if u.scheme == "adb":
            from .adb import AdbDevice

            return AdbDevice(name, u.netloc)
        if u.scheme == "hub":
            from .hub import HubDevice

            return HubDevice(name, u.netloc or name)
        if u.scheme == "ios":
            from .ios import IosDevice

            return IosDevice(name, spec[len("ios://"):])
        raise ValueError(f"不認得的裝置設定：{spec}（支援 ws:// wss:// hub:// adb:// ios://）")

    @property
    def current(self) -> Device:
        return self.get(self.current_name)

    def switch(self, name_or_alias: str) -> str:
        name = self.resolve_name(name_or_alias)
        if name is None:
            return f"Sir, 找不到裝置「{name_or_alias}」。可用：{'、'.join(self.names())}。"
        try:
            dev = self.get(name)
            if not dev.ping():
                return f"Sir, 連不上 {name}，請確認 agent 有在跑、或 ADB 有連上。"
        except Exception as e:
            return f"Sir, 切換到 {name} 失敗：{e}"
        self.current_name = name
        from ..hud import ws_emit

        ws_emit({"type": "device", "name": name, "platform": dev.platform})
        return f"Sir, 已切換控制目標到 {name}（{dev.platform}）。"

    def describe_all(self) -> str:
        lines = []
        for n in self.names():
            mark = "◉" if n == self.current_name else "○"
            spec = self._specs.get(n, "本機")
            status = ""
            dev = self._devices.get(n)  # 只看已建立的，不為了列清單去連線
            if dev is None and n != "local":
                status = "（尚未使用）"
            elif dev is not None and (st := dev.status()):
                status = f"（{st}）"
            lines.append(f"{mark} {n}：{spec.split('?')[0]}{status}")
        return "可控制的裝置（◉ = 目前）：\n" + "\n".join(lines)

    # ------------------------------------------------------------------
    def run_tool(self, tool: str, args: dict) -> ToolOutput:
        """所有工具呼叫的單一入口：大腦工具在本機跑，其他送目前目標裝置。"""
        if tool == "switch_device":
            return self.switch(args.get("name", ""))
        if tool == "list_devices":
            return self.describe_all()
        if tool in LOCAL_ONLY_TOOLS:
            return self.get("local").call(tool, args)
        return self.current.call(tool, args)


_registry: DeviceRegistry | None = None


def get_devices() -> DeviceRegistry:
    global _registry
    if _registry is None:
        _registry = DeviceRegistry()
    return _registry


__all__ = ["CORE_TOOLS", "Device", "DeviceRegistry", "ImageResult", "ToolOutput", "get_devices"]
