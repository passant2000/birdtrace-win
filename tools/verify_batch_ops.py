# -*- coding: utf-8 -*-
"""批量操作验证: 鸟点批量挂载/取消(时间线多选→BatchSpotDialog) +
鸟种库多选批量改判(set_species_batch) + 未识别整批手工标注。"""
import sys
import shutil
from pathlib import Path

sys.path.insert(0, ".")
from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtCore import QObject, Signal, QEventLoop, QTimer

app = QApplication([])
from app import theme, i18n
theme.apply_theme(app, "light")
i18n.set_lang("zh")
from app.db import Library
import app.media as media

D = Path("data/_batch_ops_check")
if D.exists():
    shutil.rmtree(D)
D.mkdir(parents=True)


def settle(ms=400):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class _Win(QObject):
    library_changed = Signal()


class _FakeMB:
    """替身QMessageBox: question一律回Yes(只测业务路径, 不测弹窗)。"""
    Yes = 1
    No = 2

    @staticmethod
    def question(*a, **k):
        return _FakeMB.Yes


# ================= 第一部分: 数据层 =================
print("---- 数据层: set_species_batch / set_photos_spot ----")
lib = Library(D)
lib.fill_species()
codes = [r["code"] for r in lib.conn.execute(
    "SELECT code FROM species LIMIT 3").fetchall()]
A, B, C = codes
lib.conn.execute("INSERT INTO batches(region_id) VALUES('GLOBAL')")
bid = lib.conn.execute("SELECT id FROM batches").fetchone()["id"]

from PIL import Image
_n = [0]


def add_ph(recs=None, rec_fail=False):
    _n[0] += 1
    p = D / "src" / f"p{_n[0]}.jpg"
    p.parent.mkdir(exist_ok=True)
    Image.new("RGB", (320, 240), (100, 110, 120)).save(p, "JPEG")
    pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                        p.stat().st_mtime, 320, 240, bid)
    if rec_fail:
        lib.conn.execute("UPDATE photos SET rec_fail=3 WHERE id=?", (pid,))
    if recs:
        lib.add_records(pid, recs)
    return pid


def eff(conn, pid):
    return [r["confirmed_code"] or r["species_code"] for r in
            conn.execute("SELECT * FROM records WHERE photo_id=? "
                         "ORDER BY rank", (pid,)).fetchall()]


wrong = [add_ph([{"species_code": B, "confidence": 0.9}]) for _ in range(4)]
right = [add_ph([{"species_code": A, "confidence": 0.9}]) for _ in range(4)]
multi = add_ph([{"species_code": A, "confidence": 0.8},
                {"species_code": B, "confidence": 0.6}])   # 一图两鸟
mixed = add_ph([{"species_code": B, "confidence": 0.7},
                {"species_code": C, "confidence": 0.5}])   # 一图两鸟异种
lib.conn.commit()

# 1) 批量改判: 错的一半 + 多鸟照的B记录 → A
n = lib.set_species_batch(wrong + [multi], A, from_code=B)
assert n == 5, f"应改5条记录, 实改{n}"
for pid in wrong:
    assert eff(lib.conn, pid) == [A]
r = lib.conn.execute("SELECT * FROM records WHERE photo_id=? ORDER BY rank",
                     (multi,)).fetchall()
assert (r[0]["confirmed_code"] or r[0]["species_code"]) == A \
    and r[0]["confirmed_code"] is None          # 原本就对的主鸟未被覆盖
assert r[1]["confirmed_code"] == A             # B被改判为A
assert r[1]["species_code"] == B               # AI原值保留
assert r[1]["reviewed"] == 1
print("1) 错半批+多鸟B记录→A:", n, "条 ✓  AI原值/主鸟未动 ✓")

# 2) from_code过滤: mixed里只有B被改, C不动
n = lib.set_species_batch([mixed], A, from_code=B)
assert n == 1 and eff(lib.conn, mixed) == [A, C], f"mixed应为[A,C], 实{eff(lib.conn, mixed)}"
print("2) from_code过滤(只动B不动C) ✓")

# 3) 幂等: 再跑一遍应0条
assert lib.set_species_batch(wrong, A, from_code=B) == 0
print("3) 幂等重跑0改动 ✓")

# 4) eff_code生效: 鸟种库归属跟着走
in_a = {p["photo_id"] for p in lib.photos_of_species(A)}
in_b = {p["photo_id"] for p in lib.photos_of_species(B)}
assert in_b == set() and set(wrong + right + [multi, mixed]) <= in_a
print("4) photos_of_species归位: A含改判照, B清空 ✓")

# 5) 鸟点批量挂载/取消
sid = lib.create_spot("测试点", 40.0, 116.0)
lib.set_photos_spot(wrong, sid)
assert all(lib.conn.execute("SELECT spot_id FROM photos WHERE id=?",
                            (p,)).fetchone()[0] == sid for p in wrong)
lib.set_photos_spot(wrong, None)
assert all(lib.conn.execute("SELECT spot_id FROM photos WHERE id=?",
                            (p,)).fetchone()[0] is None for p in wrong)
print("5) 鸟点批量挂载→整批取消 ✓")

# 5b) 鸟点简称(分享卡地点行显示用): 迁移补列/update_spot/查询带出/清空回落
sid5 = lib.create_spot("滨海国家湿地公园观鸟长堤", 39.1, 117.2)
assert "short_name" in lib.spot_info(sid5).keys()
lib.update_spot(sid5, short_name="滨海长堤")
assert lib.spot_info(sid5)["short_name"] == "滨海长堤"
assert lib.spot_info(sid5)["name"] == "滨海国家湿地公园观鸟长堤"  # 全名不动
lib.set_photos_spot(wrong[:1], sid5)
det = lib.photo_detail(wrong[0])[0]
assert det["spot_short"] == "滨海长堤" and det["spot_name"] == "滨海国家湿地公园观鸟长堤"
lib.update_spot(sid5, short_name="")           # 清空→回落全名
assert lib.spot_info(sid5)["short_name"] == ""
print("5b) 鸟点简称: 迁移/保存/查询带出/清空回落 ✓")

# 5c) 眼点落库(分享卡保头): add_records带eye→photo_detail带出→share_card_rows
import json as _j
pid5 = wrong[0]
lib.conn.execute("DELETE FROM records WHERE photo_id=?", (pid5,))
lib.add_records(pid5, [{"species_code": B, "confidence": 0.8,
                        "box": [100, 200, 900, 800], "eye": [0.62, 0.31]}])
det = lib.photo_detail(pid5)
rec0 = det[1][0]
assert rec0["eye_json"] and _j.loads(rec0["eye_json"]) == [0.62, 0.31]
rows = lib.share_card_rows([pid5])
assert len(rows) == 1 and _j.loads(rows[0]["eye_json"]) == [0.62, 0.31]
assert rows[0]["record_id"] == rec0["record_id"]
lib.conn.execute("UPDATE records SET eye_json=NULL WHERE photo_id=?", (pid5,))
lib.conn.commit()
print("5c) 眼点落库/查询带出/share_card_rows ✓")
lib.close()

# ================= 第二部分: 鸟种库页面流程 =================
print("---- 鸟种库: 多选改判 / 未识别批量标注 ----")
import app.ui.species_page as sp
import app.ui.species_pick as spick


class _FakePick:
    """替身SpeciesPickDialog: exec后固定返回目标鸟种。"""
    target = None

    def __init__(self, lib, title=None, parent=None):
        self.selected_code = None

    def exec(self):
        self.selected_code = _FakePick.target
        return 1


spick.SpeciesPickDialog = _FakePick
sp.QMessageBox = _FakeMB

D2 = Path("data/_batch_ops_check2")
if D2.exists():
    shutil.rmtree(D2)
lib2 = Library(D2)
lib2.fill_species()
codes2 = [r["code"] for r in lib2.conn.execute(
    "SELECT code FROM species LIMIT 2").fetchall()]
A2, B2 = codes2
lib2.conn.execute("INSERT INTO batches(region_id) VALUES('GLOBAL')")
bid2 = lib2.conn.execute("SELECT id FROM batches").fetchone()["id"]
win = _Win()
wrong2, right2, unids = [], [], []
for i in range(3):
    p = D2 / "src" / f"w{i}.jpg"
    p.parent.mkdir(exist_ok=True)
    Image.new("RGB", (320, 240), (90, 100, 110)).save(p, "JPEG")
    pid = lib2.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                         p.stat().st_mtime, 320, 240, bid2)
    lib2.add_records(pid, [{"species_code": B2, "confidence": 0.9,
                            "top5": [{"code": B2, "prob": 0.6},
                                     {"code": A2, "prob": 0.3}]}])
    wrong2.append(pid)
for i in range(2):
    p = D2 / "src" / f"r{i}.jpg"
    Image.new("RGB", (320, 240), (110, 120, 130)).save(p, "JPEG")
    pid = lib2.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                         p.stat().st_mtime, 320, 240, bid2)
    lib2.add_records(pid, [{"species_code": A2, "confidence": 0.9}])
    right2.append(pid)
for i in range(2):
    p = D2 / "src" / f"u{i}.jpg"
    Image.new("RGB", (320, 240), (130, 140, 150)).save(p, "JPEG")
    pid = lib2.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                         p.stat().st_mtime, 320, 240, bid2)
    lib2.conn.execute("UPDATE photos SET rec_fail=3 WHERE id=?", (pid,))
    unids.append(pid)
lib2.conn.commit()

from app.ui.species_page import SpeciesPage
from app.theme.widgets import PhotoGridItem

page = SpeciesPage(lib2, win)
page.resize(1400, 900)
page.show()
settle(300)

page._open_detail(B2)
settle(400)
assert page._mode == "detail" and len(page._sel_pool) == 3
items = page.findChildren(PhotoGridItem)
assert len(items) == 3, f"网格应3项, 实{len(items)}"

# 6) 多选: 点击翻转 + 计数
page._toggle_sel()
settle(300)
assert page._sel_mode
page._sel_click(page._sel_pool[0], page.findChildren(PhotoGridItem)[0])
assert len(page._sel) == 1
assert page._sel_cnt_lbl.text().startswith("已选 1")
print("6) 概览进入多选+点击选中+计数 ✓")

# 7) top5命中统计: 3张全带A2候选
assert page._top5_hit(sorted(page._sel_pool), A2) == 3
print("7) top5候选命中统计(低风险提示) ✓")

# 8) 批量改判(替身对话框返回A2, 确认框回Yes)
_FakePick.target = A2
page._sel |= set(page._sel_pool)
page._batch_change_species()
settle(400)
for pid in wrong2:
    assert eff(lib2.conn, pid) == [A2]
assert not page._sel and not page._sel_mode
assert {p["photo_id"] for p in lib2.photos_of_species(B2)} == set()
print("8) 批量改鸟种: 3张B→A, 页面状态复位 ✓")

# 9) 未识别: 多选批量标注
page._open_detail(Library.UNIDENTIFIED_CODE)
settle(400)
assert set(page._sel_pool) == set(unids)
page._toggle_sel()
settle(300)
items = page.findChildren(PhotoGridItem)
for i, pid in enumerate(unids):
    page._sel_click(pid, items[i])
_FakePick.target = A2
page._batch_annotate()
settle(400)
assert lib2.unidentified_photos() == []
for pid in unids:
    r = lib2.conn.execute("SELECT * FROM records WHERE photo_id=?",
                          (pid,)).fetchone()
    assert r["species_code"] == A2 and r["confirmed_code"] == A2 \
        and r["source"] == "manual"
print("9) 未识别整批标注manual记录 ✓")
page.close()
lib2.close()

# ================= 第三部分: 时间线批量挂鸟点 =================
print("---- 时间线: 多选→BatchSpotDialog ----")
import app.ui.spot_dialog as sd
from app.ui.timeline import TimelinePage

lib2 = Library(D2)
win = _Win()
page_t = TimelinePage(lib2, win)
page_t.resize(1400, 900)
page_t.show()
settle(300)
page_t.refresh(force=True)
settle(400)
page_t._toggle_select()
settle(400)
targets = right2
page_t._selected |= set(targets)
page_t._sync_sel_ui()
assert page_t.spot_btn.isEnabled()

sid2 = lib2.create_spot("挂载点", 40.1, 116.1)
_RealBatchDlg = sd.BatchSpotDialog   # 真类留底(下面要换成替身)


class _FakeBatchDlg:
    def __init__(self, lib_, win_, ids, note="", parent=None):
        self.photo_ids = list(ids)
        self.applied = False
        self.spot_name = None
        self._lib = lib_

    def exec(self):
        self._lib.set_photos_spot(self.photo_ids, sid2)
        self.applied = True
        return 1


sd.BatchSpotDialog = _FakeBatchDlg
page_t._batch_set_spot()
assert all(lib2.conn.execute("SELECT spot_id FROM photos WHERE id=?",
                             (p,)).fetchone()[0] == sid2 for p in targets)
assert page_t._selected == set(targets)   # 挂载不清选择, 可继续操作
print("10) 时间线多选→批量挂载 ✓ (选择保留)")

# 真·BatchSpotDialog的取消挂载按钮
lib2.set_photos_spot(targets, sid2)
sd.QMessageBox = _FakeMB
dlg = _RealBatchDlg(lib2, None, list(targets))
btns = [b for b in dlg.findChildren(QPushButton)
        if "取消挂载" in b.text() or "Unmount" in b.text()]
assert btns, "BatchSpotDialog应有取消挂载按钮"
btns[0].click()
settle(300)
assert dlg.applied
assert all(lib2.conn.execute("SELECT spot_id FROM photos WHERE id=?",
                             (p,)).fetchone()[0] is None for p in targets)
print("11) BatchSpotDialog取消挂载: 整批spot_id清空 ✓")
dlg.close()
page_t.close()
lib2.close()

print("\nBATCH_OPS ALL GREEN")
