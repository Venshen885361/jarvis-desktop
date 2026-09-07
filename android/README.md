# JARVIS Agent（Android App）

讓 JARVIS 控制 Android 手機的「手腳」App。取代 ADB 無線偵錯：使用者只要裝 APK、
填大腦位址與密語、在設定裡開一次無障礙服務。

```
JARVIS 大腦（PC / Pi）◀── WebSocket（手機主動連出）── JARVIS Agent App
   hub://phone                                        ├─ AccessibilityService：UI 樹 / 點 / 滑 / 打字 / 截圖
                                                      ├─ Foreground Service：常駐 + 自動重連 + 開機自啟
                                                      └─ 設定頁：位址、密語、裝置名稱
```

跟 ADB 相比的實質差異：

| | ADB | App |
|---|---|---|
| 看畫面 | 只能截圖（~800 token/張） | `get_ui_tree` 直接給元件文字 + 座標，多數任務不用截圖 |
| 點擊 | `input tap`，realme/OPPO 會被「權限監控」擋 | `dispatchGesture`，系統正規管道 |
| 中文輸入 | 要裝 ADBKeyboard | `ACTION_SET_TEXT` 原生支援 |
| 網路 | 只聽區網，換網路要重配對 | 手機主動連出，NAT / 熱點 / Tailscale 都通 |

## 建置（Android Studio）

1. Android Studio → **Open** → 選這個 `android/` 資料夾（不是整個 repo）。
2. 第一次會下載 Gradle 8.7 與 AGP，等 sync 完。若提示升級 AGP / Kotlin，接受即可。
3. 手機開「USB 偵錯」接上電腦 → 上方裝置選手機 → **Run ▶**。
   或 `Build → Build Bundle(s) / APK(s) → Build APK(s)`，APK 在 `app/build/outputs/apk/debug/`。

純 CLI（已裝 Android SDK 並設好 `ANDROID_HOME`）：

```bash
cd android && ./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

> ⚠️ 這份程式碼是在沒有 Android SDK 的環境寫的，**尚未實際編譯過**。
> 第一次 build 若有錯誤，把 Build 視窗的紅字貼回來即可，通常是 API 版本或 import 的小問題。

## 手機端設定

1. 開 App，填：
   - **JARVIS 位址**：`ws://<大腦 IP>:8771`（同一個 Wi-Fi 用區網 IP；跨網路用 Tailscale 的 `100.x.x.x`）
   - **密語**：跟大腦 `.env` 的 `JARVIS_AGENT_TOKEN` 一模一樣
   - **裝置名稱**：`phone`（要跟 `.env` 裡 `hub://` 後面的名字一樣）
2. 按 **儲存並連線** → 允許通知。
3. 按 **去開啟無障礙服務** → 找到「JARVIS 手腳服務」→ 開啟 → 允許。
4. 按 **關閉電池最佳化** → 允許。
5. **realme / OPPO 另外要做**：設定 → 電池 → App 電池用量 → JARVIS Agent → 不限制；
   最近任務畫面把 JARVIS Agent 鎖定。否則重開機後無障礙服務會被系統關掉。

## 大腦端設定

`.env`：

```ini
JARVIS_AGENT_TOKEN=一組長密語
JARVIS_DEVICES=phone=hub://phone
# JARVIS_HUB_PORT=8771   # 預設
```

啟動 JARVIS 後會印 `[hub] 等待手機 App 連線：ws://0.0.0.0:8771`，手機連上會印 `[hub] phone（android）已連線`。

然後：`用手機開 YouTube`、`切換到手機` → `幫我在手機上搜尋 …`。

## 協定

與 `jarvis/agent.py` 對稱、一行 JSON 一則訊息，定義在 `jarvis/devices/hub.py` 與 `AgentSocket.kt`。
工具名稱與 `jarvis/devices/adb.py` 完全相同（`computer:*` + 高階工具 + `get_ui_tree`），
大腦不需要知道手機是走 ADB 還是 App。

## 安全

- 密語錯 → hub 直接斷線。密語不要用短字串。
- 無障礙服務等於「能看到並操作整支手機」的權限。App 只會對**你自己填的那個位址**連線，
  不連任何第三方伺服器；不用時在通知列按「中斷」或在設定裡關掉無障礙服務。
- `usesCleartextTraffic=true` 是為了區網 `ws://`；走公網請用 `wss://`（反向代理加 TLS）。

## 已知限制

- 遊戲、影片、銀行 App（`FLAG_SECURE`）：UI 樹是空的、截圖是黑的，這是系統保護。
- WebView / 自繪輸入框可能拒絕 `SET_TEXT`，此時 JARVIS 會回報而不是假裝成功。
- Android 15+ 對 `dataSync` 型前景服務有時數限制；目前 `targetSdk=34` 不受影響，
  之後升 target 要改成 `connectedDevice` 或 `specialUse`。⚠️ 未在 Android 15 實測。
