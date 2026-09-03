@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================================
echo   J.A.R.V.I.S. setup
echo ==========================================================

set "PY=python"
where py >nul 2>&1 && set "PY=py"

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creating virtualenv...
    %PY% -m venv .venv || goto :fail
) else (
    echo [1/4] Virtualenv already exists, skipping.
)

set "VPY=.venv\Scripts\python.exe"

echo [2/4] Installing core packages ^(first run takes a few minutes^)...
"%VPY%" -m pip install --upgrade pip --quiet
"%VPY%" -m pip install --quiet python-dotenv requests anthropic pillow pyautogui pyperclip websockets pygetwindow || goto :fail

if not exist ".env" (
    copy .env.example .env >nul
    echo [!] Created .env - fill in ANTHROPIC_API_KEY before running.
)

echo [3/4] Offline check ^(no API key needed^)...
"%VPY%" -m jarvis --text --once "現在幾點" || goto :fail

echo [4/4] API check...
"%VPY%" -m jarvis --text --once "用兩句話解釋 Svelte 5 的 runes"

echo.
echo Done. Use run.bat to start J.A.R.V.I.S.
pause
exit /b 0

:fail
echo.
echo Setup failed. Copy the error above and send it to Claude.
pause
exit /b 1
