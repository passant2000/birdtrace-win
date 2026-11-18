# -*- coding: utf-8 -*-
"""1.0冲刺①+⑨ 选片工作流功能级验证:
数据层(set_rating/set_pick/quarantine 三件/拆合组+重算锁定保护/
sidecar pick同步/已有编辑优先/旧格式读回) + exporter pick筛选 +
UI冒烟(PhotoGridItem星级三态角标/时间线筛选与快捷键/查看器选片块/
组内对比推荐三档/隔离区对话框)。真窗口平台跑; 不跑模型, 约20~40秒。"""
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
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


D = Path("data/_culling_check")
if D.exists():
    shutil.rmtree(D)
D.mkdir(parents=True)
import app.media as media
from app.db import Library
from app.core.importer import import_files

# ---------- [1] 库迁移: 新列+quarantine表+重开幂等 ----------
print("[1] 迁移")
lib = Library(D)
lib.fill_species()
cols = {r["name"] for r in lib.conn.execute("PRAGMA table_info(photos)")}
check({"pick", "pick_note", "group_lock"} <= cols, "photos 加列 pick/pick_note/group_lock")
qtab = lib.conn.execute(
    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='quarantine'").fetchone()
check(bool(qtab), "quarantine 表已建")
lib2 = Library(D)   # 二次打开: 幂等不报错
cols2 = {r["name"] for r in lib2.conn.execute("PRAGMA table_info(photos)")}
check(cols == cols2, "重开库幂等(列集不变)")
lib2.conn.close()

# ---------- 测试数据: 4张不同图(连拍形态靠EXIF时间链+识别记录手工
# 插同种; 必须不同文件——同hash会被sidecar按hash键覆盖成一条)+1张异种
import_files(lib, [PROJ / "data/test_images/Alcedo_atthis.jpg"],
            mode="copy", dest_root=D / "src", region_id="CN")
row = lib.conn.execute("SELECT id FROM batches LIMIT 1").fetchone()
IMGS = ["Alcedo_atthis.jpg", "Anas_platyrhynchos.jpg", "Ardea_cinerea.jpg",
        "Cyanistes_caeruleus.jpg"]
pids = []
for i in range(4):
    p = D / f"b{i}.jpg"
    shutil.copy(PROJ / "data/test_images" / IMGS[i], p)
    pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                        p.stat().st_mtime, 0, 0, row["id"])
    lib.conn.execute(
        "INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
        (pid, f"2026-05-20 08:00:0{i}"))
    pids.append(pid)
sp = D / "sparrow.jpg"
shutil.copy(PROJ / "data/test_images/Passer_montanus.jpg", sp)
spid = lib.add_photo(str(sp), media.file_hash(sp), sp.stat().st_size,
                     sp.stat().st_mtime, 0, 0, row["id"])
lib.conn.execute(
    "INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
    (spid, "2026-06-01 10:00:00"))
# 识别记录(手工插, 不跑引擎): 翠鸟4张 rank1 + 置信度不同;
# 翠鸟码用动态查询(species表验证过的code, 不硬编码)
kcode = lib.conn.execute(
    "SELECT code FROM species WHERE en LIKE '%kingfisher%' OR code='comkin1' "
    "LIMIT 1").fetchone()["code"]
ocode = lib.conn.execute(
    "SELECT code FROM species WHERE code<>? LIMIT 1", (kcode,)).fetchone()["code"]
for i, pid in enumerate(pids):
    lib.conn.execute(
        "INSERT INTO records(photo_id,species_code,rank,confidence,source,"
        "box_json) VALUES(?,?,?,?,?,?)",
        (pid, kcode, 1, 0.9 - i * 0.1, "detect",
         json.dumps([100, 100, 800, 800 + i * 300])))
lib.conn.execute(
    "INSERT INTO records(photo_id,species_code,rank,confidence,source) "
    "VALUES(?,?,?,?,?)", (spid, ocode, 1, 0.8, "detect"))
lib.conn.commit()

# ---------- [2] set_rating / set_pick ----------
print("[2] 评分与三态")
check(lib.set_rating(pids[:2], 4) == 2, "set_rating 批量2张")
r = lib.conn.execute("SELECT rating FROM photos WHERE id=?",
                     (pids[0],)).fetchone()["rating"]
check(r == 4, "星级落库")
lib.set_rating(pids[:1], 0)
r = lib.conn.execute("SELECT rating FROM photos WHERE id=?",
                     (pids[0],)).fetchone()["rating"]
check(r == 0, "清星")
lib.set_rating(pids[:1], 9)   # 越界: 实现为夹取不抛异常
r = lib.conn.execute("SELECT rating FROM photos WHERE id=?",
                     (pids[0],)).fetchone()["rating"]
check(r == 5, "越界9被夹到5")
try:
    lib.set_pick(pids[:1], "bad")
    check(False, "非法三态值被拒绝")
except ValueError:
    check(True, "非法三态值被拒绝")
lib.set_pick(pids[:2], "keep", "构图最佳")
lib.set_pick(pids[2:3], "reject", "糊了")
rows = {r2["id"]: r2 for r2 in lib.conn.execute(
    "SELECT id, pick, pick_note FROM photos")}
check(rows[pids[0]]["pick"] == "keep" and rows[pids[0]]["pick_note"] == "构图最佳",
      "三态+备注落库")
check(rows[pids[2]]["pick"] == "reject", "拒绝态落库")
lib.set_pick(pids[0:1], "")
rows = {r2["id"]: r2 for r2 in lib.conn.execute(
    "SELECT id, pick, pick_note FROM photos")}
check(rows[pids[0]]["pick"] == "" and rows[pids[0]]["pick_note"] == "",
      "清态同时清备注")

# ---------- [3] sidecar: 导出含pick + 已有编辑优先 + 旧格式读回 ----------
print("[3] sidecar 同步")
from app.core import sidecar
folder = str(D)   # 手动造的照片 path=D/b*.jpg, sidecar 在库根目录
lib._sidecar_dirty = set()
for pid in pids + [spid]:
    lib._sidecar_touch(photo_ids=[pid])
lib.flush_sidecars()
sc = sidecar.read_sidecar(folder)
keys = [r["file_hash"] for r in lib.conn.execute(
    "SELECT file_hash FROM photos WHERE id IN "
    f"({','.join(str(i) for i in pids)})")]
check(any(e.get("pick") == "reject" for h, e in sc.items()),
      "sidecar 导出含 pick=reject")
check(any(e.get("pick_note") == "糊了" for h, e in sc.items()),
      "sidecar 导出含 pick_note")
# 已有编辑优先: 本地空的照片回填; 本地已标记不动
pid_b, pid_c = pids[3], pids[2]   # b3 未打标(回填对象), b2 已标 reject(保护对象)
h_b = lib.conn.execute("SELECT file_hash FROM photos WHERE id=?",
                       (pid_b,)).fetchone()["file_hash"]
fake = dict(sc[h_b]); fake["pick"] = "pending"; fake["pick_note"] = "来自另一台机器"
done = sidecar.apply_entry(lib, pid_b, fake)
check(done.get("pick"), "本地未标 → 回填 pick")
check(lib.conn.execute("SELECT pick FROM photos WHERE id=?",
                       (pid_b,)).fetchone()["pick"] == "pending", "回填值正确")
done = sidecar.apply_entry(lib, pid_c, fake)
check(not done.get("pick"), "本地已标记 → 不覆盖(已有编辑优先)")
# 旧格式(无pick字段)读回不崩
done = sidecar.apply_entry(lib, pids[3], {"records": [], "no_bird": False,
                                          "rating": 0})
check(isinstance(done, dict), "旧格式 sidecar 条目读回不崩")

# ---------- [4] 隔离区: 移动/恢复/绝不覆盖 ----------
print("[4] 隔离区")
rejects = [pids[2]]
res = lib.quarantine_move(rejects)
check(len(res["moved"]) == 1, "隔离移动1张")
qrow = lib.conn.execute(
    "SELECT * FROM quarantine WHERE photo_id=?", (pids[2],)).fetchone()
check(qrow is not None, "quarantine 记录写入")
check(Path(qrow["quar_path"]).is_file(), "文件已移入隔离区目录")
check(qrow["quar_path"] == lib.conn.execute(
    "SELECT path FROM photos WHERE id=?", (pids[2],)).fetchone()["path"],
    "库path已同步更新")
check("隔离区" in qrow["quar_path"], "落点在 <库>/隔离区/")
cnt = lib.conn.execute("SELECT COUNT(*) FROM records WHERE photo_id=?",
                       (pids[2],)).fetchone()[0]
check(cnt == 1, "识别记录保留")
res = lib.quarantine_move([pids[2], 99999])
check(len(res["failed"]) == 2, "已在隔离区/无记录 → 跳过并记原因")
# 恢复: 原路径被占 → 拒绝绝不覆盖
orig = Path(qrow["orig_path"])
orig.parent.mkdir(parents=True, exist_ok=True)
shutil.copy(qrow["quar_path"], orig)   # 模拟用户把同hash文件放回原位
qid = qrow["id"]
res = lib.quarantine_restore([qid])
check(len(res["failed"]) == 1 and "占用" in res["failed"][0][1],
      "原路径被占 → 恢复拒绝(绝不覆盖)")
orig.unlink()
res = lib.quarantine_restore([qid])
check(len(res["restored"]) == 1, "原路径空闲 → 恢复成功")
check(orig.is_file(), "文件回到原路径")
check(lib.conn.execute("SELECT path FROM photos WHERE id=?",
                       (pids[2],)).fetchone()["path"] == str(orig),
      "库path回写原路径")
check(lib.conn.execute(
    "SELECT restored_at FROM quarantine WHERE id=?",
    (qid,)).fetchone()["restored_at"] is not None, "恢复时间落库")
# 恢复后可再次隔离(条目不冲突)
res = lib.quarantine_move([pids[2]])
check(len(res["moved"]) == 1, "恢复后可再次隔离")
left = lib.quarantine_list()
check(len(left) == 1, "隔离清单1条")
res = lib.quarantine_restore([left[0]["id"]])
check(len(res["restored"]) == 1, "清场: 恢复成功")
check(not lib.quarantine_list(), "清场: 隔离区空")

# ---------- [5] 拆组/合组 + 重算锁定保护 ----------
print("[5] 拆合组")
lib.conn.execute(
    f"UPDATE photos SET group_id='gtest', group_lock=0 WHERE id IN "
    f"({','.join(str(p) for p in pids)})")
lib.conn.commit()
lib.split_from_group([pids[3]])
row = lib.conn.execute("SELECT group_id, group_lock FROM photos WHERE id=?",
                       (pids[3],)).fetchone()
check(row["group_id"] is None and row["group_lock"] == 1, "拆组: 脱组+锁定")
res = lib.regroup_bursts()
row = lib.conn.execute("SELECT group_id, group_lock FROM photos WHERE id=?",
                       (pids[3],)).fetchone()
check(row["group_id"] is None and row["group_lock"] == 1,
      "重算后锁定照片不被重新分配")
row = lib.conn.execute("SELECT group_lock FROM photos WHERE id=?",
                       (pids[0],)).fetchone()
check(row["group_lock"] == 0, "未锁成员不被误锁(重算主权=自动规则)")
lib.merge_into_group(pids)
row = lib.conn.execute("SELECT group_id, group_lock FROM photos WHERE id=?",
                       (pids[3],)).fetchone()
check(row["group_id"] == f"g{min(pids)}" and row["group_lock"] == 1,
      "合组: 统一组号+整组锁定")
lib.unlock_group(pids)
row = lib.conn.execute("SELECT group_lock FROM photos WHERE id=?",
                       (pids[0],)).fetchone()
check(row["group_lock"] == 0, "解锁")
lib.regroup_bursts()   # 自动重算归位(时间链1s内应成组)

# ---------- [6] exporter pick 筛选 ----------
print("[6] 导出筛选")
from app.core import exporter
all_rows = exporter.select_range(lib, pick_filter=None)
ex_rej = exporter.select_range(lib, pick_filter="!reject")
only_rej = exporter.select_range(lib, pick_filter="reject")
only_keep = exporter.select_range(lib, pick_filter="keep")
ids_all = {r["photo_id"] for r in all_rows}
ids_exrej = {r["photo_id"] for r in ex_rej}
ids_rej = {r["photo_id"] for r in only_rej}
ids_keep = {r["photo_id"] for r in only_keep}
check(pids[2] not in ids_exrej and pids[2] in ids_all,
      "排除拒绝: 拒绝片不在结果, 全量在")
check(pids[2] in ids_rej and ids_rej <= ids_all, "仅拒绝: 只含拒绝片")
check(pids[1] in ids_keep and not (ids_keep & ids_rej), "仅保留与仅拒绝不相交")

# ---------- [7] UI 冒烟 ----------
print("[7] UI 冒烟")
# [5]解锁后的重算按自动规则(时间+种+dHash相似)可能打散4张不同图的
# 手动组——对比对话框需要一组, 重新手动指定(锁不锁无所谓, 只读)
lib.conn.execute(
    f"UPDATE photos SET group_id='gtest' WHERE id IN "
    f"({','.join(str(p) for p in pids)})")
lib.conn.commit()
from PySide6.QtCore import QMargins
from PySide6.QtGui import QPixmap
from app.theme.widgets import PhotoGridItem
pm = QPixmap(PROJ / "data/test_images/Alcedo_atthis.jpg")
it = PhotoGridItem(pm, stars=3, pick="reject", tile=132)
px = it.grab()
c0 = px.toImage().pixelColor(8, 8)
check(not px.isNull() and px.width() == 132, "网格项角标渲染不崩")
it2 = PhotoGridItem(pm, stars=0, pick="", tile=132)
check(it2.grab().toImage() is not None, "无角标网格项正常")
it3 = PhotoGridItem(pm, stars=5, pick="keep", tile=320)
check(it3.grab().width() == 320, "大档位正常")

# 时间线页: 筛选下拉与快捷键绑定存在
from app.ui.timeline_page import TimelinePage
from PySide6.QtWidgets import QWidget
win = QWidget()
win.pages = {}
win.assets = None
tl = TimelinePage(lib, win)
check(hasattr(tl, "rating_filter") and hasattr(tl, "pick_filter"),
      "时间线评分/选片筛选下拉存在")
check(tl.rating_filter.count() == 7 and tl.pick_filter.count() == 5,
      "筛选档位齐全(7+5)")
check(hasattr(tl, "mark_btn") and hasattr(tl, "quar_btn"),
      "工具条标记/隔离区按钮存在")
tl._rate_apply(4)
check(True, "快捷键handler(无选中时安全无操作)")

# 查看器选片块
from app.ui.viewer import PhotoViewer
v = PhotoViewer(lib, win, pids[1], pids)
check(hasattr(v, "star_btns") and len(v.star_btns) == 5, "查看器星级按钮行")
check(set(v.pick_btns) == {"keep", "pending", "reject", ""},
      "查看器三态按钮行")
v._rate(2)
check(lib.conn.execute("SELECT rating FROM photos WHERE id=?",
                       (pids[1],)).fetchone()["rating"] == 2, "查看器打星落库")
v._pick("keep")
check(lib.conn.execute("SELECT pick FROM photos WHERE id=?",
                       (pids[1],)).fetchone()["pick"] == "keep", "查看器三态落库")
v.pick_note_edit.setText("备注测试")
v._note_started()
v._note_commit()
check(lib.conn.execute("SELECT pick_note FROM photos WHERE id=?",
                       (pids[1],)).fetchone()["pick_note"] == "备注测试",
      "查看器备注提交")
v.close()

# 组内对比: 推荐三档(含varied触发——box_ratio差异大)
from app.ui.compare_dialog import CompareDialog
cd = CompareDialog(lib, win, pids[0])
check(len(cd.frames) == 4, "对比载入全组4帧")
check(len(cd.ranked) == 4 and cd.rec_state == "ok",
      "稳妥模式: 主体尺度差异未超阈→不触发降级, 正常排序")
cd._mode_changed(0)
st0 = cd.rec_state
cd.mode_combo.setCurrentIndex(2)
check(len(cd.ranked) == 3 and cd.rec_state == "loose", "宽松模式: 荐3张")
cd.mode_combo.setCurrentIndex(1)
check(cd.rec_state == "ok", "辅助模式: 正常排序")
cd._rate(5)
check(lib.conn.execute("SELECT rating FROM photos WHERE id=?",
                       (cd.frames[cd.a_idx]["id"],)).fetchone()["rating"] == 5,
      "对比对话框A格打星落库")
cd.close()

# 隔离区对话框: 列表渲染
from app.ui.quarantine_dialog import QuarantineDialog
qd = QuarantineDialog(lib, win, selected=[pids[0]])
check(qd.preview_tree is not None and qd.preview_tree.topLevelItemCount() == 1,
      "待移入预览清单")
check(qd.tree.topLevelItemCount() >= 0, "已隔离列表渲染")
qd.close()

# ---------- 收尾 ----------
lib.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
lib.conn.close()
print()
if FAILED["v"]:
    print("FAILED")
    sys.exit(1)
print("ALL PASS")
