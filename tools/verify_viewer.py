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

    print("[5] top5候选下拉框(点名字改鸟功能已移除, 2026-11-05用户)")
    import json as _json
    from PySide6.QtWidgets import QComboBox, QLabel
    top5_db = _json.loads(lib.conn.execute(
        "SELECT top5_json FROM records WHERE photo_id=? AND rank=1",
        (ids[0],)).fetchone()[0])
    combos = dlg.findChildren(QComboBox)
    items = [combos[0].itemText(i) for i in range(combos[0].count())] \
        if combos else []
    check(len(items) == len(top5_db) and len(items) >= 2,
          f"下拉框=识别top5 ({items})")
    check(any("✓" in it for it in items), "当前鸟种带✓标记")
    # 鸟种名=纯展示标签: 点名字弹候选改鸟功能已按用户要求移除(2026-11-05)——
    # 无手型光标/无tooltip/无mousePressEvent
    rec0 = lib.photo_detail(ids[0])[1][0]
    check(rec0.get("top5_json"), "photo_detail经视图带回top5_json")
    s0 = lib.species_info(rec0["species_code"])
    sname0 = s0["cn"] if s0 else rec0["species_code"]
    titles = [lb for lb in dlg.findChildren(QLabel)
              if lb.text().startswith(sname0)]
    check(bool(titles), "鸟种名标签存在")
    if titles:
        t0 = titles[0]
        check(t0.cursor().shape() != Qt.PointingHandCursor
              and t0.toolTip() == "",
              "鸟种名不可点(无手型光标/无tooltip)")
    # 下拉候选仍是改鸟种通道(demo_lib共享fixture: 测完还原)
    if len(top5_db) >= 2:
        from PySide6.QtCore import QObject, Signal

        class _W(QObject):
            library_changed = Signal()
        dlg.win = _W()          # _confirm会发win.library_changed
        c2 = top5_db[1]["code"]
        dlg._confirm(rec0["record_id"], c2)
        eff = lib.conn.execute(
            "SELECT COALESCE(confirmed_code, species_code) FROM records "
            "WHERE id=?", (rec0["record_id"],)).fetchone()[0]
        check(eff == c2, f"下拉候选改鸟种仍可用 ({eff}=={c2})")
        lib.conn.execute(
            "UPDATE records SET confirmed_code=NULL, reviewed=0 WHERE id=?",
            (rec0["record_id"],))
        lib.conn.commit()

    print("[6] v_records老库视图迁移(缺top5_json自动重建)")
    import shutil
    MIG = PROJ / "data/viewer_mig_check"
    if MIG.exists():
        shutil.rmtree(MIG)
    lib2 = Library(MIG)
    lib2.conn.execute("DROP VIEW v_records")   # 降级成旧定义
    lib2.conn.execute(
        "CREATE VIEW v_records AS SELECT r.id AS record_id, r.photo_id, "
        "r.species_code, r.rank, r.confidence, r.source, r.reviewed "
        "FROM records r JOIN photos p ON p.id = r.photo_id")
    lib2.conn.commit()
    lib2.close()
    lib3 = Library(MIG)                        # 重开→_migrate应重建
    vcols = {r["name"] for r in lib3.conn.execute(
        "PRAGMA table_info(v_records)")}
    check("top5_json" in vcols and "eff_code" in vcols,
          f"老库视图自动重建含top5_json ({sorted(vcols)[:4]}…)")
    lib3.close()

    print()
    print("FAILED" if FAILED["v"] else "ALL PASS")
    app.quit()
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
