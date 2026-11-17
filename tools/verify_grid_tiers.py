# -*- coding: utf-8 -*-
"""0.8.5 网格档位验证: PhotoGridItem tile几何(默认120=历史尺寸兼容)/
grid_tile_of持久化回退/make_grid_tier_control写库+回调/列数公式换算。"""
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
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from app import theme, i18n
    theme.apply_theme(app, "light")
    i18n.set_lang("zh")

    D = PROJ / "data/grid_tiers_check"
    if D.exists():
        shutil.rmtree(D)
    D.mkdir(parents=True)
    from app.db import Library
    lib = Library(D)

    print("\n[1] PhotoGridItem tile几何")
    from app.theme.widgets import (GRID_TIERS, PhotoGridItem, grid_tile_of,
                                   make_grid_tier_control)
    it = PhotoGridItem(None, label="2026-11-17")
    check((it.width(), it.height()) == (120, 140),
          f"默认tile=120→120×140(历史尺寸) {it.width()}×{it.height()}")
    it2 = PhotoGridItem(None, label="x", tile=180)
    check((it2.width(), it2.height()) == (180, 180 + 30),
          f"tile180→180×210 {it2.width()}×{it2.height()}")
    it3 = PhotoGridItem(None, label="x", tile=320)
    check((it3.width(), it3.height()) == (320, 320 + 53),
          f"tile320→320×373(标签带53) {it3.width()}×{it3.height()}")
    # 信纸式整图可见(0.8.5实测修: 用户要Windows超大图标式不裁切)
    from PySide6.QtGui import QColor, QPixmap
    pmp = QPixmap(200, 100)
    pmp.fill(QColor(20, 200, 20))
    itb = PhotoGridItem(pmp, tile=132)
    d = itb._scaled_disp()
    check(d is not None and d.width() == 132 and d.height() == 66,
          f"横图整图可见(信纸式132×66) "
          f"实际{d.width() if d else 0}×{d.height() if d else 0}")
    check(it3.tile == 320, "tile属性可读(网格重建用)")

    print("\n[2] grid_tile_of 持久化/回退")
    check(grid_tile_of(lib) == 132, "未设→回退132(≈0.8.4视觉)")
    lib.set_setting("grid_tile", "240")
    check(grid_tile_of(lib) == 240, "已设240→240")
    lib.set_setting("grid_tile", "999")
    check(grid_tile_of(lib) == 132, "非法999→回退132")
    lib.set_setting("grid_tile", "132")

    print("\n[3] 档位控件: 写库+回调+初值对齐")
    calls = []
    seg = make_grid_tier_control(lib, lambda: calls.append(1))
    check(seg is not None, "控件构造")
    seg.changed.emit(GRID_TIERS.index(320))     # 模拟点击"特大"
    check(lib.get_setting("grid_tile") == "320" and len(calls) == 1,
          "切换特大→写库320+触发刷新回调")
    seg2 = make_grid_tier_control(lib, lambda: None)
    check(grid_tile_of(lib) == 320, "新控件初值读库=320(三页一致)")

    print("\n[4] 列数公式换算(与页面同式)")
    tile = grid_tile_of(lib)
    vw = 1920
    cols_spot = max(3, vw // (tile + 16))
    check(cols_spot == 1920 // 336, f"鸟点详情320档cols={cols_spot}")
    lib.set_setting("grid_tile", "132")
    tile = grid_tile_of(lib)
    check(max(2, (1000 - 8) // (tile + 10)) == 6,
          f"时间线132档1000px视口cols=6 "
          f"实际{max(2, (1000 - 8) // (tile + 10))}")

    print("\n[5] 时间线档位切换功能级(0.8.5实测修: stale tile+签名吞刷新)")
    from PIL import Image as _Img
    from app import media
    from app.ui.timeline_page import TimelinePage
    lib.fill_species()
    code2 = lib.conn.execute(
        "SELECT code FROM species LIMIT 1").fetchone()["code"]
    tp = D / "t1.jpg"
    _Img.new("RGB", (400, 300), (90, 130, 90)).save(tp)
    pid2 = lib.add_photo(str(tp), media.file_hash(tp), tp.stat().st_size,
                         tp.stat().st_mtime, 400, 300, 0)
    lib.add_records(pid2, [{"species_code": code2, "confidence": 0.9}])
    lib.conn.execute(
        "INSERT OR REPLACE INTO exif(photo_id, dt_original) VALUES(?, ?)",
        (pid2, "2026-11-16 10:00:00"))
    lib.conn.commit()
    page = TimelinePage(lib, None)
    page.resize(1400, 900)
    page.show()
    app.processEvents()
    items = list(page._grid_items.values())
    check(bool(items), "时间线渲染出网格项")
    if items:
        w0 = items[0].width()
        lib.set_setting("grid_tile", "320")
        page._tier_changed()
        app.processEvents()
        items2 = list(page._grid_items.values())
        check(bool(items2) and items2[0].width() == 320,
              f"档位切换生效 {w0}→{items2[0].width() if items2 else 0}")
        d2 = items2[0]._scaled_disp() if items2 else None
        check(d2 is not None and d2.width() == 320 and d2.height() == 240,
              f"时间线横图整图可见(320×240) "
              f"实际{d2.width() if d2 else 0}×{d2.height() if d2 else 0}")
    page.hide()

    print("\n[6] 鸟点详情档位切换功能级(0.8.5实测修)")
    from PySide6.QtWidgets import QWidget
    from app.ui.map_page import SpotDetailDialog
    sid = lib.create_spot("测试点", 31.0, 121.0)
    lib.conn.execute("UPDATE photos SET spot_id=? WHERE id=?", (sid, pid2))
    lib.conn.commit()
    sdlg = SpotDetailDialog(lib, None, sid)
    sdlg.show()
    app.processEvents()

    def _thumbs(host):
        return [w for w in host.findChildren(QWidget) if hasattr(w, "tile")]

    t1 = _thumbs(sdlg.grid_holder)
    check(bool(t1), "鸟点详情渲染出缩略图")
    if t1:
        sw0 = t1[0].width()
        lib.set_setting("grid_tile", "180")
        sdlg._tier_changed()
        app.processEvents()
        t2 = _thumbs(sdlg.grid_holder)
        # 旧网格项deleteLater在offscreen可能滞后, 判"存在180新项"即证重建生效
        check(any(w.width() == 180 for w in t2),
              f"鸟点档位切换生效(出现180项) "
              f"{sw0}→{sorted({w.width() for w in t2})}")
    sdlg.hide()

    lib.close()
    print()
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
