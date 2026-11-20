# -*- coding: utf-8 -*-
"""test3实测反馈第二批修复·功能级验证(offscreen可跑):
①地图页侧栏竖虚线: 根因=裸QFrame{}选择器泄漏给每张鸟点卡片border-right
  (test2误诊滚动条)。修=#MapSide收窄。断言=像素级扫描侧栏右缘内部列
  无贯穿竖线(仅面板自身边框允许)。
②足迹图: 原投影经/纬各自铺满=中国拉宽~2.6倍且零交互。修=等比缩放居中
  +滚轮缩放(锚点)+拖动平移+双击复位。断言=两轴比例尺一致/适配居中/
  zoom锚点不动/封顶8/拖动位移/越界夹取/双击复位/图例提示。
③生涯时间线鸟种搜索只认中文: 补拼音全拼+首字母(lifers补列+匹配两处)。
④选鸟点啥也不显示: 旧=生涯首见流按首见照片地点筛(必空)。修=db.spot_
  lifer_feed换口径(该点拍到的每种+在该点首见)+spot_visits口径统一
  (不筛rank, 与spots_overview一致)+头部/空态文案。
用法: .venv/Scripts/python.exe tools/verify_feedback_test3.py
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


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QColor, QMouseEvent, QWheelEvent
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QScrollArea
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme, i18n
    theme.apply_theme(app, "light")
    i18n.set_lang("zh")

    # ---------- 测试库: 5张3种+rank2多鸟+3鸟点(东=首见地/南=回归地/空=无识别) ----------
    D = PROJ / "data/_fb_test3"
    if D.exists():
        shutil.rmtree(D)
    D.mkdir(parents=True)
    from app.db import Library
    import app.media as media
    lib = Library(D)
    lib.fill_species()
    lib.conn.execute(
        "INSERT INTO batches(mode, dest, region_id, count) "
        "VALUES('copy',?, 'CN-SH', 5)", (str(D / "src"),))
    bid = lib.conn.execute("SELECT id FROM batches LIMIT 1").fetchone()["id"]
    IMGS = ["Alcedo_atthis.jpg", "Anas_platyrhynchos.jpg",
            "Ardea_cinerea.jpg", "Cyanistes_caeruleus.jpg",
            "Passer_montanus.jpg"]
    pids = []
    for i in range(5):
        p = D / f"b{i}.jpg"
        shutil.copy(PROJ / "data/test_images" / IMGS[i], p)
        pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                            p.stat().st_mtime, 0, 0, bid)
        lib.conn.execute(
            "INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
            (pid, f"2026-0{i + 1}-10 08:00:00"))
        pids.append(pid)
    codes = []
    for kw in ("%kingfisher%", "%mallard%", "%gray heron%"):
        r = lib.conn.execute(
            "SELECT code FROM species WHERE en LIKE ? LIMIT 1",
            (kw,)).fetchone()
        assert r, f"种码找不到: {kw}"
        codes.append(r["code"])
    A, B, C = codes
    for pid, code in [(pids[0], A), (pids[1], A), (pids[2], B),
                      (pids[3], A)]:
        lib.conn.execute(
            "INSERT INTO records(photo_id,species_code,rank,confidence,"
            "source) VALUES(?,?,1,0.9,'detect')", (pid, code))
    lib.conn.execute(  # p2多鸟: 第二只=C(rank2) —— spot_visits口径试金石
        "INSERT INTO records(photo_id,species_code,rank,confidence,"
        "source) VALUES(?,?,2,0.4,'detect')", (pids[2], C))
    sp1 = lib.create_spot("东点", 30.0, 120.0)
    sp2 = lib.create_spot("南点", 31.0, 121.0)
    sp3 = lib.create_spot("空点", 32.0, 122.0)
    lib.set_photos_spot([pids[0], pids[1]], sp1)
    lib.set_photos_spot([pids[2], pids[3]], sp2)
    lib.set_photos_spot([pids[4]], sp3)
    lib.conn.commit()

    # ---------- [A] 地图侧栏竖虚线(像素级) ----------
    print("[A] 地图侧栏虚线根除")
    from app.ui.map_page import MapPage
    mp = MapPage(lib, None)
    mp.resize(900, 800)
    mp.show()
    for _ in range(3):
        app.processEvents()
    scr = mp.findChildren(QScrollArea)[0]     # MapPage唯一滚动区=鸟点列表
    side = scr.parentWidget()
    pm = side.grab()
    img = pm.toImage()
    w, h = pm.width(), pm.height()

    def col_cov(x):
        cnt = sum(1 for y in range(0, h, 2)
                  if QColor(img.pixel(x, y)).lightness() < 235)
        return cnt * 2 / h

    check(col_cov(w - 1) > 0.9, f"面板自身右边框在(截图有效) ({col_cov(w - 1):.2f})")
    interior = [(x, round(col_cov(x), 2)) for x in range(w - 24, w - 4)
                if col_cov(x) > 0.5]
    check(not interior,
          f"右缘内部无贯穿竖线(修复前x≈w-17覆盖0.79) ({interior[:3]})")
    mp.hide()

    # ---------- [B] 足迹图等比+交互 ----------
    print("[B] 足迹图等比投影+缩放平移")
    from app.ui.china_map_widget import (ChinaMapWidget, map_legend,
                                         _CW, _CH, _LAT1, _LON0, _LON1)
    cmap = ChinaMapWidget({"CN-AH": 10, "CN-ZJ": 2})
    cmap.resize(1400, 500)
    cmap.show()
    for _ in range(3):
        app.processEvents()
    cmap.grab()                                 # 触发paint回填_w/_h
    p0 = cmap._proj(_LON0, _LAT1)
    p1 = cmap._proj(_LON1, 17.0)
    sx = (p1[0] - p0[0]) / _CW
    sy = (p1[1] - p0[1]) / _CH
    check(abs(sx - sy) < 1e-6 * max(sx, sy),
          f"两轴比例尺一致(等比, 修复前差~2.6倍) ({sx:.3f}/{sy:.3f})")
    check(sx * _CW <= 1400 + 1 and sy * _CH <= 500 + 1, "全图完整适配控件")
    check(abs((p0[0] + p1[0]) / 2 - 700) < 2
          and abs((p0[1] + p1[1]) / 2 - 250) < 2, "全图居中")

    def wheel(x, y, dy):
        cmap.wheelEvent(QWheelEvent(
            QPointF(x, y), QPointF(x, y), QPoint(0, 0), QPoint(0, dy),
            Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False))

    def mouse(tp, x, y, btn=Qt.NoButton, btns=Qt.LeftButton):
        cmap.mousePressEvent  # keep ref hot
        getattr(cmap, {
            QEvent.MouseButtonPress: "mousePressEvent",
            QEvent.MouseButtonRelease: "mouseReleaseEvent",
            QEvent.MouseButtonDblClick: "mouseDoubleClickEvent",
            QEvent.MouseMove: "mouseMoveEvent"}[tp])(
            QMouseEvent(tp, QPointF(x, y), QPointF(x, y), btn, btns,
                        Qt.NoModifier))

    ax, ay = cmap._unproj(700, 250)
    wheel(700, 250, 120)
    check(1.2 < cmap._zoom <= 1.3, f"滚轮放大生效 ({cmap._zoom:.2f})")
    bx, by = cmap._unproj(700, 250)
    check(abs(bx - ax) < 1e-3 and abs(by - ay) < 1e-3,
          "缩放锚点: 光标下的地理点不动")
    for _ in range(40):
        wheel(700, 250, 120)
    check(cmap._zoom == 8.0, f"zoom封顶8 ({cmap._zoom})")
    check(not cmap.grab().isNull(), "放大态渲染")
    s8 = cmap._view_scale()
    vx0 = cmap._vx
    mouse(QEvent.MouseButtonPress, 700, 250, Qt.LeftButton, Qt.LeftButton)
    mouse(QEvent.MouseMove, 600, 250)
    check(abs((cmap._vx - vx0) * s8 - 100) < 0.5,
          f"拖动平移100px跟手 ({(cmap._vx - vx0) * s8:.1f}px)")
    for i in range(60):                          # 往左拖出界
        mouse(QEvent.MouseMove, 600 - 50 * i, 250)
    hw = 1400 / (2 * cmap._view_scale())
    check(_CW / 2 - 0.01 <= cmap._vx <= _CW - hw + 0.01,
          f"平移越界被夹回全图范围 (vx={cmap._vx:.2f})")
    mouse(QEvent.MouseButtonRelease, 100, 250, Qt.LeftButton, Qt.NoButton)
    mouse(QEvent.MouseButtonDblClick, 700, 250, Qt.LeftButton, Qt.LeftButton)
    check(cmap._zoom == 1.0 and abs(cmap._vx - _CW / 2) < 1e-6,
          "双击复位=全图居中")
    check("缩放" in map_legend().text(), "图例含操作提示")
    cmap.close()

    # ---------- [C] 拼音搜索 ----------
    print("[C] 生涯时间线鸟种搜索拼音")
    feed = lib.lifer_feed()
    check(feed and all("cn_pinyin" in li and "cn_initials" in li
                       for li in feed), "lifer_feed带拼音列")
    li0 = feed[0]                                # A=最早首见,确定序
    py, ini = li0["cn_pinyin"] or "", li0["cn_initials"] or ""
    check(bool(py) and bool(ini), f"拼音数据非空 ({li0['cn']}→{py}/{ini})")
    from app.ui.life_page import LifePage
    check(LifePage._tl_match(li0, ini), f"首字母命中 ({ini})")
    check(LifePage._tl_match(li0, py[:4]), f"全拼前缀命中 ({py[:4]})")
    check(LifePage._tl_match(li0, (li0["en"] or "x").lower()[:4]), "英文命中")
    check(not LifePage._tl_match(li0, "zzzzz"), "乱串不命中")

    # ---------- [D] 鸟点收录流 ----------
    print("[D] 选鸟点=该点收录流(不再空白)")
    f1 = lib.spot_lifer_feed(sp1)
    check([r["code"] for r in f1] == [A], f"东点收录流=[A] ({[r['code'] for r in f1]})")
    check(f1 and f1[0]["first_at"].startswith("2026-01"),
          "A在东点首见=1月(生涯首见也在东点)")
    f2 = lib.spot_lifer_feed(sp2)
    codes2 = [r["code"] for r in f2]
    check(set(codes2) == {A, B, C}, f"南点收录流含A/B/C ({codes2})")
    ra = next(r for r in f2 if r["code"] == A)
    check(ra["first_at"].startswith("2026-04"),
          "A在南点首见=4月(该点首见, 非生涯首见1月)")
    check(ra["photo_id"] == pids[3], "首见照片=该点那张")
    no_map = {li["code"]: li["no"] for li in feed}
    check(ra["no"] == no_map[A], "no=全局lifer编号")
    check(ra["spot_name"] == "南点", "spot_name=该点")
    v = lib.spot_visits(sp2)
    check({s["code"] for s in v["species"]} == {A, B, C},
          f"spot_visits含rank2鸟种C(口径与spots_overview统一) "
          f"({[s['code'] for s in v['species']]})")
    ov = {s["id"]: s for s in lib.spots_overview()}
    check(ov[sp2]["n_species"] == 3, "地图侧栏口径=3种(与下钻卡一致)")
    check(lib.spot_lifer_feed(sp3) == [] and lib.spot_visits(sp3)["species"] == [],
          "空点(有照片无识别)=空收录流")

    # ---------- [E] 页面级(真实MainWindow) ----------
    print("[E] 页面级冒烟")
    from app.ui.main_window import MainWindow
    win = MainWindow(lib, PROJ / "assets")
    win.show()
    win.switch_to("life")
    for _ in range(5):
        app.processEvents()
    page = win.pages["life"]
    page._tab_changed(1)
    for _ in range(3):
        app.processEvents()

    def tab_texts():
        w = page.tabs[1].widget()
        labs = [x.text() for x in w.findChildren(QLabel)]
        heads = [x.text() for x in w.findChildren(QPushButton)
                 if x.text().startswith("▾")]
        return labs, heads

    idx = page._tl_spot.findData(sp2)
    page._tl_spot.setCurrentIndex(idx)
    for _ in range(3):
        app.processEvents()
    labs, heads = tab_texts()
    check(any(x.startswith("#") for x in labs),
          "选南点后时间线有条目(修复前=整页空白)")
    check(heads and all("收录" in h for h in heads),
          f"鸟点口径头部文案=收录N种 ({heads[:1]})")
    idx3 = page._tl_spot.findData(sp3)
    page._tl_spot.setCurrentIndex(idx3)
    for _ in range(3):
        app.processEvents()
    labs3, _ = tab_texts()
    check(any("还没有已识别" in x for x in labs3), "空点空态文案明确")
    page._tl_spot.setCurrentIndex(0)
    for _ in range(3):
        app.processEvents()
    page._tl_search.setText(ini)
    for _ in range(3):
        app.processEvents()
    labs4, _ = tab_texts()
    check(sum(1 for x in labs4 if x.startswith("#")) >= 1,
          f"页面级首字母搜索有条目 ({ini})")
    page._tl_search.setText("")
    for _ in range(3):
        app.processEvents()
    win.close()

    lib.close()
    shutil.rmtree(D, ignore_errors=True)
    print("\nFEEDBACK_TEST3 " + ("ALL PASS" if not FAILED["v"] else "HAS FAIL"))
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
