# -*- coding: utf-8 -*-
"""分享卡拍摄参数(EXIF)端到端验证: 勾选显隐/逐项渲染/无参不空行/EN无残留/渲染健壮。

覆盖:
[1] exif.py 解析真实EXIFjpg → 库字段
[2] ShareDialog: 参数行逐项正确/勾选显隐(实时重绘+高度预算)/无EXIF不空行/单字段只显示该字段
[3] EN模式对话框可见文案无中文残留
[4] 渲染健壮性: dark主题/照片丢失占位/超长参数截断

用法: .venv/Scripts/python.exe tools/verify_share_exif.py
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB_DIR = PROJ / "data/share_exif_check"
SRC = PROJ / "data/share_exif_src"
SHOTS = PROJ / "data/ui_shots"
FAILED = {"v": False}
ZH = re.compile(r"[\u4e00-\u9fff]")

CAMERA = ("Canon", "Canon EOS R5")
LENS = "RF100-500mm F4.5-7.1 L IS USM"
EXPECTED_PARTS = {"body": "Canon EOS R5", "lens": LENS,
                  "shot": "500mm · f/6.3 · 1/1600s · ISO 1600"}
BG_LIGHT = (240, 239, 228)      # sharecard light bg #F0EFE4


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def make_jpg(path: Path, size: tuple, color: tuple, with_exif: bool):
    """生成测试jpg; with_exif时写入完整拍摄参数(含子IFD)。"""
    from PIL import Image
    from PIL.ExifTags import IFD
    im = Image.new("RGB", size, color)
    if with_exif:
        exif = im.getexif()
        exif[271], exif[272], exif[315] = CAMERA[0], CAMERA[1], "zhaopaul"
        ifd = exif.get_ifd(IFD.Exif)
        ifd[36867] = "2024:05:12 08:31:00"   # DateTimeOriginal
        ifd[34855] = 1600                     # ISOSpeedRatings
        ifd[33434] = (1, 1600)                # ExposureTime -> 1/1600
        ifd[33437] = (63, 10)                 # FNumber -> 6.3
        ifd[37386] = (500, 1)                 # FocalLength -> 500mm
        ifd[42036] = LENS                     # LensModel
        im.save(path, exif=exif, quality=92)
    else:
        im.save(path, quality=92)


def collect_texts(root) -> list[str]:
    """对话框全部用户可见文案(参照 verify_i18n.collect_texts)。"""
    from PySide6.QtWidgets import (QDialog, QLabel, QLineEdit, QPushButton,
                                   QWidget)
    texts: list[str] = []

    def add(s):
        if s and s.strip():
            texts.append(s.strip())

    for w in [root] + root.findChildren(QWidget):
        try:
            if isinstance(w, QDialog):
                add(w.windowTitle())
            if isinstance(w, QLabel):
                add(w.text())
            elif isinstance(w, QPushButton):
                add(w.text())
            elif isinstance(w, QLineEdit):
                add(w.placeholderText() or "")
        except RuntimeError:
            continue
    return texts


def ink_count(pm, x0: int, y0: int, w: int, h: int,
              bg=BG_LIGHT, tol: int = 14) -> int:
    """统计区域内"非背景且不透明"的像素数(参数文字/线条会显著>0)。"""
    import numpy as np
    from PySide6.QtGui import QImage
    img = pm.toImage().copy(x0, y0, w, h).convertToFormat(QImage.Format_RGBA8888)
    bpl = img.bytesPerLine()
    arr = np.frombuffer(bytes(img.constBits()), dtype=np.uint8)
    arr = arr[:img.height() * bpl].reshape(img.height(), bpl // 4, 4)[:, :w]
    diff = np.abs(arr[..., :3].astype(int) - np.array(bg)).max(axis=2)
    return int(((diff > tol) & (arr[..., 3] > 200)).sum())


def main():
    for d in (LIB_DIR, SRC):
        if d.exists():
            shutil.rmtree(d)
    SRC.mkdir(parents=True)
    SHOTS.mkdir(exist_ok=True)

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme
    theme.apply_theme(app, "light")

    from app import i18n
    from app.core.importer import import_files
    from app.core.sharecard import render_card, TEXT_ZONE_H
    from app.db import Library
    from app.exif import read_exif
    from app.ui.share_dialog import ShareDialog

    # ---- [1] 测试库: 1张完整EXIF + 1张无EXIF ----
    print("\n[1] 测试库与EXIF解析")
    p_exif = SRC / "with_exif.jpg"
    p_plain = SRC / "no_exif.jpg"
    make_jpg(p_exif, (900, 1200), (110, 130, 85), True)
    make_jpg(p_plain, (1200, 900), (150, 120, 90), False)
    ex = read_exif(str(p_exif))
    check(ex.get("model") == CAMERA[1] and ex.get("iso") == 1600
          and ex.get("exposure") == "1/1600" and ex.get("fnum") == 6.3
          and ex.get("focal_len") == 500.0 and ex.get("lens") == LENS
          and (ex.get("dt_original") or "").startswith("2024-05-12"),
          f"exif.py 解析真实EXIF: {ex.get('model')} ISO{ex.get('iso')} "
          f"{ex.get('exposure')}s f/{ex.get('fnum'):g} {ex.get('focal_len'):g}mm")

    lib = Library(LIB_DIR)
    lib.fill_species()
    stats = import_files(lib, [p_exif, p_plain], mode="ref", dest_root=None)
    check(stats["added"] == 2, f"导入 {stats['added']} 张(1带EXIF/1无EXIF)")
    ids = {r["path"]: r["id"] for r in lib.conn.execute("SELECT id, path FROM photos")}
    pid_exif = ids[str(p_exif.resolve())]
    pid_plain = ids[str(p_plain.resolve())]
    sp = lib.conn.execute(
        "SELECT code FROM species WHERE sci='Anas platyrhynchos'").fetchone()
    check(sp is not None, "图鉴含 Anas platyrhynchos")
    lib.add_records(pid_exif, [{"species_code": sp["code"],
                                "confidence": 0.97, "source": "verify"}])

    class _Win(QWidget):
        pass
    win = _Win()

    # ---- [2] 参数两列布局: 三段正确/显隐/实时重绘/高度预算/像素级墨水 ----
    print("\n[2] 参数两列渲染(中文模式: 左=焦·孔·快·ISO, 右=机身/镜头叠logo上方)")
    i18n.set_lang("zh")
    dlg = ShareDialog(lib, win, pid_exif)
    parts = dlg._card_info()["exif"]
    check(parts == EXPECTED_PARTS,
          f"参数三段正确(机身/镜头/焦·孔·快·ISO): {parts}")
    check(dlg.taken == "2024-05-12", f"拍摄日期取EXIF DateTimeOriginal: {dlg.taken}")
    check(dlg.exif_toggle.isChecked() and CAMERA[1] in dlg.exif_hint.text(),
          f"默认勾选, 提示行含机型: «{dlg.exif_hint.text()}»")
    ph1 = 2048                       # 900x1200图 → 照片区 1600*1.28
    pm_on = dlg.pm
    check(pm_on.width() == 1600 and pm_on.height() == ph1 + TEXT_ZONE_H,
          f"开启参数: 尺寸 {pm_on.width()}x{pm_on.height()} (文字区含品牌行)")

    dlg.exif_toggle.setChecked(False)          # toggled → 实时重绘
    pm_off = dlg.pm
    check(dlg._card_info()["exif"] == {}, "关闭勾选后参数段消失")
    check(pm_off.height() == ph1 + TEXT_ZONE_H,
          f"关闭后画布高度不变(品牌行常驻) {pm_off.height()}")
    dlg.exif_toggle.setChecked(True)
    check(dlg.pm.height() == pm_on.height(), "重新勾选实时恢复渲染")

    # 像素级验证(v3布局): 右列三行=机身(与日期同行)/镜头(与地点)/参数(与拍摄者);
    # 罕见度胶囊在英文名行右侧; 底部品牌行(produced by+logo)常驻
    x0 = 112
    x_col = 1600 - 112 - 880
    rows = [("机身", ph1 + 470), ("镜头", ph1 + 582), ("参数", ph1 + 678)]
    for tag, ry in rows:
        ink_on = ink_count(pm_on, x_col, ry, 880, 86)
        ink_off = ink_count(pm_off, x_col, ry, 880, 86)
        check(ink_on > 200, f"右列{tag}行渲染出文字(墨水 {ink_on})")
        check(ink_off == 0, f"关闭后{tag}行无墨水({ink_off})")
    # 高对比胶囊(稀有=红底白字)确定性验证: 直接指定rarity渲染
    # (常见=灰底与米色背景对比度低于墨水容差, 墨水法测不了, 视觉样张已确认)
    info_rare = dict(dlg._card_info())
    info_rare["rarity"] = "稀有"
    pm_rare = render_card(p_exif.resolve().as_posix(), info_rare, "light")
    ink_rare = ink_count(pm_rare, x_col, ph1 + 320, 880, 78)
    check(ink_rare > 500, f"稀有红胶囊在英文名行右侧(墨水 {ink_rare})")
    pm_rare.save(str(SHOTS / "share_exif_card_rare.png"), "PNG")
    brand_on = ink_count(pm_on, x0, ph1 + 790, 1380, 150)
    check(brand_on > 500, f"品牌行(produced by+logo)有内容(墨水 {brand_on})")

    dlg.grab().save(str(SHOTS / "share_exif_dialog_zh.png"))
    pm_on.save(str(SHOTS / "share_exif_card_on.png"), "PNG")
    pm_off.save(str(SHOTS / "share_exif_card_off.png"), "PNG")

    # ---- [3] 无EXIF照片: 勾选不产生空段; 单字段只显示该字段 ----
    print("\n[3] 无EXIF/部分EXIF")
    dlg2 = ShareDialog(lib, win, pid_plain)
    check(not any(dlg2._card_info()["exif"].values()),
          "无EXIF照片勾选后不产生空段")
    check("未检测到" in dlg2.exif_hint.text(),
          f"提示行显示无参数: «{dlg2.exif_hint.text()}»")
    ph2 = 1200                       # 1200x900图 → 照片区 1600*0.75
    pm2 = dlg2.pm
    check(pm2.height() == ph2 + TEXT_ZONE_H, f"无参数卡片高度 {pm2.height()}")
    check(ink_count(pm2, x_col, ph2 + 470, 880, 300) == 0,
          "无参数卡片右列三行无墨水")
    pm2.save(str(SHOTS / "share_exif_card_noexif.png"), "PNG")

    lib.conn.execute("UPDATE exif SET iso=3200 WHERE photo_id=?", (pid_plain,))
    lib.conn.commit()
    dlg2b = ShareDialog(lib, win, pid_plain)
    check(dlg2b._card_info()["exif"] == {"body": "", "lens": "",
                                         "shot": "ISO 3200"},
          f"只有ISO时仅显示ISO段: {dlg2b._card_info()['exif']}")
    check(dlg2b.pm.height() == ph2 + TEXT_ZONE_H,
          f"仅参数行画布高度 {dlg2b.pm.height()} (品牌行常驻)")
    check(ink_count(dlg2b.pm, x_col, ph2 + 678, 880, 86) > 200,
          "ISO参数在拍摄者同行右列渲染出文字")
    check(ink_count(dlg2b.pm, x_col, ph2 + 470, 880, 86) == 0,
          "机身/镜头行保持空白(只显示ISO)")

    # ---- [4] EN模式: 对话框可见文案无中文残留 ----
    print("\n[4] EN模式文案")
    i18n.set_lang("en")
    d_en = ShareDialog(lib, win, pid_exif)
    texts = collect_texts(d_en)
    bad = [s for s in texts if ZH.search(s)]
    check(not bad, f"EN 对话框 {len(texts)} 条可见文案无中文残留"
                   + (f": {bad[:4]}" if bad else ""))
    check(any("Camera data" in s for s in texts), "EN 含 Camera data 标签")
    check(d_en._card_info()["cn"] == "Mallard", "EN 卡片标题取英文名 Mallard")
    d_en.grab().save(str(SHOTS / "share_exif_dialog_en.png"))
    i18n.set_lang("zh")

    # ---- [5] 渲染健壮性: dark主题/照片丢失/超长参数 ----
    print("\n[5] 渲染健壮性")
    info = d_en._card_info()
    pm_dark = render_card(p_exif.resolve().as_posix(), info, "dark")
    check(not pm_dark.isNull() and pm_dark.height() == pm_on.height(),
          f"dark主题渲染不崩溃 {pm_dark.width()}x{pm_dark.height()}")
    pm_dark.save(str(SHOTS / "share_exif_card_dark.png"), "PNG")
    pm_missing = render_card(str(SRC / "missing.jpg"), info, "light")
    check(not pm_missing.isNull()
          and pm_missing.height() == 1600 * 9 // 10 + TEXT_ZONE_H,
          "照片文件丢失时占位图渲染不崩溃")
    info_long = dict(info)
    info_long["exif"] = {"body": "X" * 80, "lens": "Y" * 80, "shot": "Z" * 200}
    pm_long = render_card(p_exif.resolve().as_posix(), info_long, "light")
    check(not pm_long.isNull()
          and pm_long.height() == ph1 + TEXT_ZONE_H,
          f"超长参数不崩溃(右列880封顶/左列省略号截断) {pm_long.width()}x{pm_long.height()}")

    print(f"\n截图/卡片: {SHOTS / 'share_exif_*.png'}  测试库: {LIB_DIR}")
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
