"""喚醒詞：「Hey Jarvis」說了才開始聽指令。

攜帶版沒有這個不行 —— 沒喚醒詞等於 Pi 24 小時把周圍的聲音送去 Google 辨識。
有了它，STT 只在喚醒後那幾秒才啟動，其他時間只有本機的小模型在聽（不出網路）。

用 openWakeWord（https://github.com/dscripka/openWakeWord）：
- 內建預訓練的 "hey_jarvis" 模型，不用自己收資料訓練
- 吃 16kHz 16-bit 單聲道 PCM，每次餵 80ms 的整數倍（1280 samples 最省）
- 推論框架選 onnx：onnxruntime 在 Pi 5 / x86 都有現成 wheel；tflite-runtime 對新版
  Python 的支援不穩定

回覆完之後有一小段「免喚醒視窗」（預設 8 秒），可以直接接著講下一句，
不用每句都 Hey Jarvis —— 這是對話順不順的關鍵。
"""

from __future__ import annotations

import time

from .config import settings
from .hud import emit_log, emit_state

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280  # 80 ms

_model = None
_failed_reason: str | None = None
_followup_until = 0.0


def allow_followup(seconds: float | None = None) -> None:
    """讓接下來幾秒內不用喚醒詞。speech.speak() 講完會呼叫。"""
    global _followup_until
    _followup_until = time.time() + (seconds if seconds is not None else settings.wake_followup_seconds)


def _load_model():
    global _model, _failed_reason
    if _model is not None or _failed_reason is not None:
        return _model
    try:
        import openwakeword
        from openwakeword.model import Model

        name = settings.wake_word_model
        try:
            _model = Model(wakeword_models=[name], inference_framework="onnx")
        except Exception:
            # 第一次跑：模型檔還沒下載
            openwakeword.utils.download_models(model_names=[name])
            _model = Model(wakeword_models=[name], inference_framework="onnx")
        print(f"[wake] 喚醒詞模型已載入：{name}（門檻 {settings.wake_word_threshold}）")
    except Exception as e:
        _failed_reason = str(e)
        print(f"[wake] 喚醒詞不可用（{e}），改為持續聆聽。pip install openwakeword")
        emit_log("SYS", "喚醒詞模型不可用，改為持續聆聽。")
    return _model


def wait_for_wake(timeout: float | None = None) -> bool:
    """阻塞直到聽到喚醒詞。回傳 False 代表逾時或喚醒詞功能不可用（呼叫端直接進入聆聽）。"""
    if not settings.wake_word:
        return True
    if time.time() < _followup_until:
        return True  # 免喚醒視窗內

    model = _load_model()
    if model is None:
        return True  # 模型壞了不該讓賈維斯變聾，退回持續聆聽

    try:
        import numpy as np
        import pyaudio
    except ImportError as e:
        print(f"[wake] 缺少套件：{e}")
        return True

    pa = pyaudio.PyAudio()
    stream = None
    try:
        stream = pa.open(
            format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE,
            input=True, frames_per_buffer=FRAME_SAMPLES,
        )
        model.reset()
        emit_state("standby")
        print(f"[wake] 等待「{settings.wake_word_model.replace('_', ' ')}」…")
        start = time.time()
        while True:
            if timeout is not None and time.time() - start > timeout:
                return False
            data = stream.read(FRAME_SAMPLES, exception_on_overflow=False)
            frame = np.frombuffer(data, dtype=np.int16)
            scores = model.predict(frame)
            # 不同版本的 key 可能是 "hey_jarvis" 或 "hey_jarvis_v0.1"，取最大值最穩
            score = max(scores.values()) if scores else 0.0
            if score >= settings.wake_word_threshold:
                print(f"[wake] 喚醒（score {score:.2f}）")
                emit_log("SYS", "已喚醒。")
                return True
    except Exception as e:
        print(f"[wake] 麥克風串流錯誤：{e}")
        return True
    finally:
        if stream is not None:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        pa.terminate()
