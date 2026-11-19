# -*- coding: utf-8 -*-
"""年度年鉴(10c)验证: 页面(年份选择/汇总行/十八图网格/九宫格/月度柱/
年度之最)+PDF导出(%PDF头/页数/中文字体嵌入抽查)+空库优雅降级。
不跑模型, 约10秒。"""
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


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # 字体嵌入断言需要真实字体(offscreen默认无字体目录)——
    # 指向系统字体目录=真机等价条件
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
        "INSERT INTO batches(mode,dest,region_id,count) VALUES('copy',?,'CN',4)",
        (str(D / "src"),))
    bid = lib.conn.execute("SELECT id FROM batches LIMIT 1").fetchone()["id"]
    IMGS = ["Alcedo_atthis.jpg", "Anas_platyrhynchos.jpg",
            "Ardea_cinerea.jpg", "Cyanistes_caeruleus.jpg"]
    codes = []
    for kw in ("%kingfisher%", "%mallard%", "%gray heron%", "%blue tit%"):
        r = lib.conn.execute(
            "SELECT code FROM species WHERE en LIKE ? LIMIT 1",
            (kw,)).fetchone()
        codes.append(r["code"] if r else "")
    pids = []
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
        pids.append(pid)
    lib.conn.commit()

    # ---------- [1] 页面 ----------
    print("[1] 页面")
    from app.ui.main_window import MainWindow
    win = MainWindow(lib, PROJ / "assets")
    win.show()
    win.switch_to("yearbook")
    for _ in range(8):
        app.processEvents()
    page = win.pages["yearbook"]
    check(win.stack.currentWidget() is page, "年鉴页注册且可切")
    check(page._year == "2026", f"年份自动选中 ({page._year})")
    from PySide6.QtWidgets import QLabel, QComboBox
    texts = " ".join(w.text() for w in page.content.findChildren(QLabel))
    check("年度十八图" in texts and "年度新种" in texts,
          f"十八图/九宫格卡渲染")
    check("月度出片" in texts and "年度之最" in texts, "月度柱/年度之最渲染")
    check("3" in texts, "汇总数字渲染")
    # 年份切换
    page.year_combo.blockSignals(False)
    # ---------- [2] PDF ----------
    print("[2] PDF 导出")
    from app.ui.yearbook_pdf import export_yearbook_pdf
    # 直接调内部(绕过文件对话框): 重定向 getSaveFileName
    from PySide6.QtWidgets import QFileDialog
    out = D / "yearbook.pdf"
    QFileDialog.getSaveFileName = staticmethod(
        lambda *a, **k: (str(out), "PDF (*.pdf)"))
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.information = staticmethod(lambda *a, **k: None)  # offscreen无模态
    export_yearbook_pdf(lib, win, "2026")
    check(out.exists() and out.stat().st_size > 20_000,
          f"PDF 生成 ({out.stat().st_size if out.exists() else 0}B)")
    head = out.read_bytes()[:5]
    check(head == b"%PDF-", "PDF 文件头")
    body = out.read_bytes()
    check(body.count(b"/Type /Page") >= 3 or body.count(b"/Type/Page") >= 3,
          f"多页结构 (pages≥3)")
    # 中文嵌入抽查: PDF 流里的字体子集(找不到=纯ASCII字体, 会变豆腐)
    check(b"FontFile" in body or b"FontDescriptor" in body,
          "字体描述符存在(嵌入)")
    # 空库降级
    lib2 = Library(PROJ / "data/_yearbook_check_empty")
    lib2.fill_species()
    from app.ui.yearbook_page import YearbookPage
    p2 = YearbookPage(lib2, win)
    p2.refresh()
    from PySide6.QtWidgets import QLabel
    texts2 = " ".join(w.text() for w in p2.content.findChildren(QLabel))
    check("导入并识别" in texts2, "空库引导文案")
    lib2.conn.close()

    win.close()
    print("\n" + ("FAIL" if FAILED["v"] else "ALL PASS"))
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
