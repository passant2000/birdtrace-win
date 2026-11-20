# -*- coding: utf-8 -*-
"""年度年鉴(2026-11-20 重做)验证: 统一 A4 页面模型 + 预览与 PDF 同版式
—— 页数/分页数学、深浅主题、封面满版/分栏、地图页像素、软件内 A4 预览
(缩放)、PDF(页数/字体嵌入)、空库降级。不跑模型, 约 15 秒。"""
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


def _pixel(img, x, y):
    c = img.pixelColor(int(x), int(y))
    return (c.red(), c.green(), c.blue())


def _render(doc, index, k=2.0):
    from PySide6.QtGui import QColor, QImage, QPainter
    img = QImage(int(doc_k_w(k)), int(doc_k_h(k)), QImage.Format_RGB32)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    doc.draw(p, index, k)
    p.end()
    return img


def doc_k_w(k):
    from app.core import yearbook as YB
    return YB.PAGE_W * k


def doc_k_h(k):
    from app.core import yearbook as YB
    return YB.PAGE_H * k


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    app = QApplication(sys.argv)
    app.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    from app import theme, i18n
    theme.apply_theme(app, "light")
    i18n.set_lang("zh")

    D = PROJ / "data/_yearbook_check"
    if D.exists():
        shutil.rmtree(D)
    D.mkdir(parents=True)
    from app.db import Library
    import app.media as media
    lib = Library(D)
    lib.fill_species()
    lib.conn.execute(
        "INSERT INTO batches(mode,dest,region_id,count) "
        "VALUES('copy',?,'CN-AH',6)", (str(D / "src"),))
    bid = lib.conn.execute("SELECT id FROM batches LIMIT 1").fetchone()["id"]
    IMGS = ["Alcedo_atthis.jpg", "Anas_platyrhynchos.jpg",
            "Ardea_cinerea.jpg", "Cyanistes_caeruleus.jpg",
            "Passer_montanus.jpg", "Upupa_epops.jpg"]
    codes = []
    for kw in ("%kingfisher%", "%mallard%", "%gray heron%", "%blue tit%",
               "%sparrow%", "%hoopoe%"):
        r = lib.conn.execute(
            "SELECT code FROM species WHERE en LIKE ? LIMIT 1",
            (kw,)).fetchone()
        codes.append(r["code"] if r else "")
    for i, img in enumerate(IMGS):
        p = D / f"b{i}.jpg"
        shutil.copy(PROJ / "data/test_images" / img, p)
        pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                            p.stat().st_mtime, 0, 0, bid)
        lib.conn.execute(
            "INSERT INTO exif(photo_id, dt_original) VALUES(?,?)",
            (pid, f"2026-0{i + 3}-1{i} 08:00:00"))
        if codes[i]:
            lib.conn.execute(
                "INSERT INTO records(photo_id,species_code,rank,confidence,"
                "source) VALUES(?,?,1,0.9,'detect')", (pid, codes[i]))
        lib.set_aesthetic(pid, 6.0 + i)
    sp = lib.create_spot("测试鸟点", 31.0, 118.0)
    lib.set_photos_spot([pid for pid in
                         [r["id"] for r in lib.conn.execute(
                             "SELECT id FROM photos")]], sp)
    lib.conn.commit()

    from app.core import yearbook as YB

    # ---------- [1] 文档模型 ----------
    print("[1] 文档模型")
    doc = YB.build_doc(lib, "2026", YB.LIGHT, "full", max_px=384)
    n_sp = len(doc.species)
    check(n_sp >= 5, f"鸟种档案数据 ({n_sp} 种)")
    check(doc.sp_pages == max(1, (n_sp + YB.SP_PER_PAGE - 1) //
                              YB.SP_PER_PAGE),
          f"档案分页数学 ({doc.sp_pages} 页 / 每页 {YB.SP_PER_PAGE})")
    check(doc.page_count == 2 + doc.sp_pages + 3,
          f"总页数=封面+回顾+档案+地图+时间线+十八图 ({doc.page_count})")
    # 纯数学: 12 种 → 2 页档案
    fake = YB.YearbookDoc({"best18": [], "monthly": [0] * 12},
                          [{"cn": f"x{i}", "n": 1} for i in range(12)],
                          {"provinces": [], "spots": []}, [], "2026")
    check(fake.sp_pages == 2 and fake.page_count == 7,
          f"12 种=2 页档案/共 7 页 ({fake.sp_pages}/{fake.page_count})")

    # ---------- [2] 渲染: 深浅主题 / 封面两式 / 地图 ----------
    print("[2] 渲染")
    p_overview = 1
    img_l = _render(YB.build_doc(lib, "2026", YB.LIGHT, "full",
                                 max_px=384), p_overview)
    check(_pixel(img_l, 3, 3) == (255, 255, 255),
          f"浅色页面底色=#FFFFFF ({_pixel(img_l, 3, 3)})")
    img_d = _render(YB.build_doc(lib, "2026", YB.DARK, "full",
                                 max_px=384), p_overview)
    check(_pixel(img_d, 3, 3) == (0x11, 0x18, 0x20),
          f"深色页面底色=#111820 ({_pixel(img_d, 3, 3)})")
    # 封面满版: 左下角应是照片/压暗(非白); 分栏: 左下角是白底
    h = doc_k_h(2.0)
    img_full = _render(YB.build_doc(lib, "2026", YB.LIGHT, "full",
                                    max_px=384), 0)
    img_split = _render(YB.build_doc(lib, "2026", YB.LIGHT, "split",
                                     max_px=384), 0)
    px_full = _pixel(img_full, 20, h - 20)
    px_split = _pixel(img_split, 20, h - 20)
    check(sum(px_full) < 700, f"满版封面左下=照片压暗 ({px_full})")
    check(px_split == (255, 255, 255), f"分栏封面左下=白底 ({px_split})")
    # 地图页: 应有强调色点位像素
    map_i = 2 + doc.sp_pages
    img_map = _render(doc, map_i)
    w, hh = img_map.width(), img_map.height()
    hits = 0
    # 地图框: 14..196mm 宽 / 46..164mm 高 (k=2 → ×2 px)
    for yy in range(int(46 * 2), int(164 * 2)):
        for xx in range(int(14 * 2), int(196 * 2)):
            r, g, b = _pixel(img_map, xx, yy)
            if abs(r - 0x52) < 30 and abs(g - 0x7C) < 30 and abs(b - 0x70) < 30:
                hits += 1
    check(hits > 8, f"地图页含强调色点位(≥1 个点) ({hits} px)")
    # 全部页面可渲染(不抛异常)
    ok_all = True
    for i in range(doc.page_count):
        try:
            _render(doc, i, 1.2)
        except Exception as e:      # noqa: BLE001
            ok_all = False
            print("   page", i + 1, "render failed:", e)
    check(ok_all, f"全部 {doc.page_count} 页可渲染")

    # ---------- [3] 软件内 A4 预览 ----------
    print("[3] 软件内预览")
    from app.ui.main_window import MainWindow
    win = MainWindow(lib, PROJ / "assets")
    win.show()
    win.switch_to("yearbook")
    for _ in range(8):
        app.processEvents()
    page = win.pages["yearbook"]
    check(win.stack.currentWidget() is page, "年鉴页注册且可切")
    check(page._year == "2026", f"年份自动选中 ({page._year})")
    check(page._doc is not None and page._doc.page_count == doc.page_count,
          "预览文档与导出同页数")
    check(page.preview.minimumHeight() > 0 and page.preview.doc is not None,
          "A4 预览画布已排布")
    k0 = page.preview._k()
    w0 = page.preview.width()
    check(abs(k0 - w0 / YB.PAGE_W) < 0.02,
          f"默认=适应宽度 ({k0:.2f} = {w0}/{YB.PAGE_W:.0f})")
    page.zoom_combo.setCurrentIndex(2)          # 100%(96dpi)
    for _ in range(2):
        app.processEvents()
    k1 = page.preview._k()
    check(abs(k1 - 3.7795) < 0.02, f"100% = 96dpi ({k1:.2f} px/mm)")
    page.zoom_combo.setCurrentIndex(1)          # 75%
    for _ in range(2):
        app.processEvents()
    check(abs(page.preview._k() - 3.7795 * 0.75) < 0.02,
          f"75% 档生效 ({page.preview._k():.2f})")
    page.zoom_combo.setCurrentIndex(0)
    check("A4" in page.hint.text(), "页头说明=与 PDF 同版式")
    pm = page.preview.grab()
    check(not pm.isNull(), "预览抓图非空")

    # ---------- [4] PDF ----------
    print("[4] PDF")
    from app.ui.yearbook_pdf import write_pdf
    out = D / "yb_light.pdf"
    d2 = write_pdf(lib, "2026", str(out), YB.LIGHT, "full")
    check(out.stat().st_size > 20_000, f"浅色 PDF 生成 ({out.stat().st_size}B)")
    body = out.read_bytes()
    check(body[:5] == b"%PDF-", "PDF 文件头")
    n_page = body.count(b"/Type /Page") - body.count(b"/Type /Pages")
    check(n_page == d2.page_count, f"PDF 页数={d2.page_count} (got {n_page})")
    check(b"FontFile" in body, "中文字体子集嵌入")
    out2 = D / "yb_dark.pdf"
    d3 = write_pdf(lib, "2026", str(out2), YB.DARK, "split")
    check(out2.stat().st_size > 20_000 and d3.page_count == d2.page_count,
          "深色+分栏封面 PDF 生成")

    # ---------- [5] 空库 ----------
    print("[5] 空库")
    D2 = PROJ / "data/_yearbook_check_empty"
    if D2.exists():
        shutil.rmtree(D2)
    D2.mkdir(parents=True)
    lib2 = Library(D2)
    lib2.fill_species()
    from app.ui.yearbook_page import YearbookPage
    p2 = YearbookPage(lib2, win)
    p2.refresh()
    check(p2._doc is None, "空库不建文档")
    check("导入" in p2.hint.text(), f"空库引导文案 ({p2.hint.text()[:20]})")
    lib2.close()

    win.close()
    print("\n" + ("FAIL" if FAILED["v"] else "ALL PASS"))
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
