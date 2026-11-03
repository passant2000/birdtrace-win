# -*- coding: utf-8 -*-
"""时间线列宽预算回归: 各档窗口宽度下横向滚动条必须不出现(max=0)。
用真库副本+真实主窗口(同verify_tree_nav)。

用法: .venv/Scripts/python.exe tools/verify_timeline_cols.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

from app import theme, i18n
from app.db import Library
from app.paths import assets_dir
from app.ui.main_window import MainWindow

FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


app = QApplication(sys.argv)
lib = Library(PROJ / "data" / "_lag_lib")
theme.apply_theme(app, "system")
i18n.set_lang("zh")
win = MainWindow(lib, assets_dir())
win.show()

tl = win.pages["timeline"]
win.switch_to("timeline")

from PySide6.QtCore import QEventLoop


def settle(ms=600):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


settle(1800)   # 首次布局稳定(树导航验证的教训: 必须等布局)

for w in (900, 1100, 1300, 1500, 1700, 1920, 2400):
    win.resize(w, 860)
    tl._resize_debounce.stop()
    tl._on_relayout()
    settle(700)
    hmax = tl.scroll.horizontalScrollBar().maximum()
    cols = tl._cur_cols
    vp = tl.scroll.viewport().width()
    need = cols * 140 + (cols - 1) * 10 + 16
    check(hmax == 0,
          f"窗宽{w}: 视口{vp} 列{cols} 需{need}px 横滚max={hmax}"
          f"{'' if hmax == 0 else ' ←溢出!'}")

print("ALL PASS" if not FAILED["v"] else "FAILED")
sys.exit(0 if not FAILED["v"] else 1)
