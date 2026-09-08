"""媒體：在 YouTube 搜尋並直接播放。

「播晴天」「用 YouTube 放周杰倫的歌」→ 找到第一個影片 → 在目前控制的裝置開 watch 網址。
只開搜尋結果頁的話使用者還要自己點，這裡多做一步找出 videoId。

找 videoId 的順序（都不需要金鑰）：
1. yt-dlp（有裝就用，最穩）：`ytsearch1:<query>`
2. 直接抓搜尋結果頁，從頁面裡的 ytInitialData 撈第一個 "videoId"
   ⚠️ 非官方做法，YouTube 改版可能失效；失效時退回開搜尋頁，不會假裝成功。

播放端：
- 電腦：預設瀏覽器開 https://www.youtube.com/watch?v=<id>
  ⚠️ 瀏覽器自動播放政策可能讓影片停在第一格（尤其沒互動過的瀏覽器），點一下就會播。
- Android（App / ADB）：同一個網址，系統會交給 YouTube App 開。
"""

from __future__ import annotations

import re
import urllib.parse

import requests

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
       "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"}


def _search_ytdlp(query: str) -> tuple[str, str] | None:
    """yt-dlp 的 Python API：ytsearch1 只抓 metadata（extract_flat），約 1 秒。"""
    try:
        import yt_dlp
    except ImportError:
        return None
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True,
            "default_search": "ytsearch1", "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
    except Exception:
        return None
    entries = (info or {}).get("entries") or []
    if not entries:
        return None
    e = entries[0]
    vid = e.get("id") or ""
    return (vid, e.get("title") or "") if len(vid) == 11 else None


def _search_scrape(query: str) -> tuple[str, str] | None:
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    try:
        html = requests.get(url, headers=_UA, timeout=10).text
    except requests.RequestException:
        return None
    # 第一個 videoRenderer 就是第一個搜尋結果（廣告與頻道不是 videoRenderer）
    m = re.search(r'"videoRenderer":\{"videoId":"([\w-]{11})".{0,600}?"title":\{"runs":\[\{"text":"(.*?)"', html, re.S)
    if m:
        return m.group(1), m.group(2).encode("utf-8").decode("unicode_escape", "ignore")
    m = re.search(r'"videoId":"([\w-]{11})"', html)
    return (m.group(1), "") if m else None


def youtube_play(query: str, music: bool = False) -> str:
    """在 YouTube 搜尋並播放第一個結果（在目前控制的裝置上開啟）。

    Args:
        query: 歌名 / 影片關鍵字，例如「周杰倫 晴天」「lofi hip hop」「PJSK 新曲」。
        music: True 時用 YouTube Music 網站播（純聽歌）。
    """
    from ..devices import get_devices

    q = query.strip()
    if not q:
        return "Sir, 要播什麼？"
    hit = _search_ytdlp(q) or _search_scrape(q)
    if hit:
        vid, title = hit
        url = f"https://music.youtube.com/watch?v={vid}" if music else f"https://www.youtube.com/watch?v={vid}"
        get_devices().run_tool("open_url", {"url": url})
        return f"Sir, 正在播放{('「' + title + '」') if title else ''}。"
    base = "https://music.youtube.com/search?q=" if music else "https://www.youtube.com/results?search_query="
    get_devices().run_tool("open_url", {"url": base + urllib.parse.quote(q)})
    return f"Sir, 找不到「{q}」的影片 ID，已開啟搜尋結果，請點第一個。"
