"""HUD WebSocket 橋接。

設計重點沿用原版：
- WS server 跑在獨立背景執行緒 + 自己的 event loop，不阻塞同步的語音／GUI 主流程。
- ws_emit() 是給同步程式碼呼叫的 thread-safe 入口。
- 前端沒開、或沒裝 websockets 套件時一律安靜略過，HUD 壞掉不能拖垮本體。
"""

from __future__ import annotations

import asyncio
import json
import threading

from .config import settings
from .usage import tracker

try:
    import websockets
except ImportError:  # pragma: no cover - 選用相依
    websockets = None  # type: ignore[assignment]

_ws_clients: set = set()
_ws_loop: asyncio.AbstractEventLoop | None = None
_ws_ready = threading.Event()

# 行程內的訂閱者（桌邊寵物用）。跟 WebSocket 收到的是同一份事件。
_listeners: list = []


def subscribe(fn) -> None:
    """fn(payload: dict) 會在 emit 的那個執行緒被呼叫，訂閱者自己要 thread-safe。"""
    _listeners.append(fn)


def unsubscribe(fn) -> None:
    try:
        _listeners.remove(fn)
    except ValueError:
        pass


# server mode 才會設：WebSocket 第一則訊息必須是 {"type":"auth","token":...}
_required_token: str | None = None


def require_token(token: str) -> None:
    global _required_token
    _required_token = token or None


async def _ws_handler(websocket):
    if _required_token:
        import secrets

        try:
            first = json.loads(await asyncio.wait_for(websocket.recv(), timeout=10))
            ok = first.get("type") == "auth" and secrets.compare_digest(str(first.get("token", "")), _required_token)
        except Exception:
            ok = False
        if not ok:
            try:
                await websocket.send(json.dumps({"type": "auth", "ok": False}))
                await websocket.close()
            except Exception:
                pass
            return
        await websocket.send(json.dumps({"type": "auth", "ok": True}))
    _ws_clients.add(websocket)
    print(f"[HUD] 前端已連線（共 {len(_ws_clients)} 個）。")
    try:
        async for _ in websocket:  # 前端目前只收不送
            pass
    except Exception:
        pass
    finally:
        _ws_clients.discard(websocket)


async def _broadcast_async(payload: dict) -> None:
    if not _ws_clients:
        return
    data = json.dumps(payload, ensure_ascii=False)
    dead = []
    for ws in list(_ws_clients):
        try:
            await ws.send(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.discard(ws)


def ws_emit(payload: dict) -> None:
    for fn in _listeners:
        try:
            fn(payload)
        except Exception:
            pass
    if _ws_loop is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(_broadcast_async(payload), _ws_loop)
    except Exception:
        pass


def emit_state(state: str) -> None:
    """state: 'standby' | 'listening' | 'thinking' | 'speaking'"""
    ws_emit({"type": "state", "state": state})


def emit_log(tag: str, text: str) -> None:
    """tag: 'SYS' | 'SIR' | 'JARVIS'"""
    ws_emit({"type": "log", "tag": tag, "text": text})


def emit_tool(name: str, args: dict) -> None:
    ws_emit({"type": "tool", "name": name, "args": _safe_args(args)})


def emit_usage() -> None:
    """把目前累計的 token / 成本推到 HUD 的 Token Budget 面板。"""
    ws_emit({"type": "usage", **tracker.snapshot()})


def emit_provider(name: str, model: str) -> None:
    ws_emit({"type": "provider", "provider": name, "model": model})


def _safe_args(args: dict) -> dict:
    """截斷過長的參數，避免一張 base64 截圖被塞進 HUD 日誌。"""
    out = {}
    for k, v in (args or {}).items():
        s = str(v)
        out[k] = s if len(s) <= 120 else s[:120] + "…"
    return out


def _run_ws_server() -> None:
    global _ws_loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _ws_loop = loop

    async def _serve():
        async with websockets.serve(_ws_handler, settings.ws_host, settings.ws_port):
            print(f"[HUD] ws://{settings.ws_host}:{settings.ws_port} 已啟動")
            _ws_ready.set()
            await asyncio.Future()

    loop.run_until_complete(_serve())


def start_ws_server() -> None:
    if websockets is None:
        print("[警告] 未安裝 websockets，HUD 不會連動（不影響本體）。")
        return
    threading.Thread(target=_run_ws_server, daemon=True).start()
    _ws_ready.wait(timeout=5)
