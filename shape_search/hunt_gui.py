# -*- coding: utf-8 -*-
"""
《逐鹿秋狩》棋盘辅助器
======================
真实棋盘图 + 5 只动物的图。规则：点到一只动物，整只自动显型；目标是找齐 5 只，
空格算浪费。程序用“各动物位置 + 空格”推理，用橙色框标出下一步点哪。

操作：
  * 命中动物 -> 从右侧把那只动物【拖】到棋盘上它出现的位置（或先点它、再点棋盘）。
  * 点到空格 -> 选“空格”，点一下那格。
  * 点错/放错 -> 选“擦除”，点一下那格（覆盖格会整只删掉）。
"""
import os, sys
import tkinter as tk
from PIL import Image, ImageTk

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import engine_new as E

N = E.N
ASSETS = os.path.join(HERE, "assets")
ADV = E.Advisor()

SPRITE = {0: "codex_deer.png", 1: "codex_boar.png", 2: "fox.png",
          3: "codex_duck.png", 4: "codex_chicken.png"}
NAME = {0: "鹿 (5格)", 1: "野猪 (4格)", 2: "白狐 (3格)", 3: "野鸭 (横2)", 4: "鸡 (竖2)"}

C_BG = "#20242c"; C_TXT = "#e5e7eb"


def load_sprite(name, trim_name=True):
    im = Image.open(os.path.join(ASSETS, name)).convert("RGBA")
    if trim_name:
        im = im.crop((0, 0, im.width, int(im.height * 0.82)))
    return im


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("逐鹿秋狩 · 棋盘辅助")
        self.root.configure(bg=C_BG)

        self.board_img = Image.open(os.path.join(ASSETS, "board.png")).convert("RGB")
        self.bw, self.bh = self.board_img.size
        self.cw = self.bw / N
        self.ch = self.bh / N

        self.found = []
        self.occupied = set()
        self.occ_mask = 0
        self.empty = set()
        self.tool = ("animal", 3)     # 默认野鸭
        self.drag_animal = None
        self._tk = {}

        self._build()
        self.redraw()

    # ---------- shape helpers ----------
    def shape_mask_at(self, s, r, c):
        tpl = E.SHAPES[E.ORDER[s]]
        minr = min(dr for dr, dc in tpl)
        minc = min(dc for dr, dc in tpl if dr == minr)
        mask = 0
        for dr, dc in tpl:
            rr, cc = r + (dr - minr), c + (dc - minc)
            if not (0 <= rr < N and 0 <= cc < N):
                return None
            mask |= 1 << (rr * N + cc)
        return mask

    def codepoint(self, s, mask):
        try:
            return E.PSM[s].index(mask)
        except ValueError:
            return None

    # ---------- UI ----------
    def _build(self):
        top = tk.Frame(self.root, bg=C_BG); top.pack(side="top", fill="x")
        tk.Label(top, text="逐鹿秋狩 · 棋盘辅助", bg=C_BG, fg=C_TXT,
                 font=("Microsoft YaHei UI", 13, "bold")).pack(side="left", padx=10, pady=6)
        tk.Label(top, text="命中就把动物拖到它出现的位置；空格用“空格”工具点。",
                 bg=C_BG, fg="#9ca3af", font=("Microsoft YaHei UI", 9)).pack(side="left")

        body = tk.Frame(self.root, bg=C_BG); body.pack(side="top")
        self.canvas = tk.Canvas(body, width=self.bw, height=self.bh, highlightthickness=0,
                                bg=C_BG, cursor="crosshair")
        self.canvas.grid(row=0, column=0, padx=10, pady=10)
        self.canvas.bind("<Button-1>", self.on_board_click)
        self.canvas.bind("<ButtonRelease-1>", self.on_board_release)

        side = tk.Frame(body, bg=C_BG); side.grid(row=0, column=1, sticky="n", padx=8, pady=8)
        tk.Label(side, text="把下面的动物拖到棋盘", bg=C_BG, fg=C_TXT,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")

        self.tool_widgets = {}
        for i in range(5):
            thumb = load_sprite(SPRITE[i]).resize((96, 116))
            ph = ImageTk.PhotoImage(thumb)
            self._tk[("thumb", i)] = ph
            lab = tk.Label(side, image=ph, bd=2, relief="raised", bg=C_BG)
            lab.pack(pady=2)
            lab.bind("<ButtonPress-1>", lambda e, i=i: self.thumb_press(i))
            self.tool_widgets[i] = lab

        row2 = tk.Frame(side, bg=C_BG); row2.pack(pady=(8, 0))
        self.empty_btn = tk.Button(row2, text="空格", width=8, command=lambda: self.select_tool(5))
        self.empty_btn.pack(side="left", padx=2)
        self.erase_btn = tk.Button(row2, text="擦除", width=8, command=lambda: self.select_tool(6))
        self.erase_btn.pack(side="left", padx=2)

        self.advice = tk.Label(self.root, text="", bg="#fff7ed", fg="#7c2d12",
                               font=("Microsoft YaHei UI", 11, "bold"), anchor="w",
                               justify="left", wraplength=620)
        self.advice.pack(side="top", fill="x", padx=10, pady=(0, 3))
        self.status = tk.Label(self.root, text="", bg=C_BG, fg=C_TXT,
                               font=("Microsoft YaHei UI", 10), anchor="w")
        self.status.pack(side="top", fill="x", padx=10)
        btns = tk.Frame(self.root, bg=C_BG); btns.pack(side="top", pady=6)
        tk.Button(btns, text="清空", width=10, command=self.clear).pack(side="left", padx=4)
        tk.Button(btns, text="退出", width=10, command=self.root.destroy).pack(side="left", padx=4)

        self.select_tool(3)

    def thumb_press(self, i):
        self.drag_animal = i
        self.select_tool(i)

    def select_tool(self, i):
        if i < 5:
            self.tool = ("animal", i)
        elif i == 5:
            self.tool = ("empty",)
        else:
            self.tool = ("erase",)
        for j, lab in self.tool_widgets.items():
            lab.config(bd=2, relief="sunken" if j == i else "raised",
                       highlightbackground="#f59e0b")
            if j == i:
                lab.configure(highlightthickness=0)
        self.empty_btn.config(relief="sunken" if i == 5 else "raised",
                              bg="#fde68a" if i == 5 else "SystemButtonFace")
        self.erase_btn.config(relief="sunken" if i == 6 else "raised",
                              bg="#fde68a" if i == 6 else "SystemButtonFace")

    # ---------- board ----------
    def cell_from_xy(self, x, y):
        return int(y // self.ch), int(x // self.cw)

    def on_board_click(self, ev):
        r, c = self.cell_from_xy(ev.x, ev.y)
        self.drag_animal = None
        self.act(r, c)

    def on_board_release(self, ev):
        if self.drag_animal is not None:
            r, c = self.cell_from_xy(ev.x, ev.y)
            self.act(r, c, force_animal=self.drag_animal)
            self.drag_animal = None

    def act(self, r, c, force_animal=None):
        if not (0 <= r < N and 0 <= c < N):
            return
        cell = r * N + c
        tool = ("animal", force_animal) if force_animal is not None else self.tool

        if tool[0] == "animal":
            s = tool[1]
            mask = self.shape_mask_at(s, r, c)
            if mask is None:
                self.advice.config(text="⚠ 放不下：超出棋盘边界"); return
            cp = self.codepoint(s, mask)
            if cp is None:
                self.advice.config(text="⚠ 这个形状这里放不下"); return
            if mask & self.occ_mask:
                self.advice.config(text="⚠ 和已放好的动物重叠了"); return
            self.found.append((s, cp))
            self.occ_mask |= mask
            self.occupied |= {i for i in range(N * N) if (mask >> i) & 1}
            self.empty -= self.occupied
        elif tool[0] == "empty":
            if cell in self.occupied:
                self.advice.config(text="⚠ 这格已经属于某只动物"); return
            self.empty.symmetric_difference_update({cell})
        elif tool[0] == "erase":
            if cell in self.empty:
                self.empty.discard(cell)
            else:
                for k, (s, cp) in enumerate(self.found):
                    m = E.PSM[s][cp]
                    if (m >> cell) & 1:
                        self.found.pop(k)
                        self.occ_mask &= ~m
                        self.occupied -= {i for i in range(N * N) if (m >> i) & 1}
                        break
        self.redraw()

    def clear(self):
        self.found = []; self.occupied = set(); self.occ_mask = 0; self.empty = set()
        self.redraw()

    # ---------- drawing ----------
    def redraw(self):
        cv = self.canvas
        cv.delete("all")
        if "_boardph" not in self.__dict__:
            self._boardph = ImageTk.PhotoImage(self.board_img)
        cv.create_image(0, 0, anchor="nw", image=self._boardph)
        for i in range(N + 1):
            cv.create_line(i * self.cw, 0, i * self.cw, self.bh, fill="#7c3aed", width=1)
            cv.create_line(0, i * self.ch, self.bw, i * self.ch, fill="#7c3aed", width=1)

        for cell in self.empty:
            r, c = divmod(cell, N)
            cv.create_rectangle(c * self.cw + 2, r * self.ch + 2, (c + 1) * self.cw - 2,
                                (r + 1) * self.ch - 2, outline="#94a3b8", width=2,
                                fill="#0f172a", stipple="gray50")
            cv.create_text((c + 0.5) * self.cw, (r + 0.5) * self.ch, text="空",
                           fill="#e2e8f0", font=("Microsoft YaHei UI", 16, "bold"))

        for s, cp in self.found:
            mask = E.PSM[s][cp]
            cells = [i for i in range(N * N) if (mask >> i) & 1]
            rs = [i // N for i in cells]; cs = [i % N for i in cells]
            r0, c0 = min(rs), min(cs)
            w = (max(cs) - c0 + 1) * self.cw; h = (max(rs) - r0 + 1) * self.ch
            key = ("spr", s, int(w), int(h))
            if key not in self._tk:
                self._tk[key] = ImageTk.PhotoImage(load_sprite(SPRITE[s]).resize((int(w), int(h))))
            cv.create_image(c0 * self.cw, r0 * self.ch, anchor="nw", image=self._tk[key])

        mv, info = ADV.next_move(self.occupied, self.empty, self.found)
        if mv is not None:
            r, c = mv
            cv.create_rectangle(c * self.cw + 3, r * self.ch + 3, (c + 1) * self.cw - 3,
                                (r + 1) * self.ch - 3, outline="#f59e0b", width=5)
            cv.create_text((c + 0.5) * self.cw, (r + 0.5) * self.ch - self.ch * 0.28,
                           text="→", fill="#f59e0b", font=("Consolas", 20, "bold"))
            self.advice.config(text=f"建议下一步点：({r}, {c})    ·    {info}")
        else:
            self.advice.config(text=f"没有可推荐的了 · {info}")

        self.status.config(text=f"已放动物 {len(self.found)}/5      空格 {len(self.empty)}"
                                f"      （总点击 ≈ 已找到动物数 + 空格数）")


if __name__ == "__main__":
    App().root.mainloop()
