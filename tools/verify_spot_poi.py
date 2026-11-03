# -*- coding: utf-8 -*-
"""鸟点POI/地图选点验证: 无Key引导/POI直接建点(同名复用)/地图选点创建/GPS新建。

用法: .venv/Scripts/python.exe tools/verify_spot_poi.py
全部离线(POI结果由mock注入, 不打高德API)。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB_DIR = PROJ / "data/spot_poi_check"
FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def main():
    if LIB_DIR.exists():
        shutil.rmtree(LIB_DIR)

    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme
    theme.apply_theme(app, "light")
    from app import i18n
    from app.db import Library
    from app.ui import spot_dialog as sd
    from app.ui.map_page import PoiSearcher, MapPickDialog

    lib = Library(LIB_DIR)
    lib.fill_species()
    photo_id = lib.add_photo(str(LIB_DIR / "x.jpg"), "hash1", 1, 1.0, 100, 100, 0)
    photo, _recs = lib.photo_detail(photo_id)

    print("\n[1] 双数据源: 默认MapTiler(作者Key) / 自填高德优先(离线URL断言)")
    from app.ui import amap_view as av
    sr = PoiSearcher(lib)
    captured = {}

    def fake_get(req):
        captured["url"] = req.url().toString()

    sr._nam.get = fake_get
    sr._pending = "奥林匹克"
    sr._do_search()
    # 2026-10-31起默认=内置高德Web Key(用户指示; 5080机中文POI搜不到
    # 的根因=无Key回退MapTiler而其中文POI库缺失)
    check("restapi.amap.com" in captured.get("url", "")
          and av.DEFAULT_WEB_KEY in captured.get("url", ""),
          f"默认源=内置高德Key ({captured.get('url', '')[:70]}…)")
    lib.set_setting("amap_key", "user_web_key_123")
    sr._do_search()
    check("restapi.amap.com" in captured.get("url", "")
          and "user_web_key_123" in captured.get("url", ""),
          "自填高德Key后优先走自填Key")
    lib.set_setting("amap_key", "")
    # 内置Key清空(空串会被自填覆盖; 清代码级Key模拟裁包): 走MapTiler降级
    av.DEFAULT_WEB_KEY, _bak = "", av.DEFAULT_WEB_KEY
    sr._do_search()
    check("api.maptiler.com" in captured.get("url", ""),
          "无高德Key时降级MapTiler")
    av.DEFAULT_WEB_KEY = _bak
    # MapTiler解析: WGS标记(免纠偏) + addr
    from PySide6.QtNetwork import QNetworkReply
    mt_pois = sr._parse_maptiler({
        "features": [{"geometry": {"coordinates": [121.93, 30.87]},
                      "properties": {"text": "南汇东滩",
                                     "place_name": "南汇东滩, 上海市"}}]},
        QNetworkReply.NetworkError.NoError)
    check(len(mt_pois) == 1 and mt_pois[0]["wgs"] is True
          and mt_pois[0]["addr"] == "南汇东滩, 上海市",
          "MapTiler结果解析(wgs=True+addr)")
    from app.ui.map_page import poi_location_wgs84
    w = poi_location_wgs84(mt_pois[0])
    check(w and abs(w[0] - 30.87) < 1e-9 and abs(w[1] - 121.93) < 1e-9,
          f"MapTiler坐标WGS84直过不纠偏 ({w})")
    w2 = poi_location_wgs84({"name": "x", "location": "121.93,30.87",
                             "wgs": False})
    check(w2 and (abs(w2[0] - 30.87) > 1e-4 or abs(w2[1] - 121.93) > 1e-4),
          "高德坐标仍走GCJ纠偏")

    print("\n[2] POI直接建鸟点(同名复用)")
    poi = {"name": "南汇东滩湿地公园", "location": "121.933000,30.876000",
           "pname": "上海市", "cityname": "上海市", "adname": "浦东新区"}
    sid, name, created = sd.find_or_create_spot_by_poi(lib, poi)
    check(created and sid > 0, "POI选中即建鸟点")
    row = lib.conn.execute("SELECT lat, lon FROM spots WHERE id=?", (sid,)).fetchone()
    check(row and abs(row["lat"] - 30.8707) < 0.01
          and abs(row["lon"] - 121.9267) < 0.01,
          f"POI坐标GCJ→WGS84落库 ({row['lat']:.4f},{row['lon']:.4f})")
    sid2, name2, created2 = sd.find_or_create_spot_by_poi(lib, poi)
    check(sid2 == sid and not created2, "同名POI复用既有鸟点(不重复建)")
    check(lib.conn.execute("SELECT COUNT(*) FROM spots").fetchone()[0] == 1,
          "鸟点表只有1条(复用)")

    # SpotPickDialog: mock搜索结果→选POI→挂载
    dlg = sd.SpotPickDialog(lib, photo)
    dlg.show()
    app.processEvents()
    emitted = {}
    dlg.slist.poi_chosen.connect(lambda d: emitted.update(d=d))
    sl2 = dlg.slist
    sl2.search.setText("南汇")
    from PySide6.QtCore import QTimer, QEventLoop
    l = QEventLoop()
    sl2._searcher.results.connect(lambda _p: l.quit())
    sl2._on_pois([poi])   # 直接注入(离线mock)
    QTimer.singleShot(500, l.quit)
    l.exec()
    it = None
    for i in range(sl2.listw.count()):
        d = sl2.listw.item(i).data(Qt.UserRole)
        if d and d.get("kind") == "poi":
            it = sl2.listw.item(i)
            break
    check(it is not None, "搜索结果列表出现POI项")
    sl2._trigger_item(it)
    app.processEvents()
    check(dlg.changed and dlg.result() == int(dlg.DialogCode.Accepted),
          "选POI即挂载并关闭")
    row = lib.conn.execute("SELECT spot_id FROM photos WHERE id=?",
                           (photo_id,)).fetchone()
    check(row["spot_id"] == sid, "照片挂到POI鸟点")
    dlg.deleteLater()
    app.processEvents()

    print("\n[2b] UI接线回归: 信号载荷形状建点必须带坐标")
    # 历史bug: SpotSearchList载荷{name,lat,lon,poi}无"location"键,
    # 建点函数只认location → 静默建成无坐标点(地图上点不出位置)。
    # 同名复用曾把该bug完全遮住——这里用全新名字走真实UI路径。
    poi_ui = {"name": "滴水湖", "location": "121.930000,30.870000",
              "wgs": True}
    dlg_ui = sd.SpotPickDialog(lib, photo)
    dlg_ui.show()
    app.processEvents()
    sl_ui = dlg_ui.slist
    sl_ui._on_pois([poi_ui])
    it_ui = None
    for i in range(sl_ui.listw.count()):
        d = sl_ui.listw.item(i).data(Qt.UserRole)
        if d and d.get("kind") == "poi" and d.get("name") == "滴水湖":
            it_ui = sl_ui.listw.item(i)
            break
    check(it_ui is not None, "POI项已在搜索列表")
    sl_ui._trigger_item(it_ui)
    app.processEvents()
    sp_ui = next(s for s in lib.spots_overview() if s["name"] == "滴水湖")
    check(sp_ui["lat"] is not None and abs(sp_ui["lat"] - 30.87) < 1e-9
          and abs(sp_ui["lon"] - 121.93) < 1e-9,
          f"UI路径选POI建点坐标落库 (lat={sp_ui['lat']}, lon={sp_ui['lon']})")
    dlg_ui.deleteLater()
    app.processEvents()

    print("\n[2c] 同名复用补坐标(修复历史无坐标点)")
    lib.create_spot("补坐标测试点")   # 无坐标旧点(如历史bug建出的)
    poi_fix = {"name": "补坐标测试点", "location": "121.500000,31.000000",
               "wgs": True}
    sid_f, _n_f, created_f = sd.find_or_create_spot_by_poi(lib, poi_fix)
    sp_f = lib.spot_info(sid_f)
    check(not created_f and sp_f["lat"] is not None
          and abs(sp_f["lat"] - 31.0) < 1e-9 and abs(sp_f["lon"] - 121.5) < 1e-9,
          f"无坐标旧点选中POI后坐标自动补上 ({sp_f['lat']},{sp_f['lon']})")
    sd.find_or_create_spot_by_poi(lib, {"name": "补坐标测试点",
                                        "location": "100.000000,10.000000",
                                        "wgs": True})
    sp_f2 = lib.spot_info(sid_f)
    check(abs(sp_f2["lat"] - 31.0) < 1e-9, "已有坐标不被同名POI覆盖")

    print("\n[3] 地图选点创建(零输入: 搜过POI继承其名, 没搜过退回坐标名)")
    photo2, _r2 = lib.photo_detail(lib.add_photo(
        str(LIB_DIR / "y.jpg"), "hash2", 1, 1.0, 100, 100, 0))
    dlg2 = sd.SpotPickDialog(lib, photo2)
    dlg2.show()
    app.processEvents()

    class FakePick:
        picked_wgs84 = (31.14, 121.66)

        def __init__(self, *a, **kw):
            self.picked_name = None

        def exec(self):
            return True

    # 场景1: 选点前搜过POI("南汇东滩")→精确角落→鸟点继承POI名
    pick1 = FakePick()
    pick1.picked_name = "南汇东滩"
    orig_pick = sd.MapPickDialog
    sd.MapPickDialog = lambda *a, **kw: pick1
    try:
        dlg2._create_via_map()
    finally:
        sd.MapPickDialog = orig_pick
    app.processEvents()
    row = lib.conn.execute(
        "SELECT spot_id FROM photos WHERE id=?", (photo2["id"],)).fetchone()
    check(row["spot_id"] is not None, "地图选点后建点并挂载(零输入)")
    sp = lib.spot_info(row["spot_id"])
    check(sp and sp["name"] == "南汇东滩" and sp["lat"]
          and abs(sp["lat"] - 31.14) < 1e-9,
          f"搜过POI→精确点继承POI名 ({sp['name'] if sp else None})")
    # 场景2: 同名再选 → 复用不重复建
    dlg2b = sd.SpotPickDialog(lib, photo2)
    dlg2b.show()
    app.processEvents()
    sd.MapPickDialog = lambda *a, **kw: pick1
    try:
        dlg2b._create_via_map()
    finally:
        sd.MapPickDialog = orig_pick
    app.processEvents()
    # 场景3: 完全没搜过 → 坐标名兜底
    pick3 = FakePick()   # picked_name=None
    sd.MapPickDialog = lambda *a, **kw: pick3
    try:
        sd._create_spot_via_map(lib, None)
    finally:
        sd.MapPickDialog = orig_pick
    app.processEvents()
    all_spots = {s["name"]: s for s in lib.spots_overview()}
    check(len(all_spots) == 5 and "鸟点 31.1400, 121.6600" in all_spots,
          f"同坐标复用+无上下文退回坐标名 (库内{len(all_spots)}点: "
          f"{sorted(all_spots)})")
    # 场景4: 地图选点撞上同名无坐标旧点 → 复用并补坐标
    lib.create_spot("地图补选点")
    pick4 = FakePick()
    pick4.picked_name = "地图补选点"
    pick4.picked_wgs84 = (31.50, 121.50)
    sd.MapPickDialog = lambda *a, **kw: pick4
    try:
        sid4 = sd._create_spot_via_map(lib, None)
    finally:
        sd.MapPickDialog = orig_pick
    app.processEvents()
    sp4 = lib.spot_info(sid4)
    check(sp4 and sp4["lat"] is not None and abs(sp4["lat"] - 31.5) < 1e-9
          and abs(sp4["lon"] - 121.5) < 1e-9,
          f"地图选点同名复用补坐标 ({sp4['lat'] if sp4 else None},"
          f"{sp4['lon'] if sp4 else None})")
    dlg2.deleteLater()
    dlg2b.deleteLater()
    app.processEvents()

    print("\n[4] 批量挂载(POI)")
    ids = [photo_id, photo2["id"]]
    dlg3 = sd.BatchSpotDialog(lib, None, ids)
    dlg3.show()
    app.processEvents()
    poi2 = {"name": "野鸭湖湿地", "location": "115.812000,40.514000",
            "pname": "北京市", "cityname": "北京市", "adname": "延庆区"}
    sid3, name3, created3 = sd.find_or_create_spot_by_poi(lib, poi2)
    dlg3._finish(sid3, name3)
    app.processEvents()
    n = lib.conn.execute(
        "SELECT COUNT(*) FROM photos WHERE spot_id=?", (sid3,)).fetchone()[0]
    check(dlg3.applied and n == 2, f"批量挂到POI鸟点 (挂载{n}张)")
    dlg3.deleteLater()
    app.processEvents()

    print("\n[5] EN模式文案")
    i18n.set_lang("en")
    sl3 = sd.SpotSearchList(lib)
    sl3.search.setText("x")
    app.processEvents()
    texts = [sl3.listw.item(i).text() for i in range(sl3.listw.count())]
    import re
    zh = re.compile(r"[\u4e00-\u9fff]")
    bad = [t for t in texts if zh.search(t)]
    check(not bad, f"EN模式提示无中文残留 ({bad[:2]})")
    i18n.set_lang("zh")

    print()
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
