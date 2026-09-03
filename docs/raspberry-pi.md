# 攜帶式 JARVIS：Raspberry Pi 大腦 + 電腦 / 手機手腳

```
┌──────────── Raspberry Pi 5（隨身）────────────┐
│  麥克風 → STT → 本機路由 → LLM API → TTS → 喇叭  │
│                    ↓ 工具呼叫                   │
│           DeviceRegistry：現在對誰做？           │
└───────┬──────────────────────────┬─────────────┘
        │ WebSocket（Tailscale）     │ ADB（無線偵錯）
  ┌─────▼──────┐             ┌──────▼──────┐
  │ PC agent   │             │ Android     │
  │ python -m  │             │ 不用裝任何  │
  │ jarvis.agent│            │ 東西        │
  └────────────┘             └─────────────┘
```

Pi **不跑模型**。它做的是：收音、辨識、決定要不要打 API、把工具呼叫轉發給對的裝置、把結果唸出來。
現在 `tools/` 裡的每個函式，在這個架構裡都變成「某台裝置上的遠端函式」。

三段式，**每段獨立可驗證，做完一段再做下一段**。

---

## 第一段：在同一台電腦上驗證「大腦 ↔ 手腳」分家（不需要 Pi）

開兩個終端機：

```bash
# 終端機 A：手腳 daemon
python -m jarvis.agent --host 127.0.0.1 --port 8770 --token 隨便一串密語

# 終端機 B：大腦，指向 A
JARVIS_DEVICES="pc=ws://127.0.0.1:8770?token=隨便一串密語" python -m jarvis --text
```

（Windows cmd 用 `set JARVIS_DEVICES=...` 再跑，或直接寫進 `.env`。）

對大腦說：

```
切換到電腦
有哪些裝置
打開記事本
```

`打開記事本` 這句會經過：大腦路由 → WebSocket → agent → 本機 `open_application`。
看到終端機 A 印出 `[agent] open_application(app_name=記事本)` 就是通了。

**這段通了，架構就對了。** 之後只是把「大腦」搬到 Pi、把 `127.0.0.1` 換成 Tailscale IP。

---

## 第二段：Pi 當大腦，Tailscale 串起來

### Pi 端

```bash
# Raspberry Pi OS (64-bit, Bookworm)
sudo apt update && sudo apt install -y python3-venv python3-pip portaudio19-dev libopenblas-dev
curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up

git clone https://github.com/Venshen885361/jarvis-desktop && cd jarvis-desktop
python3 -m venv .venv && source .venv/bin/activate
pip install python-dotenv requests websockets pillow anthropic google-genai \
            SpeechRecognition edge-tts pygame PyAudio
```

Pi 上**不需要** pyautogui / pygetwindow / opencv —— 那些是手腳的事。

`.env`：

```
JARVIS_PROVIDER=gemini
GEMINI_API_KEY=...
JARVIS_DEVICES=pc=ws://<電腦的 Tailscale IP>:8770?token=密語,phone=adb://<手機 IP>:5555
JARVIS_DEFAULT_DEVICE=pc
```

Pi 沒有螢幕就用 `--no-pet`：

```bash
python -m jarvis --no-pet
```

### 電腦端

```bash
tailscale up          # 同一個 Tailscale 帳號
python -m jarvis.agent --token 密語     # 預設綁 0.0.0.0，靠 Tailscale 隔離
```

想開機自動跑（Windows）：工作排程器 → 登入時 → `pythonw -m jarvis.agent --token 密語`。
Linux 用 systemd user service（下面有範本）。

### 為什麼是 Tailscale

| 沒有 Tailscale | 有 Tailscale |
|---|---|
| 要開 port forwarding、設 DDNS | 不用碰路由器 |
| agent 暴露在公網，只靠 token 擋 | 只有你的裝置連得到，token 是第二層 |
| 換了網路 IP 就變 | 三台裝置永遠是同一個 100.x.y.z |
| 手機熱點下連不回家 | 熱點也是同一張網 |

---

## 第三段：Android 手機（ADB 無線偵錯）

手機上**不用裝 agent**。Android 11+ 內建無線 ADB。

### 一次性配對

1. 手機：設定 → 開發人員選項 → **無線偵錯** → 開啟 → 「使用配對碼配對裝置」
2. Pi：
   ```bash
   sudo apt install -y adb
   adb pair <手機顯示的 IP:配對埠>      # 輸入 6 位配對碼
   adb connect <手機 IP>:<無線偵錯的埠>   # 注意：跟配對埠不同
   adb devices                         # 應該看到 device
   ```
3. `.env` 的 `JARVIS_DEVICES` 加上 `phone=adb://<手機 IP>:<埠>`

> ⚠️ 無線偵錯的埠每次重開會變。穩定做法：USB 接一次 `adb tcpip 5555`，之後固定用 5555。
> 手機重開機後要再接一次 USB。

### 中文輸入

`adb shell input text` 只吃 ASCII。要打中文得裝 [ADBKeyboard](https://github.com/senzhk/ADBKeyBoard)
並在設定裡啟用；JARVIS 偵測到需要時會自動切過去，沒裝會明確報錯。

### 能做什麼

| 你說 | 發生的事 |
|---|---|
| 「用手機開 YouTube」 | 切到 phone → `monkey -p com.google.android.youtube` |
| 「在手機上搜尋 …」 | `am start -a VIEW -d https://google.com/search?q=…` |
| 「手機音量調小」 | `input keyevent KEYCODE_VOLUME_DOWN` |
| 「幫我在手機上把這個表單填一填」 | Claude：`screencap` → 看圖 → `input tap` / `input text` → 再截圖確認 |
| 「切換到電腦」 | 回到 PC agent |

Android 沒有游標、右鍵、滾輪：`right_click` 對應長按、`scroll` 對應滑動、`mouse_move` 略過。
Claude 的 system prompt 已經知道這件事。

---

## 離線語音辨識（攜帶時沒網路的保險）

```bash
pip install vosk opencc-python-reimplemented
mkdir -p models && cd models
wget https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip && unzip vosk-model-small-cn-0.22.zip
```

`.env`：`JARVIS_STT=vosk`。

> ⚠️ 兩件事要知道：
> 1. Vosk 中文模型輸出**簡體**，所以要裝 opencc 轉繁體，否則本機路由的關鍵字（「打開」「開啟」）對不到簡體字。
> 2. 準確度比 Google 差一截。Vosk 載入失敗會自動退回 Google；有網路時建議留 `google`。
>
> 模型檔名與版本請以 https://alphacephei.com/vosk/models 為準，這裡的 0.22 是撰寫時的版本。

---

## 硬體（攜帶化才需要）

| 元件 | 建議 | 為什麼 |
|---|---|---|
| 主板 | Pi 5（4GB 夠） | Zero 2 W 跑得動但 STT 會卡、USB 口不夠 |
| 麥克風 + 喇叭 | ReSpeaker 2-Mic HAT，或任何 USB 會議麥 | 一片解決收放音 |
| 電源 | PiSugar 3 Plus / 行動電源 | PiSugar 有電量回報 |
| 網路 | 手機開熱點 | Tailscale 在熱點下照常運作 |
| 顯示（選配） | Waveshare 1.28" 圓形 LCD（240×240） | 剛好放 `pet.py` 那顆 C60 |

### 還沒做的：喚醒詞

攜帶時沒按鈕，得靠「Hey Jarvis」喚醒 —— 而且**只有喚醒後才開始 STT**，不然整天在錄音。
候選：[openWakeWord](https://github.com/dscripka/openWakeWord)（開源、Pi 5 跑得動）。這是下一步，目前版本還是持續聆聽。

---

## systemd 範本（Pi 上開機自動跑大腦）

`~/.config/systemd/user/jarvis.service`：

```ini
[Unit]
Description=J.A.R.V.I.S. brain
After=network-online.target sound.target

[Service]
WorkingDirectory=%h/jarvis-desktop
ExecStart=%h/jarvis-desktop/.venv/bin/python -m jarvis --no-pet
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now jarvis
loginctl enable-linger $USER      # 沒登入也跑
journalctl --user -u jarvis -f    # 看 log
```

電腦端的 agent 同理，`ExecStart` 換成 `python -m jarvis.agent`。

---

## 安全

- **agent 沒有 token 不會啟動**。它等於把整台電腦的滑鼠鍵盤交給連上的人。
- Tailscale 是第一層（只有你的裝置連得到），token 是第二層。兩層都要。
- 不要把 agent 綁在公網 IP 上。真的不用 Tailscale，至少 `--host 127.0.0.1` 加 SSH tunnel。
- 手機的 ADB 無線偵錯不用時關掉。開著等於任何同網段、拿到配對的人都能操作手機。
