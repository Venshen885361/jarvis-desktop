"""家電：透過 Home Assistant 的 REST API。

為什麼走 HA 而不是直接接米家 / Tuya / Broadlink：HA 已經幫每個品牌寫好整合，
JARVIS 只要會「找 entity → 呼叫 service」，之後家裡多什麼裝置都不用改這裡。

.env
  HA_URL=http://homeassistant.local:8123   # Pi 上 Docker 跑的 HA，或家裡既有的
  HA_TOKEN=長效存取權杖                      # HA → 個人資料 → 安全性 → 長效存取權杖

API：https://developers.home-assistant.io/docs/api/rest/
  GET  /api/states                              所有 entity 與狀態
  POST /api/services/<domain>/<service>  {"entity_id": ...}

entity 比對：用 friendly_name（HA 裡你取的中文名，例如「客廳燈」）做包含比對，
再退回 entity_id。找不到就把候選清單回給模型 / 使用者，不要亂猜。
"""

from __future__ import annotations

import os
import time

import requests

from ..hud import emit_log

_DOMAIN_WORDS = {
    "light": ("燈", "light", "lamp"),
    "switch": ("插座", "開關", "switch", "plug"),
    "climate": ("冷氣", "空調", "暖氣", "ac", "climate"),
    "fan": ("電扇", "風扇", "fan"),
    "media_player": ("電視", "音響", "喇叭", "tv", "speaker"),
    "cover": ("窗簾", "捲門", "curtain", "blind"),
    "lock": ("門鎖", "lock"),
}

_cache: dict = {"ts": 0.0, "states": []}


def _cfg() -> tuple[str, dict]:
    url = os.environ.get("HA_URL", "").rstrip("/")
    token = os.environ.get("HA_TOKEN", "")
    if not url or not token:
        raise RuntimeError("未設定 HA_URL / HA_TOKEN（Home Assistant 位址與長效存取權杖）。")
    return url, {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _states(max_age: float = 15.0) -> list[dict]:
    if time.time() - _cache["ts"] > max_age:
        url, headers = _cfg()
        try:
            r = requests.get(f"{url}/api/states", headers=headers, timeout=8)
        except requests.RequestException as e:
            raise RuntimeError(f"連不到 {url}（HA_URL 對嗎？Pi 跟 HA 同一個網路嗎？）") from None
        if r.status_code == 401:
            raise RuntimeError("HA_TOKEN 無效（HA → 個人資料 → 安全性 → 長效存取權杖）")
        r.raise_for_status()
        _cache["states"] = r.json()
        _cache["ts"] = time.time()
    return _cache["states"]


def _find(query: str) -> list[dict]:
    """依名稱找 entity。回傳候選（可能多個），呼叫端決定要不要動手。"""
    q = query.strip().lower().replace(" ", "")
    if not q:
        return []
    hits = []
    for st in _states():
        eid = st["entity_id"]
        name = str(st.get("attributes", {}).get("friendly_name", "")).lower().replace(" ", "")
        if q == name or q == eid:
            return [st]
        if q in name or q in eid:
            hits.append(st)
    # 「燈」這種只講類別的：把該 domain 全列出來
    if not hits:
        for domain, words in _DOMAIN_WORDS.items():
            if any(w in q for w in words):
                hits = [s for s in _states() if s["entity_id"].startswith(domain + ".")]
                break
    return hits


def _call(domain: str, service: str, data: dict) -> None:
    url, headers = _cfg()
    r = requests.post(f"{url}/api/services/{domain}/{service}", headers=headers, json=data, timeout=10)
    r.raise_for_status()
    _cache["ts"] = 0.0  # 下次查狀態要重抓


def _label(st: dict) -> str:
    return st.get("attributes", {}).get("friendly_name") or st["entity_id"]


# ---------------------------------------------------------------------------
# 工具（模型與本機路由都用這幾個）
# ---------------------------------------------------------------------------
def home_control(device: str, action: str, value: str = "") -> str:
    """控制家電（透過 Home Assistant）。

    Args:
        device: 裝置名稱，用 Home Assistant 裡的名字，例如「客廳燈」「冷氣」「電視」；
            只講類別（「燈」）且家裡只有一盞會直接做，多盞會回候選清單。
        action: on / off / toggle / set。
        value: action=set 時用：冷氣溫度（"26"）、燈亮度 0-100（"40"）、音量 0-100。
    """
    try:
        hits = _find(device)
    except Exception as e:
        return f"Sir, 連不上 Home Assistant：{e}"
    if not hits:
        return f"Sir, Home Assistant 裡找不到「{device}」。用 home_list 看看有哪些裝置。"
    if len(hits) > 1 and action != "set":
        names = "、".join(_label(h) for h in hits[:8])
        # 「關掉所有燈」這種語意：同 domain 一起做
        if any(w in device for ws in _DOMAIN_WORDS.values() for w in ws) and len(hits) <= 8:
            for h in hits:
                _do(h, action, value)
            return f"Sir, 已{ '開啟' if action == 'on' else '關閉' if action == 'off' else '切換' }：{names}。"
        return f"Sir, 有多個符合的裝置：{names}。請指定哪一個。"
    st = hits[0]
    try:
        return _do(st, action, value)
    except Exception as e:
        return f"Sir, 操作 {_label(st)} 失敗：{e}"


def _do(st: dict, action: str, value: str) -> str:
    eid = st["entity_id"]
    domain = eid.split(".")[0]
    label = _label(st)
    emit_log("SYS", f"HA {action} {eid} {value}")
    if action in ("on", "off", "toggle"):
        service = {"on": "turn_on", "off": "turn_off", "toggle": "toggle"}[action]
        if domain == "cover":
            service = {"on": "open_cover", "off": "close_cover", "toggle": "toggle"}[action]
        if domain == "lock":
            service = {"on": "lock", "off": "unlock", "toggle": "unlock"}[action]
        _call(domain, service, {"entity_id": eid})
        return f"Sir, {label} 已{ {'on': '開啟', 'off': '關閉', 'toggle': '切換'}[action] }。"
    if action == "set":
        v = str(value).strip()
        if not v:
            return "Sir, set 需要一個數值。"
        if domain == "climate":
            _call("climate", "set_temperature", {"entity_id": eid, "temperature": float(v)})
            return f"Sir, {label} 已設為 {v} 度。"
        if domain == "light":
            _call("light", "turn_on", {"entity_id": eid, "brightness_pct": int(float(v))})
            return f"Sir, {label} 亮度已設為 {v}%。"
        if domain == "media_player":
            _call("media_player", "volume_set", {"entity_id": eid, "volume_level": max(0.0, min(1.0, float(v) / 100))})
            return f"Sir, {label} 音量已設為 {v}%。"
        if domain == "fan":
            _call("fan", "set_percentage", {"entity_id": eid, "percentage": int(float(v))})
            return f"Sir, {label} 風速已設為 {v}%。"
        if domain == "cover":
            _call("cover", "set_cover_position", {"entity_id": eid, "position": int(float(v))})
            return f"Sir, {label} 已開到 {v}%。"
        return f"Sir, {label}（{domain}）不支援設定數值。"
    return f"Sir, 不認得的動作：{action}（用 on / off / toggle / set）。"


def home_status(device: str = "") -> str:
    """查家電目前狀態。device 留空 = 列出所有燈 / 開關 / 冷氣的狀態摘要。"""
    try:
        hits = _find(device) if device else [
            s for s in _states() if s["entity_id"].split(".")[0] in _DOMAIN_WORDS
        ]
    except Exception as e:
        return f"Sir, 連不上 Home Assistant：{e}"
    if not hits:
        return f"Sir, 找不到「{device}」。"
    lines = []
    for st in hits[:20]:
        a = st.get("attributes", {})
        extra = ""
        if "temperature" in a:
            extra = f" 設定 {a['temperature']}°"
            if "current_temperature" in a:
                extra += f"／目前 {a['current_temperature']}°"
        elif "brightness" in a and a["brightness"] is not None:
            extra = f" 亮度 {round(a['brightness'] / 255 * 100)}%"
        lines.append(f"{_label(st)}：{st['state']}{extra}")
    return "\n".join(lines)


def home_list() -> str:
    """列出 Home Assistant 裡可以控制的裝置（名稱與類別），找不到裝置名時先呼叫這個。"""
    try:
        sts = _states()
    except Exception as e:
        return f"Sir, 連不上 Home Assistant：{e}"
    by_domain: dict[str, list[str]] = {}
    for st in sts:
        d = st["entity_id"].split(".")[0]
        if d in _DOMAIN_WORDS:
            by_domain.setdefault(d, []).append(_label(st))
    if not by_domain:
        return "Home Assistant 裡沒有燈 / 開關 / 冷氣類的裝置。"
    return "\n".join(f"{d}：{'、'.join(sorted(v)[:15])}" for d, v in sorted(by_domain.items()))
