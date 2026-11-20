# -*- coding: utf-8 -*-
"""UI重设计c5 观鸟生涯页功能级验证:
db(lifer_feed编号连续+地点回落链+年鸟标记 / day_counts与timeline同口径 /
province_species_counts) + UI冒烟(四Tab构建/里程碑/热力图/装备榜过别名+
同别名聚合/徽章解锁数据不变/足迹payload注入) + 生涯清单CSV导出数据链。
真窗口平台跑; 不跑模型, 约10~20秒。"""
from __future__ import annotations

import json
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


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme, i18n
    theme.apply_theme(app, "light")
    i18n.set_lang("zh")

    D = PROJ / "data/_life_check"
    if D.exists():
        shutil.rmtree(D)
    D.mkdir(parents=True)
    from app.db import Library
    import app.media as media
    lib = Library(D)
    lib.fill_species()

    # ---------- 测试数据: 5张3种(2张跨年) + 鸟点 + EXIF器材 ----------
    lib.conn.execute(
        "INSERT INTO batches(mode, dest, region_id, count) "
        "VALUES('copy',?, 'CN-BJ', 5)", (str(D / "src"),))
    row = lib.conn.execute("SELECT id FROM batches LIMIT 1").fetchone()
    IMGS = ["Alcedo_atthis.jpg", "Anas_platyrhynchos.jpg",
            "Ardea_cinerea.jpg", "Cyanistes_caeruleus.jpg",
            "Passer_montanus.jpg"]
    pids = []
    for i in range(5):
        p = D / f"b{i}.jpg"
        shutil.copy(PROJ / "data/test_images" / IMGS[i], p)
        pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                            p.stat().st_mtime, 0, 0, row["id"])
        lib.conn.execute(
            "INSERT INTO exif(photo_id, dt_original, make, model, lens) "
            "VALUES(?,?,?,?,?)",
            (pid, f"2026-0{i + 1}-15 08:00:0{i}",
             "Sony" if i < 2 else "Canon", "ILCE-7CM2" if i < 2 else "R5",
             "FE 300mm" if i < 2 else "RF 600mm"))
        pids.append(pid)
    codes = []
    for kw in ("%kingfisher%", "%mallard%", "%gray heron%"):
        r = lib.conn.execute(
            "SELECT code FROM species WHERE en LIKE ? LIMIT 1",
            (kw,)).fetchone()
        assert r, f"种码找不到: {kw}"
        codes.append(r["code"])
    # 种1: b0(1月,首见)+b1(2月,回归种逻辑=同年不算); 种2: b2; 种3: b3+b4
    rec_plan = [(pids[0], codes[0]), (pids[1], codes[0]),
                (pids[2], codes[1]), (pids[3], codes[2]), (pids[4], codes[2])]
    for pid, code in rec_plan:
        lib.conn.execute(
            "INSERT INTO records(photo_id,species_code,rank,confidence,"
            "source) VALUES(?,?,1,0.9,'detect')", (pid, code))
    lib.set_aesthetic(pids[3], 9.5)
    sid = lib.create_spot("奥森南园", 40.0035, 116.3950, city="北京市")
    lib.set_photos_spot([pids[0], pids[1]], sid)
    lib.conn.commit()

    # ---------- [1] db 查询 ----------
    print("[1] db 生涯查询")
    feed = lib.lifer_feed()
    check(len(feed) == 3, f"lifer_feed 3种 (got {len(feed)})")
    nos = [li["no"] for li in feed]
    check(nos == [1, 2, 3], f"编号连续1..N ({nos})")
    first = feed[0]
    check(first["code"] == codes[0] and first["spot_name"] == "奥森南园",
          f"首见种带鸟点名 ({first['spot_name']})")
    no_spot = feed[2]
    check(no_spot["spot_name"] == "" and no_spot["region"] != "",
          f"无鸟点回落地区显示名 ({no_spot['spot_name']}/{no_spot['region']})")
    check("year_bird" in first, "年鸟标记字段存在")
    dc = lib.day_counts()
    check(sum(dc.values()) == 5 and len(dc) == 5, f"day_counts 总量/天数 ({dc})")
    check("2026-01-15" in dc, "day_counts 用 EXIF 日期")
    # 与 timeline 同口径: timeline() 分组键含同月
    tl = lib.timeline()
    tl_dates = {p.get("dt") or p.get("taken_at") or "" for v in tl.values()
                for p in v}
    check(any((d or "")[:7] == "2026-01" for d in tl_dates),
          "timeline 数据同月存在(口径对照)")
    provs = lib.province_species_counts()
    check(provs and provs[0][0] == "CN-BJ" and provs[0][1] == 3,
          f"省份统计 region_id 口径 ({provs})")

    # ---------- [2] UI 四Tab ----------
    print("[2] UI 冒烟")
    from app.ui.main_window import MainWindow
    win = MainWindow(lib, PROJ / "assets")
    win.show()
    win.switch_to("life")
    for _ in range(5):
        app.processEvents()
    page = win.pages["life"]
    check(win.stack.currentWidget() is page, "生涯页已注册且可切")
    check(page.stack.count() == 4, "四Tab栈")
    from PySide6.QtWidgets import QLabel
    # Tab1 总览
    texts1 = " ".join(w.text() for w in page.tabs[0].widget().findChildren(QLabel))
    check("生涯里程碑" in texts1 and "下一站" in texts1, f"里程碑卡渲染")
    check("观鸟热力图" in texts1, "热力图卡渲染")
    check("生涯之最" in texts1 and "奥森南园" in texts1, f"生涯之最渲染 ({texts1[:120]})")
    check("年度档案" in texts1, "年度卡行渲染")
    # Tab2 时间线
    page._tab_changed(1)
    for _ in range(5):
        app.processEvents()
    texts2 = " ".join(w.text() for w in page.tabs[1].widget().findChildren(QLabel))
    check("奥森南园" in texts2, f"时间线Tab含地点 ({texts2[:80]})")
    check(page._tl_year.count() == 2, f"年份筛选(全部+1年) ({page._tl_year.count()})")
    page._tl_search.setText("翠鸟" if any("翠鸟" in (li['cn'] or '') for li in feed)
                            else feed[0]["cn"][:2])
    for _ in range(5):
        app.processEvents()
    rows_after = sum(1 for w in page.tabs[1].widget().findChildren(QLabel)
                     if w.text().startswith("#"))
    check(rows_after >= 1, "搜索过滤后仍有条目")
    page._tl_search.setText("")
    for _ in range(3):
        app.processEvents()
    # Tab3 足迹
    page._tab_changed(2)
    for _ in range(5):
        app.processEvents()
    texts3 = " ".join(w.text() for w in page.tabs[2].widget().findChildren(QLabel))
    check("足迹" in texts3 and "奥森南园" in texts3, f"足迹Tab鸟点卡 ({texts3[:80]})")
    # 两栏独立 + 点省份筛选(2026-11-20 实测反馈)
    check(getattr(page, "_fp_map", None) is not None, "足迹: 左侧地图栏存在")
    check(page._fp_lay.count() > 0, "足迹: 右侧鸟点列表存在")
    check("鸟点" in page._fp_title.text(), f"列表标题 ({page._fp_title.text()})")
    # 模拟点击地图上的北京 → 只显示该省鸟点
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    cw = page._fp_map
    cw.resize(620, 430)
    cw.show()
    cw.grab()                        # 触发 paint → 建 paths 缓存
    for _ in range(3):
        app.processEvents()
    pt = QPointF(*cw._proj(116.4, 39.9))     # 北京市中心
    for tp, btn, btns in ((QEvent.MouseButtonPress, Qt.LeftButton,
                           Qt.LeftButton),
                          (QEvent.MouseButtonRelease, Qt.LeftButton,
                           Qt.NoButton)):
        cw.__getattribute__("mousePressEvent" if tp == QEvent.MouseButtonPress
                            else "mouseReleaseEvent")(
            QMouseEvent(tp, pt, pt, btn, btns, Qt.NoModifier))
    check(cw._sel == "北京市", f"点击省份→选中 ({cw._sel})")
    check("北京市" in page._fp_title.text(),
          f"右侧列表按省份过滤 ({page._fp_title.text()})")
    # 无鸟点省份 → 空态
    page._fp_on_province("西藏自治区")
    labels = " ".join(w.text() for w in page._fp_host.findChildren(QLabel))
    check("该省还没有鸟点" in labels, "无鸟点省份空态文案")
    # 清除恢复全部
    page._fp_clear_filter()
    check(page._fp_map._sel is None and "（1）" in page._fp_title.text(),
          f"显示全部恢复 ({page._fp_title.text()})")
    # 拖动不触发选省(位移>3px)
    page._fp_map.set_selection(None)
    p0 = QPointF(*cw._proj(116.4, 39.9))
    cw.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, p0, p0,
                                   Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    p1 = QPointF(p0.x() + 40, p0.y() + 20)
    cw.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, p1, p1, Qt.NoButton,
                                  Qt.LeftButton, Qt.NoModifier))
    cw.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, p1, p1,
                                     Qt.LeftButton, Qt.NoButton,
                                     Qt.NoModifier))
    check(cw._sel is None, "拖动平移不触发省份筛选")

    # 内嵌省级地图(实测反馈8): 构造+渲染冒烟
    from app.ui.china_map_widget import ChinaMapWidget
    cmap = ChinaMapWidget(dict(provs))
    cmap.resize(560, 430)
    cmap.show()
    for _ in range(5):
        app.processEvents()
    pm = cmap.grab()
    check(not pm.isNull() and pm.toImage().bits() and cmap._paths_cache,
          "内嵌省级地图渲染(路径已解析)")
    cmap.close()
    # Tab4 徽章(装备榜过别名+聚合)
    page._tab_changed(3)
    for _ in range(5):
        app.processEvents()
    texts4 = " ".join(w.text() for w in page.tabs[3].widget().findChildren(QLabel))
    check("SONY α7C II" in texts4, f"装备榜机身过别名 ({texts4[:160]})")
    check("ILCE-7CM2" not in texts4, "装备榜不再显示裸型号")
    gs = lib.gear_stats()
    check(dict(gs["body"]).get("Sony ILCE-7CM2") == 2,
          "db层原始计数(Sony ILCE-7CM2×2)——UI层聚合后按别名显示")
    from app.ui.life_page import _Badge
    n_badges = len(page.tabs[3].widget().findChildren(_Badge))
    check(n_badges == 24, f"徽章24枚渲染(搬家后) (got {n_badges})")

    # 徽章解锁数据搬家不变: achievements_summary 直接对照
    ach = lib.achievements_summary()
    check(ach["species"] == 3 and ach["photos"] == 5,
          f"徽章数据源(species/photos) ({ach['species']}/{ach['photos']})")

    # ---------- [3] 生涯清单CSV数据链 ----------
    print("[3] 生涯清单")
    import csv as _csv
    out = D / "list.csv"
    region = lib.get_setting("default_region", "GLOBAL")
    from app.core.prior_hint import get_hint, tier_display
    hint = get_hint()
    rows = []
    for li in lib.lifer_feed():
        rt = hint.rarity_tier(li["code"], "CN-BJ") if "CN-BJ" != "GLOBAL" else None
        rows.append([li["no"], li["cn"], li["sci"], li["en"],
                     (li["first_at"] or "")[:10],
                     li["spot_name"] or li["region"],
                     tier_display(rt) if rt else ""])
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["编号", "中文名", "学名", "英文名", "首见日期", "地点", "罕见度"])
        w.writerows(rows)
    content = out.read_text(encoding="utf-8-sig")
    check(content.count("\n") == 4, f"CSV 3种+表头 ({content.count(chr(10))})")
    check("奥森南园" in content, "CSV 地点列")

    win.close()
    print("\n" + ("FAIL" if FAILED["v"] else "ALL PASS"))
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
