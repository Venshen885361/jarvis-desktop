"""本機端登入畫面：第一次啟動（或金鑰失效）時要求輸入 API 金鑰，驗證通過才放行。

為什麼要有這個畫面而不是叫使用者改 .env：
- 裝好就要能用。一般使用者不會開記事本找 ANTHROPIC_API_KEY= 那一行。
- 金鑰在存檔前先打一次最便宜的 API（列模型）驗證，錯的金鑰當場知道，不會到第一句話才炸。
- 存到 ~/.jarvis/.env（或專案 .env），只在這台電腦、不進 git、不上傳。

跟桌寵一樣用 tkinter：零額外相依、exe 版也有。
用法：
    from .login import needs_login, run_login
    if needs_login() and not run_login():   # 使用者關掉視窗 = 不登入 = 不啟動
        return 1
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import webbrowser

from . import envfile

try:  # tkinter 只有開視窗才需要；headless（Pi / CI / 測試）也要能 import 這個模組
    import tkinter as tk
    from tkinter import font as tkfont
except ImportError:  # pragma: no cover
    tk = None  # type: ignore[assignment]
    tkfont = None  # type: ignore[assignment]

PROVIDERS = {
    "gemini": {
        "label": "Gemini（有免費額度，先玩這個）",
        "key": "GEMINI_API_KEY",
        "url": "https://aistudio.google.com/apikey",
        "hint": "AI Studio → Create API key，貼上來就好",
    },
    "claude": {
        "label": "Claude（Anthropic，預付制）",
        "key": "ANTHROPIC_API_KEY",
        "url": "https://platform.claude.com/settings/keys",
        "hint": "多工作區金鑰才需要填 Workspace ID（wrkspc_…）",
    },
}

_BG, _PANEL, _FG, _DIM, _ACCENT, _ERR, _OK = "#030711", "#071427", "#dff4ff", "#6f8ca8", "#00e5ff", "#ff5f7a", "#3ddc84"


def current_provider() -> str:
    env = envfile.read() | {k: v for k, v in os.environ.items() if k in envfile.EDITABLE}
    p = (env.get("JARVIS_PROVIDER") or "claude").strip().lower()
    return p if p in PROVIDERS else "claude"


def needs_login() -> bool:
    """選定後端的金鑰是空的 → 要登入。不檢查金鑰對不對（那要打 API，登入畫面按下去才驗）。"""
    env = envfile.read() | {k: v for k, v in os.environ.items() if k in envfile.EDITABLE}
    return not env.get(PROVIDERS[current_provider()]["key"], "").strip()


def validate(provider: str, api_key: str, workspace_id: str = "") -> str | None:
    """用最便宜的呼叫（列模型）驗證金鑰。回 None = 通過；否則回給人看的錯誤訊息。"""
    api_key = api_key.strip()
    if not api_key:
        return "金鑰是空的"
    if any(ch.isspace() for ch in api_key):
        return "金鑰裡有空白或換行，通常是複製時多貼到了"
    try:
        if provider == "gemini":
            from google import genai

            client = genai.Client(api_key=api_key)
            next(iter(client.models.list(config={"page_size": 1})), None)
        else:
            import anthropic

            headers = {"anthropic-workspace-id": workspace_id.strip()} if workspace_id.strip() else None
            anthropic.Anthropic(api_key=api_key, default_headers=headers).models.list(limit=1)
    except ImportError as e:
        return f"缺套件：{e.name}（pip install {'google-genai' if provider == 'gemini' else 'anthropic'}）"
    except Exception as e:  # 400 / 401 / 網路：全部給人看，不猜
        msg = str(e)
        if "anthropic-workspace-id" in msg:
            return "這把是多工作區金鑰，要填 Workspace ID（platform.claude.com/settings/workspaces）"
        if "API key not valid" in msg or "401" in msg or "authentication" in msg.lower() or "invalid x-api-key" in msg.lower():
            return "金鑰不對（API 回 401 / invalid key）"
        return f"驗證失敗：{msg[:160]}"
    return None


def save(provider: str, api_key: str, workspace_id: str = "") -> os.PathLike:
    changes = {"JARVIS_PROVIDER": provider, PROVIDERS[provider]["key"]: api_key.strip()}
    if provider == "claude":
        changes["ANTHROPIC_WORKSPACE_ID"] = workspace_id.strip()
    return envfile.update(changes)


class LoginWindow:
    """登入視窗。parent=None 時自己開一個 Tk 主迴圈（啟動前）；給 parent 就是 Toplevel（桌寵選單「更換金鑰」）。"""

    def __init__(self, parent=None, on_done=None) -> None:
        if tk is None:
            raise RuntimeError("這個 Python 沒有 tkinter（Linux：sudo apt install python3-tk）")
        self.on_done = on_done
        self.result = False
        self._q: queue.Queue = queue.Queue()
        self.win = tk.Toplevel(parent) if parent is not None else tk.Tk()
        self.win.title("J.A.R.V.I.S. 登入")
        self.win.configure(bg=_BG)
        self.win.resizable(False, False)
        self.win.attributes("-topmost", True)
        try:
            self.win.iconbitmap(self._asset("jarvis.ico"))
        except Exception:
            pass

        zh = "Microsoft JhengHei" if sys.platform.startswith("win") else "sans-serif"
        mono = "Consolas" if sys.platform.startswith("win") else "monospace"
        self.f_title = tkfont.Font(family=mono, size=16, weight="bold")
        self.f_body = tkfont.Font(family=zh, size=10)
        self.f_small = tkfont.Font(family=zh, size=9)

        # 第一次（兩把金鑰都空）預設 Gemini：有免費額度，先玩得起來比較重要
        env = envfile.read() | {k: v for k, v in os.environ.items() if k in envfile.EDITABLE}
        first_time = not any(env.get(m["key"], "").strip() for m in PROVIDERS.values())
        self.provider = tk.StringVar(value="gemini" if first_time else current_provider())
        self.key = tk.StringVar()
        self.workspace = tk.StringVar(value=os.environ.get("ANTHROPIC_WORKSPACE_ID", ""))
        self.show_key = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="")

        self._build()
        self.provider.trace_add("write", lambda *_: self._refresh_provider())
        self._refresh_provider()
        self.win.protocol("WM_DELETE_WINDOW", self._cancel)
        self.win.bind("<Return>", lambda _e: self._submit())
        self.win.bind("<Escape>", lambda _e: self._cancel())
        self._center()
        self.win.after(100, self._poll)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        pad = {"padx": 28}
        frame = tk.Frame(self.win, bg=_BG)
        frame.pack(fill="both", expand=True, pady=(22, 20))

        tk.Label(frame, text="J.A.R.V.I.S.", font=self.f_title, fg=_ACCENT, bg=_BG).pack(anchor="w", **pad)
        tk.Label(frame, text="登入：輸入你的 API 金鑰。金鑰只存在這台電腦，不會上傳。",
                 font=self.f_body, fg=_DIM, bg=_BG).pack(anchor="w", pady=(2, 14), **pad)

        tk.Label(frame, text="模型後端", font=self.f_small, fg=_DIM, bg=_BG).pack(anchor="w", **pad)
        for pid, meta in PROVIDERS.items():
            tk.Radiobutton(frame, text=meta["label"], variable=self.provider, value=pid,
                           font=self.f_body, fg=_FG, bg=_BG, selectcolor=_PANEL, activebackground=_BG,
                           activeforeground=_ACCENT, highlightthickness=0).pack(anchor="w", padx=24)

        tk.Label(frame, text="API 金鑰", font=self.f_small, fg=_DIM, bg=_BG).pack(anchor="w", pady=(12, 2), **pad)
        row = tk.Frame(frame, bg=_BG)
        row.pack(fill="x", **pad)
        self.key_entry = self._entry(row, self.key, show="•")
        self.key_entry.pack(side="left", fill="x", expand=True)
        tk.Checkbutton(row, text="顯示", variable=self.show_key, command=self._toggle_show,
                       font=self.f_small, fg=_DIM, bg=_BG, selectcolor=_PANEL, activebackground=_BG,
                       highlightthickness=0).pack(side="left", padx=(8, 0))

        self.ws_label = tk.Label(frame, text="Workspace ID（只有多工作區金鑰要填）", font=self.f_small, fg=_DIM, bg=_BG)
        self.ws_entry = self._entry(frame, self.workspace)

        self.link = tk.Label(frame, text="", font=self.f_small, fg=_ACCENT, bg=_BG, cursor="hand2")
        self.link.pack(anchor="w", pady=(10, 0), **pad)
        self.link.bind("<Button-1>", lambda _e: webbrowser.open(PROVIDERS[self.provider.get()]["url"]))
        self.hint = tk.Label(frame, text="", font=self.f_small, fg=_DIM, bg=_BG)
        self.hint.pack(anchor="w", **pad)

        btn_row = tk.Frame(frame, bg=_BG)
        btn_row.pack(fill="x", pady=(16, 0), **pad)
        self.btn = tk.Button(btn_row, text="驗證並登入", command=self._submit, font=self.f_body,
                             fg=_BG, bg=_ACCENT, activebackground="#7ff0ff", activeforeground=_BG,
                             relief="flat", padx=18, pady=6, cursor="hand2")
        self.btn.pack(side="left")
        self.status_label = tk.Label(btn_row, textvariable=self.status, font=self.f_small, fg=_DIM, bg=_BG,
                                     wraplength=300, justify="left")
        self.status_label.pack(side="left", padx=(12, 0))

        tk.Label(frame, text=f"存放位置：{envfile.write_path()}", font=self.f_small, fg="#3f5670", bg=_BG).pack(
            anchor="w", pady=(16, 0), **pad)

    def _entry(self, parent, var, show: str = ""):
        return tk.Entry(parent, textvariable=var, show=show, width=46, bg=_PANEL, fg=_FG, insertbackground=_ACCENT,
                        relief="flat", font=self.f_body, highlightthickness=1, highlightbackground="#123049",
                        highlightcolor=_ACCENT)

    def _refresh_provider(self) -> None:
        meta = PROVIDERS[self.provider.get()]
        self.link.configure(text=f"取得金鑰：{meta['url']}")
        self.hint.configure(text=meta["hint"])
        if self.provider.get() == "claude":
            self.ws_label.pack(anchor="w", pady=(10, 2), padx=28, after=self.key_entry.master)
            self.ws_entry.pack(fill="x", padx=28, after=self.ws_label)
        else:
            self.ws_label.pack_forget()
            self.ws_entry.pack_forget()
        self.key_entry.focus_set()

    def _toggle_show(self) -> None:
        self.key_entry.configure(show="" if self.show_key.get() else "•")

    def _center(self) -> None:
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        x = (self.win.winfo_screenwidth() - w) // 2
        y = (self.win.winfo_screenheight() - h) // 3
        self.win.geometry(f"+{x}+{y}")

    @staticmethod
    def _asset(name: str) -> str:
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(base, "assets", name)

    # ------------------------------------------------------------------ 行為
    def _submit(self) -> None:
        provider, key, ws = self.provider.get(), self.key.get(), self.workspace.get()
        if not key.strip():
            self._set_status("先貼上金鑰", _ERR)
            return
        self.btn.configure(state="disabled")
        self._set_status("驗證中…", _DIM)
        threading.Thread(target=lambda: self._q.put(validate(provider, key, ws)), daemon=True).start()

    def _poll(self) -> None:
        try:
            err = self._q.get_nowait()
        except queue.Empty:
            self.win.after(100, self._poll)
            return
        if err:
            self._set_status(err, _ERR)
            self.btn.configure(state="normal")
            self.win.after(100, self._poll)
            return
        path = save(self.provider.get(), self.key.get(), self.workspace.get())
        self._set_status(f"登入成功，已存到 {path}", _OK)
        self.result = True
        self.win.after(600, self._finish)

    def _set_status(self, text: str, color: str) -> None:
        self.status.set(text)
        self.status_label.configure(fg=color)

    def _finish(self) -> None:
        if self.on_done:
            self.on_done(True)
        self._close()

    def _cancel(self) -> None:
        if self.on_done and not self.result:
            self.on_done(False)
        self._close()

    def _close(self) -> None:
        try:
            if isinstance(self.win, tk.Tk):
                self.win.quit()
            self.win.destroy()
        except tk.TclError:
            pass


def run_login() -> bool:
    """啟動前的登入：跑自己的主迴圈直到登入成功或使用者關窗。回傳是否登入成功。"""
    try:
        w = LoginWindow()
    except Exception as e:  # 沒有顯示器（SSH / Pi headless）或沒 tkinter：退回文字提示
        print(f"[登入] 無法開視窗（{e}）。請在 {envfile.write_path()} 填入金鑰，或用手機設定頁。")
        return False
    w.win.mainloop()
    return w.result
