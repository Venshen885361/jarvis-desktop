# 手機當遙控器：Pi 是大腦，iPhone / Android 是對話窗口

```
iPhone / Android                 Pi（或任何一台電腦）                        手腳
┌──────────────┐  Tailscale     ┌──────────────────────────┐   ws://     ┌──────────┐
│ Safari PWA   │──HTTP :8080──▶│ python -m jarvis --serve │───────────▶│ PC agent │
│ 打字 / 語音   │◀──WS :8765────│  本機路由 → Gemini/Claude │             └──────────┘
│              │                │  devices registry         │   REST      ┌──────────────┐
│ Siri 捷徑     │──POST────────▶│  home_control（HA）       │───────────▶│ Home Assistant│
└──────────────┘                └──────────────────────────┘             └──────────────┘
```

手機上**不用裝 App**：Safari 開網址加到主畫面就是 PWA；Siri 捷徑用 HTTP POST 問問題、把回覆唸出來。
iOS 的限制（不能被看畫面 / 被點擊）在這個架構裡完全無關 —— 手機是遙控器，不是被控端。

## 1. 大腦端

`.env`：

```ini
JARVIS_AGENT_TOKEN=一組長密語        # 手機、PC agent、Android App 全用這組
JARVIS_PROVIDER=gemini
GEMINI_API_KEY=...
JARVIS_DEVICES=pc=ws://<電腦的 Tailscale IP>:8770   # 要控制電腦才填
HA_URL=http://homeassistant.local:8123               # 要控制家電才填
HA_TOKEN=...
```

```bash
python -m jarvis --serve
# [HUD] ws://0.0.0.0:8765 已啟動
# [server] http://0.0.0.0:8080
```

Pi 上 `scripts/pi-setup.sh` 建的 systemd 服務已經是 `--serve`；`systemctl --user enable --now jarvis`。

API（自己接別的東西也行）：

| | |
|---|---|
| `POST /api/ask` `{"text":"…"}` | 回 `{"reply","steps","ms"}`，等到 JARVIS 講完才回（多步驟電腦操作最長 180 秒） |
| `GET /api/status` | provider、目前裝置、裝置清單、用量 |
| `POST /api/device` `{"name":"pc"}` | 切換控制目標 |
| `ws://host:8765` | 即時事件；第一則送 `{"type":"auth","token":"…"}` |

認證：`Authorization: Bearer <token>` 或 `?token=`。**沒設 token 不會啟動。**

## 1.5 喚醒詞「Hey Jarvis」

三個地方都可以，看你人在哪：

| 在哪裡說 | 怎麼開 | 可靠度 |
|---|---|---|
| **大腦旁邊（Pi / 電腦的麥克風）** | `python -m jarvis --serve --voice`（需 `pip install openwakeword SpeechRecognition PyAudio`）。喚醒後回覆從喇叭出來，手機畫面同步 | 高，離線喚醒詞模型（openWakeWord `hey_jarvis`） |
| **手機網頁** | 標題列 🎧 開啟，畫面保持開著；說「Hey Jarvis 現在幾點」或先「Hey Jarvis」再講 | 中：靠瀏覽器的語音辨識，Android Chrome 穩，iOS Safari 會自己停（會自動重開）⚠️ |
| **Siri** | 第 3 節的捷徑：「Hey Siri，問 JARVIS」 | 高，但多一層 Siri |

`--serve --voice` 就是攜帶版 Pi 的最終型態：Pi + USB 麥克風喇叭，隨時 Hey Jarvis；手機是備用的畫面與打字入口。

## 1.55 https：iPhone 的定位與麥克風只在 https 下開放

Safari 對 `http://` 網頁**不給** `navigator.geolocation`（定位）與部分麥克風功能——「附近有什麼好吃的」抓不到位置就是這個原因。
兩條路：

1. **裝成 iOS App**（`ios-app/`）：App 內是安全環境，不用 https。
2. **Tailscale 憑證**（真的 https，免費）：
   - Tailscale 管理頁 → DNS → 開 **MagicDNS** 與 **HTTPS Certificates**。
   - 電腦（PowerShell，Tailscale 已裝）：`tailscale cert 你的機器名.你的tailnet.ts.net` → 產生 `.crt` 與 `.key`（名稱用 `tailscale status` 看）。
   - `.env` 加 `JARVIS_TLS_CERT=<.crt 的完整路徑>`、`JARVIS_TLS_KEY=<.key 的完整路徑>`，重跑 `--serve`。
   - 手機改連 `https://你的機器名.你的tailnet.ts.net:8080`（WebSocket 自動改走 wss）。憑證 90 天到期，再跑一次 `tailscale cert`。

## 1.6 問資訊 vs 做事

「附近有什麼好吃的」「台北 top 10 美食」「什麼是 Tailscale」「明天會下雨嗎」這類是**問資訊**，
JARVIS 不會去操作電腦，而是直接回答（Gemini 用 Google 搜尋 grounding、Claude 用 web search），
答案顯示在手機並唸出。句首是動作動詞（開 / 播 / 下載 / 關 / 切換 / 搜尋…）的才會去操作裝置。

「附近」需要位置：⚙︎ → 連線 → 勾「分享位置給 JARVIS」，手機會在每次提問附上座標（5 分鐘快取），
大腦端反查成「台北市信義區」這種地名一起給模型。沒分享位置時 JARVIS 會直說不知道你在哪。

## 2. iPhone：PWA

1. iPhone 裝 [Tailscale](https://apps.apple.com/app/tailscale/id1470499037) 登入同一個帳號（出門也能用；在家同網段可以直接用區網 IP）。
2. Safari 開 `http://<Pi 的 Tailscale IP>:8080` → ⚙︎ 填密語 → 儲存並連線。
3. 分享 → **加入主畫面**。之後從主畫面開就是全螢幕 App。
4. 設定裡勾「用手機唸出回覆」，回覆會用 iOS 的語音唸。

語音輸入：Safari 支援的話會出現 🎙 按鈕；不支援就用鍵盤上的聽寫鍵，效果一樣。
⚠️ iOS Safari 的 `SpeechRecognition` 支援度依版本而異，我沒在 iOS 26 實測；聽寫鍵是保底。

快速按鈕（現在幾點 / 關掉所有的燈 / 冷氣設 26 度 / 切換到電腦…）在 `hud/mobile.html` 的 `QUICK` 陣列，自己改。

## 3. iPhone：Siri 捷徑「問 JARVIS」

捷徑 App → 新增捷徑 → 命名 **問 JARVIS**（這個名字就是 Siri 的觸發語）：

| # | 動作 | 設定 |
|---|---|---|
| 1 | 聽寫文字 | 語言：中文（台灣）；「停止聆聽」：停頓後 |
| 2 | 取得 URL 內容 | URL：`http://<Pi IP>:8080/api/ask`；方法 **POST**；標頭：`Authorization` = `Bearer 你的密語`；請求內文 **JSON**：`text` = 聽寫文字 |
| 3 | 從輸入取得字典值 | 取得「`reply`」的值，來源：URL 內容 |
| 4 | 朗讀文字 | 上一步的值；勾「等待完成」 |

之後：「Hey Siri，問 JARVIS」→ 講話 → 回覆用 Siri 的聲音唸出來。
想省一步：把第 1 步換成「接收捷徑輸入（文字）」，就能「Hey Siri，問 JARVIS 把客廳燈關掉」一句講完。⚠️ 帶參數的 Siri 觸發在不同 iOS 版本行為不一，實機試。

## 4. 家電：Home Assistant

### Pi 上用 Docker 跑 HA（跟 JARVIS 同一台）

```bash
sudo apt install -y docker.io && sudo usermod -aG docker $USER && newgrp docker
mkdir -p ~/ha
docker run -d --name homeassistant --restart unless-stopped --privileged --network host \
  -e TZ=Asia/Taipei -v ~/ha:/config ghcr.io/home-assistant/home-assistant:stable
```

瀏覽器開 `http://<Pi IP>:8123` 建帳號 → 設定 → 裝置與服務 → 加你家的東西（米家 / Tuya / Broadlink / HomeKit 裝置 HA 幾乎都有整合）。
每個裝置**取中文名**（客廳燈、冷氣、電視），JARVIS 就是用這個名字找它。

長效權杖：HA 左下角頭像 → 安全性 → 長效存取權杖 → 建立 → 貼到 `.env` 的 `HA_TOKEN`。

### JARVIS 端

- 本機路由（零 token）：「開客廳燈」「把冷氣關掉」「冷氣設 26 度」「燈調到 40」「關掉所有的燈」。
- 模型工具：`home_control(device, on|off|toggle|set, value)`、`home_status(device)`、`home_list()`，
  自然語言的組合句（「太熱了」「我要睡了把燈都關掉冷氣調 27」）交給模型自己拆。
- 找不到裝置不會亂猜，會回候選清單。

Pi 5 記憶體：HA 約 600 MB–1 GB，JARVIS 約 300 MB（含喚醒詞），4 GB 版夠用。

## 5. 「下載 App」頁

手機 JARVIS 頁右上 📥（登入畫面也有）列出電腦版與 Android App。
把檔案放到 JARVIS 資料夾的 `dist/downloads/`，就會從這台 JARVIS 直接提供下載（帶密語）：

| 檔案 | 怎麼產生 |
|---|---|
| `JARVIS-windows.zip` | `scripts/build-exe.ps1` 會自動打包 |
| `jarvis-agent.apk` | Android Studio Build APK 後把 `android/app/build/outputs/apk/debug/app-debug.apk` 複製過來改名 |

沒放檔案時顯示 GitHub Releases 連結。

## 6. Android 手機也一樣

同一個網址，Chrome 開 → 選單 → 加到主畫面。Android 的 Chrome 有 `SpeechRecognition`，🎙 按鈕會出現。

## 安全

- token 是唯一的門。用 Tailscale 就只有你的裝置連得到；要開公網一定要前面加 TLS 反向代理（Caddy 一行搞定），
  不然密語是明文。
- `/api/ask` 能做的事 = JARVIS 能做的事（操作電腦、開關家電）。手機遺失請先換 `JARVIS_AGENT_TOKEN`。
- HA 的長效權杖等於 HA 管理員；只放在 Pi 的 `.env`。
