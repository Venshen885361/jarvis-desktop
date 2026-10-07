""".env 的讀寫：讓設定畫面可以直接改金鑰，不用叫使用者開記事本。

只改「指定的鍵」，其他行（註解、排版、別的設定）原封不動；沒有那個鍵就補在檔尾。
沒有 .env 時從 .env.example 複製一份再改。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# 允許從設定畫面改的鍵。JARVIS_AGENT_TOKEN 故意不在裡面：那是門鎖，拿到鑰匙的人不該能換鎖。
EDITABLE = {
    "JARVIS_PROVIDER", "ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID", "GEMINI_API_KEY",
    "JARVIS_CLAUDE_MODEL", "JARVIS_GEMINI_MODELS",
    "HA_URL", "HA_TOKEN", "JARVIS_DEVICES", "JARVIS_DEFAULT_DEVICE",
    "JARVIS_STT_LANG", "JARVIS_TTS_VOICE_ZH", "JARVIS_TTS_VOICE_EN",
    "JARVIS_SCREENSHOT_MAX_EDGE", "JARVIS_LOCAL_ROUTER",
}
SECRET = {"ANTHROPIC_API_KEY", "GEMINI_API_KEY", "HA_TOKEN"}


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def user_env_path() -> Path:
    """使用者層級的設定檔（登入畫面寫這裡）：~/.jarvis/.env"""
    return Path.home() / ".jarvis" / ".env"


def env_path() -> Path:
    """讀取用：第一個存在的 .env（工作目錄 → 專案 / exe 目錄 → ~/.jarvis）。都沒有就回使用者路徑。"""
    from .config import env_candidates

    for p in map(Path, env_candidates()):
        if p.is_file():
            return p
    return user_env_path()


def write_path() -> Path:
    """寫入用：現有的 .env 可寫就寫它；否則（Program Files、唯讀）退到 ~/.jarvis/.env。"""
    p = env_path()
    if p.is_file():
        if os.access(p, os.W_OK):
            return p
        return user_env_path()
    return p


def _ensure_file(p: Path) -> None:
    if p.is_file():
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    # 範本：開發時在專案根目錄；PyInstaller onedir 版在 _internal（sys._MEIPASS）
    candidates = [project_root() / ".env.example", Path(getattr(sys, "_MEIPASS", "")) / ".env.example"]
    example = next((c for c in candidates if c.is_file()), None)
    p.write_text(example.read_text(encoding="utf-8") if example else "", encoding="utf-8")
    try:  # 金鑰檔只給自己讀（Windows 的 chmod 大致無效，靠使用者目錄本身的 ACL）
        os.chmod(p, 0o600)
    except OSError:
        pass


def read() -> dict[str, str]:
    out: dict[str, str] = {}
    p = env_path()
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def masked(value: str) -> str:
    if not value:
        return ""
    return "•" * 6 + value[-4:] if len(value) > 8 else "•" * len(value)


def update(changes: dict[str, str]) -> Path:
    """寫入變更。只接受 EDITABLE 的鍵；值裡有換行一律拒絕（防止注入多行）。"""
    p = write_path()
    _ensure_file(p)
    lines = p.read_text(encoding="utf-8").splitlines()
    pending = {k: str(v).strip() for k, v in changes.items() if k in EDITABLE}
    for k, v in pending.items():
        if "\n" in v or "\r" in v:
            raise ValueError(f"{k} 的值不能有換行")
    for i, line in enumerate(lines):
        m = re.match(r"^\s*#?\s*([A-Z0-9_]+)\s*=", line)
        if not m or m.group(1) not in pending:
            continue
        k = m.group(1)
        lines[i] = f"{k}={pending.pop(k)}"
    for k, v in pending.items():
        lines.append(f"{k}={v}")
    p.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    for k, v in {k: str(v).strip() for k, v in changes.items() if k in EDITABLE}.items():
        os.environ[k] = v
    from . import config

    config.reload()  # 同一個程序裡的 settings 立刻生效（不然要重開）
    return p
