# -*- coding: utf-8 -*-
"""拖框重识别全链路验证: pipeline.recognize_box / 子进程协议box列 /
db写回 / 查看器拖框+重新识别E2E。

用法: .venv/Scripts/python.exe tools/verify_rebox.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB_DIR = PROJ / "data" / "rebox_check"
FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def make_pipe():
    from app.ai.pipeline import RecognitionPipeline
    return RecognitionPipeline(use_gpu=False,
        detector_path=str(PROJ / "assets/models/BirdTraceBirdDetector_FP32.onnx"),
        classifier_path=str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
        labels_path=str(PROJ / "assets/data/labels.json"),
        geo_prior_path=str(PROJ / "assets/data/geo_prior.sqlite"))


def main():
    if LIB_DIR.exists():
        shutil.rmtree(LIB_DIR)

    from app.ai.pipeline import load_rgb
    img_path = str(PROJ / "data/test_images/Alcedo_atthis.jpg")
    img = load_rgb(img_path)

    print("[1] pipeline.recognize_box")
    pipe = make_pipe()
    recs = pipe.recognize(img, "CN", 5, topk=5)
    check(len(recs) >= 1, f"检测到鸟 {len(recs)}框")
    base = recs[0]
    rec2 = pipe.recognize_box(img, base["box"], "CN", 5, topk=5)
    check(rec2 is not None and rec2["source"] == "rebox", "返回记录且source=rebox")
    check(rec2["species_code"] == base["species_code"],
          f"同框重认结果一致 {base['species_code']}")
    pipe.close()

    print("[2] 子进程协议box列(向后兼容无box行)")
    p = subprocess.Popen(
        [str(PROJ / ".venv/Scripts/python.exe"), "-u", "-X", "utf8", "-m",
         "app.ai.recognize_sub", "--assets", str(PROJ / "assets"), "--cpu",
         "--conf", "0.25"],
        cwd=str(PROJ), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8")

    def ask(line):
        p.stdin.write(line + "\n")
        p.stdin.flush()
        t0 = time.time()
        while time.time() - t0 < 120:
            raw = p.stdout.readline()
            if not raw:
                return None
            raw = raw.strip()
            if raw.startswith("{"):
                try:
                    return json.loads(raw)
                except ValueError:
                    pass
        return None

    def ask_answer():
        t0 = time.time()
        while time.time() - t0 < 60:
            raw = p.stdout.readline()
            if not raw:
                return None
            raw = raw.strip()
            if raw.startswith("{"):
                try:
                    return json.loads(raw)
                except ValueError:
                    pass
        return None

    box_s = ",".join(f"{v:.1f}" for v in base["box"])
    r1 = ask(f"1\t{img_path}\tCN\t5\t{box_s}")
    check(r1 and r1["ok"] and r1["records"][0]["source"] == "rebox",
          "带box行 -> rebox记录")
    r2 = ask(f"2\t{img_path}\tCN\t5")
    check(r2 and r2["ok"] and len(r2["records"]) >= 1 and
          r2["records"][0]["source"] == "detect", "无box行 -> 原检测路径(兼容)")
    # 一次发多行(滑动窗口协议): 两条都应有序返回
    p.stdin.write(f"3\t{img_path}\tCN\t5\n4\t{img_path}\tCN\t5\n")
    p.stdin.flush()
    r3, r4 = ask_answer(), ask_answer()
    check(r3 and r4 and r3["ok"] and r4["ok"], "窗口批量两行全应答")
    p.stdin.close()
    try:
        p.wait(timeout=15)
        check(True, "关stdin后子进程正常退出")
    except Exception:
        p.kill()
        check(False, "关stdin后子进程正常退出")

    print("[3] db 写回")
    from app.db import Library
    from app.core.importer import import_files
    lib = Library(LIB_DIR)
    lib.fill_species()
    import_files(lib, [PROJ / "data/test_images/Alcedo_atthis.jpg"],
                 mode="ref", dest_root=None, region_id="CN")
    pipe = make_pipe()
    pid = lib.pending_photo_ids()[0]
    photo, _ = lib.photo_detail(pid)
    lib_recs = pipe.recognize(load_rgb(photo["path"]), "CN", 5, topk=5)
    pipe.close()
    lib.add_records(pid, lib_recs)
    # 模拟"屁股误识": 追加一条异种记录(带框)
    wrong_rid = lib.conn.execute(
        "INSERT INTO records(photo_id,species_code,rank,confidence,source,box_json) "
        "VALUES(?,?,2,0.41,'detect',?)",
        (pid, "hoopoe", json.dumps([30, 30, 260, 240]))).lastrowid
    lib.conn.commit()

    lib.update_record_box(wrong_rid, [50.0, 60.0, 280.0, 270.0])
    got = json.loads(lib.conn.execute(
        "SELECT box_json FROM records WHERE id=?",
        (wrong_rid,)).fetchone()["box_json"])
    check(got == [50.0, 60.0, 280.0, 270.0], f"update_record_box 落库 {got}")

    lib.replace_record(wrong_rid, {
        "species_code": "comkin1", "confidence": 0.99, "source": "rebox",
        "box": [50, 60, 280, 270],
        "top5": [{"code": "comkin1", "prob": 0.99}]})
    row = lib.conn.execute(
        "SELECT species_code, source, rank, reviewed FROM records WHERE id=?",
        (wrong_rid,)).fetchone()
    check(row["species_code"] == "comkin1" and row["source"] == "rebox"
          and row["rank"] == 2 and row["reviewed"] == 0,
          "replace_record 原位替换(id/rank不变, 复核状态重置)")

    print("[4] 画框识别工具窗口E2E")
    from PySide6.QtCore import Qt, QEvent, QEventLoop, QTimer, Signal, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication, QWidget
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme
    theme.apply_theme(app, "light")

    class StubPage(QWidget):
        def __init__(self):
            super().__init__()
            self.refreshed = 0
        def refresh(self):
            self.refreshed += 1

    class FakeWin(QWidget):
        library_changed = Signal()
        def __init__(self, assets_path):
            super().__init__()
            self.assets = assets_path
            self.worker = None
            self.pages = {"species": StubPage(), "review": StubPage()}
        def _refresh_pages(self):
            self.pages["species"].refreshed += 100   # 区分直接refresh与_refresh_pages

    from app.ui.viewer import PhotoViewer
    from app.ui.rebox_dialog import ReboxDialog
    win = FakeWin(PROJ / "assets")
    dlg = PhotoViewer(lib, win, pid, [pid])
    dlg.show()
    loop = QEventLoop(); QTimer.singleShot(400, loop.quit); loop.exec()
    check(dlg.rebox_btn is not None and "画框识别" in dlg.rebox_btn.text(),
          "查看器工具栏有「画框识别」按钮")

    n_before = lib.conn.execute(
        "SELECT COUNT(*) c FROM records WHERE photo_id=?", (pid,)).fetchone()["c"]
    # 不调_rebox_dialog(模态exec会阻塞测试), 直接构造它内部用的对话框
    rd = ReboxDialog(lib, win, pid, dlg)
    rd.show()
    loop = QEventLoop(); QTimer.singleShot(400, loop.quit); loop.exec()
    check(rd.view.drawing(), "画框窗口打开即处于框选模式")

    vp1 = rd.view.mapFromScene(QPointF(80, 70))
    vp2 = rd.view.mapFromScene(QPointF(430, 410))
    press = QMouseEvent(QEvent.Type.MouseButtonPress, vp1, rd.view.mapToGlobal(vp1),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, vp2, rd.view.mapToGlobal(vp2),
                          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                          Qt.KeyboardModifier.NoModifier)
    rd.view.mousePressEvent(press)
    rd.view.mouseReleaseEvent(release)
    check(not rd.view.drawing(), "松手退出框选(进入识别)")

    deadline = time.time() + 120
    while time.time() < deadline:
        loop2 = QEventLoop(); QTimer.singleShot(300, loop2.quit); loop2.exec()
        if rd._last_rec is not None:
            break
    check(rd._last_rec is not None, "画框识别返回结果")
    if rd._last_rec:
        check(rd._last_rec["source"] == "rebox", "结果source=rebox")
        # 确认加入
        n_rec_before = lib.conn.execute(
            "SELECT COUNT(*) c FROM records WHERE photo_id=?", (pid,)).fetchone()["c"]
        rd._accept(rd._last_rec["species_code"])
        n_rec_after = lib.conn.execute(
            "SELECT COUNT(*) c FROM records WHERE photo_id=?", (pid,)).fetchone()["c"]
        check(n_rec_after == n_rec_before + 1, f"加入结果 记录数{n_rec_before}->{n_rec_after}")
        row = lib.conn.execute(
            "SELECT box_json, source FROM records WHERE photo_id=? " +
            "AND source='rebox' ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
        nb = json.loads(row["box_json"])
        check(abs(nb[0]-80)<1 and abs(nb[1]-70)<1 and abs(nb[2]-430)<1 and abs(nb[3]-410)<1,
              f"所画矩形落库 {nb}")
    # 回传: 查看器记录列表已刷新(用户实测bug: 确认后查看器不显示新记录)
    check(len(dlg.recs) == n_rec_after and any(
        r["source"] == "rebox" for r in dlg.recs),
        f"查看器记录列表同步刷新({len(dlg.recs)}条, 含画框记录)")
    check(win.pages["species"].refreshed >= 1 and win.pages["review"].refreshed >= 1,
          "鸟种库页与待复核页同步刷新")
    rd.grab().save(str(PROJ / "data/ui_shots/rebox_dialog.png"), "PNG")
    print("  saved rebox_dialog.png")
    from PySide6.QtCore import QProcess
    proc_obj = rd._proc
    rd.done(0)
    killed = proc_obj is None or proc_obj.state() == QProcess.ProcessState.NotRunning
    check(killed, "关窗后识别子进程被杀")
    dlg.done(0)

    print("FAILED" if FAILED["v"] else "ALL PASS")
    app.quit()
    shutil.rmtree(LIB_DIR, ignore_errors=True)
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
