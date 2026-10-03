# -*- coding: utf-8 -*-
"""
7x7 隐藏形状 —— “给棋盘，要建议”输入版
======================================
新规则：每个形状点中一格，整块自动显型；目标是“找齐 5 个形状”，空格算浪费。

怎么用：
  1. 你在游戏里点了一格，看到结果后，到这边把它标出来：
       - 点一下格子：未知('?') -> 覆盖(● 该处是某个形状的格子) -> 空格(·) -> 未知
  2. 程序会【自动识别】你标出的覆盖格属于哪几个形状、放在哪，并自动给出
     <橙色的下一格>：你在真实游戏里点它即可。
  3. 就这样一步步把看到的格子标完，跟着橙色格点，直到找齐 5 个形状。

（说明：如果你“看到一个形状”就把它所有格子都标成覆盖，程序能更准地推断。）
"""
import os, sys
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import engine_new as E

N = E.N
ADV = E.Advisor()

C_BG      = "#f3f4f6"
C_UNKNOWN = "#475569"
C_HIT     = "#16a34a"
C_EMPTY   = "#cbd5e1"
C_HINT    = "#f59e0b"
C_TEXT    = "#f8fafc"

SHAPE_NAMES = ["鹿形5", "方块4", "L形3", "横2", "竖2"]


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("7×7 隐藏形状 · 输入棋盘/给建议")
        self.root.resizable(False, False)
        self.buttons = {}
        self.state = {}          # cell -> 'u'/'c'/'e'
        self.hint_cell = None
        self._build_ui()
        for c in range(N * N):
            self.state[c] = "u"
        self.refresh_all()

    def _build_ui(self):
        tk.Label(self.root, text="7×7 隐藏形状 · 输入棋盘，程序给下一步",
                 font=("Microsoft YaHei UI", 13, "bold"), bg=C_BG).grid(
                 row=0, column=0, columnspan=7, pady=6)

        frame = tk.Frame(self.root, bg=C_BG)
        frame.grid(row=1, column=0, columnspan=7)
        for r in range(N):
            for c in range(N):
                b = tk.Button(frame, text="?", width=4, height=2,
                              font=("Consolas", 12, "bold"),
                              bg=C_UNKNOWN, fg=C_TEXT, relief="ridge",
                              command=lambda rr=r, cc=c: self.toggle(rr, cc))
                b.grid(row=r, column=c, padx=2, pady=2)
                self.buttons[(r, c)] = b

        self.advice = tk.Label(self.root, text="", font=("Microsoft YaHei UI", 11, "bold"),
                               bg="#fff7ed", fg="#7c2d12", anchor="w", justify="left",
                               wraplength=520)
        self.advice.grid(row=2, column=0, columnspan=7, sticky="we", padx=8, pady=6)

        self.status = tk.Label(self.root, text="", font=("Microsoft YaHei UI", 10),
                               bg=C_BG, anchor="w", justify="left")
        self.status.grid(row=3, column=0, columnspan=7, sticky="we", padx=8)

        row = tk.Frame(self.root, bg=C_BG); row.grid(row=4, column=0, columnspan=7, pady=8)
        tk.Button(row, text="清空", width=10, command=self.clear).pack(side="left", padx=4)
        tk.Button(row, text="退出", width=10, command=self.root.destroy).pack(side="left", padx=4)

        tk.Label(self.root,
                 text="●=覆盖(形状的格子)   ·=空格   ?=未点   ⚠点一下可选●或·（连点切换）\n"
                      "橙色=程序建议你下一步点这里。尽力把一个显型的形状的所有格子都标成●。",
                 font=("Microsoft YaHei UI", 9), bg=C_BG, fg="#374151").grid(
                 row=5, column=0, columnspan=7, pady=(0, 6))

    # ---------- interaction ----------
    def toggle(self, r, c):
        i = r * N + c
        order = ["u", "c", "e"]
        self.state[i] = order[(order.index(self.state[i]) + 1) % 3]
        self.refresh_all()

    def clear(self):
        for c in range(N * N):
            self.state[c] = "u"
        self.refresh_all()

    def _paint(self, r, c, txt, bg, fg=C_TEXT):
        self.buttons[(r, c)].config(text=txt, bg=bg, fg=fg)

    def refresh_all(self):
        # clear previous hint
        if self.hint_cell is not None:
            r, c = self.hint_cell
            self._paint(r, c, "?", C_UNKNOWN)
        self.hint_cell = None

        covered = {i for i in range(N * N) if self.state[i] == "c"}
        empty = {i for i in range(N * N) if self.state[i] == "e"}

        # paint current states
        for (r, c), b in self.buttons.items():
            i = r * N + c
            if self.state[i] == "c":
                b.config(text="●", bg=C_HIT, fg="#ffffff")
            elif self.state[i] == "e":
                b.config(text="·", bg=C_EMPTY, fg="#334155")
            else:
                b.config(text="?", bg=C_UNKNOWN, fg=C_TEXT)

        # detect found shapes
        found = E.detect_shapes(covered)
        mv, info = ADV.next_move(covered, empty, found)

        nfound = len(found)
        if mv is not None:
            r, c = mv
            self.hint_cell = (r, c)
            self._paint(r, c, "→", C_HINT, fg="#1f2937")
            self.advice.config(text=f"建议下一步点：({r}, {c})    ·  {info}")
        else:
            self.advice.config(text="建议：没有可点的了 —— " + str(info))

        found_names = "、".join(SHAPE_NAMES[idx] for idx, _ in found) or "—"
        self.status.config(
            text=f"已识别形状：{nfound}/5 [{found_names}]    "
                 f"覆盖格 {len(covered)}   空格(已浪费) {len(empty)}"
                 + ("    ✅ 五个形状都识别出来了！" if nfound == 5 else ""))


if __name__ == "__main__":
    App().root.mainloop()