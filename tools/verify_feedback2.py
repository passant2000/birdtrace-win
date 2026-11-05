# -*- coding: utf-8 -*-
"""0.8.0-test3 第二批反馈修复验证(离线, 合成库)。

用户反馈(2026-11-05):
  [1] 一张照片出现两个"主鸟"——识别结果与sidecar回填并发写入
  [2] 待复核下拉没有top5候选, 只有"（最近）"
  [3] 图鉴地区显示成最后一次导入的地区(安徽), 而非照片实际地区(上海)
  [4] 图鉴正文在深色主题下与背景同色

覆盖:
  [1] add_records 幂等(重复写不叠加) + 人工记录优先不被覆盖
  [2] 老库启动自愈去重(同照片同rank多条→留最优)
  [3] sidecar 存取 top5 候选(导出→清空→回填)
  [4] sp_extend_candidates 候选补齐(定种/置信不变)
  [5] 图鉴地区按物种照片实际地区(最美照优先), 非全局默认
  [6] 图鉴正文颜色主题感知(深色主题下为深色LABEL)

用法: .venv/Scripts/python.exe tools/verify_feedback2.py
"""
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


def make_img(path: Path, seed: int = 0):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (320, 240), (70 + seed * 9 % 120, 110, 140))
    d = ImageDraw.Draw(im)
    d.ellipse([70, 60, 250, 190], fill=(230, 200, 120))
    im.save(path, "JPEG")


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme, i18n
    theme.apply_theme(app, "light")
    i18n.set_lang("zh")

    BASE = PROJ / "data/feedback2_check"
    if BASE.exists():
        shutil.rmtree(BASE)
    (BASE / "src").mkdir(parents=True)
    from app.db import Library
    import app.media as media

    lib = Library(BASE / "lib")
    lib.fill_species()
    codes = [r["code"] for r in lib.conn.execute(
        "SELECT code FROM species WHERE in_classifier=1 LIMIT 5").fetchall()]
    A, B, C, D, E = codes
    lib.conn.execute("INSERT INTO batches(region_id) VALUES('CN-SH')")
    sh_batch = lib.conn.execute("SELECT id FROM batches").fetchone()["id"]

    def add(name, seed, ts, code=None, conf=0.9):
        p = BASE / "src" / f"{name}.jpg"
        make_img(p, seed)
        pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                            p.stat().st_mtime, 320, 240, sh_batch)
        lib.conn.execute("INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
                         (pid, ts))
        if code:
            lib.add_records(pid, [{"species_code": code, "confidence": conf,
                                   "top5": [{"code": code, "prob": conf},
                                            {"code": B, "prob": 0.02}]}])
        return pid

    print("\n[1] add_records 幂等 + 人工优先")
    p1 = add("p1", 1, "2026-09-26 07:41:14", A)
    lib.add_records(p1, [{"species_code": C, "confidence": 0.8,
                          "top5": [{"code": C, "prob": 0.8}]}])
    n = lib.conn.execute("SELECT COUNT(*) FROM records WHERE photo_id=?",
                         (p1,)).fetchone()[0]
    now = lib.conn.execute(
        "SELECT species_code FROM records WHERE photo_id=? AND rank=1",
        (p1,)).fetchone()["species_code"]
    check(n == 1 and now == C, f"重复写入=整体替换非叠加 ({n}条, {now})")
    lib.set_confirmed(lib.conn.execute(
        "SELECT id FROM records WHERE photo_id=?", (p1,)).fetchone()["id"], D)
    lib.add_records(p1, [{"species_code": A, "confidence": 0.99}])
    n2 = lib.conn.execute(
        "SELECT COUNT(*) FROM records WHERE photo_id=?", (p1,)).fetchone()[0]
    eff = lib.conn.execute(
        "SELECT confirmed_code FROM records WHERE photo_id=?", (p1,)
    ).fetchone()["confirmed_code"]
    check(n2 == 1 and eff == D, f"人工确认后自动结果不覆盖 ({n2}条, {eff})")

    print("\n[2] 老库启动自愈去重(双主鸟)")
    p2 = add("p2", 2, "2026-09-26 07:41:15", A)
    # 制造历史脏数据: 第二条rank=1(无top5)
    lib.conn.execute(
        "INSERT INTO records(photo_id,species_code,rank,confidence,source) "
        "VALUES(?,?,1,?, 'manual')", (p2, B, 0.9))
    lib.conn.commit()
    n_before = lib.conn.execute(
        "SELECT COUNT(*) FROM records WHERE photo_id=? AND rank=1",
        (p2,)).fetchone()[0]
    check(n_before == 2, f"构造2条rank=1 ({n_before})")
    lib.close()
    lib2 = Library(BASE / "lib")           # 重开→_migrate自愈
    n_after = lib2.conn.execute(
        "SELECT COUNT(*) FROM records WHERE photo_id=? AND rank=1",
        (p2,)).fetchone()[0]
    src_after = lib2.conn.execute(
        "SELECT species_code, source FROM records WHERE photo_id=? AND rank=1",
        (p2,)).fetchone()
    check(n_after == 1 and src_after["source"] == "manual",
          f"自愈后1条且保留人工 ({dict(src_after)})")
    lib = lib2

    print("\n[3] sidecar 存取 top5")
    from app.core import sidecar
    folder = BASE / "src"
    sc = sidecar.export_folder(lib, folder)
    data = json.loads(Path(sc).read_text(encoding="utf-8"))["photos"]
    entry = next(v for v in data.values()
                 if isinstance(v, dict) and v.get("file") == "p1.jpg")
    check(entry["records"] and entry["records"][0].get("top5"),
          f"导出含top5候选 ({entry['records'][0].get('top5')})")
    lib.conn.execute("DELETE FROM records WHERE photo_id=?", (p1,))
    lib.conn.commit()
    sidecar.apply_entry(lib, p1, entry)
    restored = lib.conn.execute(
        "SELECT top5_json FROM records WHERE photo_id=?", (p1,)).fetchone()
    t5 = json.loads(restored["top5_json"] or "[]")
    check(len(t5) >= 1, f"回填恢复top5 ({len(t5)}个候选)")

    print("\n[4] sp_extend_candidates 候选补齐")
    import numpy as np
    from app.ai.sp_engine import sp_extend_candidates
    labels = [{"code": A, "en": "A", "sci": "A"},
              {"code": B, "en": "B", "sci": "B"},
              {"code": C, "en": "C", "sci": "C"},
              {"code": D, "en": "D", "sci": "D"}]
    probs = np.array([0.50, 0.002, 0.001, 0.0005])
    tier = frozenset({A, B, C, D})
    picked = [{"code": A, "en": "A", "sci": "A", "prob": 0.50}]
    out = sp_extend_candidates(probs, [tier], labels, list(picked), 5)
    check([p["code"] for p in out] == [A, B, C, D]
          and out[0]["prob"] == 0.50,
          f"低概率候选补齐到top5({len(out)}个), top1不变")
    out2 = sp_extend_candidates(probs, [], labels, list(picked), 5)
    check(len(out2) == 1, "全球模式(无名录层)不补齐")

    print("\n[5] 图鉴地区=照片实际地区(非最后导入的默认地区)")
    # p1此前被确认成了D(见[1])——还原为A, 让A同时有上海/安徽两张照片
    lib.conn.execute(
        "UPDATE records SET species_code=?, confirmed_code=NULL, reviewed=0 "
        "WHERE photo_id=?", (A, p1))
    lib.conn.commit()
    # 第二批: 安徽(更晚导入), 但该物种最美照在上海批次
    lib.conn.execute("INSERT INTO batches(region_id) VALUES('CN-AH')")
    ah_batch = lib.conn.execute(
        "SELECT id FROM batches ORDER BY id DESC LIMIT 1").fetchone()["id"]
    p3 = BASE / "src" / "p3.jpg"
    make_img(p3, 3)
    pid3 = lib.add_photo(str(p3), media.file_hash(p3), p3.stat().st_size,
                         p3.stat().st_mtime, 320, 240, ah_batch)
    lib.conn.execute("INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
                     (pid3, "2026-10-27 09:48:28"))
    lib.add_records(pid3, [{"species_code": A, "confidence": 0.8}])
    lib.set_aesthetic(p1, 9.0)     # p1(上海)=最美
    lib.set_aesthetic(pid3, 5.0)   # p3(安徽)较晚但分低
    lib.set_setting("default_region", "CN-AH")   # 最后导入地区
    lib.conn.commit()
    from app.ui.species_page import SpeciesPage
    sp = SpeciesPage(lib, None)
    sp.current_code = A
    photos = lib.photos_of_species(A)
    reg = sp._species_region(photos)
    check(reg == "CN-SH", f"最美照地区优先→CN-SH (got {reg})")
    # 只有安徽照片的物种→安徽
    sp.current_code = B
    lib.add_records(pid3, [{"species_code": B, "confidence": 0.7}])
    photos_b = lib.photos_of_species(B)
    reg_b = sp._species_region(photos_b)
    check(reg_b == "CN-AH", f"仅安徽照片的物种→CN-AH (got {reg_b})")
    # 无照片物种→默认地区兜底
    sp.current_code = "nonexistent1"
    reg_none = sp._species_region([])
    check(reg_none == "CN-AH", f"无照片回退默认地区 (got {reg_none})")

    print("\n[6] 图鉴正文颜色主题感知")
    theme.apply_theme(app, "dark")
    from app.ui.species_page import _info_row
    w = _info_row("概述", "测试正文")
    val = w.findChildren(QLabel)[-1]
    dark_label = theme.LABEL        # 深色主题=#F2F2F7
    check(dark_label.lower() in val.styleSheet().lower()
          and "#1c1c1e" not in val.styleSheet().lower(),
          f"深色主题用LABEL({dark_label}) ({val.styleSheet()})")
    theme.apply_theme(app, "light")

    print("\n[7] 待复核下拉显示top5候选")
    # 低置信记录 + 5个候选 → 下拉应有 保持 + 4个候选(不含当前种)
    p5 = BASE / "src" / "p5.jpg"
    make_img(p5, 5)
    pid5 = lib.add_photo(str(p5), media.file_hash(p5), p5.stat().st_size,
                         p5.stat().st_mtime, 320, 240, sh_batch)
    lib.conn.execute("INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
                     (pid5, "2026-10-27 13:02:00"))
    cands = [{"code": A, "prob": 0.2}, {"code": B, "prob": 0.15},
             {"code": C, "prob": 0.1}, {"code": D, "prob": 0.05},
             {"code": E, "prob": 0.03}]
    lib.add_records(pid5, [{"species_code": A, "confidence": 0.2,
                            "top5": cands}])
    from app.ui.review_page import ReviewPage
    rp = ReviewPage(lib, None)
    rp.refresh()
    from PySide6.QtWidgets import QComboBox
    combos = rp.findChildren(QComboBox)
    items = [combos[0].itemText(i) for i in range(combos[0].count())] \
        if combos else []
    check(len([x for x in items if "%" in x]) >= 4
          and any("（保持）" in x for x in items),
          f"待复核下拉含top5候选 ({items[:6]})")
    rp.close()

    print("\n" + ("FAIL" if FAILED["v"] else "ALL PASS"))
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
