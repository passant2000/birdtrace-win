# -*- coding: utf-8 -*-
"""静态站 标签/作品集筛选视图(10a) 验证: gallery.json 填充(排除拒绝片/
带主鸟种名/空组不进)+index.html 第4Tab渲染标记+无数据时Tab隐藏标记+
原图两档照常。纯生成, 不跑模型, 约10秒。"""
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
        "INSERT INTO batches(mode,dest,region_id,count) VALUES('copy',?,'CN',3)",
        (str(D / "src"),))
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
        pids.append(pid)
    lib.conn.commit()

    # 标签(前2张) + 作品集(后2张) + 一个空标签(不应出现在数据里)
    tid = lib.tag_create("飞行")
    tid2 = lib.tag_create("空标签")
    for pid in pids[:2]:
        lib.conn.execute(
            "INSERT INTO photo_tags(tag_id,photo_id) VALUES(?,?)", (tid, pid))
    cid = lib.collection_create("精选")
    mem = lib.collection_photos_of(cid)
    lib.collection_set_photos(cid, mem + pids)
    lib.conn.commit()

    from app.core.static_site import build_site
    dest = D / "site"
    ret = build_site(lib, dest)
    check(ret["photos"] == 3 and ret["thumb"] == 3, f"站点生成 ({ret})")
    g = json.loads((dest / "gallery.json").read_text(encoding="utf-8"))
    check(len(g["tags"]) == 1 and g["tags"][0]["name"] == "飞行",
          f"tags 填充且空标签剔除 ({[x['name'] for x in g['tags']]})")
    check(len(g["tags"][0]["photos"]) == 2
          and all(p["cn"] for p in g["tags"][0]["photos"]),
          "tag photos 带主鸟种名")
    check(len(g["collections"]) == 1
          and g["collections"][0]["name"] == "精选"
          and len(g["collections"][0]["photos"]) == 3, "collections 填充")
    html = (dest / "index.html").read_text(encoding="utf-8")
    check('data-v="albums"' in html and "renderAlbums" in html,
          "index.html 含专辑Tab与渲染函数")
    check("标签 · 作品集" in html, "Tab 中文标签")
    check("G.tags" in html, "数据注入")
    # 拒绝片排除: 标记1张拒绝 → tags/collections 该张剔除
    lib.set_pick([pids[0]], "reject")
    g2 = lib.site_data()
    names_t = [x["name"] for x in g2["tags"]]
    check(len(g2["tags"]) == 1 and len(g2["tags"][0]["photos"]) == 1,
          f"拒绝片从标签剔除 ({names_t})")
    check(len(g2["collections"][0]["photos"]) == 2, "拒绝片从作品集剔除")
    check(g2["meta"]["photos"] == 2, "meta 口径同步排除")

    # 无数据库: gallery.json tags/collections 空 → 模板仍生成(Tab由JS隐藏)
    D2 = PROJ / "data/_site_check_empty"
    if D2.exists():
        shutil.rmtree(D2)
    D2.mkdir(parents=True)
    lib2 = Library(D2)
    lib2.fill_species()
    dest2 = D2 / "site"
    build_site(lib2, dest2)
    g3 = json.loads((dest2 / "gallery.json").read_text(encoding="utf-8"))
    check(g3["tags"] == [] and g3["collections"] == [], "空库字段=空数组")
    check("tab-albums" in (dest2 / "index.html").read_text(encoding="utf-8"),
          "空库模板仍完整")

    print("\n" + ("FAIL" if FAILED["v"] else "ALL PASS"))
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
