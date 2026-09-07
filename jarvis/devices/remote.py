"""RemoteDevice：透過 WebSocket 操作跑著 `python -m jarvis.agent` 的另一台電腦。

協定（一行 JSON 一則訊息）：
  → {"type": "auth", "token": "..."}
  ← {"type": "auth", "ok": true, "platform": "windows", "name": "desktop"}
  → {"id": 1, "tool": "computer:screenshot", "args": {}}
  ← {"id": 1, "ok": true, "image": {"b64": "...", "media_type": "image/jpeg", "width": 1024, "height": 576}}
  → {"id": 2, "tool": "open_application", "args": {"app_name": "Firefox"}}
  ← {"id": 2, "ok": true, "result": "Sir, Firefox 已啟動。"}
  ← {"id": 3, "ok": false, "error": "..."}

用 websockets 的同步 client（12.0+ 才有），因為 provider 的 agent loop 本來就是同步的，
沒必要為了一條連線把整個主流程改成 async。斷線會在下一次呼叫時自動重連一次。
"""

from __future__ import annotations

import json
import threading

from .base import Device, ImageResult, ToolOutput


class RemoteDevice(Device):
    kind = "remote"

    def __init__(self, name: str, url: str, token: str = "", timeout: float = 60.0) -> None:
        self.name = name
        self.url = url
        self.token = token
        self.timeout = timeout
        self._ws = None
        self._seq = 0
        self._lock = threading.Lock()
        self.platform = "unknown"

    # ------------------------------------------------------------------
    def _connect(self) -> None:
        from websockets.sync.client import connect

        self._ws = connect(self.url, open_timeout=10, max_size=16 * 1024 * 1024)
        self._ws.send(json.dumps({"type": "auth", "token": self.token}))
        hello = json.loads(self._ws.recv(timeout=10))
        if not hello.get("ok"):
            self._ws.close()
            self._ws = None
            raise ConnectionError(f"{self.name}: agent 拒絕連線（{hello.get('error', 'token 錯誤')}）")
        self.platform = hello.get("platform", "unknown")

    def _ensure(self) -> None:
        if self._ws is None:
            self._connect()

    def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def status(self) -> str:
        return "已連線" if self._ws is not None else "未連線（需要時會自動連）"

    def ping(self) -> bool:
        try:
            with self._lock:
                self._ensure()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    def call(self, tool: str, args: dict) -> ToolOutput:
        with self._lock:
            for attempt in (1, 2):
                try:
                    self._ensure()
                    self._seq += 1
                    self._ws.send(json.dumps({"id": self._seq, "tool": tool, "args": args or {}}))
                    reply = json.loads(self._ws.recv(timeout=self.timeout))
                    break
                except (ConnectionError, OSError) as e:
                    self.close()
                    if attempt == 2:
                        raise ConnectionError(f"{self.name}: 連不上 agent（{e}）") from e
                except Exception as e:
                    # websockets 的 ConnectionClosed 不是 OSError 子類，這裡一併當成斷線重連
                    self.close()
                    if attempt == 2:
                        raise ConnectionError(f"{self.name}: 連線中斷（{e}）") from e

        if not reply.get("ok"):
            raise RuntimeError(reply.get("error", "agent 回報失敗"))
        if "image" in reply:
            im = reply["image"]
            return ImageResult(im["b64"], im["media_type"], im["width"], im["height"])
        return str(reply.get("result", ""))
