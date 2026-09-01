"""鏡頭相關工具：拍一張照片交給模型描述。

影像一律先壓到長邊 1024 / JPEG q70 再送，跟螢幕截圖同一套節流策略。
"""

from __future__ import annotations

import io

from ..config import settings


def _encode(frame) -> tuple[bytes, str]:
    """OpenCV BGR frame -> 壓縮後的 JPEG bytes。"""
    import cv2
    from PIL import Image

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(rgb)
    max_edge = settings.screenshot_max_edge
    w, h = img.size
    if max(w, h) > max_edge:
        s = max_edge / max(w, h)
        img = img.resize((int(w * s), int(h * s)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=settings.screenshot_quality, optimize=True)
    return buf.getvalue(), "image/jpeg"


def analyze_camera_view(instruction: str) -> str:
    """用電腦鏡頭拍一張照片，並依照指令描述或辨識畫面中的東西。

    Args:
        instruction: 想問的問題，例如「這是什麼」「讀出這張紙上的字」
    """
    import cv2

    from ..providers import describe_image

    cap = None
    try:
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return "Sir, 無法開啟攝影機，請確認鏡頭是否被其他程式占用。"
        for _ in range(5):  # 丟掉前幾幀，等自動對焦與曝光穩定
            cap.read()
        ret, frame = cap.read()
        if not ret:
            return "Sir, 攝影機拍攝失敗，請再試一次。"

        data, media_type = _encode(frame)
        answer = describe_image(
            data,
            media_type,
            f"這是攝影機剛拍到的畫面。請依照指令回答，控制在 2 句話內。\n指令：{instruction}",
        )
        return f"Sir, {answer}"
    except Exception as e:
        return f"鏡頭分析失敗：{e}"
    finally:
        if cap is not None:
            cap.release()
