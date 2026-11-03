# -*- coding: utf-8 -*-
"""时间树+切页计时验证(用完可删): 真库副本上跑。"""
import ctypes
import sys
import time
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

from PIL import ImageGrab

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

from app import theme, i18n
from app.db import Library
from app.paths import assets_dir
from app.ui.main_window import MainWindow

user32 = ctypes.windll.user32
TITLE = "鸟迹 · 鸟类照片管理"
OUT = PROJ / "data" / "_diag_tree"
OUT.mkdir(exist_ok=True)

app = QApplication(sys.argv)
lib = Library(PROJ / "data" / "_lag_lib")
theme.apply_theme(app, "system")
i18n.set_lang("zh")
win = MainWindow(lib, assets_dir())
win.show()


def grab(tag):
    hwnd = user32.FindWindowW(None, TITLE)

    class R(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                    ("r", ctypes.c_long), ("b", ctypes.c_long)]
    rc = R()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))
    ImageGrab.grab(bbox=(rc.l, rc.t, rc.r, rc.b), all_screens=True).save(OUT / f"{tag}.png")
    print("saved", tag, flush=True)


tl = win.pages["timeline"]


def seq():
    win.switch_to("timeline")
    app.processEvents()
    QTimer.singleShot(1800, seq2)  # 等布局就绪再操作

def seq2():
    app.processEvents()
    # 1. 时间树结构
    top = tl.tree_nav.topLevelItemCount()
    print(f"树: 顶层(年) {top} 个", flush=True)
    y0 = tl.tree_nav.topLevelItem(0)
    print(f"  首年: {y0.text(0)!r} 月数={y0.childCount()}", flush=True)
    m0 = y0.child(0)
    print(f"  首月: {m0.text(0)!r} 日数={m0.childCount()}", flush=True)
    d0 = m0.child(0)
    print(f"  首日: {d0.text(0)!r}", flush=True)
    # 2. 点击跳转: 展开首年首月, 点最后一天
    tl.tree_nav.expandItem(y0)
    tl.tree_nav.expandItem(m0)
    app.processEvents()
    last_d = m0.child(m0.childCount() - 1)
    key = last_d.data(0, Qt.UserRole)
    print(f"  点末日: {last_d.text(0)!r} key={key}", flush=True)
    before = tl.scroll.verticalScrollBar().value()
    tl._on_tree_click(last_d, 0)
    app.processEvents()
    after = tl.scroll.verticalScrollBar().value()
    print(f"  跳转: {before} -> {after} (应增大)", flush=True)
    # 3. 反向高亮
    tl._sync_tree_current()
    cur = tl.tree_nav.currentItem()
    print(f"  高亮联动: {cur.text(0) if cur else None!r}", flush=True)
    grab("tree_nav")
    # 4. 鸟种→地图切换计时(prewarm在+6s已跑)
    win.switch_to("species")
    app.processEvents()
    sp = win.pages["species"]
    items = sp.lib.species_overview()
    sp._open_detail(items[0]["code"])
    app.processEvents()
    t0 = time.time()
    win.switch_to("map")
    app.processEvents()
    print(f"切地图(预热后): {(time.time()-t0)*1000:.0f}ms", flush=True)
    app.quit()


QTimer.singleShot(9000, seq)   # 等9s: 预热(6s)已完成
sys.exit(app.exec())
