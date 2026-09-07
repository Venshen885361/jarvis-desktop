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

### Pi 端：一鍵安裝

```bash
# Raspberry Pi OS (64-bit, Bookworm)
curl -fsSL https://raw.githubusercontent.com/Venshen885361/jarvis-desktop/main/scripts/pi-setup.sh | bash

# 想順便裝離線辨識：
WITH_VOSK=1 bash ~/jarvis-desktop/scripts/pi-setup.sh
```

腳本會裝 apt 套件、Tailscale、adb、venv、Python 套件、喚醒詞模型，建 `.env` 與 systemd 服務。
每一步都可重跑。跑完照它印出來的四個步驟做（登入 Tailscale → 填 .env → 手動跑一次 → 開機自動跑）。

Pi 上**不需要** pyautogui / pygetwindow / opencv —— 那些是手腳的事，腳本不會裝。

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

## 第三段：手機

iPhone 走 [docs/ios.md](ios.md)（捷徑自動化，只能做預定義動作）。以下是 Android。

## 第三段（Android）：Android 手機

推薦裝 [JARVIS Agent App](../android/README.md)：`.env` 寫 `phone=hub://phone`，手機 App 填 `ws://<Pi 的 Tailscale IP>:8771` 與密語即可，
不用開發人員選項、不用同網段。以下是不裝 App 的 ADB 備案。

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
3. `.env` 的 `JARVIS_DEVICES` 加上 `phone=adb://auto`（自動用 mDNS 找配對過的手機；要固定位址也可寫 `adb://<手機 IP>:<埠>`）

> 無線偵錯的埠每次重開會變、換網路 IP 也會變；`adb://auto` 會自己重找，只要手機配對過一次。
> 想完全不靠 mDNS（例如路由器擋廣播）再用 USB `adb tcpip 5555` + `adb://IP:5555`。
>
> realme / OPPO（ColorOS）額外要開「停用權限監控」和「USB 偵錯（安全性設定）」，否則 `input tap` 會被擋。

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

### 喚醒詞（已內建）

攜帶時沒按鈕，靠「**Hey Jarvis**」喚醒。用 [openWakeWord](https://github.com/dscripka/openWakeWord)
的預訓練 `hey_jarvis` 模型，在 Pi 本機跑，**喚醒前麥克風聲音不出網路** —— 只有喚醒後那幾秒才開 STT。

```
JARVIS_WAKE_WORD=1
JARVIS_WAKE_WORD_THRESHOLD=0.5     # 太常誤喚醒調高，喊不醒調低
JARVIS_WAKE_FOLLOWUP_SECONDS=8     # 回覆後這幾秒內可直接接話，不用再喊
```

模型載入失敗會自動退回持續聆聽並在 log 提示，不會讓賈維斯變聾。
桌機上通常不需要（有寵物可以點），`.env.example` 預設是關的；`pi-setup.sh` 建的 `.env` 預設是開的。

> ⚠️ 推論框架固定用 onnxruntime（Pi 5 / x86 都有 wheel）。openwakeword 安裝時會一起拉
> tflite-runtime，那個在新版 Python 上可能裝不起來 —— 裝不起來沒關係，我們不用它。

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
