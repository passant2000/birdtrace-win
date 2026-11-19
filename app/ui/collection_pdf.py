# -*- coding: utf-8 -*-
"""作品集画册 PDF 导出(实测反馈3b, 2026-11-19):
A4 竖版(设计规范-年鉴与静态站 §3: 595.28×841.89pt/安全边距14mm/底部页码+
BirdTrace标识/减少圆角/浅色/衬线大标题[Noto Serif SC→Georgia→雅黑回落]/
强调色自然绿#527C70)。版式: 封面(集名+封面大图+概要+创作者) + 作品页
(每页2张, 编辑排版: 图+鸟种名+日期·地点)。QPdfWriter 自动子集嵌入中文。
原图离线时降级用缩略图并注记; 都没有画占位框, 绝不中断导出。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QPainter, QPixmap)
from PySide6.QtWidgets import QFileDialog, QMessageBox
from PySide6.QtGui import QPdfWriter
from PySide6.QtCore import QPageSize

from .. import theme
from ..i18n import t, sname
from ..media import cached_thumbnail, ensure_thumbnail

# 设计规范色板(浅色/新界面)
INK = QColor("#20252B")
INK_2 = QColor("#68727D")
ACCENT = QColor("#527C70")
RULE = QColor("#E7EBEF")


def _serif(point_size: int, bold: bool = False) -> QFont:
    """衬线标题字体: 规范推荐 Noto Serif SC/Georgia; 不在则系统回落。"""
    f = QFont("Noto Serif SC")
    f.setStyleHint(QFont.Serif)
    f.setPointSizeF(point_size)
    f.setBold(bold)
    return f


def _sans(point_size: int, bold: bool = False) -> QFont:
    f = QFont()
    f.setPointSizeF(point_size)
    f.setBold(bold)
    return f


def export_collection_pdf(lib, win, cid: int):
    row = lib.conn.execute(
        "SELECT name FROM collections WHERE id=?", (cid,)).fetchone()
    if not row:
        return
    name = row["name"]
    st = lib.collection_stats(cid)
    pids = lib.collection_photos_of(cid)
    creator = lib.copyright_defaults_get().get("creator") or ""
    default_path = str(Path.home() / f"画册-{name}.pdf")
    path, _ = QFileDialog.getSaveFileName(
        win, t("导出画册 PDF", "Export album PDF"), default_path,
        "PDF (*.pdf)")
    if not path:
        return

    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QPageSize.A4))       # 595×842pt
    writer.setResolution(150)                          # 1mm ≈ 5.905px
    writer.setPageMargins(QMarginsF(14, 14, 14, 14))   # 规范: 安全边距14mm
    page_w = writer.width()
    page_h = writer.height()
    mm = writer.width() / 210.0                        # 1mm 像素数
    margin = int(14 * mm)
    content_w = page_w - 2 * margin

    p = QPainter(writer)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    page_no = 0

    def _footer():
        nonlocal page_no
        page_no += 1
        p.setFont(_sans(8))
        p.setPen(QColor(INK_2))
        p.drawText(QRectF(margin, page_h - margin + 4 * mm, content_w, 6 * mm),
                   Qt.AlignLeft | Qt.AlignVCenter, "BirdTrace")
        p.drawText(QRectF(margin, page_h - margin + 4 * mm, content_w, 6 * mm),
                   Qt.AlignRight | Qt.AlignVCenter, f"{page_no}")

    def _photo_pixmap(pid):
        r = lib.conn.execute(
            "SELECT path, file_hash FROM photos WHERE id=?", (pid,)).fetchone()
        if not r:
            return None, ""
        pm = None
        if r["path"] and Path(r["path"]).exists():
            pm = QPixmap(r["path"])
        if pm is None or pm.isNull():
            tp = cached_thumbnail(lib.root, r["file_hash"], 1200) or \
                (ensure_thumbnail(lib.root, r["path"], r["file_hash"], 1200)
                 if r["path"] else None)
            if tp:
                pm = QPixmap(str(tp))
        return pm, Path(r["path"]).name if r["path"] else ""

    # ---------- 封面 ----------
    cover_pid = lib.collection_cover(cid)
    pm_cov, _fn = _photo_pixmap(cover_pid) if cover_pid else (None, "")
    p.setPen(QColor(ACCENT))
    p.setFont(_sans(9, bold=True))
    p.drawText(QRectF(margin, margin + 6 * mm, content_w, 6 * mm),
               Qt.AlignLeft | Qt.AlignVCenter,
               t("作品集 · 画册", "COLLECTION · ALBUM"))
    y = margin + 16 * mm
    p.setPen(QColor(INK))
    p.setFont(_serif(26, bold=True))
    p.drawText(QRectF(margin, y, content_w, 14 * mm),
               Qt.AlignLeft | Qt.AlignVCenter, name)
    y += 18 * mm
    span = ""
    if st["first"]:
        a, b = (st["first"] or "")[:10], (st["last"] or "")[:10]
        span = a if a == b else f"{a} — {b}"
    p.setPen(QColor(INK_2))
    p.setFont(_sans(10))
    meta = t(f"{st['n']} 张 · {st['species']} 种", f"{st['n']} photos · "
             f"{st['species']} species")
    if span:
        meta += "  ·  " + span
    p.drawText(QRectF(margin, y, content_w, 7 * mm),
               Qt.AlignLeft | Qt.AlignVCenter, meta)
    y += 12 * mm
    # 封面大图(占满内容宽, 高约 170mm, keep-aspect 裁切居中)
    box = QRectF(margin, y, content_w, 168 * mm)
    if pm_cov is not None and not pm_cov.isNull():
        scaled = pm_cov.scaled(int(box.width()), int(box.height()),
                               Qt.KeepAspectRatioByExpanding,
                               Qt.SmoothTransformation)
        sx = (scaled.width() - box.width()) / 2
        sy = (scaled.height() - box.height()) / 2
        p.save()
        from PySide6.QtGui import QPainterPath
        clip = QPainterPath()
        clip.addRoundedRect(box, 6 * mm, 6 * mm)   # 规范: PDF减圆角
        p.setClipPath(clip)
        p.drawPixmap(int(box.x() - sx), int(box.y() - sy), scaled)
        p.restore()
    else:
        p.setPen(RULE)
        p.setBrush(QColor("#F4F6F8"))
        p.drawRoundedRect(box, 6 * mm, 6 * mm)
    y = box.bottom() + 10 * mm
    if creator:
        p.setPen(QColor(INK))
        p.setFont(_sans(10))
        p.drawText(QRectF(margin, y, content_w, 7 * mm),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   t(f"摄影 · {creator}", f"Photography · {creator}"))
    _footer()
    writer.newPage()

    # ---------- 作品页: 每页 2 张 ----------
    def _caption(pid, box_bottom_y):
        v = lib.conn.execute(
            "SELECT v.eff_code, COALESCE(e.dt_original, p.added_at) ts, "
            "sp.name AS spot_name FROM photos p LEFT JOIN v_records v "
            "ON v.photo_id=p.id AND v.rank=1 LEFT JOIN species s "
            "ON s.code=v.eff_code LEFT JOIN exif e ON e.photo_id=p.id "
            "LEFT JOIN spots sp ON sp.id=p.spot_id WHERE p.id=?",
            (pid,)).fetchone()
        nm = ""
        if v and v["eff_code"]:
            sp = lib.species_info(v["eff_code"])
            if sp:
                nm = sname(sp["cn"], sp["en"])
        line_y = box_bottom_y + 3 * mm
        p.setPen(QColor(INK))
        p.setFont(_sans(11, bold=True))
        p.drawText(QRectF(margin, line_y, content_w, 6 * mm),
                   Qt.AlignLeft | Qt.AlignVCenter, nm or "—")
        sub = (v["ts"] or "")[:10] if v else ""
        if v and v["spot_name"]:
            sub += "  ·  " + v["spot_name"]
        p.setPen(QColor(INK_2))
        p.setFont(_sans(9))
        p.drawText(QRectF(margin, line_y + 6 * mm, content_w, 5 * mm),
                   Qt.AlignLeft | Qt.AlignVCenter, sub)
        return line_y + 12 * mm

    img_h = 96 * mm      # 每页2张: 图96mm+说明12mm+间距
    for i in range(0, len(pids), 2):
        y0 = margin
        for pid in pids[i:i + 2]:
            pm, fn = _photo_pixmap(pid)
            box = QRectF(margin, y0, content_w, img_h)
            if pm is not None and not pm.isNull():
                scaled = pm.scaled(int(box.width()), int(box.height()),
                                   Qt.KeepAspectRatio,
                                   Qt.SmoothTransformation)
                # 居中放盒内(留白式排版)
                px = box.x() + (box.width() - scaled.width()) / 2
                py = box.y() + (box.height() - scaled.height()) / 2
                p.drawPixmap(int(px), int(py), scaled)
            else:
                p.setPen(RULE)
                p.setBrush(QColor("#F4F6F8"))
                p.drawRoundedRect(box, 4 * mm, 4 * mm)
                p.setPen(QColor(INK_2))
                p.setFont(_sans(9))
                p.drawText(box, Qt.AlignCenter,
                           t(f"原图离线：{fn}", f"Original offline: {fn}"))
            y_end = _caption(pid, box.bottom())
            y0 = max(y_end, box.bottom() + 8 * mm) + 4 * mm
        _footer()
        if i + 2 < len(pids):
            writer.newPage()
    p.end()

    QMessageBox.information(
        win, t("导出完成", "Export complete"),
        t(f"画册已导出（{page_no} 页）：\n{path}\n\n"
          "A4 版式可直接打印或分享。",
          f"Album exported ({page_no} pages):\n{path}\n\n"
          "A4 layout, ready to print or share."))
