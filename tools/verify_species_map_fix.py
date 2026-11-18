# -*- coding: utf-8 -*-
"""v0.5.4两项bugfix验证:

1) 鸟种库首开慢: 详情页缩略图先即时渲染(缓存命中), 缺失的后台补齐逐张点亮;
   ensure_thumbnail优先从已有更大尺寸缓存降采样, 不再解码高像素原图。
2) 鸟点地图弹卡切换: _show_popup复用布局正确清空重建, 连续切换鸟点不再
   留下空白卡片(旧代码takeAt(0)返回None时AttributeError中断重建)。

用法: .venv/Scripts/python.exe tools/verify_species_map_fix.py
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB_DIR = PROJ / "data" / "speciesmap_check"
SRC_DIR = PROJ / "data" / "speciesmap_src"
N_PHOTOS = 60          # 模拟"图多"的鸟种
FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def make_copies():
    """同一张图做N个内容各异的副本(内容不同才不会被按hash去重)。"""
    from PIL import Image
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    base = Image.open(PROJ / "data/test_images/Anas_platyrhynchos.jpg").copy()
    px = base.load()
    files = []
    for i in range(N_PHOTOS):
        px[0, 0] = (i % 256, (i * 7) % 256, (i * 13) % 256)   # 改1像素→hash不同
        f = SRC_DIR / f"鸭_{i:03d}.jpg"
        base.save(f, quality=92)
        files.append(f)
    return files


def photo_grid(page):
    """详情页的照片网格(项数最多的QGridLayout)。"""
    from PySide6.QtWidgets import QGridLayout
    grids = [g for g in page.content.findChildren(QGridLayout)
             if g.count() > 0]
    return max(grids, key=lambda g: g.count())


def grid_items(grid):
    return [grid.itemAt(i).widget() for i in range(grid.count())
            if grid.itemAt(i).widget() is not None]


def lit_count(grid):
    return sum(1 for it in grid_items(grid)
               if it.pixmap is not None and not it.pixmap.isNull())


def main():
    if LIB_DIR.exists():
        shutil.rmtree(LIB_DIR)

    from PySide6.QtCore import QEventLoop, QObject, Qt, Signal
    from PySide6.QtWidgets import QApplication, QGridLayout, QWidget
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme
    theme.apply_theme(app, "light")
    from app.db import Library
    from app.core.importer import import_files
    from app.ai.pipeline import RecognitionPipeline, load_rgb
    from app.exif import month_of

    lib = Library(LIB_DIR)
    lib.fill_species()
    files = make_copies()
    import_files(lib, files, mode="ref", dest_root=None, region_id="CN")
    check(len(lib.pending_photo_ids()) == N_PHOTOS,
          f"导入 {N_PHOTOS} 张待识别")

    pipe = RecognitionPipeline(
        detector_path=str(PROJ / "assets/models/BirdTraceBirdDetector_FP32.onnx"),
        classifier_path=str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
        labels_path=str(PROJ / "assets/data/labels.json"),
        geo_prior_path=str(PROJ / "assets/data/geo_prior.sqlite"))
    for pid in lib.pending_photo_ids():
        photo, _ = lib.photo_detail(pid)
        recs = pipe.recognize(load_rgb(photo["path"]),
                              lib.region_for_photo(pid),
                              month_of(photo.get("dt_original"), 5))
        lib.add_records(pid, recs)
    pipe.close()
    overview = lib.species_overview()
    code = max(overview, key=lambda s: s["n"])["code"]
    n = next(s for s in overview if s["code"] == code)["n"]
    check(n == N_PHOTOS, f"最大鸟种 {code} 共 {n} 张(图多场景)")

    # ============ bug1: 鸟种详情首开 ============
    print("\n[bug1] 鸟种库详情页 · 首次打开")
    from app.ui.species_page import SpeciesPage

    class _WinStub(QWidget):
        worker = None
        pages = {}

    win = _WinStub()
    page = SpeciesPage(lib, win)
    page.resize(1200, 800)
    page.show()
    app.processEvents()

    t0 = time.perf_counter()
    page._open_detail(code)
    t_open = time.perf_counter() - t0
    app.processEvents()
    grid = photo_grid(page)
    items = grid_items(grid)
    n_now = lit_count(grid)
    check(len(items) == N_PHOTOS,
          f"网格一次渲染 {len(items)}/{N_PHOTOS} 项(不等待缩略图)")
    check(t_open < 1.5, f"首开耗时 {t_open*1000:.0f}ms (<1.5s)")

    deadline = time.time() + 30
    while time.time() < deadline:
        app.processEvents(QEventLoop.AllEvents, 50)
        if lit_count(grid) == N_PHOTOS:
            break
    check(lit_count(grid) == N_PHOTOS,
          f"后台补齐后 {lit_count(grid)}/{N_PHOTOS} 张全部点亮(首开即时见{n_now}张)")

    print("[bug1] 第二次打开(缓存全命中)")
    page._back()
    app.processEvents()
    t0 = time.perf_counter()
    page._open_detail(code)
    t_open2 = time.perf_counter() - t0
    app.processEvents()
    grid2 = photo_grid(page)
    check(len(grid_items(grid2)) == N_PHOTOS
          and lit_count(grid2) == N_PHOTOS,
          f"二次打开立即全部显示 {lit_count(grid2)}/{N_PHOTOS}")
    check(t_open2 < 1.5, f"二次打开 {t_open2*1000:.0f}ms")

    page._back()
    app.processEvents()
    check(page._thumb_items == {}, "返回列表后后台缩略图任务已作废")

    # ============ bug2: 地图弹卡切换 ============
    print("\n[bug2] 鸟点地图 · 弹卡连续切换")
    import app.ui.amap_view as amv

    class _StubAmap(QWidget):
        spot_clicked = Signal(dict)
        center_moved = Signal(float, float, float)
        picked_wgs84 = Signal(float, float)
        _center_state = (35.0, 105.0, 4.0)

        def __init__(self, lib, parent=None):
            super().__init__(parent)

        def ensure_keys(self):
            return False

        def set_spots(self, spots, fit=False):
            pass

        def focus_wgs84(self, *a):
            pass

        def fit_wgs84(self, *a):
            pass

        def set_pick(self, on):
            pass

    real_amap = amv.AmapView
    amv.AmapView = _StubAmap
    try:
        from app.ui.map_page import MapPage
        sid1 = lib.create_spot("测试点甲", 40.001, 116.301, "")
        sid2 = lib.create_spot("测试点乙", 40.002, 116.302, "")
        pids = [r["photo_id"] for r in lib.photos_of_species(code)]
        for i, pid in enumerate(pids):
            lib.set_photo_spot(pid, sid1 if i % 2 == 0 else sid2)

        mpage = MapPage(lib, win)
        mpage.resize(1280, 860)
        mpage.show()
        app.processEvents()

        def popup_texts():
            return " | ".join(w.text() for w in mpage.popup.findChildren(QWidget)
                              if w.metaObject().className() == "QLabel"
                              and w.parent() is mpage.popup)

        mpage._show_popup(sid1)
        app.processEvents()
        check(mpage.popup.isVisible() and mpage.popup.layout() is not None
              and mpage.popup.layout().count() > 0,
              "第一个鸟点弹卡正常显示")
        check("测试点甲" in popup_texts(), "弹卡内容为鸟点甲信息")

        mpage._show_popup(sid2)
        app.processEvents()
        lay = mpage.popup.layout()
        check(mpage.popup.isVisible() and lay is not None and lay.count() > 0,
              "切换后弹卡仍有内容(不是空白卡片)")
        check("测试点乙" in popup_texts() and "测试点甲" not in popup_texts(),
              "弹卡内容已更新为鸟点乙(旧内容不残留)")

        ok_switch = True
        for k in range(7):
            mpage._on_marker_clicked({"id": sid1 if k % 2 == 0 else sid2})
            app.processEvents()
            if not (mpage.popup.isVisible() and mpage.popup.layout().count() > 0):
                ok_switch = False
        texts = popup_texts()
        check(ok_switch, "marker路径连续切换7次弹卡始终有内容")
        check("测试点甲" in texts and "测试点乙" not in texts,
              "第7次(甲)内容正确且无乙残留")

        mpage._hide_popup()
        check(not mpage.popup.isVisible(), "× 关闭后弹卡隐藏")
    finally:
        amv.AmapView = real_amap

    # ============ bug3: 返回列表恢复滚动位置 ============
    print("\n[bug3] 鸟种库 · 返回列表恢复滚动位置")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QScrollArea
    # 39个新鸟种挂到既有照片 → 列表40卡(CARD_COLS=5, 8行)可滚动
    extra = [r["code"] for r in lib.conn.execute(
        "SELECT code FROM species WHERE code != 'mallar3' LIMIT 39")]
    pid0 = lib.conn.execute("SELECT id FROM photos LIMIT 1").fetchone()[0]
    for c in extra:
        # 0.8.6语义: add_records对已有人工痕迹照片整组跳过(pid0此前被
        # 改判测试动过)——追加语义用append_record(0.8.6修的同款路径)
        lib.append_record(pid0, {"species_code": c, "confidence": 0.9,
                                 "source": "verify"})
    overview = lib.species_overview()
    check(len(overview) == 1 + len(extra),
          f"列表 {len(overview)} 种(1+{len(extra)})")
    page2 = SpeciesPage(lib, win)
    page2.resize(1200, 800)
    page2.show()
    page2.refresh()              # 真实应用=切页时refresh, 直建页面需手动刷
    app.processEvents()
    page2.resize(1201, 800)      # offscreen顶层widget不吃LayoutRequest(真实
    app.processEvents()          # GUI子页面正常), 微调尺寸强制QScrollArea重算
    bar = page2.scroll.verticalScrollBar()
    check(bar.maximum() > 0, f"列表可滚动(max={bar.maximum()}px)")
    target = min(400, bar.maximum())
    bar.setValue(target)
    page2._open_detail(overview[0]["code"])
    app.processEvents()
    check(page2.current_code == overview[0]["code"] and page2.back_btn.isVisible(),
          "进入详情")
    page2._back()
    loop = QEventLoop()          # 恢复走singleShot(0), 等事件循环转一拍
    QTimer.singleShot(50, loop.quit)
    loop.exec()
    app.processEvents()
    check(bar.value() == min(target, bar.maximum()),
          f"返回后滚动位置恢复在原处 ({bar.value()}px, 期望{target}px)")
    page2._open_detail(overview[1]["code"])
    app.processEvents()
    page2._back()
    loop2 = QEventLoop()
    QTimer.singleShot(50, loop2.quit)
    loop2.exec()
    app.processEvents()
    check(bar.value() == min(target, bar.maximum()),
          f"再次进出详情仍恢复同一位置 ({bar.value()}px)")

    # 列表态refresh(切页回来/识别完成刷新场景)保持位置
    bar.setValue(200)
    page2.refresh()
    loop3 = QEventLoop()
    QTimer.singleShot(50, loop3.quit)
    loop3.exec()
    app.processEvents()
    check(bar.value() == 200, f"列表态refresh后位置保持 ({bar.value()}px)")

    # 搜索词变更=新列表, 回到顶部(预期行为, 不恢复旧位置)
    page2.search.setText("鸭")     # 匹配绿头鸭( Mallard ), 其余39种不匹配
    app.processEvents()
    loop4 = QEventLoop()
    QTimer.singleShot(50, loop4.quit)
    loop4.exec()
    check("1" in page2.title.text() or bar.value() == 0,
          f"搜索后列表过滤 ({page2.title.text()})")
    check(bar.value() == 0, "新搜索词列表从头看(不恢复旧位置)")
    page2.search.clear()
    loop5 = QEventLoop()
    QTimer.singleShot(50, loop5.quit)
    loop5.exec()

    # 详情内tab切换恢复(概览→图鉴→概览)
    code0 = max(overview, key=lambda s: s["n"])["code"]   # 60张图的鸭: 内容超屏
    page2._open_detail(code0)
    app.processEvents()
    page2.resize(1202, 800)        # offscreen range重算quirk, 同列表场景
    app.processEvents()
    dbar = page2.scroll.verticalScrollBar()
    dmax = dbar.maximum()
    check(dmax > 0, f"详情概览可滚动(max={dmax}px)")
    d_target = min(500, dmax)
    dbar.setValue(d_target)
    page2._tab_changed(1)          # → 图鉴
    page2.resize(1203, 800)
    loop6 = QEventLoop()
    QTimer.singleShot(50, loop6.quit)
    loop6.exec()
    app.processEvents()
    page2._tab_changed(0)          # → 概览(恢复)
    page2.resize(1204, 800)
    loop7 = QEventLoop()
    QTimer.singleShot(50, loop7.quit)
    loop7.exec()
    app.processEvents()
    check(page2.detail_tab == 0 and dbar.value() == d_target,
          f"tab切换回概览位置恢复 ({dbar.value()}px, 期望{d_target}px)")

    # 详情内refresh(查看器关闭/库刷新场景)保持位置
    dbar.setValue(min(300, dbar.maximum()))
    d_target2 = dbar.value()
    page2.refresh()
    page2.resize(1205, 800)
    loop8 = QEventLoop()
    QTimer.singleShot(50, loop8.quit)
    loop8.exec()
    app.processEvents()
    check(page2.current_code == code0 and dbar.value() == d_target2,
          f"详情refresh后位置保持 ({dbar.value()}px, 期望{d_target2}px)")

    print()
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")
    shutil.rmtree(SRC_DIR, ignore_errors=True)
    shutil.rmtree(LIB_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
