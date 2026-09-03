"""進入點：python -m jarvis"""

from __future__ import annotations

import argparse
import sys

from .config import settings
from .hud import emit_log, emit_provider, emit_state, emit_usage, start_ws_server
from .router import try_local
from .speech import listen, speak
from .usage import tracker

_EXIT_WORDS = (
    "再見", "關機", "掰掰", "退出", "關閉賈維斯", "關閉桌寵", "關閉寵物", "下班",
    "bye", "quit", "exit",
)


class _LazyProvider:
    """延後建立 provider：本機路由處理得掉的指令不需要金鑰，
    讓沒填金鑰的人也能先 `python -m jarvis --text --once "現在幾點"` 試玩。
    """

    def __init__(self) -> None:
        self._p = None
        self._failed: str | None = None

    def get(self):
        if self._p is None and self._failed is None:
            from .providers import get_provider

            try:
                self._p = get_provider()
                emit_provider(self._p.name, self._p.model)
            except Exception as e:
                self._failed = str(e)
        return self._p

    @property
    def name(self) -> str:
        return self._p.name if self._p else settings.provider

    @property
    def model(self) -> str:
        return self._p.model if self._p else "(未初始化)"

    def remember(self, user_text: str, reply: str) -> None:
        if self._p is not None:
            self._p.remember(user_text, reply)

    def run_turn(self, user_text: str) -> str:
        p = self.get()
        if p is None:
            return f"Sir, 模型後端無法啟動：{self._failed}"
        return p.run_turn(user_text)


def _banner(provider) -> None:
    print("=" * 58)
    print(f"  J.A.R.V.I.S.  provider={provider.name}  model={provider.model}")
    print(f"  平台：{__import__('sys').platform}  |  本機路由："
          f"{'開' if settings.enable_local_router else '關'}"
          f"  |  prompt cache：{'開' if settings.enable_prompt_cache else '關'}")
    print("  介面：桌邊寵物（右鍵選單可退出；--hud 另開網頁 HUD；--no-pet 純終端機）")
    print("=" * 58)


def _report_usage() -> None:
    s = tracker.snapshot()
    print(
        f"\n[用量] API 呼叫 {s['api_calls']} 次 / 本機處理 {s['local_hits']} 次"
        f"（本機占比 {s['local_ratio']}%）\n"
        f"       input {s['input']} · output {s['output']} · "
        f"cache read {s['cache_read']} · 估計成本 ${s['cost_usd']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="jarvis")
    parser.add_argument(
        "--text", action="store_true", help="純文字模式（不用麥克風與喇叭）"
    )
    parser.add_argument(
        "--provider", choices=["claude", "gemini"], help="覆寫 JARVIS_PROVIDER"
    )
    parser.add_argument("--once", metavar="指令", help="執行單一指令後結束")
    parser.add_argument(
        "--no-pet", action="store_true", help="不顯示桌邊寵物，只用終端機（與 HUD 網頁）"
    )
    parser.add_argument(
        "--hud", action="store_true", help="同時啟動 WebSocket 供 hud/jarvis_hub.html 連線"
    )
    args = parser.parse_args()

    if args.text or args.once:
        object.__setattr__(settings, "text_mode", True)
    if args.provider:
        object.__setattr__(settings, "provider", args.provider)

    provider = _LazyProvider()
    if args.hud or args.no_pet:
        start_ws_server()
    _banner(provider)

    if args.once:
        _handle(provider, args.once)
        _report_usage()
        return 0

    if args.no_pet:
        _conversation_loop(provider)
        _report_usage()
        return 0

    # 預設：桌邊寵物在主執行緒畫圖，賈維斯主流程搬到背景執行緒
    from . import speech
    from .pet import DesktopPet

    pet = DesktopPet()
    if settings.text_mode:
        speech.use_text_queue(pet.text_queue)  # 打字改在寵物下方的輸入框
        print("[系統] 文字模式：請在桌邊寵物下方的輸入框輸入指令。")
    pet.run(worker=lambda: _conversation_loop(provider))
    return 0


def _conversation_loop(provider) -> None:
    speak("J.A.R.V.I.S. online. Systems ready, Sir.")
    while True:
        try:
            user_input = listen()
        except KeyboardInterrupt:
            break
        if not user_input:
            continue
        if any(w in user_input.lower() for w in _EXIT_WORDS):
            speak("Shutting down core systems. Have a good day, Sir.")
            break
        _handle(provider, user_input)
    emit_state("standby")
    _report_usage()


def _handle(provider, user_input: str) -> None:
    # 本機優先：能自己做完就完全不打 API
    local = try_local(user_input)
    if local is not None:
        emit_log("SYS", "本機處理，未呼叫 API。")
        provider.remember(user_input, local)
        speak(local)
        emit_usage()
        return

    try:
        reply = provider.run_turn(user_input)
    except Exception as e:
        emit_log("SYS", f"模型呼叫失敗：{e}")
        reply = f"Sir, 這個指令執行時發生問題：{e}"
    speak(reply)
    emit_usage()


if __name__ == "__main__":
    sys.exit(main())
