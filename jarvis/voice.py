"""server mode 的語音輸入：背景執行緒「Hey Jarvis → 聽一句 → 塞進同一個文字 queue」。

手機遙控（HTTP）和機器本身的麥克風共用同一個對話迴圈，所以：
- 在 Pi / 電腦旁邊直接說「Hey Jarvis，現在幾點」，回覆會從喇叭出來，手機畫面也會同步看到
- 手機打字問的，喇叭也會唸（JARVIS_SERVE_TTS=0 可關）

需要：SpeechRecognition、PyAudio、openwakeword（pip install openwakeword）。
缺套件會明確印出並停止語音執行緒，手機遙控不受影響。
"""

from __future__ import annotations

import threading

from .config import settings
from .hud import emit_log


def start(text_queue) -> bool:
    try:
        import speech_recognition  # noqa: F401
    except ImportError:
        print("[voice] 缺少 SpeechRecognition / PyAudio，語音輸入未啟動（pip install SpeechRecognition PyAudio）。")
        return False
    if settings.wake_word:
        try:
            import openwakeword  # noqa: F401
        except ImportError:
            print("[voice] 缺少 openwakeword，會變成持續聆聽而不是等喚醒詞（pip install openwakeword）。")

    def loop() -> None:
        from . import speech

        emit_log("SYS", "語音輸入已啟動：說「Hey Jarvis」再講指令。" if settings.wake_word else "語音輸入已啟動（持續聆聽）。")
        while True:
            try:
                text = speech.listen_voice()
            except Exception as e:  # 麥克風拔掉之類的，不要讓執行緒死掉
                print(f"[voice] {e}")
                import time

                time.sleep(2)
                continue
            if text:
                text_queue.put(text)

    threading.Thread(target=loop, name="jarvis-voice", daemon=True).start()
    return True
