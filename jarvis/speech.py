"""語音輸入（STT）與輸出（TTS）。

兩者都做成「壞掉也不會讓程式死掉」：沒有麥克風、沒裝 pygame、TTS 失敗時
一律退回純文字模式，讓別人 clone 下來至少能先用鍵盤試玩。
"""

from __future__ import annotations

import asyncio
import os
import tempfile

from .config import settings
from .hud import emit_log, emit_state


async def _speak_async(text: str) -> None:
    from edge_tts import Communicate

    voice = settings.tts_voice_en if text.isascii() else settings.tts_voice_zh
    path = os.path.join(tempfile.gettempdir(), "jarvis_response.mp3")
    await Communicate(text, voice).save(path)

    # 真的開始播放的那一刻才切 speaking，HUD 的波形長度才會對得上實際聲音，
    # 不會把 TTS 合成的等待時間也一起律動。
    emit_state("speaking")
    try:
        import pygame

        pygame.mixer.init()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
        pygame.mixer.quit()
    finally:
        if os.path.exists(path):
            os.remove(path)


def speak(text: str) -> None:
    print(f"\n[J.A.R.V.I.S.] {text}")
    emit_log("JARVIS", text)
    if settings.text_mode:
        emit_state("standby")
        return
    try:
        asyncio.run(_speak_async(text))
    except Exception as e:
        print(f"[TTS] 播放失敗（略過）：{e}")
    emit_state("standby")


def listen() -> str | None:
    """聽一句話。純文字模式下改成讀 stdin。"""
    if settings.text_mode:
        emit_state("listening")
        try:
            text = input("\n[Sir] ").strip()
        except (EOFError, KeyboardInterrupt):
            return "再見"
        emit_state("thinking")
        if text:
            emit_log("SIR", text)
        return text or None

    import speech_recognition as sr

    r = sr.Recognizer()
    r.pause_threshold = 1.8      # 等講完的停頓長度
    r.non_speaking_duration = 0.8
    r.energy_threshold = 300
    r.dynamic_energy_threshold = True

    try:
        with sr.Microphone() as source:
            print("\n[系統] 傾聽中（講完停頓一下就會執行）…")
            emit_state("listening")
            r.adjust_for_ambient_noise(source, duration=0.5)
            audio = r.listen(source, timeout=8, phrase_time_limit=20)
    except sr.WaitTimeoutError:
        emit_state("standby")
        return None
    except Exception as e:
        print(f"[STT] 麥克風不可用：{e}；改用文字模式輸入。")
        emit_state("standby")
        return None

    try:
        emit_state("thinking")
        text = r.recognize_google(audio, language=settings.stt_language)
        print(f"[Sir] {text}")
        emit_log("SIR", text)
        return text
    except sr.UnknownValueError:
        emit_state("standby")
        return None
    except sr.RequestError:
        emit_log("SYS", "語音辨識連線異常")
        emit_state("standby")
        return None
