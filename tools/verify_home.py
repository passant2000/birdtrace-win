# -*- coding: utf-8 -*-
"""UI重设计c7 首页功能级验证:
默认启动页=首页 / 每日一鸟横幅(同日确定性, 自时间线搬入) / 最近导入卡 /
快速入口+档案速览 / 新功能导览卡(关闭写seen_tour=1不再显示) /
时间线不再含每日一鸟横幅。真窗口平台跑; 不跑模型, 约10~20秒。"""
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
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme, i18n
    theme.apply_theme(app, "light")
    i18n.set_lang("zh")

    D = PROJ / "data/_home_check"
    if D.exists():
        shutil.rmtree(D)
    D.mkdir(parents=True)
    from app.db import Library
    import app.media as media
    lib = Library(D)
    lib.fill_species()
    lib.conn.execute(
        "INSERT INTO batches(mode, dest, region_id, count) "
        "VALUES('copy',?,'CN',3)", (str(D / "src"),))
    row = lib.conn.execute("SELECT id FROM batches LIMIT 1").fetchone()
    IMGS = ["Alcedo_atthis.jpg", "Anas_platyrhynchos.jpg", "Ardea_cinerea.jpg"]
    for i, img in enumerate(IMGS):
        p = D / f"b{i}.jpg"
        shutil.copy(PROJ / "data/test_images" / img, p)
        pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                            p.stat().st_mtime, 0, 0, row["id"])
        lib.conn.execute(
            "INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
            (pid, f"2026-05-20 0{i + 8}:00:00"))
    lib.conn.commit()

    from app.ui.main_window import MainWindow
    win = MainWindow(lib, PROJ / "assets")
    win.show()
    for _ in range(5):
        app.processEvents()

    print("[1] 默认启动页")
    check(win.stack.currentWidget() is win.pages["home"],
          "默认启动页=首页(c7)")
    page = win.pages["home"]
    for _ in range(5):
        app.processEvents()

    from PySide6.QtWidgets import QPushButton
    texts = lambda ps: " ".join(w.text() for w in ps if hasattr(w, "text"))
    labels = page.content.findChildren(QLabel)
    t_all = " ".join(w.text() for w in labels)
    btn_all = " ".join(w.text() for w in page.content.findChildren(QPushButton))

    print("[2] 新功能导览卡")
    check("新功能导览" in t_all, "导览卡显示(seen_tour未置位)")
    check("组内对比" in t_all or "选片工作流" in t_all, "导览条目渲染")
    # 关闭 → seen_tour=1 → 刷新后不再显示
    got = [w for w in page.content.findChildren(QPushButton)
           if "不再显示" in w.text()]
    check(bool(got), "导览卡有「知道了」按钮")
    if got:
        got[0].click()
        for _ in range(3):
            app.processEvents()
        check(lib.get_setting("seen_tour", "") == "1", "关闭写 seen_tour=1")
        page.refresh()
        for _ in range(5):
            app.processEvents()
        labels = page.content.findChildren(QLabel)
        t_all = " ".join(w.text() for w in labels)
        check("新功能导览" not in t_all, "关闭后导览卡不再显示")

    print("[3] 每日一鸟横幅(自时间线搬入)")
    check("每日一鸟" in t_all or "文化故事" in t_all,
          "首页含每日一鸟横幅(文化资产可用时)")
    from app.ui.home_page import daily_bird_card
    c1 = daily_bird_card(lib, win)
    c2 = daily_bird_card(lib, win)
    check((c1 is None) == (c2 is None), "每日一鸟构造稳定")
    if c1 is not None:
        l1 = " ".join(w.text() for w in c1.findChildren(QLabel))
        l2 = " ".join(w.text() for w in c2.findChildren(QLabel))
        check(l1 == l2, "同日确定性(两次构造同文案)")

    print("[4] 时间线不再含横幅")
    win.switch_to("timeline")
    for _ in range(5):
        app.processEvents()
    tl_labels = " ".join(w.text() for w in
                         win.pages["timeline"].content.findChildren(QLabel))
    check("每日一鸟" not in tl_labels, "时间线已无每日一鸟横幅(迁至首页)")

    print("[5] 最近导入卡")
    win.switch_to("home")
    for _ in range(5):
        app.processEvents()
    labels = page.content.findChildren(QLabel)
    t_all = " ".join(w.text() for w in labels)
    check("最近导入" in t_all, "最近导入卡渲染")
    check("3 张" in t_all, f"批量计数显示 ({t_all[:100]})")

    print("[6] 快速入口+档案速览")
    btn_all = " ".join(w.text() for w in page.content.findChildren(QPushButton))
    check("导入照片" in btn_all and "时间线" in btn_all, f"快速入口按钮 ({btn_all[:80]})")
    check("生涯鸟种" in btn_all, "档案速览(生涯鸟种)")

    win.close()
    print("\n" + ("FAIL" if FAILED["v"] else "ALL PASS"))
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
