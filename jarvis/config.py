"""集中式設定。所有可調參數都走環境變數，方便別人 clone 下來只改 .env 就能跑。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _load_dotenv_fallback() -> None:
    """沒裝 python-dotenv 時的最小 .env 解析：KEY=VALUE、忽略註解與空行、去掉引號。

    以前是「沒裝就安靜跳過」，結果使用者換了個 Python 跑，.env 整份沒生效，
    只看到「未設定金鑰」，完全猜不到原因。現在不依賴套件也一定會讀。
    只補「環境裡還沒有」的鍵，真正的環境變數優先。
    """
    import sys

    roots = [os.getcwd(), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    if getattr(sys, "frozen", False):  # PyInstaller：.env 放在 JARVIS.exe 旁邊
        roots.insert(0, os.path.dirname(sys.executable))
    for folder in roots:
        path = os.path.join(folder, ".env")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value
        except OSError:
            pass
        return


try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    _load_dotenv_fallback()


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except ValueError:
        return default


def _env_list(key: str, default: list[str]) -> list[str]:
    raw = os.environ.get(key, "")
    items = [x.strip() for x in raw.split(",") if x.strip()]
    return items or default


@dataclass(frozen=True)
class Settings:
    # ---- provider 選擇 ----
    # "claude" = Anthropic computer-use toolset（多步驟 GUI 任務較強）
    # "gemini" = Google Gemini function calling（原始實作，成本較低）
    provider: str = os.environ.get("JARVIS_PROVIDER", "claude").strip().lower()

    # ---- Anthropic ----
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    # 多工作區（multi-workspace）金鑰必須在每個請求帶上 workspace id，否則 API 回 400。
    # 金鑰若已 scope 到單一 workspace 就留空。
    anthropic_workspace_id: str = os.environ.get("ANTHROPIC_WORKSPACE_ID", "")
    # computer_toolset_20260801 支援的模型中最便宜的一階；可用 env 覆寫。
    claude_model: str = os.environ.get("JARVIS_CLAUDE_MODEL", "claude-sonnet-5")
    # 純文字對話（不需要看畫面）時降級用的模型
    claude_model_light: str = os.environ.get(
        "JARVIS_CLAUDE_MODEL_LIGHT", "claude-haiku-4-5"
    )
    claude_max_tokens: int = _env_int("JARVIS_CLAUDE_MAX_TOKENS", 1024)

    # ---- Gemini ----
    gemini_api_key: str = os.environ.get("GEMINI_API_KEY", "")
    gemini_models: list[str] = field(
        default_factory=lambda: _env_list(
            "JARVIS_GEMINI_MODELS",
            ["gemini-3.5-flash", "gemini-3.5-flash-lite"],
        )
    )
    gemini_model_light: str = os.environ.get(
        "JARVIS_GEMINI_MODEL_LIGHT", "gemini-3.5-flash-lite"
    )

    # ---- token 節流 ----
    # 截圖送進模型前縮放的長邊上限。1024 是視覺定位精度與 token 成本的甜蜜點。
    screenshot_max_edge: int = _env_int("JARVIS_SCREENSHOT_MAX_EDGE", 1024)
    screenshot_format: str = os.environ.get("JARVIS_SCREENSHOT_FORMAT", "jpeg")
    screenshot_quality: int = _env_int("JARVIS_SCREENSHOT_QUALITY", 70)
    # 對話歷史保留幾則完整訊息，更舊的壓成一行摘要
    history_keep_turns: int = _env_int("JARVIS_HISTORY_KEEP_TURNS", 8)
    # 歷史中只保留最近 N 張截圖，更舊的換成佔位文字（省最多 token 的一招）
    history_keep_images: int = _env_int("JARVIS_HISTORY_KEEP_IMAGES", 1)
    # 單一工具回傳文字進歷史前截斷長度
    tool_result_max_chars: int = _env_int("JARVIS_TOOL_RESULT_MAX_CHARS", 600)
    enable_prompt_cache: bool = _env_bool("JARVIS_PROMPT_CACHE", True)
    enable_local_router: bool = _env_bool("JARVIS_LOCAL_ROUTER", True)

    # ---- agent loop ----
    max_tool_steps: int = _env_int("JARVIS_MAX_TOOL_STEPS", 12)

    # ---- 安全 ----
    # execute_shell 預設關閉：讓陌生人 clone 下來不會第一次講話就被模型 rm -rf。
    allow_shell: bool = _env_bool("JARVIS_ALLOW_SHELL", False)
    # lens_search 需要把照片上傳到暫存圖床（1 小時後刪除）才能給 Google Lens 網址。
    # 不想讓任何照片離開電腦就設 0；camera_search 不受影響（它只把圖送給模型供應商）。
    allow_image_upload: bool = _env_bool("JARVIS_ALLOW_IMAGE_UPLOAD", True)
    # 每次動作之間的最小間隔，避免模型連點失控
    action_delay: float = float(os.environ.get("JARVIS_ACTION_DELAY", "0.15"))

    # ---- 語音 ----
    stt_language: str = os.environ.get("JARVIS_STT_LANG", "zh-TW")
    tts_voice_zh: str = os.environ.get("JARVIS_TTS_VOICE_ZH", "zh-CN-YunxiNeural")
    tts_voice_en: str = os.environ.get("JARVIS_TTS_VOICE_EN", "en-GB-RyanNeural")
    text_mode: bool = _env_bool("JARVIS_TEXT_MODE", False)

    # ---- 多裝置（Pi 大腦 ↔ PC / 手機）----
    # 例：JARVIS_DEVICES=pc=ws://100.64.0.2:8770?token=xxx,phone=adb://192.168.1.50:5555
    # 沒設就只有本機。詳見 jarvis/devices/__init__.py 與 docs/raspberry-pi.md
    agent_token: str = os.environ.get("JARVIS_AGENT_TOKEN", "")
    agent_port: int = _env_int("JARVIS_AGENT_PORT", 8770)
    agent_host: str = os.environ.get("JARVIS_AGENT_HOST", "0.0.0.0")
    # hub：手機 App 主動連進來的 WebSocket server（hub:// 裝置才會啟動），密語同 agent_token
    hub_port: int = _env_int("JARVIS_HUB_PORT", 8771)
    hub_host: str = os.environ.get("JARVIS_HUB_HOST", "0.0.0.0")
    # server mode（--serve）：手機遙控用的 HTTP 埠；認證同樣用 agent_token
    server_host: str = os.environ.get("JARVIS_SERVER_HOST", "0.0.0.0")
    server_port: int = _env_int("JARVIS_SERVER_PORT", 8080)
    # TLS（選用）：iOS Safari 的定位 / 麥克風只在 https 下開放。憑證用 `tailscale cert <機器>.<tailnet>.ts.net`
    tls_cert: str = os.environ.get("JARVIS_TLS_CERT", "")
    tls_key: str = os.environ.get("JARVIS_TLS_KEY", "")

    # ---- 喚醒詞（攜帶版必開）----
    wake_word: bool = _env_bool("JARVIS_WAKE_WORD", False)
    wake_word_model: str = os.environ.get("JARVIS_WAKE_WORD_MODEL", "hey_jarvis")
    wake_word_threshold: float = float(os.environ.get("JARVIS_WAKE_WORD_THRESHOLD", "0.5"))
    # 回覆講完後這幾秒內可以直接接著講，不用再喊喚醒詞
    wake_followup_seconds: float = float(os.environ.get("JARVIS_WAKE_FOLLOWUP_SECONDS", "8"))

    # ---- STT 引擎 ----
    # google = 免費線上（預設）；vosk = 離線，需要 pip install vosk 並下載中文模型
    stt_engine: str = os.environ.get("JARVIS_STT", "google").strip().lower()
    vosk_model_path: str = os.environ.get("JARVIS_VOSK_MODEL", "models/vosk-model-small-cn-0.22")

    # ---- HUD ----
    ws_host: str = os.environ.get("JARVIS_WS_HOST", "localhost")
    ws_port: int = _env_int("JARVIS_WS_PORT", 8765)


settings = Settings()
