# -*- coding: utf-8 -*-
"""静态图库站(2026-11-20 重做)验证: 多页结构(首页/图鉴/详情/时间轴/地区)
+ 占位符零残留 + 前端标签键齐全 + 隐私(无坐标/无鸟点名) + 标签/作品集
分组能力保留 + 拒绝片排除 + 空库降级 + 图片两档。纯生成, 约 15 秒。"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

FAILED = {"v": False}
TOKEN_RE = re.compile(r"__[A-Z][A-Z0-9_]{2,}__")


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    app = QApplication(sys.argv)
    app.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    from app import theme, i18n
    theme.apply_theme(app, "light")
    i18n.set_lang("zh")

    D = PROJ / "data/_site_check"
    if D.exists():
        shutil.rmtree(D)
    D.mkdir(parents=True)
    from app.db import Library
    import app.media as media
    lib = Library(D)
    lib.fill_species()
    lib.conn.execute(
        "INSERT INTO batches(mode,dest,region_id,count) "
        "VALUES('copy',?,'CN-AH',3)", (str(D / "src"),))
    bid = lib.conn.execute("SELECT id FROM batches LIMIT 1").fetchone()["id"]
    IMGS = ["Alcedo_atthis.jpg", "Anas_platyrhynchos.jpg", "Ardea_cinerea.jpg"]
    codes = []
    for kw in ("%kingfisher%", "%mallard%", "%gray heron%"):
        codes.append(lib.conn.execute(
            "SELECT code FROM species WHERE en LIKE ? LIMIT 1",
            (kw,)).fetchone()["code"])
    pids = []
    for i, img in enumerate(IMGS):
        p = D / f"b{i}.jpg"
        shutil.copy(PROJ / "data/test_images" / img, p)
        pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                            p.stat().st_mtime, 0, 0, bid)
        lib.conn.execute(
            "INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
            (pid, f"2026-05-20 0{i + 8}:00:00"))
        lib.conn.execute(
            "INSERT INTO records(photo_id,species_code,rank,confidence,"
            "source) VALUES(?,?,1,0.9,'detect')", (pid, codes[i]))
        lib.set_aesthetic(pid, 7.0 + i)
        pids.append(pid)
    sp = lib.create_spot("私密鸟点甲", 31.23, 121.47)
    lib.set_photos_spot(pids, sp)
    lib.conn.commit()

    # 标签 + 作品集(含一个空标签: 不应进数据)
    tid = lib.tag_create("飞行")
    lib.tag_create("空标签")
    for pid in pids[:2]:
        lib.conn.execute(
            "INSERT INTO photo_tags(tag_id,photo_id) VALUES(?,?)", (tid, pid))
    cid = lib.collection_create("精选")
    lib.collection_set_photos(cid, lib.collection_photos_of(cid) + pids)
    lib.conn.commit()

    from app.core.static_site import build_site
    dest = D / "site"
    ret = build_site(lib, dest)

    # ---------- [1] 多页结构 ----------
    print("[1] 多页结构")
    expected = ["index.html", "gallery.html", "species.html",
                "timeline.html", "regions.html"]
    check(all((dest / n).is_file() for n in expected),
          f"5 个页面齐 ({ret.get('pages')})")
    check(all((dest / n).is_file() for n in
              ("style.css", "app.js", "gallery.js", "gallery.json")),
          "样式/脚本/数据齐")
    leftover = []
    for n in expected:
        hits = TOKEN_RE.findall((dest / n).read_text(encoding="utf-8"))
        if hits:
            leftover.extend((n, h) for h in hits)
    check(not leftover, f"模板占位符零残留 ({leftover[:3]})")
    gjs = (dest / "gallery.js").read_text(encoding="utf-8")
    check("window.G=" in gjs and "window.L=" in gjs, "gallery.js 注入数据+标签")

    # ---------- [2] 前端标签键齐全 ----------
    print("[2] 前端标签")
    appjs = (dest / "app.js").read_text(encoding="utf-8")
    used = set(re.findall(r"L\.([a-zA-Z_]+)", appjs))
    L = json.loads(gjs.split("window.L=", 1)[1].rstrip(";\n"))
    missing = sorted(k for k in used if k not in L)
    check(not missing, f"app.js 引用的标签键全部存在 (缺 {missing})")
    check(L.get("gallery") and L.get("timeline") and L.get("regions"),
          "导航/页面标签已本地化")

    # ---------- [3] 首页 ----------
    print("[3] 首页")
    idx = (dest / "index.html").read_text(encoding="utf-8")
    check('class="bg"' in idx, "Hero 图/渐变存在")
    check("images/" in idx and ".1280.webp" in idx, "Hero 用 1280 展示图")
    g = json.loads((dest / "gallery.json").read_text(encoding="utf-8"))
    hero = g["meta"].get("hero")
    check(hero and hero.get("h"), f"meta.hero 存在 ({hero and hero.get('cn')})")
    check('<b>3</b>' in idx.replace(" ", ""),
          "统计数字来自真实数据(3 作品)")

    # ---------- [4] 图鉴/详情/时间轴/地区 ----------
    print("[4] 各页面")
    gal = (dest / "gallery.html").read_text(encoding="utf-8")
    check('id="chips"' in gal and 'id="gchips"' in gal and 'id="q"' in gal,
          "图鉴: 筛选胶囊+分组胶囊+搜索")
    check("标签 · 作品集" in gjs, "标签/作品集分组能力保留")
    spe = (dest / "species.html").read_text(encoding="utf-8")
    check('id="detail"' in spe, "详情页容器")
    tml = (dest / "timeline.html").read_text(encoding="utf-8")
    check(tml.count('class="mgroup"') >= 1, "时间轴: 月份分组")
    check("2026-05" in tml and ".256.webp" in tml, "时间轴: 日期+缩略图")
    rgn = (dest / "regions.html").read_text(encoding="utf-8")
    check(rgn.count("<path") >= 30, f"地区: 省界路径 ({rgn.count('<path')})")
    check('class="dot"' in rgn, "地区: 点位(省域中心)")
    check("中国·安徽" in rgn, "地区: 省名")

    # ---------- [5] 隐私 ----------
    print("[5] 隐私")
    check("私密鸟点甲" not in rgn and "私密鸟点甲" not in gjs,
          "鸟点名不进站点")
    check('"lat"' not in gjs and '"lon"' not in gjs,
          "坐标不进站点数据")
    check('"spot"' not in gjs, "鸟点字段不进站点数据")

    # ---------- [6] 标签/作品集 + 拒绝片 ----------
    print("[6] 分组数据")
    check(len(g["tags"]) == 1 and g["tags"][0]["name"] == "飞行",
          f"tags 填充/空标签剔除 ({[x['name'] for x in g['tags']]})")
    check(len(g["collections"]) == 1
          and len(g["collections"][0]["photos"]) == 3, "collections 填充")
    lib.set_pick([pids[0]], "reject")
    g2 = lib.site_data()
    check(len(g2["tags"][0]["photos"]) == 1, "拒绝片从标签剔除")
    check(len(g2["collections"][0]["photos"]) == 2, "拒绝片从作品集剔除")
    check(g2["meta"]["photos"] == 2, "meta 口径同步排除")

    # ---------- [7] 图片两档 ----------
    print("[7] 图片")
    thumbs = list((dest / "images").glob("*.256.webp"))
    webs = list((dest / "images").glob("*.1280.webp"))
    check(len(thumbs) == 3 and len(webs) == 3,
          f"两档 webp ({len(thumbs)}/{len(webs)})")
    check(ret["thumb"] == 3 and ret["web"] == 3, f"返回统计 ({ret})")

    # ---------- [8] 空库 ----------
    print("[8] 空库")
    D2 = PROJ / "data/_site_check_empty"
    if D2.exists():
        shutil.rmtree(D2)
    D2.mkdir(parents=True)
    lib2 = Library(D2)
    lib2.fill_species()
    dest2 = D2 / "site"
    ret2 = build_site(lib2, dest2)
    idx2 = (dest2 / "index.html").read_text(encoding="utf-8")
    check('<img class="bg"' not in idx2, "空库 Hero 用渐变(不虚构图片)")
    check("linear-gradient" in idx2, "空库渐变兜底存在")
    tml2 = (dest2 / "timeline.html").read_text(encoding="utf-8")
    check("empty" in tml2, "空库时间轴空状态")
    rgn2 = (dest2 / "regions.html").read_text(encoding="utf-8")
    check("empty" in rgn2, "空库地区空状态")
    check(ret2["species"] == 0 and ret2["photos"] == 0,
          f"空库统计 ({ret2['species']}/{ret2['photos']})")
    lib2.close()

    print("\n" + ("FAIL" if FAILED["v"] else "ALL PASS"))
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
