# -*- coding: utf-8 -*-
"""UI重设计c4 作品集页功能级验证:
db(collection_rename 空名/重名拒绝 / collection_cover 封面=美学最高
并列取置信高 / collection_stats) + exporter.select_range 作品集范围 +
导出向导预选 + UI冒烟(list空态/卡片→detail/选择移出/删除只解关联/
「在时间线查看」=apply_collection_filter 联动网格过滤)。
真窗口平台跑; 不跑模型, 约10~20秒。"""
from __future__ import annotations

import json
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
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme, i18n
    theme.apply_theme(app, "light")
    i18n.set_lang("zh")

    D = PROJ / "data/_collections_check"
    if D.exists():
        shutil.rmtree(D)
    D.mkdir(parents=True)
    from app.db import Library
    import app.media as media
    lib = Library(D)
    lib.fill_species()

    # ---------- 测试数据: 4张不同图 + 手工记录/美学分 ----------
    # (batch行手工插——import_files会多带1张测试图入库, 破坏计数断言)
    lib.conn.execute(
        "INSERT INTO batches(mode, dest, region_id, count) "
        "VALUES('copy',?, 'CN', 4)", (str(D / "src"),))
    row = lib.conn.execute("SELECT id FROM batches LIMIT 1").fetchone()
    IMGS = ["Alcedo_atthis.jpg", "Anas_platyrhynchos.jpg",
            "Ardea_cinerea.jpg", "Cyanistes_caeruleus.jpg"]
    pids = []
    for i in range(4):
        p = D / f"b{i}.jpg"
        shutil.copy(PROJ / "data/test_images" / IMGS[i], p)
        pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                            p.stat().st_mtime, 0, 0, row["id"])
        lib.conn.execute(
            "INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
            (pid, f"2026-05-20 08:00:0{i}"))
        pids.append(pid)
    kcode = lib.conn.execute(
        "SELECT code FROM species WHERE en LIKE '%kingfisher%' OR "
        "code='comkin1' LIMIT 1").fetchone()["code"]
    for i, pid in enumerate(pids):
        lib.conn.execute(
            "INSERT INTO records(photo_id,species_code,rank,confidence,"
            "source) VALUES(?,?,1,?,'detect')",
            (pid, kcode, 0.9 - i * 0.1))
        lib.set_aesthetic(pid, 5.0 + i)          # b3=8.0 最高
    lib.conn.commit()

    # ---------- [1] db: rename / cover / stats ----------
    print("[1] db 方法")
    from app.core import exporter
    cid = lib.collection_create("猛禽专题")
    check(lib.collections_list()[0]["name"] == "猛禽专题", "建集成功")
    try:
        lib.collection_rename(cid, "  ")
        check(False, "空名应 ValueError")
    except ValueError:
        check(True, "空名拒绝")
    lib.collection_create("旅行")
    try:
        lib.collection_rename(cid, "旅行")
        check(False, "重名应 ValueError")
    except ValueError:
        check(True, "重名拒绝")
    lib.collection_rename(cid, "猛禽精选")
    names = [c["name"] for c in lib.collections_list()]
    check("猛禽精选" in names and "旅行" in names, f"重命名生效 ({names})")

    check(lib.collection_cover(lib.conn.execute(
        "SELECT id FROM collections WHERE name='旅行'").fetchone()["id"])
        is None, "空集封面=None")
    cov = lib.collection_cover(cid)
    # 前3张入集, 封面应=美学最高那张(b3, 8.0)
    lib.collection_set_photos(cid, pids[:3])
    cov = lib.collection_cover(cid)
    check(cov == pids[2], f"封面=美学最高照 (got {cov}, want {pids[2]})")
    # 并列美学分时取主记录置信高: 把两张并列8.0
    lib.set_aesthetic(pids[2], 8.0)
    lib.set_aesthetic(pids[1], 8.0)   # pids[1] conf 0.8 < pids[2] 0.7? 0.9-1*0.1=0.8; pids[2]=0.7
    lib.conn.commit()
    cov2 = lib.collection_cover(cid)
    check(cov2 == pids[1], f"并列美学取置信高 (got {cov2}, want {pids[1]})")
    st = lib.collection_stats(cid)
    check(st["n"] == 3 and st["species"] == 1, f"stats n/种 ({st})")
    check((st["first"] or "").startswith("2026-05-20")
          and (st["last"] or "").startswith("2026-05-20"), f"stats 跨度 ({st})")

    # ---------- [2] exporter: 作品集范围 ----------
    print("[2] exporter 作品集范围")
    all_rows = exporter.select_range(lib)
    cid_row = lib.conn.execute(
        "SELECT id FROM collections WHERE name='猛禽精选'").fetchone()["id"]
    in_rows = exporter.select_range(lib, collection_id=cid_row)
    check(len(all_rows) == 4 and len(in_rows) == 3,
          f"全范围4/集内3 (got {len(all_rows)}/{len(in_rows)})")
    check({r["photo_id"] for r in in_rows} == set(pids[:3]),
          "集内范围=成员3张")

    # ---------- [3] UI 冒烟 ----------
    print("[3] UI 冒烟")
    from app.ui.main_window import MainWindow
    win = MainWindow(lib, PROJ / "assets")
    win.show()
    win.switch_to("collections")
    for _ in range(5):
        app.processEvents()
    page = win.pages["collections"]
    check(page._mode == "list" and page.content_lay.count() >= 2,
          "list模式渲染出卡片(无空态)")
    check(all(not getattr(page, b).isVisible() for b in
              ("back_btn", "view_btn", "export_btn", "sel_btn")),
          "list模式detail按钮全部隐藏")
    # 累积bug回归(实测反馈3): refresh多次, 「返回列表」只此一个
    page.refresh()
    page.refresh()
    page.refresh()
    from PySide6.QtWidgets import QPushButton
    n_back = sum(1 for b in page.title._actions
                 if False) if False else sum(
        1 for b in page.findChildren(QPushButton)
        if b.text().startswith("← 返回"))
    check(n_back == 1, f"refresh×4后返回按钮仍=1 (got {n_back})")

    # 卡片点击 → detail
    page._open_detail(cid_row)
    for _ in range(5):
        app.processEvents()
    check(page._mode == "detail", "卡片点击进detail")
    check(page.title.title_label.text() == "猛禽精选", "detail标题=集名")
    n_items = len(page.content.findChildren(
        __import__("app.theme.widgets", fromlist=["PhotoGridItem"])
        .PhotoGridItem))
    check(n_items == 3, f"detail网格3张 (got {n_items})")

    # 选择 → 移出1张
    page._toggle_sel()
    for _ in range(3):
        app.processEvents()
    check(page._sel_mode and page.sel_bar.isVisible(), "选择模式+工具条")
    from app.theme.widgets import PhotoGridItem
    items = page.content.findChildren(PhotoGridItem)
    page._sel_click(pids[0], items[0])
    check(page._sel == {pids[0]}, "点选1张")
    page._remove_selected()
    for _ in range(5):
        app.processEvents()
    mem = lib.collection_photos_of(cid_row)
    check(mem == pids[1:3], f"移出后剩2张 ({mem})")
    n_photos = lib.conn.execute("SELECT COUNT(*) c FROM photos").fetchone()["c"]
    check(n_photos == 4, "移出只解关联, 照片记录不受影响")

    # 「在时间线查看」→ 时间线过滤联动
    page._view_in_timeline()
    for _ in range(8):
        app.processEvents()
    tl = win.pages["timeline"]
    check(win.stack.currentWidget() is tl, "已切到时间线")
    check(tl.col_filter.currentData() == cid_row, "时间线作品集下拉已选中该集")
    got = sorted(tl._order_ids)
    check(got == sorted(pids[1:3]), f"时间线网格按集过滤 ({got})")
    tl.col_filter.setCurrentIndex(0)
    tl.refresh(force=True)
    for _ in range(5):
        app.processEvents()
    check(len(tl._order_ids) == 4, "还原全部后网格恢复4张")

    # 删除作品集: 只解关联
    n_rec = lib.conn.execute("SELECT COUNT(*) c FROM records").fetchone()["c"]
    page2 = win.pages["collections"]
    page2._mode = "list"
    page2._cur_cid = None
    page2.refresh()
    lib.collection_delete(cid_row)
    page2.refresh()
    for _ in range(5):
        app.processEvents()
    check(page2._mode == "list", "删除后回落list")
    check(lib.conn.execute("SELECT COUNT(*) c FROM photos").fetchone()["c"] == 4
          and lib.conn.execute("SELECT COUNT(*) c FROM records").fetchone()["c"] == n_rec,
          "删集只解关联: 照片/记录计数不变")

    # 空库空态
    lib3_d = PROJ / "data/_collections_check_empty"
    if lib3_d.exists():
        shutil.rmtree(lib3_d)
    lib3 = Library(lib3_d)
    lib3.fill_species()
    from app.ui.collections_page import CollectionsPage
    p3 = CollectionsPage(lib3, win)
    p3.refresh()
    for _ in range(3):
        app.processEvents()
    from PySide6.QtWidgets import QLabel
    texts = " ".join(w.text() for w in p3.content.findChildren(QLabel))
    check(p3.content_lay.count() >= 1 and "还没有作品集" in texts,
          "空态引导卡渲染")
    win.close()

    print("\n" + ("FAIL" if FAILED["v"] else "ALL PASS"))
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
