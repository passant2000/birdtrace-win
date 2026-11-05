# -*- coding: utf-8 -*-
"""侧边栏导航拖动重排验证(2026-11-06 用户反馈"拖动不顺畅"重做后)。

覆盖:
  [1] 真实鼠标事件: 按住按钮拖到列表底部/顶部, 一次到位(不是一格一格)
  [2] 小幅移动(<5px)不算拖动, 点击照常切页
  [3] 拖到按钮外松手: 下一次点击不被误吞
  [4] 顺序持久化 + 重启恢复

用法: .venv/Scripts/python.exe tools/verify_nav_drag.py
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme, i18n
    theme.apply_theme(app, "light")
    i18n.set_lang("zh")

    LIB = PROJ / "data/nav_drag_check"
    if LIB.exists():
        shutil.rmtree(LIB)
    LIB.mkdir(parents=True)
    from app.db import Library
    lib = Library(LIB)
    lib.fill_species()
    from app.ui.main_window import MainWindow
    win = MainWindow(lib, PROJ / "assets")
    win.resize(1200, 820)
    win.show()
    for _ in range(5):
        app.processEvents()

    def order(w):
        items = [(w._nav_lay.indexOf(b), k)
                 for k, b in w._nav_buttons.items()
                 if w._nav_lay.indexOf(b) >= 0]
        return [k for _i, k in sorted(items)]

    def press(btn, pos=None):
        p = pos or btn.rect().center()
        g = btn.mapToGlobal(p)
        ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(p), QPointF(g),
                         Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(btn, ev)

    def move(btn, global_y: int):
        # 用按钮本地坐标表达目标全局Y(水平保持中心)
        g = btn.mapToGlobal(btn.rect().center())
        g = type(g)(g.x(), global_y)
        local = btn.mapFromGlobal(g)
        ev = QMouseEvent(QEvent.MouseMove, QPointF(local), QPointF(g),
                         Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(btn, ev)

    def release(btn, global_y: int | None = None):
        g = btn.mapToGlobal(btn.rect().center())
        if global_y is not None:
            g = type(g)(g.x(), global_y)
        local = btn.mapFromGlobal(g)
        ev = QMouseEvent(QEvent.MouseButtonRelease, QPointF(local),
                         QPointF(g), Qt.LeftButton, Qt.NoButton,
                         Qt.NoModifier)
        QApplication.sendEvent(btn, ev)

    print("\n[1] 拖到列表底部(一次到位)")
    before = order(win)
    tl = win._nav_buttons["timeline"]
    last_k = before[-1]
    last_btn = win._nav_buttons[last_k]
    target_y = last_btn.mapToGlobal(last_btn.rect().center()).y() + 10
    press(tl)
    move(tl, target_y)
    app.processEvents()
    check(order(win)[-1] == "timeline",
          f"timeline已到最后一位 ({order(win)})")
    release(tl, target_y)
    app.processEvents()
    check(order(win)[-1] == "timeline", f"松手后顺序={order(win)}")

    print("\n[2] 拖回顶部 + 小幅移动不算拖动")
    first_k = order(win)[0]
    first_btn = win._nav_buttons[first_k]
    top_y = first_btn.mapToGlobal(first_btn.rect().center()).y() - 10
    press(tl)
    move(tl, top_y)
    app.processEvents()
    check(order(win)[0] == "timeline", f"拖到顶部一次到位 ({order(win)})")
    release(tl, top_y)
    app.processEvents()

    # 小幅移动(3px): 不应进入拖动, 点击照常切页
    win.switch_to("about")
    app.processEvents()
    btn = win._nav_buttons["timeline"]
    y0 = btn.mapToGlobal(btn.rect().center()).y()
    press(btn)
    move(btn, y0 + 3)
    release(btn, y0 + 3)
    app.processEvents()
    win._nav_click("timeline")   # 模拟clicked(off屏合成事件不产生clicked)
    app.processEvents()
    check(win.stack.currentWidget() is win.pages["timeline"],
          "小幅移动后点击照常切页")

    print("\n[2b] 拖动后松手仍在按钮上: 不误切页")
    win.switch_to("about")
    app.processEvents()
    b1 = win._nav_buttons["review"]
    y1 = b1.mapToGlobal(b1.rect().center()).y()
    press(b1)
    move(b1, y1 + 10)
    release(b1, y1 + 10)         # 仍在按钮内 → QPushButton会发clicked
    app.processEvents()
    check(win.stack.currentWidget() is win.pages["about"],
          "拖动后的clicked被吞掉(未误切页)")
    import time as _t
    _t.sleep(0.05)
    app.processEvents()
    win._nav_click("review")
    app.processEvents()
    check(win.stack.currentWidget() is win.pages["review"],
          "随后正常点击仍生效")

    print("\n[3] 拖到按钮外松手不吞下一次点击")
    b2 = win._nav_buttons["stats"]
    g0 = b2.mapToGlobal(b2.rect().center())
    press(b2)
    move(b2, g0.y() + 120)       # 拖出去
    app.processEvents()
    release(b2, g0.y() + 120)    # 在按钮外松手(无clicked)
    app.processEvents()
    import time
    time.sleep(0.05)
    app.processEvents()
    win.switch_to("about")
    win._nav_click("species")
    app.processEvents()
    check(win.stack.currentWidget() is win.pages["species"],
          "拖到外面松手后, 下一次点击正常生效")

    print("\n[4] 顺序持久化 + 重启恢复")
    saved = lib.get_setting("nav_order", "")
    live = order(win)
    check(saved.split(",") == live, f"顺序已存 ({saved})")
    win.close()
    win2 = MainWindow(lib, PROJ / "assets")
    win2.show()
    for _ in range(5):
        app.processEvents()
    check(order(win2) == live, f"重启后顺序恢复 ({order(win2)})")
    win2.close()

    print("\n" + ("FAIL" if FAILED["v"] else "ALL PASS"))
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
