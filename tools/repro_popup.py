# -*- coding: utf-8 -*-
"""bug1复现: 地图页弹卡(左下角)第1个鸟点显示、切第2个不显示。

复刻app/main.py启动序列(演示库, 地图页), 依次_locate(1)/_locate(2)/_locate(1),
每步后多时点打印popup几何/可见性/布局子项, 并实拍窗口。
"""
from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

from PIL import ImageGrab

user32 = ctypes.windll.user32
TITLE = "鸟迹 · 鸟类照片管理"
OUT = PROJ / "data" / "_diag_popup"
OUT.mkdir(exist_ok=True)


def grab(tag):
    hwnd = user32.FindWindowW(None, TITLE)
    if not hwnd:
        print(tag, "NO WINDOW")
        return

    class RECT(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                    ("r", ctypes.c_long), ("b", ctypes.c_long)]
    rc = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))
    img = ImageGrab.grab(bbox=(rc.l, rc.t, rc.r, rc.b), all_screens=True)
    p = OUT / f"{tag}.png"
    img.save(p)
    print("saved", p, flush=True)


def popup_state(page):
    pop = page.popup
    lay = pop.layout()
    n_w = sum(1 for i in range(lay.count()) if lay.itemAt(i).widget()) if lay else -1
    return (f"visible={pop.isVisible()} geo={pop.x()},{pop.y()} "
            f"{pop.width()}x{pop.height()} layw={n_w} "
            f"children={len(pop.children())} raised_map={page.amap.geometry()}")


def step(page, sid, tag):
    print(f"--- locate spot {sid} ({tag}) ---", flush=True)
    page._locate(sid)
    for i in range(10):
        time.sleep(0.5)
        if i in (2, 5, 9):
            print(f"  t+{(i + 1) * 0.5:.0f}s {popup_state(page)}", flush=True)
    grab(f"{tag}_spot{sid}")


def main():
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

    from app import theme, i18n
    from app.db import Library
    from app.paths import assets_dir
    from app.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    lib = Library(PROJ / "data" / "demo_lib")
    theme.apply_theme(app, lib.get_setting("theme", "system"))
    i18n.set_lang(lib.get_setting("lang", "zh"))
    win = MainWindow(lib, assets_dir())
    win.show()
    win.switch_to("map")

    page_holder = {}

    def drive():
        page = win.pages.get("map")
        if page is None:
            print("no map page:", list(win.pages))
            app.quit()
            return
        page_holder["p"] = page
        print("spots:", list(page._spots.keys()), flush=True)
        spots = sorted(page._spots.keys())
        # 给WebEngine 12s建图; 然后弹卡三连
        QTimer.singleShot(12000, lambda: None)

        def seq():
            p = page_holder["p"]
            step(p, spots[0], "a")
            step(p, spots[1], "b")
            step(p, spots[0], "c")
            # 附加: 直接点marker路径(_on_marker_clicked, 模拟地图内点击)
            try:
                p._on_marker_clicked({"id": spots[1]})
                time.sleep(2)
                print("marker-click path:", popup_state(p), flush=True)
                grab("d_marker_spot%d" % spots[1])
            except Exception as e:
                print("marker path err:", e)
            app.quit()

        # 刷新一次保证_spots就绪
        page.refresh()
        QTimer.singleShot(12000, seq)

    QTimer.singleShot(1500, drive)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
