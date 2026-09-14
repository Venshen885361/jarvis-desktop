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
# 句首的單字「開」也算（「開 YouTube」「開記事本」），但不放進 _OPEN_TRIGGERS 以免「開心」「開會」誤觸
_BARE_OPEN = re.compile(r"^(?:請)?(?:幫我)?開(?!心|會|始|玩|發|學|車|門|關|燈|口|放|頭|花|水|機)\s*(?=\S)")

# 常見「其實是網站」的東西：電腦上沒裝 App 時直接開網頁，不要回「找不到程式」
_WEB_APPS = {
    "youtube": "https://www.youtube.com", "yt": "https://www.youtube.com",
    "google": "https://www.google.com", "gmail": "https://mail.google.com",
    "netflix": "https://www.netflix.com", "chatgpt": "https://chatgpt.com",
    "instagram": "https://www.instagram.com", "ig": "https://www.instagram.com",
    "facebook": "https://www.facebook.com", "fb": "https://www.facebook.com",
    "twitter": "https://x.com", "x": "https://x.com", "threads": "https://www.threads.net",
    "github": "https://github.com", "reddit": "https://www.reddit.com",
    "twitch": "https://www.twitch.tv", "spotify": "https://open.spotify.com",
    "notion": "https://www.notion.so", "討論區": "https://www.ptt.cc", "ptt": "https://www.ptt.cc",
    "地圖": "https://maps.google.com", "google map": "https://maps.google.com", "maps": "https://maps.google.com",
    "翻譯": "https://translate.google.com", "行事曆": "https://calendar.google.com",
    "雲端硬碟": "https://drive.google.com", "drive": "https://drive.google.com",
    "瀏覽器": "https://www.google.com",
}
# 網域只認 ASCII：\w 在 Python 會吃中文，「開啟github.com」整段就被當成網址
_URL_RE = re.compile(r"((?:https?://)?[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+(?:/\S*)?)")

_GREETINGS = {
    "你好": "Sir, 我在。",
    "哈囉": "Sir, 我在。",
    "嗨": "Sir, 隨時待命。",
    "謝謝": "Sir, 這是我的榮幸。",
    "感謝": "Sir, 不客氣。",
    "在嗎": "Sir, 隨時待命。",
    "測試": "Sir, 系統運作正常。",
    "安安": "Sir, 我在。",
    "早安": "Sir, 早安。",
    "午安": "Sir, 午安。",
    "晚安": "Sir, 晚安。",
    "hi": "Sir, 隨時待命。",
    "hello": "Sir, 隨時待命。",
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


# 「問資訊」而不是「做事」：附近美食、top 10、解釋、翻譯、建議… 這類直接由模型回答（可搜尋），
# 顯示在手機 / 唸出來，不會去操作電腦。動作動詞在句首的一律不算。
_ACTION_START = re.compile(r"^(?:幫我|請|用|在)?\s*(?:打開|開啟|開|關掉|關閉|關|播放|播|放|下載|安裝|裝|切換|搜尋|搜|查一下|google|截圖|鎖定|調|設|切到|跳到|回到|執行|啟動|傳|寄|輸入|打字|點)", re.I)
_INFO_RE = re.compile(
    r"(附近|這附近|周邊|哪裡有|哪裡可以|推薦|top\s*\d+|前\s*\d+\s*名|排行|排名|有什麼好(吃|玩|逛)|好吃的|好玩的|"
    r"什麼是|是什麼|為什麼|為何|怎麼|如何|怎樣|差別|比較(?!大聲|小聲)|解釋|介紹|說明一下|"
    r"翻譯|意思|建議|該不該|值得|評價|好不好|多少錢|幾點開|營業時間|天氣預報|幫我想|幫我寫|給我.*(清單|名單|列表)|"
    r"\?$|？$|嗎$|吧$|呢$)",
    re.I,
)


_SEARCH_VERB = re.compile(r"^(?:幫我|請|麻煩)?\s*(?:搜尋|搜|查詢|查一下|查|找一下|找找|找|尋找|google)\s*")


def is_info_query(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    # 「搜尋台北 top 10 美食」「幫我查附近有什麼好吃的」：動詞是搜尋，內容卻是要推薦 / 排行 → 直接回答比開 Google 好
    if (m := _SEARCH_VERB.match(t)) and _INFO_RE.search(t[m.end():]):
        return True
    if _ACTION_START.match(t):
        return False
    return bool(_INFO_RE.search(t))


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
    rf"^(?:請|麻煩)?(?:幫我|替我|幫忙)?(?:把|將)?"
    rf"(?:(打開|開啟|啟動|開|關掉|關閉|關上|關|熄掉|熄滅|設定|設|調)\s*(?:個|一下)?\s*([^\d]*?{_HOME_WORDS})\s*(?:到|成|在|為)?\s*(\d+)?\s*(?:度|%|趴)?"
    rf"|([^\d]*?{_HOME_WORDS})\s*(?:幫我)?\s*(?:的)?(?:溫度|風量|亮度)?\s*(?:改)?(打開|開啟|開起來|開|關掉|關閉|關上|關起來|關|熄掉|熄滅|設定|設為|設成|設|調到|調成|調|改為|改成)\s*(?:到|成|在|為)?\s*(\d+)?\s*(?:度|%|趴)?)"
    rf"\s*$"
)
_HOME_STRIP = re.compile(r"^(?:所有的?|全部的?|把|的)+|的$")


# 下載 / 安裝：「下載 X」「安裝 X」「幫我裝 X」「(用|在) Steam (安裝|下載|開|玩) X」「X 這款遊戲」
_INSTALL_RE = re.compile(
    r"^(?:"
    r"(?:請)?(?:幫我)?(?P<steam>(?:用|在|去|從|透過|藉由)?\s*steam\s*(?:上面|裡面|上|裡)?\s*(?:來)?)\s*(?:(?P<run>開|玩|啟動|執行)|下載並安裝|下載安裝|下載|安裝|裝)"  # 有 Steam：動詞放寬
    r"|(?:請)?(?:幫我|協助|幫忙)?(?:下載並安裝|下載安裝|下載|安裝)"                                                          # 沒 Steam：只認 下載 / 安裝
    r"|(?:請)?(?:幫我|幫忙)(?:裝|載)"                                                                                     # 「幫我裝 VLC」「幫我載 VLC」；單獨「裝」會撞「裝潢」
    r")\s*(?:一下)?\s*(?P<q>.+?)\s*(?P<game>這款遊戲|這個遊戲|的遊戲)?\s*(?:這個程式|這個)?$",
    re.I,
)

# 播放：句首「播 / 播放 / 放 / 放一下 / 幫我播」，或「(用|在) YouTube (播|放|搜尋…播)」
_PLAY_RE = re.compile(
    r"^(?:請|麻煩)?(?:幫我|幫忙)?"
    r"(?:(?P<yt>(?:用|在|去|透過|藉由|從)?\s*(?:youtube|yt|油管)\s*(?:上面|裡面|上|裡)?)\s*(?:來)?\s*(?:播放|播|放|搜尋|找|聽|看)"   # 有 YouTube 前綴：動詞放寬
    r"|(?:播放|播(?!報|客)|放一下|放(?=[^假學棄]))"                                          # 沒前綴：只認「播 / 播放 / 放」
    r")\s*(?P<q>.+?)\s*(?:來播|來聽|給我聽|並播放|然後播)?$",
    re.I,
)

_DEVICE_PREFIX = re.compile(r"^(?:用|在|請用|幫我用)(手機|電腦|桌機|筆電|本機)(?:上|裡)?[，,\s]*")

# ---- 正規化（蛻變測試找到的一整類錯：任何前綴 / 語助詞就讓 startswith 型規則失效）----
# 句首填充：「欸」「那個」「嗯」「JARVIS」「對了」——說話時的口頭禪，對意圖沒有貢獻
_FILLER_RE = re.compile(r"^(?:(?:欸|誒|嘿|喂|那個|嗯|呃|對了|哎呀|哎|唉|好啦|好的|好嗎|好了|jarvis|賈維斯)[，,、。!！\s]*)+", re.I)
# 外層客氣話：「麻煩」「可以」「能不能」——剝掉後留下「幫我 / 請」給各規則自己處理（_INSTALL_RE 靠「幫我裝」區分「裝潢」）
_OUTER_RE = re.compile(r"^(?:麻煩|拜託|可以|可不可以|能不能|能否)+[，,\s]*")
# 內層：startswith 型規則（搜尋 / 切換 / 複製）比對前再剝「幫我 / 請」
_POLITE_RE = re.compile(r"^(?:幫我|請|替我|幫忙)+\s*")
# 句尾語助詞：「一下」「好嗎」「謝謝」——不剝掉會黏進程式名（open_application("記事本好嗎")）
_TAIL_RE = re.compile(r"(?:[，,\s]*(?:一下下|一下|好嗎|好不好|可以嗎|行嗎|謝謝|謝啦|拜託|好了|喔|啦|吧|呢|哦|嘛|唷|喲|啊|呀|耶|那邊))+[。！!？?]*$")
# 動詞後面的「一下」：「搜尋一下 python」「播放一下周杰倫」——語氣，不是目標的一部分
_MID_YIXIA_RE = re.compile(r"(搜尋|搜|播放|播|放|打開|開啟|開|關掉|關|下載|安裝|裝|查詢|查|找|幫我|幫忙|麻煩|看|聽|用|鎖定|鎖|切換|切|設定|設|調)(?:一下|個)")
# 「我要看 YouTube」「我想聽晴天」「想裝 VLC」：意願句 = 指令；看 / 用 → 開，聽 → 播
_DESIRE_RE = re.compile(r"^(?:我)?(?:想要|想|要|需要)\s*(看|用|聽|開|打開|裝|播|放|下載|安裝|查|找|切換到|切到|切換|切)\s*(?=\S)")
_DESIRE_VERB = {"看": "開", "用": "開", "聽": "播", "裝": "安裝"}
# 「把記事本打開」「把 Terraria 裝起來」：受詞在前的句型，翻回動詞在前
_SOV_RE = re.compile(r"^((?:用|在|去|透過|藉由)\s*\S+\s*)?(?:把|將)\s*(.+?)\s*(打開|開啟|開起來|開一下|裝起來|裝好|安裝好|裝一下|鎖定起來|鎖定|鎖起來|鎖上|關掉|關閉|關上|關起來|熄掉|熄滅)$")
_SOV_VERB = {"打開": "打開", "開啟": "開啟", "開起來": "打開", "開一下": "打開", "裝起來": "安裝", "裝好": "安裝", "安裝好": "安裝", "裝一下": "安裝",
             "鎖定起來": "鎖定", "鎖定": "鎖定", "鎖起來": "鎖定", "鎖上": "鎖定", "關掉": "關掉", "關閉": "關掉", "關上": "關掉", "關起來": "關掉", "熄掉": "關掉", "熄滅": "關掉"}
# 否定 / 反問：「不要打開記事本」「我不想播晴天」——本機規則不該執行，交給模型用講的回
_NEGATION_RE = re.compile(r"^(?:先)?(?:不要|別|不用|不必|不想|不准|不可以|我不想|我不要|我不用|千萬不要|拜託不要)")


# 問句 / 反問：「剛剛靜音了嗎」「鎖定螢幕會怎樣」「音量調大的教學在哪」——是在問，不是在下令
_QUESTION_RE = re.compile(
    r"(了嗎|了沒|會怎樣|會怎麼樣|怎麼辦|在哪|在哪裡|是什麼意思|什麼意思|嗎)[？?]?$"
    r"|^(?:為什麼|為何|怎麼|如何|什麼是|有人知道|誰知道|請問.*(?:嗎|呢)$)"
    r"|(?:要怎麼|該怎麼|怎樣才能|才能|才要|也不知道|搞不清楚|怎麼說|會被|是不是|會不會|好像|沒反應|沒有反應|壞掉)"
    r"|(?:快速鍵|快捷鍵|的教學|教學影片|差別|好處|由來|笑話|梗圖|原因|版權|誰設計|誰會用|哪個比較|什麼原因|什麼時候|去哪裡看|哪裡找)"
)


def _normalize(text: str) -> str:
    t = _FILLER_RE.sub("", text.strip())
    t = _MID_YIXIA_RE.sub(r"\1", t)
    outer_polite = bool(_OUTER_RE.match(t))
    t = _OUTER_RE.sub("", t)
    t = re.sub(r"^一下[，,\s]*", "", t)
    t = _TAIL_RE.sub("", t).strip(" ，,。")
    t = re.sub(r"[。！!？?]+$", "", t).strip()
    # 「幫我，開 YouTube」：客氣前綴後面的逗號拿掉，不然 ^(?:幫我)?開 接不上
    t = re.sub(r"^(幫我|請|幫忙|替我)[，,、\s]+", r"\1", t)
    # 「幫我開記事本嗎」是請求不是問句：客氣前綴 + 句尾「嗎」→ 把「嗎」拿掉
    if t.endswith("嗎") and (outer_polite or _POLITE_RE.match(t)):
        t = _TAIL_RE.sub("", t[:-1]).strip(" ，,。")
    # 意願句：「我要看 YouTube」→「開 YouTube」；問句形式（怎麼 / 什麼）不算
    if (m := _DESIRE_RE.match(t)) and not re.search(r"怎麼|什麼|為何|如何|嗎", t) and not _INFO_RE.search(t[m.end():]):
        verb = _DESIRE_VERB.get(m.group(1), m.group(1))
        t = verb + t[m.end():]
    # 受詞在前：「把記事本打開」「請幫我把記事本打開」→「打開記事本」
    if (m := _SOV_RE.match(_POLITE_RE.sub("", t))):
        t = (m.group(1) or "") + _SOV_VERB[m.group(3)] + m.group(2)
    return t or text.strip()


# 「幫我看一下現在幾點」「你知道1加1等於多少嗎」——問東西時的外圍詞，剝掉後看剩下的是不是純問題
_ASK_RE = re.compile(r"(?:幫我|請|麻煩|替我|你|想問|問一下|問|看一下|看下|看看|看|查一下|查|告訴我|跟我說|跟我講|說一下|講一下|知道|可以|到底|現在是|是|請問|那|一下|嗎|呢|啊|呀|啦|喔|[，,\s])")
_TIME_RE = re.compile(r"(?:現在|目前)?(?:幾點鐘|幾點|時間|報時)(?:幾點|了|鐘)?")
_DATE_RE = re.compile(r"(?:今天|今日|現在)?(?:幾號|日期|星期幾|禮拜幾|週幾|幾月幾號|禮拜幾號|星期幾號)(?:了)?")
_NEXT_RE = re.compile(r"^(?:請)?(?:幫我)?(?:播放|播|放|跳到|切到|切換到|轉到|換到|跳|切|換|來)?\s*(下一首歌|下一首|下一曲|換一首|換首歌|換首聽|換首|跳過這首|跳過)(?:歌)?$")
_PREV_RE = re.compile(r"^(?:請)?(?:幫我)?(?:播放|播|放|跳到|切到|切換到|轉到|換到|回到|跳|切|換)?\s*(上一首歌|上一首|上一曲|前一首)(?:歌)?$")
_LOCK_RE = re.compile(r"^(?:請)?(?:幫我|執行|幫忙)?\s*(?:(?:鎖定|鎖)\s*(?:螢幕|畫面|電腦|屏)|(?:螢幕|畫面|電腦)\s*(?:鎖定|鎖起來|鎖上|鎖)|鎖屏|lock screen)$", re.I)
_SWITCH_RE = re.compile(r"^(?:請)?(?:幫我)?(?:把)?(?:畫面|視窗)?\s*(?:切換|切|轉換|轉|跳|換|改)\s*(?:到|至|去|過去|回|成|用|看)?\s*(.+?)\s*(?:畫面|視窗|那邊)?$")
_SWITCH_STOP = {"靜音", "靜音模式", "英文", "中文", "下一首", "上一首"}


def _pure_math(t: str) -> str | None:
    """整句除了算式和「算 / 等於多少」這類外圍詞之外幾乎沒別的字，才算算術；
    「1加1等於多少這個問題好難」不算。"""
    m = try_math(t)
    if m is None:
        return None
    rest = re.sub(r"[\d\.\+\-\*\/\%\(\)\s加減乘除以上去等於多少是算幫我一下計答案]", "", t)
    return m if len(rest) <= 2 else None


def _route(text: str) -> str | None:
    text = _normalize(text)
    # 媒體鍵 / 報時 / 日期 / 算術：先看「剝掉問法的外圍詞後」是不是就是那件事
    if _NEXT_RE.match(text):
        return _press("nexttrack")
    if _PREV_RE.match(text):
        return _press("prevtrack")
    bare = _ASK_RE.sub("", text)
    if _TIME_RE.fullmatch(bare):
        return f"Sir, 現在是 {_dt.datetime.now():%H 點 %M 分}。"
    if _DATE_RE.fullmatch(bare):
        now = _dt.datetime.now()
        week = "一二三四五六日"[now.weekday()]
        return f"Sir, 今天是 {now:%Y 年 %m 月 %d 日}，星期{week}。"
    if (m := _pure_math(bare)) is not None:
        return m
    if _NEGATION_RE.match(text) or _QUESTION_RE.search(text):
        return None
    for keywords, key in _MEDIA_KEYS.items():
        if text in keywords:
            return _press(key)
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

        verb1, dev1, num1, dev2, verb2, num2 = m.groups()
        device = _HOME_STRIP.sub("", (dev1 or dev2 or "").strip())
        verb = verb1 or verb2 or ""
        num = num1 or num2
        if num:
            return home_control(device, "set", num)
        if verb.startswith(("設", "調", "改")):
            return "Sir, 要設定成多少？"
        action = "on" if verb in ("開", "打開", "開啟", "啟動", "開起來") else "off"
        return home_control(device, action)

    # 0) 招呼語：整句就是招呼詞才算，避免「你好幫我打開瀏覽器」被攔截
    if len(text) <= 6:
        for k, v in _GREETINGS.items():
            if k in text.lower():
                return v

    # 1) 算術（「幫我算 (3+5)*2」）
    if (m := _pure_math(text)) is not None:
        return m

    # 2.5) 音量：「切換到靜音」「開啟靜音」「把聲音關掉」也算；要在切換 / 開程式之前
    if re.search(r"靜音|音量|聲量|聲音|大聲|小聲", text) and len(text) <= 14:
        if "靜音" in text or re.search(r"(聲音|音量|聲量)(關掉|關閉|關)|(關掉|關閉|關)(聲音|音量|聲量)", text):
            return _dev("set_volume", action="mute")
        if any(k in text for k in ("大", "調高", "上升", "加", "高一點")):
            return _dev("set_volume", action="up")
        if any(k in text for k in ("小", "調低", "下降", "減", "低一點")):
            return _dev("set_volume", action="down")
    # 2.6) 鎖定螢幕：「把螢幕鎖定起來」「螢幕鎖定」「執行鎖定螢幕」
    if _LOCK_RE.match(text):
        return _dev("lock_screen")
    # 2.7) 剪貼簿：「查一下剪貼簿裡有什麼」「目前剪貼簿內容」；問剪貼簿功能的長句不算
    if re.search(r"剪貼簿|剪貼板", text):
        core0 = _POLITE_RE.sub("", text)
        if core0.startswith("複製"):
            content = core0[2:].strip()
            if content:
                return _dev("write_clipboard", text=content)
        if re.fullmatch(r"(?:請)?(?:幫我)?(?:看一下|看看|看|查一下|查|讀|唸|念)?(?:目前|現在)?(?:的)?(?:剪貼簿|剪貼板)(?:裡|內|裡面)?(?:有什麼|是什麼|內容|東西)?", text):
            return _dev("read_clipboard")

    # 3) 網址：整句裡有網域就直接開，不必請模型幫忙認
    if (any(k in text for k in _OPEN_TRIGGERS + ("進入", "前往", "連到", "連去", "上")) or _BARE_OPEN.match(text)) and (m := _URL_RE.search(text)):
        candidate = m.group(1)
        if "." in candidate and not candidate.replace(".", "").isdigit():
            return _dev("open_url", url=candidate)

    # 3.4) 下載 / 安裝：「下載 Discord」「幫我裝 VLC」「安裝 Steam 上的 Terraria」「用 Steam 開 Terraria」「下載 https://…」
    if (m := _INSTALL_RE.match(text)):
        from .tools.downloads import download_file, install_app, install_steam_game

        target = m.group("q").strip(" ，,。")
        if re.match(r"^(https?://|www\.)", target):
            return download_file(target)
        if m.group("steam") or m.group("game") or re.search(r"遊戲|game", target, re.I):
            target = re.sub(r"(這款|這個|的)?(遊戲|game)$", "", target, flags=re.I).strip()
            return install_steam_game(target, run=bool(m.group("run")))
        return install_app(target)

    # 3.5) 播放音樂 / 影片：「播晴天」「播放 周杰倫的歌」「用 YouTube 放 lofi」「YouTube 搜尋 xxx 然後播」
    if (m := _PLAY_RE.match(text)):
        from .tools.media import youtube_play

        q = m.group("q").strip(" ，,。的")
        q = re.sub(r"(的)?(歌|音樂|影片|MV|mv)$", "", q).strip() or m.group("q")
        return youtube_play(q, music=bool(re.search(r"music|音樂|歌", text, re.I)))

    # 4) 網頁搜尋：直接組 Google 網址開啟，比讓模型開瀏覽器再視覺定位網址列
    #    少掉整整一輪截圖 + 定位（省最多的一條規則）
    core = _POLITE_RE.sub("", text)
    _weatherish = any(k in text for k in ("天氣", "氣溫", "溫度", "下雨", "雨量"))
    for trigger in ("搜尋", "google一下", "查一下網路", "上網查", "google", "尋找", "查詢", "查查", "找找", "查", "找"):
        if core.lower().startswith(trigger) and "剪貼" not in core and not (
            trigger not in ("google一下", "google") and _INFO_RE.search(core[len(trigger):])
        ) and not (trigger in ("查", "找", "尋找", "查詢", "查查", "找找") and _weatherish):
            q = core[len(trigger):].strip(" ，,。")
            if q:
                url = "https://www.google.com/search?q=" + urllib.parse.quote(q)
                _dev("open_url", url=url)
                return f"Sir, 已為您搜尋「{q}」。"

    # 4.4) Google Lens 以圖搜圖：「用 lens 查」「反向搜尋這個」「以圖搜圖」
    #      要排在 camera_search 前面，因為兩者的觸發詞高度重疊
    if any(k in text.lower() for k in ("lens", "以圖搜圖", "反向搜", "反向查", "圖片搜尋", "找出處", "找來源", "用圖片", "用照片", "這張照片", "這張圖", "用圖")):
        return _dev("lens_search", use_gesture=any(k in text for k in ("框選", "手勢")))

    # 4.5) 鏡頭視覺搜尋：「用鏡頭查這是什麼」「拍一下幫我找哪裡買」「掃描這個」
    #      這條要在「開啟應用程式」之前，不然「打開鏡頭查一下」會被當成開程式
    if any(k in text for k in ("鏡頭", "相機", "拍一下", "拍照", "掃描", "掃一下", "框選")) and any(
        k in text for k in ("搜尋", "查", "找", "什麼", "啥", "多少錢", "哪裡買", "評價", "規格", "牌子", "類似", "辨識", "看看", "認一下", "東西", "物品")
    ):
        hint = next(
            (k for k in ("多少錢", "價格", "哪裡買", "怎麼用", "什麼牌子", "類似", "評價", "規格") if k in text),
            "",
        )
        return _dev("camera_search", hint=hint, use_gesture=any(k in text for k in ("框選", "手勢")))

    # 5) 開啟資料夾 / 應用程式
    open_target = None
    if text.startswith("顯示") and ("資料夾" in text or "目錄" in text):
        open_target = text[2:]
    elif text.startswith("顯示") and text.endswith("視窗"):
        return _dev("focus_window", keyword=text[2:-2].strip())
    for trigger in _OPEN_TRIGGERS:
        if open_target is None and trigger in text:
            open_target = text.split(trigger, 1)[1].strip()
            break
    if open_target is None and (m := _BARE_OPEN.match(text)):
        open_target = text[m.end():]
    if open_target is not None:
        target = re.sub(r"^(我|一下|給我|的)", "", open_target).strip(" ，,。")
        if target:
            # 「打開 jarvis 的資料夾」「開啟下載資料夾」「打開 C:\\Users\\me\\Downloads」
            if "資料夾" in target or "目錄" in target or re.match(r"^[A-Za-z]:\\|^[~/]", target):
                folder = re.sub(r"(的)?(資料夾|目錄)$", "", target).strip(" 的")
                return _dev("open_folder", name=folder or target)
            result = _dev("open_application", app_name=target)
            # 電腦上沒裝、但它其實是網站：改開網頁（手機端自己認得 App，不會走到這）
            if "找不到" in result and get_devices().current_name == "local":
                url = _WEB_APPS.get(target.lower().strip())
                if url:
                    return _dev("open_url", url=url)
            return result

    # 6) 切換「裝置」優先於切換「視窗」：「切換到手機」「改用電腦」「控制本機」
    devs = get_devices()
    for trigger in ("切換到", "切到", "改用", "控制", "換到", "換成", "用", "改成用"):
        if core.startswith(trigger):
            target = core[len(trigger):].strip(" ，,。")
            if devs.resolve_name(target):
                return devs.switch(target)
    if any(k in text for k in ("有哪些裝置", "列出裝置", "現在控制誰", "控制哪台")):
        return devs.describe_all()

    # 6.5) 切換視窗 / 裝置（統一句型）：「切換至 Chrome」「把畫面轉到手機」「跳去 Chrome」「切過去 Chrome」
    if (m := _SWITCH_RE.match(text)):
        target = m.group(1).strip(" ，,。")
        if target and target not in _SWITCH_STOP:
            if devs.resolve_name(target):
                return devs.switch(target)
            return _dev("focus_window", keyword=target)
    for trigger in ("回到",):
        if core.startswith(trigger):
            target = core[len(trigger):].strip(" ，,。")
            if target:
                return devs.switch(target) if devs.resolve_name(target) else _dev("focus_window", keyword=target)
    if any(k in text for k in ("有哪些視窗", "開了什麼", "列出視窗")):
        return _dev("list_windows")

    # 8) 媒體鍵
    for keywords, key in _MEDIA_KEYS.items():
        if any(k in text for k in keywords) and len(text) <= 6:
            return _press(key)

    # 10) 輸入法
    if any(k in text for k in ("輸入法", "切換語言", "切成英文", "切成中文", "中英切換")):
        if "英文" in text:
            return _dev("switch_input_method", mode="english")
        if "中文" in text:
            return _dev("switch_input_method", mode="chinese")
        return _dev("switch_input_method", mode="toggle_lang")

    # 12) 天氣
    if any(k in text for k in ("天氣", "氣溫", "溫度", "下雨", "雨量")):
        return fetch_weather(text)  # 抓不到時回 None，改交給模型

    return None
