# -*- coding: utf-8 -*-
"""时间线：树删除后刷新 / 按日期选择 / Shift范围选择 验证。"""
import sys
import shutil
import sqlite3
from pathlib import Path

sys.path.insert(0, ".")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QEventLoop, QTimer

app = QApplication([])
from app import theme, i18n
theme.apply_theme(app, "light")
i18n.set_lang("zh")
from app.db import Library
from app.ui.timeline_page import TimelinePage

SRC = Path("C:/Users/zhaohp2116/Documents/BirdTraceWin/catalog.db")
D = Path("data/_timeline_feature_check")
if D.exists():
    shutil.rmtree(D)
D.mkdir(parents=True)

def _seed_synthetic(lib_d: Path, n: int = 30):
    """源库为空时的合成库兜底(2026-11-05: 用户正式测试库清空后脚本
    无法运行——外部依赖脆弱, 补自洽路径)。"""
    from PIL import Image
    lib2 = Library(lib_d)
    lib2.fill_species()
    codes = [r["code"] for r in lib2.conn.execute(
        "SELECT code FROM species LIMIT 3").fetchall()]
    lib2.conn.execute("INSERT INTO batches(region_id) VALUES('GLOBAL')")
    bid = lib2.conn.execute("SELECT id FROM batches").fetchone()["id"]
    import app.media as media
    for i in range(n):
        p = lib_d / "src" / f"t{i}.jpg"
        p.parent.mkdir(exist_ok=True)
        im = Image.new("RGB", (320, 240), (80 + i * 3 % 120, 110, 150))
        im.save(p, "JPEG")
        pid = lib2.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                             p.stat().st_mtime, 320, 240, bid)
        lib2.conn.execute(
            "INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
            (pid, f"2026-10-{20 + i % 5:02d} 10:00:00"))
        lib2.add_records(pid, [{"species_code": codes[i % 3],
                                "confidence": 0.8}])
    lib2.conn.commit()
    lib2.close()


if SRC.exists() and sqlite3.connect(SRC).execute(
        "SELECT COUNT(*) FROM photos").fetchone()[0] > 10:
    shutil.copy2(SRC, D / "catalog.db")
    lib = Library(D)
    # 测试库原本只有同一天: 人为分散到5天, 便于验证日期选择与树刷新
    _ids = [r["id"] for r in lib.conn.execute(
        "SELECT id FROM photos ORDER BY id")]
    for _i, _pid in enumerate(_ids):
        lib.conn.execute("UPDATE exif SET dt_original=? WHERE photo_id=?",
                         (f"2026-10-{20 + _i % 5:02d} 10:00:00", _pid))
    lib.conn.commit()
else:
    _seed_synthetic(D)
    lib = Library(D)

page = TimelinePage(lib, None)
page.resize(1400, 900)
page.show()


def settle(ms=300):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


page.refresh(force=True)
settle(800)
# 连拍折叠(0.8-③)后浏览视图是折叠集; 日期/范围选择都在多选模式(展开集)下
# 执行——统计时点必须在 toggle_select 之后(2026-11-04正式库出现连拍后暴露)
page._toggle_select()
settle(600)
order = list(page._order_ids)
dates = dict(page._iso_dates)
print("照片数(展开):", len(order), "| 日期种类:", len(set(dates.values())))
assert len(order) > 20
tree_before = page.tree_nav.topLevelItemCount()
print("树顶层(年)数:", tree_before)

# ---- 1) 按日期选择 ----
day = sorted(set(dates.values()))[3]
expect = sum(1 for d in dates.values() if d == day)
page._select_date_range(day, day, append=False)
print(f"日期选择 {day}: 选中{len(page._selected)} 预期{expect}")
assert len(page._selected) == expect and expect > 0
# 追加模式
day2 = sorted(set(dates.values()))[4]
exp2 = sum(1 for d in dates.values() if d == day2)
page._select_date_range(day2, day2, append=True)
print(f"追加 {day2}: 选中{len(page._selected)} 预期{expect+exp2}")
assert len(page._selected) == expect + exp2

# ---- 2) Shift 范围选择 ----
page._toggle_select()          # 退出
page._toggle_select()          # 重新进入(清空)
assert not page._selected
page._select_range(order[0], order[4])
print("Shift范围 0..4: 选中", len(page._selected))
assert page._selected == set(order[:5])

# ---- 3) 部分删除后树刷新 ----
page._toggle_select()          # 退出选择
victim = order[0]
month_key = dates[victim][:7]
before_month = None
for i in range(page.tree_nav.topLevelItemCount()):
    y = page.tree_nav.topLevelItem(i)
    for j in range(y.childCount()):
        if y.child(j).data(0, Qt.UserRole) == month_key:
            before_month = y.child(j).text(0)
lib.remove_photo(victim)
page.refresh()
settle(500)
after_month = None
for i in range(page.tree_nav.topLevelItemCount()):
    y = page.tree_nav.topLevelItem(i)
    for j in range(y.childCount()):
        if y.child(j).data(0, Qt.UserRole) == month_key:
            after_month = y.child(j).text(0)
print(f"部分删除 月节点: '{before_month}' -> '{after_month}'")
assert before_month != after_month, "月节点张数未刷新"

# ---- 4) 全选删除后树必须清空(原bug) ----
for pid in [r["id"] for r in lib.conn.execute("SELECT id FROM photos")]:
    lib.remove_photo(pid)
page.refresh()
settle(500)
print("全删后: 照片", len(page._order_ids), "树顶层", page.tree_nav.topLevelItemCount(),
      "标题", page.title.text())
assert page.tree_nav.topLevelItemCount() == 0, "全删后树仍残留(原bug)"
assert "0 张" in page.title.text()
print("ALL PASS")
