# iPhone：用捷徑自動化接 JARVIS 指令

先講清楚能力邊界：**iOS 沒有讓第三方 App 讀畫面、代替你點擊的 API**。
Android 的無障礙服務在 iOS 不存在，所以「JARVIS 看著 iPhone 畫面幫你填表單」做不到。
iPhone 能做的是**預先定義好的動作**：開 App、傳訊息、打電話、導航、音量、計時、唸文字、跑任何捷徑。

```
JARVIS ──寄信（主旨 "JARVIS: url youtube://"）──▶ iCloud 信箱 ──推播──▶ iPhone
                                                  捷徑自動化「收到電子郵件」→ 立即執行「JARVIS」捷徑
                                                  捷徑：取主旨 → 去掉前綴 → 第一個字是動詞 → 分支
```

延遲：iCloud 推播 2–5 秒。**不要用 Gmail 當收件信箱**，Apple Mail 對 Gmail 是定時抓取，可能慢好幾分鐘。

## 1. JARVIS 端（.env）

```ini
JARVIS_DEVICES=iphone=ios://你的@icloud.com
JARVIS_SMTP_HOST=smtp.gmail.com        # JARVIS 寄信用的帳號，建議另開一個專用 Gmail
JARVIS_SMTP_PORT=587
JARVIS_SMTP_USER=jarvis.sender@gmail.com
JARVIS_SMTP_PASS=xxxx xxxx xxxx xxxx   # Google 帳戶 → 安全性 → 兩步驟驗證 → 應用程式密碼
JARVIS_IOS_SECRET=一組密語              # 選用但建議：主旨變成 "JARVIS-密語: …"
```

測試：`python -m jarvis --text --no-pet` → `切換到 iphone` → `用手機開 YouTube`。信箱應該收到主旨 `JARVIS-密語: url youtube://` 的信。

## 2. iPhone：建「JARVIS」捷徑

捷徑 App → 「+」→ 命名 **JARVIS**。動作依序（右邊是要設的值）：

| # | 動作（搜尋這個名字） | 設定 |
|---|---|---|
| 1 | 取得捷徑輸入 | 類型：電子郵件 |
| 2 | 取得電子郵件的詳細資訊 | 取得「主旨」，來源：捷徑輸入 |
| 3 | 取代文字 | 尋找 `JARVIS-密語: `（含冒號與空格）→ 取代成空白 |
| 4 | 分割文字 | 依「自訂」分隔：一個空格 |
| 5 | 從清單取得項目 | 第一個項目 → 之後稱它 **verb** |
| 6 | 從清單取得項目 | 範圍中的項目：2 到 99 |
| 7 | 合併文字 | 上一步的結果，以「自訂」一個空格合併 → 之後稱它 **args** |
| 8 | 如果 | verb 是 `url` → **打開 URL**：args |
| 9 | 否則如果 | verb 是 `say` → **朗讀文字**：args |
| 10 | 否則如果 | verb 是 `volume` → **設定音量**：args（0–100） |
| 11 | 否則如果 | verb 是 `timer` → **設定計時器**：args 分鐘 |
| 12 | 否則如果 | verb 是 `navigate` → **打開 URL**：`maps://?daddr=` + args |
| 13 | 否則如果 | verb 是 `call` → **尋找聯絡人**（姓名 包含 args）→ **撥打電話** |
| 14 | 否則如果 | verb 是 `message` → 先把 args 再「分割文字」一次：第 1 項是聯絡人、其餘合併是內容 → **尋找聯絡人** → **傳送訊息**（收件人：聯絡人，內容：內容，關閉「傳送前顯示」） |
| 15 | 否則如果 | verb 是 `shortcut` → 看下面 |
| 16 | 否則 | **顯示通知**：「JARVIS：不認得 」+ verb |

> iOS 26 的「如果」支援多個「否則如果」分支，一路加下去即可。
> 步驟 3 的前綴要跟 `.env` 的 `JARVIS_IOS_SECRET` 一致；沒設密語就是 `JARVIS: `。

**`shortcut` 動詞**：JARVIS 對不認得的 App 會送 `shortcut open <名稱>`，鎖定會送 `shortcut lock`。
在第 15 步裡面再用「如果 args 開頭是 open LINE → 打開 App：LINE」這種分支自己加，
或者把常用 App 的 URL scheme 加進 JARVIS 端 `jarvis/devices/ios.py` 的 `_APP_SCHEMES`，
就會直接走 `url` 分支。⚠️ 「執行捷徑」動作能不能用變數指定捷徑名稱，我沒在 iOS 26 上驗證，
所以這裡用 If 分支而不是動態呼叫。

## 3. iPhone：建自動化

捷徑 App → 自動化 → 「+」→ **電子郵件**：

- 寄件者：`jarvis.sender@gmail.com`（JARVIS 的寄信帳號）
- 主旨包含：`JARVIS-密語:`（沒設密語就 `JARVIS:`）
- 帳號：你的 iCloud
- 下一步 → **立即執行**（不要選「執行前詢問」）、關閉「執行時通知」
- 選捷徑：**JARVIS**

官方說明：[Shortcuts 的電子郵件 / 訊息觸發條件](https://support.apple.com/en-gu/guide/shortcuts/apdd711f9dff/ios)

## 4. 測試順序

1. 自己手動寄一封主旨 `JARVIS-密語: say 哈囉` 的信到 iCloud → iPhone 應該唸出「哈囉」。
   沒反應：檢查 Mail 有加這個 iCloud 帳號、推播開著、自動化的寄件者拼對。
2. JARVIS：`切換到 iphone` → `用手機開 YouTube` → `幫我用手機傳訊息給媽媽說我晚點到`。

## 安全

- 任何能寄信到你 iCloud、主旨帶對前綴的人都能觸發捷徑。**一定要設 `JARVIS_IOS_SECRET`**，
  自動化的「主旨包含」也帶密語，寄件者條件也要設。
- 寄信帳號用專用信箱與應用程式密碼，別用主帳號密碼。
- `message` 動詞會真的送出訊息，JARVIS 的 prompt 已要求它先複述內容再送；不放心就在捷徑的
  「傳送訊息」打開「傳送前顯示」。

## 已知限制

- 單向：JARVIS 只知道信寄出了，不知道捷徑有沒有成功。
- 鎖定狀態下 `say` / `volume` / `timer` 通常能跑，`url`（開 App）需要解鎖。⚠️ 依 iOS 版本可能不同。
- 每封指令信會留在收件匣。iCloud.com → 郵件 → 規則：主旨包含 `JARVIS` → 移到「JARVIS」資料夾，就不會吵。
- 想要「看畫面 + 點擊」的完整版：Pi 當藍牙滑鼠鍵盤 + AirPlay 鏡像接收器（UxPlay），
  是攜帶版的獨立硬體專案，見 [raspberry-pi.md](raspberry-pi.md) 的 roadmap。⚠️ 未實作。
