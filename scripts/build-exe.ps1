# 把 JARVIS 打包成不需要 Python 的 Windows 程式：dist\JARVIS\JARVIS.exe
# 用法（專案資料夾）：powershell -ExecutionPolicy Bypass -File scripts\build-exe.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
& $py -m pip install --quiet pyinstaller
& $py -m PyInstaller --noconfirm --clean jarvis.spec

Write-Host ""
Write-Host "完成：dist\JARVIS\JARVIS.exe"
Write-Host "整個 dist\JARVIS 資料夾就是可散佈的程式；第一次跑會在旁邊找 .env（或用 .env.example 複製一份）。"
