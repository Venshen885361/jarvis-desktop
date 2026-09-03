# 在桌面建一個「J.A.R.V.I.S.」捷徑，指向 jarvis.vbs，用 assets\jarvis.ico 當圖示。
# 用法（在專案資料夾）：powershell -ExecutionPolicy Bypass -File scripts\make-shortcut.ps1
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$desktop = [Environment]::GetFolderPath("Desktop")
$lnk = Join-Path $desktop "J.A.R.V.I.S..lnk"

$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($lnk)
$s.TargetPath = "wscript.exe"
$s.Arguments = "`"$root\jarvis.vbs`""
$s.WorkingDirectory = $root
$s.IconLocation = "$root\assets\jarvis.ico,0"
$s.Description = "J.A.R.V.I.S. voice assistant"
$s.Save()

Write-Host "已建立捷徑：$lnk"
Write-Host "想開機自動啟動，把這個捷徑複製到： $env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
