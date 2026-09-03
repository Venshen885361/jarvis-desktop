' J.A.R.V.I.S. 無視窗啟動器：雙擊就跑，不會開黑色 cmd。
' 輸出寫在 %USERPROFILE%\.jarvis\jarvis.log；想看即時訊息改用 run.bat。
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = root

' 有 venv 就用 venv 的 pythonw，沒有就用系統的
py = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(py) Then py = "pythonw"

sh.Run """" & py & """ -m jarvis", 0, False
