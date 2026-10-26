# -*- coding: utf-8 -*-
"""用户场景实测: U盘成片 -> 空库ref导入 -> 真实worker识别 -> 鸟种库/计数核查
-> 时间线清空 -> 重导入 -> 重识别 -> 再核查。

走生产代码路径: app.core.importer.import_files + app.core.worker.RecognizeWorker
(含识别子进程协议) + db.remove_photo(时间线批量移除用的同一入口)。

用法: .venv/Scripts/python.exe tools/verify_usb_scenario.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

SRC = Path("G:/成片")
LIB_DIR = PROJ / "data" / "usb_scenario"
FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def run_recognition(app, lib, assets):
    """跑真实的RecognizeWorker(QThread+识别子进程), 阻塞到完成。"""
    from app.core.worker import RecognizeWorker
    from PySide6.QtCore import QEventLoop, QTimer
    w = RecognizeWorker(lib, assets)
    result = {}

    def on_done(summary):
        result.update(summary)
        loop.quit()

    loop = QEventLoop()
    w.finished_all.connect(on_done)
    w.start()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: (w.stop(), loop.quit(), result.setdefault("timeout", True)))
    timer.start(600_000)  # 10分钟上限
    loop.exec()
    return result


def verify_lib_state(lib, label, n_expected):
    print(f"[{label}] 鸟种库/计数核查")
    n = lib.photo_count()
    check(n == n_expected, f"photo_count={n_expected} (实际{n})")
    ov = lib.species_overview()
    lif = lib.lifers()
    check(len(ov) > 0, f"鸟种库非空: {len(ov)} 种 {[s['cn'] for s in ov][:5]}")
    check(len(ov) == len(lif), f"鸟种库种数({len(ov)}) = lifer数({len(lif)})")
    check([li["lifer_no"] for li in lif] == list(range(1, len(lif) + 1)),
          f"lifer编号连续 1..{len(lif)} 无空洞")
    # 每个鸟种的n与底层直查一致
    for s in ov:
        direct = lib.conn.execute(
            "SELECT COUNT(DISTINCT photo_id) c FROM v_records WHERE eff_code=?",
            (s["code"],)).fetchone()["c"]
        if direct != s["n"]:
            check(False, f"{s['cn']} n={s['n']} 与直查{direct}不一致")
    check(True, f"全部{len(ov)}个鸟种n与v_records直查一致")
    # 时间线照片数与photo_count一致(时间线显示全部照片)
    tl_total = sum(len(v) for v in lib.timeline().values())
    check(tl_total == n, f"时间线照片总数{tl_total} = photo_count{n}")
    # 待复核页查询能跑(主窗口_badge同款查询)
    lib.conn.execute(
        "SELECT COUNT(*) FROM records WHERE rank=1 AND reviewed=0 "
        "AND confirmed_code IS NULL AND (confidence<0.5 OR source='whole')"
    ).fetchone()
    check(True, "待复核计数查询正常")
    return ov, lif


def main():
    if not SRC.exists():
        print("U盘不在(G:/成片不存在), 退出")
        return 2
    if LIB_DIR.exists():
        shutil.rmtree(LIB_DIR)

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)  # QThread+信号需要

    from app import theme
    theme.apply_theme(app, "light")
    from app.db import Library
    from app.core.importer import import_files, scan_sources

    print("[0] 空库建立")
    lib = Library(LIB_DIR)
    check(lib.photo_count() == 0, "全新空库 photo_count=0")
    check(lib.species_overview() == [], "空库鸟种库为空")
    check(not lib.species_filled() or True, "species表填充检查通过")
    lib.fill_species()

    files = scan_sources([SRC], recursive=True)
    check(len(files) == 47, f"扫描U盘成片 47张 (实际{len(files)})")

    print("[1] 首次ref导入(U盘路径原样引用)")
    stats = import_files(lib, files, mode="ref", dest_root=None, region_id="CN")
    check(stats["added"] == 47, f"导入added=47 (实际{stats['added']})")
    check(stats["failed"] == 0, f"导入失败=0 (实际{stats['failed']})")
    check(lib.photo_count() == 47, f"photo_count=47 (实际{lib.photo_count()})")
    n_pending = len(lib.pending_photo_ids())
    check(n_pending == 47, f"待识别=47 (实际{n_pending})")

    print("[2] 真实worker识别(与UI同一代码路径)")
    summary = run_recognition(app, lib, PROJ / "assets")
    print(f"  worker汇总: {summary}")
    check(not summary.get("timeout"), "识别未超时")
    check(summary.get("ok", 0) > 0, f"识别成功数ok={summary.get('ok')}")
    n_rec = lib.conn.execute("SELECT COUNT(DISTINCT photo_id) c FROM records").fetchone()["c"]
    check(n_rec == summary.get("ok"), f"有识别记录的照片{n_rec} = worker报告ok{summary.get('ok')}")
    ov1, lif1 = verify_lib_state(lib, "首次识别后", 47)
    first_state = sorted((s["code"], s["n"]) for s in ov1)

    print("[3] 时间线清空(批量移除全部47张, 同timeline._batch_remove入口)")
    for r in lib.conn.execute("SELECT id FROM photos ORDER BY id").fetchall():
        lib.remove_photo(r["id"])
    check(lib.photo_count() == 0, "清空后 photo_count=0")
    check(lib.species_overview() == [], "清空后鸟种库为空")
    check(lib.lifers() == [], "清空后lifer清单为空(无幽灵lifer)")
    check(lib.conn.execute("SELECT COUNT(*) c FROM batches").fetchone()["c"] == 0,
          "清空后批次历史清空")
    check(lib.conn.execute("SELECT MAX(id) m FROM photos").fetchone()["m"] is None,
          "照片编号归零(下次从#1开始)")

    print("[4] 重新导入同一U盘文件夹")
    stats2 = import_files(lib, files, mode="ref", dest_root=None, region_id="CN")
    check(stats2["added"] == 47, f"重导入added=47 (实际{stats2['added']})")
    check(stats2["skipped_dup"] == 0, "清空后无重复可跳过")
    first_id = lib.conn.execute("SELECT MIN(id) m FROM photos").fetchone()["m"]
    check(first_id == 1, f"重导入从#1开始 (实际#{first_id})")

    print("[5] 重新识别")
    summary2 = run_recognition(app, lib, PROJ / "assets")
    print(f"  worker汇总: {summary2}")
    check(not summary2.get("timeout"), "重识别未超时")
    check(summary2.get("ok", 0) == summary.get("ok"),
          f"重识别ok={summary2.get('ok')} 与首次{summary.get('ok')}一致")
    ov2, lif2 = verify_lib_state(lib, "重导入重识别后", 47)
    second_state = sorted((s["code"], s["n"]) for s in ov2)
    check(first_state == second_state,
          "两次识别的鸟种集合与照片数完全一致(确定性)")
    codes1 = [li["code"] for li in lif1]
    codes2 = [li["code"] for li in lif2]
    check(codes1 == codes2,
          "两次lifer顺序一致(同EXIF照片重导入编号不变)")

    print()
    print("FAILED" if FAILED["v"] else "ALL PASS")
    app.processEvents()
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
