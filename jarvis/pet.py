"""桌邊寵物：一顆會呼吸、會轉、講話時會抖的 C60 骨架，永遠浮在桌面最上層。

刻意用 tkinter，不用 Qt / pywebview：
- Windows 的 Python 內建就有，clone 下來零額外相依。
- `-transparentcolor` 在 Windows 上能做出真正的去背視窗，只剩線框浮在桌面。
- 幾何很小（60 點 90 邊），Canvas 30fps 綽綽有餘。

跟本體的連動走 hud.subscribe()：後端 emit_state / emit_log 的事件，WebSocket HUD
和這隻寵物收到的是同一份，兩者可以並存。tkinter 只能在主執行緒跑，所以主流程
（聽 → 想 → 講）被搬到背景執行緒，事件經 queue 丟回來，主執行緒只負責畫。

C60（截角二十面體）的頂點：對 (0, ±1, ±3φ)、(±1, ±(2+φ), ±2φ)、(±φ, ±2, ±(2φ+1))
取所有偶置換，剛好 60 個點；邊長為 2，所以「距離等於 2」的點對就是 90 條邊。
"""

from __future__ import annotations

import itertools
import json
import math
import os
import queue
import random
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont

from . import hud
from .config import settings

PHI = (1 + 5**0.5) / 2

MIN_SIZE, MAX_SIZE = 120, 640
# 講話動畫的整體強度：1.0 = 預設；嫌太安靜就調大，太誇張就調小（.env: JARVIS_PET_SPEAK_AMP）
SPEAK_AMP = float(os.environ.get("JARVIS_PET_SPEAK_AMP", "1.6"))
PREFS_PATH = Path.home() / ".jarvis_pet.json"  # 記住大小與位置，下次開在同一個地方

# 狀態 → (R, G, B, 自轉速度倍率)
_STATE_STYLE = {
    "standby": ((0, 229, 255), 1.0),
    "listening": ((0, 229, 255), 2.0),
    "thinking": ((138, 92, 255), 3.5),
    "speaking": ((0, 229, 255), 1.6),
}
_STATE_LABEL = {
    "standby": "STANDBY",
    "listening": "LISTENING",
    "thinking": "PROCESSING",
    "speaking": "SPEAKING",
}


def c60_geometry() -> tuple[list[tuple[float, float, float]], list[tuple[int, int]]]:
    base = [(0, 1, 3 * PHI), (1, 2 + PHI, 2 * PHI), (PHI, 2, 2 * PHI + 1)]
    verts: set[tuple[float, float, float]] = set()
    for b in base:
        for signs in itertools.product((1, -1), repeat=3):
            p = tuple(s * c for s, c in zip(signs, b, strict=True))
            for perm in ((0, 1, 2), (1, 2, 0), (2, 0, 1)):  # 偶置換
                verts.add(tuple(p[i] for i in perm))
    vlist = sorted(verts)
    radius = max(math.dist(v, (0, 0, 0)) for v in vlist)
    vlist = [(x / radius, y / radius, z / radius) for x, y, z in vlist]

    edge_len = 2.0 / radius
    edges = [
        (i, j)
        for i, j in itertools.combinations(range(len(vlist)), 2)
        if abs(math.dist(vlist[i], vlist[j]) - edge_len) < 1e-6
    ]
    return vlist, edges


def _rgb(r: float, g: float, b: float) -> str:
    clamp = lambda v: max(0, min(255, int(v)))  # noqa: E731
    return f"#{clamp(r):02x}{clamp(g):02x}{clamp(b):02x}"


class DesktopPet:
    TRANSPARENT = "#010101"  # chroma key：Windows 上這個顏色會變成完全透明
    HIT = "#070c14"          # 命中區底色：夠暗、但不是去背色，滑鼠事件才收得到
    FPS = 30

    def __init__(self, size: int = 240) -> None:
        prefs = self._load_prefs()
        self.size = int(prefs.get("size", size))
        self._saved_pos = prefs.get("pos")  # [x, y] 或 None
        self.events: queue.Queue = queue.Queue()
        self.text_queue: queue.Queue = queue.Queue()  # 文字模式下寵物的輸入框 → 主流程

        self.verts, self.edges = c60_geometry()
        self.phase = [random.uniform(0, math.tau) for _ in self.verts]
        self.ax = 0.3
        self.ay = 0.0
        self.t = 0.0
        self.state = "standby"
        self.color = [0.0, 229.0, 255.0]
        self.amp = 0.0
        self.amp_target = 0.0
        self.caption = ""
        self.caption_until = 0.0
        self.rings: list[float] = []  # 講話時往外擴散的聲波圈（記錄誕生時刻）
        self.device = ""  # 目前控制的裝置名稱（非本機時顯示）

        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S.")
        self.root.overrideredirect(True)  # 無邊框、不進工作列
        self.root.attributes("-topmost", True)

        # 只有 Windows 支援 chroma-key 去背；其他平台退回半透明深色底
        try:
            self.root.attributes("-transparentcolor", self.TRANSPARENT)
            self.bg = self.TRANSPARENT
            self.transparent = True
        except tk.TclError:
            self.bg = "#030711"
            self.transparent = False
            try:
                self.root.attributes("-alpha", 0.93)
            except tk.TclError:
                pass

        self.pad_bottom = 96 if settings.text_mode else 64
        self.w = self.size
        self.h = self.size + self.pad_bottom
        self.root.configure(bg=self.bg)
        self._hover_close = False
        self._resizing = False

        self.canvas = tk.Canvas(
            self.root, width=self.w, height=self.h,
            bg=self.bg, highlightthickness=0, bd=0,
        )
        self.canvas.pack()

        mono = "Consolas" if sys.platform.startswith("win") else "monospace"
        self.font_small = tkfont.Font(family=mono, size=8)
        self.font_caption = tkfont.Font(family="Microsoft JhengHei" if sys.platform.startswith("win") else "sans-serif", size=9)

        if settings.text_mode:
            self._build_entry()

        if self._saved_pos:
            self.root.geometry(f"{self.w}x{self.h}+{self._saved_pos[0]}+{self._saved_pos[1]}")
        else:
            self._place_bottom_right()
        self._bind_mouse()
        self._build_menu()
        self.root.bind("<Escape>", lambda e: self.quit())

        hud.subscribe(self.events.put)

    # ------------------------------------------------------------------ 偏好
    @staticmethod
    def _load_prefs() -> dict:
        try:
            return json.loads(PREFS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_prefs(self) -> None:
        try:
            PREFS_PATH.write_text(
                json.dumps(
                    {"size": self.size, "pos": [self.root.winfo_x(), self.root.winfo_y()]}
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ------------------------------------------------------------------ 視窗
    def _place_bottom_right(self) -> None:
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{self.w}x{self.h}+{sw - self.w - 24}+{sh - self.h - 72}")
        self._save_prefs()

    def set_size(self, size: int) -> None:
        """改變球體大小；視窗、畫布、輸入框一起跟著重排，位置以左上角為錨。"""
        size = max(MIN_SIZE, min(MAX_SIZE, int(size)))
        if size == self.size:
            return
        self.size = size
        self.w = size
        self.h = size + self.pad_bottom
        self.canvas.config(width=self.w, height=self.h)
        if settings.text_mode:
            self.entry.place(x=12, y=self.h - 30, width=self.w - 24, height=24)
        self.root.geometry(f"{self.w}x{self.h}+{self.root.winfo_x()}+{self.root.winfo_y()}")
        self._save_prefs()

    def _close_btn_rect(self) -> tuple[float, float, float, float]:
        r = 9
        cx, cy = self.w - 16, 16
        return cx - r, cy - r, cx + r, cy + r

    def _in_close_btn(self, x: float, y: float) -> bool:
        x1, y1, x2, y2 = self._close_btn_rect()
        return x1 - 4 <= x <= x2 + 4 and y1 - 4 <= y <= y2 + 4

    def _in_resize_grip(self, x: float, y: float) -> bool:
        return x >= self.w - 26 and self.size - 4 <= y <= self.size + 26

    def _bind_mouse(self) -> None:
        self._drag = (0, 0)

        def press(e):
            if self._in_close_btn(e.x, e.y):
                self.quit()
                return
            self._resizing = self._in_resize_grip(e.x, e.y)
            self._resize_origin = (self.size, e.x_root)  # 以按下當時為基準，避免第一下跳動
            self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

        def motion(e):
            if self._resizing:
                base, x0 = self._resize_origin
                self.set_size(base + (e.x_root - x0))
            else:
                self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

        def release(_e):
            self._resizing = False
            self._save_prefs()

        def hover(e):
            self._hover_close = self._in_close_btn(e.x, e.y)
            if self._in_resize_grip(e.x, e.y):
                self.canvas.config(cursor="size_nw_se" if sys.platform.startswith("win") else "bottom_right_corner")
            elif self._hover_close:
                self.canvas.config(cursor="hand2")
            else:
                self.canvas.config(cursor="fleur")

        def wheel(e):
            # Windows / macOS 用 delta；X11 用 Button-4/5
            step = 16 if (getattr(e, "delta", 0) > 0 or getattr(e, "num", 0) == 4) else -16
            self.set_size(self.size + step)

        c = self.canvas
        c.bind("<ButtonPress-1>", press)
        c.bind("<B1-Motion>", motion)
        c.bind("<ButtonRelease-1>", release)
        c.bind("<Motion>", hover)
        c.bind("<Leave>", lambda e: setattr(self, "_hover_close", False))
        c.bind("<MouseWheel>", wheel)
        c.bind("<Button-4>", wheel)
        c.bind("<Button-5>", wheel)

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="放大  (滾輪↑)", command=lambda: self.set_size(self.size + 32))
        menu.add_command(label="縮小  (滾輪↓)", command=lambda: self.set_size(self.size - 32))
        menu.add_command(label="重設大小", command=lambda: self.set_size(240))
        menu.add_separator()
        menu.add_command(label="回到右下角", command=self._place_bottom_right)
        menu.add_separator()
        menu.add_command(label="退出 J.A.R.V.I.S.  (Esc)", command=self.quit)
        self.canvas.bind("<ButtonPress-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

    def _build_entry(self) -> None:
        self.entry = tk.Entry(
            self.root, bg="#071427", fg="#dff4ff", insertbackground="#00e5ff",
            relief="flat", font=self.font_caption, highlightthickness=1,
            highlightbackground="#123049", highlightcolor="#00e5ff",
        )
        self.entry.place(x=12, y=self.h - 30, width=self.w - 24, height=24)
        self.entry.insert(0, "")

        def submit(_e=None):
            text = self.entry.get().strip()
            if text:
                self.text_queue.put(text)
                self.entry.delete(0, tk.END)

        self.entry.bind("<Return>", submit)

    # ------------------------------------------------------------------ 事件
    def _drain_events(self) -> None:
        while True:
            try:
                msg = self.events.get_nowait()
            except queue.Empty:
                return
            kind = msg.get("type")
            if kind == "state":
                self.state = msg.get("state", "standby")
            elif kind == "log" and msg.get("tag") == "JARVIS":
                self.caption = msg.get("text", "")
                self.caption_until = self.t + 8.0
            elif kind == "device":
                self.device = "" if msg.get("name") == "local" else str(msg.get("name", ""))
            elif kind == "quit":
                self.quit()

    # ------------------------------------------------------------------ 動畫
    def _tick(self) -> None:
        self._drain_events()
        dt = 1 / self.FPS
        self.t += dt

        color, speed = _STATE_STYLE.get(self.state, _STATE_STYLE["standby"])
        for i in range(3):
            self.color[i] += (color[i] - self.color[i]) * 0.12

        # 振幅：講話時隨機爆發，聆聽時微微起伏，思考時規律脈動，待命時靜止
        if self.state == "speaking":
            if random.random() < 0.45:
                self.amp_target = random.uniform(0.55, 1.0)
                if self.amp_target > 0.75 and (not self.rings or self.t - self.rings[-1] > 0.18):
                    self.rings.append(self.t)
        elif self.state == "listening":
            self.amp_target = 0.18 + random.random() * 0.1
        elif self.state == "thinking":
            self.amp_target = 0.25 + 0.2 * math.sin(self.t * 5)
        else:
            self.amp_target = 0.0
        self.amp += (self.amp_target - self.amp) * 0.3
        self.amp_target *= 0.86
        self.rings = [r for r in self.rings if self.t - r < 0.9]

        # 講話時轉速跟著音量衝，靜下來就慢回去
        boost = 1 + self.amp * 2.2 if self.state == "speaking" else 1
        self.ax += 0.006 * speed * boost
        self.ay += 0.011 * speed * boost

        self._draw()
        self.root.after(int(1000 / self.FPS), self._tick)

    def _project(self):
        cx, cy = self.w / 2, self.size / 2
        breathe = 0.03 * math.sin(self.t * 1.3) if self.state == "standby" else 0.0
        # 0.31 讓透視放大（最多 1.45x）加上講話抖動（1.1x）後仍落在 size/2 的命中圓盤內
        R = self.size * 0.31 * (1 + breathe + self.amp * 0.10 * SPEAK_AMP)
        D = 3.2

        sax, cax = math.sin(self.ax), math.cos(self.ax)
        say, cay = math.sin(self.ay), math.cos(self.ay)

        out = []
        for i, (x, y, z) in enumerate(self.verts):
            # 講話時每個頂點沿徑向抖動，相位各不同，看起來像整顆在共振
            k = 1 + self.amp * SPEAK_AMP * (
                0.16 * math.sin(self.t * 17 + self.phase[i])
                + 0.06 * math.sin(self.t * 31 + self.phase[i] * 2)
            )
            x, y, z = x * k, y * k, z * k
            # 繞 X 再繞 Y
            y, z = y * cax - z * sax, y * sax + z * cax
            x, z = x * cay + z * say, -x * say + z * cay
            p = D / (D - z)
            out.append((cx + x * R * p, cy + y * R * p, z))
        return out, cx, cy, R

    def _draw(self) -> None:
        c = self.canvas
        c.delete("all")
        pts, cx, cy, R = self._project()
        r, g, b = self.color
        white = self.amp * 0.8 if self.state == "speaking" else 0.0

        # 命中圓盤 + 下方面板。Windows 的 -transparentcolor 會把透明像素的滑鼠事件
        # 一起丟給桌面，所以球的範圍內必須有「非去背色」的像素，拖曳／滾輪才接得到。
        # 顏色壓到接近黑，視覺上只是一圈很淡的暈。
        half = self.size / 2 - 1
        c.create_oval(cx - half, cy - half, cx + half, cy + half, fill=self.HIT, outline="")
        c.create_rectangle(6, self.size - 2, self.w - 6, self.h - 2, fill=self.HIT, outline="")
        # 外圈細線讓圓盤邊界看起來是刻意的設計，而不是渲染殘留
        c.create_oval(
            cx - half, cy - half, cx + half, cy + half,
            outline=_rgb(r * 0.18, g * 0.18, b * 0.18), width=1,
        )

        # 講話時的聲波圈：從核心往外擴散、越遠越淡，一眼就知道它在出聲
        for born in self.rings:
            age = (self.t - born) / 0.9
            rr = R * (0.55 + age * 1.05)
            fade = (1 - age) ** 1.5
            c.create_oval(
                cx - rr, cy - rr, cx + rr, cy + rr,
                outline=_rgb(r * fade + 255 * fade * 0.3, g * fade + 255 * fade * 0.3, b * fade),
                width=2 if age < 0.4 else 1,
            )

        # 內核兩圈（跟 HUD 一樣的語彙）
        pulse = (math.sin(self.t * 10) * 0.5 + 0.5) * 0.06 if self.state == "speaking" else 0
        for k, alpha in ((0.42 + pulse, 0.55), (0.32, 0.35)):
            c.create_oval(
                cx - R * k, cy - R * k, cx + R * k, cy + R * k,
                outline=_rgb(r * alpha, g * alpha, b * alpha), width=1,
            )

        # 邊：先畫遠的，後畫近的，近的比較亮比較粗
        order = sorted(self.edges, key=lambda e: pts[e[0]][2] + pts[e[1]][2])
        for i, j in order:
            x1, y1, z1 = pts[i]
            x2, y2, z2 = pts[j]
            depth = ((z1 + z2) / 2 + 1) / 2  # 0 = 最遠, 1 = 最近
            bright = 0.22 + 0.78 * depth
            col = _rgb(
                r * bright + (255 - r) * white * depth,
                g * bright + (255 - g) * white * depth,
                b * bright + (255 - b) * white * depth,
            )
            width = 2 if depth > 0.55 else 1
            if self.state == "speaking" and depth > 0.55 and self.amp > 0.5:
                width = 3
            c.create_line(x1, y1, x2, y2, fill=col, width=width)

        # 前側頂點的小點
        for x, y, z in pts:
            if z > 0.15:
                s = 1.5 + z * 1.5
                c.create_oval(x - s, y - s, x + s, y + s, fill=_rgb(r, g, b), outline="")

        # 狀態標籤
        label = "● " + _STATE_LABEL.get(self.state, "STANDBY")
        if self.device:
            label += f"  ›  {self.device.upper()}"
        c.create_text(
            self.w / 2, self.size + 10, text=label, fill=_rgb(r * 0.85, g * 0.85, b * 0.85),
            font=self.font_small,
        )

        # 最後一句回覆
        if self.caption and self.t < self.caption_until:
            c.create_text(
                self.w / 2, self.size + 28, text=self.caption, width=self.w - 24,
                fill="#dff4ff", font=self.font_caption, justify="center", anchor="n",
            )

        # 右上角關閉鈕：平常淡淡的，滑鼠移上去才亮，不搶球體的視覺
        x1, y1, x2, y2 = self._close_btn_rect()
        if self._hover_close:
            c.create_oval(x1, y1, x2, y2, fill="#3a1520", outline="#ff5c7a", width=1)
            c.create_text((x1 + x2) / 2, (y1 + y2) / 2 - 1, text="×", fill="#ff5c7a", font=self.font_caption)
        else:
            c.create_oval(x1, y1, x2, y2, fill=self.HIT, outline=_rgb(r * 0.35, g * 0.35, b * 0.35), width=1)
            c.create_text((x1 + x2) / 2, (y1 + y2) / 2 - 1, text="×", fill=_rgb(r * 0.45, g * 0.45, b * 0.45), font=self.font_caption)

        # 右下角縮放把手（三條斜線）
        gx, gy = self.w - 6, self.size + 8
        for k in (4, 9, 14):
            c.create_line(gx - k, gy, gx, gy - k, fill=_rgb(r * 0.4, g * 0.4, b * 0.4), width=1)

    # ------------------------------------------------------------------ 生命週期
    def run(self, worker) -> None:
        """在背景執行緒跑 worker（賈維斯主流程），主執行緒跑 tk。worker 結束就關窗。"""

        def _wrapped():
            try:
                worker()
            finally:
                self.events.put({"type": "quit"})

        threading.Thread(target=_wrapped, daemon=True).start()
        self.root.after(50, self._tick)
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            pass
        self.quit()

    def quit(self) -> None:
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        # 背景執行緒可能正卡在麥克風 listen 裡，正常 join 不回來；桌寵關掉就是要整個結束。
        os._exit(0)
