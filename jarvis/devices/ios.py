"""IosDevice：透過「捷徑（Shortcuts）自動化」操作 iPhone。

iOS 沒有讓第三方 App 讀畫面、代替使用者點擊的 API（Android 的 AccessibilityService
在 iOS 不存在），所以 iPhone 做不到「看畫面然後點」。能做的是**事先定義好的動作**：
開 App / 開網址、傳訊息、打電話、導航、調音量、計時器、讓手機唸一段話……

指令怎麼送到 iPhone：iOS 17+ 的捷徑自動化有「收到電子郵件（寄件者 + 主旨包含）」觸發器，
可以設成「立即執行」不用確認。JARVIS 寄一封主旨 `JARVIS: <指令>` 的信到你的 iCloud 信箱，
iPhone 上的自動化收到就跑「JARVIS」捷徑，捷徑解析主旨的第一個字（動詞）決定做什麼。
iCloud 是推播，延遲通常 2–5 秒；Gmail 在 Apple Mail 裡是定時抓取，會慢很多，不要用。

  .env
    JARVIS_DEVICES=iphone=ios://you@icloud.com     # 收指令的 iPhone 信箱（要加在 Apple Mail 裡）
    JARVIS_SMTP_HOST=smtp.gmail.com                 # JARVIS 用來寄信的帳號（建議另開一個專用信箱）
    JARVIS_SMTP_PORT=587
    JARVIS_SMTP_USER=jarvis.sender@gmail.com
    JARVIS_SMTP_PASS=應用程式密碼
    JARVIS_IOS_SECRET=一組密語                       # 選用：主旨變成 "JARVIS-密語: …"，防止別人寄信觸發
  iPhone 端捷徑與自動化的設定步驟：docs/ios.md

指令格式（捷徑端用「以空白分割」取第一個字當動詞）：
  url <網址或 URL scheme>     開 App（youtube:// line:// …）或網頁
  message <聯絡人> <內容>      iMessage / SMS
  call <聯絡人>
  navigate <地點>              Apple 地圖導航
  volume <0-100>
  timer <分鐘>
  say <文字>                   用 iPhone 的喇叭唸出來
  shortcut <捷徑名稱> [輸入]    執行任何你自己寫的捷徑

限制（誠實版）：單向、無法確認執行結果（只知道信寄出了）；iPhone 鎖定時多數捷徑
仍能跑，但「開 App」類需要解鎖；每封信會留在信箱裡（捷徑最後一步可以把它刪掉）。
"""

from __future__ import annotations

import json
import os
import smtplib
import time
from email.message import EmailMessage

from .base import Device, ToolOutput

# open_application 的口語名稱 → URL scheme。找不到就退回 `shortcut open <name>` 交給捷徑端的字典。
_APP_SCHEMES = {
    "youtube": "youtube://", "line": "line://", "instagram": "instagram://", "ig": "instagram://",
    "spotify": "spotify:", "discord": "discord://", "telegram": "tg://", "twitter": "twitter://",
    "x": "twitter://", "threads": "barcelona://", "gmail": "googlegmail://",
    "地圖": "maps://", "maps": "maps://", "google map": "comgooglemaps://", "google 地圖": "comgooglemaps://",
    "設定": "App-prefs://", "settings": "App-prefs://", "相機": "camera://", "camera": "camera://",
    "音樂": "music://", "music": "music://", "safari": "x-web-search://", "youtube music": "youtubemusic://",
    "chatgpt": "chatgpt://", "notion": "notion://", "shopee": "shopeetw://", "蝦皮": "shopeetw://",
}


class IosDevice(Device):
    kind = "ios"
    platform = "ios"

    def __init__(self, name: str, mailbox: str) -> None:
        self.name = name
        self.mailbox = mailbox
        self.host = os.environ.get("JARVIS_SMTP_HOST", "")
        self.port = int(os.environ.get("JARVIS_SMTP_PORT", "587") or 587)
        self.user = os.environ.get("JARVIS_SMTP_USER", "")
        self.password = os.environ.get("JARVIS_SMTP_PASS", "")
        self.sender = os.environ.get("JARVIS_SMTP_FROM", self.user)
        # 主旨帶密語：自動化的「主旨包含」條件設成 "JARVIS-<密語>:"，知道你信箱的人也觸發不了
        secret = os.environ.get("JARVIS_IOS_SECRET", "").strip()
        self.prefix = f"JARVIS-{secret}:" if secret else "JARVIS:"
        self._seq = 0
        if not mailbox or "@" not in mailbox:
            raise ValueError("ios:// 後面要接 iPhone 收指令的信箱，例如 ios://you@icloud.com")
        if not (self.host and self.user and self.password):
            raise RuntimeError("iPhone 裝置需要 JARVIS_SMTP_HOST / JARVIS_SMTP_USER / JARVIS_SMTP_PASS（JARVIS 寄信用）。")

    # ------------------------------------------------------------------
    def _send(self, command: str) -> str:
        self._seq += 1
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = self.mailbox
        msg["Subject"] = f"{self.prefix} {command}"
        msg.set_content(json.dumps({"id": self._seq, "command": command, "ts": int(time.time())}, ensure_ascii=False))
        if self.port == 465:
            with smtplib.SMTP_SSL(self.host, self.port, timeout=15) as s:
                s.login(self.user, self.password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(self.host, self.port, timeout=15) as s:
                s.starttls()
                s.login(self.user, self.password)
                s.send_message(msg)
        return command

    def ping(self) -> bool:
        # 寄信通道能不能用：只驗證 SMTP 登入，不寄信
        try:
            if self.port == 465:
                with smtplib.SMTP_SSL(self.host, self.port, timeout=10) as s:
                    s.login(self.user, self.password)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=10) as s:
                    s.starttls()
                    s.login(self.user, self.password)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    def call(self, tool: str, args: dict) -> ToolOutput:
        a = args or {}
        if tool.startswith("computer:"):
            raise RuntimeError(
                "iPhone 無法被看畫面或代替點擊（iOS 沒有這種 API）。"
                "請改用 phone_command 送捷徑指令：url / message / call / navigate / volume / timer / say / shortcut。"
            )
        if tool == "ping":
            return "pong"
        if tool == "phone_command":
            cmd = str(a.get("command", "")).strip()
            if not cmd:
                raise ValueError("phone_command 需要 command")
            self._send(cmd)
            return f"Sir, 已把指令送到 iPhone：{cmd}（捷徑會在幾秒內執行，無法回報結果）。"
        if tool == "open_application":
            q = str(a.get("app_name", "")).strip()
            scheme = _APP_SCHEMES.get(q.lower())
            self._send(f"url {scheme}" if scheme else f"shortcut open {q}")
            return f"Sir, 已請 iPhone 開啟 {q}。"
        if tool == "focus_window":
            return self.call("open_application", {"app_name": a.get("keyword", "")})
        if tool == "open_url":
            url = str(a.get("url", ""))
            if not url.startswith(("http://", "https://")) and "://" not in url and ":" not in url:
                url = "https://" + url
            self._send(f"url {url}")
            return f"Sir, 已請 iPhone 開啟 {url}。"
        if tool == "set_volume":
            action = a.get("action", "up")
            # 捷徑端只吃 0–100 的數字，up/down 用固定檔位
            level = {"up": "75", "down": "25", "mute": "0", "set": str(a.get("level", 50))}.get(action, "75")
            self._send(f"volume {level}")
            return "Sir, 已請 iPhone 調整音量。"
        if tool == "lock_screen":
            self._send("shortcut lock")
            return "Sir, 已請 iPhone 鎖定（需要捷徑端有對應動作）。"
        if tool in ("get_ui_tree", "list_windows"):
            return "iPhone 無法讀取畫面內容。"
        if tool in ("analyze_camera_view", "camera_search", "lens_search", "open_gesture_selector"):
            return "Sir, 鏡頭類工具請切回電腦或 Pi 本機執行。"
        return f"Sir, iPhone 不支援工具 {tool}；能做的請用 phone_command。"
