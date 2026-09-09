# JARVIS 手機遙控 App（Capacitor 殼，iOS + Android 共用）

把 `hud/mobile.html` 原封不動包進 App。多出來的只有：**原生語音辨識**（不會像 Safari 自己停）、
定位與麥克風不用 https、之後可以加 Siri / 推播。網頁本身零改動——改 `hud/mobile.html` 就是改 App。
（資料夾名字叫 `ios-app` 是歷史因素，Android 也從這裡 build。）

這是**遙控端**（你拿在手上問 JARVIS 的那個畫面）；讓 JARVIS 操作 Android 手機的**被控端** Agent 在 `android/`。

## 固定下載點（GitHub Actions 每次 build 覆蓋，不用登入）

| 平台 | 網址 | 安裝 |
|---|---|---|
| Android | `https://github.com/Venshen885361/jarvis-desktop/releases/download/android-latest/JARVIS-android.apk` | 手機瀏覽器開 → 允許未知來源 → 裝。**免費、不會過期** |
| iPhone | `https://github.com/Venshen885361/jarvis-desktop/releases/download/ios-latest/JARVIS-unsigned.ipa` | 電腦用 [Sideloadly](https://sideloadly.io/) + 自己的 Apple ID 簽章安裝（免費，7 天重簽） |

手機 JARVIS 頁的 📥 也有這兩個連結。

## iPhone 流程
1. Windows 裝 Sideloadly（需要 Apple 官網版 iTunes 的 **Apple Mobile Device Support**；Store 版 iTunes 不行）。
2. iPhone 接線 → 信任電腦 → Sideloadly 拖入 IPA → Apple ID → Start。
3. iPhone：設定 → 一般 → VPN 與裝置管理 → 信任你的 Apple ID。
4. 開 JARVIS → `http://<電腦或 Pi 的 Tailscale IP>:8080` + 密語。

免費 Apple ID 簽的 App **7 天到期**，到期再用 Sideloadly 裝一次即可（資料會保留）；付費開發者帳號（US$99/年）才有 TestFlight / 一年簽章。

## Android 流程
手機瀏覽器開上面的 APK 網址 → 下載 → 安裝（第一次要允許「未知來源」）→ 開 JARVIS → 填位址與密語。
debug 簽章每次 CI 可能不同，**覆蓋安裝被拒就先解除安裝再裝**；想固定簽章：本機產生 keystore 放進 repo Secrets
`ANDROID_DEBUG_KEYSTORE_B64`（作法寫在 `.github/workflows/android-app.yml` 開頭）。

## 本機開發
```bash
cd ios-app && npm install
npm run build          && npx cap open ios       # 要 Mac
npm run build:android  && npx cap open android   # Android Studio
```

## 檔案
| 檔案 | 作用 |
|---|---|
| `capacitor.config.json` | appId `xyz.tonicatowo.jarvis`、webDir `www`、`CapacitorHttp` 原生請求 |
| `sync-www.mjs` | 把 `hud/mobile.html` 複製成 `www/index.html` |
| `patch_plist.py` | iOS：麥克風 / 語音 / 定位權限說明、ATS（**只放 `NSAllowsArbitraryLoads`**，多加別的鍵它就失效） |
| `patch_android.py` | Android：RECORD_AUDIO / LOCATION 權限、App 名稱 |
| `.github/workflows/ios-app.yml` | macOS runner → 未簽章 IPA → Release `ios-latest` |
| `.github/workflows/android-app.yml` | Linux runner → debug APK → Release `android-latest` |

## 踩過的坑（都已修）
- iOS 17+ 預設禁止連 IP 位址；`NSAllowsArbitraryLoads` 旁邊只要多一個 `NSAllowsLocalNetworking` 就會被忽略 → `Load failed`。
- App 的頁面來源是 `capacitor://localhost`，打 `http://<IP>:8080` 是跨來源：server 要回 CORS 標頭（已加），App 端另開 `CapacitorHttp` 走原生。
- Tailscale 的 100.x 不算 iOS「區域網路」，不會出現在那個權限清單，正常。

⚠️ Android 這條 CI 尚未實跑（我這裡沒有 Android SDK）；第一次 build 紅字貼回來。
