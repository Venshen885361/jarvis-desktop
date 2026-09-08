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


def env_path() -> Path:
    for folder in (Path.cwd(), project_root()):
        if (folder / ".env").is_file():
            return folder / ".env"
    return project_root() / ".env"


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
    p = env_path()
    if not p.is_file():
        example = project_root() / ".env.example"
        p.write_text(example.read_text(encoding="utf-8") if example.is_file() else "", encoding="utf-8")
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
    return p
