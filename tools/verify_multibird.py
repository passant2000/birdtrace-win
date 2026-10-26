# -*- coding: utf-8 -*-
"""查看器多鸟场景验证: 缩略图/框高亮/单条删除/重排/鸟种库同步/防自动重识别。

用法: .venv/Scripts/python.exe tools/verify_multibird.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB_DIR = PROJ / "data" / "multibird_check"
FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def main():
    if LIB_DIR.exists():
        shutil.rmtree(LIB_DIR)

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
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
    files = [PROJ / "data/test_images/Anas_platyrhynchos.jpg",
             PROJ / "data/test_images/Alcedo_atthis.jpg"]
    import_files(lib, files, mode="ref", dest_root=None, region_id="CN")

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

    # 模拟用户场景: 第一张照片追加一条"屁股误识"异种低置信度记录
    duck_pid = lib.conn.execute("SELECT MIN(id) m FROM photos").fetchone()["m"]
    wrong_rid = lib.conn.execute(
        "INSERT INTO records(photo_id,species_code,rank,confidence,source,box_json) "
        "VALUES(?,?,2,0.41,'detect',?)",
        (duck_pid, "hoopoe", json.dumps([400, 300, 900, 850]))).lastrowid
    lib.conn.commit()

    print("[1] db.remove_record 语义")
    had_hoopoe_elsewhere = lib.conn.execute(
        "SELECT COUNT(*) c FROM records WHERE species_code='hoopoe' "
        "AND photo_id!=?", (duck_pid,)).fetchone()["c"]
    n_before = len(lib.species_overview())
    photo, recs = lib.photo_detail(duck_pid)
    check(len(recs) >= 2, f"多记录照片就绪({len(recs)}条)")
    lib.remove_record(wrong_rid)
    _, recs2 = lib.photo_detail(duck_pid)
    ranks = sorted(r["rank"] for r in recs2)
    check(ranks == list(range(1, len(recs2) + 1)),
          f"删除后rank连续重排 {ranks}")
    hoopoe_now = lib.conn.execute(
        "SELECT COUNT(*) c FROM records WHERE species_code='hoopoe'"
    ).fetchone()["c"]
    check(hoopoe_now == had_hoopoe_elsewhere, "误识记录已删")
    n_after = len(lib.species_overview())
    expect = n_before if had_hoopoe_elsewhere else n_before - 1
    check(n_after == expect, f"鸟种库同步: {n_before} -> {n_after}")

    print("[2] 删光全部记录 -> 不再被自动重识别")
    _, recs3 = lib.photo_detail(duck_pid)
    for r in recs3:
        lib.remove_record(r["record_id"])
    check(lib.conn.execute(
        "SELECT rec_fail FROM photos WHERE id=?", (duck_pid,)).fetchone()[0] == 3,
        "rec_fail=3(视同无鸟)")
    check(duck_pid not in lib.pending_photo_ids(),
          "pending不包含该照片(不会被自动重识别)")
    lib.add_manual_record(duck_pid, "mallar3")
    check(lib.conn.execute(
        "SELECT COUNT(*) c FROM records WHERE photo_id=?", (duck_pid,)
    ).fetchone()["c"] == 1, "手工标注仍可用")

    print("[3] 查看器UI(缩略图/框/路径链接)")
    kf_pid = lib.conn.execute(
        "SELECT MAX(id) m FROM photos").fetchone()["m"]
    lib.conn.execute(
        "INSERT INTO records(photo_id,species_code,rank,confidence,source,box_json) "
        "VALUES(?,?,2,0.38,'detect',?)",
        (kf_pid, "graher1", json.dumps([50, 40, 620, 580])))
    lib.conn.commit()

    from app.ui.viewer import PhotoViewer
    dlg = PhotoViewer(lib, None, kf_pid, [kf_pid])
    dlg.show()
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop(); QTimer.singleShot(600, loop.quit); loop.exec()

    info_txt = dlg.info.text()
    check(Path(dlg.photo["path"]).name in info_txt, "信息面板含文件名")
    check(dlg.photo["path"] in info_txt and "open-path" in info_txt,
          "信息面板含完整路径(可点击链接)")
    row_widgets = [dlg.records_box.itemAt(i).widget()
                   for i in range(dlg.records_box.count())]
    has_thumb = any(
        lbl.pixmap() and not lbl.pixmap().isNull()
        for row in row_widgets if row is not None
        for lbl in row.findChildren(type(dlg.navi)))
    check(has_thumb, "记录行有裁剪缩略图")
    check(not hasattr(dlg, "_box_items"),
          "大图不再叠加检测框(画框识别改独立窗口)")
    dlg.grab().save(str(PROJ / "data/ui_shots/multibird_viewer.png"), "PNG")
    print("  saved multibird_viewer.png")

    print()
    print("FAILED" if FAILED["v"] else "ALL PASS")
    dlg.close()
    app.quit()
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
