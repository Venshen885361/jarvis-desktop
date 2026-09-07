"""HubDevice：讓「主動連進來」的裝置（Android App）也能被大腦操作。

RemoteDevice 是大腦去連 agent；手機在 NAT / 熱點 / 行動網路後面，反過來比較合理：
大腦開一個 WebSocket server（hub），手機 App 主動連上來報到，之後大腦要操作它時
就從 hub 找到那條連線送指令。

協定與 agent.py 完全對稱（一行 JSON 一則訊息）：
  App → {"type": "hello", "token": "...", "name": "phone", "platform": "android"}
  Hub → {"type": "hello", "ok": true}
  Hub → {"id": 1, "tool": "computer:screenshot", "args": {}}
  App → {"id": 1, "ok": true, "image": {...}} / {"id": 1, "ok": true, "result": "..."} / {"id": 1, "ok": false, "error": "..."}

.env：
  JARVIS_DEVICES=phone=hub://phone      # 名稱要跟 App 裡填的「裝置名稱」一樣
  JARVIS_AGENT_TOKEN=同一組密語          # App 那邊也填這個
  JARVIS_HUB_PORT=8771                  # 預設 8771，Tailscale 下手機連 <Pi 的 100.x IP>:8771

安全：沒 token 不啟動；hello 的 token 錯就斷線。
"""

from __future__ import annotations

import json
import secrets
import threading
import time

from ..config import settings
from .base import Device, ImageResult, ToolOutput


class _Peer:
    """一條已報到的 App 連線。send 與 recv 在不同執行緒（websockets sync 允許）。"""

    def __init__(self, ws, name: str, platform: str) -> None:
        self.ws = ws
        self.name = name
        self.platform = platform
        self._seq = 0
        self._pending: dict[int, dict] = {}
        self._cv = threading.Condition()
        self.alive = True

    def request(self, tool: str, args: dict, timeout: float) -> dict:
        with self._cv:
            self._seq += 1
            req_id = self._seq
        self.ws.send(json.dumps({"id": req_id, "tool": tool, "args": args or {}}, ensure_ascii=False))
        deadline = time.monotonic() + timeout
        with self._cv:
            while req_id not in self._pending:
                if not self.alive:
                    raise ConnectionError("手機連線已中斷")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"手機 {timeout:.0f} 秒內沒有回應")
                self._cv.wait(remaining)
            return self._pending.pop(req_id)

    def deliver(self, msg: dict) -> None:
        with self._cv:
            self._pending[int(msg["id"])] = msg
            self._cv.notify_all()

    def kill(self) -> None:
        with self._cv:
            self.alive = False
            self._cv.notify_all()


class Hub:
    def __init__(self, host: str, port: int, token: str) -> None:
        self.host, self.port, self.token = host, port, token
        self._peers: dict[str, _Peer] = {}
        self._lock = threading.Lock()
        self._server = None

    def start(self) -> None:
        from websockets.sync.server import serve

        self._server = serve(self._handle, self.host, self.port, max_size=16 * 1024 * 1024)
        threading.Thread(target=self._server.serve_forever, name="jarvis-hub", daemon=True).start()
        print(f"[hub] 等待手機 App 連線：ws://{self.host}:{self.port}")

    def peer(self, name: str) -> _Peer | None:
        with self._lock:
            return self._peers.get(name)

    def _handle(self, ws) -> None:
        try:
            first = json.loads(ws.recv(timeout=10))
        except Exception:
            ws.close()
            return
        if first.get("type") != "hello" or not secrets.compare_digest(str(first.get("token", "")), self.token):
            ws.send(json.dumps({"type": "hello", "ok": False, "error": "token 錯誤"}))
            ws.close()
            print("[hub] 拒絕連線：token 錯誤")
            return
        name = str(first.get("name") or "phone")
        peer = _Peer(ws, name, str(first.get("platform") or "android"))
        with self._lock:
            old = self._peers.get(name)
            self._peers[name] = peer
        if old is not None:
            old.kill()
            try:
                old.ws.close()
            except Exception:
                pass
        ws.send(json.dumps({"type": "hello", "ok": True, "name": name}))
        print(f"[hub] {name}（{peer.platform}）已連線")
        try:
            for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if "id" in msg:
                    peer.deliver(msg)
        except Exception:
            pass
        finally:
            peer.kill()
            with self._lock:
                if self._peers.get(name) is peer:
                    del self._peers[name]
            print(f"[hub] {name} 已離線")


_hub: Hub | None = None
_hub_lock = threading.Lock()


def get_hub() -> Hub:
    global _hub
    with _hub_lock:
        if _hub is None:
            if not settings.agent_token:
                raise RuntimeError("hub:// 裝置需要 JARVIS_AGENT_TOKEN（手機 App 用同一組密語連線）。")
            _hub = Hub(settings.hub_host, settings.hub_port, settings.agent_token)
            _hub.start()
        return _hub


class HubDevice(Device):
    kind = "remote"

    def __init__(self, name: str, peer_name: str = "", timeout: float = 60.0) -> None:
        self.name = name
        self.peer_name = peer_name or name
        self.timeout = timeout
        self.platform = "android"
        get_hub()

    def _peer(self) -> _Peer:
        p = get_hub().peer(self.peer_name)
        if p is None:
            raise ConnectionError(
                f"手機「{self.peer_name}」還沒連上 hub。請確認 App 有開、位址填 ws://<大腦IP>:{settings.hub_port}、密語一致。"
            )
        self.platform = p.platform
        return p

    def ping(self) -> bool:
        try:
            self._peer().request("ping", {}, timeout=5)
            return True
        except Exception:
            return False

    def call(self, tool: str, args: dict) -> ToolOutput:
        reply = self._peer().request(tool, args or {}, self.timeout)
        if not reply.get("ok"):
            raise RuntimeError(reply.get("error", "手機回報失敗"))
        if "image" in reply:
            im = reply["image"]
            return ImageResult(im["b64"], im["media_type"], im["width"], im["height"])
        return str(reply.get("result", ""))
