"""把 jarvis.router 變成「純函式」：輸入一句話，輸出它會被路由到哪裡，不真的開程式、不打 API。

研究用。router._route() 本身有副作用（開程式、播 YouTube、呼叫 Home Assistant…），
這裡把所有出口都換成「記錄下來」的假物件，所以可以一秒跑一萬句。

    >>> from research.mt.harness import route_label
    >>> route_label("幫我開一下記事本")
    Label(kind='open_application', target='記事本')
    >>> route_label("今天很開心")
    Label(kind='model', target='')

Label.kind 的取值（就是路由的「目的地」）：
  本機工具：open_application / open_folder / open_url / set_volume / focus_window / lock_screen /
           computer:key / switch_input_method / read_clipboard / write_clipboard / lens_search / camera_search
  本機函式：youtube_play / install_app / install_steam_game / download_file / home_control /
           math / time / date / weather / greeting / hide / show / device_switch / device_list / list_windows
  非本機：  info（純問答，交給模型回答）/ model（交給模型操作）
"""

from __future__ import annotations

import contextlib
import os
import re
import urllib.parse
from dataclasses import dataclass
from unittest import mock


@dataclass(frozen=True)
class Label:
    kind: str
    target: str = ""

    def __str__(self) -> str:
        return f"{self.kind}:{self.target}" if self.target else self.kind


# ---------------------------------------------------------------------------
class _Recorder:
    """收集這一句路由過程中呼叫了哪個出口。第一個被呼叫的就是答案。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def dev(self, tool: str, **args) -> str:
        self.calls.append((tool, args))
        # 回傳值會被 router 拿去判斷「找不到」→ 改開網頁；給一個中性字串
        return f"[fake {tool}]"

    def fn(self, name: str):
        def _f(*a, **kw):
            self.calls.append((name, {"args": a, "kwargs": kw}))
            return f"[fake {name}]"
        return _f


class _FakeDevices:
    """router 會問裝置註冊表三件事：這名字是不是裝置、切換、目前是誰。"""

    names = {"手機": "phone", "電腦": "local", "桌機": "local", "筆電": "local", "本機": "local", "phone": "phone", "pc": "pc"}

    def __init__(self, rec: _Recorder) -> None:
        self.rec = rec
        self.current_name = "local"

    def resolve_name(self, name: str):
        return self.names.get(name.strip().lower())

    def switch(self, name: str) -> str:
        self.rec.calls.append(("device_switch", {"name": name}))
        return f"Sir, 已切換到 {name}。"

    def describe_all(self) -> str:
        self.rec.calls.append(("device_list", {}))
        return "[fake devices]"

    def run_tool(self, tool, args):
        return self.rec.dev(tool, **(args or {}))


_TARGET_KEYS = ("app_name", "name", "url", "keyword", "action", "mode", "text", "hint", "device")


def _target_of(tool: str, args: dict) -> str:
    if "args" in args:  # 本機函式：第一個位置參數就是目標（歌名 / 程式名 / 裝置名）
        a = args["args"]
        if tool == "home_control" and len(a) >= 2:
            return f"{a[0]}={a[1]}" + (f"={a[2]}" if len(a) > 2 else "")
        return str(a[0]) if a else ""
    for k in _TARGET_KEYS:
        if k in args and args[k] not in (None, ""):
            v = str(args[k])
            # 網頁搜尋是「組 Google 網址再開」：把查詢字串還原成人看得懂的目標
            if k == "url" and v.startswith("https://www.google.com/search?q="):
                return "google:" + urllib.parse.unquote(v.split("q=", 1)[1])
            return v
    return ""


def _classify_text_result(text: str, result: str) -> Label:
    """沒有呼叫任何出口、但 router 回了字串：算術 / 時間 / 招呼 之類。"""
    if "計算結果" in result:
        return Label("math")
    if result.startswith("Sir, 現在是"):
        return Label("time")
    if result.startswith("Sir, 今天是"):
        return Label("date")
    if result == "Sir, 要設定成多少？":
        return Label("home_control", "?")
    import sys

    router = sys.modules["jarvis.router"]
    if result in router._GREETINGS.values():
        return Label("greeting")
    if result.startswith("Sir, 已為您搜尋"):
        return Label("open_url", "google:" + re.sub(r"^Sir, 已為您搜尋「|」。$", "", result))
    return Label("local_other", result[:30])


@contextlib.contextmanager
def _patched(rec: _Recorder):
    import sys

    import jarvis.tools.downloads as dl
    router = sys.modules["jarvis.router"] if "jarvis.router" in sys.modules else __import__("jarvis.router", fromlist=["_"])
    import jarvis.tools.home as home
    import jarvis.tools.media as media

    fake_devs = _FakeDevices(rec)
    patches = [
        mock.patch.object(router, "_dev", rec.dev),
        mock.patch.object(router, "get_devices", lambda: fake_devs),
        mock.patch.object(router, "fetch_weather", rec.fn("weather")),
        mock.patch.object(media, "youtube_play", rec.fn("youtube_play")),
        mock.patch.object(dl, "install_app", rec.fn("install_app")),
        mock.patch.object(dl, "install_steam_game", rec.fn("install_steam_game")),
        mock.patch.object(dl, "download_file", rec.fn("download_file")),
        mock.patch.object(home, "home_control", rec.fn("home_control")),
        mock.patch.dict(os.environ, {"HA_URL": os.environ.get("HA_URL", "http://fake-ha:8123")}),
    ]
    # 桌寵顯示 / 隱藏走 hud.ws_emit
    import jarvis.hud as hud
    patches.append(mock.patch.object(hud, "ws_emit", lambda payload: rec.calls.append((payload.get("type", "ws"), {}))))
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in reversed(patches):
            p.stop()


def _label_one(router, rec: _Recorder, text: str) -> Label:
    rec.calls.clear()
    try:
        result = router._route(text.strip())
    except Exception as e:  # 路由自己炸掉也是一種結果，研究上要記
        return Label("error", type(e).__name__)
    if rec.calls:
        tool, args = rec.calls[0]
        return Label(tool, _target_of(tool, args))
    if result is not None:
        return _classify_text_result(text, result)
    try:
        if router.is_info_query(text):
            return Label("info")
    except Exception as e:
        return Label("error", type(e).__name__)
    return Label("model")


def route_label(text: str) -> Label:
    """一句話 → Label。順序跟 __main__._handle 一樣：本機路由 → 純問答 → 模型。"""
    import jarvis.router as router

    rec = _Recorder()
    with _patched(rec):
        return _label_one(router, rec, text)


def batch_labels(texts: list[str]) -> list[Label]:
    """一次貼補、跑很多句（突變測試用：幾十萬次呼叫時 patch 的開銷才是瓶頸）。
    透過 sys.modules 取 jarvis.router，所以換成突變體模組也吃得到。"""
    import sys

    import jarvis.router  # noqa: F401  確保原版已載入（之後可能被突變體替換）
    router = sys.modules["jarvis.router"]
    rec = _Recorder()
    with _patched(rec):
        return [_label_one(router, rec, t) for t in texts]


def same_route(a: Label, b: Label) -> bool:
    """蛻變關係用的等價判斷：目的地一樣、目標（程式名 / 歌名）一樣就算同路。
    目標比對忽略大小寫與前後空白；時間 / 日期 / 招呼這類沒有目標的只比 kind。"""
    # 用字串形式比：seeds.json 的 "computer:key:nexttrack" 解析成 (computer, key:nexttrack)，
    # 而 route_label 給的是 (computer:key, nexttrack)，結構不同但意義相同
    norm = lambda x: f"{x.kind}:{x.target.strip()}".rstrip(":").lower()  # noqa: E731
    return norm(a) == norm(b)


if __name__ == "__main__":
    import sys

    for s in (sys.argv[1:] or ["幫我開一下記事本", "今天很開心", "播晴天", "附近有什麼好吃的", "現在幾點", "把客廳燈關掉", "裝潢要多少錢", "下載 Discord"]):
        print(f"{s!r:24} → {route_label(s)}")
