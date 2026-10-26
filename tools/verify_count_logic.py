# -*- coding: utf-8 -*-
"""计数逻辑回归: 照片计数 + lifer编号 在 引用模式移除/重导入 下的行为。

用法: .venv/Scripts/python.exe tools/verify_count_logic.py
验证(db.py docstring承诺的规则):
  1. ref导入6张 -> photo_count=6, 鸟种库n与lifer编号连续
  2. 移除某鸟种唯一照片 -> photo_count=5, 该种退出, 编号前移无空洞
  3. 同一批照片重新导入(同EXIF) -> lifer编号恢复
  4. 全部移除 -> photo_count=0, 编号归零, 重新导入从#1开始
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB_DIR = PROJ / "data" / "count_check"
SRC_DIR = PROJ / "data" / "test_images"


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}")
    if not cond:
        globals()["FAILED"] = True


def main():
    if LIB_DIR.exists():
        shutil.rmtree(LIB_DIR)
    globals()["FAILED"] = False
    from app.db import Library
    from app.core.importer import import_files, scan_sources
    from app.ai.pipeline import RecognitionPipeline, load_rgb
    from app.exif import month_of

    lib = Library(LIB_DIR)
    lib.fill_species()
    files = scan_sources([SRC_DIR], recursive=True)
    stats = import_files(lib, files, mode="ref", dest_root=None, region_id="CN")
    print(f"[1] ref导入: {stats}")

    pipe = RecognitionPipeline(
        detector_path=str(PROJ / "assets/models/BirdTraceBirdDetector_FP32.onnx"),
        classifier_path=str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
        labels_path=str(PROJ / "assets/data/labels.json"),
        geo_prior_path=str(PROJ / "assets/data/geo_prior.sqlite"),
    )
    for pid in lib.pending_photo_ids():
        photo, _ = lib.photo_detail(pid)
        recs = pipe.recognize(load_rgb(photo["path"]),
                              lib.region_for_photo(pid),
                              month_of(photo.get("dt_original"), 5))
        lib.add_records(pid, recs)
    pipe.close()

    print("[1] 识别后计数")
    check(lib.photo_count() == 6, f"photo_count=6 (实际{lib.photo_count()})")
    ov = lib.species_overview()
    lif = lib.lifers()
    check(len(ov) == len(lif), f"鸟种库n({len(ov)})=lifer数({len(lif)})")
    check([li["lifer_no"] for li in lif] == list(range(1, len(lif) + 1)),
          f"lifer编号连续1..{len(lif)}")
    # 一照多鸟(不同种)会同时计入两个鸟种的照片列表, 和>=照片数是正常状态
    n_sum = sum(s["n"] for s in ov)
    check(n_sum >= 6, f"各鸟种照片数之和{n_sum} >= 照片数6(一照多鸟按种各计)")
    for s in ov:
        direct = lib.conn.execute(
            "SELECT COUNT(DISTINCT photo_id) c FROM v_records WHERE eff_code=?",
            (s["code"],)).fetchone()["c"]
        check(direct == s["n"], f"{s['cn']} n={s['n']} 与直查一致")
    codes_before = [li["code"] for li in lif]
    has_exif = lib.conn.execute(
        "SELECT COUNT(*) c FROM exif WHERE dt_original IS NOT NULL"
    ).fetchone()["c"]
    print(f"  (测试图EXIF: {has_exif}/6 张有拍摄时间, 无EXIF时拍摄时间=导入时间)")

    print("[2] 移除第一张(其鸟种若唯一则退出)")
    first_code = lib.conn.execute(
        "SELECT eff_code FROM v_records WHERE photo_id=1").fetchone()[0]
    others_have = lib.conn.execute(
        "SELECT COUNT(DISTINCT photo_id) c FROM v_records WHERE eff_code=? "
        "AND photo_id!=1", (first_code,)).fetchone()["c"]
    lib.remove_photo(1)
    check(lib.photo_count() == 5, f"移除后photo_count=5 (实际{lib.photo_count()})")
    lif2 = lib.lifers()
    check([li["lifer_no"] for li in lif2] == list(range(1, len(lif2) + 1)),
          "移除后编号仍连续无空洞")
    if others_have == 0:
        check(all(li["code"] != first_code for li in lif2),
              f"{first_code} 已退出清单")

    print("[3] 同批照片重新导入(同EXIF -> 编号恢复)")
    stats = import_files(lib, [PROJ / "data/test_images/Alcedo_atthis.jpg"],
                         mode="ref", dest_root=None, region_id="CN")
    pid = lib.pending_photo_ids()
    check(len(pid) == 1, f"新导入1张待识别 (实际{len(pid)})")
    if pid:
        photo, _ = lib.photo_detail(pid[0])
        pipe = RecognitionPipeline(
            detector_path=str(PROJ / "assets/models/BirdTraceBirdDetector_FP32.onnx"),
            classifier_path=str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
            labels_path=str(PROJ / "assets/data/labels.json"),
            geo_prior_path=str(PROJ / "assets/data/geo_prior.sqlite"),
        )
        recs = pipe.recognize(load_rgb(photo["path"]),
                              lib.region_for_photo(pid[0]),
                              month_of(photo.get("dt_original"), 5))
        lib.add_records(pid[0], recs)
        pipe.close()
    lif3 = lib.lifers()
    check([li["lifer_no"] for li in lif3] == list(range(1, len(lif3) + 1)),
          "重导入后编号连续")
    check(set(li["code"] for li in lif3) == set(codes_before),
          "重导入后鸟种集合与最初一致")
    # 无EXIF的测试图: 拍摄时间=导入时间 -> 重导入按新时间排位(规则内行为);
    # 有EXIF的真实照片: 按EXIF时间排位, 重导入编号不变
    if has_exif == 6:
        check([li["code"] for li in lif3] == codes_before,
              "同EXIF重导入 -> lifer顺序与最初一致")
    else:
        re_code = lib.conn.execute(
            "SELECT eff_code FROM v_records WHERE photo_id=?", (pid[0],)).fetchone()
        print(f"  (无EXIF图按重导入时间排位: {re_code['eff_code'] if re_code else '?'} -> "
              f"第{[li['code'] for li in lif3].index(re_code['eff_code'])+1 if re_code else '?'}位)")

    print("[4] 全部移除 -> 归零")
    for r in lib.conn.execute("SELECT id FROM photos").fetchall():
        lib.remove_photo(r["id"])
    check(lib.photo_count() == 0, "photo_count=0")
    check(lib.lifers() == [], "lifer清单清空")
    check(lib.conn.execute("SELECT COUNT(*) c FROM batches").fetchone()["c"] == 0,
          "批次历史清空(编号归零)")
    stats = import_files(lib, [PROJ / "data/test_images/Passer_montanus.jpg"],
                         mode="ref", dest_root=None, region_id="CN")
    check(lib.photo_count() == 1, "清空后再导入从新库开始")
    check(lib.conn.execute("SELECT MAX(id) m FROM photos").fetchone()["m"] == 1,
          "photo id 从#1重新开始")

    print()
    print("FAILED" if globals()["FAILED"] else "ALL PASS")
    return 1 if globals()["FAILED"] else 0


if __name__ == "__main__":
    sys.exit(main())
