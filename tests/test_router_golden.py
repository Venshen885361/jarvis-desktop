"""router 的黃金案例：蛻變測試找到、修掉的每一類錯都留一句在這裡，CI 擋回歸。
（用 research/mt/harness 跑，不碰裝置、不打 API。）"""
import os

import pytest

os.environ.setdefault("JARVIS_AGENT_TOKEN", "test")

from research.mt.harness import route_label  # noqa: E402

CASES = [
    # 前綴 / 填充 / 客氣話
    ("欸 開 YouTube", "open_application:YouTube"),
    ("Jarvis 幫我，開 YouTube", "open_application:YouTube"),
    ("麻煩幫我裝 VLC", "install_app:VLC"),
    ("請幫我安裝 VLC", "install_app:VLC"),
    ("請切換到手機", "device_switch:手機"),
    # 語助詞不黏進目標
    ("打開記事本好嗎", "open_application:記事本"),
    ("可以幫我打開記事本嗎？", "open_application:記事本"),
    ("幫我搜尋一下 python 教學，謝謝", "open_url:google:python 教學"),
    ("下載 Discord 好了", "install_app:Discord"),
    # 受詞在前 / 意願句
    ("把記事本打開", "open_application:記事本"),
    ("請幫我把 Chrome 開啟喔", "open_application:Chrome"),
    ("我要看 YouTube", "open_application:YouTube"),
    ("我想聽晴天", "youtube_play:晴天"),
    ("用 Steam 把 Terraria 裝起來", "install_steam_game:Terraria"),
    # 否定 / 問句不執行
    ("不要打開記事本", "model"),
    ("剛剛靜音了嗎", "info"),
    ("有人知道 github.com 要怎麼打開嗎", "info"),
    ("現在幾點才能進去考場", "model"),
    # 同義 / 平台片語
    ("開啟github.com", "open_url:github.com"),
    ("進入 github.com", "open_url:github.com"),
    ("透過 YouTube 播放 lofi", "youtube_play:lofi"),
    ("用 YouTube 聽 lofi", "youtube_play:lofi"),
    ("透過 Steam 來安裝 Terraria", "install_steam_game:Terraria"),
    # 家電
    ("冷氣溫度調到 26 度", "home_control:冷氣=set=26"),
    ("請幫我把冷氣溫度設在 26 度", "home_control:冷氣=set=26"),
    # 不該誤觸的
    ("今天很開心", "model"),
    ("裝潢要多少錢", "info"),
    ("不要1加1等於多少", "model"),
    ("開心一點", "model"),
    ("播報新聞", "model"),
    ("播放", "computer:key:playpause"),
    ("播放周杰倫的歌", "youtube_play:周杰倫"),
    ("查一下台北天氣", "weather:查台北天氣"),
    ("現在幾點", "time"),
    ("附近有什麼好吃的", "info"),
    # 第三輪：鎖定 / 切換 / 家電 / 媒體鍵 / 報時的句型，與關鍵字規則收緊
    ("把螢幕鎖定起來", "lock_screen"),
    ("執行鎖定螢幕", "lock_screen"),
    ("把畫面轉到手機", "device_switch:手機"),
    ("切換至 Chrome", "focus_window:Chrome"),
    ("顯示 Chrome 視窗", "focus_window:Chrome"),
    ("冷氣開起來", "home_control:冷氣=on"),
    ("把客廳燈熄掉", "home_control:客廳燈=off"),
    ("幫我設定冷氣 26 度一下謝謝", "home_control:冷氣=set=26"),
    ("換首歌", "computer:key:nexttrack"),
    ("播放下一首歌", "computer:key:nexttrack"),
    ("切換到靜音", "set_volume:mute"),
    ("請幫我把聲音關掉啦", "set_volume:mute"),
    ("音量調大是不是對耳朵不好", "model"),
    ("幫我看一下現在幾點", "time"),
    ("可以跟我說今天星期幾嗎謝謝", "date"),
    ("你知道1加1等於多少嗎", "math"),
    ("1加1等於多少這個問題好難", "model"),
    ("搜尋台北 top 10 美食", "info"),
    ("查一下剪貼簿裡有什麼", "read_clipboard"),
    ("幫我用這張照片搜尋一下啦", "lens_search"),
    ("拿鏡頭看看這是啥", "camera_search"),
    ("可以藏起來嗎", "hide"),
    ("早安", "greeting"),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_golden(text, expected):
    assert str(route_label(text)) == expected
