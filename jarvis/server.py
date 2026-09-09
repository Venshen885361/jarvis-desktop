"""Server mode：讓手機（或任何 HTTP client）當 JARVIS 的遙控器。

    python -m jarvis --serve            # 預設 0.0.0.0:8080，HUD WebSocket 也會綁到 0.0.0.0

設計：對話迴圈一行不改。listen() 在文字模式會從 speech._text_queue 拿輸入，
speak() 會把回覆丟到 hud 事件匯流排（emit_log("JARVIS", …)）。這支只是把兩端接到網路上：

  POST /api/ask  {"text": "..."}       → 塞進 queue，等下一則 JARVIS 回覆，回 {"reply", "steps", "ms"}
  GET  /api/status                     → provider / 裝置 / 用量
  POST /api/device {"name": "pc"}      → 切換控制目標
  GET  /api/settings                   → 可編輯的設定（金鑰遮罩）+ 使用者檔案 + 是否需要初次設定
  POST /api/settings {"env": {...}, "profile": {...}}
                                       → 寫 .env / profile.json，立刻生效（provider 重建）
  GET  /                               → hud/mobile.html（iPhone 加到主畫面就是 PWA）
  GET  /manifest.webmanifest           → PWA manifest
  WS   ws://host:8765                  → 即時事件（state / log / tool），沿用 HUD 的 WebSocket

認證：所有 /api/* 與 WebSocket 都要 token（JARVIS_AGENT_TOKEN）。
HTTP 用 `Authorization: Bearer <token>` 或 `?token=`；WebSocket 第一則訊息 {"type":"auth","token"}。
沒設 token 不啟動 —— 這個 server 等於把整台電腦 / 家電的控制權交給連得上的人。
建議只在 Tailscale 網段上開；要走公網請前面加 TLS 反向代理。
"""

from __future__ import annotations

import json
import os
import queue
import secrets
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import hud
from .config import settings
from .usage import tracker

_STATIC = Path(__file__).resolve().parent.parent / "hud"
# 放這裡的檔案會出現在手機「下載 App」頁：dist/downloads/JARVIS-windows.zip、jarvis-agent.apk …
_DOWNLOADS = Path(__file__).resolve().parent.parent / "dist" / "downloads"
_RELEASES = "https://github.com/Venshen885361/jarvis-desktop/releases/latest"
_DL_TYPES = {".zip": "application/zip", ".apk": "application/vnd.android.package-archive",
             ".exe": "application/octet-stream", ".msi": "application/octet-stream"}

text_queue: queue.Queue[str] = queue.Queue()
# 手機最後回報的位置（選用；PWA 開「分享位置」才會送），給「附近…」類問題用
last_location: dict = {}
_geo_cache: dict = {}


def set_location(lat: float, lon: float) -> None:
    last_location.update({"lat": float(lat), "lon": float(lon), "ts": time.time()})


def _place_name(lat: float, lon: float) -> str:
    """反查地名（OpenStreetMap Nominatim，免金鑰；要帶 User-Agent），依 3 位小數快取。"""
    key = (round(lat, 3), round(lon, 3))
    if key in _geo_cache:
        return _geo_cache[key]
    name = ""
    try:
        import requests

        r = requests.get("https://nominatim.openstreetmap.org/reverse",
                         params={"lat": lat, "lon": lon, "format": "jsonv2", "accept-language": "zh-TW", "zoom": 16},
                         headers={"User-Agent": "jarvis-desktop/1.0 (github.com/Venshen885361/jarvis-desktop)"}, timeout=6)
        a = r.json().get("address", {})
        parts = [a.get(k, "") for k in ("city", "county", "town", "suburb", "city_district", "neighbourhood", "road")]
        name = "".join(dict.fromkeys(p for p in parts if p))
    except Exception:
        pass
    _geo_cache[key] = name
    return name


def context() -> str:
    """給純問答的環境資訊：位置、時間。沒有位置就明講，模型才不會亂猜。"""
    lines = [f"現在時間：{time.strftime('%Y-%m-%d %H:%M %Z')}"]
    if last_location and time.time() - last_location["ts"] < 1800:
        lat, lon = last_location["lat"], last_location["lon"]
        place = _place_name(lat, lon)
        lines.append(f"使用者目前位置：{place or '（無法反查地名）'}，座標 {lat:.5f},{lon:.5f}。「附近」= 這個位置周圍 1–2 公里。")
    else:
        lines.append("使用者位置：未知（手機沒有分享位置）。")
    return "\n".join(lines)
_ask_lock = threading.Lock()          # 對話迴圈是單執行緒，同時只能有一個問題在跑
_token = ""
on_settings_changed = None            # __main__ 掛進來：設定改了要 reset provider


def _setup_needed() -> bool:
    """還沒有能用的模型金鑰 → 前端要跑初次設定精靈。"""
    from . import envfile

    env = envfile.read() | {k: v for k, v in os.environ.items() if k in envfile.EDITABLE}
    prov = (env.get("JARVIS_PROVIDER") or "claude").lower()
    key = env.get("GEMINI_API_KEY" if prov == "gemini" else "ANTHROPIC_API_KEY", "")
    return not key


def _settings_payload() -> dict:
    from . import envfile, profile

    env = envfile.read()
    out = {}
    for k in sorted(envfile.EDITABLE):
        v = os.environ.get(k, env.get(k, ""))
        out[k] = envfile.masked(v) if k in envfile.SECRET else v
    return {"env": out, "profile": profile.public(), "setup_needed": _setup_needed(),
            "env_path": str(envfile.env_path())}


def _apply_settings(body: dict) -> dict:
    """寫入並套用。金鑰欄位若傳回來的是遮罩字串（•••），視為沒改。"""
    from . import envfile, profile
    from .config import settings as cfg

    env_changes = {k: v for k, v in (body.get("env") or {}).items()
                   if k in envfile.EDITABLE and not (k in envfile.SECRET and "•" in str(v))}
    if env_changes:
        envfile.update(env_changes)
        # 同步到已建立的 settings 物件（frozen dataclass，只能這樣改）
        field_map = {
            "JARVIS_PROVIDER": ("provider", lambda v: v.strip().lower()),
            "ANTHROPIC_API_KEY": ("anthropic_api_key", str),
            "ANTHROPIC_WORKSPACE_ID": ("anthropic_workspace_id", str),
            "GEMINI_API_KEY": ("gemini_api_key", str),
            "JARVIS_CLAUDE_MODEL": ("claude_model", str),
            "JARVIS_STT_LANG": ("stt_language", str),
            "JARVIS_TTS_VOICE_ZH": ("tts_voice_zh", str),
            "JARVIS_TTS_VOICE_EN": ("tts_voice_en", str),
        }
        for k, v in env_changes.items():
            if k in field_map and hasattr(cfg, field_map[k][0]):
                object.__setattr__(cfg, field_map[k][0], field_map[k][1](v))
        if "JARVIS_DEVICES" in env_changes or "JARVIS_DEFAULT_DEVICE" in env_changes:
            from . import devices

            devices._registry = None  # 下次 get_devices 重新解析
    prof_changes = {k: v for k, v in (body.get("profile") or {}).items()
                    if k in ("name", "style", "lang", "notes", "quick", "onboarded")}
    if prof_changes:
        if "name" in prof_changes:
            prof_changes["name"] = str(prof_changes["name"]).strip()[:20] or "Sir"
        if "quick" in prof_changes:
            prof_changes["quick"] = [str(q).strip()[:40] for q in prof_changes["quick"] if str(q).strip()][:12]
        profile.save(prof_changes)
    if (env_changes or prof_changes) and on_settings_changed:
        on_settings_changed()
        hud.emit_log("SYS", "設定已更新，模型後端重新載入。")
    return _settings_payload()


class _Collector:
    """訂閱 hud 事件，收集這一輪的工具呼叫，直到看到 JARVIS 的回覆。"""

    def __init__(self) -> None:
        self.steps: list[dict] = []
        self.reply: str | None = None
        self.done = threading.Event()

    def __call__(self, payload: dict) -> None:
        t = payload.get("type")
        if t == "tool":
            self.steps.append({"tool": payload.get("name"), "args": payload.get("args")})
        elif t == "log" and payload.get("tag") == "JARVIS":
            self.reply = payload.get("text", "")
            self.done.set()


def ask(text: str, timeout: float = 180.0) -> dict:
    """同步問一句，等到回覆。timeout 給 computer-use 多步驟任務留餘裕。"""
    with _ask_lock:
        col = _Collector()
        hud.subscribe(col)
        t0 = time.monotonic()
        try:
            text_queue.put(text)
            if not col.done.wait(timeout):
                return {"reply": "Sir, 這個指令執行太久了，我先回來聽你說。", "steps": col.steps,
                        "ms": int((time.monotonic() - t0) * 1000), "timeout": True}
            return {"reply": col.reply or "", "steps": col.steps, "ms": int((time.monotonic() - t0) * 1000)}
        finally:
            hud.unsubscribe(col)


def _downloads() -> dict:
    """本機有的安裝檔 + GitHub Releases 連結。分類靠副檔名與檔名關鍵字。"""
    items = []
    if _DOWNLOADS.is_dir():
        for f in sorted(_DOWNLOADS.iterdir()):
            if f.suffix.lower() not in _DL_TYPES or not f.is_file():
                continue
            name = f.name.lower()
            # agent = 被控端（android/ 的 Agent App）；android = 遙控 App（ios-app/ 的 Capacitor 殼）
            if "agent" in name:
                platform = "agent"
            elif f.suffix.lower() == ".apk" or "android" in name:
                platform = "android"
            else:
                platform = "windows"
            items.append({"name": f.name, "platform": platform, "size": f.stat().st_size,
                          "url": f"/downloads/{f.name}"})
    return {"local": items, "releases": _RELEASES}


def _status() -> dict:
    from . import profile
    from .devices import get_devices

    devs = get_devices()
    return {
        "provider": settings.provider,
        "device": devs.current_name,
        "devices": devs.names(),
        "usage": tracker.snapshot(),
        "text_mode": settings.text_mode,
        "ws_port": settings.ws_port,
        "setup_needed": _setup_needed(),
        "top": profile.top_commands(),
        "name": profile.load().get("name", "Sir"),
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "jarvis/1"

    # ---- CORS ----
    # PWA 與網頁同源、不需要；但 iOS App（Capacitor）的頁面來源是 capacitor://localhost，
    # 對 http://<大腦>:8080 的 fetch 是跨來源，瀏覽器會先發 OPTIONS 預檢、再看回應有沒有
    # Access-Control-Allow-Origin，兩個都沒有就直接 "Load failed"。
    # 開放 * 沒問題：每個 API 都要 Bearer token，且不用 cookie（沒有 CSRF 面）。
    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---- helpers ----
    def _authed(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and secrets.compare_digest(auth[7:].strip(), _token):
            return True
        q = parse_qs(urlparse(self.path).query)
        tok = q.get("token", [""])[0]
        return bool(tok) and secrets.compare_digest(tok, _token)

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, name: str, ctype: str) -> None:
        p = _STATIC / name
        if not p.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = p.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            return {}

    def log_message(self, fmt, *args):  # 安靜一點，只印 API
        if "/api/" in str(args[0] if args else ""):
            print(f"[server] {self.address_string()} {args[0]}")

    # ---- routes ----
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._file("mobile.html", "text/html; charset=utf-8")
        if path == "/manifest.webmanifest":
            return self._file("manifest.webmanifest", "application/manifest+json")
        if path == "/icon.png":
            return self._file("icon.png", "image/png")
        if path == "/api/status":
            if not self._authed():
                return self._json(HTTPStatus.UNAUTHORIZED, {"error": "token 錯誤"})
            return self._json(HTTPStatus.OK, _status())
        if path == "/api/settings":
            if not self._authed():
                return self._json(HTTPStatus.UNAUTHORIZED, {"error": "token 錯誤"})
            return self._json(HTTPStatus.OK, _settings_payload())
        if path == "/api/downloads":
            if not self._authed():
                return self._json(HTTPStatus.UNAUTHORIZED, {"error": "token 錯誤"})
            return self._json(HTTPStatus.OK, _downloads())
        if path.startswith("/downloads/"):
            # 瀏覽器下載連結帶不了 header，用 ?token=
            if not self._authed():
                return self._json(HTTPStatus.UNAUTHORIZED, {"error": "token 錯誤"})
            name = Path(path).name
            f = _DOWNLOADS / name
            if "/" in name or not f.is_file() or f.suffix.lower() not in _DL_TYPES:
                return self.send_error(HTTPStatus.NOT_FOUND)
            data = f.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", _DL_TYPES[f.suffix.lower()])
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            return self.send_error(HTTPStatus.NOT_FOUND)
        if not self._authed():
            return self._json(HTTPStatus.UNAUTHORIZED, {"error": "token 錯誤"})
        body = self._body()
        if path == "/api/ask":
            text = str(body.get("text", "")).strip()
            if not text:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": "text 不能空白"})
            hud.emit_log("SYS", f"[手機] {text}")
            from . import profile

            profile.record_command(text)
            loc = body.get("location") or {}
            if isinstance(loc, dict) and "lat" in loc and "lon" in loc:
                try:
                    set_location(loc["lat"], loc["lon"])
                except (TypeError, ValueError):
                    pass
            return self._json(HTTPStatus.OK, ask(text))
        if path == "/api/settings":
            try:
                return self._json(HTTPStatus.OK, _apply_settings(body))
            except Exception as e:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
        if path == "/api/device":
            from .devices import get_devices

            msg = get_devices().switch(str(body.get("name", "")))
            return self._json(HTTPStatus.OK, {"reply": msg, **_status()})
        self.send_error(HTTPStatus.NOT_FOUND)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # 手機切網路 / 關掉分頁時 keep-alive 連線會被對方硬切，Windows 會丟 WinError 10054。
        # 這不是錯誤，不要印一整頁 traceback 嚇人。
        import sys

        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def start(host: str, port: int, token: str) -> ThreadingHTTPServer:
    """啟動 HTTP server（背景執行緒）。呼叫端要先把 text_queue 接給 speech.use_text_queue。"""
    global _token
    if not token:
        raise RuntimeError("server mode 需要 JARVIS_AGENT_TOKEN。")
    _token = token
    hud.require_token(token)
    srv = _Server((host, port), _Handler)
    ssl_ctx = hud.tls_context()
    if ssl_ctx:
        srv.socket = ssl_ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, name="jarvis-http", daemon=True).start()
    scheme = "https" if ssl_ctx else "http"
    print(f"[server] {scheme}://{host}:{port}  （手機 Safari 開這個網址；token 見 .env）")
    if not ssl_ctx:
        print("[server] 提示：iOS 的定位 / 麥克風只在 https 下開放。設 JARVIS_TLS_CERT / JARVIS_TLS_KEY（tailscale cert）即可。")
    return srv
