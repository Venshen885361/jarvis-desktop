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

## 5. Android 手機也一樣

同一個網址，Chrome 開 → 選單 → 加到主畫面。Android 的 Chrome 有 `SpeechRecognition`，🎙 按鈕會出現。

## 安全

- token 是唯一的門。用 Tailscale 就只有你的裝置連得到；要開公網一定要前面加 TLS 反向代理（Caddy 一行搞定），
  不然密語是明文。
- `/api/ask` 能做的事 = JARVIS 能做的事（操作電腦、開關家電）。手機遺失請先換 `JARVIS_AGENT_TOKEN`。
- HA 的長效權杖等於 HA 管理員；只放在 Pi 的 `.env`。
