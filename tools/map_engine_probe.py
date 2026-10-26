# -*- coding: utf-8 -*-
"""地图引擎探针: 启动主窗口切到地图页, 查询JS侧状态与marker数, 截图落盘。

用法: .venv/Scripts/python -u tools/map_engine_probe.py [engine]
  engine: maplibre(默认) | amap
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401,E402

from app import theme

ENGINE = sys.argv[1] if len(sys.argv) > 1 else "maplibre"


def main():
    app = QApplication(sys.argv)
    theme.apply_theme(app, "light")
    from app.db import Library
    from app.ui.main_window import MainWindow

    shutil.rmtree(PROJ / "data/test_lib", ignore_errors=True)
    shutil.copytree(PROJ / "data/demo_lib", PROJ / "data/test_lib")
    lib = Library(PROJ / "data/test_lib")
    lib.set_setting("map_engine", ENGINE)
    win = MainWindow(lib, PROJ / "assets")
    win.show()
    win.resize(1280, 820)
    win.raise_()
    win.activateWindow()
    win.switch_to("map")
    amap = win.pages["map"].amap

    amap.mapReady.connect(lambda: print("<< mapReady", flush=True))
    amap.center_moved.connect(
        lambda la, lo, z: print(f"<< center {la:.3f},{lo:.3f} z{z:.0f}", flush=True))
    amap.picked_wgs84.connect(
        lambda la, lo: print(f"<< picked {la:.4f},{lo:.4f}", flush=True))

    def probe():
        page = amap.web.page()
        page.runJavaScript(
            'String(typeof maplibregl)+" / style:"+(map?String(map.getStyle().name):"-")'
            '+" / center:"+map.getCenter().lat.toFixed(3)+","+map.getCenter().lng.toFixed(3)'
            '+" / zoom:"+map.getZoom().toFixed(1)',
            lambda r: print("JS:", r, flush=True))
        page.runJavaScript(
            'document.querySelectorAll(".maplibregl-marker").length+'
            '"/"+document.querySelectorAll(".amap-marker").length+" markers"',
            lambda r: print("markers:", r, flush=True))

        def snap():
            from PIL import ImageGrab
            g = win.frameGeometry()
            dpr = win.devicePixelRatioF()
            win.raise_(); win.activateWindow()
            img = ImageGrab.grab(
                bbox=(int(g.left() * dpr), int(g.top() * dpr),
                      int(g.right() * dpr), int(g.bottom() * dpr)),
                all_screens=True)
            out = PROJ / "data" / "ui_shots" / f"engine_{ENGINE}.png"
            img.save(out)
            import numpy as np
            crop = img.crop((int(img.width * 0.32), int(img.height * 0.2),
                             int(img.width * 0.9), int(img.height * 0.7)))
            colors = crop.convert("RGB").getcolors(maxcolors=400000)
            print(f"截图 {out.name} 地图区色数:", len(colors) if colors else -1,
                  flush=True)
            print("PROBE DONE", flush=True)
            app.quit()

        QTimer.singleShot(1200, snap)

    QTimer.singleShot(16000, probe)
    app.exec()


if __name__ == "__main__":
    main()
