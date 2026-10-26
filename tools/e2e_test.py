# -*- coding: utf-8 -*-
"""端到端CLI联调: 建库 -> 导入 -> 识别 -> 查询 -> 分享卡渲染。

用法: .venv/Scripts/python.exe tools/e2e_test.py
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB_DIR = PROJ / "data" / "testlib"
SRC_DIR = PROJ / "data" / "test_images"


def main():
    if LIB_DIR.exists():
        shutil.rmtree(LIB_DIR)
    from app.db import Library
    from app.core.importer import import_files, scan_sources

    lib = Library(LIB_DIR)
    lib.fill_species()

    files = scan_sources([SRC_DIR], recursive=True)
    print(f"scanned: {len(files)} files")
    t0 = time.time()
    stats = import_files(lib, files, mode="ref", dest_root=None, region_id="CN")
    print(f"import: {stats} in {time.time()-t0:.1f}s")

    # 识别 (直接走管线, 验证与UI线程相同代码路径的数据落库)
    from app.ai.pipeline import RecognitionPipeline, load_rgb
    from app.exif import month_of
    pipe = RecognitionPipeline(
        detector_path=str(PROJ / "assets/models/BirdTraceBirdDetector_FP32.onnx"),
        classifier_path=str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
        labels_path=str(PROJ / "assets/data/labels.json"),
        geo_prior_path=str(PROJ / "assets/data/geo_prior.sqlite"),
    )
    for pid in lib.pending_photo_ids():
        photo, _ = lib.photo_detail(pid)
        region = lib.region_for_photo(pid)
        month = month_of(photo.get("dt_original"), 5)
        recs = pipe.recognize(load_rgb(photo["path"]), region, month)
        lib.add_records(pid, recs)
        print(f"  #{pid} {Path(photo['path']).name}: "
              f"{[(r['species_code'], round(r['confidence'],3), r['source']) for r in recs]}")
    pipe.close()

    print("\n--- timeline ---")
    for ym, photos in lib.timeline().items():
        print(f"  {ym}: {len(photos)} photos")

    print("\n--- species overview ---")
    for sp in lib.species_overview():
        print(f"  {sp['cn']:8s} {sp['en'][:28]:28s} n={sp['n']} first={sp['first_at'][:10]}")

    print("\n--- lifers ---")
    for li in lib.lifers():
        print(f"  #{li['lifer_no']} {li['cn']} {li['en'][:24]} first={li['first_at'][:10]}")

    print("\n--- review queue (conf<0.5 or whole) ---")
    for item in lib.review_queue():
        print(f"  {item['cn']} conf={item['confidence']:.3f} src={item['source']}")

    print("\n--- stats ---")
    print(f"  {lib.stats_summary()}")

    # 分享卡渲染 (需QApplication)
    print("\n--- share card ---")
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from app.core.sharecard import render_card
    lifers = lib.lifers()
    li = lifers[0]
    photo, recs = lib.photo_detail(li["photo_id"])
    sp = lib.species_info(li["code"])
    from pypinyin import Style, lazy_pinyin
    py = "".join(lazy_pinyin(sp["cn"] or "", style=Style.TONE))
    info = {"cn": sp["cn"], "pinyin": py[:1].upper() + py[1:], "en": sp["en"],
            "sci": sp["sci"], "lifer_no": li["lifer_no"],
            "photographer": "测试者", "date": li["first_at"][:10], "place": None}
    for theme_name in ("light", "dark"):
        pm = render_card(photo["path"], info, theme_name)
        out = PROJ / "data" / f"sharecard_{theme_name}.png"
        pm.save(str(out), "PNG")
        print(f"  {theme_name}: {out} {out.stat().st_size:,} bytes ({pm.width()}x{pm.height()})")

    # 复核: 纠正第一条记录看看联动
    print("\n--- confirm flow ---")
    item = (lib.review_queue() or [None])[0]
    if item:
        lib.set_confirmed(item["record_id"], item["code"])
        print(f"  confirmed {item['cn']} -> reviewed")
    else:
        r = lib.conn.execute("SELECT id, species_code FROM records LIMIT 1").fetchone()
        lib.set_confirmed(r["id"], r["species_code"])
        print(f"  confirmed top1 #{r['id']}")
    print(f"  lifers now: {len(lib.lifers())}")
    lib.close()
    print("\nE2E DONE.")


if __name__ == "__main__":
    main()
