# -*- coding: utf-8 -*-
"""美学评分(最美鸟照)端到端验证: 迁移/评分器/排序/封面/回填线程/十八图/长图。

用法: .venv/Scripts/python.exe tools/verify_aesthetic.py
前置: assets/models/AestheticTOPIQ_fp16.onnx (tools/export_aesthetic_onnx.py产出)
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB_DIR = PROJ / "data/aesthetic_check"
MODEL = PROJ / "assets/models/AestheticTOPIQ_fp16.onnx"
FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def main():
    if not MODEL.exists():
        print("模型不存在, 先跑 tools/export_aesthetic_onnx.py")
        sys.exit(1)
    if LIB_DIR.exists():
        shutil.rmtree(LIB_DIR)

    from PIL import Image, ImageFilter
    from PySide6.QtCore import QEventLoop, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QGridLayout, QLabel, QWidget
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme
    theme.apply_theme(app, "light")
    from app.db import Library
    from app.core.importer import import_files
    from app.ai.pipeline import RecognitionPipeline, load_rgb
    from app.exif import month_of

    # ---- 1. 评分器语义 ----
    print("\n[1] 评分器")
    from app.ai.aesthetic import AestheticScorer
    sc = AestheticScorer(MODEL)
    img = PROJ / "data/test_images/Anas_platyrhynchos.jpg"
    blur = PROJ / "data/aesthetic_blur_probe.jpg"
    Image.open(img).convert("RGB").filter(
        ImageFilter.GaussianBlur(8)).save(blur, quality=90)
    t0 = time.perf_counter()
    s_sharp = sc.score_file(img)
    s_blur = sc.score_file(blur)
    dt = time.perf_counter() - t0
    check(1.0 <= s_sharp <= 10.0, f"清晰图评分 {s_sharp:.2f} 在1~10内")
    check(s_blur < s_sharp, f"模糊图 {s_blur:.2f} < 清晰图 {s_sharp:.2f}")
    check(dt < 2.0, f"两张评分共耗时 {dt*1000:.0f}ms")

    # ---- 2. 建库+导入+识别(8张同种改像素副本 + 2张他种) ----
    print("\n[2] 库与数据")
    from PIL import Image as _PILImage
    src_dir = PROJ / "data/aesthetic_src"
    if src_dir.exists():
        shutil.rmtree(src_dir)
    src_dir.mkdir()
    base = _PILImage.open(
        PROJ / "data/test_images/Anas_platyrhynchos.jpg").copy()
    px = base.load()
    for i in range(8):
        px[0, 0] = ((i * 37) % 256, (i * 91) % 256, (i * 151) % 256)
        base.save(src_dir / f"鸭{i}.jpg", quality=92)
    shutil.copy2(PROJ / "data/test_images/Alcedo_atthis.jpg",
                 src_dir / "翠鸟.jpg")
    shutil.copy2(PROJ / "data/test_images/Upupa_epops.jpg",
                 src_dir / "戴胜.jpg")
    lib = Library(LIB_DIR)
    lib.fill_species()
    files = sorted(src_dir.glob("*.jpg"))
    import_files(lib, files, mode="ref", dest_root=None, region_id="CN")
    pipe = RecognitionPipeline(
        detector_path=str(PROJ / "assets/models/BirdTraceBirdDetector_FP32.onnx"),
        classifier_path=str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
        labels_path=str(PROJ / "assets/data/labels.json"),
        geo_prior_path=str(PROJ / "assets/data/geo_prior.sqlite"))
    for pid in lib.pending_photo_ids():
        photo, _ = lib.photo_detail(pid)
        lib.add_records(pid, pipe.recognize(
            load_rgb(photo["path"]), lib.region_for_photo(pid),
            month_of(photo.get("dt_original"), 5)))
    pipe.close()
    n_photos = lib.conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    check(n_photos == len(files), f"导入 {n_photos} 张")

    # ---- 3. 老库迁移分支: 删列后重开, _migrate应补回 ----
    lib.conn.execute("DROP INDEX IF EXISTS idx_photos_aesthetic")
    lib.conn.execute("ALTER TABLE photos DROP COLUMN aesthetic")
    lib.conn.commit()
    lib2 = Library(LIB_DIR)
    cols = {r["name"] for r in lib2.conn.execute("PRAGMA table_info(photos)")}
    check("aesthetic" in cols, "旧库迁移补回 aesthetic 列")
    lib = lib2

    # ---- 4. 回填线程(真实模型) ----
    print("\n[3] 回填线程")
    check(len(lib.pending_aesthetic()) == n_photos,
          f"待评分 {len(lib.pending_aesthetic())} 张")
    from app.core.aesthetic_worker import AestheticWorker
    loop = QEventLoop()
    w = AestheticWorker(lib, PROJ / "assets")
    w.finished_all.connect(lambda s: (globals().__setitem__("_aes_sum", s),
                                      loop.quit()))
    t0 = time.perf_counter()
    w.start()
    QTimer.singleShot(300000, loop.quit)   # 5分钟兜底
    while w.isRunning():
        app.processEvents(QEventLoop.AllEvents, 50)
    loop.processEvents()
    ok_n = lib.conn.execute(
        "SELECT COUNT(*) FROM photos WHERE aesthetic IS NOT NULL").fetchone()[0]
    check(ok_n == n_photos,
          f"回填完成 {ok_n}/{n_photos} (耗时{time.perf_counter()-t0:.0f}s)")
    check(len(lib.pending_aesthetic()) == 0, "待评分清零")

    # ---- 5. 鸟种排序/封面/徽章 ----
    print("\n[4] 排序与封面")
    from app.ui.species_page import SpeciesPage

    class _WinStub(QWidget):
        worker = None
        pages = {}

    win = _WinStub()
    page = SpeciesPage(lib, win)
    page.resize(1200, 800)
    page.show()
    app.processEvents()
    ov = lib.species_overview()
    big = max(ov, key=lambda s: s["n"])
    if big["n"] < 2:   # 单张种无法验证排序, 用总数最多的种(默认图集基本每图一种)
        check(False, f"需要至少一个多张照的鸟种(当前最大 {big['n']})")
    else:
        ph = lib.photos_of_species(big["code"])
        scores = [p["aesthetic"] for p in ph]
        check(scores == sorted(scores, reverse=True),
              "photos_of_species 最美在前(评分降序)")
        best_row = lib.conn.execute(
            "SELECT path, file_hash FROM photos WHERE id=?",
            (big["cover_photo_id"],)).fetchone()
        best_id = lib.conn.execute(
            "SELECT p.id FROM v_records v JOIN photos p ON p.id=v.photo_id "
            "WHERE v.eff_code=? ORDER BY p.aesthetic DESC, v.taken_at ASC "
            "LIMIT 1", (big["code"],)).fetchone()["id"]
        check(big["cover_photo_id"] == best_id, "封面=该种最美照片")
        page._open_detail(big["code"])
        app.processEvents()
        grids = [g for g in page.content.findChildren(QGridLayout) if g.count()]
        items = [g.itemAt(i).widget() for g in [max(grids, key=lambda g: g.count())]
                 for i in range(g.count()) if g.itemAt(i).widget()]
        check(items[0].corner == "★最美", "详情首项带★最美徽章")
        check(all(it.corner is None for it in items[1:]), "其余项无徽章")

    # ---- 6. 年度十八图 ----
    print("\n[5] 年度十八图")
    year = time.strftime("%Y")
    best = lib.best_of_year(year)
    check(0 < len(best) <= 18, f"选出 {len(best)} 张")
    per: dict[str, int] = {}
    cap_ok = True
    for b in best:
        per[b["eff_code"]] = per.get(b["eff_code"], 0) + 1
        if per[b["eff_code"]] > 2:
            cap_ok = False
    check(cap_ok, "每种鸟最多2张")
    s_sorted = [b["aesthetic"] for b in best]
    check(s_sorted == sorted(s_sorted, reverse=True), "按评分降序")
    d = lib.yearly_report(year)
    check(d["best18"] == best, "yearly_report带best18")

    from app.ui.report_dialog import YearlyReportDialog
    dlg = YearlyReportDialog(lib, win)
    dlg.refresh()
    labels = [w.text() for w in dlg.findChildren(QLabel)]
    check(any("年度十八图" in t for t in labels), "报告含年度十八图卡片")
    pm = dlg._render_poster()
    check(not pm.isNull() and pm.height() > 1620,
          f"长图渲染成功 {pm.width()}x{pm.height()}")
    out = PROJ / "data/ui_shots/report_18.png"
    pm.save(str(out), "PNG")

    # ---- 7. 查看器信息带分数 ----
    pid = lib.conn.execute("SELECT id FROM photos LIMIT 1").fetchone()["id"]
    photo, _ = lib.photo_detail(pid)
    check(photo["aesthetic"] is not None, "photo_detail携带美学分")

    print()
    blur.unlink(missing_ok=True)
    shutil.rmtree(src_dir, ignore_errors=True)
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
