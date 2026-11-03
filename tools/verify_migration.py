# -*- coding: utf-8 -*-
"""迁徙地图验证: 下载缓存链路(本地HTTP模拟作者服务)/解码器季曲线语义/
真WebEngine渲染断言。

用法: .venv/Scripts/python.exe tools/verify_migration.py
前置: data/migration_probe/barswa_surface_tiles.sqlite (探测产物);
底图需联网(高德瓦片), 迁徙数据本身走本地服务器(离线可跑)。
"""
from __future__ import annotations

import json
import lzma
import hashlib
import shutil
import sqlite3
import struct
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB_DIR = PROJ / "data/migration_check"
FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


# ---- 本地模拟服务器 ----

class _FakeServer:
    """提供 latest.json/catalog.json/物种包; 可切换损坏模式统计请求数。"""

    def __init__(self, root: Path):
        self.root = root
        self.hits: dict[str, int] = {}
        self.corrupt = False
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                name = self.path.lstrip("/")
                outer.hits[name] = outer.hits.get(name, 0) + 1
                p = outer.root / name
                if not p.exists():
                    self.send_error(404)
                    return
                data = p.read_bytes()
                if outer.corrupt and name.endswith("surface_tiles.sqlite"):
                    data = b"CORRUPT" + data[7:]
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def stop(self):
        self.httpd.shutdown()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_fake_species(root: Path) -> dict:
    """构造1物种的最小迁徙包: 2个world tile(其一跨日界线), 已知季曲线。"""
    weeks, rows, cols = 52, 16, 16
    spec_dir = root / "species" / "barswa"
    spec_dir.mkdir(parents=True, exist_ok=True)

    def make_payload(peak_week: int, active: list[tuple[int, int]]) -> bytes:
        vals = bytearray(weeks * rows * cols)
        for r, c in active:
            for wk in range(weeks):
                if wk == peak_week:
                    vals[wk * rows * cols + r * cols + c] = 150
                elif peak_week - 2 <= wk <= peak_week + 2:
                    vals[wk * rows * cols + r * cols + c] = 30
        head = struct.pack("<4sHHHH4x", b"BTRS", 2, weeks, rows, cols)
        return lzma.compress(head + bytes(weeks * 16) + bytes(vals))

    # tile A: 正常区间 [100,116]×[40,56]; tile B: 两段记录但未跨日界线
    # [-32.5→21]; tile C: 真跨日界线 [113.44→226.85], 含骑线cell
    pa = make_payload(22, [(0, 0), (0, 1), (1, 0), (1, 1)])
    pb = make_payload(2, [(15, 0), (15, 15)])
    pc = make_payload(40, [(0, 0), (0, 9), (0, 15)])
    db = sqlite3.connect(spec_dir / "surface_tiles.sqlite")
    db.executescript(
        "CREATE TABLE surface_tile (tile_id INTEGER PRIMARY KEY, lod TEXT NOT NULL,"
        " tile_y INTEGER NOT NULL, tile_x INTEGER NOT NULL, cell_span INTEGER NOT NULL,"
        " tile_span INTEGER NOT NULL, cell_rows INTEGER NOT NULL, cell_columns INTEGER NOT NULL,"
        " active_week_mask INTEGER NOT NULL, payload BLOB NOT NULL, payload_sha256 TEXT NOT NULL,"
        " uncompressed_bytes INTEGER NOT NULL, UNIQUE(lod,tile_y,tile_x));"
        "CREATE TABLE tile_coverage (lod TEXT NOT NULL, tile_y INTEGER NOT NULL,"
        " tile_x INTEGER NOT NULL, coverage_part INTEGER NOT NULL, min_longitude REAL NOT NULL,"
        " max_longitude REAL NOT NULL, min_latitude REAL NOT NULL, max_latitude REAL NOT NULL,"
        " PRIMARY KEY(lod,tile_y,tile_x,coverage_part)) WITHOUT ROWID;")
    mask = (1 << 52) - 1
    for i, (lod, ty, tx, payload) in enumerate(
            [("world", 0, 1, pa), ("world", 0, 5, pb), ("world", 1, 9, pc),
             ("continental", 2, 8, pa)]):
        span = 1024 if lod == "world" else 256
        db.execute("INSERT INTO surface_tile VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (i, lod, ty, tx, 64 if lod == "world" else 16, span,
                    16, 16, mask, payload, "", len(lzma.decompress(payload))))
    cov = [("world", 0, 1, 0, 100.0, 116.0, 40.0, 56.0),
           ("world", 0, 5, 0, -32.5, 180.0, 43.05, 84.86),
           ("world", 0, 5, 1, -180.0, 21.0, 43.05, 84.86),
           ("world", 1, 9, 0, 113.44, 180.0, 17.17, 43.05),
           ("world", 1, 9, 1, -180.0, -133.15, 17.17, 43.05),
           ("continental", 2, 8, 0, 100.0, 116.0, 40.0, 56.0)]
    for lod, ty, tx, part, mnlon, mxlon, mnlat, mxlat in cov:
        db.execute("INSERT INTO tile_coverage VALUES (?,?,?,?,?,?,?,?)",
                   (lod, ty, tx, part, mnlon, mxlon, mnlat, mxlat))
    db.commit()
    db.close()

    frames = []
    from datetime import date, timedelta
    # 家燕同款季段序列: 6非繁殖→18北迁→6繁殖→22南迁
    for w in range(52):
        phase = ("nonBreeding" if w < 6 else
                 "preBreedingMigration" if w < 24 else
                 "breeding" if w < 30 else "postBreedingMigration")
        frames.append({"weekIndex": w + 1, "phase": phase,
                       "date": (date(2023, 1, 4) +
                                timedelta(days=7 * w)).isoformat()})
    manifest = {"englishCommonName": "Barn Swallow", "frames": frames,
                "artifactRole": "test-fixture"}
    (spec_dir / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8")

    sq = (spec_dir / "surface_tiles.sqlite").read_bytes()
    mf = (spec_dir / "manifest.json").read_bytes()
    catalog = {
        "releaseId": "test-r1",
        "species": [{
            "speciesCode": "barswa",
            "sqliteKey": "species/barswa/surface_tiles.sqlite",
            "sqliteSHA256": sha(sq), "sqliteBytes": len(sq),
            "manifestKey": "species/barswa/manifest.json",
            "manifestSHA256": sha(mf), "manifestBytes": len(mf),
        }],
    }
    cat_raw = json.dumps(catalog).encode()
    (root / "catalog.json").write_bytes(cat_raw)
    latest = {"catalogKey": "catalog.json", "catalogSHA256": sha(cat_raw),
              "releaseId": "test-r1"}
    # 镜像生产布局: latest.json 固定在 migration/status-2023/ 下
    latest_path = root / "migration" / "status-2023" / "latest.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_bytes(json.dumps(latest).encode())
    return catalog


def client_tests(server: _FakeServer):
    from app.core.migration import (MigrationClient, MigrationError,
                                    decode_world, week_dates)

    print("\n[1] 下载/缓存/校验(本地模拟服务)")
    lib1 = LIB_DIR / "dl1"
    if lib1.exists():
        shutil.rmtree(lib1)
    cl = MigrationClient(lib1, base_url=server.base)

    n0 = sum(server.hits.values())
    paths = cl.fetch_species("barswa")
    n1 = sum(server.hits.values())
    check(n1 > n0, "首次下载发生网络请求")
    check(paths["sqlite"].exists() and paths["manifest"].exists(),
          "物种包落在 <库>/migration/ 下")

    def pkg_hits() -> int:
        # 目录(latest/catalog)设计为每次在线刷新, 只考察物种包(大文件)缓存
        return sum(v for k, v in server.hits.items()
                   if "surface_tiles" in k or "manifest.json" in k)

    n_pkg = pkg_hits()
    paths2 = cl.fetch_species("barswa")
    check(pkg_hits() == n_pkg, "二次调用物种包全缓存命中(零下载)")
    check(paths2["from_cache"] is True, "from_cache标记正确")

    # 缓存被篡改 → SHA不符 → 自动重下修复
    paths["sqlite"].write_bytes(b"tampered" + paths["sqlite"].read_bytes()[8:])
    n_pkg = pkg_hits()
    paths3 = cl.fetch_species("barswa")
    check(pkg_hits() > n_pkg, "缓存损坏后自动重新下载")
    check(sha(paths3["sqlite"].read_bytes()) ==
          json.loads((server.root / "catalog.json").read_bytes())
          ["species"][0]["sqliteSHA256"], "重下后SHA256与目录一致")

    # 服务器端数据损坏 → 报sha错误且不落盘
    lib2 = LIB_DIR / "dl2"
    if lib2.exists():
        shutil.rmtree(lib2)
    cl2 = MigrationClient(lib2, base_url=server.base)
    server.corrupt = True
    try:
        cl2.fetch_species("barswa")
        check(False, "服务器数据损坏应报sha错误")
    except MigrationError as e:
        check(e.reason == "sha", f"服务器数据损坏报sha错误(实际{e.reason})")
    check(not (lib2 / "migration" / "barswa.sqlite").exists(),
          "损坏下载未落盘")
    server.corrupt = False

    # 不在目录中的物种
    try:
        cl.fetch_species("mallar3")
        check(False, "目录外物种应报not_in_catalog")
    except MigrationError as e:
        check(e.reason == "not_in_catalog",
              f"目录外物种报not_in_catalog(实际{e.reason})")

    # 断网回退: 目录已缓存+包已缓存 → 死端口也能全量取回
    cl_dead = MigrationClient(lib1, base_url="http://127.0.0.1:9/")
    paths4 = cl_dead.fetch_species("barswa")
    check(paths4["from_cache"] is True, "断网时目录+包缓存回退成功")

    # 解码(构造数据): 峰周/区间/跨日界线
    print("\n[2] 解码器(构造数据)")
    d = decode_world(paths["sqlite"])
    check(d["weeks"] == 52, "52周")
    ncell = len(d["cells"])
    check(ncell == 10, f"活跃cell=10(4+2+骑线拆双4, 实得{ncell})")
    vals = d["values"]
    wk = [vals[i * 52 + w] for i in range(ncell) for w in range(52)]
    check(max(wk) == 150 and min(wk) == 0, "u8值域0..150")
    box_a = d["cells"][0]
    check(abs(box_a[0] - 100.0) < 1e-9 and abs(box_a[3] - 56.0) < 1e-9,
          f"tile A首cell几何[{box_a[0]:.2f},{box_a[1]:.2f},{box_a[2]:.2f},{box_a[3]:.2f}]")
    peaks = {i: max(range(52), key=lambda w: vals[i * 52 + w])
             for i in range(ncell)}
    check({peaks[i] for i in range(4)} == {22}, "tile A峰周=22")
    check({peaks[i] for i in range(4, 6)} == {2}, "tile B峰周=2")
    check({peaks[i] for i in range(6, 10)} == {40}, "tile C峰周=40")
    lons = [c[0] for c in d["cells"]] + [c[2] for c in d["cells"]]
    check(all(-180.001 <= v <= 180.001 for v in lons), "跨日界线后经度均∈[-180,180]")
    has_wrap = any(abs(c[2] - 180.0) < 1e-9 for c in d["cells"])
    has_wrapped = any(abs(c[0] + 180.0) < 1e-9 for c in d["cells"])
    check(has_wrap and has_wrapped, "跨日界线cell拆成东西两半")
    near_a = [c for c in d["cells"] if abs(c[0] - 17.0) < 1.0]
    check(len(near_a) == 1, "tile B东侧cell落在区间末端(≈17.7..21)")
    west = [c for c in d["cells"] if -140.5 < c[0] < -133.0 and c[1] > 17.0]
    check(len(west) >= 1, f"tile C东端cell平移回西半球 (实得{west})")
    # 泛化解码: bbox过滤/LOD选择/周计数
    from app.core.migration import decode_view, lod_for_zoom, week_counts
    dv = decode_view(paths["sqlite"], "world", (100.0, 44.0, 116.0, 56.0))
    check(len(dv["cells"]) == 4, f"bbox过滤后tile A的4格 (实得{len(dv['cells'])})")
    check(all(c[0] == "world" for c in dv["cells"]), "view解码cells带lod键")
    dv0 = decode_view(paths["sqlite"], "world", (0.0, 0.0, 1.0, 1.0))
    check(len(dv0["cells"]) == 0, "不相交bbox解码为空")
    counts = week_counts(d)
    check(len(counts) == 52 and counts[22] == 4 and counts[2] == 2
          and counts[40] == 4 and counts[10] == 0,
          f"week_counts峰周计数 (w23={counts[22]} w3={counts[2]} "
          f"w41={counts[40]} w11={counts[10]})")
    check([lod_for_zoom(z) for z in (1.1, 2.5, 2.7, 4.1, 4.3, 5.7, 6.0)]
          == ["world", "world", "continental", "continental", "regional",
              "regional", "local"], "LOD缩放阈值")

    # manifest周历
    man = json.loads(Path(paths["manifest"]).read_text(encoding="utf-8"))
    dates = week_dates(man)
    check(len(dates) == 52 and dates[0] == "2023-01-04", "周历52条首周1月4日")


def semantic_tests():
    from app.core.migration import (decode_world, week_dates, world_geojson,
                                    frame_phases, week_counts)
    print("\n[3] 解码器(真实barswa数据, 语义)")
    d = decode_world(PROJ / "data/migration_probe/barswa_surface_tiles.sqlite")
    vals, W, n = d["values"], d["weeks"], len(d["cells"])
    check(W == 52 and n > 2000, f"52周且活跃cell {n}>2000")
    lons = [c[0] for c in d["cells"]] + [c[2] for c in d["cells"]]
    lats = [c[1] for c in d["cells"]] + [c[3] for c in d["cells"]]
    check(all(-180.001 <= v <= 180.001 for v in lons), "经度均∈[-180,180]")
    check(min(lats) > -62 and max(lats) < 86, "纬度范围合理(南美~北高纬)")

    def mean_at(pred, widx):
        vs = [vals[i * W + widx] for i in range(n) if pred(d["cells"][i])]
        return sum(vs) / max(1, len(vs))

    north = lambda c: c[3] > 42          # 北方繁殖带
    south = lambda c: c[1] < -10         # 南方越冬带
    nj, njly = mean_at(north, 22), mean_at(north, 0)
    sj, sje = mean_at(south, 0), mean_at(south, 22)
    check(nj > 20 * max(njly, 0.5), f"北半球6月丰度≫1月 ({nj:.1f} vs {njly:.1f})")
    check(sj > 10 * max(sje, 0.5), f"南半球1月丰度≫6月 ({sj:.1f} vs {sje:.1f})")

    # 西伯利亚东北tile(0,2): 区间[166.95→263.76]跨日界线, 峰周中位26
    # (6月下旬, 与侦察结论25一致; 活跃cell超百)
    import statistics
    t02 = [i for i in range(n)
           if d["cells"][i][3] > 42 and (
               (160 < d["cells"][i][0] < 180.01
                and 5.9 < d["cells"][i][2] - d["cells"][i][0] < 6.2)
               or (abs(d["cells"][i][2] - 180.0) < 0.01
                   and d["cells"][i][0] > 160)
               or (-180.01 <= d["cells"][i][0] < -96.0
                   and 5.9 < d["cells"][i][2] - d["cells"][i][0] < 6.2))]
    mids = [max(range(W), key=lambda k: vals[i * W + k])
            for i in t02 if any(vals[i * W:(i + 1) * W])]
    check(len(mids) > 100 and statistics.median(mids) in (25, 26),
          f"西伯利亚tile活跃{len(mids)}cell峰周中位={statistics.median(mids)} (预期25/26)")

    gj = world_geojson(d)
    check(len(gj["features"]) == n, "geojson feature数=活跃cell数")
    w0 = gj["features"][0]["properties"]["w"]
    check(len(w0) == 52 and all(isinstance(v, int) for v in w0),
          "feature.w为52个整数")

    man = json.loads((PROJ / "data/mig_barswa_manifest.json").read_text(
        encoding="utf-8"))
    dates = week_dates(man)
    check(len(dates) == 52 and dates[0] == "2023-01-04" and dates[51]
          == "2023-12-27", "真实manifest周历首尾正确")
    ph = frame_phases(man)
    from collections import Counter
    cph = Counter(ph)
    check(set(cph) == {"breeding", "nonBreeding",
                       "preBreedingMigration", "postBreedingMigration"}
          and sum(cph.values()) == 52,
          f"真实manifest四季段齐全52周 ({dict(cph)})")
    cnt = week_counts(d)
    check(len(cnt) == 52 and max(cnt) > 500 and min(cnt) >= 0,
          f"真实week_counts(峰值周{max(cnt)}cell)")


def ui_tests(server: _FakeServer):
    from PySide6.QtCore import QEventLoop, Qt, QTimer
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication.instance() or QApplication(sys.argv)
    from app import theme
    theme.apply_theme(app, "light")
    from app import i18n
    from app.db import Library
    from app.ui import migration_view as mv
    from app.core.migration import MigrationClient as _Real

    print("\n[4] 对话框渲染(真WebEngine, 数据走本地服务)")

    lib = Library(LIB_DIR / "ui")
    lib.fill_species()

    class PatchedClient(_Real):
        def __init__(self, lib_root, base_url=None):
            super().__init__(lib_root, base_url=server.base)

    mv.MigrationClient = PatchedClient

    dlg = mv.MigrationMapDialog(lib, None, "barswa")
    loop = QEventLoop()
    dlg._worker.decoded.connect(lambda *a: loop.quit())
    dlg._worker.failed.connect(lambda *a: loop.quit())
    QTimer.singleShot(30000, loop.quit)
    dlg.show()
    loop.exec()
    check(dlg._data_ready, "数据下载+解码30s内完成")
    if not dlg._data_ready:
        print("FAILED (数据未就绪)")
        sys.exit(1)
    dlg._timer.stop()  # 停自动播放便于断言

    check(dlg._timeline.isEnabled() and dlg._play_btn.isEnabled()
          and dlg._prev_btn.isEnabled() and dlg._next_btn.isEnabled(),
          "时间线/播放/上下周按钮已启用")
    check(dlg._timeline.weeks() == 52 and len(dlg._timeline._phases) == 52,
          "时间线52周+52季段")
    check(dlg._timeline._phases[0] == "nonBreeding"
          and dlg._timeline._phases[25] == "breeding",
          f"季段数据(nonBreeding→breeding) ({dlg._timeline._phases[:2]}…)")

    # 配色方案A: 单色深浅(色相=季段) 单元检查
    import re as _re
    from app.ui.migration_view import RESIDENT_MIN_WEEKS
    check(RESIDENT_MIN_WEEKS == 46, f"常驻阈值=46周 ({RESIDENT_MIN_WEEKS})")
    for key, (hexc, _pair) in mv._PHASES.items():
        ramp = mv.phase_ramp(key)
        vals = [_re.match(r"rgba\((\d+),(\d+),(\d+),([\d.]+)\)", r).groups()
                for r in ramp]
        br, bg, bb = (int(hexc[1:3], 16), int(hexc[3:5], 16),
                      int(hexc[5:7], 16))
        alphas = [float(v[3]) for v in vals]
        check(len(ramp) == 4 and vals[-1][:3] == (str(br), str(bg), str(bb)),
              f"phase_ramp[{key}] 4档且最深档=季段原色")
        check(alphas == sorted(alphas) and alphas[0] < alphas[-1],
              f"phase_ramp[{key}] 浅→深alpha单调 ({alphas})")
    check(mv.phase_ramp("") == mv.phase_ramp("unknown"),
          "未知季段回退中性灰(不崩)")
    check(dlg._week_lbl.text().startswith("第1周"),
          f"周标签ZH ({dlg._week_lbl.text()})")
    check("1月4日" in dlg._week_lbl.text(), "首周日期1月4日")

    def js_query(expr: str, timeout_ms: int = 4000):
        box = {}

        def done(v):
            box["v"] = v
        dlg.web.page().runJavaScript(expr, done)
        loop_q = QEventLoop()
        QTimer.singleShot(timeout_ms, loop_q.quit)
        loop_q.exec()
        return box.get("v")

    # 数据入JS要等地图'load'(底图瓦片就绪), 轮询等待
    wait_loop = QEventLoop()
    polls = {"n": 0}

    def poll():
        if js_query("!!window.__MIG", 1500) is True or polls["n"] > 20:
            wait_loop.quit()
        else:
            polls["n"] += 1
            QTimer.singleShot(500, poll)
    QTimer.singleShot(300, poll)
    QTimer.singleShot(30000, wait_loop.quit)
    wait_loop.exec()
    check(js_query("!!window.__MIG") is True, "地图load后迁徙数据注入JS")

    st = js_query("JSON.stringify(window.__MIG)")
    try:
        st = json.loads(st) if isinstance(st, str) else st
    except Exception:
        st = None
    check(isinstance(st, dict) and st.get("weeks") == 52
          and isinstance(st.get("counts"), list),
          f"JS侧__MIG含weeks/counts (实得{str(st)[:80]})")
    check(js_query("!!map && !!map.getSource('mig') && !!map.getLayer('mig-fill')"),
          "mig source/fill图层已挂载")
    # 方案A: 常驻描边层 + 单色深浅色带注入 + Python/JS常驻判定一致
    check(js_query("!!map.getLayer('mig-res')"), "常驻描边层mig-res已挂载")
    ramps_len = js_query("(RAMPS||[]).length")
    check(ramps_len == 52, f"52周单色深浅色带注入JS ({ramps_len})")
    r1 = js_query("RAMPS[0][3]")
    r22 = js_query("RAMPS[22][3]")
    r24 = js_query("RAMPS[24][3]")
    check(isinstance(r1, str) and "59,102,179" in r1,
          f"第1周(非繁)最深档=蓝原色 ({r1})")
    check(isinstance(r22, str) and "62,155,184" in r22,
          f"第23周(北迁)最深档=青原色 ({r22})")
    check(isinstance(r24, str) and "217,69,75" in r24,
          f"第25周(繁殖)最深档=红原色 ({r24})")
    gj_cache = dlg._world_cache[0]
    py_res = sum(1 for f in gj_cache["features"]
                 if sum(1 for v in f["properties"]["w"] if v > 0)
                 >= RESIDENT_MIN_WEEKS)
    js_res = js_query(
        "map.getSource('mig')._data.features.filter("
        "function(f){return f.properties.res;}).length")
    check(js_res == py_res,
          f"常驻区判定Python/JS一致 (≥{RESIDENT_MIN_WEEKS}周: {py_res})")
    dlg._on_week(23)
    check(js_query("window.__MIG.week") == 22, "切到第23周→JS week=22")
    filt = js_query("JSON.stringify(map.getFilter('mig-fill'))")
    check(filt and "22" in filt and "at" in filt,
          f"filter含周索引22 ({filt})")
    # 渲染层实证: 第23周(数据侧瓣)有cell真正画出, 第11周(全空)为零
    # (防filter/fill表达式静默失败——source/layer在≠画得出);
    # filter更新后要等一帧再查, 否则queryRenderedFeatures拿到旧状态
    def settle(ms: int = 1200):
        loop_s = QEventLoop()
        QTimer.singleShot(ms, loop_s.quit)
        loop_s.exec()

    dlg._on_week(23)
    settle()
    rendered = js_query("map.queryRenderedFeatures({layers:['mig-fill']}).length")
    check(isinstance(rendered, (int, float)) and rendered > 0,
          f"第23周实际渲染cell {rendered}>0")
    dlg._on_week(11)
    settle()
    rendered0 = js_query("map.queryRenderedFeatures({layers:['mig-fill']}).length")
    check(rendered0 == 0, f"第11周(无数据)实际渲染cell {rendered0}==0")
    nodata_vis = js_query(
        "document.getElementById('nodata').style.display")
    check(nodata_vis == "block",
          f"第11周无数据提示显示 (display={nodata_vis})")
    nodata_txt = js_query("document.getElementById('nodata').textContent")
    check(nodata_txt == "本周该视野无模拟数据", f"无数据提示ZH ({nodata_txt})")
    dlg._on_week(23)
    settle()
    nodata_vis2 = js_query(
        "document.getElementById('nodata').style.display")
    check(nodata_vis2 == "none", f"第23周提示隐藏 (display={nodata_vis2})")
    w23 = dlg._week_lbl.text()
    check("第23周" in w23 and "6月" in w23, f"第23周标签含6月 ({w23})")
    # LOD联动: 模拟放大到华东(continental)→JS counts变化→缩小恢复world
    world_counts = js_query("JSON.stringify(window.__MIG.counts)")
    dlg._on_viewport(3.0, 100.0, 40.0, 135.0, 56.0)
    cur = None
    for _ in range(30):
        settle(500)
        cur = js_query("JSON.stringify(window.__MIG.counts)")
        if isinstance(cur, str) and cur != world_counts:
            break
    check(isinstance(cur, str) and cur != world_counts,
          f"放大→continental LOD注入 (counts变化)")
    check(json.loads(cur)[22] == 4 and sum(json.loads(cur)) == 20,
          f"continental counts=tile A侧瓣5周×4格 ({cur[:60]}…)")
    src_cnt = js_query("map.querySourceFeatures('mig').length")
    check(isinstance(src_cnt, (int, float)) and src_cnt == 4,
          f"continental source features=4 (实得{src_cnt})")
    dlg._on_viewport(1.2, -20.0, 10.0, 40.0, 50.0)
    cur2 = None
    for _ in range(10):
        settle(500)
        cur2 = js_query("JSON.stringify(window.__MIG.counts)")
        if isinstance(cur2, str) and cur2 == world_counts:
            break
    check(cur2 == world_counts, "缩回→world counts恢复")
    # 播放/步进
    dlg._timer.stop()
    dlg._toggle_play()
    check(dlg._timer.isActive(), "播放启动")
    before = dlg._timeline.week()
    dlg._advance()
    check(dlg._timeline.week() == before % 52 + 1, "播放推进+1周(循环)")
    dlg._toggle_play()
    check(not dlg._timer.isActive(), "暂停")
    dlg._on_week(10)
    dlg._step(1)
    check(dlg._timeline.week() == 11, "‹›步进+1")
    dlg._step(-1)
    dlg._step(-1)
    check(dlg._timeline.week() == 9, "‹›步进-1")

    pm = dlg.grab()
    shots = PROJ / "data/ui_shots"
    shots.mkdir(exist_ok=True)
    pm.save(str(shots / "migration_map.png"))
    check(not pm.isNull(), "对话框截图保存(自渲染)")
    dlg._shutdown()
    dlg.close()

    # 目录外物种 → 错误提示+无重试
    dlg2 = mv.MigrationMapDialog(lib, None, "mallar3")
    loop2 = QEventLoop()
    dlg2._worker.failed.connect(lambda *a: loop2.quit())
    QTimer.singleShot(15000, loop2.quit)
    dlg2.show()
    loop2.exec()
    check("暂无迁徙数据" in dlg2._status.text(),
          f"目录外物种提示 ({dlg2._status.text()})")
    check(not dlg2._retry_btn.isVisible(), "目录外物种不显示重试")
    dlg2._shutdown()
    dlg2.close()

    # 断网+无缓存 → 离线提示
    lib3 = Library(LIB_DIR / "ui_offline")
    lib3.fill_species()

    class DeadClient(_Real):
        def __init__(self, lib_root, base_url=None):
            super().__init__(lib_root, base_url="http://127.0.0.1:9/")

    mv.MigrationClient = DeadClient
    dlg3 = mv.MigrationMapDialog(lib3, None, "barswa")
    loop3 = QEventLoop()
    dlg3._worker.failed.connect(lambda *a: loop3.quit())
    QTimer.singleShot(20000, loop3.quit)
    dlg3.show()
    loop3.exec()
    check("无法连接" in dlg3._status.text(),
          f"断网提示 ({dlg3._status.text()})")
    check(dlg3._retry_btn.isVisible(), "断网显示重试")
    dlg3._shutdown()
    dlg3.close()

    # EN模式周标签(切语言后重建对话框场景)
    i18n.set_lang("en")
    mv.MigrationClient = PatchedClient
    dlg4 = mv.MigrationMapDialog(lib, None, "barswa")
    loop4 = QEventLoop()
    dlg4._worker.decoded.connect(lambda *a: loop4.quit())
    QTimer.singleShot(20000, loop4.quit)
    dlg4.show()
    loop4.exec()
    check(dlg4._week_lbl.text().startswith("Week 1 · Jan 4"),
          f"EN周标签 ({dlg4._week_lbl.text()})")
    dlg4._shutdown()
    dlg4.close()
    i18n.set_lang("zh")


def main():
    if LIB_DIR.exists():
        shutil.rmtree(LIB_DIR)
    if (PROJ / "data/migration_server").exists():
        shutil.rmtree(PROJ / "data/migration_server")
    server = _FakeServer(PROJ / "data/migration_server")
    try:
        build_fake_species(server.root)
        client_tests(server)
        semantic_tests()
        ui_tests(server)
    finally:
        server.stop()

    print()
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
