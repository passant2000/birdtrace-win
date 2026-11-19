# -*- coding: utf-8 -*-
"""UI冒烟: 启动主窗口, 遍历各页面截图后退出。

地图页含QWebEngineView, 其内容无法用widget.grab()拍到(独立进程合成),
统一用 PIL ImageGrab 抓真实屏幕区域(需窗口在前台)。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

# WebEngine要求: 属性必须在QApplication创建前设置, 模块先于app导入
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401,E402

from app import theme
from app.db import Library

SHOTS = PROJ / "data" / "ui_shots"
THEME = __import__("os").environ.get("BT_THEME", "light")


def screen_grab(win, name):
    """按窗口屏幕区域抓真实屏幕(物理像素), WebEngine内容只有这条路能拍到。"""
    from PIL import ImageGrab
    # 真实屏幕抓取可能被其他窗口遮挡, 抓前强制置前
    win.show()
    win.raise_()
    win.activateWindow()
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(200, loop.quit)
    loop.exec()
    g = win.frameGeometry()
    dpr = win.devicePixelRatioF()
    bbox = (int(g.left() * dpr), int(g.top() * dpr),
            int(g.right() * dpr), int(g.bottom() * dpr))
    img = ImageGrab.grab(bbox=bbox, all_screens=True)
    out = SHOTS / f"{name}.png"
    img.save(out)
    print("saved", out)


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    # 主题必须先于UI模块import应用(内联颜色常量在import时绑定)
    theme.apply_theme(app, THEME)
    from app.ui.main_window import MainWindow
    lib = Library(PROJ / "data" / "demo_lib")
    win = MainWindow(lib, PROJ / "assets")
    win.resize(1280, 820)
    win.show()
    win.raise_()
    win.activateWindow()

    pages = ["home", "timeline", "import", "species", "map", "review", "life", "yearbook",
             "about", "settings"]
    state = {"i": 0}

    def grab_widget(w, name):
        pm = w.grab()
        out = SHOTS / f"{name}.png"
        pm.save(str(out), "PNG")
        print("saved", out)

    def shot_next():
        i = state["i"]
        if i >= len(pages):
            grab_tail()
            return
        key = pages[i]
        win.switch_to(key)
        state["i"] = i + 1

        def grab():
            if key == "map":
                mp = win.pages["map"]
                print("MAPSTATE ready:", mp.amap._ready,
                      "spots:", len(mp._spots), flush=True)
                screen_grab(win, key)
            else:
                grab_widget(win, key)
            QTimer.singleShot(400, shot_next)

        # 地图页先等JS加载+首帧再拍; 其余页400ms足够
        QTimer.singleShot(12000 if key == "map" else 400, grab)

    def grab_tail():
        # 批量鸟点对话框(导入完成后的询问)
        from app.ui.spot_dialog import BatchSpotDialog
        pids = [r["id"] for r in lib.conn.execute(
            "SELECT id FROM photos ORDER BY id LIMIT 6").fetchall()]
        bdlg = BatchSpotDialog(lib, win, pids,
                               "这批照片都没有GPS信息，无法自动归组。\n"
                               "如果是同一个地方拍的，在这里一次挂好最省事。", win)
        bdlg.show()

        def snap_batch():
            grab_widget(bdlg, "batch_spot")
            bdlg.close()
            grab_tail2()
        QTimer.singleShot(1000, snap_batch)

    def grab_tail2():
        # 鸟点详情对话框
        first_spot = lib.conn.execute(
            "SELECT id FROM spots ORDER BY id LIMIT 1").fetchone()
        if first_spot:
            from app.ui.map_page import SpotDetailDialog
            dlg = SpotDetailDialog(lib, win, first_spot["id"], win)
            dlg.show()

            def snap_detail():
                grab_widget(dlg, "spots_detail")
                dlg.close()

                from app.ui.viewer import PhotoViewer
                ids = [r["id"] for r in lib.conn.execute(
                    "SELECT id FROM photos ORDER BY id").fetchall()]
                if not ids:
                    app.quit()
                    return
                vdlg = PhotoViewer(lib, win, ids[0], ids)
                vdlg.show()
                vdlg.resize(1200, 780)

                def grab_dlg():
                    vdlg.view.resetTransform()
                    vdlg.view.scale(2.5, 2.5)
                    grab_widget(vdlg, "viewer_zoom")
                    vdlg.view.fit()
                    grab_widget(vdlg, "viewer")
                    from app.ui.share_dialog import ShareDialog
                    sd = ShareDialog(lib, win, ids[0])
                    sd.show()
                    sd.resize(560, 800)

                    def grab_sd():
                        grab_widget(sd, "share")
                        app.quit()
                    QTimer.singleShot(1200, grab_sd)
                QTimer.singleShot(1200, grab_dlg)
            QTimer.singleShot(1200, snap_detail)
        else:
            app.quit()

    QTimer.singleShot(2500, shot_next)  # 等首屏加载
    app.exec()
    print("UI SMOKE DONE")


if __name__ == "__main__":
    main()
