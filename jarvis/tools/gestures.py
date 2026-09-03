"""手勢框選：用大拇指 + 食指捏合拉出一個選取框。

select_region_with_gesture() 只負責「拿到框選後的影像」，不做任何分析，
所以 open_gesture_selector（描述）和 camera_search（拿去搜尋）都能共用。

mediapipe 是選用相依（安裝體積不小），沒裝時誠實回報不可用，
而不是讓整個程式 import 失敗。
"""

from __future__ import annotations

import time

from .vision import _encode

# ---- 捏合判定參數 ----
# 距離一律除以「手掌大小」（手腕 → 中指根部）再比較，手離鏡頭遠近都用同一套標準。
PINCH_ON_RATIO = 0.20    # 比例低於此 → 進入捏合（開始／持續框選）
PINCH_OFF_RATIO = 0.7   # 比例高於此 → 才算放開。中間那段是遲滯區：不改變狀態
PINCH_ON_FRAMES = 3      # 連續 N 幀低於 ON 才真的開始，避免手一晃就誤觸
RELEASE_FRAMES = 6       # 連續 N 幀高於 OFF 才算放開（約 0.2 秒），單幀抖動不會斷
SMOOTH_ALPHA = 0.45      # 座標指數平滑；越小越穩但越遲鈍
TIMEOUT_SECONDS = 45
DISPLAY_SCALE = 2

_hands_solution = None


def _get_hands_solution():
    global _hands_solution
    if _hands_solution is None:
        import mediapipe as mp

        _hands_solution = mp.solutions.hands
    return _hands_solution


def select_region_with_gesture():
    """開鏡頭讓使用者捏合拖曳框選一塊區域。

    Returns:
        (error_message, cropped_frame)：成功時 error_message 為 None。
    """
    try:
        import cv2

        mp_hands = _get_hands_solution()
    except ImportError:
        return "Sir, 這台機器沒有安裝 mediapipe，手勢選取功能無法使用。", None

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return "Sir, 無法開啟攝影機。", None

    hands = mp_hands.Hands(
        max_num_hands=1,
        min_detection_confidence=0.6,
        # 追蹤門檻調低：0.7 會讓 mediapipe 在手稍微模糊時整幀放棄，等於憑空多出一次「放開」
        min_tracking_confidence=0.5,
    )
    window_name = "Jarvis - Gesture Select (SPACE confirm / ESC cancel)"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    is_pinched = False
    on_streak = 0        # 連續判定「捏合」的幀數
    off_streak = 0       # 連續判定「張開」的幀數
    anchor = None
    current = None       # 平滑後的目前點
    final_box = None
    last_frame = None
    ratio = 1.0
    start = time.time()

    def _box(a, b):
        return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))

    try:
        while True:
            if time.time() - start > TIMEOUT_SECONDS:
                return "Sir, 手勢選取逾時，已自動取消。", None

            ret, frame = cap.read()
            if not ret:
                break
            frame = cv2.flip(frame, 1)
            last_frame = frame.copy()
            h, w = frame.shape[:2]

            results = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            if results.multi_hand_landmarks:
                lm = results.multi_hand_landmarks[0].landmark
                tp = (int(lm[4].x * w), int(lm[4].y * h))     # 拇指尖
                ip = (int(lm[8].x * w), int(lm[8].y * h))     # 食指尖
                wrist = (lm[0].x * w, lm[0].y * h)
                mcp = (lm[9].x * w, lm[9].y * h)               # 中指根部
                hand_size = max(1.0, ((wrist[0] - mcp[0]) ** 2 + (wrist[1] - mcp[1]) ** 2) ** 0.5)
                pinch_dist = ((tp[0] - ip[0]) ** 2 + (tp[1] - ip[1]) ** 2) ** 0.5
                ratio = pinch_dist / hand_size
                raw_mid = ((tp[0] + ip[0]) / 2, (tp[1] + ip[1]) / 2)

                # 三態判定：低於 ON 算捏、高於 OFF 算開、中間維持現狀（遲滯）
                if ratio < PINCH_ON_RATIO:
                    on_streak += 1
                    off_streak = 0
                elif ratio > PINCH_OFF_RATIO:
                    off_streak += 1
                    on_streak = 0
                else:
                    on_streak = 0
                    off_streak = 0

                if not is_pinched and on_streak >= PINCH_ON_FRAMES:
                    is_pinched = True
                    anchor = (int(raw_mid[0]), int(raw_mid[1]))
                    current = raw_mid

                if is_pinched:
                    if current is None:
                        current = raw_mid
                    else:
                        current = (
                            current[0] + (raw_mid[0] - current[0]) * SMOOTH_ALPHA,
                            current[1] + (raw_mid[1] - current[1]) * SMOOTH_ALPHA,
                        )
                    if off_streak >= RELEASE_FRAMES:
                        final_box = _box(anchor, (int(current[0]), int(current[1])))

                color = (0, 0, 255) if is_pinched else (0, 255, 0)
                cv2.circle(frame, tp, 8, color, -1)
                cv2.circle(frame, ip, 8, color, -1)
                cv2.line(frame, tp, ip, color, 2)
            # 沒偵測到手：什麼都不改，等下一幀（掉幀不算放開）

            if anchor and current:
                cv2.rectangle(frame, anchor, (int(current[0]), int(current[1])), (0, 200, 255), 2)

            # 上方狀態列：讓使用者看得到「離放開還有多遠」，不會覺得它莫名其妙斷掉
            if is_pinched:
                status = f"selecting... open fingers to confirm  [{off_streak}/{RELEASE_FRAMES}]"
            else:
                status = f"pinch to start  (ratio {ratio:.2f} < {PINCH_ON_RATIO})"
            cv2.putText(frame, status, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
            cv2.putText(frame, "SPACE: confirm box   R: reset   ESC: cancel", (10, h - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)
            cv2.resizeWindow(window_name, w * DISPLAY_SCALE, h * DISPLAY_SCALE)
            cv2.imshow(window_name, frame)

            if final_box is not None:
                break
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                return "Sir, 手勢選取已取消。", None
            if key in (32, 13) and anchor and current:   # 保險：手勢判定不順就直接按鍵確認
                final_box = _box(anchor, (int(current[0]), int(current[1])))
                break
            if key in (ord("r"), ord("R")):
                is_pinched, anchor, current = False, None, None
                on_streak = off_streak = 0
    finally:
        cap.release()
        cv2.destroyWindow(window_name)
        hands.close()

    if final_box is None or last_frame is None:
        return "Sir, 沒有偵測到完整的選取動作，請再試一次。", None

    x1, y1, x2, y2 = final_box
    x1, x2 = max(0, x1), min(last_frame.shape[1], x2)
    y1, y2 = max(0, y1), min(last_frame.shape[0], y2)
    if (x2 - x1) < 10 or (y2 - y1) < 10:
        return "Sir, 選取範圍太小，請重試並把動作放大一點。", None

    return None, last_frame[y1:y2, x1:x2]


def open_gesture_selector(instruction: str = "") -> str:
    """打開鏡頭，讓使用者用手勢（食指與拇指捏合並拖曳）框選畫面中的一塊區域，
    再依照指令分析框選內容。

    Args:
        instruction: 想問框選區域的問題；留空則只描述框選到的東西。
    """
    from ..providers import describe_image

    err, cropped = select_region_with_gesture()
    if err:
        return err

    data, media_type = _encode(cropped)
    prompt = instruction or "這是什麼？"
    try:
        answer = describe_image(
            data, media_type,
            f"這是使用者手勢框選的畫面區域。依指令回答，控制在 2 句話內。\n指令：{prompt}",
        )
        return f"Sir, {answer}"
    except Exception as e:
        return f"Sir, 選取完成，但分析失敗：{e}"
