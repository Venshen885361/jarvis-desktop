"""下載與安裝：程式（winget）、Steam 遊戲、任意網址的檔案。

這些工具在「目前控制的裝置」上執行（不是大腦）：手機遙控 Pi、Pi 控制電腦時，
「幫我下載 Discord」要裝在電腦上，所以走 dispatch 而不是 LOCAL_ONLY。

- install_app：Windows 用 winget（微軟官方套件管理器，Win10 1709+ / Win11 內建）。
  搜尋 → 取最像的 → 安裝。找不到就開官方下載頁的搜尋，不亂裝。
  Linux：flatpak 有的話用 flatpak，否則回報要手動。
- install_steam_game：Steam 商店搜尋 API 找 appid → 開 steam://install/<appid>，Steam 會跳出安裝視窗。
  ⚠️ storesearch 是 Steam 網頁用的非公開端點，沒有官方文件；失效時退回開商店搜尋頁。
- download_file：直接下載網址到 ~/Downloads（串流寫入，回報大小與路徑）。

安全：winget 只裝它索引裡的套件（微軟審過）；不會執行下載回來的檔案。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

import requests

from ..hud import emit_log

_UA = {"User-Agent": "Mozilla/5.0 JARVIS"}


def _downloads_dir() -> Path:
    d = Path.home() / "Downloads"
    if not d.is_dir():
        d = Path.home() / "下載"
    d.mkdir(exist_ok=True)
    return d


# ---------------------------------------------------------------- winget
def _run(cmd: list[str], timeout: int) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _winget_search(query: str) -> list[tuple[str, str]]:
    """回傳 [(name, id)]，依 winget 的排序（它把最符合的放前面）。"""
    code, out = _run(["winget", "search", query, "--accept-source-agreements", "--disable-interactivity"], 40)
    rows = []
    for line in out.splitlines():
        # 表格：Name  Id  Version  Source（欄寬對齊，用 2+ 空白切）
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) >= 3 and re.match(r"^[\w.+-]+\.[\w.+-]+$", parts[1]):
            rows.append((parts[0], parts[1]))
    return rows


def install_app(name: str) -> str:
    """在這台電腦安裝程式（Windows 用 winget）。例：「Discord」「VLC」「Steam」「OBS」「Firefox」。"""
    q = name.strip()
    if not q:
        return "Sir, 要安裝什麼？"
    if sys.platform == "win32":
        if not shutil.which("winget"):
            return "Sir, 這台電腦沒有 winget（Windows 套件管理器）。請先從 Microsoft Store 安裝「應用程式安裝程式」。"
        try:
            rows = _winget_search(q)
        except Exception as e:
            return f"Sir, winget 搜尋失敗：{e}"
        if not rows:
            return _open_download_page(q)
        # 名稱完全相符優先，其次第一筆
        pick = next((r for r in rows if r[0].lower() == q.lower()), rows[0])
        emit_log("SYS", f"winget install {pick[1]}")
        try:
            code, out = _run(["winget", "install", "--id", pick[1], "-e", "-h",
                              "--accept-package-agreements", "--accept-source-agreements",
                              "--disable-interactivity"], 900)
        except subprocess.TimeoutExpired:
            return f"Sir, {pick[0]} 安裝超過 15 分鐘還沒完成，請到電腦上看一下。"
        if code == 0 or "已成功安裝" in out or "Successfully installed" in out:
            return f"Sir, {pick[0]} 已安裝完成。"
        if "already installed" in out or "已安裝" in out:
            return f"Sir, {pick[0]} 本來就裝好了。"
        tail = out.strip().splitlines()[-1] if out.strip() else f"exit {code}"
        return f"Sir, {pick[0]} 安裝沒有成功：{tail}（有些程式需要在電腦上按一下 UAC 同意）。"
    if sys.platform.startswith("linux") and shutil.which("flatpak"):
        code, out = _run(["flatpak", "search", "--columns=application,name", q], 40)
        line = next((ln for ln in out.splitlines() if "\t" in ln), "")
        if not line:
            return _open_download_page(q)
        app_id, app_name = line.split("\t", 1)
        code, out = _run(["flatpak", "install", "-y", "--noninteractive", "flathub", app_id.strip()], 900)
        return f"Sir, {app_name.strip()} 已安裝。" if code == 0 else f"Sir, 安裝失敗：{out.strip().splitlines()[-1] if out.strip() else code}"
    return _open_download_page(q)


def _open_download_page(q: str) -> str:
    from ..devices import get_devices

    url = "https://www.google.com/search?q=" + urllib.parse.quote(f"{q} 官方下載")
    get_devices().run_tool("open_url", {"url": url})
    return f"Sir, 套件庫裡找不到「{q}」，已開啟官方下載頁的搜尋，請您確認來源。"


# ---------------------------------------------------------------- Steam
def _steam_search(query: str) -> tuple[int, str] | None:
    r = requests.get("https://store.steampowered.com/api/storesearch/",
                     params={"term": query, "l": "tchinese", "cc": "TW"}, headers=_UA, timeout=10)
    r.raise_for_status()
    items = r.json().get("items") or []
    if not items:
        return None
    q = query.lower().replace(" ", "")
    exact = next((i for i in items if str(i.get("name", "")).lower().replace(" ", "") == q), None)
    it = exact or items[0]
    return int(it["id"]), str(it.get("name", ""))


def install_steam_game(name: str, run: bool = False) -> str:
    """用 Steam 安裝（或啟動）遊戲。run=True 表示直接開始遊戲而不是安裝。例：「Terraria」「Stardew Valley」。"""
    from ..devices import get_devices

    q = name.strip()
    if not q:
        return "Sir, 哪一款遊戲？"
    try:
        hit = _steam_search(q)
    except Exception as e:
        hit = None
        emit_log("SYS", f"steam search failed: {e}")
    if not hit:
        get_devices().run_tool("open_url", {"url": "https://store.steampowered.com/search/?term=" + urllib.parse.quote(q)})
        return f"Sir, Steam 商店找不到「{q}」，已開啟搜尋頁。"
    appid, title = hit
    action = "rungameid" if run else "install"
    get_devices().run_tool("open_url", {"url": f"steam://{action}/{appid}"})
    return f"Sir, 已請 Steam {'啟動' if run else '安裝'}「{title}」（需要 Steam 已登入；未購買的遊戲會開商店頁）。"


# ---------------------------------------------------------------- 任意檔案
def download_file(url: str, filename: str = "") -> str:
    """把網址的檔案下載到這台裝置的「下載」資料夾。filename 留空用網址的檔名。"""
    u = url.strip()
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    name = filename.strip() or os.path.basename(urllib.parse.urlparse(u).path) or "download.bin"
    name = re.sub(r"[\\/:*?\"<>|]", "_", name)
    dest = _downloads_dir() / name
    try:
        with requests.get(u, headers=_UA, stream=True, timeout=30, allow_redirects=True) as r:
            r.raise_for_status()
            cd = r.headers.get("Content-Disposition", "")
            if not filename and (m := re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', cd)):
                dest = _downloads_dir() / re.sub(r"[\\/:*?\"<>|]", "_", urllib.parse.unquote(m.group(1)))
            size = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
                    size += len(chunk)
    except Exception as e:
        return f"Sir, 下載失敗：{e}"
    mb = size / 1e6
    return f"Sir, 已下載 {dest.name}（{mb:.1f} MB）到 {dest.parent}。"
