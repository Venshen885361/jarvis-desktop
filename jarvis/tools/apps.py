"""已安裝應用程式索引 + 開啟程式。

沿用原版的核心想法：不靠寫死的中文對照表，而是實際掃描系統上的捷徑／.desktop，
用「完全相同 → 子字串 → 模糊比對」三段式找出使用者口語講的那個程式。
平台差異全部下放到 platform_ 層。
"""

from __future__ import annotations

import difflib
import threading
import time

from ..platform_ import AppEntry, get_platform

_INDEX: list[AppEntry] | None = None
_LOCK = threading.Lock()

# 瀏覽器會保留背景行程，不能用「行程存在」判斷開沒開，要看有沒有可見視窗。
_BROWSER_KEYWORDS = {
    "chrome": "Chrome",
    "chromium": "Chromium",
    "edge": "Edge",
    "firefox": "Firefox",
    "zen": "Zen",
    "brave": "Brave",
    "vivaldi": "Vivaldi",
}


def get_index(force: bool = False) -> list[AppEntry]:
    global _INDEX
    with _LOCK:
        if _INDEX is None or force:
            _INDEX = get_platform().list_apps()
            print(f"[app index] 共 {len(_INDEX)} 個項目。")
        return _INDEX


def find_installed_app(query: str) -> AppEntry | None:
    q = query.strip().lower()
    if not q:
        return None
    index = get_index()

    for e in index:
        if e.display.strip().lower() == q:
            return e

    hits = [
        e for e in index
        if q in e.display.lower() or e.display.lower() in q
    ]
    if hits:
        hits.sort(key=lambda e: abs(len(e.display) - len(query)))
        return hits[0]

    names = [e.display for e in index]
    close = difflib.get_close_matches(query, names, n=1, cutoff=0.6)
    if close:
        for e in index:
            if e.display == close[0]:
                return e
    return None


def _browser_keyword(entry: AppEntry) -> str | None:
    haystack = f"{entry.display} {entry.target}".lower()
    for key, title in _BROWSER_KEYWORDS.items():
        if key in haystack:
            return title
    return None


def _wait_for_window(keyword: str, timeout: float = 6.0):
    plat = get_platform()
    deadline = time.time() + timeout
    while time.time() < deadline:
        w = plat.find_visible_window(keyword)
        if w:
            return w
        time.sleep(0.3)
    return None


def open_application(app_name: str) -> str:
    """開啟這台電腦上已安裝的應用程式（不限於預先列出的名字）。

    若該程式已經有看得到的視窗，會切換過去而不是再開一個，方便後續直接對現有視窗操作。

    Args:
        app_name: 使用者說的程式名稱，例如「記事本」「小算盤」「LINE」「Spotify」「Firefox」。
    """
    entry = find_installed_app(app_name)
    if not entry:
        return (
            f"Sir, 已安裝的程式裡找不到「{app_name}」，"
            "請確認名稱，或這個程式是否真的裝在這台電腦上。"
        )

    plat = get_platform()
    try:
        keyword = _browser_keyword(entry)
        if keyword:
            existing = plat.find_visible_window(keyword)
            if existing:
                existing.activate()
                return f"Sir, {entry.display} 已經開著，已為您切換過去。"
            plat.launch(entry.target)
            win = _wait_for_window(keyword, timeout=8)
            if not win:
                return (
                    f"Sir, 已嘗試開啟 {entry.display}，但 8 秒內偵測不到視窗，"
                    "請確認畫面狀態。"
                )
            win.activate()
            return f"Sir, {entry.display} 已啟動。"

        if plat.is_process_running(entry.target):
            return f"Sir, {entry.display} 已經在執行中，沿用現有視窗即可。"

        plat.launch(entry.target)
        time.sleep(1.2)
        return f"Sir, {entry.display} 已啟動。"
    except Exception as e:
        return f"開啟 {entry.display} 失敗：{e}"


def focus_window(keyword: str) -> str:
    """把符合關鍵字的視窗切到最前面。

    Args:
        keyword: 視窗標題或程式名稱的一部分，例如「Firefox」「記事本」。
    """
    w = get_platform().find_visible_window(keyword)
    if not w:
        return f"Sir, 找不到標題包含「{keyword}」的視窗。"
    w.activate()
    return f"Sir, 已切換到「{w.title}」。"


def list_windows() -> str:
    """列出目前開著的視窗標題，用來確認畫面上有什麼。"""
    titles = [t for t in get_platform().list_window_titles() if t]
    if not titles:
        return "Sir, 目前沒有偵測到任何視窗。"
    return "目前開著的視窗：" + "、".join(titles[:20])


def open_url(url: str) -> str:
    """用系統預設瀏覽器開啟網址。

    Args:
        url: 完整網址，例如 https://github.com
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        get_platform().open_url(url)
        return f"Sir, 已開啟 {url}。"
    except Exception as e:
        return f"開啟網址失敗：{e}"


def refresh_app_index() -> str:
    """重新掃描已安裝程式清單（剛裝完新軟體時用）。"""
    n = len(get_index(force=True))
    return f"Sir, 應用程式索引已重建，共 {n} 個項目。"


__all__ = [
    "find_installed_app",
    "focus_window",
    "get_index",
    "list_windows",
    "open_application",
    "open_url",
    "refresh_app_index",
]
