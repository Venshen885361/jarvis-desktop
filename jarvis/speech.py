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

# 文字模式的輸入來源。桌邊寵物開著時會塞一個 queue 進來，輸入框取代 stdin。
_text_queue = None


def use_text_queue(q) -> None:
    global _text_queue
    _text_queue = q


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
    # 講完之後開一小段免喚醒視窗，讓 Sir 可以直接接話
    from .wakeword import allow_followup

    allow_followup()


def listen() -> str | None:
    """聽一句話。純文字模式下改成讀 stdin。"""
    if settings.text_mode:
        emit_state("listening")
        try:
            if _text_queue is not None:
                text = str(_text_queue.get()).strip()
            else:
                text = input("\n[Sir] ").strip()
        except (EOFError, KeyboardInterrupt):
            return "再見"
        emit_state("thinking")
        if text:
            emit_log("SIR", text)
        return text or None

    # 喚醒詞：沒說「Hey Jarvis」之前不開 STT（麥克風聲音不出網路）
    from .wakeword import wait_for_wake

    wait_for_wake()

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
        text = _recognize(r, audio)
        if not text:
            emit_state("standby")
            return None
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


# ---------------------------------------------------------------------------
# STT 引擎：google（線上、免費、準）/ vosk（離線、Pi 跑得動、準確度略低）
# ---------------------------------------------------------------------------
_vosk_model = None
_vosk_failed = False
_opencc = None


def _recognize(r, audio) -> str | None:
    if settings.stt_engine == "vosk":
        text = _recognize_vosk(audio)
        if text is not None:
            return text
        # vosk 載入失敗時退回 google，但只警告一次（_vosk_failed 記住了）
    return r.recognize_google(audio, language=settings.stt_language)


def _recognize_vosk(audio) -> str | None:
    """離線辨識。回傳 None 代表 vosk 不可用（沒裝 / 沒模型），呼叫端會退回 google。

    模型：https://alphacephei.com/vosk/models 的 vosk-model-small-cn-0.22（約 40MB）。
    ⚠️ 中文模型輸出是簡體且字與字之間有空白，這裡會去空白並用 OpenCC 轉成繁體 ——
    沒裝 opencc 的話本機路由的關鍵字（「打開」「開啟」…）會對不到簡體字。
    """
    global _vosk_model, _vosk_failed, _opencc
    if _vosk_failed:
        return None
    import json
    import os

    try:
        if _vosk_model is None:
            from vosk import KaldiRecognizer, Model, SetLogLevel

            SetLogLevel(-1)
            if not os.path.isdir(settings.vosk_model_path):
                raise FileNotFoundError(
                    f"找不到 Vosk 模型資料夾：{settings.vosk_model_path}（設定 JARVIS_VOSK_MODEL）"
                )
            _vosk_model = Model(settings.vosk_model_path)
            try:
                from opencc import OpenCC

                _opencc = OpenCC("s2twp")  # 簡→繁（台灣用語）
            except ImportError:
                print("[STT] 未安裝 opencc，Vosk 的簡體輸出不會轉繁體：pip install opencc-python-reimplemented")
        from vosk import KaldiRecognizer

        rec = KaldiRecognizer(_vosk_model, 16000)
        rec.AcceptWaveform(audio.get_raw_data(convert_rate=16000, convert_width=2))
        text = json.loads(rec.FinalResult()).get("text", "").replace(" ", "").strip()
        if _opencc is not None and text:
            text = _opencc.convert(text)
        return text or ""
    except Exception as e:
        _vosk_failed = True
        print(f"[STT] Vosk 不可用（{e}），改用 Google 線上辨識。")
        emit_log("SYS", "Vosk 離線辨識不可用，改用線上辨識。")
        return None
