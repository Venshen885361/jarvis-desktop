"""jarvis-agent：跑在「被操作的電腦」上的手腳 daemon。

    python -m jarvis.agent --port 8770 --token 你的密語

大腦（Pi 或另一台電腦）用 RemoteDevice 連進來，透過 WebSocket 呼叫這台機器的
工具與 computer 動作。這支程式本身不聽麥克風、不打任何 API、不需要金鑰 ——
它只是把 LocalDevice 掛到網路上。

安全：
- 一定要設 token。沒 token 直接拒絕啟動，不提供「先跑起來再說」的選項，
  因為這個 daemon 等於把整台電腦的滑鼠鍵盤交給連得上的人。
- 預設綁 0.0.0.0 是為了 Tailscale；若沒用 Tailscale 請自己改成 Tailscale IP
  或 127.0.0.1，不要把它暴露在公網。
- 每個連線第一則訊息必須是 auth，錯一次就斷。
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys

from .config import settings
from .devices.local import LocalDevice
from .hud import subscribe


def _handle(ws, device: LocalDevice, token: str) -> None:
    try:
        peer = str(ws.remote_address)  # 關閉後就拿不到了，先存起來
    except Exception:
        peer = "?"
    try:
        first = json.loads(ws.recv(timeout=10))
    except Exception:
        ws.close()
        return
    if first.get("type") != "auth" or not secrets.compare_digest(str(first.get("token", "")), token):
        ws.send(json.dumps({"type": "auth", "ok": False, "error": "token 錯誤"}))
        ws.close()
        print(f"[agent] 拒絕連線：{peer}")
        return
    ws.send(json.dumps({"type": "auth", "ok": True, "platform": device.platform, "name": device.name}))
    print(f"[agent] 大腦已連線：{peer}")

    for raw in ws:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        req_id = msg.get("id")
        tool = msg.get("tool", "")
        args = msg.get("args") or {}
        print(f"[agent] {tool}({_short(args)})")
        try:
            out = device.call(tool, args)
            if hasattr(out, "b64"):
                reply = {
                    "id": req_id, "ok": True,
                    "image": {"b64": out.b64, "media_type": out.media_type,
                              "width": out.width, "height": out.height},
                }
            else:
                reply = {"id": req_id, "ok": True, "result": str(out)}
        except Exception as e:
            reply = {"id": req_id, "ok": False, "error": str(e)}
        try:
            ws.send(json.dumps(reply, ensure_ascii=False))
        except Exception:
            break
    print(f"[agent] 大腦已離線：{peer}")


def _short(args: dict) -> str:
    return ", ".join(f"{k}={str(v)[:40]}" for k, v in args.items())


def main() -> int:
    parser = argparse.ArgumentParser(prog="jarvis.agent", description="JARVIS 手腳 daemon")
    parser.add_argument("--host", default=settings.agent_host)
    parser.add_argument("--port", type=int, default=settings.agent_port)
    parser.add_argument("--token", default=settings.agent_token, help="預先共享密語（或設 JARVIS_AGENT_TOKEN）")
    parser.add_argument("--name", default=None, help="這台裝置的名字（預設用主機名）")
    args = parser.parse_args()

    if not args.token:
        print("[agent] 必須提供 --token 或設定 JARVIS_AGENT_TOKEN。"
              "這個 daemon 會把整台電腦的操作權交給連上的人，不能沒有密語。")
        return 1

    try:
        from websockets.sync.server import serve
    except ImportError:
        print("[agent] 需要 websockets>=12：pip install websockets")
        return 1

    import socket

    device = LocalDevice(args.name or socket.gethostname())
    subscribe(lambda _payload: None)  # 讓 tools 內的 emit_* 不會因為沒有 HUD 而報錯

    print("=" * 58)
    print(f"  jarvis-agent  {device.name}  ({device.platform})")
    print(f"  ws://{args.host}:{args.port}   token: {'*' * 8}{args.token[-4:]}")
    print("  等待大腦連線… Ctrl+C 結束")
    print("=" * 58)

    with serve(lambda ws: _handle(ws, device, args.token), args.host, args.port,
               max_size=16 * 1024 * 1024) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
