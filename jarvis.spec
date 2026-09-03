# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包設定：pyinstaller --noconfirm --clean jarvis.spec
#
# 產出 dist/JARVIS/JARVIS.exe（onedir，不用 onefile —— onefile 每次啟動都要解壓數百 MB，
# 而且防毒軟體特別討厭它）。mediapipe 刻意不打包（體積 +300MB），手勢框選在 exe 版會
# 誠實回報「未安裝」；其他功能全部保留。
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

hidden = (
    ["jarvis", "jarvis.agent", "jarvis.pet", "jarvis.wakeword"]
    + collect_submodules("jarvis")
    + ["anthropic", "google.genai", "speech_recognition", "edge_tts", "pygame", "pyaudio",
       "cv2", "websockets", "websockets.sync", "websockets.sync.client", "websockets.sync.server",
       "pyautogui", "pygetwindow", "pyperclip", "PIL", "dotenv", "requests", "numpy"]
)
datas = (
    [("hud", "hud"), ("assets", "assets"), (".env.example", ".")]
    + collect_data_files("openwakeword", include_py_files=False)
    + collect_data_files("speech_recognition", include_py_files=False)
    + copy_metadata("google-genai") + copy_metadata("anthropic")
)

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    hiddenimports=hidden,
    datas=datas,
    excludes=["mediapipe", "matplotlib", "tkinter.test", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="JARVIS",
    icon="assets/jarvis.ico",
    console=False,            # 無主控台；log 在 %USERPROFILE%\.jarvis\jarvis.log
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="JARVIS")
