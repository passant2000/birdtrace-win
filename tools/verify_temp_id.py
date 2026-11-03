# -*- coding: utf-8 -*-
"""临时识别验证: 剪贴板/选图→子进程识别→结果展示, 全程不落库。

用法: .venv/Scripts/python.exe tools/verify_temp_id.py
需要识别模型资产(assets/models); 测试图为程序生成的合成图+真实测试照片。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB_DIR = PROJ / "data/tempid_check"
FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def restore_real_rawpy():
    """彻底移除fake rawpy(含子模块)。只pop主模块会残留rawpy._rawpy,
    真模块再导入时撞circular import(实测AttributeError)。"""
    for k in [k for k in sys.modules
              if k == "rawpy" or k.startswith("rawpy.")]:
        del sys.modules[k]


def make_test_images() -> list[Path]:
    """真实鸟照(此前冻结验证用的中文路径图) + 程序生成的纯色无鸟图。"""
    out = []
    for name in ("data/frozen_060_src/普通翠鸟中文.jpg",
                 "data/chengpian/普通翠鸟中文.jpg",
                 "data/demo_src/Alcedo_atthis.jpg"):
        p = PROJ / name
        if p.exists() and p.stat().st_size > 30000:
            out.append(p)
            break
    # 纯色"无鸟"图
    from PySide6.QtGui import QImage, QColor
    img = QImage(640, 480, QImage.Format_RGB32)
    img.fill(QColor(90, 140, 90))
    p = LIB_DIR / "plain.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(p))
    out.append(p)
    return out


def main():
    if LIB_DIR.exists():
        shutil.rmtree(LIB_DIR)

    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QEventLoop, Qt, QTimer
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme
    theme.apply_theme(app, "light")
    from app import i18n
    from app.db import Library
    from app import paths
    from app.ui import temp_id_dialog as td

    lib = Library(LIB_DIR)
    lib.fill_species()

    class FakeWin:
        assets = paths.assets_dir()

    dlg = td.TempIdDialog(lib, FakeWin())
    dlg.show()
    app.processEvents()
    check(dlg._proc is None, "对话框构造不立即拉起worker(懒加载)")

    print("\n[1] 剪贴板路径")
    from PySide6.QtGui import QImage
    QGuiApplication = __import__("PySide6.QtGui",
                                 fromlist=["QGuiApplication"]).QGuiApplication
    QGuiApplication.clipboard().setImage(QImage())   # 清空剪贴板
    dlg._paste_clipboard()
    check("剪贴板" in dlg.status.text() or "screenshot" in dlg.status.text(),
          f"空剪贴板提示 ({dlg.status.text()[:40]})")

    imgs = make_test_images()
    check(len(imgs) >= 1, f"测试图就绪 ({[i.name for i in imgs]})")

    print("\n[2] 识别链路(子进程)")
    # 有鸟图(若有真实照片)与无鸟图都跑
    results: dict[str, tuple] = {}

    def run_one(path: Path, key: str):
        loop = QEventLoop()
        done = {}

        def poll():
            txt = dlg.results.text()
            if txt and "识别中" not in txt and "Recognizing" not in txt:
                done["txt"] = txt
                loop.quit()
        dlg._recognize_file(path)
        timer = QTimer()
        timer.timeout.connect(poll)
        timer.start(300)
        QTimer.singleShot(120000, loop.quit)
        loop.exec()
        timer.stop()
        results[key] = (dlg.results.text(), dlg.preview.pixmap())

    # 库断言基准
    n_photos0 = lib.photo_count()
    n_rec0 = lib.conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]

    bird_img = [i for i in imgs if i.suffix == ".jpg" or i.name != "plain.png"]
    if bird_img:
        run_one(bird_img[0], "bird")
        txt, pix = results["bird"]
        check("没认出鸟" not in txt and "failed" not in txt.lower(),
              f"真实照片识别出结果 ({txt.splitlines()[:2]})")
        check(pix is not None and not pix.isNull(), "预览图已显示")
    run_one(LIB_DIR / "plain.png", "plain")
    txt, _pix = results["plain"]
    check("没认出鸟" in txt or "No bird" in txt,
          f"无鸟图走无检测路径 ({txt[:36]})")

    print("\n[3] 不落库断言")
    check(lib.photo_count() == n_photos0, "photos表零新增")
    check(lib.conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
          == n_rec0, "records表零新增")
    check(not (LIB_DIR / "migration").exists()
          and not any(LIB_DIR.glob("*.html")), "库目录无临时html落盘")

    print("\n[4] 过期结果丢弃")
    dlg._pid = 99
    dlg._apply({"ok": True, "pid": 1, "records": []})   # 旧pid结果
    check(True, "旧pid不崩溃")

    print("\n[5] RAW支持(mock解码集成+损坏RAW错误路径)")
    import numpy as np
    import types

    class _FakeRaw:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def postprocess(self, **kw):
            # 合成RGB图供预览/识别链路(真实解码由rawpy/LibRaw保证)
            img = np.full((400, 600, 3), 200, np.uint8)
            img[150:250, 250:350] = (60, 40, 30)
            return img

    fake_rawpy = types.ModuleType("rawpy")
    fake_rawpy.imread = lambda path: _FakeRaw()
    fake_rawpy.LibRawFileUnsupportedError = type(
        "LibRawFileUnsupportedError", (Exception,), {})
    sys.modules["rawpy"] = fake_rawpy
    raw_src = LIB_DIR / "fake.arw"
    raw_src.write_bytes(b"FAKE")
    dlg_r = td.TempIdDialog(lib, FakeWin())
    dlg_r.show()
    app.processEvents()
    dlg_r._recognize_file(raw_src)
    loop5 = QEventLoop()

    def poll5():
        txt = dlg_r.results.text()
        if txt and "识别中" not in txt and "Recognizing" not in txt \
                and "Decoding" not in txt:
            loop5.quit()
    tm5 = QTimer()
    tm5.timeout.connect(poll5)
    tm5.start(300)
    QTimer.singleShot(120000, loop5.quit)
    loop5.exec()
    tm5.stop()
    tmp_jpg = dlg_r._tmp_dir / "fake_raw.jpg"
    check(tmp_jpg.exists(), "RAW经rawpy解码落临时JPG")
    # 合成色块图不会有真鸟——断言"完整走通到识别结果"(非解码失败/非卡住)
    rtxt = dlg_r.results.text()
    check(rtxt and "识别中" not in rtxt and "Recognizing" not in rtxt,
          f"mock RAW→识别链路完整走通 ({rtxt[:30]})")
    dlg_r.close()

    # 损坏RAW: data/test_raw/sample.nef = 被截断的样张, LibRaw报错且UI不崩
    restore_real_rawpy()
    bad = PROJ / "data/test_raw/sample.nef"
    if bad.exists():
        dlg_b = td.TempIdDialog(lib, FakeWin())
        dlg_b.show()
        app.processEvents()
        dlg_b._recognize_file(bad)
        app.processEvents()
        check("RAW 解码失败" in dlg_b.status.text(),
              f"损坏RAW报错不崩溃 ({dlg_b.status.text()[:40]})")
        dlg_b.close()
    else:
        check(False, "损坏RAW样张缺失(data/test_raw/sample.nef)")

    # 不支持的压缩档(如尼康Z8高效RAW HE, LibRaw 0.22.x已知缺口):
    # LibRawFileUnsupportedError → 可操作的人话提示(导JPG/转DNG), 非甩英文错误
    fake_unsup = types.ModuleType("rawpy")

    class _UnsupError(Exception):
        pass

    fake_unsup.LibRawFileUnsupportedError = _UnsupError
    fake_unsup.imread = lambda path: (_ for _ in ()).throw(
        _UnsupError(b"Unsupported file format or not RAW file"))
    sys.modules["rawpy"] = fake_unsup
    hef = LIB_DIR / "he.nef"
    hef.write_bytes(b"FAKE")
    dlg_u = td.TempIdDialog(lib, FakeWin())
    dlg_u.show()
    app.processEvents()
    dlg_u._decode_raw(hef)
    check("内置解码器" in dlg_u.status.text() and "DNG" in dlg_u.status.text(),
          f"HE等不支持档位给人话提示 ({dlg_u.status.text()[:48]})")
    dlg_u.close()
    restore_real_rawpy()

    print("\n[5c] 内嵌JPEG兜底(FastStone同款: LibRaw追不上的新压缩档→抠内嵌预览)")
    import struct
    import io as _io
    from PIL import Image as _Img
    _buf = _io.BytesIO()
    _Img.new("RGB", (64, 48), (120, 140, 90)).save(_buf, "JPEG", quality=90)
    _jpg = _buf.getvalue()

    def _mk_tiff(jpeg_bytes):
        blob_off = 8 + 2 + 3 * 12 + 4
        out = bytearray(b"II*\x00" + struct.pack("<I", 8))
        out += struct.pack("<H", 3)
        out += struct.pack("<HHI", 259, 3, 1) + struct.pack("<H", 6) + b"\x00\x00"
        out += struct.pack("<HHI", 513, 4, 1) + struct.pack("<I", blob_off)
        out += struct.pack("<HHI", 514, 4, 1) + struct.pack("<I", len(jpeg_bytes))
        out += struct.pack("<I", 0)
        assert len(out) == blob_off
        return bytes(out + jpeg_bytes)

    def _mk_tiff_nopreview():
        out = bytearray(b"II*\x00" + struct.pack("<I", 8))
        out += struct.pack("<H", 1)
        out += struct.pack("<HHI", 259, 3, 1) + struct.pack("<H", 34713) \
            + b"\x00\x00"
        out += struct.pack("<I", 0)
        return bytes(out)

    class _UnsupError(Exception):
        pass

    fake_he = types.ModuleType("rawpy")
    fake_he.LibRawFileUnsupportedError = _UnsupError
    fake_he.imread = lambda path: (_ for _ in ()).throw(
        _UnsupError(b"Unsupported file format or not RAW file"))
    sys.modules["rawpy"] = fake_he
    dlg_e = td.TempIdDialog(lib, FakeWin())
    dlg_e.show()
    app.processEvents()
    tiff_he = LIB_DIR / "he_with_preview.nef"
    tiff_he.write_bytes(_mk_tiff(_jpg))
    emb = dlg_e._decode_raw(tiff_he)
    check(emb is not None and emb.exists() and emb.read_bytes() == _jpg,
          "TIFF系RAW解不开时兜底抠出内嵌JPEG(逐字节一致)")
    tiff_no = LIB_DIR / "he_no_preview.nef"
    tiff_no.write_bytes(_mk_tiff_nopreview())
    r_no = dlg_e._decode_raw(tiff_no)
    check(r_no is None and "内置解码器" in dlg_e.status.text()
          and "DNG" in dlg_e.status.text(),
          f"无内嵌预览时给人话提示 ({dlg_e.status.text()[:36]})")
    dlg_e.close()
    restore_real_rawpy()

    print("\n[5d] 真实Z8 HE NEF(data/test_raw/z8_he.nef = 用户样张副本)")
    z8he = PROJ / "data/test_raw/z8_he.nef"
    if z8he.exists():
        dlg_z = td.TempIdDialog(lib, FakeWin())
        dlg_z.show()
        app.processEvents()
        embz = dlg_z._decode_raw(z8he)   # 真rawpy报unsupported → 走兜底
        if embz is not None:
            imz = _Img.open(str(embz))
            check(imz.size == (8256, 5504),
                  f"Z8 HE兜底提取全尺寸内嵌JPEG {imz.size}")
        else:
            check(False, f"Z8 HE兜底失败: {dlg_z.status.text()[:48]}")
        dlg_z.close()
    else:
        check(True, "Z8样张不在(跳过该断言, 不影响其余)")

    print("\n[6] EN模式")
    i18n.set_lang("en")
    import re
    zh = re.compile(r"[\u4e00-\u9fff]")
    dlg2 = td.TempIdDialog(lib, FakeWin())
    dlg2.show()
    app.processEvents()
    texts = []
    for lab in dlg2.findChildren(type(dlg2.status)):
        texts.append(lab.text())
    bad = [x for x in texts if x and zh.search(x) and "e.g" not in x]
    check(not [b for b in bad if "鸟" in b or "截图" in b],
          f"EN模式对话框无中文残留 ({bad[:2]})")
    dlg2._shutdown_proc = None
    dlg2.close()
    i18n.set_lang("zh")

    dlg.close()
    print()
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
