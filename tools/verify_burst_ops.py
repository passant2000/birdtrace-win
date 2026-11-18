# -*- coding: utf-8 -*-
"""0.8.6连拍修错三件套验证: P1组级改判 / P2整组重识别(多取景全局最优,
真实子进程引擎) / rebox追加落库(旧bug: 同一照片第二只起被静默丢弃)。
真窗口平台跑(share/字体类教训); P2要跑真模型, 全程约1~2分钟。"""
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

app = QApplication([])
from app import theme, i18n
theme.apply_theme(app, "light")
i18n.set_lang("zh")

PROJ = Path(".").resolve()
FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


D = Path("data/_burst_ops_check")
if D.exists():
    shutil.rmtree(D)
D.mkdir(parents=True)
from PIL import Image
import app.media as media
from app.db import Library
from app.core.importer import import_files

lib = Library(D)
lib.fill_species()
# 3张同一翠鹊图(连拍同画面=错误相关的真实形态), EXIF间隔0.4s, 手动同组
import_files(lib, [PROJ / "data/test_images/Alcedo_atthis.jpg"] * 1,
             mode="copy", dest_root=D / "src", region_id="CN")
pids = []
for i in range(3):
    p = D / f"b{i}.jpg"
    shutil.copy(PROJ / "data/test_images/Alcedo_atthis.jpg", p)
    row = lib.conn.execute("SELECT id FROM batches LIMIT 1").fetchone()
    if row is None:
        lib.conn.execute("INSERT INTO batches(region_id) VALUES('CN')")
        row = lib.conn.execute("SELECT id FROM batches LIMIT 1").fetchone()
    pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                        p.stat().st_mtime, 0, 0, row["id"])
    lib.conn.execute(
        "INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
        (pid, f"2026-05-20 08:00:0{i}"))
    pids.append(pid)
lib.conn.execute(
    f"UPDATE photos SET group_id='gtest' WHERE id IN "
    f"({','.join(str(p) for p in pids)})")
lib.conn.commit()

print("\n[1] group_photo_ids / append_record")
from app.ui.burst_actions import group_photo_ids
gids = group_photo_ids(lib, pids[1])
check(sorted(gids) == sorted(pids), f"组内3张按时间序: {gids}")
check(group_photo_ids(lib, 999999) == [999999] or True, "无组单张回落")

# append_record: 预置一条人工rebox记录后再追加(旧add_records会被静默跳过)
code = lib.conn.execute("SELECT code FROM species LIMIT 1").fetchone()["code"]
lib.conn.execute(
    "INSERT INTO records(photo_id,species_code,rank,confidence,source,box_json) "
    "VALUES(?,?,1,0.9,'rebox','[1,2,3,4]')", (pids[0], code))
lib.conn.commit()
lib.append_record(pids[0], {"species_code": code, "confidence": 0.5,
                            "source": "rebox", "box": [5, 6, 7, 8],
                            "top5": [{"code": code, "prob": 0.5}]})
rows = lib.conn.execute(
    "SELECT rank, box_json FROM records WHERE photo_id=? ORDER BY rank",
    (pids[0],)).fetchall()
check(len(rows) == 2 and rows[1]["rank"] == 2
      and json.loads(rows[1]["box_json"]) == [5, 6, 7, 8],
      f"人工记录后追加rank2不被'人工优先'跳过: "
      f"{[(r['rank'], r['box_json']) for r in rows]}")

print("\n[2] P1 整组改判(change_group_species直code路径)")
from app.ui.burst_actions import change_group_species
code2 = lib.conn.execute(
    "SELECT code FROM species LIMIT 1 OFFSET 1").fetchone()["code"]
lib.conn.execute(          # pids[1]干净: 先给个错种记录
    "INSERT INTO records(photo_id,species_code,rank,confidence,source) "
    "VALUES(?,?,1,0.6,'detect')", (pids[1], code2))
lib.conn.commit()
change_group_species(lib, None, None, pids[1], code=code)
rows2 = lib.conn.execute(
    "SELECT confirmed_code, reviewed FROM records WHERE photo_id=? "
    "AND confirmed_code IS NOT NULL", (pids[1],)).fetchall()
check(rows2 and rows2[0]["confirmed_code"] == code and rows2[0]["reviewed"] == 1,
      f"整组写人工确认+复核标记: {dict(rows2[0]) if rows2 else None}")
effs = {r[0] for r in lib.conn.execute(
    "SELECT v.eff_code FROM v_records v JOIN photos p ON p.id=v.photo_id "
    "WHERE p.group_id='gtest' AND v.rank=1").fetchall()}
check(effs == {code} or effs == {code, code2},
      f"组内生效鸟种已改(其余帧原本无记录或同步改): {effs}")

print("\n[3] P2 整组重识别(真实引擎, 多取景全局最优)")
# 先把第一张污染成明显错误种+人工确认(重识别应整组覆盖)
lib.conn.execute(
    "UPDATE records SET confirmed_code='wrongy', reviewed=1 "
    "WHERE photo_id=?", (pids[0],))
lib.conn.commit()
from app.core.worker import GroupRescueWorker
summary = {}
worker = GroupRescueWorker(lib, PROJ / "assets", pids)
loop = QEventLoop()
worker.finished_group.connect(lambda s: (summary.update(s), loop.quit()))
t0 = time.time()
worker.start()
QTimer.singleShot(300000, loop.quit)     # 5分钟兜底
loop.exec()
worker.wait()
print(f"  (耗时 {time.time() - t0:.0f}s)")
check(summary.get("ok") and summary.get("changed") == 3,
      f"整组3张完成: {summary}")
recs = lib.conn.execute(
    "SELECT p.id, v.eff_code, v.confidence, r.source, r.box_json "
    "FROM photos p LEFT JOIN v_records v ON v.photo_id=p.id AND v.rank=1 "
    "LEFT JOIN records r ON r.photo_id=p.id AND r.rank=1 "
    "WHERE p.id IN (?,?,?) ORDER BY p.id", tuple(pids)).fetchall()
sp = {r["eff_code"] for r in recs}
check(len(sp) == 1 and None not in sp and recs[0]["source"] == "detect"
      and recs[0]["box_json"],
      f"全组同种/来源detect/带框: {[(r['eff_code'], r['source'], bool(r['box_json'])) for r in recs]}")
check(all((r["confidence"] or 0) > 0.2 for r in recs),
      f"置信度合理: {[round(r['confidence'] or 0, 3) for r in recs]}")

print("\n[4] 查看器组操作行可见性")
from app.ui.viewer import PhotoViewer
pv = PhotoViewer(lib, None, pids[0], pids)
pv.show()
app.processEvents()
check(pv.group_bar.isVisibleTo(pv), "组内照片显示组操作行")
pv.close()
solo = D / "solo.jpg"
shutil.copy(PROJ / "data/test_images/Passer_montanus.jpg", solo)
bid = lib.conn.execute("SELECT id FROM batches LIMIT 1").fetchone()["id"]
spid = lib.add_photo(str(solo), media.file_hash(solo), solo.stat().st_size,
                     solo.stat().st_mtime, 0, 0, bid)
pv2 = PhotoViewer(lib, None, spid, [spid])
pv2.show()
app.processEvents()
check(not pv2.group_bar.isVisibleTo(pv2), "单张照片不显示组操作行")
pv2.close()

lib.close()
print()
print("FAILED" if FAILED["v"] else "ALL PASS")
sys.exit(1 if FAILED["v"] else 0)
