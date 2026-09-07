#!/usr/bin/env bash
# =============================================================================
# J.A.R.V.I.S. 大腦 —— Raspberry Pi 一鍵安裝
#
#   curl -fsSL https://raw.githubusercontent.com/Venshen885361/jarvis-desktop/main/scripts/pi-setup.sh | bash
#   或 clone 之後：bash scripts/pi-setup.sh
#
# 做的事（每一步都可重跑，不會重複裝）：
#   1. apt：Python venv、PortAudio（PyAudio 需要）、adb、git
#   2. Tailscale（沒裝才裝；裝完要你自己 `sudo tailscale up` 登入）
#   3. clone / 更新 repo 到 ~/jarvis-desktop
#   4. venv + pip：大腦需要的套件（不裝 pyautogui / opencv —— 那是手腳的事）
#   5. 喚醒詞模型（openWakeWord hey_jarvis）
#   6. （選）Vosk 離線中文模型
#   7. .env（沒有才從範本複製）
#   8. systemd user service（不啟用，等你填好 .env 再啟用）
#
# 測試環境：Raspberry Pi OS Bookworm 64-bit（Python 3.11）。其他版本請自行對照。
# =============================================================================
set -euo pipefail

REPO_URL="https://github.com/Venshen885361/jarvis-desktop"
DIR="$HOME/jarvis-desktop"
WITH_VOSK="${WITH_VOSK:-0}"          # WITH_VOSK=1 bash scripts/pi-setup.sh 會順便抓離線模型
VOSK_MODEL="vosk-model-small-cn-0.22"

log()  { printf '\033[36m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[setup]\033[0m %s\n' "$*"; }

# ---------------------------------------------------------------- 1. apt
log "安裝系統套件"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip python3-dev \
    portaudio19-dev libopenblas-dev libatlas-base-dev \
    adb git curl unzip alsa-utils

# ---------------------------------------------------------------- 2. Tailscale
if ! command -v tailscale >/dev/null 2>&1; then
    log "安裝 Tailscale"
    curl -fsSL https://tailscale.com/install.sh | sh
else
    log "Tailscale 已安裝，略過"
fi

# ---------------------------------------------------------------- 3. repo
if [ -d "$DIR/.git" ]; then
    log "更新 repo（$DIR）"
    git -C "$DIR" pull --ff-only || warn "git pull 失敗，用現有版本繼續"
elif [ -f "$(dirname "$0")/../pyproject.toml" ] 2>/dev/null; then
    DIR="$(cd "$(dirname "$0")/.." && pwd)"
    log "在 repo 內執行，使用 $DIR"
else
    log "clone repo 到 $DIR"
    git clone "$REPO_URL" "$DIR"
fi
cd "$DIR"

# ---------------------------------------------------------------- 4. venv + pip
if [ ! -x .venv/bin/python ]; then
    log "建立 venv"
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
log "安裝 Python 套件（第一次要幾分鐘）"
pip install --quiet \
    python-dotenv requests websockets pillow \
    anthropic google-genai \
    SpeechRecognition edge-tts pygame PyAudio \
    openwakeword numpy

# ---------------------------------------------------------------- 5. 喚醒詞模型
log "下載喚醒詞模型（hey_jarvis）"
python - <<'PY' || warn "喚醒詞模型下載失敗，之後第一次啟動會再試一次"
import openwakeword
openwakeword.utils.download_models(model_names=["hey_jarvis"])
print("ok")
PY

# ---------------------------------------------------------------- 6. Vosk（選）
if [ "$WITH_VOSK" = "1" ]; then
    log "安裝 Vosk 離線辨識 + 中文模型"
    pip install --quiet vosk opencc-python-reimplemented
    mkdir -p models
    if [ ! -d "models/$VOSK_MODEL" ]; then
        ( cd models && curl -fsSLO "https://alphacephei.com/vosk/models/$VOSK_MODEL.zip" \
          && unzip -q "$VOSK_MODEL.zip" && rm "$VOSK_MODEL.zip" )
    fi
fi

# ---------------------------------------------------------------- 7. .env
if [ ! -f .env ]; then
    log "建立 .env（從範本）"
    cp .env.example .env
    # Pi 上的合理預設：Gemini 免費層、喚醒詞開、沒螢幕
    sed -i 's/^JARVIS_PROVIDER=.*/JARVIS_PROVIDER=gemini/' .env
    sed -i 's/^JARVIS_WAKE_WORD=.*/JARVIS_WAKE_WORD=1/' .env
    [ "$WITH_VOSK" = "1" ] && sed -i 's/^JARVIS_STT=.*/JARVIS_STT=vosk/' .env
    warn ".env 已建立，請填：GEMINI_API_KEY、JARVIS_DEVICES、JARVIS_AGENT_TOKEN"
else
    log ".env 已存在，不動"
fi

# ---------------------------------------------------------------- 8. systemd
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/jarvis.service" <<EOF
[Unit]
Description=J.A.R.V.I.S. brain
After=network-online.target sound.target

[Service]
WorkingDirectory=$DIR
# --serve：手機當遙控器（http://<Pi>:8080 + ws :8765）。想改成 Pi 自己聽麥克風就換成 --no-pet
ExecStart=$DIR/.venv/bin/python -m jarvis --serve
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload

# ---------------------------------------------------------------- 完成
cat <<EOF

$(printf '\033[32m')安裝完成。$(printf '\033[0m')接下來：

  1. 登入 Tailscale（只要一次）：
       sudo tailscale up
       tailscale ip -4          # 記下 Pi 的 100.x.y.z

  2. 填 .env：
       nano $DIR/.env
     至少要有 GEMINI_API_KEY 與 JARVIS_AGENT_TOKEN（手機遙控的密語）；
     要控制電腦再填 JARVIS_DEVICES；家電再填 HA_URL / HA_TOKEN

  3. 先手動跑一次確認麥克風與喇叭：
       cd $DIR && source .venv/bin/activate
       python -m jarvis --no-pet
     說「Hey Jarvis」→ 等它回應 → 再說「現在幾點」

  4. 都沒問題再開機自動跑：
       systemctl --user enable --now jarvis
       loginctl enable-linger \$USER
       journalctl --user -u jarvis -f

麥克風沒聲音？ arecord -l 看裝置、arecord -d 3 test.wav && aplay test.wav 測收放音。
EOF
