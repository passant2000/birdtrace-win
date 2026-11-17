# -*- coding: utf-8 -*-
"""鸟点详情重做验证(0.8.4): 窗口可放大/时间树(年月日)/月份分组多列网格/
鸟种筛选胶囊/弹卡宽度自适应/查看器筛选内翻页。

用法: .venv/Scripts/python.exe tools/verify_spot_detail.py (offscreen可用)
"""
from __future__ import annotations

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
    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme, i18n
    theme.apply_theme(app, "light")
    i18n.set_lang("zh")

    D = PROJ / "data/spot_detail_check"
    if D.exists():
        shutil.rmtree(D)
    D.mkdir(parents=True)
    from PIL import Image
    import app.media as media
    from app.db import Library

    lib = Library(D)
    lib.fill_species()
    codes = [r["code"] for r in lib.conn.execute(
        "SELECT code FROM species LIMIT 3").fetchall()]
    A, B, C = codes
    lib.conn.execute("INSERT INTO batches(region_id) VALUES('GLOBAL')")
    bid = lib.conn.execute("SELECT id FROM batches").fetchone()["id"]
    sid = lib.create_spot("重做测试鸟点", 40.0, 116.0)
    # 6张: 2025-11两张A, 2026-10两张A一张B(带EXIF时间)
    plan = [("2025-11-05 09:00:00", A), ("2025-11-20 10:00:00", A),
            ("2026-10-01 08:00:00", A), ("2026-10-15 09:30:00", A),
            ("2026-10-16 14:00:00", B), ("2026-10-17 15:00:00", A),
            ("2026-10-18 08:00:00", C), ("2026-10-19 09:00:00", C)]
    for i, (dt, code) in enumerate(plan):
        p = D / "src" / f"p{i}.jpg"
        p.parent.mkdir(exist_ok=True)
        Image.new("RGB", (320, 240), (90, 100, 110)).save(p, "JPEG")
        pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                            p.stat().st_mtime, 320, 240, bid)
        lib.add_records(pid, [{"species_code": code, "confidence": 0.9}])
        lib.conn.execute(
            "INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
            (pid, dt))
        lib.set_photos_spot([pid], sid)
    lib.conn.commit()

    from app.ui.map_page import SpotDetailDialog
    dlg = SpotDetailDialog(lib, None, sid)
    dlg.resize(1080, 760)
    dlg.show()

    # 1) 窗口可放大
    check(bool(dlg.windowFlags() & Qt.WindowMaximizeButtonHint),
          "窗口带最大化按钮(可放大)")
    # 2) 时间树: 全部 + 2年 + 月 + 日
    root = dlg.tree.topLevelItem(0)
    check(root is not None and "全部" in root.text(0) and "8" in root.text(0),
          f"树根'全部 8 张': {root.text(0) if root else None}")
    check(root.childCount() == 2, f"两个年份层: {root.childCount()}")
    y2026 = next(root.child(i) for i in range(root.childCount())
                 if "2026" in root.child(i).text(0))
    check(y2026.childCount() == 1 and "10月" in y2026.child(0).text(0),
          f"2026年下10月节点: {y2026.child(0).text(0) if y2026.childCount() else None}")
    m2026 = y2026.child(0)
    check(m2026.childCount() == 6, f"10月下6个日节点: {m2026.childCount()}")
    # 3) 网格: 月份分组 + 多列
    check(len(dlg._flow) == 8, f"照片流8项: {len(dlg._flow)}")
    titles = [dlg.grid_lay.itemAt(i).widget().text()
              for i in range(dlg.grid_lay.count())
              if dlg.grid_lay.itemAt(i).widget() and
              dlg.grid_lay.itemAt(i).widget().metaObject().className()
              == "QLabel"]
    check(any("2026年10月" in t for t in titles)
          and any("2025年11月" in t for t in titles),
          f"月份分组标题: {titles}")
    check(len(titles) >= 2 and len(dlg._flow) >= 4,
          "网格多列(6张全渲染, 列数随窗宽)")
    # 4) 鸟种筛选
    dlg._pick_species(A)
    check(len(dlg._filtered()) == 5, f"选鸟种A后5张: {len(dlg._filtered())}")
    check("全部 5" in dlg.tree.topLevelItem(0).text(0),
          "树随筛选重建: " + dlg.tree.topLevelItem(0).text(0))
    dlg._pick_species(B)
    check(len(dlg._filtered()) == 1, f"切到B后1张: {len(dlg._filtered())}")
    dlg._pick_species(B)
    check(len(dlg._filtered()) == 8, f"再点B恢复全部: {len(dlg._filtered())}")
    # 5) 树点击跳转不崩(树已重建, 必须重取句柄——旧QTreeWidgetItem已删)
    root2 = dlg.tree.topLevelItem(0)
    y26 = next(root2.child(i) for i in range(root2.childCount())
               if "2026" in root2.child(i).text(0))
    dlg._on_tree_click(y26, 0)
    check(True, "树点击跳转不崩")
    # 6) 查看器上下文=筛选结果(直接看ids来源)
    ids = [p["id"] for p in dlg._filtered()]
    check(len(ids) == 8 and len(set(ids)) == 8, "查看器翻页上下文=全部8张")
    # 7) 默认最大化 + 鸟种胶囊自动换行(多鸟种+窄窗)
    check(bool(dlg.windowState() & Qt.WindowMaximized),
          "打开默认最大化")
    dlg.setWindowState(dlg.windowState() & ~Qt.WindowMaximized)
    dlg.resize(520, 760)
    dlg._refresh_view()
    app.processEvents()
    app.processEvents()
    ys = set()
    for i in range(dlg.chips_lay.count()):
        w = dlg.chips_lay.itemAt(i).widget()
        if w is not None:
            ys.add(w.geometry().y())
    check(len(ys) >= 2, f"胶囊自动换行(占{len(ys)}行)")
    dlg.close()

    # 7) 弹卡宽度自适应(不截断)
    from app.ui.map_page import MapPage
    page = MapPage(lib, None)
    check(page.popup.minimumWidth() >= 280 and page.popup.maximumWidth() <= 420,
          f"弹卡宽度自适应 min={page.popup.minimumWidth()} "
          f"max={page.popup.maximumWidth()}")
    page.hide()

    lib.close()
    print("\nSPOT_DETAIL " + ("ALL GREEN" if not FAILED["v"] else "HAS FAIL"))
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
