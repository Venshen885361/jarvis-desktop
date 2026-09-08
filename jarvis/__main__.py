"""進入點：python -m jarvis"""

from __future__ import annotations

import argparse
import sys

from .config import settings
from .hud import emit_log, emit_provider, emit_state, emit_usage, start_ws_server
from .router import is_info_query, try_local
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

    def reset(self) -> None:
        from .providers import reset_provider

        reset_provider()
        self._p = None
        self._failed = None

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

    def answer(self, user_text: str, context: str = "") -> str:
        p = self.get()
        if p is None:
            return f"Sir, 模型後端無法啟動：{self._failed}"
        return p.answer(user_text, context)


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


def _setup_headless_logging() -> None:
    """用 pythonw（無主控台）啟動時 sys.stdout 是 None，任何 print 都會炸。
    改把輸出寫到 ~/.jarvis/jarvis.log，出問題還有地方可以看。"""
    if sys.stdout is not None and sys.stderr is not None:
        return
    from pathlib import Path

    log_dir = Path.home() / ".jarvis"
    log_dir.mkdir(exist_ok=True)
    log_file = open(log_dir / "jarvis.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    sys.stdout = sys.stderr = log_file


def main() -> int:
    _setup_headless_logging()
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
    parser.add_argument(
        "--serve", action="store_true",
        help="server mode：手機當遙控器（HTTP :8080 + WebSocket），文字模式、不開桌寵"
    )
    parser.add_argument(
        "--voice", action="store_true",
        help="搭配 --serve：這台機器的麥克風也能用（Hey Jarvis 喚醒），回覆用喇叭唸"
    )
    args = parser.parse_args()

    if args.text or args.once or args.serve:
        object.__setattr__(settings, "text_mode", True)
    if args.provider:
        object.__setattr__(settings, "provider", args.provider)

    provider = _LazyProvider()
    if args.serve:
        # 手機遙控：HTTP + WS 都綁到 server_host，輸入來自 server.text_queue
        from . import server, speech

        object.__setattr__(settings, "ws_host", settings.server_host)
        start_ws_server()
        server.start(settings.server_host, settings.server_port, settings.agent_token)
        server.on_settings_changed = provider.reset
        speech.use_text_queue(server.text_queue)
        # 語音：--voice 或 JARVIS_WAKE_WORD=1 → 麥克風執行緒 + 喇叭輸出
        import os as _os

        want_voice = args.voice or settings.wake_word
        if want_voice:
            from . import voice

            if args.voice:
                object.__setattr__(settings, "wake_word", True)
            if voice.start(server.text_queue):
                speech.voice_out = _os.environ.get("JARVIS_SERVE_TTS", "1") != "0"
        elif _os.environ.get("JARVIS_SERVE_TTS") == "1":
            speech.voice_out = True
        _banner(provider)
        print("  server mode：手機 Safari 開 http://<這台的IP>:%d，⚙︎ 填 .env 的 JARVIS_AGENT_TOKEN" % settings.server_port)
        _conversation_loop(provider)
        return 0
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
        if is_info_query(user_input):
            # 問資訊（附近美食 / 解釋 / 推薦）：純回答，不碰裝置；有搜尋就先搜
            emit_log("SYS", "純問答（不操作裝置）")
            from . import server

            reply = provider.answer(user_input, server.context())
        else:
            reply = provider.run_turn(user_input)
    except Exception as e:
        emit_log("SYS", f"模型呼叫失敗：{e}")
        reply = f"Sir, 這個指令執行時發生問題：{e}"
    speak(reply)
    emit_usage()


if __name__ == "__main__":
    sys.exit(main())
