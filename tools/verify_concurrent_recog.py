# -*- coding: utf-8 -*-
"""导入与识别并行验证: worker波次循环应拾取识别过程中新增的照片。

场景: 3张先导入待识别 -> worker启动 -> 识别进行中再导入2张 ->
worker自动在下一波拾取, 最终5张全部识别完成(无需外部重启)。
另测: worker全部跑完退出后, start_recognition式的重启拉起能拾取新增。
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB_DIR = PROJ / "data" / "concurrent_check"
FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def main() -> int:
    if LIB_DIR.exists():
        shutil.rmtree(LIB_DIR)

    from PySide6.QtCore import Qt, QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme
    theme.apply_theme(app, "light")
    from app.db import Library
    from app.core.importer import import_files
    from app.core.worker import RecognizeWorker

    lib = Library(LIB_DIR)
    lib.fill_species()
    imgs = sorted((PROJ / "data/test_images").glob("*.jpg"))
    import_files(lib, imgs[:3], mode="ref", dest_root=None, region_id="CN")
    check(len(lib.pending_photo_ids()) == 3, "首批3张待识别")

    from PySide6.QtCore import QThread

    class W(RecognizeWorker):
        pass

    results = []
    worker_ref = {}

    def start_worker():
        w = RecognizeWorker(lib, PROJ / "assets")
        w.finished_all.connect(lambda s: results.append(s) or done_loop.quit())
        worker_ref["w"] = w
        w.start()
        return w

    done_loop = QEventLoop()
    start_worker()

    # 1.5s后(worker正在跑首批)追加导入2张 —— 波次循环应自动拾取
    def add_more():
        import_files(lib, imgs[3:5], mode="ref", dest_root=None, region_id="CN")
    QTimer.singleShot(1500, add_more)

    t0 = time.time()
    while time.time() - t0 < 180:
        done_loop.processEvents()
        QTimer.singleShot(200, done_loop.quit)
        done_loop.exec()
        n_rec = lib.conn.execute(
            "SELECT COUNT(DISTINCT photo_id) c FROM records").fetchone()["c"]
        if n_rec >= 5:
            break
        if not worker_ref["w"].isRunning() and n_rec < 5:
            # worker提前退出(跑完首批时新增还没入库): 模拟导入页的反复拉起
            start_worker()
    n_rec = lib.conn.execute(
        "SELECT COUNT(DISTINCT photo_id) c FROM records").fetchone()["c"]
    pending = len(lib.pending_photo_ids())
    # 2026-11-03 未识别语义: 零检测/非鸟门照片不写记录(rec_fail=3),
    # 计入"已处理"而非"有记录"。全部5张都应离开待识别队列。
    n_nobird = lib.conn.execute(
        "SELECT COUNT(*) c FROM photos WHERE rec_fail>=3").fetchone()["c"]
    check(n_rec + n_nobird == 5 and pending == 0,
          f"5张全部处理完(有记录={n_rec}, 无鸟={n_nobird}, 待识别={pending})")

    # worker已退出后再新增 -> 重启拉起(导入页_import_progress的行为)
    import_files(lib, [imgs[5]], mode="ref", dest_root=None, region_id="CN")
    start_worker()
    t0 = time.time()
    while time.time() - t0 < 120:
        QTimer.singleShot(200, done_loop.quit)
        done_loop.exec()
        _n = lib.conn.execute(
            "SELECT COUNT(DISTINCT photo_id) c FROM records"
        ).fetchone()["c"] + lib.conn.execute(
            "SELECT COUNT(*) c FROM photos WHERE rec_fail>=3").fetchone()["c"]
        if _n >= 6:
            break
    n6 = lib.conn.execute(
        "SELECT COUNT(DISTINCT photo_id) c FROM records").fetchone()["c"]
    n_all6 = n6 + lib.conn.execute(
        "SELECT COUNT(*) c FROM photos WHERE rec_fail>=3").fetchone()["c"]
    check(n_all6 == 6 and len(lib.pending_photo_ids()) == 0,
          f"退出后重启worker拾取新增(有记录={n6}+无鸟={n_all6 - n6}/6)")

    print()
    print("FAILED" if FAILED["v"] else "ALL PASS")
    app.quit()
    shutil.rmtree(LIB_DIR, ignore_errors=True)
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
