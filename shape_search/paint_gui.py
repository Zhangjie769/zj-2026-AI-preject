# -*- coding: utf-8 -*-
"""
逐鹿秋狩 · 涂色版辅助
=====================
6 种颜色：野鸭(横2)/鸡(竖2)/野猪(方块4)/鹿(5格)/白狐(L3)/空地；绿色=未知。
涂色时会自动计算“下一步最优点击”，用橙色 ★ 标出。
按钮：确认（锁定并再看一次结果）/ 转换模式 / 撤销 / 清空。
"""
import os, sys, copy
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import engine_new as E

N = E.N
ADV = E.Advisor()

GRASS = "#6d8c2f"
COLORS = {
    3: ("#2e8bd6", "鸭 横2"),
    4: ("#e8552e", "鸡 竖2"),
    1: ("#8a5a2b", "猪 方块4"),
    0: ("#d4a017", "鹿 5格"),
    2: ("#cfd8e3", "兔 L3"),
    "E": ("#f0e6c0", "空 地"),
}
PALETTE = [3, 4, 1, 0, 2, "E"]
CELL = 76
MARGIN = 30   # 边框留白：放行列号
BG = "#1b1f27"; FG = "#e5e7eb"


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("逐鹿秋狩 · 涂色辅助")
        self.root.configure(bg=BG)
        self.cells = [[None] * N for _ in range(N)]
        self.color = 3
        self.history = []
        self.precise = tk.BooleanVar(value=True)
        self.live_hint = True      # 自动提示开关（默认开 = 全自动）
        self.hint = None
        self.cell = 76          # 格子像素大小（随窗口自适应）
        self.advice_text = "涂色即可，程序会自动算下一步。"
        self._build()
        self.solve()
        self.root.state("zoomed")                    # 默认最大化
        self.root.bind("<Configure>", self._on_resize)
        self.root.update_idletasks()
        self._on_resize()

    # ---------- UI ----------
    def _build(self):
        tk.Label(self.root, text="逐鹿秋狩 · 涂色辅助", bg=BG, fg=FG,
                 font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w", padx=12, pady=(8, 0))
        self.mode_lab = tk.Label(self.root, text="", bg=BG, fg="#fbbf24",
                                 font=("Microsoft YaHei UI", 10, "bold"))
        self.mode_lab.pack(anchor="w", padx=12)
        self.update_mode_label()

        body = tk.Frame(self.root, bg=BG); body.pack(padx=10, pady=6)

        self.canvas = tk.Canvas(body, width=self.cell * N + 2 * MARGIN, height=self.cell * N + 2 * MARGIN,
                                highlightthickness=2, highlightbackground="#111", bg=BG)
        self.canvas.grid(row=0, column=0, sticky="n")
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Button-3>", self.on_right)
        tk.Label(body, text="先点右侧颜色，再点/拖格子涂色；右键单格擦回未知",
                 bg=BG, fg="#9ca3af", font=("Microsoft YaHei UI", 9)).grid(
                 row=1, column=0, pady=(2, 0))

        panel = tk.Frame(body, bg=BG); panel.grid(row=0, column=1, sticky="n", padx=12)

        tk.Label(panel, text="① 选颜色（点一下）", bg=BG, fg=FG,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        self.swatches = {}
        for key in PALETTE:
            col, name = COLORS[key]
            sw = tk.Label(panel, text=name, bg=col, fg="#111", width=12, height=1,
                          font=("Microsoft YaHei UI", 11, "bold"), bd=3, relief="raised",
                          anchor="center")
            sw.pack(fill="x", pady=1)
            sw.bind("<Button-1>", lambda e, k=key: self.select_color(k))
            self.swatches[key] = sw
        tk.Label(panel, text="右键单格 = 擦回未知", bg=BG, fg="#9ca3af",
                 font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(2, 8))

        tk.Label(panel, text="② 操作", bg=BG, fg=FG,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        self.confirm_btn = tk.Button(panel, text="重新计算", width=20, height=2,
                                     font=("Microsoft YaHei UI", 12, "bold"),
                                     bg="#16a34a", fg="white", command=self.confirm)
        self.confirm_btn.pack(fill="x", pady=2)
        self.switch_btn = tk.Button(panel, text="自动提示：开（点我关）", width=20,
                                    font=("Microsoft YaHei UI", 10), command=self.toggle_mode)
        self.switch_btn.pack(fill="x", pady=2)
        row = tk.Frame(panel, bg=BG); row.pack(fill="x", pady=2)
        tk.Button(row, text="撤销", width=9, font=("Microsoft YaHei UI", 10),
                  command=self.undo).pack(side="left", expand=True, fill="x", padx=1)
        tk.Button(row, text="清空", width=9, font=("Microsoft YaHei UI", 10),
                  command=self.clear).pack(side="left", expand=True, fill="x", padx=1)
        reset_btn = tk.Button(panel, text="重置 · 重新开始这一把", width=20, height=2,
                              font=("Microsoft YaHei UI", 11, "bold"),
                              bg="#dc2626", fg="white", command=self.reset_game)
        reset_btn.pack(fill="x", pady=2)
        ck = tk.Checkbutton(panel, text="精确模式（一步前瞻，更准）",
                            variable=self.precise, bg=BG, fg=FG,
                            selectcolor="#374151", activebackground=BG, anchor="w")
        ck.pack(fill="x", pady=(6, 0))

        self.advice = tk.Label(panel, text="", bg="#fff7ed", fg="#7c2d12",
                               font=("Microsoft YaHei UI", 11, "bold"), wraplength=240,
                               justify="left", anchor="w")
        self.advice.pack(fill="x", pady=(10, 4))

        self.stat = tk.Label(self.root, text="", bg=BG, fg=FG,
                             font=("Microsoft YaHei UI", 10), anchor="w")
        self.stat.pack(fill="x", padx=12, pady=(0, 8))

        self.select_color(3)
        self.update_mode_label()

    def select_color(self, key):
        self.color = key
        for k, sw in self.swatches.items():
            sw.config(relief="sunken" if k == key else "raised", bd=5 if k == key else 3)

    def toggle_mode(self):
        self.live_hint = not self.live_hint
        self.update_mode_label()
        if self.live_hint:
            self.solve()
        self.redraw()

    def update_mode_label(self):
        self.mode_lab.config(text="自动提示：开 —— 涂色即出建议（不用点任何按钮）"
                             if self.live_hint else "自动提示：关（点【重新计算】看建议）")

    # ---------- painting ----------
    def _cell(self, ev):
        x, y = ev.x - MARGIN, ev.y - MARGIN
        if x < 0 or y < 0:
            return -1, -1
        return int(y // self.cell), int(x // self.cell)

    def _on_resize(self, _ev=None):
        w = self.root.winfo_width(); h = self.root.winfo_height()
        if w < 200 or h < 200:
            return
        avail_w = w - 460      # 右侧面板等占用的宽度
        avail_h = h - 200      # 顶部标题/底部按钮等占用的高度
        newc = int(min(avail_w / N, avail_h / N, 150))
        newc = max(newc, 40)
        if newc != self.cell:
            self.cell = newc
            self.canvas.config(width=self.cell * N + 2 * MARGIN,
                               height=self.cell * N + 2 * MARGIN)
            self.redraw()

    def _paint(self, r, c):
        if not (0 <= r < N and 0 <= c < N):
            return
        if self.cells[r][c] == self.color:
            return
        self.history.append(copy.deepcopy(self.cells))
        self.cells[r][c] = self.color

    def on_click(self, ev):
        r, c = self._cell(ev)
        self._paint(r, c)
        if self.live_hint:
            self.solve()
        self.redraw()

    def on_drag(self, ev):
        r, c = self._cell(ev)
        self._paint(r, c)
        self.redraw()          # 拖动过程中只刷颜色，松开再算

    def on_release(self, ev):
        if self.live_hint:
            self.solve(); self.redraw()

    def on_right(self, ev):
        r, c = self._cell(ev)
        if not (0 <= r < N and 0 <= c < N):
            return
        if self.cells[r][c] is not None:
            self.history.append(copy.deepcopy(self.cells))
            self.cells[r][c] = None
            if self.live_hint:
                self.solve()
            self.redraw()

    def undo(self):
        if self.history:
            self.cells = self.history.pop()
            if self.live_hint:
                self.solve()
            self.redraw()

    def clear(self):
        self.history.append(copy.deepcopy(self.cells))
        self.cells = [[None] * N for _ in range(N)]
        if self.live_hint:
            self.solve()
        self.redraw()

    def reset_game(self):
        """彻底重置：整盘回到全部未知 + 清空撤销历史 + 立刻重新推荐。"""
        self.cells = [[None] * N for _ in range(N)]
        self.history = []
        self.hint = None
        self.advice_text = "涂色即可，程序会自动算下一步。"
        if self.live_hint:
            self.solve()
        self.redraw()

    # ---------- solve ----------
    def build_state(self):
        occ = set(); empty = set(); found = []; bad = []
        for s in range(5):
            cells = [(r, c) for r in range(N) for c in range(N) if self.cells[r][c] == s]
            if not cells:
                continue
            occ |= {r * N + c for r, c in cells}
            minr = min(r for r, c in cells); minc = min(c for r, c in cells)
            norm = frozenset((r - minr, c - minc) for r, c in cells)
            if norm == frozenset(E.SHAPES[E.ORDER[s]]):
                mask = 0
                for r, c in cells:
                    mask |= 1 << (r * N + c)
                cp = self.codepoint(s, mask)
                if cp is not None:
                    found.append((s, cp))
                else:
                    bad.append(COLORS[s][1].split()[0])
            else:
                bad.append(COLORS[s][1].split()[0])
        for r in range(N):
            for c in range(N):
                if self.cells[r][c] == "E":
                    empty.add(r * N + c)
        return occ, empty, found, bad

    def _set_advice(self, mv, info, bad):
        self.hint = mv
        if mv is None:
            self.advice_text = f"{info}"
        else:
            r, c = mv
            self.advice_text = f"→ 下一步点：第 {r+1} 行 第 {c+1} 列\n{info}"
            if bad:
                self.advice_text += f"\n⚠ {','.join(set(bad))} 涂得不完整，只按覆盖格算"

    def solve(self):
        occ, empty, found, bad = self.build_state()
        self.n_found = len(found)
        if self.precise.get():
            mv, info = ADV.lookahead_next_move(occ, empty, found)
        else:
            mv, info = ADV.next_move(occ, empty, found)
        self._set_advice(mv, info, bad)

    def confirm(self):
        self.solve()
        self.redraw()

    def codepoint(self, s, mask):
        try:
            return E.PSM[s].index(mask)
        except ValueError:
            return None

    # ---------- drawing ----------
    def redraw(self):
        cv = self.canvas
        cv.delete("all")
        cell = self.cell
        fs = max(14, int(cell * 0.26))     # 格子字号随格大小缩放
        # 行列号（1..7）
        for i in range(N):
            cv.create_text(MARGIN - 12, MARGIN + i * cell + cell / 2,
                           text=str(i + 1), fill="#d4d4d8",
                           font=("Consolas", 11, "bold"))
            cv.create_text(MARGIN + i * cell + cell / 2, MARGIN - 14,
                           text=str(i + 1), fill="#d4d4d8",
                           font=("Consolas", 11, "bold"))
        for r in range(N):
            for c in range(N):
                x0, y0 = MARGIN + c * cell, MARGIN + r * cell
                v = self.cells[r][c]
                col = GRASS if v is None else COLORS[v][0]
                cv.create_rectangle(x0 + 1, y0 + 1, x0 + cell - 1, y0 + cell - 1,
                                    fill=col, outline="#e5e7eb", width=2)
                if v is not None:
                    _, name = COLORS[v]
                    txtcol = "#111" if v in (2, "E", 0) else "#fff"
                    cv.create_text(x0 + cell / 2, y0 + cell / 2, text=name.split()[0],
                                   fill=txtcol, font=("Microsoft YaHei UI", fs, "bold"))
        if self.hint is not None:
            r, c = self.hint
            x0, y0 = MARGIN + c * cell, MARGIN + r * cell
            cv.create_rectangle(x0 + 3, y0 + 3, x0 + cell - 3, y0 + cell - 3,
                                outline="#f97316", width=5)
            cv.create_text(x0 + cell / 2, y0 + cell * 0.26, text="★",
                           fill="#f97316", font=("Microsoft YaHei UI", fs + 2, "bold"))
        self.advice.config(text=self.advice_text)
        n_animal = sum(1 for r in range(N) for c in range(N) if isinstance(self.cells[r][c], int))
        n_empty = sum(1 for r in range(N) for c in range(N) if self.cells[r][c] == "E")
        self.stat.config(text=f"已找到动物 {getattr(self, 'n_found', 0)}/5    "
                              f"已涂动物格 {n_animal}    空地格 {n_empty}")


if __name__ == "__main__":
    App().root.mainloop()
