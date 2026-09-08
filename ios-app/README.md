# JARVIS iOS App（Capacitor 殼）

把 `hud/mobile.html` 原封不動包進 iOS App。多出來的只有：**原生語音辨識**（不會像 Safari 自己停）、
定位與麥克風不用 https、之後可以加 Siri App Intents / 推播。網頁本身零改動——改 `hud/mobile.html` 就是改 App。

## 你需要的
- 一個 Apple ID（免費即可；付費開發者帳號 US$99/年 才能 TestFlight / 上架）
- Windows 上裝 [Sideloadly](https://sideloadly.io/)（用 Apple ID 幫 IPA 簽章並裝到 iPhone）
- GitHub Actions（公開 repo 免費）負責在 macOS 上編譯——你不需要 Mac

## 流程
1. 把 `.github/workflows/ios-app.yml` 放進 repo（GitHub 對 workflow 檔有保護，可能要在網頁上手動建立）。
2. GitHub → Actions → **ios-app** → Run workflow。約 8–12 分鐘。
3. 完成後在該次 run 的 Artifacts 下載 `JARVIS-ios-unsigned`（裡面是 `JARVIS-unsigned.ipa`）。
4. iPhone 用線接 Windows → 開 Sideloadly → 拖入 IPA → 填 Apple ID → Start。
5. iPhone：設定 → 一般 → VPN 與裝置管理 → 信任你的 Apple ID。
6. 開 JARVIS App → 登入頁填 `http://<電腦或 Pi 的 IP>:8080` 與密語（App 沒有「這個網頁的來源」可用，位址一定要填）。

免費 Apple ID 簽的 App **7 天到期**，到期再用 Sideloadly 裝一次即可（資料會保留）。

## 本機開發（有 Mac 才行）
```bash
cd ios-app && npm install && npm run build && npx cap open ios
```

## 檔案
| 檔案 | 作用 |
|---|---|
| `capacitor.config.json` | appId `xyz.tonicatowo.jarvis`、webDir `www` |
| `sync-www.mjs` | 把 `hud/mobile.html` 複製成 `www/index.html` |
| `patch_plist.py` | CI 產生 iOS 專案後補麥克風 / 語音 / 定位權限說明與 ATS |
| `.github/workflows/ios-app.yml` | macOS runner：cap add ios → archive（不簽章）→ 未簽章 IPA artifact |

⚠️ 未實測：整條 CI 流程在這個沙箱只跑到 `cap add ios`（Linux 上能跑），`xcodebuild` 那步要靠 GitHub 的 macOS runner；
原生語音 plugin 的事件行為（`partialResults` / `listeningState`）以實機為準。
