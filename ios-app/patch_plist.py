"""CI 用：`npx cap add ios` 產生的 Info.plist 補上權限說明與 ATS 設定。
沒有這些 iOS 會直接拒絕麥克風 / 定位，且 http:// 的區網位址會被 ATS 擋掉。"""
import plistlib, pathlib

p = pathlib.Path("ios/App/App/Info.plist")
d = plistlib.loads(p.read_bytes())
d.update({
    "NSMicrophoneUsageDescription": "對 JARVIS 說話（語音輸入）",
    "NSSpeechRecognitionUsageDescription": "把你說的話轉成文字給 JARVIS",
    "NSLocationWhenInUseUsageDescription": "回答「附近有什麼」時需要你的位置",
    "NSAppTransportSecurity": {"NSAllowsArbitraryLoads": True, "NSAllowsLocalNetworking": True},
    "UIBackgroundModes": ["audio"],
    "CFBundleDisplayName": "JARVIS",
})
p.write_bytes(plistlib.dumps(d))
print("Info.plist patched")
