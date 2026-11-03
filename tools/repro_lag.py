# -*- coding: utf-8 -*-
"""卡顿复现计时(用完可删): 鸟种库→开鸟种→切地图, 分段计时。"""
import sys
import time
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

app = QApplication(sys.argv)
lib = Library(PROJ / "data" / "_lag_lib")
theme.apply_theme(app, lib.get_setting("theme", "system"))
i18n.set_lang(lib.get_setting("lang", "zh"))
win = MainWindow(lib, assets_dir())
win.show()

T = {}


def stamp(k):
    T[k] = time.time()
    print(f"[{k}] {time.time() - T.get('_t0', time.time()):+.0f}ms 累计", flush=True)


def seq():
    app.processEvents()
    stamp("_t0")
    # 1. 切鸟种库
    stamp("s1-切到鸟种库.start")
    win.switch_to("species")
    app.processEvents()
    stamp("s1-done")
    # 2. 打开第一个鸟种详情
    sp = win.pages["species"]
    items = sp.lib.species_overview()
    stamp("s2-打开鸟种详情.start")
    sp._open_detail(items[0]["code"])
    app.processEvents()
    stamp("s2-done")
    # 3. 切到地图(首次: 含WebEngine初始化)
    stamp("s3-切到地图.start(首次)")
    t0 = time.time()
    win.switch_to("map")
    app.processEvents()
    stamp("s3-done")
    print(f"  s3 耗时: {(time.time()-t0)*1000:.0f}ms")
    # 4. 再切回鸟种库再切地图(第二次, WebEngine已就绪)
    win.switch_to("species")
    app.processEvents()
    stamp("s4-二切地图.start")
    t0 = time.time()
    win.switch_to("map")
    app.processEvents()
    stamp("s4-done")
    print(f"  s4 耗时: {(time.time()-t0)*1000:.0f}ms")
    # 5. 第三切(热)
    win.switch_to("timeline")
    app.processEvents()
    t0 = time.time()
    win.switch_to("map")
    app.processEvents()
    print(f"  s5 三切地图耗时: {(time.time()-t0)*1000:.0f}ms")
    app.quit()


QTimer.singleShot(2500, seq)
sys.exit(app.exec())
