# 把 JARVIS 打包成不需要 Python 的 Windows 程式：dist\JARVIS\JARVIS.exe
# 用法（專案資料夾）：powershell -ExecutionPolicy Bypass -File scripts\build-exe.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
Write-Host "使用 Python：$py"

# 打包前先確認套件都在。PyInstaller 找不到 hidden import 只會警告不會停，
# 結果就是 exe 跑起來才發現 No module named ...
$required = "speech_recognition","edge_tts","pygame","pyaudio","google.genai","anthropic","websockets","pyautogui","pyperclip","PIL","cv2","numpy","openwakeword","pystray"
$missing = @()
foreach ($m in $required) {
    & $py -c "import $m" 2>$null
    if ($LASTEXITCODE -ne 0) { $missing += $m }
}
if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "這個 Python 缺少：$($missing -join ', ')" -ForegroundColor Red
    Write-Host "先裝：$py -m pip install SpeechRecognition edge-tts pygame PyAudio google-genai anthropic websockets pyautogui pyperclip pillow opencv-python numpy openwakeword pystray"
    exit 1
}

& $py -m pip install --quiet pyinstaller
& $py -m PyInstaller --noconfirm --clean jarvis.spec

Write-Host ""
# 順便打包成 zip 放到 dist\downloads：手機 JARVIS 頁的「下載 App」會直接提供這個檔
New-Item -ItemType Directory -Force -Path dist\downloads | Out-Null
Compress-Archive -Path dist\JARVIS\* -DestinationPath dist\downloads\JARVIS-windows.zip -Force
Write-Host "完成：dist\JARVIS\JARVIS.exe（zip：dist\downloads\JARVIS-windows.zip）"
Write-Host "整個 dist\JARVIS 資料夾就是可散佈的程式；第一次跑會在旁邊找 .env（或用 .env.example 複製一份）。"
