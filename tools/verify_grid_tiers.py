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
    pm = QPixmap_like = None
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

    lib.close()
    print()
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
