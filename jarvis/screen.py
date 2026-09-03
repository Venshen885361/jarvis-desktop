"""螢幕擷取與壓縮 —— token 節流的最大單點。

原版每次 locate_and_type 都送一張全解析度 PNG。以 1920x1080 來算，
Anthropic 的影像 token 估算約 (w*h)/750，一張就 ≈ 2765 tokens；
縮到長邊 1024（1024x576）後約 786 tokens，再轉 JPEG 幾乎不影響定位精度。
同一輪 agent loop 常常要看 3-5 次畫面，省下來的量相當可觀。

縮放之後座標系統也跟著變小，所以這裡一併回傳 scale，讓上層把模型給的座標
乘回真實螢幕座標再點下去。
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from .config import settings


@dataclass
class Shot:
    data: bytes
    media_type: str
    width: int          # 送給模型的影像寬（模型看到的座標系）
    height: int
    scale: float        # 真實螢幕座標 = 模型座標 / scale
    offset: tuple[int, int] = (0, 0)  # 區域截圖時的左上角偏移

    @property
    def b64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        """把模型回報的座標換算回真實螢幕像素。"""
        return (
            int(round(x / self.scale)) + self.offset[0],
            int(round(y / self.scale)) + self.offset[1],
        )

    @property
    def approx_tokens(self) -> int:
        """Anthropic 影像 token 粗估：(w * h) / 750。用來在 HUD 顯示省了多少。"""
        return int(self.width * self.height / 750)


def capture(region: tuple[int, int, int, int] | None = None) -> Shot:
    """擷取這台電腦的螢幕（或指定區域），套用縮放與格式壓縮。

    Args:
        region: (x1, y1, x2, y2) 真實螢幕座標。給定時只送這塊，省最多 token。
    """
    import pyautogui

    if region:
        x1, y1, x2, y2 = region
        img = pyautogui.screenshot(region=(x1, y1, x2 - x1, y2 - y1))
        offset = (x1, y1)
    else:
        img = pyautogui.screenshot()
        offset = (0, 0)
    return compress(img, offset)


def compress(img, offset: tuple[int, int] = (0, 0)) -> Shot:
    """把任何 PIL 影像壓成模型要吃的 Shot（縮放 + JPEG）。

    抽出來是因為手機截圖（adb screencap）走的是同一套節流，只是來源不同。
    """
    from PIL import Image

    orig_w, orig_h = img.size
    max_edge = settings.screenshot_max_edge
    scale = 1.0
    if max(orig_w, orig_h) > max_edge:
        scale = max_edge / max(orig_w, orig_h)
        img = img.resize(
            (max(1, int(orig_w * scale)), max(1, int(orig_h * scale))),
            Image.LANCZOS,
        )

    fmt = settings.screenshot_format.lower()
    buf = io.BytesIO()
    if fmt in ("jpeg", "jpg"):
        img.convert("RGB").save(
            buf, format="JPEG", quality=settings.screenshot_quality, optimize=True
        )
        media_type = "image/jpeg"
    else:
        img.save(buf, format="PNG", optimize=True)
        media_type = "image/png"

    return Shot(
        data=buf.getvalue(),
        media_type=media_type,
        width=img.size[0],
        height=img.size[1],
        scale=scale,
        offset=offset,
    )


def screen_size() -> tuple[int, int]:
    import pyautogui

    size = pyautogui.size()
    return int(size[0]), int(size[1])
