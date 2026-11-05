# -*- coding: utf-8 -*-
"""0.8.0-test2 反馈修复验证: 开始导入确认弹窗全流程 + 地区卡样式。

用户反馈(2026-11-05):
  [1] 点击「开始导入」没有任何反应(0.8.0-test2 实机) —— 复现并验证修复
  [2] 地区卡橙色框难看 —— 只保留卡片单一外框, 子控件(标题/提示)不得带框

用法: .venv/Scripts/python.exe tools/verify_import_confirm.py
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


def make_img(path: Path, seed: int = 0):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (320, 240), (60 + seed * 7 % 100, 100, 140))
    d = ImageDraw.Draw(im)
    d.ellipse([60 + seed, 50, 260, 190], fill=(230, 200 - seed % 50, 120))
    d.text((10, 10), f"seed{seed}", fill=(255, 255, 255))
    im.save(path, "JPEG")


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt, QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox, QFrame, QLabel
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme, i18n
    theme.apply_theme(app, "light")
    i18n.set_lang("zh")

    LIB = PROJ / "data/import_confirm_check"
    if LIB.exists():
        shutil.rmtree(LIB)
    (LIB / "src").mkdir(parents=True)
    from app.db import Library
    lib = Library(LIB)
    lib.fill_species()

    from app.ui.main_window import MainWindow
    win = MainWindow(lib, PROJ / "assets")
    page = win.pages["import"]

    # ---- [1] 开始导入全流程: 真点按钮, 记录确认弹窗 ----
    print("\n[1] 开始导入全流程(点按钮→确认→导入线程→完成)")
    imgs = []
    for i in range(2):
        p = LIB / "src" / f"img{i}.jpg"
        make_img(p, i)
        imgs.append(p)
    page._set_sources(imgs)
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()  # 预览线程起跑(不依赖)
    check(page.go_btn.isEnabled(), "选完来源后按钮可用")

    # 地区选到 中国·上海(CN-SH; regions.json用eBird式省级码)
    page.country_combo.setCurrentIndex(page.country_combo.findData("CN"))
    page.sub_combo.setCurrentIndex(page.sub_combo.findData("CN-SH"))
    check(page.current_region() == "CN-SH", f"current_region=CN-SH (got {page.current_region()})")

    calls = {}
    # 桩掉识别启动与导入后挂点模态框: 本脚本只验导入链路本身
    # (start_recognition会拉真模型; BatchSpotDialog.exec()在offscreen永久阻塞)
    win.start_recognition = lambda *a, **k: None
    import app.ui.spot_dialog as _sd
    _real_bsd = _sd.BatchSpotDialog

    class _StubBSD:
        def __init__(self, *a, **k):
            self.applied = False

        def exec(self):
            return 0

    _sd.BatchSpotDialog = _StubBSD
    _real_q = QMessageBox.question

    def fake_question(parent, title, text, *a, **k):
        calls["title"] = title
        calls["text"] = text
        return QMessageBox.StandardButton.Yes

    QMessageBox.question = staticmethod(fake_question)
    tb = []

    def hook(etype, val, tback):
        tb.append(f"{etype.__name__}: {val}")

    sys.excepthook = hook
    page.go_btn.click()   # 真点击 → _start_import
    sys.excepthook = sys.__excepthook__
    check(not tb, f"点击无异常 ({tb})")
    check("title" in calls, "确认弹窗已弹出")
    if "text" in calls:
        check("上海" in calls["text"],
              f"弹窗正文含地区显示 ({calls['text'].splitlines()[0]})")

    # 等导入线程完成
    end = {"t": 0}
    t0 = QTimer()
    t0.setInterval(100)

    def pump():
        end["t"] += 1
        if page.import_thread is None or not page.import_thread.isRunning():
            t0.stop()
    t0.timeout.connect(pump)
    loop2 = QEventLoop()
    t0.timeout.connect(lambda: loop2.quit() if not t0.isActive() else None)
    t0.start()
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(lambda: (t0.stop(), loop2.quit()))
    deadline.start(15000)
    loop2.exec()
    app.processEvents()
    n = lib.conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    check(n == 2, f"2张照片入库 (got {n})")
    check(lib.get_setting("default_region", "") == "CN-SH",
          f"default_region 已存 CN-SH (got {lib.get_setting('default_region', '')})")
    check("导入完成" in page.status.text(), f"状态栏报完成 ({page.status.text()})")
    QMessageBox.question = _real_q

    # No 路径: 弹窗返回 No → 不导入
    print("\n[2] 确认弹窗点 No → 中止导入")
    p3 = LIB / "src" / "img2.jpg"
    make_img(p3, 9)
    page._set_sources([p3])
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
    page.go_btn.click()
    app.processEvents()
    n2 = lib.conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    check(n2 == 2, f"No 后不新增 (got {n2})")
    QMessageBox.question = _real_q
    _sd.BatchSpotDialog = _real_bsd

    # ---- [3] 地区卡样式: 只有卡片本体带边框 ----
    print("\n[3] 地区卡样式(单一外框, 子控件不带框)")
    # 卡片保持#Card名(背景仍走全局QSS), 从国家下拉向上找宿主卡
    card = page.country_combo.parentWidget()
    while card is not None and card.objectName() != "Card":
        card = card.parentWidget()
    check(card is not None and card is not page, "地区卡可寻址(objectName=Card)")
    if card is not None:
        ss = card.styleSheet()
        check("QFrame#Card" in ss, f"样式表选择器限定#Card本身 ({ss!r})")
        check("QFrame{" not in ss and "QLabel" not in ss,
              "选择器不裸匹配子QFrame/QLabel(0.8.0-test2满屏橙框根因)")
        title = [lb for lb in card.findChildren(QLabel) if lb.objectName() == "CardTitle"]
        check(bool(title), "卡内标题存在")
        if title:
            check("border" not in (title[0].styleSheet() or ""),
                  f"标题标签无独立边框 ({title[0].styleSheet()!r})")
        # 渲染grab: 顶边中点=橙色边框, 卡内部不得有大片橙(旧版每个标签都有橙框)
        card.resize(card.sizeHint().expandedTo(card.minimumSizeHint()))
        pm = card.grab().toImage()

        def is_orange(px):
            r, g, b = px.red(), px.green(), px.blue()
            return r > 200 and 120 < g < 190 and b < 90

        mid_top = pm.pixelColor(pm.width() // 2, 1)
        check(is_orange(mid_top), f"卡片顶边中点是橙色边框 ({mid_top.name()})")
        inner = pm.pixelColor(pm.width() // 2, pm.height() // 2)
        check(not is_orange(inner), f"卡内部无橙色块 ({inner.name()})")
        Path(PROJ / "data").mkdir(exist_ok=True)
        pm.save(str(PROJ / "data/region_card_preview.png"))

    print("\n" + ("FAIL" if FAILED["v"] else "ALL PASS"))
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
