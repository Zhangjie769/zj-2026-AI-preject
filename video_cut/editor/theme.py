# -*- coding: utf-8 -*-
"""
editor/theme.py —— 深色现代主题（ttk clam 定制，零第三方依赖）

统一配色：
  背景 #1e1e1e / 面板 #252526 / 组件 #2d2d30 / 文字 #e0e0e0
  强调 #4a9eff / 选区 #094771 / 危险 #e53935
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

BG = "#1e1e1e"
PANEL = "#252526"
WIDGET = "#2d2d30"
WIDGET2 = "#383838"
FG = "#e0e0e0"
FG_DIM = "#9a9a9a"
ACCENT = "#4a9eff"
SEL = "#094771"
SEL_FG = "#ffffff"
DANGER = "#e53935"
BORDER = "#3c3c3c"

FONT = ("Microsoft YaHei UI", 9)
FONT_MONO = ("Consolas", 9)


def apply_dark_theme(root: tk.Tk) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    root.configure(bg=BG)
    # tk 原生控件
    root.option_add("*Font", FONT)
    for klass, bg, fg in (
        ("Menu", BG, FG), ("Menubutton", BG, FG),
        ("Listbox", WIDGET, FG), ("Text", WIDGET, FG),
        ("Label", BG, FG), ("Entry", WIDGET, FG),
        ("Toplevel", BG, FG),
    ):
        try:
            root.option_add(f"*{klass}.background", bg)
            root.option_add(f"*{klass}.foreground", fg)
        except Exception:
            pass
    try:
        root.option_add("*Menu.activeBackground", SEL)
        root.option_add("*Menu.activeForeground", SEL_FG)
        root.option_add("*Menu.selectColor", ACCENT)
    except Exception:
        pass

    # ttk 样式
    style.configure(".", background=BG, foreground=FG, font=FONT,
                    bordercolor=BORDER, lightcolor=WIDGET2,
                    darkcolor=WIDGET2, troughcolor=WIDGET2)
    style.configure("TFrame", background=BG)
    style.configure("TLabelframe", background=BG, bordercolor=BORDER,
                    relief="solid")
    style.configure("TLabelframe.Label", background=BG, foreground=FG)
    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("Accent.TLabel", background=BG, foreground=ACCENT)

    style.configure("TButton", background=WIDGET, foreground=FG,
                    bordercolor=BORDER, padding=(8, 3))
    style.map("TButton",
              background=[("active", WIDGET2), ("pressed", SEL),
                          ("disabled", PANEL)],
              foreground=[("disabled", FG_DIM)])
    style.configure("Toolbutton", background=WIDGET, foreground=FG)
    style.map("Toolbutton", background=[("active", WIDGET2),
                                        ("pressed", SEL)])

    style.configure("TCheckbutton", background=BG, foreground=FG)
    style.map("TCheckbutton", background=[("active", BG)],
              foreground=[("disabled", FG_DIM)])
    style.configure("TRadiobutton", background=BG, foreground=FG)

    style.configure("TEntry", fieldbackground=WIDGET, foreground=FG,
                    insertcolor=FG, bordercolor=BORDER)

    style.configure("TCombobox", fieldbackground=WIDGET, foreground=FG,
                    background=WIDGET, arrowcolor=FG)
    style.map("TCombobox", fieldbackground=[("readonly", WIDGET)])
    try:
        root.option_add("*TCombobox*Listbox.background", WIDGET)
        root.option_add("*TCombobox*Listbox.foreground", FG)
        root.option_add("*TCombobox*Listbox.selectBackground", SEL)
        root.option_add("*TCombobox*Listbox.selectForeground", SEL_FG)
    except Exception:
        pass

    style.configure("Treeview", background=WIDGET, fieldbackground=WIDGET,
                    foreground=FG, bordercolor=BORDER, rowheight=22)
    style.map("Treeview", background=[("selected", SEL)],
              foreground=[("selected", SEL_FG)])
    style.configure("Treeview.Heading", background=WIDGET2, foreground=FG,
                    bordercolor=BORDER, relief="flat")
    style.map("Treeview.Heading", background=[("active", WIDGET2)])

    style.configure("TScale", background=BG, troughcolor=WIDGET2)
    style.configure("Horizontal.TScale", background=BG)

    style.configure("TProgressbar", background=ACCENT, troughcolor=WIDGET2,
                    bordercolor=BORDER)
    style.configure("Vertical.TScrollbar", background=WIDGET, troughcolor=BG,
                    arrowcolor=FG, bordercolor=BORDER)
    style.configure("Horizontal.TScrollbar", background=WIDGET,
                    troughcolor=BG, arrowcolor=FG, bordercolor=BORDER)
    style.configure("TSeparator", background=BORDER)

    style.configure("TNotebook", background=BG, bordercolor=BORDER)
    style.configure("TNotebook.Tab", background=WIDGET, foreground=FG,
                    padding=(10, 4))
    style.map("TNotebook.Tab", background=[("selected", WIDGET2)])