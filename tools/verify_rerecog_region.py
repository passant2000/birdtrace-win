# -*- coding: utf-8 -*-
"""0.8.0-test2 复查修复验证: 批量重新识别的地区选择对话框。

修复: 国家级地区项 data 曾为 None(与「保持不变」同值)——选"中国"后
      if new_region 不成立, 批次地区静默不变。现国家级带真实地区id。

用法: .venv/Scripts/python.exe tools/verify_rerecog_region.py
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def make_img(path: Path, seed: int = 0):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (320, 240), (90, 120, 150))
    d = ImageDraw.Draw(im)
    d.ellipse([70, 60, 250, 190], fill=(230, 200, 120))
    d.text((10, 10), str(seed), fill=(255, 255, 255))
    im.save(path, "JPEG")


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (QApplication, QComboBox, QDialog,
                                   QMessageBox)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme, i18n
    theme.apply_theme(app, "light")
    i18n.set_lang("zh")

    LIB = PROJ / "data/rerecog_check"
    if LIB.exists():
        shutil.rmtree(LIB)
    (LIB / "src").mkdir(parents=True)
    from app.db import Library
    import app.media as media
    lib = Library(LIB)
    lib.fill_species()
    code = lib.conn.execute("SELECT code FROM species LIMIT 1").fetchone()["code"]

    p = LIB / "src" / "r1.jpg"
    make_img(p, 1)
    lib.conn.execute("INSERT INTO batches(region_id) VALUES('GLOBAL')")
    bid = lib.conn.execute("SELECT id FROM batches").fetchone()["id"]
    pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                        p.stat().st_mtime, 320, 240, bid)
    lib.conn.execute("INSERT INTO exif(photo_id, dt_original) "
                     "VALUES(?, '2026-05-01 08:00:00')", (pid,))
    lib.add_records(pid, [{"species_code": code, "confidence": 0.9}])
    lib.conn.commit()
    print(f"\n[1] 建库: photo={pid}, 当前批次region="
          f"{lib.conn.execute('SELECT region_id FROM batches').fetchone()[0]}")

    from app.ui.main_window import MainWindow
    win = MainWindow(lib, PROJ / "assets")
    tl = win.pages["timeline"]
    win.start_recognition = lambda *a, **k: None   # 不拉真模型
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    picked = {}

    def fake_exec(self_dlg):
        combos = self_dlg.findChildren(QComboBox)
        picked["combos"] = combos
        # 国家级"中国"必须可寻址(data=CN)——修复前findData("CN")=-1
        idx = combos[0].findData("CN")
        picked["cn_idx"] = idx
        if idx >= 0:
            combos[0].setCurrentIndex(idx)
        return 1   # QDialog.Accepted

    QDialog.exec = fake_exec
    tl._selected = {pid}
    tb = []
    sys.excepthook = lambda et, v, t: tb.append(f"{et.__name__}: {v}")
    tl._batch_rerecognize()
    sys.excepthook = sys.__excepthook__

    check(not tb, f"_batch_rerecognize 无异常 ({tb})")
    check(picked.get("cn_idx", -2) >= 0,
          f"国家级地区项可寻址 (findData('CN')={picked.get('cn_idx')})")
    region_now = lib.conn.execute(
        "SELECT region_id FROM batches b JOIN photos p ON p.batch_id=b.id "
        "WHERE p.id=?", (pid,)).fetchone()[0]
    check(region_now == "CN", f"选「中国」后批次region_id=CN (got {region_now})")
    n_recs = lib.conn.execute(
        "SELECT COUNT(*) FROM records WHERE photo_id=?", (pid,)).fetchone()[0]
    check(n_recs == 0, f"旧识别结果已重置 (records={n_recs})")

    # [2] 省级 + 鸟点"不挂"
    print("\n[2] 省级(CN-SH)+不挂鸟点")

    def fake_exec2(self_dlg):
        combos = self_dlg.findChildren(QComboBox)
        combos[0].setCurrentIndex(combos[0].findData("CN-SH"))
        combos[1].setCurrentIndex(combos[1].findData(None))   # 不挂鸟点
        return 1

    QDialog.exec = fake_exec2
    lib.add_records(pid, [{"species_code": code, "confidence": 0.9}])
    spot_id = lib.create_spot("测试点")
    lib.set_photos_spot([pid], spot_id)
    tl._selected = {pid}
    tl._batch_rerecognize()
    region2 = lib.conn.execute(
        "SELECT region_id FROM batches b JOIN photos p ON p.batch_id=b.id "
        "WHERE p.id=?", (pid,)).fetchone()[0]
    spot2 = lib.conn.execute(
        "SELECT spot_id FROM photos WHERE id=?", (pid,)).fetchone()[0]
    check(region2 == "CN-SH", f"省级生效 (got {region2})")
    check(spot2 is None, f"不挂鸟点生效 (got {spot2})")

    # [3] 「保持不变」两项都不动
    print("\n[3] 保持不变")

    def fake_exec3(self_dlg):
        return 1   # 两个combo都停在第一项=保持不变

    QDialog.exec = fake_exec3
    lib.set_photos_spot([pid], spot_id)
    tl._selected = {pid}
    tl._batch_rerecognize()
    region3 = lib.conn.execute(
        "SELECT region_id FROM batches b JOIN photos p ON p.batch_id=b.id "
        "WHERE p.id=?", (pid,)).fetchone()[0]
    spot3 = lib.conn.execute(
        "SELECT spot_id FROM photos WHERE id=?", (pid,)).fetchone()[0]
    check(region3 == "CN-SH", f"地区保持不变 (got {region3})")
    check(spot3 == spot_id, f"鸟点保持不变 (got {spot3})")

    print("\n" + ("FAIL" if FAILED["v"] else "ALL PASS"))
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
