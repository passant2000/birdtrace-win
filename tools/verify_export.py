# -*- coding: utf-8 -*-
"""0.8-④ 导出向导验证(离线, 合成库)。

  [1] select_range: 日期/鸟种/鸟点/评分 过滤
  [2] 复制模式: 层级/原名/日期_鸟种_序号(按日期重启); RAW+JPG成对同号;
      重名安全编号绝不覆盖(同计划内+盘上已存在)
  [3] 原地重命名: 文件改名+库path同步(hash定位)+成对改名+换名两段式+失败不动库
  [4] 原图离线跳过; sidecar按hash键改名不受影响
  [5] ExportDialog UI: 计数/模式切换/无op禁用/复制执行落盘

用法: .venv/Scripts/python.exe tools/verify_export.py
"""
from __future__ import annotations

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
    im = Image.new("RGB", (320, 240), (60, 100 + seed * 13 % 120, 140))
    d = ImageDraw.Draw(im)
    d.ellipse([80, 60, 240, 200], fill=(230, 200, 120))
    d.text((10, 10), str(seed), fill=(255, 255, 255))
    im.save(path, "JPEG")


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme, i18n
    theme.apply_theme(app, "light")
    i18n.set_lang("zh")
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

    BASE = PROJ / "data/export_check"
    if BASE.exists():
        shutil.rmtree(BASE)
    src = BASE / "src"
    src.mkdir(parents=True)
    from app.db import Library
    import app.media as media
    lib = Library(BASE / "lib")
    lib.fill_species()
    codes = [r["code"] for r in lib.conn.execute(
        "SELECT code FROM species LIMIT 2").fetchall()]
    A, B = codes
    cn_a = lib.species_info(A)["cn"]
    cn_b = lib.species_info(B)["cn"]

    def add(name: str, seed: int, code: str, ts: str, spot=None) -> int:
        p = src / name
        make_img(p, seed)
        fh = media.file_hash(p)
        pid = lib.add_photo(str(p), fh, p.stat().st_size, p.stat().st_mtime,
                            320, 240, 0)
        lib.conn.execute("INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
                         (pid, ts))
        lib.add_records(pid, [{"species_code": code, "confidence": 0.9}])
        if spot:
            lib.set_photo_spot(pid, spot)
        lib.conn.commit()
        return pid

    from app.core import exporter
    print("\n[1] select_range")
    sid = lib.create_spot("测试点", 31.0, 121.5, "")
    add("a1.jpg", 1, A, "2026-04-01 08:00:00")
    add("a2.jpg", 2, A, "2026-05-01 08:00:00", spot=sid)
    add("a3.jpg", 3, A, "2026-05-02 08:00:00")
    add("b1.jpg", 4, B, "2026-05-03 08:00:00")
    add("b2.jpg", 5, B, "2026-06-01 08:00:00")
    lib.conn.execute("UPDATE photos SET rating=1 WHERE path LIKE '%b2.jpg'")
    lib.conn.commit()
    check(len(exporter.select_range(lib)) == 5, "全部=5")
    check(len(exporter.select_range(lib, "2026-05-01", "2026-05-31")) == 3,
          "5月=3")
    check(len(exporter.select_range(lib, code=B)) == 2, "B种=2")
    check(len(exporter.select_range(lib, spot_id=sid)) == 1, "鸟点=1")
    check(len(exporter.select_range(lib, rated_only=True)) == 1, "评分=1")
    rows = exporter.select_range(lib, code=A)
    check(rows[0]["taken_at"] < rows[-1]["taken_at"], "按时间升序")

    print("\n[2] 复制模式")
    plan = exporter.plan_ops(rows, BASE / "out1", hierarchy="time_species",
                             naming="date_name")
    names = sorted(Path(o["dst"]).name for o in plan["ops"])
    check(names == [f"2026-04-01_{cn_a}_0001.jpg", f"2026-05-01_{cn_a}_0001.jpg",
                    f"2026-05-02_{cn_a}_0001.jpg"],
          f"日期_中文鸟种_序号(按日期重启) ({names})")
    check(all(Path(o["dst"]).parent in
              (BASE / "out1" / "2026" / "4月" / cn_a,
               BASE / "out1" / "2026" / "5月" / cn_a) for o in plan["ops"]),
          "层级=年/月/鸟种")
    res = exporter.execute_plan(plan["ops"], action="copy")
    check(not res["failed"] and len(res["done"]) == 3, "复制执行成功")
    check(all(Path(o["dst"]).exists() and Path(o["src"]).exists()
              for o in res["done"]), "文件落盘且原图未动")
    plan2 = exporter.plan_ops(rows, BASE / "out2", hierarchy="species_time",
                              naming="original")
    check(all(Path(o["dst"]).parent == BASE / "out2" / cn_a / "2026-04"
              or Path(o["dst"]).parent == BASE / "out2" / cn_a / "2026-05"
              for o in plan2["ops"]), "鸟种→年月")
    check(all(Path(o["dst"]).name == Path(o["src"]).name
              for o in plan2["ops"]), "原名保留")
    plan3 = exporter.plan_ops(rows, BASE / "out3", hierarchy="flat",
                              naming="original")
    check(all(Path(o["dst"]).parent == BASE / "out3" for o in plan3["ops"]),
          "平铺")
    # 成对: RAW+JPG 同号
    make_img(src / "p.jpg", 9)
    (src / "p.ARW").write_bytes(b"rawdata")
    add("p.jpg", 9, B, "2026-05-05 08:00:00")
    rows_p = exporter.select_range(lib, code=B)
    plan4 = exporter.plan_ops(rows_p, BASE / "out4", hierarchy="flat",
                              naming="date_name")
    stems = {Path(o["dst"]).stem for o in plan4["ops"]}
    raw = [o for o in plan4["ops"] if Path(o["dst"]).suffix == ".arw"]
    check(len(plan4["ops"]) == 4 and len(raw) == 1
          and Path(raw[0]["dst"]).stem.startswith("2026-05-05")
          and stems == {f"2026-05-03_{cn_b}_0001", f"2026-05-05_{cn_b}_0001",
                        f"2026-06-01_{cn_b}_0001"},
          f"RAW+JPG成对同号 (ops={len(plan4['ops'])}, stems={stems})")
    res4 = exporter.execute_plan(plan4["ops"], action="copy")
    check(not res4["failed"] and (BASE / "out4" /
                                  f"2026-05-05_{cn_b}_0001.arw").exists()
          and (BASE / "out4" / f"2026-05-05_{cn_b}_0001.jpg").exists(),
          "RAW副本落盘且与JPG同stem")
    # 重名安全: 先按原名复制一份, 再复制第二份→自动编号(1), 绝不覆盖
    plan5 = exporter.plan_ops(rows_p, BASE / "out4", hierarchy="flat",
                              naming="original")
    res5 = exporter.execute_plan(plan5["ops"], action="copy")
    check(not res5["failed"] and len(res5["done"]) == len(plan5["ops"])
          and (BASE / "out4" / "p.jpg").exists(), "第一份原名复制")
    plan5b = exporter.plan_ops(rows_p, BASE / "out4", hierarchy="flat",
                               naming="original")
    res5b = exporter.execute_plan(plan5b["ops"], action="copy")
    outs = {p.name.lower() for p in (BASE / "out4").glob("p*")}
    check(not res5b["failed"] and "p.jpg" in outs
          and "p (1).jpg" in outs and "p (1).arw" in outs
          and len(res5b["done"]) == len(plan5b["ops"]),
          f"重名安全编号不覆盖 ({sorted(outs)})")

    print("\n[3] 原地重命名")
    lib2 = Library(BASE / "lib2")
    lib2.fill_species()
    src2 = BASE / "src2"
    src2.mkdir()
    make_img(src2 / "DSC001.jpg", 21)
    make_img(src2 / "DSC002.jpg", 22)
    (src2 / "DSC002.ARW").write_bytes(b"raw")
    make_img(src2 / "DSC003.jpg", 23)

    def add2(name, seed, code, ts):
        p = src2 / name
        fh = media.file_hash(p)
        pid = lib2.add_photo(str(p), fh, p.stat().st_size, p.stat().st_mtime,
                             320, 240, 0)
        lib2.conn.execute(
            "INSERT INTO exif(photo_id, dt_original) VALUES(?,?)", (pid, ts))
        lib2.add_records(pid, [{"species_code": code, "confidence": 0.9}])
        lib2.conn.commit()
        return pid

    q1 = add2("DSC001.jpg", 21, A, "2026-05-01 08:00:00")
    q2 = add2("DSC002.jpg", 22, B, "2026-05-01 08:01:00")
    q3 = add2("DSC003.jpg", 23, A, "2026-05-02 08:00:00")
    rec_id = lib2.conn.execute("SELECT id FROM records WHERE photo_id=?",
                               (q1,)).fetchone()["id"]
    lib2.set_confirmed(rec_id, A)
    rows2 = exporter.select_range(lib2)
    plan6 = exporter.plan_ops(rows2, None, naming="date_name")
    check(len(plan6["ops"]) == 4, f"3照片+1成对RAW=4op ({len(plan6['ops'])})")
    check(all(Path(o["dst"]).parent == src2 for o in plan6["ops"]),
          "原地=不动目录")
    res6 = exporter.execute_plan(plan6["ops"], action="rename")
    check(not res6["failed"], f"重命名执行无失败 ({res6['failed'][:1]})")
    n = exporter.apply_rename_to_db(lib2, res6["done"])
    check(n == 3, f"库path更新3行 ({n})")
    h_q2 = lib2.conn.execute("SELECT file_hash FROM photos WHERE id=?",
                             (q2,)).fetchone()["file_hash"]
    check((src2 / f"2026-05-01_{cn_a}_0001.jpg").exists()
          and (src2 / f"2026-05-01_{cn_b}_0001.jpg").exists()
          and (src2 / f"2026-05-01_{cn_b}_0001.arw").exists()
          and (src2 / f"2026-05-02_{cn_a}_0001.jpg").exists()
          and not (src2 / "DSC001.jpg").exists(),
          "新旧文件名落盘(成对RAW同号)")
    row = lib2.conn.execute("SELECT path, file_hash FROM photos WHERE id=?",
                            (q2,)).fetchone()
    check(Path(row["path"]).name == f"2026-05-01_{cn_b}_0001.jpg"
          and media.file_hash(Path(row["path"])) == row["file_hash"] == h_q2,
          "库path=新名且hash不变(记录/缩略图不受影响)")
    check(lib2.conn.execute(
        "SELECT confirmed_code FROM records WHERE id=?",
        (rec_id,)).fetchone()["confirmed_code"] == A, "确认记录原封不动")
    # 换名冲突(A→B且B→A): 两段式都成功且内容正确
    y1 = src2 / f"2026-05-01_{cn_a}_0001.jpg"
    y2 = src2 / f"2026-05-01_{cn_b}_0001.jpg"
    h1, h2 = media.file_hash(y1), media.file_hash(y2)
    ops_swap = [{"src": str(y1), "dst": str(y2), "pair": False, "photo_id": None},
                {"src": str(y2), "dst": str(y1), "pair": False, "photo_id": None}]
    res7 = exporter.execute_plan(ops_swap, action="rename")
    check(not res7["failed"] and media.file_hash(y1) == h2
          and media.file_hash(y2) == h1, "换名冲突两段式都成功且不丢内容")
    # 失败不动库: 目标父目录不存在
    keep = lib2.conn.execute("SELECT path FROM photos WHERE id=?",
                             (q1,)).fetchone()["path"]
    bad = [{"src": keep, "dst": str(BASE / "no_such_dir" / "x.jpg"),
            "pair": False, "photo_id": q1}]
    res8 = exporter.execute_plan(bad, action="rename")
    check(bool(res8["failed"]) and res8["done"] == [], "失败op不入done")
    check(exporter.apply_rename_to_db(lib2, res8["done"]) == 0
          and lib2.conn.execute("SELECT path FROM photos WHERE id=?",
                                (q1,)).fetchone()["path"] == keep,
          "失败的行库path不动")

    print("\n[4] 离线跳过 + sidecar 兼容")
    lib3 = Library(BASE / "lib3")
    lib3.fill_species()
    src3 = BASE / "src3"
    src3.mkdir()
    make_img(src3 / "m1.jpg", 31)
    fh3 = media.file_hash(src3 / "m1.jpg")
    m1 = lib3.add_photo(str(src3 / "m1.jpg"), fh3,
                        (src3 / "m1.jpg").stat().st_size,
                        (src3 / "m1.jpg").stat().st_mtime, 320, 240, 0)
    lib3.conn.execute("INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
                      (m1, "2026-05-01 09:00:00"))
    lib3.add_records(m1, [{"species_code": A, "confidence": 0.9}])
    m2 = lib3.add_photo("Z:\\离线\\m2.jpg", "a" * 40, 123, 0.0, 320, 240, 0)
    lib3.conn.execute("INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
                      (m2, "2026-05-01 09:00:01"))
    lib3.add_records(m2, [{"species_code": A, "confidence": 0.9}])
    lib3.conn.commit()
    rows3 = exporter.select_range(lib3)
    plan9 = exporter.plan_ops(rows3, None, naming="date_name")
    check(len(plan9["ops"]) == 1 and len(plan9["skipped_offline"]) == 1,
          f"离线1张跳过 (ops={len(plan9['ops'])})")
    res9 = exporter.execute_plan(plan9["ops"], action="rename")
    exporter.apply_rename_to_db(lib3, res9["done"])
    from app.core.sidecar import read_sidecar
    lib3._sidecar_touch(paths=[str(src3)])
    lib3.flush_sidecars()
    sc = read_sidecar(src3)
    check(len(sc) == 1 and fh3 in sc, "sidecar按hash键(改名后flush正常)")

    print("\n[5] ExportDialog UI")
    from app.ui.export_dialog import ExportDialog
    n_total = len(exporter.select_range(lib))
    dlg = ExportDialog(lib, None)
    dlg.show()
    app.processEvents()
    check(str(n_total) in dlg.range_hint.text(),
          f"范围计数 ({dlg.range_hint.text()})")
    n_ops = len(dlg._plan["ops"])
    check(n_ops == n_total + 1, f"默认计划含成对RAW (实际{n_ops})")
    dlg._on_mode(1)
    check(not dlg.copy_box.isVisibleTo(dlg)
          and "撤销" in dlg.warn_lab.text(), "切原地模式: 目标目录隐藏+警示")
    dlg.name_seg.setCurrent(0)
    app.processEvents()
    dlg._update_preview()
    check(dlg._plan["ops"] == [] and not dlg.go_btn.isEnabled(),
          "原地+原名=无op且禁用执行")
    dlg._on_mode(0)
    dlg.name_seg.setCurrent(1)
    dlg.dir_edit.setText(str(BASE / "out_ui"))
    app.processEvents()
    dlg._run()
    out_files = list((BASE / "out_ui").rglob("*.*"))
    check(len(out_files) == n_total + 1,
          f"UI执行落盘{n_total + 1}个文件 (实际{len(out_files)})")
    dlg.close()

    print()
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
