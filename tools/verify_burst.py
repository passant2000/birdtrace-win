# -*- coding: utf-8 -*-
"""0.8-③ 连拍分组+封面验证(离线, 合成库)。

  [1] group_bursts 纯函数: 链式≤2s/同鸟种/哈希相近; 漂移连成一组; 异种/异构/超时拆开
  [2] Library.regroup_bursts: 落库 group_id, 幂等(第二次 changed=0), 版本门
  [3] collapse_bursts: 封面=美学最高, group_n/group_ids(时间序), 位置保持
  [4] 时间线: 折叠开→封面数+×N角标; 关→全部; 多选自动展开; 点封面→组内浏览
  [5] 鸟种页详情: 折叠+★最美仍可见
  [6] BurstWorker 同步跑通

用法: .venv/Scripts/python.exe tools/verify_burst.py
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


def make_img(path: Path, kind: str, shift: int = 0):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (320, 240), (40, 60, 90))
    d = ImageDraw.Draw(im)
    if kind == "bird":        # 条纹底+一只"鸟"(椭圆)微移=连拍帧
        for x in range(0, 320, 40):
            d.rectangle([x, 0, x + 19, 239], fill=(200, 200, 200))
        d.ellipse([100 + shift, 80, 200 + shift, 160], fill=(240, 180, 60))
    elif kind == "checker":   # 完全不同构图
        for y in range(0, 240, 24):
            for x in range(0, 320, 24):
                c = 250 if (x // 24 + y // 24) % 2 else 20
                d.rectangle([x, y, x + 23, y + 23], fill=(c, c, c))
    im.save(path, "JPEG")


def settle(ms: int = 250):
    """跑一段事件循环: 让 deleteLater 的旧网格真正回收(processEvents 不处理
    DeferredDelete, 否则 findChildren 会数到上次刷新的僵尸控件)。"""
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme, i18n
    theme.apply_theme(app, "light")
    i18n.set_lang("zh")

    print("\n[1] group_bursts 纯函数")
    from app.core.burst import group_bursts, collapse_bursts
    H = {1: "0" * 16, 2: "0" * 15 + "f", 3: "0" * 14 + "ff", 4: "0" * 13 + "fff",
         5: "f" * 16, 6: "0" * 16, 7: "0" * 16, 8: "0" * 16, 9: "0" * 16}
    rows = [
        {"id": 1, "taken_at": "2026-05-01 08:00:00", "code": "A"},
        {"id": 2, "taken_at": "2026-05-01 08:00:01", "code": "A"},   # 漂移4
        {"id": 3, "taken_at": "2026-05-01 08:00:03", "code": "A"},   # 再漂移4
        {"id": 4, "taken_at": "2026-05-01 08:00:05", "code": "A"},   # 首尾距12>10仍同组
        {"id": 5, "taken_at": "2026-05-01 08:00:06", "code": "A"},   # 哈希全反→拆
        {"id": 6, "taken_at": "2026-05-01 08:00:06", "code": "B"},   # 异种
        {"id": 7, "taken_at": "2026-05-01 08:00:20", "code": "A"},   # 超时
        {"id": 8, "taken_at": "2026-05-01 08:00:21", "code": None},  # 未识别
        {"id": 9, "taken_at": None, "code": "A"},                    # 无时间
    ]
    g = group_bursts(rows, lambda pid: H.get(pid))
    check(g == {1: "g1", 2: "g1", 3: "g1", 4: "g1"},
          f"链式漂移连成一组, 异构/异种/超时/未识别/无时间不入组 ({g})")
    # 缺哈希: 只按时间+鸟种
    g2 = group_bursts(rows[:2], lambda pid: None)
    check(g2 == {1: "g1", 2: "g1"}, "任一帧无哈希→按时间+鸟种成组")
    # 交错异种(同秒拍到另一只鸟)不拆散连拍链
    g4 = group_bursts([
        {"id": 1, "taken_at": "2026-05-01 08:00:00", "code": "A"},
        {"id": 2, "taken_at": "2026-05-01 08:00:01", "code": "B"},
        {"id": 3, "taken_at": "2026-05-01 08:00:02", "code": "A"},
        {"id": 4, "taken_at": "2026-05-01 08:00:02", "code": "B"},
    ], lambda pid: None)
    check(g4 == {1: "g1", 3: "g1", 2: "g2", 4: "g2"},
          f"异种交错各自成组 ({g4})")
    # EXIF冒号日期格式
    g3 = group_bursts([{"id": 1, "taken_at": "2026:05:01 08:00:00", "code": "A"},
                       {"id": 2, "taken_at": "2026:05:01 08:00:02", "code": "A"}],
                      lambda pid: None)
    check(g3 == {1: "g1", 2: "g1"}, "EXIF 'YYYY:MM:DD' 时间可解析")

    print("\n[3] collapse_bursts")
    lst = [{"id": 10, "group_id": "g10", "aesthetic": 5.0, "taken_at": "2026-05-01 08:00:02"},
           {"id": 11, "group_id": None, "aesthetic": 9.0, "taken_at": "2026-05-01 08:00:01"},
           {"id": 12, "group_id": "g10", "aesthetic": 7.5, "taken_at": "2026-05-01 08:00:01"},
           {"id": 13, "group_id": "g10", "aesthetic": None, "taken_at": "2026-05-01 08:00:00"}]
    c = collapse_bursts(lst)
    check([r["id"] for r in c] == [12, 11], f"封面=组内美学最高(12), 放在组首次出现位置 ({[r['id'] for r in c]})")
    check(c[0]["group_n"] == 3 and c[0]["group_ids"] == [13, 12, 10],
          f"group_n=3, group_ids按时间升序 ({c[0].get('group_ids')})")
    check("group_n" not in c[1], "单张不带group_n")
    c2 = collapse_bursts([dict(r, photo_id=r["id"]) for r in lst], id_key="photo_id")
    check(c2[0]["group_ids"] == [13, 12, 10], "id_key=photo_id 变体")

    print("\n[2] Library.regroup_bursts 落库")
    LIB = PROJ / "data/burst_check"
    if LIB.exists():
        shutil.rmtree(LIB)
    LIB.mkdir(parents=True)
    from app.db import Library
    import app.media as media
    lib = Library(LIB)
    lib.fill_species()
    codes = [r["code"] for r in lib.conn.execute(
        "SELECT code FROM species LIMIT 2").fetchall()]
    A, B = codes

    def add(name, kind, shift, ts, code, aest):
        p = LIB / f"{name}.jpg"
        make_img(p, kind, shift)
        pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                            p.stat().st_mtime, 320, 240, 0)
        lib.conn.execute("INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
                         (pid, ts))
        if code:
            lib.add_records(pid, [{"species_code": code, "confidence": 0.9}])
        if aest is not None:
            lib.set_aesthetic(pid, aest)
        lib.conn.commit()
        return pid

    f1 = add("f1", "bird", 0, "2026-05-01 08:00:00", A, 6.0)
    f2 = add("f2", "bird", 3, "2026-05-01 08:00:00", A, 6.5)
    f3 = add("f3", "bird", 6, "2026-05-01 08:00:01", A, 8.8)   # 封面
    f4 = add("f4", "bird", 9, "2026-05-01 08:00:03", A, 7.0)
    f5 = add("f5", "bird", 12, "2026-05-01 08:00:04", A, 5.5)
    s1 = add("s1", "bird", 0, "2026-05-01 08:00:12", A, 7.7)   # 超时单张
    b1 = add("b1", "bird", 0, "2026-05-01 08:00:01", B, 9.5)   # 异种单张
    d1 = add("d1", "bird", 0, "2026-05-01 09:00:00", A, 6.0)
    d2 = add("d2", "checker", 0, "2026-05-01 09:00:01", A, 6.1)  # 异构→拆
    res = lib.regroup_bursts()
    gid = {r["id"]: r["group_id"] for r in lib.conn.execute(
        "SELECT id, group_id FROM photos")}
    check(res["groups"] == 1 and res["photos"] == 5,
          f"1组5张 ({res})")
    check(all(gid[x] == f"g{f1}" for x in (f1, f2, f3, f4, f5))
          and all(gid[x] is None for x in (s1, b1, d1, d2)),
          f"group_id落库正确 ({gid})")
    res2 = lib.regroup_bursts()
    check(res2["changed"] == 0, "第二次重算 changed=0(幂等)")
    check(not lib.bursts_stale(), "版本门已写")
    check(lib.group_members(f"g{f1}") == [f1, f2, f3, f4, f5],
          "group_members 按时间升序")
    ph = lib.conn.execute("SELECT COUNT(*) FROM photos WHERE phash IS NOT NULL").fetchone()[0]
    check(ph >= 6, f"phash已缓存落库 ({ph}张)")

    print("\n[4] 时间线折叠")
    from app.ui.timeline_page import TimelinePage
    from app.theme.widgets import PhotoGridItem
    page = TimelinePage(lib, None)
    page.resize(1300, 800)
    page.show()
    page.refresh(force=True)
    settle()
    items = page.content.findChildren(PhotoGridItem)
    check(len(items) == 5, f"折叠后5个网格项(1封面+4单张) (实际{len(items)})")
    cover = [it for it in items if it.stack == 5]
    check(len(cover) == 1, "封面带 ×5 角标")
    check(f3 in page._grid_items and page._grid_items[f3].stack == 5,
          "封面=f3(组内美学最高)")
    check("9 张" in page.title.title_label.text(), f"标题仍是真实张数 ({page.title.title_label.text()})")
    opened = {}
    page._open = lambda pid, ids: opened.update(pid=pid, ids=list(ids))
    page._on_item_click(f3, page._grid_items[f3], [f1, f2, f3, f4, f5])
    check(opened.get("ids") == [f1, f2, f3, f4, f5], "点封面→组内浏览")
    page._on_item_click(s1, page._grid_items[s1], None)
    check(len(opened.get("ids", [])) == 9, "点单张→全库浏览")
    page._toggle_select()
    settle()
    check(len(page.content.findChildren(PhotoGridItem)) == 9, "多选模式自动展开全部")
    page._toggle_select()
    settle()
    page.burst_btn.setChecked(False)
    settle()
    check(len(page.content.findChildren(PhotoGridItem)) == 9
          and lib.get_setting("burst_collapse") == "0", "关闭折叠→全部显示+设置持久化")
    page.burst_btn.setChecked(True)
    settle()
    check(len(page.content.findChildren(PhotoGridItem)) == 5, "重新打开折叠")
    page.close()

    print("\n[5] 鸟种页详情折叠")
    from app.ui.main_window import MainWindow
    win = MainWindow(lib, PROJ / "assets")
    win.show()
    app.processEvents()
    sp = win.pages["species"]
    sp._open_detail(A)
    settle(400)
    sp_items = sp.content.findChildren(PhotoGridItem)
    stacks = [it.stack for it in sp_items]
    check(len(sp_items) == 4 and 5 in stacks,
          f"A种: 封面+3单张=4项, 封面×5 ({len(sp_items)}, {stacks})")
    check(any(it.corner == "★最美" and it.stack == 5 for it in sp_items),
          "★最美=封面f3(组内最高8.8>其余)")

    print("\n[6] BurstWorker")
    from app.core.aesthetic_worker import BurstWorker
    got = []
    w = BurstWorker(lib)
    w.finished_all.connect(lambda r: got.append(r))
    w.run()
    check(got and "groups" in got[0] and got[0]["groups"] == 1, f"worker同步跑通 ({got})")
    win.close()

    print("\n[7] unify_burst_species 连拍组鸟种统一")
    # 场景1: EXIF链1s两帧, 高置信A + 低置信异种B → B帧统一成A
    u1 = add("u1", "bird", 1, "2026-06-01 10:00:00", A, 6.0)
    lib.conn.execute(
        "UPDATE records SET confidence=0.92 WHERE photo_id=? AND rank=1", (u1,))
    u2 = add("u2", "bird", 2, "2026-06-01 10:00:01", B, 6.0)
    lib.conn.execute(
        "UPDATE records SET confidence=0.30 WHERE photo_id=? AND rank=1", (u2,))
    lib.conn.commit()
    r = lib.unify_burst_species()
    rec2 = lib.conn.execute(
        "SELECT species_code, confidence, source FROM records "
        "WHERE photo_id=? AND rank=1", (u2,)).fetchone()
    check(rec2["species_code"] == A and abs(rec2["confidence"] - 0.92) < 1e-9
          and rec2["source"] == "burst",
          f"低置信帧统一成胜出帧 ({dict(rec2)})")
    # 场景2: 人工确认帧绝不改写
    u3 = add("u3", "bird", 3, "2026-06-01 10:00:02", B, 6.0)
    lib.conn.execute(
        "UPDATE records SET confidence=0.95, reviewed=1 WHERE photo_id=? AND rank=1",
        (u3,))   # 假装人工确认(B, 高置信)——若被采纳为胜出帧应改u2, 但reviewed不参与
    lib.conn.commit()
    lib.unify_burst_species()
    rec2b = lib.conn.execute(
        "SELECT species_code FROM records WHERE photo_id=? AND rank=1",
        (u2,)).fetchone()
    rec3 = lib.conn.execute(
        "SELECT species_code, reviewed FROM records WHERE photo_id=? AND rank=1",
        (u3,)).fetchone()
    check(rec3["species_code"] == B and rec3["reviewed"] == 1,
          f"人工确认帧不被改写 ({dict(rec3)})")
    # 场景3: 全组低于0.5 → 不动
    u4 = add("u4", "bird", 4, "2026-07-01 11:00:00", A, 6.0)
    u5 = add("u5", "bird", 5, "2026-07-01 11:00:01", B, 6.0)
    lib.conn.execute(
        "UPDATE records SET confidence=0.30 WHERE photo_id=?", (u4,))
    lib.conn.execute(
        "UPDATE records SET confidence=0.40 WHERE photo_id=?", (u5,))
    lib.conn.commit()
    lib.unify_burst_species()
    got4 = lib.conn.execute(
        "SELECT species_code FROM records WHERE photo_id=? AND rank=1",
        (u4,)).fetchone()["species_code"]
    check(got4 == A, f"组内无≥0.5帧整组不动 ({got4}=={A})")
    # 场景4(0.8.0-test2复查修复): 无EXIF照片不参与统一——
    # added_at全在同一秒, 纯时间链曾把整批不相干照片并组改写鸟种
    n1 = add("n1", "bird", 6, None, B, 6.0)
    n2 = add("n2", "checker", 7, None, A, 6.0)
    lib.conn.execute("DELETE FROM exif WHERE photo_id IN (?,?)", (n1, n2))
    lib.conn.execute(
        "UPDATE records SET confidence=0.95 WHERE photo_id=?", (n2,))
    lib.conn.execute("UPDATE records SET confidence=0.30 WHERE photo_id=?", (n1,))
    lib.conn.commit()
    lib.unify_burst_species()
    recn = lib.conn.execute(
        "SELECT species_code, source FROM records WHERE photo_id=? AND rank=1",
        (n1,)).fetchone()
    check(recn["species_code"] == B and recn["source"] != "burst",
          f"无EXIF照片绝不被并组改写 ({dict(recn)})")

    print()
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
