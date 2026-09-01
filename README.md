# J.A.R.V.I.S.

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
git clone https://github.com/tonicatowo/jarvis-desktop
cd jarvis-desktop

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # 填入 ANTHROPIC_API_KEY
python -m jarvis
```

沒有麥克風？用鍵盤模式先玩玩看：

```bash
python -m jarvis --text
python -m jarvis --once "打開記事本"
```

HUD 介面：用瀏覽器打開 `hud/jarvis_hub.html`，後端跑起來會自動連上。

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
├── speech.py            STT / TTS（可退回純文字模式）
├── usage.py             token 計量與成本估算
├── hud.py               HUD WebSocket 橋接
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

## 參考

- [Computer use tool — Anthropic docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)
- [Prompt caching — Anthropic docs](https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching)
- [Gemini API models](https://ai.google.dev/gemini-api/docs/models)

## 授權

MIT
