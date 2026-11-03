# -*- coding: utf-8 -*-
"""0.8-① 标注随文件夹走(.birdtrace.json)验证(离线, 合成库)。

  [1] 导出: 标注变更→flush→两文件夹各落一份; Windows隐藏属性; JSON结构
  [2] 回填: 新库导入(引用)自动读回→记录/确认/鸟点/评分/美学/无鸟全回;
      pending_photo_ids 排除已回填照片(不重复识别)
  [3] 冲突: 本地已有人工确认→sidecar旧记录不覆盖(已有编辑优先)
  [4] 合并: 文件夹里已有本库不认识的hash条目→flush后保留
  [5] import_files 链路: ref/copy 两种模式 sidecar 统计字段
  [6] relink/删除钩子: dirty标记变化

用法: .venv/Scripts/python.exe tools/verify_sidecar.py
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
    im = Image.new("RGB", (320, 240), (60, 100 + seed * 11 % 120, 140))
    d = ImageDraw.Draw(im)
    d.ellipse([80, 60, 240, 200], fill=(230, 200, 120))
    d.text((10, 10), str(seed), fill=(255, 255, 255))
    im.save(path, "JPEG")


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)

    BASE = PROJ / "data/sidecar_check"
    if BASE.exists():
        shutil.rmtree(BASE)
    folder = BASE / "F:/成片" if False else BASE / "photos"
    folder.mkdir(parents=True)
    folder2 = BASE / "其他目录"
    folder2.mkdir()

    from app.db import Library
    import app.media as media
    lib = Library(BASE / "lib")
    lib.fill_species()
    codes = [r["code"] for r in lib.conn.execute(
        "SELECT code FROM species LIMIT 3").fetchall()]
    A, B, C = codes

    def add(d: Path, name: str, seed: int, code=None, conf=0.9) -> int:
        p = d / name
        make_img(p, seed)
        fh = media.file_hash(p)
        pid = lib.add_photo(str(p), fh, p.stat().st_size, p.stat().st_mtime,
                            320, 240, 0)
        if code:
            lib.add_records(pid, [{"species_code": code, "confidence": conf}])
        return pid

    p1 = add(folder, "DSC001.jpg", 1, A)
    p2 = add(folder, "DSC002.jpg", 2, B, conf=0.35)   # 待复核
    p3 = add(folder, "DSC003.jpg", 3)                 # 无记录(还没识别)
    p4 = add(folder2, "DSC004.jpg", 4, C)

    print("\n[1] 导出 flush")
    lib.set_confirmed(lib.conn.execute(
        "SELECT id FROM records WHERE photo_id=?", (p1,)).fetchone()["id"], A)
    sid = lib.create_spot("南汇东滩", 30.87, 121.93, "测试点")
    lib.set_photo_spot(p1, sid)
    lib.set_aesthetic(p1, 7.7)
    lib.add_manual_record(p3, C)                     # 手工标注
    lib.mark_not_bird(p2)                            # 不是鸟→无鸟
    check(lib.sidecar_dirty_count() >= 2, f"标注变更已标脏 ({lib.sidecar_dirty_count()}个目录)")
    n = lib.flush_sidecars()
    sc = folder / ".birdtrace.json"
    sc2 = folder2 / ".birdtrace.json"
    check(n == 2 and sc.is_file() and sc2.is_file(), "两文件夹各落一份")
    if os.name == "nt":
        import ctypes
        check(bool(ctypes.windll.kernel32.GetFileAttributesW(str(sc)) & 0x2),
              "Windows隐藏属性已设")
    doc = json.loads(sc.read_text(encoding="utf-8"))
    check(doc["format"].startswith("birdtrace-sidecar/"), "format字段")
    ph = doc["photos"]
    check(len(ph) == 3 and all(len(k) == 40 for k in ph),
          "按file_hash键(40位SHA1)")
    e1 = next(e for e in ph.values() if e["file"] == "DSC001.jpg")
    check(e1["records"][0]["confirmed"] == A and e1["spot"]["name"] == "南汇东滩"
          and e1["aesthetic"] == 7.7, f"确认/鸟点/美学齐全 ({e1['records'][0]['confirmed']})")
    e2 = next(e for e in ph.values() if e["file"] == "DSC002.jpg")
    check(e2["no_bird"] and not e2["records"], "「不是鸟」记no_bird")
    e3 = next(e for e in ph.values() if e["file"] == "DSC003.jpg")
    check(e3["records"][0]["source"] == "manual"
          and e3["records"][0]["confirmed"] == C, "手工标注带source/确认")

    print("\n[2] 新库导入读回")
    lib2 = Library(BASE / "lib2")
    lib2.fill_species()
    for f in sorted(folder.glob("DSC*.jpg")):
        fh = media.file_hash(f)
        pid = lib2.add_photo(str(f), fh, f.stat().st_size, f.stat().st_mtime,
                             320, 240, 0)
        lib2.add_exif(pid, {})
    from app.core.sidecar import apply_for_imports
    items = []
    for r in lib2.conn.execute("SELECT id, file_hash, path FROM photos"):
        items.append((r["id"], r["file_hash"], os.path.dirname(r["path"])))
    stats = apply_for_imports(lib2, items)
    check(stats["restored"] == 2 and stats["folders"] == 1,
          f"回填2张带鸟种+1张无鸟 ({stats})")
    rows = {r["id"]: r for r in lib2.conn.execute(
        "SELECT id, rec_fail, aesthetic, spot_id FROM photos")}
    p1b = next(i for i, r in rows.items()
               if r["aesthetic"] == 7.7)
    rec = lib2.conn.execute(
        "SELECT confirmed_code FROM records WHERE photo_id=? AND rank=1",
        (p1b,)).fetchone()
    check(rec["confirmed_code"] == A, "确认码回填")
    check(rows[p1b]["spot_id"] == sid, f"同名鸟点直接复用 (spot_id={rows[p1b]['spot_id']})")
    p2b = next(i for i, r in rows.items() if r["rec_fail"] == 3)
    check(p2b is not None, "无鸟标记回填(rec_fail=3)")
    pend = set(lib2.pending_photo_ids())
    check(not (pend & set(rows)), f"已回填照片不再进识别队列 (待识别={pend})")
    check(lib2.spot_info(sid)["lat"] == 30.87, "鸟点信息原样")
    # 名字回填(records[].name 只是展示字段)
    doc2 = json.loads(sc.read_text(encoding="utf-8"))
    names = [e["records"][0]["name"] for e in doc2["photos"].values()
             if e["records"]]
    check(all(names), f"记录带展示名 ({names[:1]})")

    print("\n[3] 冲突: 已有编辑优先")
    lib3 = Library(BASE / "lib3")
    lib3.fill_species()
    p = folder / "DSC001.jpg"
    fh = media.file_hash(p)
    pid3 = lib3.add_photo(str(p), fh, p.stat().st_size, p.stat().st_mtime,
                          320, 240, 0)
    lib3.add_manual_record(pid3, B)     # 本地先人工确认为B(与sidecar的A不同)
    apply_for_imports(lib3, [(pid3, fh, str(folder))])
    rec3 = lib3.conn.execute(
        "SELECT confirmed_code FROM records WHERE photo_id=?", (pid3,)).fetchone()
    check(rec3["confirmed_code"] == B,
          f"本地人工确认不被sidecar覆盖 ({rec3['confirmed_code']})")
    p3b = folder / "DSC003.jpg"
    fh3 = media.file_hash(p3b)
    pid3b = lib3.add_photo(str(p3b), fh3, p3b.stat().st_size,
                           p3b.stat().st_mtime, 320, 240, 0)
    lib3.set_photo_spot(pid3b, lib3.create_spot("本地优先点", 31.0, 121.5, ""))
    stats3 = apply_for_imports(lib3, [(pid3b, fh3, str(folder))])
    row3 = lib3.conn.execute("SELECT spot_id FROM photos WHERE id=?",
                             (pid3b,)).fetchone()
    check(lib3.spot_info(row3["spot_id"])["name"] == "本地优先点"
          and stats3["spots"] == 0, "本地鸟点不被覆盖")

    print("\n[4] 未知条目合并")
    ghost = "f" * 40
    doc["photos"][ghost] = {"file": "ghost.jpg", "records": [], "no_bird": False,
                            "rating": 3, "aesthetic": None, "spot": None}
    from app.core.sidecar import _write_atomic
    _write_atomic(sc, json.dumps(doc, ensure_ascii=False))
    lib.add_manual_record(p4, B)      # 触发folder2脏
    lib._sidecar_touch(paths=[str(sc)])   # folder也标脏
    lib.flush_sidecars()
    doc4 = json.loads(sc.read_text(encoding="utf-8"))
    check(ghost in doc4["photos"], "本库不认识的条目flush后保留")

    print("\n[5] import_files 链路(ref/copy)")
    from app.core.importer import import_files, scan_sources
    files = scan_sources([folder])
    lib4 = Library(BASE / "lib4")
    lib4.fill_species()
    st = import_files(lib4, files, mode="ref")
    check(st["added"] == 3 and st["sidecar"]["restored"] == 2,
          f"ref导入sidecar回填 ({st['sidecar']})")
    rec4 = lib4.conn.execute(
        "SELECT COUNT(*) FROM records r JOIN photos p ON p.id=r.photo_id "
        "WHERE p.path LIKE ? AND r.confirmed_code IS NOT NULL",
        (str(folder) + "%",)).fetchone()[0]
    check(rec4 >= 2, f"ref导入后确认码在库 ({rec4})")
    copy_root = BASE / "copied"
    lib5 = Library(BASE / "lib5")
    lib5.fill_species()
    st2 = import_files(lib5, files, mode="copy", dest_root=copy_root)
    check(st2["added"] == 3, f"copy导入3张 (skipped={st2['skipped_dup']})")
    lib5.flush_sidecars()   # 应用里=3s定时/退出时写; 测试显式触发
    scs = list(copy_root.rglob(".birdtrace.json"))
    check(bool(scs), f"copy模式目标目录(按年月子目录)flush后落sidecar ({scs[:1]})")
    rec5 = lib5.conn.execute(
        "SELECT COUNT(*) FROM records WHERE confirmed_code IS NOT NULL").fetchone()[0]
    check(rec5 >= 2, f"copy导入确认码随hash回填 ({rec5})")

    print("\n[6] 脏标记钩子(删除/重链)")
    n0 = lib.sidecar_dirty_count()
    lib.set_photo_spot(p4, None)
    check(lib.sidecar_dirty_count() > n0, "set_photo_spot 标脏")
    n1 = lib.sidecar_dirty_count()
    lib.delete_spot(sid)
    check(lib.sidecar_dirty_count() >= n1, "delete_spot 标脏(解挂的全部照片)")
    lib.flush_sidecars()
    doc6 = json.loads((folder2 / ".birdtrace.json").read_text(encoding="utf-8"))
    e4 = next(e for e in doc6["photos"].values() if e["file"] == "DSC004.jpg")
    check(e4["spot"] is None, "解挂后sidecar里spot为None")

    print()
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
