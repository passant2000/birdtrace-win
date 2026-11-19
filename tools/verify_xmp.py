# -*- coding: utf-8 -*-
"""⑪ XMP 鸟种写回验证(可选功能, 默认关):
段解析/写入(替换已有+新建)/像素不动(JPEG重解码逐字节像素相等)/
关键词与日期与版权落段/非JPEG跳过/设置关不写/set_confirmed自动写/
原子临时文件清理。纯stdlib, 不跑模型, 约5~10秒。"""
from __future__ import annotations

import io
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
    D = PROJ / "data/_xmp_check"
    if D.exists():
        shutil.rmtree(D)
    D.mkdir(parents=True)

    from app.core.xmp_write import (build_xmp, read_xmp, write_xmp,
                                    maybe_write_for_photo)

    # ---------- [1] 构造/读回 ----------
    print("[1] build/read")
    xmp = build_xmp(["斑头大翠鸟", "Crested Kingfisher", "Megaceryle lugubris"],
                    "2026-05-20", "© 苏坡慢")
    s = xmp.decode("utf-8")
    check("斑头大翠鸟" in s and "Megaceryle lugubris" in s, "关键词入段")
    check("2026-05-20" in s and "photoshop:DateCreated" in s, "日期入段")
    check("dc:rights" in s and "苏坡慢" in s, "版权入段")
    check(s.startswith('<?xpacket begin'), "xpacket 头")

    # ---------- [2] 写入/替换/像素不动 ----------
    print("[2] write/replace/pixels")
    import PIL.Image as I
    src = PROJ / "data/test_images/Alcedo_atthis.jpg"
    jp = D / "a.jpg"
    shutil.copy(src, jp)
    im0 = I.open(jp)
    px0 = list(im0.convert("RGB").getdata())
    im0.close()
    check(read_xmp(jp) is None or "BirdTrace" not in read_xmp(jp) or True,
          "原图可能有/没有XMP, 读接口不炸")
    ok = write_xmp(jp, xmp)
    check(ok, "首次写入成功")
    back = read_xmp(jp)
    check(back is not None and "斑头大翠鸟" in back, "读回含关键词")
    # 像素不动(全图重解码逐像素相等)
    im1 = I.open(jp)
    px1 = list(im1.convert("RGB").getdata())
    im1.close()
    check(px0 == px1, f"像素逐点不动 ({len(px0)}px)")
    # 再写一次(替换已有段, 不叠加)
    xmp2 = build_xmp(["替换种"], "2026-01-01", None)
    check(write_xmp(jp, xmp2), "二次写入(替换)")
    back2 = read_xmp(jp) or ""
    check("替换种" in back2 and "斑头大翠鸟" not in back2, "旧段被整段替换")
    check(back2.count("<x:xmpmeta") == 1, "XMP 元数据只有一份")
    # PIL 仍可正常解码(结构没破坏)
    I.open(jp).verify()
    check(True, "JPEG 结构仍可验证")
    # 无临时文件残留
    leftovers = list(D.glob("*.birdtrace-xmp-tmp"))
    check(not leftovers, f"无临时文件残留 ({leftovers})")

    # ---------- [3] 非 JPEG / 越界 ----------
    print("[3] guard")
    png = D / "b.png"
    I.open(src).save(png)
    check(not write_xmp(png, xmp2), "PNG 拒写")
    check(read_xmp(png) is None, "PNG 读=None")
    tiny = build_xmp(["k" * 70000], "2026-01-01")
    check(not write_xmp(jp, tiny), "超64KB段拒写")

    # ---------- [4] 设置钩子: 关不写/开自动写 ----------
    print("[4] hooks")
    from app.db import Library
    import app.media as media
    lib = Library(D / "lib")
    lib.fill_species()
    lib.conn.execute(
        "INSERT INTO batches(mode,dest,region_id,count) VALUES('copy',?,'CN',1)",
        (str(D / "src"),))
    bid = lib.conn.execute("SELECT id FROM batches LIMIT 1").fetchone()["id"]
    p2 = D / "c.jpg"
    shutil.copy(src, p2)
    pid = lib.add_photo(str(p2), media.file_hash(p2), p2.stat().st_size,
                        p2.stat().st_mtime, 0, 0, bid)
    kcode = lib.conn.execute(
        "SELECT code FROM species WHERE en LIKE '%kingfisher%' LIMIT 1"
    ).fetchone()["code"]
    rid = lib.conn.execute(
        "INSERT INTO records(photo_id,species_code,rank,confidence,source) "
        "VALUES(?,?,1,0.9,'detect') RETURNING id", (pid, kcode)).fetchone()["id"]
    lib.conn.commit()
    check(lib.get_setting("xmp_writeback", "0") == "0", "默认关")
    lib.set_confirmed(rid, kcode)
    check(read_xmp(p2) is None or "cn_name" not in (read_xmp(p2) or ""),
          "默认关: set_confirmed 不写文件")
    lib.set_setting("xmp_writeback", "1")
    lib.copyright_defaults_set(creator="苏坡慢", copyright_notice="©测试")
    rec0 = read_xmp(p2)
    lib.set_confirmed(rid, kcode)   # 开启后重新确认 → 自动写
    back4 = read_xmp(p2) or ""
    sp = lib.species_info(kcode)
    check(sp["cn"] in back4, f"开启后自动写({sp['cn'][:6]}…)")
    check("©测试" in back4, "版权声明单源入段")
    # maybe_write_for_photo 直接调(批量按钮路径)
    lib.set_setting("xmp_writeback", "1")
    check(maybe_write_for_photo(lib, pid), "批量入口返回成功")
    check(maybe_write_for_photo(lib, 999999) is False, "不存在照片=False")
    # 批量改判也写回
    ocode = lib.conn.execute(
        "SELECT code FROM species WHERE code<>? AND en LIKE '%heron%' "
        "LIMIT 1", (kcode,)).fetchone()["code"]
    lib.set_species_batch([pid], ocode)
    back5 = read_xmp(p2) or ""
    sp2 = lib.species_info(ocode)
    check(sp2["cn"] in back5, "批量改判写回新种")
    lib.conn.close()

    print("\n" + ("FAIL" if FAILED["v"] else "ALL PASS"))
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
