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


def capture_with_preview(timeout: float = 30.0):
    """開鏡頭並顯示預覽，讓使用者把東西對好再按空白鍵拍。

    盲拍的問題是使用者不知道鏡頭在看哪裡，拍到的常常是半顆頭。
    這裡給一個預覽視窗：SPACE / Enter 拍照，ESC 取消，逾時自動拍。

    Returns:
        (error_message, frame)
    """
    import time

    import cv2

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return "Sir, 無法開啟攝影機，請確認鏡頭是否被其他程式占用。", None

    window = "Jarvis - Camera (SPACE: capture / ESC: cancel)"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    start = time.time()
    frame = None
    try:
        for _ in range(5):  # 等自動對焦與曝光穩定
            cap.read()
        while True:
            ret, frame = cap.read()
            if not ret:
                return "Sir, 攝影機讀取失敗。", None
            remaining = int(timeout - (time.time() - start))
            view = cv2.flip(frame, 1)  # 預覽鏡像，比較直覺；拍下來的用原始方向
            cv2.putText(
                view, f"SPACE: capture   ESC: cancel   auto in {remaining}s",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2,
            )
            cv2.imshow(window, view)
            key = cv2.waitKey(30) & 0xFF
            if key in (32, 13):  # SPACE / Enter
                return None, frame
            if key == 27:
                return "Sir, 已取消拍攝。", None
            if remaining <= 0:
                return None, frame
    finally:
        cap.release()
        try:
            cv2.destroyWindow(window)
        except Exception:
            pass


_SEARCH_MODES = {
    "shopping": "https://www.google.com/search?tbm=shop&q=",
    "images": "https://www.google.com/search?tbm=isch&q=",
    "web": "https://www.google.com/search?q=",
}


def camera_search(hint: str = "", use_gesture: bool = False, mode: str = "web") -> str:
    """用鏡頭拍下（或手勢框選）眼前的東西，辨識後直接用瀏覽器搜尋它。

    像 Google Lens 的用法：把商品、書、零件、植物對著鏡頭，賈維斯會先認出它是什麼，
    產生精準的搜尋關鍵字（品牌＋型號、書名＋作者…），再開瀏覽器搜尋。

    Args:
        hint: 使用者想查的面向，例如「多少錢」「哪裡買」「怎麼用」「這是什麼牌子」。留空就查它是什麼。
        use_gesture: True 時改用手勢框選畫面中的一部分，適合桌上有很多東西只想查其中一個。
        mode: 'web'（一般搜尋）/ 'shopping'（購物比價）/ 'images'（相似圖片）
    """
    import json
    import re
    import urllib.parse

    from ..platform_ import get_platform
    from ..providers import describe_image

    if use_gesture:
        from .gestures import select_region_with_gesture

        err, frame = select_region_with_gesture()
    else:
        err, frame = capture_with_preview()
    if err:
        return err

    # 依提示自動挑搜尋模式（呼叫端沒特別指定時）
    if mode == "web" and hint:
        if any(k in hint for k in ("多少錢", "價格", "價錢", "哪裡買", "購買", "比價")):
            mode = "shopping"
        elif any(k in hint for k in ("類似", "相似", "同款", "圖片")):
            mode = "images"

    data, media_type = _encode(frame)
    prompt = f"""辨識這張照片裡最主要的物品，回傳 JSON（只回 JSON，不要 Markdown）：
{{"name": "物品的中文名稱（含品牌/型號/書名等可辨識資訊）",
  "query": "最適合拿去 Google 搜尋的關鍵字，繁體中文為主，品牌型號保留原文",
  "confidence": "high|medium|low"}}
使用者想查的面向：{hint or "這是什麼"}。
如果畫面上有可讀的文字（包裝、標籤、書封、型號），優先用那些文字組 query。
無法辨識時 name 填 "無法辨識"、query 留空。"""

    try:
        raw = describe_image(data, media_type, prompt)
    except Exception as e:
        return f"Sir, 辨識時發生錯誤：{e}"

    m = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        info = json.loads(m.group()) if m else {}
    except json.JSONDecodeError:
        info = {}

    name = (info.get("name") or "").strip()
    query = (info.get("query") or "").strip()
    if not query or name == "無法辨識":
        return f"Sir, 我看不出這是什麼，{raw[:80]}"

    if hint and hint not in query:
        query = f"{query} {hint}"

    url = _SEARCH_MODES.get(mode, _SEARCH_MODES["web"]) + urllib.parse.quote(query)
    try:
        get_platform().open_url(url)
    except Exception as e:
        return f"Sir, 辨識為「{name}」，但開啟瀏覽器失敗：{e}"

    conf = info.get("confidence", "")
    hedge = "看起來像是" if conf == "low" else "這是"
    return f"Sir, {hedge}{name}，已為您搜尋「{query}」。"


_LITTERBOX_API = "https://litterbox.catbox.moe/resources/internals/api.php"


def _upload_temp_image(data: bytes, expires: str = "1h") -> str:
    """把圖片丟到暫存圖床拿一個公開網址（1 小時後自動刪除）。

    Google Lens 在桌面上只吃三種輸入：上傳檔案、拖曳、貼圖片網址。前兩種要自動化
    得去操作瀏覽器 GUI（脆弱又慢），所以走第三種：先拿到一個公開網址再交給 Lens。
    Litterbox API：https://litterbox.catbox.moe/tools.php（time 可為 1h/12h/24h/72h）
    """
    import requests

    r = requests.post(
        _LITTERBOX_API,
        data={"reqtype": "fileupload", "time": expires},
        files={"fileToUpload": ("jarvis.jpg", data, "image/jpeg")},
        timeout=20,
    )
    r.raise_for_status()
    url = r.text.strip()
    if not url.startswith("http"):
        raise RuntimeError(f"圖床回應異常：{url[:80]}")
    return url


def lens_search(use_gesture: bool = False) -> str:
    """用 Google Lens 對鏡頭前的東西做「以圖搜圖」反向搜尋，找相似圖片與來源網頁。

    跟 camera_search 的差別：這裡不經過模型辨識，直接把照片交給 Google Lens，
    對「沒有文字線索的東西」（不知名零件、植物、藝術品、某張圖的出處）效果更好，
    而且完全不花 API token。代價是照片會先上傳到暫存圖床（1 小時後自動刪除）
    才能給 Lens 一個網址 —— 敏感畫面請改用 camera_search。

    Args:
        use_gesture: True 時改用手勢框選畫面中的一部分。
    """
    import urllib.parse

    from ..config import settings
    from ..platform_ import get_platform

    if not settings.allow_image_upload:
        return (
            "Sir, 以圖搜圖需要把照片上傳到暫存圖床，目前設定為不允許"
            "（JARVIS_ALLOW_IMAGE_UPLOAD=0）。要開啟請改設定，或改用 camera_search。"
        )

    if use_gesture:
        from .gestures import select_region_with_gesture

        err, frame = select_region_with_gesture()
    else:
        err, frame = capture_with_preview()
    if err:
        return err

    data, _ = _encode(frame)
    try:
        public_url = _upload_temp_image(data)
    except Exception as e:
        return f"Sir, 圖片上傳失敗，無法交給 Lens：{e}"

    # ⚠️ uploadbyurl 不是 Google 公開文件化的端點，只是「貼圖片網址」功能實際打開的網址；
    # 若某天失效，退回 Google Images 的 searchbyimage 路徑。
    lens_url = "https://lens.google.com/uploadbyurl?url=" + urllib.parse.quote(public_url, safe="")
    try:
        get_platform().open_url(lens_url)
    except Exception as e:
        return f"Sir, 圖片已上傳，但開啟瀏覽器失敗：{e}"

    return "Sir, 已交給 Google Lens 以圖搜圖，結果在瀏覽器；照片一小時後自動失效。"


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
