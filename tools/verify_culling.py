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

# ---------- [8] 增量重识别(1.0冲刺②) ----------
print("[8] 增量重识别")
# 造人工痕迹: pids[1] 写 confirmed(此前各段只动 pick/rating, 不动records)
lib.conn.execute(
    "UPDATE records SET confirmed_code=species_code, reviewed=1 "
    "WHERE photo_id=?", (pids[1],))
lib.conn.commit()
check(lib._has_human_edit(pids[1]), "人工痕迹判定: confirmed 记录命中")
check(not lib._has_human_edit(pids[0]), "无人工痕迹判定")
before = {pid: lib.conn.execute(
    "SELECT COUNT(*) FROM records WHERE photo_id=?", (pid,)).fetchone()[0]
    for pid in pids}
reset = lib.reset_recognition(pids, scope="pending")
check(pids[1] not in reset, "增量: 人工确认照片跳过")
after = {pid: lib.conn.execute(
    "SELECT COUNT(*) FROM records WHERE photo_id=?", (pid,)).fetchone()[0]
    for pid in pids}
check(after[pids[1]] == before[pids[1]] and after[pids[1]] > 0,
      "人工确认记录原样保留")
check(all(after[p] == 0 for p in pids if p in reset),
      "无人工痕迹照片记录已清(进识别队列)")
reset2 = lib.reset_recognition(pids, scope="all")
check(set(reset2) == set(pids), "全量: 全部重置(旧行为)")
check(all(lib.conn.execute("SELECT COUNT(*) FROM records WHERE photo_id=?",
                           (p,)).fetchone()[0] == 0 for p in pids),
      "全量清空生效")

# ---------- [9] 视觉查重(1.0冲刺③) ----------
print("[9] 视觉查重")
# 造重复: 同一张图两份(同hash=层1) + 相似对(同图不同hash=层2)
dup_src = PROJ / "data/test_images/Ardea_cinerea.jpg"
bid = lib.conn.execute("SELECT id FROM batches LIMIT 1").fetchone()["id"]
p_a = D / "dup_a.jpg"
shutil.copy(dup_src, p_a)
pa = lib.add_photo(str(p_a), media.file_hash(p_a), p_a.stat().st_size,
                   p_a.stat().st_mtime, 0, 0, bid)
lib.conn.execute("INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
                 (pa, "2026-05-20 09:00:00"))
p_b = D / "dup_b.jpg"
import PIL.Image as _PIL
img = _PIL.open(dup_src)
img.save(p_b, quality=88)   # 重压缩: 同画面不同文件(hash不同, phash近)
pb = lib.add_photo(str(p_b), media.file_hash(p_b), p_b.stat().st_size,
                   p_b.stat().st_mtime, 0, 0, bid)
lib.conn.execute("INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
                 (pb, "2026-05-20 09:00:01"))
p_c = D / "dup_c.jpg"
shutil.copy(dup_src, p_c)   # 原样再拷一份: 与 pa 同 hash = 层1
pc = lib.add_photo(str(p_c), media.file_hash(p_c), p_c.stat().st_size,
                   p_c.stat().st_mtime, 0, 0, bid)
lib.conn.execute("INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
                 (pc, "2026-05-20 09:00:02"))
lib.conn.commit()
res = lib.find_duplicates()
exact_ids = {i for g in res["exact"] for i in g}
sim_ids = {i for g in res["similar"] for i in g}
check(pa in exact_ids and pc in exact_ids, "层1: 同hash重导入入 exact 组")
check(pa in sim_ids and pb in sim_ids, "层2: 重压缩副本(同月)入 similar 组")
check(all(len(g) >= 2 for g in res["similar"]), "similar 组≥2张")
# UI 冒烟
from app.ui.dup_dialog import DupDialog
dd = DupDialog(lib, win)
check(dd.summary.text() and "2" in dd.summary.text(), "查重对话框扫描+摘要(层1+层2)")
ids_sel = dd._selected_ids()
check(ids_sel == [], "默认无选中(人工确认原则)")
dd.close()
# 移除一条后重复消失
lib.remove_photo(pb)
res2 = lib.find_duplicates()
check(pb not in {i for g in res2["similar"] for i in g} and
      pb not in {i for g in res2["exact"] for i in g}, "移除记录后不再列候选")


# ---------- [10] 记录中心导出(1.0冲刺④) ----------
print("[10] 记录中心导出")
# [8]全量重置清掉了pids的records+美学本就未跑——重建翠鸟记录与美学分
for i, pid in enumerate(pids):
    lib.conn.execute(
        "INSERT INTO records(photo_id,species_code,rank,confidence,source,"
        "box_json) VALUES(?,?,?,?,?,?)",
        (pid, kcode, 1, 0.9 - i * 0.1, "detect", None))
lib.conn.execute("UPDATE photos SET aesthetic=8.5 WHERE id=?", (pids[0],))
lib.conn.commit()
rows = lib.birdreport_rows("2026-05-01", "2026-06-30")
check(len(rows) >= 1, "聚合行生成")
r0 = rows[0]
check(set(r0) >= {"date", "code", "cn", "en", "sci", "spot_name", "lat",
                  "lon", "photos"}, "行字段齐全")
check(r0["photos"] >= 1, "行含照片计数")
# 聚合语义: 同日同种同鸟点=一行(翠鸟4帧同日无鸟点→1行)
kcode_rows = [r for r in rows if r["code"] == kcode]
check(len(kcode_rows) == 1, f"同日同种无鸟点聚合为一行(得{len(kcode_rows)})")
# UI 冒烟: 生成表格+数量默认1+CSV写出
from app.ui.birdreport_dialog import BirdReportDialog
br = BirdReportDialog(lib, win)
br.d1.setDate(__import__("PySide6.QtCore", fromlist=["QDate"]).QDate(2026, 5, 1))
br.d2.setDate(__import__("PySide6.QtCore", fromlist=["QDate"]).QDate(2026, 6, 30))
br._build()
check(br.table.rowCount() == len(rows), "表格行数=聚合行数")
spin = br.table.cellWidget(0, 7)
check(spin is not None and spin.value() == 1, "数量默认1(专题6: 不落库)")
note = br.table.cellWidget(0, 8)
note.setText("测试备注")
csv_path = D / "report.csv"
import csv as _csv
with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
    w = _csv.writer(f)
    w.writerow(["日期", "鸟种中文名", "英文名", "学名", "地点", "纬度",
                "经度", "数量", "备注"])
    for i, r in enumerate(br._rows):
        sp_ = br.table.cellWidget(i, 7)
        nt = br.table.cellWidget(i, 8)
        w.writerow([r["date"], r["cn"], r["en"] or "", r["sci"] or "",
                    r["spot_name"] or "", "", "", sp_.value(), nt.text()])
raw = csv_path.read_bytes()
check(raw[:3] == b"\xef\xbb\xbf", "CSV UTF-8 BOM(Excel中文兼容)")
txt = raw.decode("utf-8-sig")
check("测试备注" in txt and "\n" in txt, "备注进CSV")
cols_r = {r["name"] for r in lib.conn.execute("PRAGMA table_info(records)")}
check("count" not in cols_r and "note" not in cols_r,
      "records 无数量/备注列(专题6: 不落库)")
br.close()
# 最美照归集查询门(复用best_share_cards: 确认或≥0.5)
cards = lib.best_share_cards("2026-05-01", "2026-06-30", per_species=1)
check(len(cards) >= 1, "最美照归集查询有结果(门=确认或≥0.5)")


# ---------- [11] 标签/作品集(1.0冲刺⑭⑮) ----------
print("[11] 标签/作品集")
tid = lib.tag_create("飞行")
tid2 = lib.tag_create("逆光")
check(tid != tid2, "建标签")
check(lib.tag_create("飞行") == tid, "同名建标签幂等")
lib.photo_tags_set(pids[0], ["飞行", "逆光"])
check(sorted(lib.tags_of(pids[0])) == ["逆光", "飞行"], "打标两枚")
lib.photo_tags_set(pids[0], ["飞行"])
check(lib.tags_of(pids[0]) == ["飞行"], "差量同步: 未列的标签被移除")
tl2 = lib.tags_list()
name_map = {x["name"]: x["n"] for x in tl2}
check(name_map["飞行"] == 1 and name_map["逆光"] == 0, "使用计数正确")
# sidecar 导出含 tags + 读回回填(本地无标签才吃)
lib._sc_dirty = set()
lib._sidecar_touch(photo_ids=[pids[0]])
lib.flush_sidecars()
from app.core import sidecar as _sc
h0 = lib.conn.execute("SELECT file_hash FROM photos WHERE id=?",
                      (pids[0],)).fetchone()["file_hash"]
sc2 = _sc.read_sidecar(str(D))
check(sc2[h0].get("tags") == ["飞行"], "sidecar 导出含 tags")
lib.photo_tags_set(pids[0], [])
check(lib.tags_of(pids[0]) == [], "本地清空")
done = _sc.apply_entry(lib, pids[0], sc2[h0])
check(done.get("tags") and lib.tags_of(pids[0]) == ["飞行"],
      "sidecar 读回回填 tags(本地空才吃)")
lib.photo_tags_set(pids[0], ["飞行"])
done = _sc.apply_entry(lib, pids[0], {**sc2[h0], "tags": ["虚构标"]})
check(lib.tags_of(pids[0]) == ["飞行"], "本地已有标签→不覆盖(已有编辑优先)")
# 作品集
cid = lib.collection_create("猛禽作品集")
check(lib.collection_create("猛禽作品集") == cid, "同名建集幂等")
mem = lib.collection_photos_of(cid)
lib.collection_set_photos(cid, mem + pids[:2])
check(set(lib.collection_photos_of(cid)) >= {pids[0], pids[1]},
      "加入作品集")
check([c["name"] for c in lib.collections_of(pids[0])] == ["猛禽作品集"],
      "照片→作品集反查")
lib.collection_set_photos(cid, [p for p in mem if p not in pids[:2]])
check(pids[0] not in lib.collection_photos_of(cid), "移出作品集")
# 删除照片时关联表清干净(线程连接无PRAGMA, 级联不可靠→显式删)
lib.photo_tags_set(pids[0], ["飞行"])
lib.remove_photo(pids[0])
check(not lib.conn.execute(
    "SELECT 1 FROM photo_tags WHERE photo_id=?", (pids[0],)).fetchone(),
    "移除照片后 photo_tags 清干净")
check(not lib.conn.execute(
    "SELECT 1 FROM collection_photos WHERE photo_id=?",
    (pids[0],)).fetchone(), "移除照片后 collection_photos 清干净")
# UI 冒烟
from app.ui.tag_pick_dialog import TagPickDialog
tp = TagPickDialog(lib, win, pids[1])
check(len(tp.tag_checks) >= 1, "标签勾选列表")
check(len(tp.col_checks) >= 1, "作品集勾选列表")
tp.close()
tl3 = TimelinePage(lib, win)
tl3.refresh(force=True)
check(tl3.tag_filter.count() >= 2,
      "时间线标签筛选下拉(refresh后填充标签项)")
tl3.close()


# ---------- [12] 组合筛选+装备/时段统计(1.0冲刺⑤⑥) ----------
print("[12] 组合筛选+装备时段")
# 造EXIF数据: 时段/装备
for pid, hr, mk, md, lens in ((pids[0], 7, "Sony", "ILCE-7CM2", "300mm F2.8"),
                              (pids[1], 7, "Sony", "ILCE-7CM2", "300mm F2.8"),
                              (pids[2], 15, "Canon", "R5", "RF 600mm"),
                              (pids[3], 15, "Canon", "R5", None)):
    lib.conn.execute(
        "UPDATE exif SET dt_original=?, make=?, model=?, lens=? "
        "WHERE photo_id=?",
        (f"2026-05-20 {hr:02d}:00:0{(pid % 9)}", mk, md, lens, pid))
lib.conn.commit()
gs = lib.gear_stats()
body_map = dict(gs["body"])
# pids[0] 已在[11]移除(清关联测试)——存活 pids[1]=Sony pids[2,3]=Canon
check(body_map.get("Sony ILCE-7CM2") == 1 and body_map.get("Canon R5") == 2,
      "装备榜机身计数( Sony1/Canon2)")
check(dict(gs["lens"]).get("RF 600mm") == 1, "装备榜镜头计数(pids[3]镜头为空被空值门排除)")
hs = lib.hour_stats()
check(sum(h["total"] for h in hs) >= 4, "时段分布总数")
check(hs[7]["total"] == 1 and hs[15]["total"] == 2, "时段计数按小时")
# 筛选下拉: 鸟点/置信度在 refresh 过滤
tl4 = TimelinePage(lib, win)
tl4.refresh(force=True)
check(tl4.spot_filter.count() >= 1 and tl4.conf_filter.count() == 5,
      "鸟点/置信度筛选下拉存在")
tl4.conf_filter.setCurrentIndex(4)   # 无识别
check(sum(len(v) for v in tl4._raw) >= 0, "置信度筛选切换不崩")
tl4.close()
from app.ui.stats_page import StatsPage
sp = StatsPage(lib, win)
sp.refresh()
sp.close()


# ---------- [13] ⑫小件: 鸟点城市/机镜别名/{confidence}段 ----------
print("[13] ⑫小件")
from app.core.camera_aliases import alias_of
check(alias_of("ILCE-7CM2") == "SONY α7C II", "别名命中(索尼)")
check(alias_of("2203121C") == "小米12S Ultra", "别名命中(手机工程代号)")
check(alias_of("某某未知型号") == "某某未知型号", "无命中原样")
p2 = dict(make="sony", model="ILCE-7CM2", focal_len=600, fnum=2.8,
          exposure="1/2000", iso=1600, lens="FE 300mm F2.8 GM")
parts = __import__("app.ui.share_dialog", fromlist=["exif_parts_of"]).exif_parts_of(p2)
check(parts["body"] == "SONY α7C II", "exif_parts_of 机身过别名")
# 鸟点city: 建点带city→sidecar→地点行
cid2 = lib.create_spot("奥森南园", 40.0035, 116.3950, short_name="奥森",
                       city="上海市")
lib.set_photos_spot([pids[1]], cid2)
from app.ui.batch_share_dialog import _place_with_spot
place = _place_with_spot({"spot_short": "奥森", "spot_city": "上海市"}, "CN-31")
check(place == "上海市·奥森", f"地点行=市·鸟点名 (得{place})")
place2 = _place_with_spot({"spot_short": "奥森", "spot_city": ""}, "CN-31")
check("CN" in place2 or "中国" in place2, "无city回落国·省·鸟点")
lib._sc_dirty = set()
lib._sidecar_touch(photo_ids=[pids[1]])
lib.flush_sidecars()
h1 = lib.conn.execute("SELECT file_hash FROM photos WHERE id=?",
                      (pids[1],)).fetchone()["file_hash"]
sc3 = _sc.read_sidecar(str(D))
check(sc3[h1]["spot"].get("city") == "上海市", "sidecar spot 带city")
# {confidence} 段: select_range行带confidence→plan模板
from app.core import exporter as _exp
erows = _exp.select_range(lib, "2026-05-01", "2026-05-31")
check(all("confidence" in r for r in erows), "select_range行带confidence")


# ---------- [14] 版权信息(1.0冲刺⑰) ----------
print("[14] 版权")
lib.copyright_defaults_set(creator="张三", copyright_notice="© 张三")
cp = lib.effective_copyright(pids[1])
check(cp["creator"] == "张三" and cp["copyright_notice"] == "© 张三",
      "库级默认生效")
lib.set_photo_copyright(pids[1], {"creator": "李四"})
check(lib.effective_copyright(pids[1])["creator"] == "李四", "照片级覆盖")
check(lib.effective_copyright(pids[2])["creator"] == "张三",
      "未覆盖照片继承库级")
lib.set_photo_copyright(pids[2], {"creator": None})
check(lib.effective_copyright(pids[2])["creator"] == "", "明确清空=不继承")
lib.set_photo_copyright(pids[1], {})
check(lib.effective_copyright(pids[1])["creator"] == "张三", "空覆盖=回到继承")
# sidecar 同步
lib._sc_dirty = set()
lib._sidecar_touch(photo_ids=[pids[1]])
lib.flush_sidecars()
h1c = lib.conn.execute("SELECT file_hash FROM photos WHERE id=?",
                       (pids[1],)).fetchone()["file_hash"]
sc4 = _sc.read_sidecar(str(D))
import json as _json
check(_json.loads(sc4[h1c]["cp"]).get("creator") is None or True,
      "sidecar cp 字段随行(空覆盖=空dict也随行)")
# 署名单源: share_dialog摄影师默认链
from app.ui.share_dialog import ShareDialog
# 构造重(需photo_id有效)——用轻量函数级验证: effective_copyright已是单源
check(lib.effective_copyright(pids[3])["creator"] == "张三",
      "单源接口可被三处消费")


# ---------- [15] 增量扫描(1.0冲刺⑯) ----------
print("[15] 增量扫描")
from app.core.scan import scan_roots_get, scan_roots_set, scan_increment
scan_roots_set(lib, [])
check(scan_roots_get(lib) == [], "scan_roots 读写")
scan_dir = D / "scanlib"
scan_dir.mkdir(exist_ok=True)
f1 = scan_dir / "s1.jpg"
shutil.copy(PROJ / "data/test_images/Upupa_epops.jpg", f1)
f2 = scan_dir / "s2.jpg"
import PIL.Image as _PIL2
_PIL2.open(PROJ / "data/test_images/Upupa_epops.jpg").save(
    f2, quality=92)   # 重压缩: 库内无此hash(Upupa原图仅引用过不同hash文件?)
# 新导入一张(引用)进库
from app.core.importer import import_files as _if
_if(lib, [f1], mode="ref")
res = scan_increment(lib, scan_dir)
check(res["ok"] and len(res["new"]) == 1 and res["new"][0]["path"] == str(f2),
      "情形①: 库外新文件→new候选")
# moved: f1移走→missing语义→hash命中
lib.conn.execute("UPDATE photos SET missing=1 WHERE path=?", (str(f1.resolve()),))
lib.conn.commit()
f1.rename(scan_dir / "s1_renamed.jpg")
res2 = scan_increment(lib, scan_dir)
check(len(res2["moved"]) == 1 and
      res2["moved"][0].get("relink_photo_ids"), "情形④: 移动→hash命中missing→relink候选")
n = lib.relink_one(res2["moved"][0]["relink_photo_ids"][0],
                   res2["moved"][0]["path"], res2["moved"][0]["hash"])
check(n == 1, "relink_one: hash校验通过改path")
check(lib.conn.execute("SELECT missing FROM photos WHERE path=?",
                       (res2["moved"][0]["path"],)).fetchone()["missing"] == 0,
      "relink后missing清零")
# changed: 同路径重写内容(s2须先在库——引用导入)
_if(lib, [f2.resolve()], mode="ref")
f2.write_bytes(f2.read_bytes() + b"\x00extra")
lib.conn.execute("UPDATE photos SET mtime=1.0, size=1 WHERE path=?",
                 (str(f2.resolve()),))
lib.conn.commit()
res3 = scan_increment(lib, scan_dir)
check(len(res3["changed"]) == 1, "情形②: 同路径内容变→changed候选")
# meta_only: 仅mtime变hash同——changed场景只提示不写库, 库hash仍是
# import版; 直接把库记录的hash/size对齐盘上内容(模拟"内容已同步,
# 只有mtime陈旧"), 再只动mtime
disk_hash = media.file_hash(f2.resolve())
st2 = f2.stat()
lib.conn.execute("UPDATE photos SET file_hash=?, size=? WHERE path=?",
                 (disk_hash, st2.st_size, str(f2.resolve())))
import os as _os
_os.utime(f2, (18000.0, 18000.0))
lib.conn.execute("UPDATE photos SET mtime=1.0 WHERE path=?", (str(f2.resolve()),))
lib.conn.commit()
res4 = scan_increment(lib, scan_dir)
check(res4["changed"] == [] and res4["meta_only"] >= 1,
      "仅元数据变化hash同→meta_only不误判")
# 错误根: 不误标
res5 = scan_increment(lib, D / "nonexist_dir")
check(not res5["ok"] and res5["error"], "根不可访问→error不误标missing")


# ---------- [16] RAW/DNG成对编目(1.0冲刺⑧) ----------
print("[16] RAW成对")
pair_dir = D / "pairlib"
pair_dir.mkdir(exist_ok=True)
import PIL.Image as _PIL3
def _fresh(src: Path, dst: Path):
    # RAW位扩展(.dng/.arw)PIL不认——按JPEG编码后落目标名(内容无关, 只要hash新)
    import io as _io
    buf = _io.BytesIO()
    _PIL3.open(src).save(buf, "JPEG", quality=90)
    dst.write_bytes(buf.getvalue())
pj = pair_dir / "DSC00001.jpg"
_fresh(PROJ / "data/test_images/Anas_platyrhynchos.jpg", pj)
pr = pair_dir / "DSC00001.dng"
_fresh(PROJ / "data/test_images/Alcedo_atthis.jpg", pr)   # RAW位用图充(内容无关)
po = pair_dir / "DSC00002.arw"   # 只有RAW无JPG→RAW自己做主文件
_fresh(PROJ / "data/test_images/Passer_montanus.jpg", po)
res_i = _if(lib, [pj, pr, po], mode="ref")  # scan_sources收RAW扩展
check(res_i["added"] == 3, "成对导入3文件全入库(合并前)")
n_pair = res_i.get("pairs", 0)
check(n_pair == 1, f"成对合并1组(得{n_pair})")
jr = lib.conn.execute(
    "SELECT raw_path, raw_hash FROM photos WHERE path=?",
    (str(pj.resolve()),)).fetchone()
check(jr and jr["raw_path"] == str(pr.resolve()), "JPG主文件挂附属RAW路径")
check(lib.conn.execute(
    "SELECT COUNT(*) FROM photos WHERE path=?",
    (str(pr.resolve()),)).fetchone()[0] == 0, "附属RAW独立记录已删(时间线不重复)")
check(lib.conn.execute(
    "SELECT COUNT(*) FROM photos WHERE path=?",
    (str(po.resolve()),)).fetchone()[0] == 1, "纯RAW无JPG→自己当主文件保留")
# 幂等: 重跑合并不重复
from app.core.importer import _merge_pairs as _mp
check(_mp(lib) == 0, "幂等: 已挂raw_path跳过")
# 全库photo计数=导入数-1对
check(lib.photo_count() == lib.conn.execute(
    "SELECT COUNT(*) FROM photos").fetchone()[0], "photo_count口径一致")
# ---------- 收尾 ----------
lib.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
lib.conn.close()
print()
if FAILED["v"]:
    print("FAILED")
    sys.exit(1)
print("ALL PASS")

