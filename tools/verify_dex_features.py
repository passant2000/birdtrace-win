# -*- coding: utf-8 -*-
"""图鉴页增强验证: 全年分布热力表 + 我的最美照片 + 罕见度徽章。

覆盖: 先验矩阵解码一致性(与vector()逐值对照)/档位映射/选行规则/
色阶单调性/最美照片点击进查看器/徽章配色/EN模式新文案无中文残留。

用法: .venv/Scripts/python.exe tools/verify_dex_features.py
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "tools"))

LIB_DIR = PROJ / "data/dex_feature_check"
FAILED = {"v": False}
ZH = re.compile(r"[\u4e00-\u9fff]")


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def main():
    if LIB_DIR.exists():
        shutil.rmtree(LIB_DIR)

    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtWidgets import QApplication, QLabel
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)

    def flush_delete():
        # deleteLater的旧控件(切标签页/重建页)立即出树, 避免僵尸干扰findChildren
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()

    from app import theme
    theme.apply_theme(app, "light")
    from app import i18n
    from app.db import Library
    from app.core.importer import import_files
    from app.core.prior_hint import PriorHint, value_tier
    from app.ui import species_page as sp

    # ---- 1. 区域峰值: 解码与vector()逐值一致 ----
    print("\n[1] region_peaks 解码一致性")
    hint = PriorHint()
    code = "mallar3"   # 绿头鸭
    idx = hint.code_idx[code]
    t0 = __import__("time").perf_counter()
    peaks = hint.region_peaks(code)
    dt = __import__("time").perf_counter() - t0
    check(len(peaks) > 400, f"峰值表覆盖 {len(peaks)} 区域")
    check(dt < 2.0, f"首次全表扫描 {dt*1000:.0f}ms (<2s)")
    t0 = __import__("time").perf_counter()
    hint.region_peaks(code)
    dt2 = __import__("time").perf_counter() - t0
    check(dt2 < 0.05, f"会话缓存命中 {dt2*1000:.1f}ms")
    import numpy as np
    ok = True
    for rid in ("CN-BJ", "CN", "US-NY", "GB", "CN-SH"):
        if rid not in peaks:
            continue
        vals = [hint.gp.vector(rid, m) for m in range(1, 13)]
        want = max(float(v[idx]) if v is not None else -4.0 for v in vals)
        if abs(peaks[rid] - want) > 1e-6:
            ok = False
    check(ok, "抽样区域峰值=12个月vector()最大值")
    # rerank 与月份无关(同安卓同源去月份)
    logits = np.random.RandomState(3).randn(10480).astype(np.float32)
    check(bool(np.array_equal(hint.gp.rerank(logits, "CN-BJ", 1)[1],
                              hint.gp.rerank(logits, "CN-BJ", 7)[1])),
          "rerank结果与month无关")
    absent = [rid for rid, v in peaks.items() if v <= -1.49]
    check(len(absent) > 0, f"缺席/无数据区域 {len(absent)} 个会被选行排除")

    # ---- 2. 档位与色阶 ----
    print("\n[2] 档位映射与色阶")
    check(value_tier(2.0) == "常见" and value_tier(0.5) == "可见"
          and value_tier(-0.5) == "偶见" and value_tier(-2.0) == "罕见",  # i18n:ok
          "value_tier 四档边界正确")
    check(sp._heat_css(-2.0) == theme.FILL, "无记录值用主题占位灰")
    grad = [sp._heat_css(v) for v in (-1.0, 0.0, 1.0, 2.0)]
    check(len(set(grad)) == 4 and grad[-1] == "#55631F",
          "色阶随丰度单调加深, 顶格=深橄榄")

    # ---- 3. 选行规则 ----
    print("\n[3] 选行规则")
    fpeaks = {r: v for r, v in peaks.items() if v > -1.49}
    parents = hint.gp.region_parents()
    rows, hidden = sp._heat_rows(fpeaks, parents, "CN-BJ")
    check(rows[0] == "CN-BJ" and rows[1] == "CN",
          "默认地区与所在国置顶")
    provs = [r for r in rows[2:8] if parents.get(r) == "CN"]
    check(len(provs) == 6, f"随后是该国省级行×6 (实得{len(provs)})")
    check(len(rows) <= 14, f"总行数≤14 (实得{len(rows)})")
    check(hidden == len(fpeaks) - len(rows) and hidden > 0,
          f"未展示地区数正确 ({hidden})")
    rows_g, _ = sp._heat_rows(fpeaks, parents, "GLOBAL")
    check(rows_g[0] != "CN-BJ", "GLOBAL时不pin任何地区")
    vals = [fpeaks[r] for r in rows_g]
    check(vals == sorted(vals, reverse=True), "GLOBAL模式按峰值降序")

    # ---- 4. UI: 建库(手工记录免ONNX)→图鉴页渲染 ----
    print("\n[4] 图鉴页 UI")
    from PIL import Image
    src_dir = PROJ / "data/dex_feature_src"
    if src_dir.exists():
        shutil.rmtree(src_dir)
    src_dir.mkdir()
    base = Image.open(PROJ / "data/test_images/Anas_platyrhynchos.jpg").copy()
    px = base.load()
    for i in range(3):
        px[0, 0] = ((i * 37) % 256, (i * 91) % 256, (i * 151) % 256)
        base.save(src_dir / f"鸭{i}.jpg", quality=92)
    lib = Library(LIB_DIR)
    lib.fill_species()
    import_files(lib, sorted(src_dir.glob("*.jpg")), mode="ref", dest_root=None,
                 region_id="CN-BJ")
    # 手工识别记录: 绿头鸭×2(第二张最美) + 苍鹭×1
    pids = [r["id"] for r in lib.conn.execute(
        "SELECT id FROM photos ORDER BY id")]
    lib.add_records(pids[0], [{"species_code": "mallar3", "rank": 1,
                               "confidence": 0.97, "source": "detect"}])
    lib.add_records(pids[1], [{"species_code": "mallar3", "rank": 1,
                               "confidence": 0.95, "source": "detect"}])
    lib.add_records(pids[2], [{"species_code": "graher1", "rank": 1,
                               "confidence": 0.93, "source": "detect"}])
    lib.set_aesthetic(pids[0], 6.0)
    lib.set_aesthetic(pids[1], 8.5)   # 最美
    lib.conn.commit()
    lib.set_setting("default_region", "CN-BJ")

    class _Win:
        pass
    win = _Win()
    page = sp.SpeciesPage(lib, win)
    page.resize(1200, 860)
    page._open_detail("mallar3")
    page._tab_changed(1)
    flush_delete()

    tables = page.findChildren(sp._HeatTable)
    check(len(tables) == 1, "图鉴页有1张地区分布表")
    cells = [w for w in tables[0].findChildren(QLabel)
             if w.objectName() == "HeatCell"]
    check(len(cells) == len(rows), f"色块 {len(cells)} = 行数(每行1条峰值色)")
    names = [w for w in tables[0].findChildren(QLabel)
             if w.objectName() == "HeatName"]
    check(len(names) == len(rows), f"行名 {len(names)} = 选行数")
    labels = [w.toolTip() for w in tables[0].findChildren(QLabel)]
    check(any("📍" in x for x in labels), "默认地区行带📍标记")
    all_text = [w.text() for w in tables[0].findChildren(QLabel)]
    check(not any(re.search(r"\d+月|Jan", x) for x in all_text),
          "无月份字样残留(月份维度已去)")
    tips = [w.toolTip() for w in cells]
    check(tips and all("：" in x or ": " in x for x in tips),
          "色块tooltip为 地区：档位(+值) 格式")

    # 徽章: 地区档位 + 罕见度(绿头鸭在北京为常见系=灰; 找一个稀有种验证红)
    pills = page._dex_badges(hint, "mallar3", "CN-BJ", True)
    check(any("📍" in p.text() and "本月" not in p.text() for p in pills)
          and any("罕见度" in p.text() for p in pills),
          "绿头鸭出 地区+罕见度 两枚徽章, 且无『本月』字样")
    rare_code = None
    for c, i2 in hint.code_idx.items():
        if hint.rarity_tier(c, "CN-BJ") in ("稀有", "罕见"):  # i18n:ok
            rare_code = c
            break
    rpills = page._dex_badges(hint, rare_code, "CN-BJ", True)
    check(any("#E5484D" in p.styleSheet() for p in rpills),
          f"稀有种({rare_code})罕见度徽章为醒目红")

    # 最美照片: 角标/点击进查看器
    from app.theme.widgets import PhotoGridItem
    grids = [w for w in page.findChildren(PhotoGridItem) if w.corner]
    check(len(grids) == 1 and grids[0].corner == i18n.t("★最美", "★ Best"),
          "最美照片角标存在")
    opened = []

    class _FakeViewer:
        def __init__(self, lib_, win_, pid, ids):
            opened.append((pid, list(ids)))

        def exec(self):
            return 0
    real_viewer = sp.PhotoViewer
    sp.PhotoViewer = _FakeViewer
    try:
        grids[0].mousePressEvent(None)
    finally:
        sp.PhotoViewer = real_viewer
    check(opened and opened[0][0] == pids[1],
          "点击最美照片→查看器打开评分最高那张")
    check(opened and set([pids[0], pids[1]]) <= set(opened[0][1]),
          "查看器ids含该种全部照片")

    # ---- 5. EN模式新文案无中文残留 ----
    print("\n[5] EN模式残留")
    from verify_i18n import collect_texts, zh_residue
    from app.core.birddex import get_dex
    i18n.set_lang("en")
    # 真实语言切换=整窗重建(_rebuild_window), 这里同样重建页面而非复用ZH页
    page = sp.SpeciesPage(lib, win)
    page.resize(1200, 860)
    page._open_detail("mallar3")
    page._tab_changed(1)
    flush_delete()
    tables = page.findChildren(sp._HeatTable)
    d = get_dex().detail(lib.species_info("mallar3")["sci"])
    dex_data = []
    if d:
        for key, _zl, _el in sp.DEX_FIELDS:
            zh = d[key]["zh"]
            if not zh:
                continue
            text = zh.replace("\n- ", "\n• ").replace("- ", "• ", 1) \
                if zh.startswith("- ") else zh.replace("\n- ", "\n• ")
            dex_data.append(text.replace("\n", "<br>"))
    fam = lib.species_info("mallar3")["family_cn"]   # 科中文名=库内数据, 按设计保留
    texts = collect_texts(page)
    bad = zh_residue(texts, dex_data + ([fam] if fam else []))
    check(not bad, "图鉴页EN模式无中文残留" + (f": {bad[:3]}" if bad else ""))
    en_heads = [w.text() for w in tables[0].findChildren(QLabel)]
    check(any(x == "Regional abundance" for x in en_heads),
          "EN模式分布表标题为英文")
    shots = PROJ / "data/ui_shots"
    shots.mkdir(exist_ok=True)
    page.grab().save(str(shots / "dex_feature_en.png"))
    i18n.set_lang("zh")
    page = sp.SpeciesPage(lib, win)
    page.resize(1200, 860)
    page._open_detail("mallar3")
    page._tab_changed(1)
    flush_delete()
    page.grab().save(str(shots / "dex_feature_zh.png"))
    page.close()

    print()
    shutil.rmtree(src_dir, ignore_errors=True)
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
