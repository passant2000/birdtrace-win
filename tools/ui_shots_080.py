# -*- coding: utf-8 -*-
"""0.8.0 网站素材截图: 补齐演示库数据后抓取新功能界面。

与 ui_shots.py 不同: 本脚本走**真实窗口平台**(非offscreen)以获得系统
字体; 全部用 widget.grab()(不需前台), 日期弹层单独抓取后由调用方合成。

用法: .venv/Scripts/python.exe tools/ui_shots_080.py [light|dark]
产物: data/ui_shots/s080_*.png
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

THEME = sys.argv[1] if len(sys.argv) > 1 else "light"
SHOTS = PROJ / "data" / "ui_shots"


def settle(app, ms=350):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def grab(w, name):
    pm = w.grab()
    out = SHOTS / f"{name}.png"
    pm.save(str(out), "PNG")
    print("saved", out.name, pm.width(), "x", pm.height())


def prepare_demo_lib():
    """补 0.8.0 演示数据: 麻雀连拍组×3 / 低置信待复核 / 批次地区上海。"""
    from PIL import Image, ImageDraw
    from app.db import Library
    import app.media as media

    lib = Library(PROJ / "data" / "demo_lib")
    # 批次地区=上海(图鉴地区徽章用)
    lib.conn.execute("UPDATE batches SET region_id='CN-SH'")
    # 麻雀连拍组: 同种+同秒链(07:15:01/02), 复制原图微调像素
    sparrow = lib.conn.execute(
        "SELECT code FROM species WHERE sci='Passer montanus'").fetchone()
    code = sparrow["code"] if sparrow else "eutspa"
    src = PROJ / "data" / "demo_src" / "Passer_montanus.jpg"
    existing = lib.conn.execute(
        "SELECT COUNT(*) FROM photos WHERE path LIKE '%burst_demo%'"
    ).fetchone()[0]
    if not existing and src.exists():
        for i, (name, sec) in enumerate((("burst_demo_1", 1),
                                         ("burst_demo_2", 2))):
            out = PROJ / "data" / "demo_src" / f"{name}.jpg"
            im = Image.open(src).convert("RGB")
            d = ImageDraw.Draw(im)
            d.text((12 + i * 8, 12), f"+{i+1}", fill=(255, 255, 0))
            im.save(out, "JPEG", quality=92)
            pid = lib.add_photo(str(out), media.file_hash(out),
                                out.stat().st_size, out.stat().st_mtime,
                                im.width, im.height, 1)
            lib.conn.execute(
                "INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
                (pid, f"2024:06:03 07:15:{sec:02d}"))
            lib.add_records(pid, [{"species_code": code,
                                   "confidence": 0.91 + i * 0.01}])
    # 低置信待复核: 绿头鸭 0.30
    duck = lib.conn.execute(
        "SELECT p.id FROM photos p JOIN records r ON r.photo_id=p.id "
        "JOIN species s ON s.code=r.species_code "
        "WHERE s.sci='Anas platyrhynchos' LIMIT 1").fetchone()
    if duck:
        n = lib.conn.execute(
            "SELECT COUNT(*) FROM records WHERE photo_id=? AND confidence<0.4",
            (duck["id"],)).fetchone()[0]
        if not n:
            lib.add_records(duck["id"], [{"species_code": code,
                                          "confidence": 0.30}])
    lib.conn.commit()
    lib.regroup_bursts()
    n_grp = lib.conn.execute(
        "SELECT COUNT(DISTINCT group_id) FROM photos "
        "WHERE group_id IS NOT NULL").fetchone()[0]
    print("demo_lib ready: burst groups =", n_grp)
    return lib


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)          # 真实窗口平台 → 系统字体
    from app import theme, i18n
    theme.apply_theme(app, THEME)
    i18n.set_lang("zh")

    lib = prepare_demo_lib()
    from app.ui.main_window import MainWindow
    win = MainWindow(lib, PROJ / "assets")
    win.resize(1280, 820)
    win.show()
    settle(app, 600)

    # ---- 1. 时间线(连拍折叠 ×N + 每日一鸟) ----
    win.switch_to("timeline")
    settle(app, 700)
    if not win.pages["timeline"].burst_btn.isChecked():
        win.pages["timeline"].burst_btn.setChecked(True)
        win._toggle_collapse(True)
        settle(app, 600)
    tl = win.pages["timeline"]
    sb = tl.scroll.verticalScrollBar()
    sb.setValue(sb.maximum())          # 滚到连拍组所在位置
    settle(app, 400)
    grab(win, f"s080_timeline_{THEME}")

    # ---- 2. 导入页(地区卡橙框) ----
    win.switch_to("import")
    settle(app, 400)
    grab(win, f"s080_import_{THEME}")

    # ---- 3. 鸟种详情·图鉴(地区徽章+热力表) ----
    sp = win.pages["species"]
    win.switch_to("species")
    settle(app, 400)
    sp.current_code = "eutspa"
    sp.detail_tab = 1
    sp._show_detail("eutspa")
    settle(app, 500)
    grab(win, f"s080_species_dex_{THEME}")

    # ---- 4. 待复核(候选下拉+不是鸟) ----
    win.switch_to("review")
    settle(app, 400)
    grab(win, f"s080_review_{THEME}")

    # ---- 5. 关于页(v0.8.0) ----
    win.switch_to("about")
    settle(app, 400)
    grab(win, f"s080_about_{THEME}")

    # ---- 6. 导出向导(模板下拉+树形预览) ----
    from app.ui.export_dialog import ExportDialog
    ex = ExportDialog(lib, win)
    ex.show()
    settle(app, 400)
    ex.from_date.setDate(ex.from_date.minimumDate())   # 不限
    ex._apply_quick(3)                                  # 今年
    ex.tpl_combos[0].setCurrentIndex(ex._SEG_ITEMS.index("日期"))
    ex.tpl_combos[1].setCurrentIndex(ex._SEG_ITEMS.index("鸟名"))
    ex.tpl_combos[2].setCurrentIndex(ex._SEG_ITEMS.index("序号"))
    ex._update_preview()
    settle(app, 300)
    grab(ex, "s080_export_wizard")
    ex.close()

    # ---- 7. 批量分享卡 + 日期弹层合成 ----
    from app.ui.batch_share_dialog import BatchShareDialog
    bs = BatchShareDialog(lib, win)
    bs.show()
    settle(app, 400)
    bs._apply_quick(2)                                  # 本月
    settle(app, 200)
    grab(bs, "s080_batch_share")
    # 弹层: 抓弹层本体, 合成到对话框"日期从"下方
    bs.from_date._open_popup()
    settle(app, 300)
    pop = getattr(bs.from_date, "_popup", None)
    if pop is not None:
        grab(pop, "s080_date_popup_raw")
        pop.close()
    bs.close()

    # ---- 8. 查看器(top5候选下拉/按钮组) ----
    from app.ui.viewer import PhotoViewer
    ids = [r["id"] for r in lib.conn.execute(
        "SELECT id FROM photos ORDER BY id").fetchall()]
    v = PhotoViewer(lib, win, ids[0], ids)
    v.show()
    settle(app, 700)
    grab(v, f"s080_viewer_{THEME}")
    v.close()

    print("DONE", THEME)
    app.processEvents()


if __name__ == "__main__":
    main()
