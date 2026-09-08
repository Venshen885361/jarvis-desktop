"""CI 用：`npx cap add ios` 產生的 Info.plist 補上權限說明與 ATS 設定。
沒有這些 iOS 會直接拒絕麥克風 / 定位，且 http:// 的區網位址會被 ATS 擋掉。"""
import plistlib, pathlib

p = pathlib.Path("ios/App/App/Info.plist")
d = plistlib.loads(p.read_bytes())
d.update({
    "NSMicrophoneUsageDescription": "對 JARVIS 說話（語音輸入）",
    "NSSpeechRecognitionUsageDescription": "把你說的話轉成文字給 JARVIS",
    "NSLocationWhenInUseUsageDescription": "回答「附近有什麼」時需要你的位置",
    # iOS 14+ 的「區域網路」隱私：連 192.168.x / Tailscale 100.x 這種非公網位址要有這行，
    # 否則第一次連線 iOS 直接擋掉且不一定跳提示（結果就是 Load failed）。
    "NSLocalNetworkUsageDescription": "連到同一個網路裡的 JARVIS 大腦（電腦 / Raspberry Pi）",
    # ATS：只放 NSAllowsArbitraryLoads。**不要**同時加 NSAllowsLocalNetworking / *InWebContent —
    # Apple 文件：iOS 10+ 只要出現其他全域例外鍵，NSAllowsArbitraryLoads 就被忽略；
    # 而 iOS 17+ 預設又禁止連 IP 位址，結果 http://100.x.x.x:8080 在原生層直接被擋（Load failed）。
    # https://developer.apple.com/documentation/bundleresources/information-property-list/nsapptransportsecurity
    "NSAppTransportSecurity": {"NSAllowsArbitraryLoads": True},
    "UIBackgroundModes": ["audio"],
    "CFBundleDisplayName": "JARVIS",
})
p.write_bytes(plistlib.dumps(d))
print("Info.plist patched")
