# -*- coding: utf-8 -*-
"""时间线刷新保持滚动位置验证(识别完成/库变化触发refresh不跳顶)。

背景: refresh()整页重建曾把滚动条归零——用户导入180张后一边等识别一边
浏览时间线, 识别完成刷新直接跳回顶部。同类修复见鸟种库(verify_species_map_fix)。

用法: .venv/Scripts/python.exe tools/verify_scroll_restore.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB_DIR = PROJ / "data" / "tl_scroll_check"
SRC_DIR = PROJ / "data" / "tl_scroll_src"
N_PHOTOS = 40
FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def make_copies():
    """40张内容各异的副本, EXIF日期分属3个月份(时间线多分组)。"""
    from PIL import Image
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    base = Image.open(PROJ / "data/test_images/Anas_platyrhynchos.jpg").copy()
    px = base.load()
    files = []
    for i in range(N_PHOTOS):
        px[0, 0] = (i % 256, (i * 7) % 256, (i * 13) % 256)
        exif = base.getexif()
        ifd = exif.get_ifd(0x8769)
        dt = f"2024:0{i % 3 + 1}:15 08:{i:02d}:00"
        exif[306] = dt                    # DateTime
        ifd[36867] = dt                   # DateTimeOriginal
        f = SRC_DIR / f"鸭_{i:03d}.jpg"
        base.save(f, exif=exif, quality=92)
        files.append(f)
    return files


def main():
    for d in (LIB_DIR, SRC_DIR):
        if d.exists():
            shutil.rmtree(d)

    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QEventLoop, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QWidget
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme
    theme.apply_theme(app, "light")
    from app.core.importer import import_files
    from app.db import Library

    lib = Library(LIB_DIR)
    lib.fill_species()
    files = make_copies()
    import_files(lib, files, mode="ref", dest_root=None, region_id="CN")
    months = {r[0] for r in lib.conn.execute(
        "SELECT substr(dt_original,1,7) FROM exif WHERE dt_original IS NOT NULL")}
    check(len(months) >= 3, f"EXIF日期分属{len(months)}个月份组")

    from app.ui.timeline_page import TimelinePage

    class _Win(QWidget):
        worker = None
        pages = {}

    win = _Win()
    page = TimelinePage(lib, win)
    page.resize(1200, 800)
    page.show()
    app.processEvents()

    def rebuild_settle():
        page.refresh()
        app.processEvents()
        page.content.adjustSize()   # offscreen range重算quirk, 真实GUI不需要
        app.processEvents()

    rebuild_settle()
    bar = page.scroll.verticalScrollBar()
    check(bar.maximum() > 0, f"时间线可滚动(max={bar.maximum()}px)")

    target = min(400, bar.maximum())
    bar.setValue(target)
    rebuild_settle()             # 模拟识别完成触发的库刷新
    loop = QEventLoop()
    QTimer.singleShot(80, loop.quit)
    loop.exec()
    app.processEvents()
    check(bar.value() == target,
          f"识别完成刷新后位置保持 ({bar.value()}px, 期望{target}px)")

    # 回到顶部再刷新: 保持顶部
    bar.setValue(0)
    rebuild_settle()
    loop2 = QEventLoop()
    QTimer.singleShot(80, loop2.quit)
    loop2.exec()
    app.processEvents()
    check(bar.value() == 0, "顶部刷新保持顶部")

    # ---- 窗口放大: 列数自适应扩展(曾固定构建时列数不扩展) ----
    cols_before = page._cur_cols
    page.resize(2000, 900)
    loop3 = QEventLoop()
    QTimer.singleShot(450, loop3.quit)   # resize防抖250ms + 重建
    loop3.exec()
    app.processEvents()
    page.content.adjustSize()
    app.processEvents()
    check(page._cur_cols > cols_before,
          f"放大窗口列数扩展 {cols_before}→{page._cur_cols}")
    check(bar.value() == 0, "重排后位置保持顶部")

    # ---- 全选: 就地更新选中态(签名跳过曾使全选无反应) ----
    page._toggle_select()        # 进入选择模式
    app.processEvents()
    page._select_all()
    app.processEvents()
    sel_items = sum(1 for it in page._grid_items.values() if it.selected)
    check(len(page._selected) == N_PHOTOS and sel_items == N_PHOTOS,
          f"全选: 集合{len(page._selected)}张, 界面{sel_items}项高亮")
    check("全不选" in page.all_btn.text(), "按钮切换为全不选")
    page._select_all()           # 再点=全不选
    app.processEvents()
    sel_items2 = sum(1 for it in page._grid_items.values() if it.selected)
    check(not page._selected and sel_items2 == 0, "全不选就地清空")

    shutil.rmtree(SRC_DIR, ignore_errors=True)
    shutil.rmtree(LIB_DIR, ignore_errors=True)
    print()
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
