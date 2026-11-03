# -*- coding: utf-8 -*-
"""0.8-⑦ 年度十八图去重验证(每鸟种一张优先)。

合成图库验证:
  [1] 鸟种≥18: 十八图全为不同鸟种(全局美学Top18)。
  [2] 鸟种<18: 第2张补位——与该种第1张同构图(汉距0)不补; 构图不同且
      高于已选中位数才补; ≤中位数停补。
  [3] 返回按美学降序; 每种≤2张不变。

用法: .venv/Scripts/python.exe tools/verify_best18.py  (离线, 合成图)
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB_DIR = PROJ / "data/best18_check"
FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def make_img(path: Path, kind: str):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (320, 240))
    d = ImageDraw.Draw(im)
    if kind == "stripes":     # 竖条纹(16px)
        for x in range(0, 320, 32):
            d.rectangle([x, 0, x + 15, 239], fill=(220, 220, 220))
    elif kind == "checker":   # 棋盘(行间相位交替, 与条纹汉距大)
        for y in range(0, 240, 20):
            for x in range(0, 320, 20):
                c = 255 if (x // 20 + y // 20) % 2 else 30
                d.rectangle([x, y, x + 19, y + 19], fill=(c, c, c))
    elif kind == "hgrad":     # 水平渐变(dHash近全0, 与条纹汉距≈32)
        for x in range(320):
            d.line([(x, 0), (x, 240)], fill=(x * 255 // 320,) * 3)
    im.save(path, "JPEG")


def main():
    if LIB_DIR.exists():
        shutil.rmtree(LIB_DIR)
    if (PROJ / "data/best18_check2").exists():
        shutil.rmtree(PROJ / "data/best18_check2")
    LIB_DIR.mkdir(parents=True)

    from app.db import Library
    lib = Library(LIB_DIR)
    lib.fill_species()

    def add(code: str, kind: str, aest: float, name: str) -> int:
        p = LIB_DIR / f"{name}.jpg"
        make_img(p, kind)
        import app.media as media
        pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                            p.stat().st_mtime, 320, 240, 0)
        lib.add_records(pid, [{"species_code": code, "confidence": 0.9}])
        lib.set_aesthetic(pid, aest)
        return pid

    # 挑18个真实鸟种码
    codes = [r["code"] for r in lib.conn.execute(
        "SELECT code FROM species LIMIT 25").fetchall()]
    assert len(codes) >= 20

    print("\n[1] 鸟种≥18: 全局美学Top18且各种一张")
    for i, c in enumerate(codes[:20]):
        add(c, "hgrad", 0.50 + (20 - i) * 0.01, f"a{i:02d}")
    best = lib.best_of_year("2026")
    check(len(best) == 18, f"选满18张 (实际{len(best)})")
    check(len({b['eff_code'] for b in best}) == 18, "18张=18个不同鸟种")
    s = [b["aesthetic"] for b in best]
    check(s == sorted(s, reverse=True), "按评分降序")

    print("\n[2] 鸟种<18: 第2张补位条件")
    # 独立库: 4种。每种的美学Top=其"第1张"; 第2张候选按构图/中位数检验。
    lib2 = Library(PROJ / "data/best18_check2")
    lib2.fill_species()
    L2 = PROJ / "data/best18_check2"
    a1 = add_(lib2, L2, codes[0], "stripes", 0.95, "A1")     # 种A的Top
    add_same_content(lib2, L2, a1, codes[0], 0.93, "A2")   # 同构图高分
    b1 = add_(lib2, L2, codes[1], "stripes", 0.88, "B1")     # 种B的Top
    b2 = add_(lib2, L2, codes[1], "checker", 0.86, "B2")     # 异构图
    c1 = add_(lib2, L2, codes[2], "stripes", 0.76, "C1")     # 种C的Top
    add_(lib2, L2, codes[2], "checker", 0.74, "C2")        # 异构图低分
    d1 = add_(lib2, L2, codes[3], "stripes", 0.66, "D1")     # 种D的Top
    add_(lib2, L2, codes[3], "hgrad", 0.50, "D2")          # 异构图更低
    best2 = lib2.best_of_year("2026")
    ids = [b["photo_id"] for b in best2]
    # pass1: A1 .95, B1 .88, C1 .76, D1 .66 (median .82)
    # → A2 .93 同构图跳过 → B2 .86 > .82 且异构图补入
    #   (picked median→.86) → C2 .74 ≤ .86 停
    check(len(best2) == 5, f"补位后共5张 (实际{len(best2)}: {ids})")
    check(all(i in ids for i in (a1, b1, c1, d1)), "各种Top(第1张)全在")
    check(b2 in ids, "B2(异构图0.86>中位0.82)补入")
    check(sum(1 for i in ids
              if lib2.conn.execute(
                  "SELECT eff_code FROM v_records WHERE photo_id=?",
                  (i,)).fetchone()["eff_code"] == codes[0]) == 1,
          "A2同构图高分未补入(去重生效)")
    check(sum(1 for i in ids
              if lib2.conn.execute(
                  "SELECT eff_code FROM v_records WHERE photo_id=?",
                  (i,)).fetchone()["eff_code"] == codes[2]) == 1,
          "C2(0.74≤中位0.86)未补入")
    s2 = [b["aesthetic"] for b in best2]
    check(s2 == sorted(s2, reverse=True), "返回按评分降序")
    per: dict[str, int] = {}
    for b in best2:
        per[b["eff_code"]] = per.get(b["eff_code"], 0) + 1
    check(max(per.values()) <= 2, "每种≤2张")

    print()
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


def add_(lib, libdir: Path, code: str, kind: str, aest: float, name: str) -> int:
    p = libdir / f"{name}.jpg"
    make_img(p, kind)
    import app.media as media
    pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                        p.stat().st_mtime, 320, 240, 0)
    lib.add_records(pid, [{"species_code": code, "confidence": 0.9}])
    lib.set_aesthetic(pid, aest)
    return pid


def add_same_content(lib, libdir: Path, src_pid: int, code: str,
                     aest: float, name: str) -> int:
    """与src同文件内容(拷贝)→同file_hash、同构图(汉距0), 不同path。"""
    src = Path(lib.conn.execute("SELECT path FROM photos WHERE id=?",
                                (src_pid,)).fetchone()["path"])
    p = libdir / f"{name}.jpg"
    shutil.copyfile(src, p)
    import app.media as media
    pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                        p.stat().st_mtime, 320, 240, 0)
    lib.add_records(pid, [{"species_code": code, "confidence": 0.9}])
    lib.set_aesthetic(pid, aest)
    return pid


if __name__ == "__main__":
    main()
