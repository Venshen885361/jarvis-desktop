"""使用者檔案：稱呼、回覆風格、常用指令、使用習慣。

存在 ~/.jarvis/profile.json（不在 repo 裡、不在 .env 裡 —— 這不是設定，是「關於使用者」的資料）。
兩個用途：
1. 拼進 system prompt（稱呼 / 風格 / 備註），讓模型照使用者的偏好回話
2. 記錄使用者實際下過的指令，算出最常用的幾個，手機介面拿來當快速鍵 ——
   「讓系統自己調整」的最小版本：不用使用者設定，用久了自然變成他的樣子
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

_DIR = Path.home() / ".jarvis"
_PATH = _DIR / "profile.json"
_lock = threading.Lock()

DEFAULT = {
    "name": "Sir",            # 怎麼稱呼使用者
    "style": "concise",       # concise（兩句內）/ normal / detailed
    "lang": "zh-TW",
    "notes": "",              # 使用者自己寫的備註：「我用 Firefox 不用 Chrome」「冷氣叫做房間冷氣」
    "quick": [],              # 使用者釘選的快速指令
    "history": {},            # 指令 → 次數（自動）
    "onboarded": False,
}

_STYLE_TEXT = {
    "concise": "回答非常簡明扼要，控制在 2 句話內。",
    "normal": "回答簡潔，通常 2–4 句。",
    "detailed": "可以多解釋一點，但仍然不要長篇大論。",
}


def load() -> dict:
    with _lock:
        try:
            data = json.loads(_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        return {**DEFAULT, **data}


def save(data: dict) -> dict:
    merged = {**load(), **data}
    with _lock:
        _DIR.mkdir(exist_ok=True)
        _PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def public(p: dict | None = None) -> dict:
    """給前端的版本：不含 history 原始資料，改給 top_commands。"""
    p = p or load()
    return {k: v for k, v in p.items() if k != "history"} | {"top": top_commands(p)}


# ---------------------------------------------------------------------------
def style_text(p: dict | None = None) -> str:
    p = p or load()
    return _STYLE_TEXT.get(p.get("style", "concise"), _STYLE_TEXT["concise"])


def prompt_block(p: dict | None = None, include_style: bool = True) -> str:
    """接在 system prompt 後面的使用者段落。內容穩定（不放時間、不放歷史）才不會打壞 prompt cache。"""
    p = p or load()
    lines = [f"使用者偏好：稱呼使用者為「{p['name']}」。" + (style_text(p) if include_style else "")]
    if p.get("lang") and p["lang"] != "zh-TW":
        lines.append(f"回覆語言：{p['lang']}。")
    if p.get("notes"):
        lines.append("使用者備註：" + p["notes"].strip()[:600])
    return "\n".join(lines)


def personalize(text: str, p: dict | None = None) -> str:
    """本機路由的回覆寫死 'Sir,'；稱呼改了就替換掉。"""
    name = (p or load()).get("name", "Sir")
    if name == "Sir" or not text:
        return text
    return re.sub(r"\bSir\b", name, text)


# ---------------------------------------------------------------------------
_SKIP = ("再見", "退出", "關機", "bye", "quit", "exit")


def record_command(text: str) -> None:
    """記一筆指令；太長的（模型任務描述）與退出詞不記。"""
    t = " ".join(text.split())
    if not t or len(t) > 30 or any(w in t.lower() for w in _SKIP):
        return
    p = load()
    hist = dict(p.get("history", {}))
    hist[t] = int(hist.get(t, 0)) + 1
    if len(hist) > 200:  # 只留最常用的
        hist = dict(sorted(hist.items(), key=lambda kv: -kv[1])[:150])
    save({"history": hist})


def top_commands(p: dict | None = None, n: int = 6) -> list[str]:
    p = p or load()
    pinned = [q for q in p.get("quick", []) if q]
    auto = [k for k, _ in sorted(p.get("history", {}).items(), key=lambda kv: -kv[1]) if k not in pinned]
    return (pinned + auto)[:n]
