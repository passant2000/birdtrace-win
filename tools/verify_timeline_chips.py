# -*- coding: utf-8 -*-
"""0.8.6时间线三件套功能级验证: 鸟种胶囊(树点击范围+点击筛选) /
缩略图说明(鸟种+鸟点) / 批量分享卡默认日期=当前选中节点。
真窗口平台跑(share/字体类教训)。"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, ".")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

app = QApplication([])
from app import theme, i18n
theme.apply_theme(app, "light")
i18n.set_lang("zh")
from app.db import Library
from app.ui.timeline_page import TimelinePage

FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


D = Path("data/_timeline_chips_check")
if D.exists():
    shutil.rmtree(D)
D.mkdir(parents=True)
from PIL import Image
import app.media as media

lib = Library(D)
lib.fill_species()
codes = [r["code"] for r in lib.conn.execute(
    "SELECT code FROM species LIMIT 2").fetchall()]
A, B = codes
na = lib.species_info(A)["cn"]
nb = lib.species_info(B)["cn"]
lib.conn.execute("INSERT INTO batches(region_id) VALUES('GLOBAL')")
bid = lib.conn.execute("SELECT id FROM batches").fetchone()["id"]
sid1 = lib.create_spot("傍霞村鸟点", 29.9, 118.3)
# 2026-05-10: A×2(挂鸟点)+B×1; 2026-05-11: A×1; 2026-06-01: B×1(未挂点)
plan = [("2026-05-10 08:00:00", A, sid1), ("2026-05-10 09:00:00", A, sid1),
        ("2026-05-10 10:00:00", B, None), ("2026-05-11 07:30:00", A, None),
        ("2026-06-01 15:00:00", B, sid1)]
pids = []
for i, (dt, code, sid) in enumerate(plan):
    p = D / f"t{i}.jpg"
    Image.new("RGB", (320, 240), (90, 120, 150)).save(p, "JPEG")
    pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                        p.stat().st_mtime, 320, 240, bid)
    lib.conn.execute(
        "INSERT INTO exif(photo_id, dt_original) VALUES(?,?)", (pid, dt))
    lib.add_records(pid, [{"species_code": code, "confidence": 0.9}])
    if sid:
        lib.set_photos_spot([pid], sid)
    pids.append(pid)
lib.conn.commit()

page = TimelinePage(lib, None)
page.resize(1200, 800)
page.show()
app.processEvents()

print("\n[1] 缩略图说明=鸟种+鸟点")
page.refresh(force=True)
app.processEvents()
cap_a = page._grid_items[pids[0]].label
cap_b = page._grid_items[pids[2]].label
check(na in cap_a and "傍霞村鸟点" in cap_a, f"A种+挂点: {cap_a}")
check(nb in cap_b and "傍霞村鸟点" not in cap_b,
      f"B种未挂点只显示鸟种: {cap_b}")

print("\n[2] 鸟种胶囊: 默认隐藏, 树点击出范围")


def find_item(key):
    from PySide6.QtWidgets import QTreeWidgetItemIterator
    it = QTreeWidgetItemIterator(page.tree_nav)
    while it.value() is not None:
        if it.value().data(0, Qt.UserRole) == key:
            return it.value()
        it += 1
    return None


check(page.chips_lay.count() == 0, "未点树→胶囊行隐藏")
d510 = find_item("2026-05|10")
check(d510 is not None, "树里有5月10日节点")
page._on_tree_click(d510, 0)
app.processEvents()
texts = [page.chips_lay.itemAt(i).widget().text()
         for i in range(page.chips_lay.count())
         if page.chips_lay.itemAt(i).widget() is not None]
check(any(x.startswith("全部 3") for x in texts), f"点10日→胶囊=当天3张: {texts}")
check(any(x.startswith(na + " ") for x in texts)
      and any(x.startswith(nb + " ") for x in texts),
      f"当天鸟种A×2+B×1: {texts}")

print("\n[3] 胶囊点击筛选(日模式=当天∩鸟种)与复位")
page._pick_species(B)          # 模拟点B胶囊(仍在5月10日day模式)
app.processEvents()
check(page._tl_sp == B and len(page._grid_items) == 1,
      f"日模式筛B→当天1张B (实际{len(page._grid_items)})")
b_chip = next(page.chips_lay.itemAt(i).widget()
              for i in range(page.chips_lay.count())
              if page.chips_lay.itemAt(i).widget() is not None
              and page.chips_lay.itemAt(i).widget().text().startswith(nb))
check(theme.BLUE in b_chip.styleSheet(), "被筛鸟种胶囊高亮")
page._pick_species(B)
app.processEvents()
check(page._tl_sp is None and len(page._grid_items) == 3,
      "再点B→恢复当天全部3张")

print("\n[4] 月份节点: 回月模式+胶囊=当月+整库筛选")
m5 = find_item("2026-05")
page._on_tree_click(m5, 0)
app.processEvents()
check(page._group_level == "month", "点月节点→回月模式(全部月份)")
texts3 = [page.chips_lay.itemAt(i).widget().text()
          for i in range(page.chips_lay.count())
          if page.chips_lay.itemAt(i).widget() is not None]
check(any(x.startswith("全部 4") for x in texts3), f"点5月→胶囊=当月4张: {texts3[:2]}")
page._pick_species(B)          # 月模式筛选=整库范围
app.processEvents()
check(page._tl_sp == B and len(page._grid_items) == 2,
      f"月模式筛B→整库2张B (实际{len(page._grid_items)})")
page._pick_species(B)
app.processEvents()
check(len(page._grid_items) == 5, "复位→整库5张")

print("\n[5] 批量分享卡默认日期=当前选中节点")
rng = page._sel_date_range()
check(rng == ("2026-05-01", "2026-05-31"), f"5月节点→整月范围: {rng}")
from app.ui.batch_share_dialog import BatchShareDialog
dlg = BatchShareDialog(lib, None, preset=rng)
check(dlg.from_date.date().toString("yyyy-MM-dd") == "2026-05-01"
      and dlg.to_date.date().toString("yyyy-MM-dd") == "2026-05-31",
      f"批量默认日期=选中月 ({dlg.from_date.date().toString('yyyy-MM-dd')}"
      f"~{dlg.to_date.date().toString('yyyy-MM-dd')})")
check(not any(b.isChecked() for b in dlg.quick_seg.buttons),
      "带预设时快捷段不点亮'今天'")
dlg.close()
d511 = find_item("2026-05|11")
page._on_tree_click(d511, 0)
rng2 = page._sel_date_range()
check(rng2 == ("2026-05-11", "2026-05-11"), f"日节点→单日范围: {rng2}")

page.hide()
lib.close()
print()
print("FAILED" if FAILED["v"] else "ALL PASS")
sys.exit(1 if FAILED["v"] else 0)
