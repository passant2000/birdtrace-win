# -*- coding: utf-8 -*-
"""0.8-② 移动硬盘离线韧性验证(离线, 合成库)。

  [1] core.offline: 可用/离线卷/不在原位置 三态判定; 离线卷按卷聚合
  [2] Library.file_status: 计数+photos.missing回写(0/1/2)+缓存/失效
  [3] relink_photos: 同名hash校验 / 改名按size+hash找回 / 同名假货不误配
  [4] 时间线: 离线横幅(不带重新链接)与丢失横幅(带)分开; 角标"原图离线"/"文件丢失"
  [5] 查看器/画框/分享卡: 离线文案(含盘符) vs 丢失文案

用法: .venv/Scripts/python.exe tools/verify_offline.py
"""
from __future__ import annotations

import os
import shutil
import string
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def free_drive() -> str:
    """找一个本机不存在的盘符(模拟拔掉的移动硬盘)。"""
    for L in reversed(string.ascii_uppercase):
        if not os.path.exists(f"{L}:\\"):
            return f"{L}:"
    raise RuntimeError("no free drive letter")


def make_img(path: Path, seed: int = 0):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (320, 240), (60 + seed * 7 % 100, 100, 140))
    d = ImageDraw.Draw(im)
    d.ellipse([60 + seed, 50, 260, 190], fill=(230, 200 - seed % 50, 120))
    d.text((10, 10), f"seed{seed}", fill=(255, 255, 255))
    im.save(path, "JPEG")


def add(lib, p: Path, seed: int, code: str | None = None) -> int:
    import app.media as media
    make_img(p, seed)
    pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                        p.stat().st_mtime, 320, 240, 0)
    if code:
        lib.add_records(pid, [{"species_code": code, "confidence": 0.9}])
    return pid


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme, i18n
    theme.apply_theme(app, "light")
    i18n.set_lang("zh")

    LIB = PROJ / "data/offline_check"
    if LIB.exists():
        shutil.rmtree(LIB)
    (LIB / "src").mkdir(parents=True)
    OFF = free_drive()

    print(f"\n[1] core.offline 三态判定 (离线盘模拟={OFF})")
    from app.core import offline as off
    real = LIB / "src" / "ok.jpg"
    make_img(real, 1)
    gone = LIB / "src" / "gone.jpg"           # 不创建
    off_path = f"{OFF}\\成片\\DSC0001.jpg"
    check(off.path_state(str(real)) == off.OK, "存在文件=OK")
    check(off.path_state(str(gone)) == off.MISSING, "盘在文件不在=MISSING")
    check(off.path_state(off_path) == off.OFFLINE, "盘不在=OFFLINE")
    cls = off.classify_paths([(1, str(real)), (2, str(gone)),
                              (3, off_path), (4, f"{OFF}\\x\\y.jpg")])
    check(cls["ok"] == [1] and cls["missing"] == [2]
          and cls["offline"] == {f"{OFF}\\": [3, 4]},
          f"批量分类按卷聚合 ({cls})")
    check(off.drive_label(f"{OFF}\\") == OFF, "盘符标签去尾斜杠")
    check(off.drive_root(r"\\nas\photos\a.jpg") == "\\\\nas\\photos\\",
          "UNC路径卷根")

    print("\n[2] Library.file_status + photos.missing 回写")
    from app.db import Library
    lib = Library(LIB)
    lib.fill_species()
    codes = [r["code"] for r in lib.conn.execute(
        "SELECT code FROM species LIMIT 3").fetchall()]
    p_ok = add(lib, LIB / "src" / "a.jpg", 2, codes[0])
    p_off = add(lib, LIB / "src" / "b.jpg", 3, codes[1])
    p_miss = add(lib, LIB / "src" / "c.jpg", 4, codes[2])
    # 把b改成离线盘路径(模拟引用F盘), c删除文件(真丢失)
    lib.conn.execute("UPDATE photos SET path=? WHERE id=?",
                     (f"{OFF}\\成片\\b.jpg", p_off))
    lib.conn.commit()
    (LIB / "src" / "c.jpg").unlink()
    fs = lib.file_status(max_age=0)
    check(fs["ok"] == 1 and fs["n_offline"] == 1 and fs["missing"] == [p_miss]
          and list(fs["offline"].values()) == [[p_off]],
          f"状态计数 ok=1/offline=1/missing=1 ({fs})")
    col = {r["id"]: r["missing"] for r in lib.conn.execute(
        "SELECT id, missing FROM photos")}
    check(col == {p_ok: 0, p_off: 1, p_miss: 2}, f"photos.missing回写 {col}")
    fs2 = lib.file_status()
    check(fs2 is fs, "3s内缓存命中(同一对象)")
    lib.invalidate_file_status()
    check(lib.file_status() is not fs, "invalidate后重扫")
    check(sorted(lib.missing_photo_ids()) == sorted([p_off, p_miss]),
          "missing_photo_ids=离线+丢失")

    print("\n[3] relink_photos: hash校验 / 改名找回 / 假货不误配")
    moved = LIB / "moved"
    moved.mkdir()
    # c: 改名为 renamed.jpg 放到新目录(同内容)
    make_img(moved / "renamed.jpg", 4)
    # 再放一个同名假货 c.jpg(内容不同)
    make_img(moved / "c.jpg", 99)
    n = lib.relink_photos(moved)
    row = lib.conn.execute("SELECT path, missing FROM photos WHERE id=?",
                           (p_miss,)).fetchone()
    check(n == 1, f"重新链接1张 (n={n})")
    check(Path(row["path"]).name == "renamed.jpg",
          f"按size+hash找回改名文件, 同名假货不误配 ({row['path']})")
    check(row["missing"] == 0, "relink后missing=0")
    check(lib.file_status(max_age=0)["missing"] == [], "重扫无丢失")
    # 离线盘的b不该被relink(它不在新目录), 仍离线
    check(lib.file_status(max_age=0)["n_offline"] == 1, "离线照片不受relink影响")
    # 同名唯一无hash命中(重存过的文件) → 按名兼容
    p_resaved = add(lib, LIB / "src" / "d.jpg", 5, codes[0])
    (LIB / "src" / "d.jpg").unlink()
    moved2 = LIB / "moved2"
    moved2.mkdir()
    make_img(moved2 / "d.jpg", 77)   # 同名不同内容, 唯一候选
    n2 = lib.relink_photos(moved2)
    check(n2 == 1, "同名唯一候选按名兼容链接(重存过的文件)")

    print("\n[4] 时间线横幅与角标")
    from app.ui.timeline_page import TimelinePage
    # 再造一个真丢失
    p_miss2 = add(lib, LIB / "src" / "e.jpg", 6, codes[1])
    (LIB / "src" / "e.jpg").unlink()
    lib.invalidate_file_status()
    page = TimelinePage(lib, None)
    page.resize(1300, 800)
    page.show()
    app.processEvents()
    page.refresh(force=True)
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(600, loop.quit)
    loop.exec()
    labels = [w.text() for w in page.content.findChildren(QLabel)]
    off_banner = [x for x in labels if "原图离线" in x and OFF in x]
    miss_banner = [x for x in labels if "不在原位置" in x]
    check(len(off_banner) == 1, f"离线横幅含盘符 ({off_banner[:1]})")
    check(len(miss_banner) == 1, f"丢失横幅 ({miss_banner[:1]})")
    from PySide6.QtWidgets import QPushButton
    btns = [b.text() for b in page.content.findChildren(QPushButton)]
    check(btns.count("重新链接…") == 1, f"只有丢失横幅带重新链接按钮 ({btns})")
    from app.theme.widgets import PhotoGridItem
    corners = {it.corner for it in page.content.findChildren(PhotoGridItem)}
    check("原图离线" in corners and "文件丢失" in corners,
          f"角标区分离线/丢失 ({corners})")
    # 批量重识别: 全选离线 → 提示离线而非丢失(拦截弹框)
    from PySide6.QtWidgets import QMessageBox
    seen = {}
    QMessageBox.information = staticmethod(
        lambda *a, **k: seen.update(title=a[1], text=a[2]))
    QMessageBox.question = staticmethod(
        lambda *a, **k: seen.update(qtitle=a[1]) or QMessageBox.No)
    page._toggle_select()
    page._selected = {p_off}
    page._batch_rerecognize()
    check(seen.get("title") == "原图离线" and OFF in seen.get("text", ""),
          f"全离线重识别→离线提示(含盘符) ({seen.get('title')})")
    page._toggle_select()
    page.close()

    print("\n[5] 查看器/画框/分享卡离线文案")
    from app.ui.viewer import PhotoViewer
    v = PhotoViewer(lib, None, p_off, [p_off, p_ok])
    v.show()
    app.processEvents()
    vt = " ".join(w.text() for w in v.findChildren(QLabel))
    check("原图离线" in vt and OFF in vt, "查看器: 离线文案含盘符")
    # 回归: 从离线照片切到正常照片再切回(此前_scene.clear()删掉_item会崩)
    v._next()
    app.processEvents()
    check(not v.view._item.pixmap().isNull(), "查看器: 离线→正常切图显示大图")
    v._prev()
    app.processEvents()
    ov = getattr(v.view, "_overlay", None)
    check(v.view._item.pixmap().isNull() and ov is not None and ov.isVisible(),
          "查看器: 正常→离线切回占位说明")
    v.close()
    v2 = PhotoViewer(lib, None, p_miss2, [p_miss2])
    v2.show()
    app.processEvents()
    vt2 = " ".join(w.text() for w in v2.findChildren(QLabel))
    check("不存在" in vt2 and "重新链接" in vt2, "查看器: 丢失文案引导重新链接")
    v2.close()
    from app.ui.rebox_dialog import ReboxDialog
    rb = ReboxDialog(lib, None, p_off)
    check("原图离线" in rb.hint.text() and OFF in rb.hint.text(),
          "画框: 离线文案")
    rb.close()
    from app.ui.share_dialog import ShareDialog
    sd = ShareDialog(lib, None, p_off)
    check("原图离线" in sd.exif_hint.text(), "分享卡: 离线提示")
    sd.close()
    sd2 = ShareDialog(lib, None, p_ok)
    check("⚠️" not in sd2.exif_hint.text(), "分享卡: 正常照片无警告")
    sd2.close()

    print()
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
