# -*- coding: utf-8 -*-
"""分布地图验证: adcode映射/区域峰值注入/真WebEngine渲染。

用法: .venv/Scripts/python.exe tools/verify_distribution_map.py
前置: assets/map/china_provinces.json (阿里DataV省界); 需联网加载高德底图。
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB_DIR = PROJ / "data/migration_check"
FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def main():
    if LIB_DIR.exists():
        shutil.rmtree(LIB_DIR)

    from PySide6.QtCore import QEventLoop, Qt, QTimer
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme
    theme.apply_theme(app, "light")
    from app import i18n
    from app.db import Library
    from app.core.prior_hint import get_hint
    from app.ui import distribution_map as dm

    # ---- 1. adcode映射完整性 ----
    print("\n[1] 映射与几何")
    import json
    gj = dm._load_geojson()
    adcodes = {str(f["properties"].get("adcode")) for f in gj["features"]}
    provs = adcodes - {"100000_JD"}
    mapped = {str(a) for a in dm.ADCODE_TO_REGION}
    check(len(provs) == 34 and provs == mapped,
          f"省级feature 34个与映射表一致 (实得{len(provs)})")
    check("100000_JD" in adcodes and "100000_JD" not in mapped,
          "九段线feature存在且不参与着色")
    check(all(f.get("id") for f in gj["features"]),
          "每个feature已注入MapLibre所需的id")
    conn = get_hint().gp.conn
    in_priors = {r[0] for r in conn.execute(
        "SELECT DISTINCT region_id FROM priors WHERE region_id LIKE 'CN-%'")}
    check(set(dm.ADCODE_TO_REGION.values()) == in_priors,
          "映射目标与priors表CN-*完全一致(34)")

    # ---- 2. 区域峰值注入值 ----
    print("\n[2] region_tooltip_map")
    code = "barswa"   # 家燕: 北方夏候鸟(数据月度失真, 但区域峰值仍有意义)
    hint = get_hint()
    peaks = hint.region_peaks(code)
    payload = dm.region_tooltip_map(code)
    check(len(payload) == 34, "34省齐全")
    check(all(payload[str(a)]["v"] == peaks.get(r, -4.0)
              for a, r in dm.ADCODE_TO_REGION.items()),
          "各省值与region_peaks逐省一致(精确)")
    seasonal = [r for r in peaks if peaks[r] > -1.49]
    check(len(seasonal) >= 10, f"有记录区域 {len(seasonal)} 个")
    zh_re = re.compile(r"[\u4e00-\u9fff]")
    i18n.set_lang("en")
    en_payload = dm.region_tooltip_map(code)
    check(not any(zh_re.search(p["tip"]) for p in en_payload.values()),
          "EN模式悬浮文案无中文")
    i18n.set_lang("zh")

    # ---- 3. UI: 真WebEngine渲染 ----
    print("\n[3] 对话框渲染(需联网加载底图)")
    lib = Library(LIB_DIR)
    lib.fill_species()
    from app.ui.distribution_map import DistributionMapDialog
    dlg = DistributionMapDialog(lib, None, code)
    loop = QEventLoop()
    dlg._bridge.ready.connect(loop.quit)
    QTimer.singleShot(25000, loop.quit)
    dlg.show()
    loop.exec()
    check(dlg._ready, "mapReady 25s内上报(底图+choropleth层就绪)")
    if not dlg._ready:
        print("FAILED (底图未就绪, 疑似离线)")
        sys.exit(1)

    # 用runJavaScript硬断言地图状态(不抓全屏: 会拍到用户桌面)
    def js_query(expr: str, timeout_ms: int = 3000):
        box = {}

        def done(v):
            box["v"] = v
        dlg.web.page().runJavaScript(expr, done)
        loop_q = QEventLoop()
        QTimer.singleShot(timeout_ms, loop_q.quit)
        loop_q.exec()
        return box.get("v")

    loop2 = QEventLoop()
    QTimer.singleShot(2500, loop2.quit)
    loop2.exec()
    check(js_query("!!map && !!map.getSource('prov')") is True,
          "prov GeoJSON source已注册")
    check(js_query("!!map.getLayer('prov-fill') && !!map.getLayer('prov-line')")
          is True, "choropleth fill/line图层已挂载")
    check(js_query("map.isStyleLoaded()") is True, "样式已加载")
    v0 = js_query("map.getFeatureState({source:'prov', id:'110000'}).v")
    check(v0 == payload["110000"]["v"],
          f"北京feature-state为峰值先验 ({v0})")

    pm = dlg.grab()
    shots = PROJ / "data/ui_shots"
    shots.mkdir(exist_ok=True)
    pm.save(str(shots / "distribution_map.png"))
    check(not pm.isNull(), "对话框截图保存(自渲染)")
    dlg.close()

    print()
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
