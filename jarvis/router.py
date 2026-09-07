"""本機優先意圖路由（Local-First Intent Router）。

打 API 之前先問一句：「這件事本機自己就能做完嗎？」能的話直接做，
一個 token 都不花。實測下來日常語音指令有相當高比例落在這裡 ——
開程式、調音量、切視窗、報時間、開網頁搜尋、簡單算術，
這些都不需要一顆大模型幫忙判斷。

回傳 str 代表「已處理」，回傳 None 代表「交給模型」。
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import urllib.parse

import requests

from .config import settings
from .devices import get_devices
from .usage import tracker


def _dev(tool: str, **args) -> str:
    """裝置相關的工具一律經過註冊表送到「目前目標裝置」——本機、Tailscale 另一端的電腦、
    或 ADB 連著的手機。路由本身不再直接呼叫本機函式。"""
    return str(get_devices().run_tool(tool, args))

# ---------------------------------------------------------------- 算術
_MATH_SAFE = re.compile(r"^[\d\.\+\-\*\/\%\(\)\s]+$")
_MATH_FILLER = ("等於多少", "是多少", "幫我算", "算一下", "計算", "查一下", "多少")


def try_math(text: str) -> str | None:
    candidate = text
    for w in _MATH_FILLER:
        candidate = candidate.replace(w, "")
    for zh, op in (
        ("加上", "+"), ("減去", "-"), ("乘以", "*"), ("除以", "/"),
        ("加", "+"), ("減", "-"), ("乘", "*"), ("除", "/"),
    ):
        candidate = candidate.replace(zh, op)

    m = re.search(r"[\d\.\+\-\*\/\%\(\)\s]{2,}", candidate)
    if not m:
        return None
    expr = m.group().strip()
    if not _MATH_SAFE.match(expr) or not re.search(r"[\+\-\*\/\%]", expr):
        return None
    try:
        # 已經用白名單把 expr 限制成純算式字元，且 builtins 清空
        result = eval(expr, {"__builtins__": {}}, {})  # noqa: S307
    except Exception:
        return None
    return f"Sir, {expr} 的計算結果是 {result}。"


# ---------------------------------------------------------------- 天氣
_CITY_MAP = {
    "台北": "Taipei", "臺北": "Taipei", "新北": "NewTaipei",
    "桃園": "Taoyuan", "新竹": "Hsinchu", "台中": "Taichung", "臺中": "Taichung",
    "彰化": "Changhua", "雲林": "Yunlin", "嘉義": "Chiayi",
    "台南": "Tainan", "臺南": "Tainan", "高雄": "Kaohsiung",
    "屏東": "Pingtung", "宜蘭": "Yilan", "花蓮": "Hualien", "台東": "Taitung",
}


def fetch_weather(query: str) -> str | None:
    """免金鑰的即時天氣（wttr.in）。抓不到就回 None 交給模型。"""
    city = next((v for k, v in _CITY_MAP.items() if k in query), "Taipei")
    try:
        r = requests.get(
            f"https://wttr.in/{city}?format=%C+%t+(體感+%f)+濕度%h+風速%w&lang=zh-tw",
            headers={"User-Agent": "curl/7.68.0"},
            timeout=5,
        )
        if r.status_code == 200 and r.text.strip():
            return f"Sir, 即時天氣：{r.text.strip()}。"
    except Exception as e:
        print(f"[weather] {e}")
    return None


# ---------------------------------------------------------------- 規則表
_OPEN_TRIGGERS = ("打開", "開啟", "啟動", "執行", "幫我開")
_URL_RE = re.compile(r"((?:https?://)?[\w\-]+(?:\.[\w\-]+)+(?:/\S*)?)")

_GREETINGS = {
    "你好": "Sir, 我在。",
    "哈囉": "Sir, 我在。",
    "嗨": "Sir, 隨時待命。",
    "謝謝": "Sir, 這是我的榮幸。",
    "感謝": "Sir, 不客氣。",
    "在嗎": "Sir, 隨時待命。",
    "測試": "Sir, 系統運作正常。",
}

_MEDIA_KEYS = {
    ("暫停", "播放", "繼續播"): "playpause",
    ("下一首", "下一曲", "跳過"): "nexttrack",
    ("上一首", "上一曲"): "prevtrack",
}


def _press(key: str) -> str:
    # 走 computer:key 讓手機也能收到（AdbDevice 會翻成 KEYCODE_MEDIA_*）
    _dev("computer:key", text=key)
    return "Sir, 已執行。"


def try_local(user_input: str) -> str | None:
    """本機能處理就處理掉，回傳語音文字；否則回 None。"""
    if not settings.enable_local_router:
        return None

    text = user_input.strip()
    if not text:
        return None

    try:
        result = _route(text)
    except Exception as e:
        # 本機路由自己壞掉時，如實回報而不是靜默轉給模型再花一次錢
        return f"Sir, 本機執行「{text}」時出錯：{e}"

    if result is not None:
        tracker.add_local_hit()
        from .hud import emit_usage

        emit_usage()
    return result


# 「開客廳燈」「把冷氣關掉」「客廳燈關掉」「冷氣設 26 度」「燈調到 40」
_HOME_WORDS = r"(?:燈|冷氣|空調|暖氣|電扇|風扇|插座|電視|音響|窗簾|捲門|門鎖|加濕器|除濕機|掃地機)"
_HOME_RE = re.compile(
    rf"^(?:幫我|請)?(?:把)?"
    rf"(?:(打開|開啟|啟動|開|關掉|關閉|關)\s*([^\d]*?{_HOME_WORDS})"
    rf"|([^\d]*?{_HOME_WORDS})\s*(打開|開啟|開|關掉|關閉|關|設定|設為|設成|設|調到|調成|調)\s*(\d+)?\s*(?:度|%|趴)?)"
    rf"\s*$"
)
_HOME_STRIP = re.compile(r"^(?:所有的?|全部的?|把|的)+|的$")


_DEVICE_PREFIX = re.compile(r"^(?:用|在|請用|幫我用)(手機|電腦|桌機|筆電|本機)(?:上|裡)?[，,\s]*")


def _route(text: str) -> str | None:
    # -1) 「用手機開 YouTube」「在電腦上搜尋 …」：先切裝置，再用剩下的句子繼續路由。
    #     剩下的句子本機處理不了時回 None 交給模型 —— 裝置已經切好，模型會看到標示。
    if (m := _DEVICE_PREFIX.match(text)):
        devs = get_devices()
        if devs.resolve_name(m.group(1)):
            msg = devs.switch(m.group(1))
            if not msg.startswith("Sir, 已切換"):
                return msg  # 連不上就直接回報，不要繼續做
            rest = text[m.end():].strip()
            return _route(rest) if rest else msg

    # -0.5) 桌寵顯示 / 隱藏（大腦自己的事，不經裝置）
    if any(k in text for k in ("藏起來", "隱藏桌寵", "躲起來", "隱藏", "收起來")) and len(text) <= 8:
        from .hud import ws_emit

        ws_emit({"type": "hide"})
        return "Sir, 我在背景待命。"
    if any(k in text for k in ("出來", "顯示桌寵", "現身", "出現")) and len(text) <= 8:
        from .hud import ws_emit

        ws_emit({"type": "show"})
        return "Sir, 我在。"

    # -0.2) 家電（Home Assistant 有設定才啟用）：「把客廳燈關掉」「開冷氣」「冷氣設 26 度」
    if os.environ.get("HA_URL") and (m := _HOME_RE.match(text)):
        from .tools.home import home_control

        verb1, dev1, dev2, verb2, num = m.groups()
        device = _HOME_STRIP.sub("", (dev1 or dev2 or "").strip())
        verb = verb1 or verb2 or ""
        if num:
            return home_control(device, "set", num)
        if verb.startswith(("設", "調")):
            return "Sir, 要設定成多少？"
        action = "on" if verb in ("開", "打開", "開啟", "啟動") else "off"
        return home_control(device, action)

    # 0) 招呼語：整句就是招呼詞才算，避免「你好幫我打開瀏覽器」被攔截
    if len(text) <= 4:
        for k, v in _GREETINGS.items():
            if k in text:
                return v

    # 1) 算術（優先權高於「查詢」類關鍵字，免得 1+1 被當成網頁搜尋）
    if (m := try_math(text)) is not None:
        return m

    # 2) 時間與日期
    if any(k in text for k in ("幾點", "現在時間", "報時")):
        return f"Sir, 現在是 {_dt.datetime.now():%H 點 %M 分}。"
    if any(k in text for k in ("今天幾號", "今天日期", "星期幾", "禮拜幾")):
        now = _dt.datetime.now()
        week = "一二三四五六日"[now.weekday()]
        return f"Sir, 今天是 {now:%Y 年 %m 月 %d 日}，星期{week}。"

    # 3) 網址：整句裡有網域就直接開，不必請模型幫忙認
    if any(k in text for k in _OPEN_TRIGGERS) and (m := _URL_RE.search(text)):
        candidate = m.group(1)
        if "." in candidate and not candidate.replace(".", "").isdigit():
            return _dev("open_url", url=candidate)

    # 4) 網頁搜尋：直接組 Google 網址開啟，比讓模型開瀏覽器再視覺定位網址列
    #    少掉整整一輪截圖 + 定位（省最多的一條規則）
    for trigger in ("搜尋", "google一下", "查一下網路", "上網查"):
        if text.startswith(trigger):
            q = text[len(trigger):].strip(" ，,。")
            if q:
                url = "https://www.google.com/search?q=" + urllib.parse.quote(q)
                _dev("open_url", url=url)
                return f"Sir, 已為您搜尋「{q}」。"

    # 4.4) Google Lens 以圖搜圖：「用 lens 查」「反向搜尋這個」「以圖搜圖」
    #      要排在 camera_search 前面，因為兩者的觸發詞高度重疊
    if any(k in text.lower() for k in ("lens", "以圖搜圖", "反向搜", "反向查", "圖片搜尋", "找出處", "找來源")):
        return _dev("lens_search", use_gesture=any(k in text for k in ("框選", "手勢")))

    # 4.5) 鏡頭視覺搜尋：「用鏡頭查這是什麼」「拍一下幫我找哪裡買」「掃描這個」
    #      這條要在「開啟應用程式」之前，不然「打開鏡頭查一下」會被當成開程式
    if any(k in text for k in ("鏡頭", "相機", "拍一下", "拍照", "掃描", "掃一下", "框選")) and any(
        k in text for k in ("搜尋", "查", "找", "什麼", "多少錢", "哪裡買", "評價", "規格", "牌子", "類似")
    ):
        hint = next(
            (k for k in ("多少錢", "價格", "哪裡買", "怎麼用", "什麼牌子", "類似", "評價", "規格") if k in text),
            "",
        )
        return _dev("camera_search", hint=hint, use_gesture=any(k in text for k in ("框選", "手勢")))

    # 5) 開啟資料夾 / 應用程式
    for trigger in _OPEN_TRIGGERS:
        if trigger in text:
            target = text.split(trigger, 1)[1].strip()
            target = re.sub(r"^(我|一下|給我|的)", "", target).strip(" ，,。")
            if not target:
                continue
            # 「打開 jarvis 的資料夾」「開啟下載資料夾」「打開 C:\\Users\\me\\Downloads」
            if "資料夾" in target or "目錄" in target or re.match(r"^[A-Za-z]:\\|^[~/]", target):
                folder = re.sub(r"(的)?(資料夾|目錄)$", "", target).strip(" 的")
                return _dev("open_folder", name=folder or target)
            return _dev("open_application", app_name=target)

    # 6) 切換「裝置」優先於切換「視窗」：「切換到手機」「改用電腦」「控制本機」
    devs = get_devices()
    for trigger in ("切換到", "切到", "改用", "控制", "換到", "用"):
        if text.startswith(trigger):
            target = text[len(trigger):].strip(" ，,。")
            if devs.resolve_name(target):
                return devs.switch(target)
    if any(k in text for k in ("有哪些裝置", "列出裝置", "現在控制誰", "控制哪台")):
        return devs.describe_all()

    # 6.5) 切換視窗
    for trigger in ("切換到", "切到", "跳到", "回到"):
        if text.startswith(trigger):
            target = text[len(trigger):].strip(" ，,。")
            if target:
                return _dev("focus_window", keyword=target)
    if any(k in text for k in ("有哪些視窗", "開了什麼", "列出視窗")):
        return _dev("list_windows")

    # 7) 音量
    if any(k in text for k in ("音量", "聲音", "大聲", "小聲", "靜音")):
        if "靜音" in text:
            return _dev("set_volume", action="mute")
        if any(k in text for k in ("大", "調高", "上升", "加")):
            return _dev("set_volume", action="up")
        if any(k in text for k in ("小", "調低", "下降", "減")):
            return _dev("set_volume", action="down")

    # 8) 媒體鍵
    for keywords, key in _MEDIA_KEYS.items():
        if any(k in text for k in keywords):
            return _press(key)

    # 9) 鎖定螢幕
    if any(k in text for k in ("鎖定螢幕", "鎖屏", "鎖電腦", "lock screen")):
        return _dev("lock_screen")

    # 10) 輸入法
    if any(k in text for k in ("輸入法", "切換語言", "切成英文", "切成中文", "中英切換")):
        if "英文" in text:
            return _dev("switch_input_method", mode="english")
        if "中文" in text:
            return _dev("switch_input_method", mode="chinese")
        return _dev("switch_input_method", mode="toggle_lang")

    # 11) 剪貼簿
    if any(k in text for k in ("剪貼簿", "剪貼板")):
        if text.startswith("複製"):
            content = text[2:].strip()
            if content:
                return _dev("write_clipboard", text=content)
        return _dev("read_clipboard")

    # 12) 天氣
    if any(k in text for k in ("天氣", "氣溫", "溫度", "下雨", "雨量")):
        return fetch_weather(text)  # 抓不到時回 None，改交給模型

    return None
