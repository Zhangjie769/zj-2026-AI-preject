# -*- coding: utf-8 -*-
"""
7x7 隐藏形状游戏 —— 最优策略图形助手
------------------------------------
玩法：程序随机生成一局（5 个不可旋转/翻转的形状，互不重叠）。
     点击空格子会揭示它是"命中"还是"空格"。
     <橙色的格子> 就是程序根据你已看到的格子，按"贝叶斯最大后验占用率"
     规则推荐的"下一步"。跟着它点，就能用最少的点击把这 5 个形状点完。
顶部有当前点击次数 / 命中数 / 空点数。
"""
import os, sys, random
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from solver import Solver, N

# 颜色
C_BG      = "#f3f4f6"
C_UNKNOWN = "#475569"   # 未揭示
C_HIT     = "#16a34a"   # 命中(被覆盖)
C_EMPTY   = "#cbd5e1"   # 空格
C_HINT    = "#f59e0b"   # 推荐点
C_TEXT    = "#f8fafc"


class Game:
    def __init__(self):
        self.solver = Solver()   # 加载布局 + 位集合(已缓存, 很快)
        self.root = tk.Tk()
        self.root.title("7×7 隐藏形状 —— 最优策略助手")
        self.root.resizable(False, False)
        self.buttons = {}
        self.true_mask = 0
        self.obs = {}
        self.clicks = 0
        self.hits = 0
        self.empties = 0
        self.done = False
        self.hint_cell = None
        self._build_ui()
        self.new_game()

    # ---------- UI ----------
    def _build_ui(self):
        title = tk.Label(self.root, text="7×7 隐藏形状 · 最少点击策略",
                         font=("Microsoft YaHei UI", 13, "bold"), bg=C_BG)
        title.grid(row=0, column=0, columnspan=7, pady=8)

        frame = tk.Frame(self.root, bg=C_BG)
        frame.grid(row=1, column=0, columnspan=7)
        for r in range(N):
            for c in range(N):
                b = tk.Button(frame, text="?", width=4, height=2,
                              font=("Consolas", 12, "bold"),
                              bg=C_UNKNOWN, fg=C_TEXT, relief="ridge",
                              command=lambda rr=r, cc=c: self.reveal(rr, cc))
                b.grid(row=r, column=c, padx=2, pady=2)
                self.buttons[(r, c)] = b

        self.status = tk.Label(self.root, text="", font=("Microsoft YaHei UI", 10),
                               bg=C_BG, anchor="w", justify="left")
        self.status.grid(row=2, column=0, columnspan=7, sticky="we", padx=8, pady=(6, 0))

        controls = tk.Frame(self.root, bg=C_BG)
        controls.grid(row=3, column=0, columnspan=7, pady=8)
        tk.Button(controls, text="新局", width=10, command=self.new_game).pack(side="left", padx=4)
        tk.Button(controls, text="自动演示", width=10, command=self.auto_play).pack(side="left", padx=4)
        tk.Button(controls, text="退出", width=10, command=self.root.destroy).pack(side="left", padx=4)

        hint = tk.Label(self.root,
                        text="橙色 = 推荐坐标。单击格子揭示内容；空格点一下，命中会变绿。",
                        font=("Microsoft YaHei UI", 9), bg=C_BG, fg="#374151")
        hint.grid(row=4, column=0, columnspan=7, pady=(0, 6))

    # ---------- game logic ----------
    def _occ(self, r, c):
        return bool((self.true_mask >> (r * N + c)) & 1)

    def new_game(self):
        self.true_mask = int(self.solver.configs[random.randrange(self.solver.n)])
        self.obs = {}
        self.clicks = 0
        self.hits = 0
        self.empties = 0
        self.done = False
        for (r, c), b in self.buttons.items():
            b.config(text="?", bg=C_UNKNOWN, fg=C_TEXT)
        self.hint_cell = None
        self.recommend()

    def reveal(self, r, c):
        if self.done:
            return
        if (r, c) in self.obs:
            return
        occ = self._occ(r, c)
        self.clicks += 1
        self.obs[(r, c)] = 1 if occ else 0
        b = self.buttons[(r, c)]
        if occ:
            self.hits += 1
            b.config(text="●", bg=C_HIT)
        else:
            self.empties += 1
            b.config(text="·", bg=C_EMPTY, fg="#334155")
        if self.hits == 16:
            self.done = True
        self.refresh_status()
        self.recommend()
        if self.done:
            self._finish()

    def recommend(self):
        # 清除旧的推荐高亮
        if self.hint_cell is not None:
            rr, cc = self.hint_cell
            self.buttons[(rr, cc)].config(text="?", bg=C_UNKNOWN, fg=C_TEXT)
        self.hint_cell = None
        if self.done:
            return
        mv, why = self.solver.next_move(self.obs)
        if mv is None:
            # 已全部确定，但可能还有未点击的必中格子 -> 直接把剩余的选中格补完
            for (r, c), b in self.buttons.items():
                if (r, c) not in self.obs and self._occ(r, c):
                    self.reveal(r, c)
            return
        r, c = mv
        self.hint_cell = (r, c)
        self.buttons[(r, c)].config(text="→", bg=C_HINT, fg="#1f2937")

    def refresh_status(self):
        self.status.config(
            text=f"点击: {self.clicks}    命中: {self.hits}/16    空格: {self.empties}"
                 + ("      —— 已全部找到！" if self.done else ""))

    def _finish(self):
        self.refresh_status()
        tk.messagebox.showinfo("完成", f"全部 16 格都已点完！\n总点击 {self.clicks} 次"
                                         f"，其中空格 {self.empties} 次。")

    def auto_play(self):
        if self.done:
            return
        self._auto_step()

    def _auto_step(self):
        if self.done:
            return
        if self.hint_cell is None:
            self.recommend()
        if self.hint_cell is not None:
            r, c = self.hint_cell
            self.reveal(r, c)
            if not self.done:
                self.root.after(180, self._auto_step)


if __name__ == "__main__":
    g = Game()
    g.root.mainloop()