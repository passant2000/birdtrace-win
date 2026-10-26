# -*- coding: utf-8 -*-
"""地图桥接探针v3: 端到端测 JS→Python 信号。"""
from __future__ import annotations

import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401,E402

from app import theme
from app.db import Library
from app.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    theme.apply_theme(app)
    lib = Library(PROJ / "data" / "demo_lib")
    win = MainWindow(lib, PROJ / "assets")
    win.show()
    win.switch_to("map")
    mp = win.pages["map"]
    amap = mp.amap
    page = amap.web.page()

    amap.center_moved.connect(
        lambda lat, lon, z: print(f"  << center_moved {lat:.3f},{lon:.3f},{z:.1f}",
                                  flush=True))
    amap.spot_clicked.connect(
        lambda d: print(f"  << spot_clicked {d.get('name')}", flush=True))
    amap.picked_wgs84.connect(
        lambda lat, lon: print(f"  << picked {lat:.4f},{lon:.4f}", flush=True))
    amap.mapReady.connect(lambda: print("  << mapReady", flush=True))

    def fire():
        print(f"before: ready={amap._ready} center={amap._center_state}", flush=True)
        page.runJavaScript(
            "String(typeof bridge) + ' mapReady=' + typeof bridge.mapReady"
            " + ' mapMoved=' + typeof bridge.mapMoved",
            lambda r: print("  bridge methods:", r, flush=True))
        page.runJavaScript("bridge.mapReady(); 'fired'", lambda r: print("  call:", r, flush=True))

        def after():
            print(f"after : ready={amap._ready} center={amap._center_state}", flush=True)
            app.quit()
        QTimer.singleShot(2500, after)

    QTimer.singleShot(12000, fire)
    app.exec()
    print("PROBE3 DONE")


if __name__ == "__main__":
    main()
