# 產 Windows 安裝包：dist\JARVIS-Setup-<版本>.exe
# 用法（專案資料夾）：powershell -ExecutionPolicy Bypass -File scripts\build-installer.ps1 [-SkipBuild]
#   -SkipBuild：dist\JARVIS 已經是最新的，不重跑 PyInstaller
param([switch]$SkipBuild)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

# 1) PyInstaller → dist\JARVIS\
if (-not $SkipBuild -or -not (Test-Path "dist\JARVIS\JARVIS.exe")) {
    & powershell -ExecutionPolicy Bypass -File scripts\build-exe.ps1
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# 2) 版本號從 pyproject.toml 讀，安裝包檔名與「新增 / 移除程式」都用它
$version = (Select-String -Path pyproject.toml -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Host "版本：$version"

# 3) Inno Setup（沒有就用 winget 裝）
$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    Write-Host "找不到 Inno Setup，用 winget 安裝…"
    winget install --id JRSoftware.InnoSetup -e --silent --accept-package-agreements --accept-source-agreements
    $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (-not (Test-Path $iscc)) { throw "Inno Setup 裝不起來，請手動安裝：https://jrsoftware.org/isdl.php" }
}

# 4) 繁體中文安裝介面（Inno 官方的 unofficial 翻譯；抓不到就只有英文，不影響安裝）
$zh = "installer\ChineseTraditional.isl"
if (-not (Test-Path $zh)) {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/jrsoftware/issrc/main/Files/Languages/Unofficial/ChineseTraditional.isl" -OutFile $zh
    } catch { Write-Host "（略過中文語言檔：$($_.Exception.Message)）" }
}

# 5) 編譯
& $iscc "/DAppVersion=$version" "installer\JARVIS.iss"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$out = "dist\JARVIS-Setup-$version.exe"
Copy-Item $out "dist\JARVIS-Setup.exe" -Force       # 固定檔名：Release / 手機下載頁用
Write-Host ""
Write-Host "完成：$out（固定檔名 dist\JARVIS-Setup.exe）"
Write-Host "安裝包預設裝到 %LocalAppData%\Programs\JARVIS（不需要管理員）；金鑰存 %USERPROFILE%\.jarvis\.env"
