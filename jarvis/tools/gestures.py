"""手勢框選：用大拇指 + 食指捏合拉出一個選取框，再把框內畫面交給模型分析。

mediapipe 是選用相依（安裝體積不小），沒裝時這個工具會誠實回報不可用，
而不是讓整個程式 import 失敗。
"""

from __future__ import annotations

import time

from .vision import _encode

PINCH_THRESHOLD_PX = 40
TIMEOUT_SECONDS = 45
DISPLAY_SCALE = 2

_hands_solution = None


def _get_hands_solution():
    global _hands_solution
    if _hands_solution is None:
        import mediapipe as mp

        _hands_solution = mp.solutions.hands
    return _hands_solution


def open_gesture_selector(instruction: str = "") -> str:
    """打開鏡頭，讓使用者用手勢（食指與拇指捏合並拖曳）框選畫面中的一塊區域，
    再依照指令分析框選內容。

    Args:
        instruction: 想問框選區域的問題；留空則只回報座標。
    """
    try:
        import cv2

        mp_hands = _get_hands_solution()
    except ImportError:
        return "Sir, 這台機器沒有安裝 mediapipe，手勢選取功能無法使用。"

    from ..providers import describe_image

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return "Sir, 無法開啟攝影機。"

    hands = mp_hands.Hands(
        max_num_hands=1, min_detection_confidence=0.7, min_tracking_confidence=0.7
    )
    window_name = "Jarvis - Gesture Select (ESC to cancel)"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    is_pinched = False
    anchor = None
    current = None
    final_box = None
    last_frame = None
    start = time.time()

    try:
        while True:
            if time.time() - start > TIMEOUT_SECONDS:
                return "Sir, 手勢選取逾時，已自動取消。"

            ret, frame = cap.read()
            if not ret:
                break
            frame = cv2.flip(frame, 1)
            last_frame = frame.copy()
            h, w = frame.shape[:2]

            results = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            if results.multi_hand_landmarks:
                lm = results.multi_hand_landmarks[0]
                thumb = lm.landmark[4]
                index = lm.landmark[8]
                tp = (int(thumb.x * w), int(thumb.y * h))
                ip = (int(index.x * w), int(index.y * h))
                mid = ((tp[0] + ip[0]) // 2, (tp[1] + ip[1]) // 2)
                dist = ((tp[0] - ip[0]) ** 2 + (tp[1] - ip[1]) ** 2) ** 0.5
                pinched = dist < PINCH_THRESHOLD_PX

                color = (0, 0, 255) if pinched else (0, 255, 0)
                cv2.circle(frame, tp, 8, color, -1)
                cv2.circle(frame, ip, 8, color, -1)
                cv2.line(frame, tp, ip, color, 2)

                if pinched and not is_pinched:
                    anchor = mid
                if pinched:
                    current = mid
                # 只有「確實偵測到手且距離變大」才算放開，避免掉幀被誤判
                if not pinched and is_pinched and anchor is not None:
                    final_box = (
                        min(anchor[0], mid[0]), min(anchor[1], mid[1]),
                        max(anchor[0], mid[0]), max(anchor[1], mid[1]),
                    )
                is_pinched = pinched

            if anchor and current:
                cv2.rectangle(frame, anchor, current, (0, 200, 255), 2)

            cv2.putText(
                frame,
                "drag to select, release to confirm" if is_pinched else "pinch to start",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2,
            )
            cv2.resizeWindow(window_name, w * DISPLAY_SCALE, h * DISPLAY_SCALE)
            cv2.imshow(window_name, frame)

            if final_box is not None:
                break
            if (cv2.waitKey(1) & 0xFF) == 27:
                return "Sir, 手勢選取已取消。"
    finally:
        cap.release()
        cv2.destroyWindow(window_name)
        hands.close()

    if final_box is None or last_frame is None:
        return "Sir, 沒有偵測到完整的選取動作，請再試一次。"

    x1, y1, x2, y2 = final_box
    x1, x2 = max(0, x1), min(last_frame.shape[1], x2)
    y1, y2 = max(0, y1), min(last_frame.shape[0], y2)
    if (x2 - x1) < 10 or (y2 - y1) < 10:
        return "Sir, 選取範圍太小，請重試並把動作放大一點。"

    if not instruction:
        return f"Sir, 已完成選取，範圍 ({x1}, {y1}) 到 ({x2}, {y2})。"

    data, media_type = _encode(last_frame[y1:y2, x1:x2])
    try:
        answer = describe_image(
            data, media_type,
            f"這是使用者手勢框選的畫面區域。依指令回答，控制在 2 句話內。\n指令：{instruction}",
        )
        return f"Sir, {answer}"
    except Exception as e:
        return f"Sir, 選取完成，但分析失敗：{e}"
