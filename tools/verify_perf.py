# -*- coding: utf-8 -*-
"""⑦万张库性能审计(实测反馈10e, time-box): 5000张合成库——
timeline()查询/TimelinePage首次构建/二次刷新(签名跳过)/鸟种库列表/
作品集封面查询 逐项计时。阈值宽松(个人级硬件中位), 超阈值报FAIL并给
数据(网格虚拟化是否需要的依据)。不跑模型, 构建耗时主要在缩略图——
首刷缩略图按需生成(PIL), 5000张×新缓存=慢, 预生成256缓存后计时。"""
from __future__ import annotations

import os
import random
import shutil
import sys
import time
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
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    app = QApplication(sys.argv)
    app.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    from app import theme, i18n
    theme.apply_theme(app, "light")
    i18n.set_lang("zh")

    D = PROJ / "data/_perf_check"
    if D.exists():
        shutil.rmtree(D)
    D.mkdir(parents=True)
    from app.db import Library
    import app.media as media
    lib = Library(D)
    lib.fill_species()
    lib.conn.execute(
        "INSERT INTO batches(mode,dest,region_id,count) VALUES('copy',?,'CN',1)",
        (str(D / "src"),))
    bid = lib.conn.execute("SELECT id FROM batches LIMIT 1").fetchone()["id"]
    IMGS = [PROJ / "data/test_images" / x for x in
            ("Alcedo_atthis.jpg", "Anas_platyrhynchos.jpg",
             "Ardea_cinerea.jpg", "Cyanistes_caeruleus.jpg",
             "Passer_montanus.jpg")]
    codes = []
    for kw in ("%kingfisher%", "%mallard%", "%gray heron%", "%blue tit%",
               "%sparrow%"):
        r = lib.conn.execute(
            "SELECT code FROM species WHERE en LIKE ? LIMIT 1",
            (kw,)).fetchone()
        codes.append(r["code"] if r else "")
    rnd = random.Random(42)

    (D / "src").mkdir(parents=True, exist_ok=True)
    print("造 5000 张合成库…")
    t0 = time.time()
    pids = []
    for i in range(5000):
        p = D / "src" / f"p{i % 50}_{i}.jpg"
        if not p.exists():
            shutil.copy(IMGS[i % 5], p)
        pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                            p.stat().st_mtime, 0, 0, bid)
        y, mo, d, hh = rnd.choice((2024, 2025, 2026)), rnd.randint(1, 12), \
            rnd.randint(1, 28), rnd.randint(5, 19)
        lib.conn.execute(
            "INSERT OR REPLACE INTO exif(photo_id, dt_original) VALUES(?,?)",
            (pid, f"{y}-{mo:02d}-{d:02d} {hh:02d}:00:00"))
        if i % 3:   # 2/3有识别
            lib.conn.execute(
                "INSERT INTO records(photo_id,species_code,rank,confidence,"
                "source) VALUES(?,?,1,?,'detect')",
                (pid, codes[i % 5], round(rnd.uniform(0.4, 0.99), 2)))
        if i % 7 == 0:
            lib.set_aesthetic(pid, round(rnd.uniform(4, 9), 1))
        pids.append(pid)
    lib.conn.commit()
    print(f"  数据就绪 {time.time()-t0:.1f}s")

    # 预生成256缩略图缓存(排除首刷缩略图解码噪声, 单独测布局性能)
    t0 = time.time()
    n_cached = 0
    for r in lib.conn.execute("SELECT id, path, file_hash FROM photos"):
        tp = media.ensure_thumbnail(lib.root, r["path"], r["file_hash"], 256)
        n_cached += bool(tp)
    print(f"  缩略图缓存 {n_cached} 张 {time.time()-t0:.1f}s")

    from app.ui.timeline import TimelinePage
    t0 = time.time()
    rows = lib.timeline()
    t_sql = time.time() - t0
    check(t_sql < 2.0, f"timeline() 查询 {t_sql*1000:.0f}ms (阈值2000ms)")

    page = TimelinePage(lib, None)
    page.resize(1400, 900)
    page.show()
    t0 = time.time()
    page.refresh(force=True)
    for _ in range(10):
        app.processEvents()
    t_build = time.time() - t0
    check(t_build < 15.0,
          f"时间线首刷(5000张, 无折叠) {t_build:.2f}s (阈值15s)")
    t0 = time.time()
    page.refresh(force=False)   # 签名相同→应跳过
    for _ in range(5):
        app.processEvents()
    t_skip = time.time() - t0
    check(t_skip < 0.3, f"切回(签名跳过) {t_skip*1000:.0f}ms (阈值300ms)")
    t0 = time.time()
    page.refresh(force=True)    # 折叠后重刷
    for _ in range(10):
        app.processEvents()
    t_collapse = time.time() - t0
    check(t_collapse < 12.0,
          f"连拍折叠重刷 {t_collapse:.2f}s (阈值12s)")

    from app.ui.species_page import SpeciesPage

    class _W:
        worker = None
        assets = PROJ / "assets"
    sp = SpeciesPage(lib, _W())
    sp.resize(1400, 900)
    sp.show()
    t0 = time.time()
    sp.refresh()
    for _ in range(10):
        app.processEvents()
    t_sp = time.time() - t0
    check(t_sp < 6.0, f"鸟种库列表(11171种) {t_sp:.2f}s (阈值6s)")
    sp.close()

    # 作品集封面查询(无集→空) + 查重扫描规模
    t0 = time.time()
    n = lib.conn.execute(
        "SELECT COUNT(*) c FROM photos WHERE aesthetic IS NOT NULL"
    ).fetchone()["c"]
    print(f"  已评分 {n} 张 查询 {time.time()-t0:.0f}ms")

    page.close()
    print("\n结论: 数据已给出——网格虚拟化是否需要, 以真机大库滚动体感为准"
          "(offscreen计时不含GPU合成, 阈值只拦结构性退化)")
    print("FAIL" if FAILED["v"] else "ALL PASS")
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
