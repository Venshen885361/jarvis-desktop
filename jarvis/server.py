"""Server mode：讓手機（或任何 HTTP client）當 JARVIS 的遙控器。

    python -m jarvis --serve            # 預設 0.0.0.0:8080，HUD WebSocket 也會綁到 0.0.0.0

設計：對話迴圈一行不改。listen() 在文字模式會從 speech._text_queue 拿輸入，
speak() 會把回覆丟到 hud 事件匯流排（emit_log("JARVIS", …)）。這支只是把兩端接到網路上：

  POST /api/ask  {"text": "..."}       → 塞進 queue，等下一則 JARVIS 回覆，回 {"reply", "steps", "ms"}
  GET  /api/status                     → provider / 裝置 / 用量
  POST /api/device {"name": "pc"}      → 切換控制目標
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

text_queue: "queue.Queue[str]" = queue.Queue()
_ask_lock = threading.Lock()          # 對話迴圈是單執行緒，同時只能有一個問題在跑
_token = ""


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


def _status() -> dict:
    from .devices import get_devices

    devs = get_devices()
    return {
        "provider": settings.provider,
        "device": devs.current_name,
        "devices": devs.names(),
        "usage": tracker.snapshot(),
        "text_mode": settings.text_mode,
        "ws_port": settings.ws_port,
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "jarvis/1"

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
            return self._json(HTTPStatus.OK, ask(text))
        if path == "/api/device":
            from .devices import get_devices

            msg = get_devices().switch(str(body.get("name", "")))
            return self._json(HTTPStatus.OK, {"reply": msg, **_status()})
        self.send_error(HTTPStatus.NOT_FOUND)


def start(host: str, port: int, token: str) -> ThreadingHTTPServer:
    """啟動 HTTP server（背景執行緒）。呼叫端要先把 text_queue 接給 speech.use_text_queue。"""
    global _token
    if not token:
        raise RuntimeError("server mode 需要 JARVIS_AGENT_TOKEN。")
    _token = token
    hud.require_token(token)
    srv = ThreadingHTTPServer((host, port), _Handler)
    threading.Thread(target=srv.serve_forever, name="jarvis-http", daemon=True).start()
    print(f"[server] http://{host}:{port}  （手機 Safari 開這個網址；token 見 .env）")
    return srv
