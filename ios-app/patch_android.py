"""CI 用：`npx cap add android` 產生的專案補上權限。
Capacitor 的 geolocation / speech-recognition 外掛不會自己寫 AndroidManifest，沒宣告的話
系統直接拒絕（不會跳授權框）。`server.cleartext: true` 已由 cap sync 處理 usesCleartextTraffic。"""
import pathlib
import re

manifest = pathlib.Path("android/app/src/main/AndroidManifest.xml")
xml = manifest.read_text(encoding="utf-8")

PERMS = [
    "android.permission.INTERNET",
    "android.permission.RECORD_AUDIO",             # 語音輸入（原生 SpeechRecognizer）
    "android.permission.MODIFY_AUDIO_SETTINGS",
    "android.permission.ACCESS_COARSE_LOCATION",   # 「附近有什麼好吃的」
    "android.permission.ACCESS_FINE_LOCATION",
]
add = "".join(f'    <uses-permission android:name="{p}" />\n' for p in PERMS if p not in xml)
xml = xml.replace("</manifest>", add + "</manifest>")
# WebView 的 getUserMedia（瀏覽器版 🎙）也需要這行才會出授權框
if "android.hardware.microphone" not in xml:
    xml = xml.replace("</manifest>", '    <uses-feature android:name="android.hardware.microphone" android:required="false" />\n</manifest>')
manifest.write_text(xml, encoding="utf-8")

strings = pathlib.Path("android/app/src/main/res/values/strings.xml")
s = strings.read_text(encoding="utf-8")
s = re.sub(r'<string name="app_name">.*?</string>', '<string name="app_name">JARVIS</string>', s)
s = re.sub(r'<string name="title_activity_main">.*?</string>', '<string name="title_activity_main">JARVIS</string>', s)
strings.write_text(s, encoding="utf-8")
print("AndroidManifest / strings patched")
