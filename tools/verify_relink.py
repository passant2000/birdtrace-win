# -*- coding: utf-8 -*-
"""重新链接功能验证: 导入→搬走源→缺失检测→重链→识别(结果写文件)。"""
import sys
import time
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
from app import theme

OUT = []
app = QApplication(sys.argv)
theme.apply_theme(app, "light")
from app.db import Library
from app.ui.main_window import MainWindow
from app.core.importer import import_files

BASE = PROJ / "data" / "relink_verify"
import shutil
shutil.rmtree(BASE, ignore_errors=True)

lib = Library(BASE / "lib")
win = MainWindow(lib, PROJ / "assets")
win.show()
r = []


def check(name, cond):
    r.append((name, bool(cond)))
    OUT.append(("PASS" if cond else "FAIL") + " " + name)


def step1():
    src = BASE / "orig"
    src.mkdir(parents=True, exist_ok=True)
    for f in (PROJ / "data" / "test_images").glob("*.jpg"):
        shutil.copy2(f, src / f.name)
    import_files(lib, sorted(src.glob("*.jpg")), mode="ref", region_id="CN")
    check("导入6张", lib.photo_count() == 6)
    shutil.move(str(src), str(BASE / "moved"))
    missing = lib.missing_photo_ids()
    check(f"缺失检测({len(missing)})=6", len(missing) == 6)
    n = lib.relink_photos(BASE / "moved")
    check(f"重新链接({n})=6", n == 6)
    check("链接后文件全部存在",
          all(Path(row["path"]).exists()
              for row in lib.conn.execute("SELECT path FROM photos")))
    lib.reset_recognition([x["id"] for x in lib.conn.execute("SELECT id FROM photos")])
    from app.core.worker import RecognizeWorker
    worker = RecognizeWorker(lib, PROJ / "assets")
    results = []
    worker.finished_all.connect(lambda s: results.append(s))
    worker.start()
    deadline = time.time() + 180
    while time.time() < deadline and not results:
        app.processEvents()
        time.sleep(0.05)
    n_rec = lib.conn.execute("SELECT count(*) c FROM records").fetchone()["c"]
    # 2026-11-03 未识别语义: 无鸟/非鸟照片不写记录(rec_fail=3), 期望按此扣除
    n_nobird = lib.conn.execute(
        "SELECT count(*) c FROM photos WHERE rec_fail>=3").fetchone()["c"]
    check(f"重链后识别(records={n_rec}, 无鸟={n_nobird})>=6-无鸟",
          n_rec >= 6 - n_nobird and n_rec >= 1)
    fails = [x for x, ok in r if not ok]
    OUT.append("VERDICT: " + ("ALL PASS" if not fails else f"FAIL: {fails}"))
    (PROJ / "data" / "relink_result.txt").write_text("\n".join(OUT), encoding="utf-8")
    app.quit()


QTimer.singleShot(600, step1)
app.exec()
