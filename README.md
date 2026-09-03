# J.A.R.V.I.S.

[![ci](https://github.com/Venshen885361/jarvis-desktop/actions/workflows/ci.yml/badge.svg)](https://github.com/Venshen885361/jarvis-desktop/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

<p align="center"><img src="docs/pet.gif" width="220" alt="C60 桌邊寵物：待命 → 聆聽 → 思考 → 講話"></p>

語音控制電腦的本機 AI 總管。對著麥克風講一句話，它會開程式、切視窗、看螢幕、點按鈕、打字。
附一個 WebSocket 連動的 HUD 介面。

- **兩種後端**：Anthropic 官方 computer-use toolset（真正看螢幕操作 GUI）或 Google Gemini（成本更低）
- **Windows + Linux 雙平台**（Linux 含 Hyprland / wlroots / X11）
- **本機優先路由**：日常指令（開程式、調音量、報時間、算數學、網頁搜尋）完全不打 API
- **HUD 即時顯示 token 用量與估計花費**，省了多少看得見

> ⚠️ 這個程式會用你的 API 金鑰、控制你的滑鼠鍵盤、讀你的螢幕內容。
> 跑之前請先讀 [SECURITY.md](SECURITY.md)。

---

## 快速開始

```bash
git clone https://github.com/Venshen885361/jarvis-desktop
cd jarvis-desktop

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # 填入 ANTHROPIC_API_KEY
python -m jarvis
```

Windows 使用者可以直接跑 `setup.bat`（建 venv、裝套件、跑一次驗證），之後用 `run.bat` 啟動。

### 像 App 一樣用（Windows）

不想每次開 cmd：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\make-shortcut.ps1
```

桌面會多一個 **J.A.R.V.I.S.** 圖示（那顆 C60），雙擊就跑、沒有黑色視窗；輸出寫在
`%USERPROFILE%\.jarvis\jarvis.log`。想開機自動啟動，把捷徑複製到「啟動」資料夾（腳本會印路徑）。

要打包成**不需要 Python 的 .exe** 給別人：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-exe.ps1     # → dist\JARVIS\JARVIS.exe
```

⚠️ 打包版刻意不含 mediapipe（+300MB），手勢框選會回報未安裝；其他功能都在。

沒有麥克風？用鍵盤模式先玩玩看：

```bash
python -m jarvis --text
python -m jarvis --once "打開記事本"
```

啟動後桌面右下角會出現一顆 **C60 骨架的桌邊寵物**：待命時緩慢自轉呼吸、聆聽時轉快、
思考時變紫色脈動、講話時整顆共振抖動，最後一句回覆會顯示在下方。

| 操作 | 方式 |
|---|---|
| 移動 | 左鍵拖曳 |
| 調整大小 | 滾輪、拖右下角把手、或右鍵選單「放大／縮小」（120–640 px） |
| 關閉 | 右上角 ×、按 Esc、右鍵選單「退出」、或直接說「再見」「退出」 |

大小與位置會記在 `~/.jarvis_pet.json`，下次開在同一個地方。
Windows 上是真正去背的（只剩線框浮在桌面）；Linux 退回半透明深色底。

不想要寵物的話 `--no-pet` 走純終端機；`--hud` 會另外啟動 WebSocket 讓 `hud/jarvis_hub.html` 網頁版連上。

### 沒有 Anthropic 額度？先用 Gemini 跑

Anthropic API 是**預付制，跟 Claude 訂閱（Pro / Max）是分開的** —— 有訂閱不等於有 API 額度。
看到 `Your credit balance is too low` 就是這個原因。

想先免費試玩的話改用 Gemini：[AI Studio](https://aistudio.google.com/apikey) 拿一把免費金鑰，
`.env` 改成 `JARVIS_PROVIDER=gemini` 加 `GEMINI_API_KEY=`。
免費層涵蓋本專案預設的 `gemini-3.5-flash` 與 `gemini-3.5-flash-lite`。

代價是 Gemini 沒有官方 computer-use toolset，GUI 操作靠視覺定位，多步驟任務較弱；
本機路由那些 0 token 的功能則完全不受影響。

### 踩到 `anthropic-workspace-id is required` 的話

代表你的金鑰是**多工作區金鑰**，每個請求都得指定 workspace。兩個解法擇一：

- 重新建一把 **scope 到單一 workspace** 的金鑰（最省事，不用改設定）
- 或到 [Settings → Workspaces](https://platform.claude.com/settings/workspaces) 拿 id
  （格式 `wrkspc_xxxxxxxx`），填進 `.env` 的 `ANTHROPIC_WORKSPACE_ID=`

---

## 它能做什麼

| 你說 | 實際發生的事 | 花費 |
|---|---|---|
| 「打開 Firefox」 | 掃描已安裝程式索引 → 模糊比對 → 啟動／切換到現有視窗 | **0 token** |
| 「搜尋 Svelte 5 runes」 | 直接組 Google 網址用系統瀏覽器開啟 | **0 token** |
| 「音量調小」「鎖定螢幕」「現在幾點」 | 本機系統呼叫 | **0 token** |
| 「12 乘以 88 等於多少」 | 本機算式解析 | **0 token** |
| 「嘉義天氣」 | wttr.in（免金鑰） | **0 token** |
| 「幫我把這個表單填一填」 | Claude 截圖 → 定位欄位 → 點擊輸入 → 再截圖確認 | 一輪 API |
| 「唸出畫面上這段錯誤訊息」 | 截圖 → 模型讀 | 一輪 API |
| 「這是什麼東西」（拿著東西對鏡頭） | 開鏡頭拍照 → 模型辨識 | 一次輕量呼叫 |
| 「用 Lens 反向搜尋這個」 | 拍照→傳暫存圖床（1h）→開 Google Lens 以圖搜圖 | **0 token** |
| 「用鏡頭查這個多少錢」 | 預覽→拍照→辨識出品牌型號→直接開 Google 購物搜尋（類 Google Lens） | 一次輕量呼叫 |

---

## 省 token 的四個做法

原版每講一句話都會打一次 API，需要看畫面時再送一張全解析度 PNG。這版做了四件事：

### 1. 本機優先路由（省最多）

`jarvis/router.py` 在呼叫模型之前先跑一輪規則比對。開程式、切視窗、音量、媒體鍵、
鎖定螢幕、輸入法、剪貼簿、時間日期、算術、天氣、開網址、網頁搜尋 —— 全部本機做完，
一個 token 都不花。HUD 上的 `LOCAL HIT RATE` 就是這條路徑的命中率。

其中「網頁搜尋」這條特別值錢：原本要「開瀏覽器 → 截圖 → 定位網址列 → 輸入 → Enter」
四五步，現在直接組 URL 開起來，省掉整整一輪截圖與視覺定位。

### 2. 截圖壓縮

Anthropic 的影像 token 約等於 `寬 × 高 ÷ 750`：

| 送出的截圖 | 尺寸 | 約略 token |
|---|---|---|
| 原版（1080p 全解析度 PNG） | 1920×1080 | ~2,765 |
| 本版預設（長邊 1024、JPEG q70） | 1024×576 | ~786 |
| `zoom` 局部區域 | 視區域大小 | 通常 < 300 |

同一輪任務常要看畫面三到五次，這裡的差距會直接乘上去。縮放後模型看到的座標系也變小，
`screen.Shot.to_screen()` 負責把座標換算回真實螢幕像素，點擊才不會整個偏掉。

### 3. 對話歷史壓縮

- **舊截圖從歷史移除**：一張圖留在歷史裡，之後每一輪都會被重新計費。預設只保留最近 1 張，
  更舊的換成 `[舊截圖已移除以節省 token]`。這是單項效益最高的一條。
- **工具結果截斷**：文字結果超過 600 字截掉。
- **安全邊界裁切**：訊息超量時只從「非 tool_result 的 user 訊息」切開，
  不會留下沒有配對 `tool_use` 的 `tool_result`（那會被 API 直接拒絕）。

### 4. 模型分級 + prompt caching

不需要看畫面的指令（閒聊、問答）走輕量模型，而且**完全不掛 computer toolset** ——
工具定義本身就要錢。輕量模型自己判斷需要看畫面時，會呼叫
`escalate_to_computer_control` 把這輪升級給完整模型重跑。

system prompt 與工具定義掛上 `cache_control: {"type": "ephemeral"}` 斷點。
這兩塊每輪都會重送、內容又完全固定，是最值得快取的部分；快取命中時這段只算 0.1 倍價錢。
（所以 system prompt 裡刻意不插入當下時間之類會變動的東西 —— 一變就永遠打不中快取。）

HUD 右側的 Token Budget 面板會即時顯示 input / output / cache read 與估計成本。

---

## 兩種後端怎麼選

| | `JARVIS_PROVIDER=claude` | `JARVIS_PROVIDER=gemini` |
|---|---|---|
| GUI 操作方式 | 官方 `computer_toolset_20260801`：screenshot / zoom / click / drag / scroll / type / key / wait 共 17 個動作 | 自製 `locate_and_type`：截圖問座標再點 |
| 多步驟任務 | 強，模型自己規劃並確認每一步 | 普通，複雜流程容易斷在中間 |
| 成本 | 較高（sonnet $2/$10 per MTok） | 較低 |
| 適合 | 真的要它幫你操作電腦 | 語音問答為主、偶爾開個程式 |

兩邊共用同一套工具函式（`jarvis/tools/`），`providers/schema.py` 負責把 Python function
轉成 Anthropic 的 `input_schema`（google-genai SDK 本來就吃 function 物件）。

---

## 多裝置：Pi 大腦 + 電腦 / 手機手腳

大腦（語音、路由、LLM）和手腳（截圖、點擊、開程式）可以分開跑：

```bash
# 被操作的電腦
python -m jarvis.agent --token 密語

# 大腦（Pi 或另一台電腦）
JARVIS_DEVICES="pc=ws://100.64.0.2:8770?token=密語,phone=adb://192.168.1.50:5555" python -m jarvis
```

「切換到手機」「用電腦開 Firefox」「在手機上搜尋 …」會自動切換目標。Android 走 ADB 無線偵錯，
手機上不用裝任何東西。完整步驟（Tailscale、systemd、ADB 配對、離線 STT）見
[docs/raspberry-pi.md](docs/raspberry-pi.md)。

## 平台支援

| 功能 | Windows | Linux |
|---|---|---|
| 已安裝程式索引 | 開始功能表 `.lnk` + 登錄檔 App Paths | freedesktop `.desktop`（含 flatpak） |
| 啟動程式 | `os.startfile` | `gio launch` → `gtk-launch` → 直接跑 Exec |
| 視窗偵測／切換 | `pygetwindow` | Hyprland `hyprctl -j` / 其他 `wmctrl` |
| 輸入法切換 | IMM32 API | `fcitx5-remote` → `ibus` |
| 音量 | 媒體鍵 | `wpctl` → `pactl` |
| 鎖定螢幕 | `LockWorkStation` | `loginctl` / `hyprlock` / `swaylock` |

Linux 額外建議安裝：`wmctrl`（非 Hyprland 環境）、`wl-clipboard` 或 `xclip`（pyperclip 需要）。

> Wayland 下 `pyautogui` 的滑鼠鍵盤模擬支援不完整。Hyprland 使用者建議搭配
> XWayland 應用程式，或改用 `ydotool` 後端 —— 這部分**尚未在本專案內建**，
> 目前 Linux 的 computer-use 操作能力比 Windows 弱。

---

## 專案結構

```
jarvis/
├── __main__.py          進入點與主迴圈
├── config.py            所有可調參數（讀 .env）
├── router.py            本機優先路由 ← 省 token 的第一道關卡
├── screen.py            截圖擷取、縮放壓縮、座標換算
├── speech.py            STT / TTS（可退回純文字模式；支援 Vosk 離線）
├── wakeword.py          「Hey Jarvis」喚醒詞（openWakeWord，攜帶版用）
├── usage.py             token 計量與成本估算
├── agent.py             手腳 daemon：把本機工具掛到 WebSocket 上給大腦用
├── devices/             Local / Remote(WebSocket) / Adb(Android) 三種裝置，統一 call(tool, args)
├── hud.py               事件匯流排 + HUD WebSocket 橋接
├── pet.py               桌邊寵物（tkinter，C60 線框，講話時共振）
├── platform_/           Windows / Linux 平台實作
├── tools/
│   ├── apps.py          程式索引、開啟、視窗切換
│   ├── gui.py           滑鼠鍵盤、音量、剪貼簿、shell
│   ├── computer.py      Anthropic computer-use 動作執行器
│   ├── vision.py        鏡頭辨識
│   └── gestures.py      手勢框選（mediapipe，選用）
└── providers/
    ├── claude.py        computer-use agent loop + 分級路由 + 快取
    ├── gemini.py        function calling agent loop
    └── schema.py        Python function → Anthropic tool schema
```

---

## 專案狀態

誠實版。「程式完成」不等於「實機驗證過」，這張表分開寫：

| 功能 | 程式 | 實機驗證 |
|---|---|---|
| Gemini 後端、本機路由、token 節流 | ✅ | ✅ Windows 11 |
| Claude computer-use 後端 | ✅ | ⚠️ 依官方文件實作，尚未以真實額度跑過完整 agent loop |
| 桌邊寵物（去背、縮放、拖曳、關閉） | ✅ | ✅ Windows 11 |
| 鏡頭辨識 / 手勢框選 | ✅ | ✅ Windows 11 |
| Google Lens 反向搜尋（圖床上傳） | ✅ | ⚠️ 未實測 |
| 大腦 / 手腳分家（`jarvis.agent` + `devices/`） | ✅ | ✅ Windows 11 localhost（大腦 → agent → 工具往返） |
| Android ADB 控制 | ✅ | ⚠️ 僅以模擬 adb 驗證指令翻譯 |
| 喚醒詞（openWakeWord） | ✅ | ⚠️ 未實測 |
| Raspberry Pi 部署腳本 | ✅ | ⚠️ 未在真 Pi 上跑過 |
| Linux（Hyprland）桌面操作 | ⚠️ 部分 | Wayland 下 pyautogui 受限，見上方說明 |

### Roadmap

- [ ] Pi 5 實機：喚醒詞、麥克風、Tailscale 跨網路控制電腦
- [ ] Android 實機：ADB 無線偵錯 + 中文輸入
- [ ] Linux：`ydotool` 後端補上 Wayland 原生視窗操作
- [ ] STT / TTS 抽成 provider 介面（目前的 Google Web Speech / edge-tts 皆為非官方端點，不可商用）
- [ ] 自架 relay server 取代 Tailscale（產品化前提）
- [ ] 圓形 LCD 上畫 C60（Pi 攜帶版的臉）

## 參考

- [Computer use tool — Anthropic docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)
- [Prompt caching — Anthropic docs](https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching)
- [Gemini API models](https://ai.google.dev/gemini-api/docs/models)

## 授權

MIT
