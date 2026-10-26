# -*- coding: utf-8 -*-
"""查看器回归: 图片自适应视口 + 最小化/最大化按钮 + 手动缩放不被抢。

用法: .venv/Scripts/python.exe tools/verify_viewer.py
输出: 断言结果 + data/ui_shots/viewer_fit_*.png 供目检。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

from PySide6.QtCore import Qt, QTimer, QEventLoop
from PySide6.QtWidgets import QApplication

SHOTS = PROJ / "data" / "ui_shots"
FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def fill_ratio(view):
    """图片在视口内的映射矩形相对视口的覆盖率(KeepAspectRatio下短边=1)。"""
    br = view._item.sceneBoundingRect()
    poly = view.mapFromScene(br)
    r = poly.boundingRect()
    vw, vh = view.viewport().width(), view.viewport().height()
    return (r.width() / vw, r.height() / vh, r.x(), r.y())


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    from app import theme
    theme.apply_theme(app, "light")
    from app.db import Library
    from app.ui.viewer import PhotoViewer

    lib = Library(PROJ / "data" / "demo_lib")
    ids = [r["id"] for r in lib.conn.execute(
        "SELECT id FROM photos ORDER BY id").fetchall()]
    assert ids, "demo_lib无照片"
    dlg = PhotoViewer(lib, None, ids[0], ids)
    dlg.show()

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    wait(600)

    print("[1] 窗口按钮")
    check(bool(dlg.windowFlags() & Qt.WindowMinMaxButtonsHint),
          "windowFlags含WindowMinMaxButtonsHint(标题栏有最小化/最大化)")
    check(bool(dlg.windowFlags() & Qt.WindowCloseButtonHint), "保留关闭按钮")

    print("[2] 首次打开即自适应(修复四周空白)")
    rw, rh, rx, ry = fill_ratio(dlg.view)
    check(max(rw, rh) > 0.95,
          f"打开时图片贴合视口 短边覆盖率max={max(rw, rh):.2f}(>0.95)")
    check(rw <= 1.05 and rh <= 1.05, f"不越界 w={rw:.2f} h={rh:.2f}")
    dlg.grab().save(str(SHOTS / "viewer_fit_1200.png"), "PNG")

    print("[3] 拉伸/缩小窗口跟随适配")
    dlg.resize(900, 700)
    wait(400)
    rw2, rh2, _, _ = fill_ratio(dlg.view)
    check(max(rw2, rh2) > 0.95, f"缩小到900x700仍贴合 max={max(rw2, rh2):.2f}")
    dlg.resize(1500, 950)
    wait(400)
    rw3, rh3, _, _ = fill_ratio(dlg.view)
    check(max(rw3, rh3) > 0.95, f"放大到1500x950仍贴合 max={max(rw3, rh3):.2f}")
    dlg.grab().save(str(SHOTS / "viewer_fit_1500.png"), "PNG")

    print("[4] 手动缩放后窗口变化不再抢视角, 双击恢复自适应")
    dlg.view._zoom_by(2.0)
    t_before = dlg.view.transform().m11()
    dlg.resize(1100, 800)
    wait(400)
    check(abs(dlg.view.transform().m11() - t_before) < 1e-6,
          "手动缩放2x后resize视角不变")
    dlg.view._user_zoomed = False
    dlg.view.fit()
    wait(200)
    rw4, rh4, _, _ = fill_ratio(dlg.view)
    check(max(rw4, rh4) > 0.95, "双击后恢复自适应")

    print()
    print("FAILED" if FAILED["v"] else "ALL PASS")
    app.quit()
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
