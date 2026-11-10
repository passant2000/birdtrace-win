# -*- coding: utf-8 -*-
"""0.8-⑥ 批量分享卡验证: best_share_cards 选取口径 + BatchShareDialog 导出。

口径(用户定):
  "最美" = 美学分×置信度最高, 每鸟种一张;
  只取 已确认(confirmed_code非空, 含手工) 或 原始置信≥0.5 的rank=1记录;
  待复核(0.2~0.5未确认)与未评分照片不印进卡。

用法: .venv/Scripts/python.exe tools/verify_batch_share.py (离线, 合成图)
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


def make_img(path: Path):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (320, 240), (90, 120, 160))
    d = ImageDraw.Draw(im)
    d.ellipse([80, 60, 240, 200], fill=(230, 200, 120))
    im.save(path, "JPEG")


def add_photo(lib, d: Path, name: str, code: str, conf: float,
              aest: float | None, confirmed: bool = False) -> int:
    p = d / f"{name}.jpg"
    make_img(p)
    import app.media as media
    pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                        p.stat().st_mtime, 320, 240, 0)
    lib.add_records(pid, [{"species_code": code, "confidence": conf}])
    if aest is not None:
        lib.set_aesthetic(pid, aest)
    if confirmed:
        rid = lib.conn.execute(
            "SELECT id FROM records WHERE photo_id=?", (pid,)).fetchone()["id"]
        lib.set_confirmed(rid, code)
    return pid


def main():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    QMessageBox.information = staticmethod(lambda *a, **k: None)  # 不弹框

    LIB_DIR = PROJ / "data/batch_share_check"
    OUT_DIR = PROJ / "data/batch_share_out"
    for d in (LIB_DIR, OUT_DIR):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)

    from app.db import Library
    lib = Library(LIB_DIR)
    lib.fill_species()
    codes = [r["code"] for r in lib.conn.execute(
        "SELECT code FROM species LIMIT 5").fetchall()]
    a, b, c, e, d5 = codes

    print("\n[1] best_share_cards 选取口径")
    # A: 已确认低分(conf0.35<0.5, 靠确认资格入选) vs 未确认高分(0.9资格)
    #    → 都有资格, 取组合分最高的未确认那张
    pa1 = add_photo(lib, LIB_DIR, "A_unconf", a, 0.9, 0.95)
    pa2 = add_photo(lib, LIB_DIR, "A_conf", a, 0.35, 0.80, confirmed=True)
    # B: 未确认但置信0.6(≥0.5) → 入选
    pb = add_photo(lib, LIB_DIR, "B_raw", b, 0.6, 0.70)
    # C: 待复核(0.3未确认) → 不出卡
    pc = add_photo(lib, LIB_DIR, "C_review", c, 0.3, 0.99)
    # D: 置信0.4<0.5但已确认 → 入选(确认资格单独成证)
    pd = add_photo(lib, LIB_DIR, "D_conf", d5, 0.4, 0.85, confirmed=True)
    # E: 无美学分 → 不出卡
    pe = add_photo(lib, LIB_DIR, "E_noaest", e, 0.9, None)

    got = lib.best_share_cards("2000-01-01", "2099-12-31")
    picked = {g["eff_code"]: g["photo_id"] for g in got}
    check(set(picked) == {a, b, d5},
          f"A/B/D入选, C待复核与E无评分被排除 (实际{sorted(picked)})")
    check(picked.get(a) == pa1, "A取组合分最高的那张(资格与选取分离)")
    check(by_code := {g["eff_code"]: g for g in got}, "非空")
    check(by_code[a]["en_name"] is not None and by_code[a]["cn"],
          "行带中英文名")
    check(by_code[a]["path"] and by_code[b]["taken_at"],
          "行带path/taken_at(渲染需要)")

    print("\n[2] BatchShareDialog 构造+计数+导出全流程")
    from app.ui.batch_share_dialog import BatchShareDialog, _safe_name
    from app.i18n import sname
    dlg = BatchShareDialog(lib, None)
    dlg.show()
    app.processEvents()
    dlg.from_date.setDate(dlg.from_date.date().addDays(-7))
    app.processEvents()
    check(str(len(got)) in dlg.count_hint.text(),
          f"计数提示含 {len(got)} («{dlg.count_hint.text()}»)")
    # 鸟种过滤
    dlg.species_combo.setProperty("code", a)
    info_a = lib.species_info(a)
    dlg.species_combo.setText(sname(info_a["cn"], info_a["en"]))
    dlg._update_count()
    check(dlg.count_hint.text().startswith("共 1 "),
          f"按鸟种过滤后计数=1 («{dlg.count_hint.text()}»)")
    dlg.species_combo.setProperty("code", None)
    dlg.species_combo.setText("")
    dlg._update_count()

    # 快捷范围+年份下拉(2026-11-04: 年份转轮难调)
    # 注: SegmentedControl.setCurrent不发changed(真实点击才发), 测试直调处理器
    dlg._apply_quick(3)             # 今年
    d1, d2 = dlg.from_date.date(), dlg.to_date.date()
    check(d1 == d1.addDays(-d1.day() + 1) and d2 == QDate.currentDate(),
          f"快捷'今年'→1月1日~今天 ({d1.toString('yyyy-MM-dd')}~"
          f"{d2.toString('yyyy-MM-dd')})")
    # 日期弹层(2026-11-05用户: 年份/月份都应一点直达; 原日期旁的
    # "年份…"下拉重复且看着没功能→已删)
    check(not hasattr(dlg, "to_year") and not hasattr(dlg, "from_year"),
          "多余年份下拉已移除")
    from app.theme.widgets import ThemedDateEdit, _DatePopup
    from PySide6.QtWidgets import QDateEdit
    check(isinstance(dlg.to_date, ThemedDateEdit)
          and not isinstance(dlg.to_date, QDateEdit)
          and not dlg.to_date.calendarPopup(),
          "日期控件=自绘ThemedDateEdit(非QDateEdit, 无原生弹层)")
    # 回归(2026-11-06用户实测日期框全空白): QSS里一旦出现QDateEdit选择器,
    # Qt会把内部输入框宽度压成1px→日期不可见。改成自绘按钮后断言文字非空。
    app.processEvents()
    check(dlg.from_date.text() == dlg.from_date.date().toString("yyyy-MM-dd")
          and dlg.to_date.text() == dlg.to_date.date().toString("yyyy-MM-dd")
          and dlg.from_date.text() and dlg.from_date.width() > 50,
          f"日期文字可见({dlg.from_date.text()}/{dlg.to_date.text()}, "
          f"宽{dlg.from_date.width()})")
    pop = _DatePopup(dlg.to_date.date(), dlg.to_date)
    check(pop.year_combo.count() > 50
          and pop.year_combo.findData(2019) >= 0,
          f"年份下拉覆盖多年({pop.year_combo.count()}项, 含2019)")
    check(pop.month_combo.count() == 12, "月份下拉12项")
    check(not pop.cal.isNavigationBarVisible(),
          "日网格不带原生导航栏(年份月份由下拉控制)")
    pop.year_combo.setCurrentIndex(pop.year_combo.findData(2019))
    pop.month_combo.setCurrentIndex(d2.month() - 1)
    check(pop.cal.yearShown() == 2019
          and pop.cal.monthShown() == d2.month(),
          f"年份+月份下拉联动日历页 ({pop.cal.yearShown()}-{pop.cal.monthShown()})")
    pop.date_selected.connect(dlg.to_date._on_picked)
    pop._pick(QDate(2019, d2.month(), d2.day()))
    check(dlg.to_date.date().year() == 2019
          and dlg.to_date.date().month() == d2.month()
          and dlg.to_date.date().day() == d2.day(),
          f"选日→只换日期回填 ({dlg.to_date.date().toString('yyyy-MM-dd')})")
    dlg._apply_quick(0)             # 今天
    check(dlg.from_date.date() == dlg.to_date.date() == QDate.currentDate(),
        "快捷'今天'→从=到=今天")
    dlg.dir_edit.setText(str(OUT_DIR))
    dlg.name_edit.setText("测试者")
    dlg._export()
    files = sorted(OUT_DIR.glob("*.png"))
    check(len(files) == 3, f"导出3张PNG (实际{[f.name for f in files]})")
    names = [f.stem for f in files]
    expect = {_safe_name(sname(g["cn"], g["en_name"])) for g in got}
    check({n.split("_", 1)[1] for n in names} == expect,
          f"文件名=日期_鸟种名 ({names})")
    check(all(n[:10].count("-") == 2 for n in names),
          f"文件名带日期前缀 ({names[:1]}…)")
    from PySide6.QtGui import QImage
    for f in files:
        im = QImage(str(f))
        check(not im.isNull() and im.width() == 2000, f"{f.name} 2000宽PNG")
    check(dlg.open_btn.isVisibleTo(dlg), "导出后显示打开文件夹按钮")

    print("\n[3] 文件名安全化")
    check(_safe_name("蓝/喉:蜂虎?") == "蓝_喉_蜂虎", "非法字符清洗")
    check(_safe_name("  ") == "card", "空白回退card")

    print("\n[4] 原图离线跳过并在完成框说明")
    (LIB_DIR / "B_raw.jpg").unlink()   # 模拟移动硬盘拔出
    sub = OUT_DIR / "sub"
    sub.mkdir()
    dlg2 = BatchShareDialog(lib, None)
    dlg2.from_date.setDate(dlg2.from_date.date().addDays(-7))
    dlg2.dir_edit.setText(str(sub))
    dlg2._export()
    got2 = sorted(sub.glob("*.png"))
    info_b = lib.species_info(b)
    b_name = _safe_name(sname(info_b["cn"], info_b["en"]))
    check(len(got2) == 2 and all(b_name not in f.stem for f in got2),
          f"离线B跳过, 导出其余2张 ({[f.name for f in got2]})")

    print()
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
