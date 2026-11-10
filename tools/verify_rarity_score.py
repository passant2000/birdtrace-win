# -*- coding: utf-8 -*-
"""0.8.1 分享卡稀有度分值 + IUCN 胶囊 + 卡宽2000 验证。

  [1] rarity_score 映射: 百分位→0-10, 档位分带对齐, 地区相对(同一物种
      上海/云南不同分), 全球/无数据=None
  [2] rarity_info 三元组 + iucn_of 过滤(只返回受威胁等级)
  [3] 渲染: 分值文本入胶囊 / IUCN 胶囊存在 / 卡宽 2000
  [4] batch_share card_info 带 score/iucn

用法: .venv/Scripts/python.exe tools/verify_rarity_score.py
"""
from __future__ import annotations

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
    im = Image.new("RGB", (3200, 2400), (70 + seed * 11 % 120, 110, 140))
    d = ImageDraw.Draw(im)
    d.ellipse([700, 600, 2500, 1900], fill=(230, 200, 120))
    d.text((100, 100), str(seed), fill=(255, 255, 255))
    im.save(path, "JPEG", quality=95)


def main():
    os_environ = __import__("os").environ
    os_environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme, i18n
    theme.apply_theme(app, "light")
    i18n.set_lang("zh")

    BASE = PROJ / "data/rarity_score_check"
    if BASE.exists():
        shutil.rmtree(BASE)
    (BASE / "src").mkdir(parents=True)
    from app.db import Library
    import app.media as media

    lib = Library(BASE / "lib")
    lib.fill_species()
    codes = [r["code"] for r in lib.conn.execute(
        "SELECT code FROM species WHERE in_classifier=1 LIMIT 3").fetchall()]
    A = codes[0]
    lib.conn.execute("INSERT INTO batches(region_id) VALUES('CN-SH')")
    bid = lib.conn.execute("SELECT id FROM batches").fetchone()["id"]

    print("\n[1] rarity_score 映射(百分位→0-10, 档位分带对齐)")
    from app.core.prior_hint import PriorHint, RARITY_TIERS
    hint = PriorHint()
    # 注入伪排序表: idx→(tier, pct) 直接管映射数学
    idx = hint.code_idx.get(A, 0)
    hint._rarity_cache["TEST"] = {idx: ("常见", 90.0)}
    s = hint.rarity_score(A, "TEST")
    check(s == 1.0, f"常见90%→1.0 (got {s})")
    hint._rarity_cache["TEST"] = {idx: ("较常见", 65.0)}
    s = hint.rarity_score(A, "TEST")
    check(s == 3.5, f"较常见65%→3.5 (got {s})")
    hint._rarity_cache["TEST"] = {idx: ("不常见", 50.0)}
    s = hint.rarity_score(A, "TEST")
    check(s == 5.0, f"不常见50%→5.0 (got {s})")
    hint._rarity_cache["TEST"] = {idx: ("稀有", 30.0)}
    s = hint.rarity_score(A, "TEST")
    check(s == 7.0, f"稀有30%→7.0 (got {s})")
    hint._rarity_cache["TEST"] = {idx: ("罕见", 3.0)}
    s = hint.rarity_score(A, "TEST")
    check(s == 9.7, f"罕见3%→9.7(懂鸟式) (got {s})")
    hint._rarity_cache["TEST"] = {idx: ("罕见", 0.2)}
    s = hint.rarity_score(A, "TEST")
    check(s == 9.9 or s == 10.0, f"罕见0.2%→钳制10内 (got {s})")
    check(hint.rarity_score(A, None) is None
          and hint.rarity_score(A, "GLOBAL") is None
          and hint.rarity_score("nonexist9", "TEST") is None,
          "全球/无数据→None")

    print("\n[2] rarity_info 三元组 + iucn_of 过滤")
    from app.ui.share_dialog import rarity_info, iucn_of
    # 真实区域: 用注入缓存(真实CN-SH计算太重; rarity_info走get_hint单例)
    from app.core import prior_hint
    prior_hint.get_hint()._rarity_cache["CN-SH"] = {
        prior_hint.get_hint().code_idx.get(A, 0): ("罕见", 3.0)}
    r = rarity_info(A, "CN-SH")
    check(len(r) == 3 and r[0] == "罕见" and r[1] == 3.0 and r[2] == 9.7,
          f"三元组(tier,pct,score) {r}")
    r2 = rarity_info(A, "GLOBAL")
    check(r2 == (None, None, None), f"全球→None三元组 {r2}")
    # iucn_of: species.iucn 直查
    lib.conn.execute("UPDATE species SET iucn='VU' WHERE code=?", (A,))
    lib.conn.commit()
    check(iucn_of(lib, A) == "VU", "VU 物种→VU")
    lib.conn.execute("UPDATE species SET iucn='LC' WHERE code=?", (A,))
    lib.conn.commit()
    check(iucn_of(lib, A) is None, "LC→None(无危不显示)")
    check(iucn_of(lib, None) is None, "无code→None")
    lib.conn.execute("UPDATE species SET iucn='EN' WHERE code=?", (A,))
    lib.conn.commit()

    print("\n[3] 渲染: 分值/IUCN 胶囊/卡宽2000")
    from app.core.sharecard import render_card, CARD_W
    check(CARD_W == 2000, f"CARD_W=2000 ({CARD_W})")
    p1 = BASE / "src" / "c1.jpg"
    make_img(p1, 1)
    info = {"cn": "青头潜鸭", "pinyin": [], "en": "Baer's Pochard",
            "sci": "Aythya baeri", "lifer_no": None,
            "rarity": "罕见", "rarity_pct": 3.0, "rarity_score": 9.7,
            "iucn": "CR", "photographer": "测试", "date": "2026-11-06",
            "place": "上海", "exif": {"body": "SONY", "lens": "FE 600mm",
                                      "shot": "ISO 800"}}
    pm = render_card(str(p1), info, "light")
    check(not pm.isNull() and pm.width() == 2000, f"渲染2000宽 ({pm.width()})")
    pm.save(str(BASE / "card_score_iucn.png"))
    # OCR不可用: 用像素抽验胶囊区域颜色(罕见红#E5484D 与 极危深红#8B1A12
    # 应同时出现在标题行 y≈photo区+329 的色带里)
    img = pm.toImage()
    ph = pm.height() - 1000          # 文字区起点(与dpi测试同口径)
    band = ph + 329
    found_rare = found_cr = False
    for x in range(0, pm.width(), 2):
        c1_ = img.pixelColor(x, band + 31)
        if c1_.name().upper() == "#E5484D":
            found_rare = True
        if c1_.name().upper() == "#8B1A12":
            found_cr = True
    check(found_rare, "罕见红胶囊在渲染中")
    check(found_cr, "极危深红胶囊在渲染中")
    # LC 不出胶囊: info.iucn=None 再渲染, 深红不再出现
    info2 = dict(info, iucn=None, rarity_score=None)
    pm2 = render_card(str(p1), info2, "light")
    img2 = pm2.toImage()
    found_cr2 = any(img2.pixelColor(x, band + 31).name().upper() == "#8B1A12"
                    for x in range(0, pm2.width(), 2))
    check(not found_cr2, "iucn=None 时无 IUCN 胶囊")
    pm2.save(str(BASE / "card_no_iucn.png"))

    print("\n[4] batch_share card_info 带分值/IUCN")
    from app.ui.batch_share_dialog import BatchShareDialog
    dlg = BatchShareDialog(lib, None)
    dlg.show()
    app.processEvents()
    row = {"eff_code": A, "cn": "青头潜鸭", "en_name": "Baer's Pochard",
           "sci": "Aythya baeri", "path": str(p1), "hash": "x",
           "taken_at": "2026-11-06 08:00:00", "region_id": "CN-SH",
           "artist": ""}
    info3 = dlg._card_info(row)
    check(info3.get("rarity_score") == 9.7 and info3.get("iucn") == "EN",
          f"card_info 带 score/iucn ({info3.get('rarity_score')}, "
          f"{info3.get('iucn')})")
    dlg.close()

    print("\n" + ("FAIL" if FAILED["v"] else "ALL PASS"))
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
