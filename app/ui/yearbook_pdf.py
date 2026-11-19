# -*- coding: utf-8 -*-
"""年度年鉴 PDF 导出(1.0主打, 实测反馈10c): A4排版, 设计规范版式——
封面(年份大字衬线+年度最佳1张Hero+汇总行) → 汇总页(数字卡+月度柱自绘) →
年度十八图(每页4张, 图+鸟种名) → 新种九宫格页 → 尾页署名。
与 collection_pdf 同一设计语言(自然绿点缀/衬线标题/页脚页码)。
数据=yearly_report(全复用)。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QPainter, QPainterPath, QPixmap,
                           QPdfWriter)
from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QPageSize
from PySide6.QtWidgets import QFileDialog, QMessageBox

from ..i18n import t, sname
from ..media import cached_thumbnail, ensure_thumbnail
from .collection_pdf import INK, INK_2, ACCENT, RULE, _serif, _sans


def _pm(lib, path, h, size):
    tp = cached_thumbnail(lib.root, h, size) or \
        (ensure_thumbnail(lib.root, path, h, size) if path else None)
    if tp:
        pm = QPixmap(str(tp))
        if not pm.isNull():
            return pm
    return None


def _draw_bar_chart(p: QPainter, rect: QRectF, values: list[int],
                    x_labels: list[str]):
    """PDF 内自绘月度柱(不依赖 QWidget)。"""
    top = max(values) or 1
    n = len(values)
    slot = rect.width() / n
    bw = min(18 * (rect.width() / 600.0), slot * 0.5)
    base = rect.bottom()
    for i, v in enumerate(values):
        bh = (rect.height() - 14) * v / top
        cx = rect.x() + slot * i + slot / 2
        p.setPen(QColor(ACCENT))
        p.setBrush(QColor(ACCENT) if v else QColor("#F0F1F4"))
        p.drawRoundedRect(QRectF(cx - bw / 2, base - 14 - bh, bw, max(bh, 2)),
                          3, 3)
        p.setPen(QColor(INK_2))
        f = p.font()
        f.setPointSizeF(7)
        p.setFont(f)
        p.drawText(QRectF(cx - slot / 2, base - 12, slot, 12),
                   Qt.AlignCenter, x_labels[i])
        if v:
            p.setPen(QColor(INK))
            p.drawText(QRectF(cx - slot / 2, base - 14 - bh - 11, slot, 10),
                       Qt.AlignCenter, str(v))


def export_yearbook_pdf(lib, win, year: str):
    d = lib.yearly_report(year)
    default_path = str(Path.home()
                       / f"{t('年鉴-', 'Yearbook-')}{year}.pdf")
    path, _ = QFileDialog.getSaveFileName(
        win, t("导出年鉴 PDF", "Export yearbook PDF"), default_path,
        "PDF (*.pdf)")
    if not path:
        return

    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setResolution(150)
    writer.setPageMargins(QMarginsF(14, 14, 14, 14))
    page_w, page_h = writer.width(), writer.height()
    mm = page_w / 210.0
    margin = int(14 * mm)
    content_w = page_w - 2 * margin
    creator = lib.copyright_defaults_get().get("creator") or ""
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
                   Qt.AlignLeft | Qt.AlignVCenter,
                   f"BirdTrace · {year}")
        p.drawText(QRectF(margin, page_h - margin + 4 * mm, content_w, 6 * mm),
                   Qt.AlignRight | Qt.AlignVCenter, f"{page_no}")

    # ---------- 封面 ----------
    best = d["best18"]
    p.setPen(QColor(ACCENT))
    p.setFont(_sans(9, bold=True))
    p.drawText(QRectF(margin, margin + 6 * mm, content_w, 6 * mm),
               Qt.AlignLeft | Qt.AlignVCenter,
               t("BIRDTRACE · 年度摄影年鉴", "BIRDTRACE · YEARBOOK"))
    y = margin + 14 * mm
    p.setPen(QColor(INK))
    p.setFont(_serif(48, bold=True))
    p.drawText(QRectF(margin, y, content_w, 26 * mm),
               Qt.AlignLeft | Qt.AlignVCenter, year)
    y += 30 * mm
    p.setPen(QColor(INK_2))
    p.setFont(_sans(10))
    meta = t(f"{d['photos']} 作品 · 新种 {d['new']} · 拍摄 {d['days']} 天",
             f"{d['photos']} photos · {d['new']} new · {d['days']} days")
    p.drawText(QRectF(margin, y, content_w, 7 * mm),
               Qt.AlignLeft | Qt.AlignVCenter, meta)
    y += 12 * mm
    hero = best[0] if best else None
    box = QRectF(margin, y, content_w, 160 * mm)
    if hero:
        pm = _pm(lib, hero["path"], hero["hash"], 1600)
        if pm is not None and not pm.isNull():
            scaled = pm.scaled(int(box.width()), int(box.height()),
                               Qt.KeepAspectRatioByExpanding,
                               Qt.SmoothTransformation)
            sx = (scaled.width() - box.width()) / 2
            sy = (scaled.height() - box.height()) / 2
            p.save()
            clip = QPainterPath()
            clip.addRoundedRect(box, 5 * mm, 5 * mm)
            p.setClipPath(clip)
            p.drawPixmap(int(box.x() - sx), int(box.y() - sy), scaled)
            p.restore()
            p.setPen(QColor(INK))
            p.setFont(_sans(11, bold=True))
            nm = sname(hero["name"], hero.get("en", "")) \
                if hero.get("en") is not None else hero["name"]
            p.drawText(QRectF(margin, box.bottom() + 4 * mm, content_w,
                              7 * mm),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       t(f"封面 · {nm}", f"Cover · {nm}"))
    else:
        p.setPen(RULE)
        p.setBrush(QColor("#F4F6F8"))
        p.drawRoundedRect(box, 5 * mm, 5 * mm)
    if creator:
        p.setPen(QColor(INK))
        p.setFont(_sans(10))
        p.drawText(QRectF(margin, page_h - margin - 10 * mm, content_w,
                          7 * mm),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   t(f"摄影 · {creator}", f"Photography · {creator}"))
    _footer()
    writer.newPage()

    # ---------- 汇总页: 数字行 + 月度柱 ----------
    y = margin
    p.setPen(QColor(INK))
    p.setFont(_serif(16, bold=True))
    p.drawText(QRectF(margin, y, content_w, 10 * mm),
               Qt.AlignLeft | Qt.AlignVCenter,
               t(f"{year} 年度回顾", f"{year} in numbers"))
    y += 14 * mm
    stats = [(d["photos"], t("作品", "Photos")),
             (d["new"], t("新种", "New species")),
             (d["yearbird"], t("年鸟回归", "Returning")),
             (d["days"], t("拍摄天数", "Days")),
             (d["total_species"], t("生涯累计", "Life total"))]
    cw = (content_w - 4 * 6 * mm) / 5
    x = margin
    for val, label in stats:
        card = QRectF(x, y, cw, 24 * mm)
        p.setPen(QColor("#E7EBEF"))
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(card, 3 * mm, 3 * mm)
        p.setPen(QColor(INK))
        f = _sans(17, bold=True)
        p.setFont(f)
        p.drawText(QRectF(x, y + 4 * mm, cw, 9 * mm), Qt.AlignCenter, str(val))
        p.setPen(QColor(INK_2))
        p.setFont(_sans(8))
        p.drawText(QRectF(x, y + 14 * mm, cw, 6 * mm), Qt.AlignCenter, label)
        x += cw + 6 * mm
    y += 32 * mm
    p.setPen(QColor(INK))
    p.setFont(_serif(13, bold=True))
    p.drawText(QRectF(margin, y, content_w, 8 * mm),
               Qt.AlignLeft | Qt.AlignVCenter,
               t("月度出片", "Photos by month"))
    y += 10 * mm
    chart_rect = QRectF(margin, y, content_w, 62 * mm)
    p.setBrush(QColor("#FFFFFF"))
    p.setPen(QColor("#E7EBEF"))
    p.drawRoundedRect(chart_rect, 3 * mm, 3 * mm)
    _draw_bar_chart(p, chart_rect.adjusted(6 * mm, 5 * mm, -6 * mm, -5 * mm),
                    d["monthly"],
                    [f"{m + 1}" for m in range(12)])
    y += 72 * mm
    # 年度之最
    rows = lib.conn.execute(
        "SELECT v.eff_code, s.cn, s.en, COUNT(*) c FROM v_records v "
        "JOIN species s ON s.code=v.eff_code WHERE substr(v.taken_at,1,4)=? "
        "GROUP BY v.eff_code ORDER BY c DESC LIMIT 3", (year,)).fetchall()
    if rows:
        p.setPen(QColor(INK))
        p.setFont(_sans(10))
        txt = "  ·  ".join(f"{sname(r['cn'], r['en'])}×{r['c']}" for r in rows)
        p.drawText(QRectF(margin, y, content_w, 8 * mm),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   t(f"拍摄最多：{txt}", f"Most shot: {txt}"))
        y += 10 * mm
    _footer()
    writer.newPage()

    # ---------- 十八图: 每页 4 张(2×2) ----------
    img_h = 92 * mm
    cap_h = 10 * mm
    cell_gap = 6 * mm
    for start in range(0, len(best), 4):
        page_best = best[start:start + 4]
        for i, r in enumerate(page_best):
            cx = margin + (i % 2) * (content_w / 2 + 3 * mm)
            cy = margin + (i // 2) * (img_h + cap_h + cell_gap)
            w2 = content_w / 2 - 3 * mm
            box = QRectF(cx, cy, w2, img_h)
            pm = _pm(lib, r["path"], r["hash"], 900)
            if pm is not None and not pm.isNull():
                scaled = pm.scaled(int(box.width()), int(box.height()),
                                   Qt.KeepAspectRatio,
                                   Qt.SmoothTransformation)
                px = box.x() + (box.width() - scaled.width()) / 2
                py = box.y() + (box.height() - scaled.height()) / 2
                p.drawPixmap(int(px), int(py), scaled)
            else:
                p.setPen(RULE)
                p.setBrush(QColor("#F4F6F8"))
                p.drawRoundedRect(box, 3 * mm, 3 * mm)
            nm = sname(r["name"], r.get("en", "")) \
                if r.get("en") is not None else r["name"]
            p.setPen(QColor(INK))
            p.setFont(_sans(9, bold=True))
            p.drawText(QRectF(cx, box.bottom() + 2 * mm, w2, 5 * mm),
                       Qt.AlignLeft | Qt.AlignVCenter, nm)
            p.setPen(QColor(INK_2))
            p.setFont(_sans(8))
            p.drawText(QRectF(cx, box.bottom() + 7 * mm, w2, 4 * mm),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       (r["taken_at"] or "")[:10])
        _footer()
        if start + 4 < len(best):
            writer.newPage()

    # ---------- 新种九宫格页 ----------
    if d["grid"]:
        writer.newPage()
        p.setPen(QColor(INK))
        p.setFont(_serif(16, bold=True))
        p.drawText(QRectF(margin, margin, content_w, 10 * mm),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   t(f"年度新种 · {d['new']} 个",
                     f"New species · {d['new']}"))
        cell = (content_w - 2 * 6 * mm) / 3
        gh = cell * 0.75
        for i, g in enumerate(d["grid"][:9]):
            cx = margin + (i % 3) * (cell + 6 * mm)
            cy = margin + 14 * mm + (i // 3) * (gh + 12 * mm)
            box = QRectF(cx, cy, cell, gh)
            pm = _pm(lib, g["path"], g["hash"], 700)
            if pm is not None and not pm.isNull():
                scaled = pm.scaled(int(box.width()), int(box.height()),
                                   Qt.KeepAspectRatioByExpanding,
                                   Qt.SmoothTransformation)
                sx = (scaled.width() - box.width()) / 2
                sy = (scaled.height() - box.height()) / 2
                p.save()
                clip = QPainterPath()
                clip.addRoundedRect(box, 3 * mm, 3 * mm)
                p.setClipPath(clip)
                p.drawPixmap(int(box.x() - sx), int(box.y() - sy), scaled)
                p.restore()
            else:
                p.setPen(RULE)
                p.setBrush(QColor("#F4F6F8"))
                p.drawRoundedRect(box, 3 * mm, 3 * mm)
            p.setPen(QColor(INK))
            p.setFont(_sans(9, bold=True))
            p.drawText(QRectF(cx, box.bottom() + 1.5 * mm, cell, 5 * mm),
                       Qt.AlignLeft | Qt.AlignVCenter, g["cn"])
            p.setPen(QColor(INK_2))
            p.setFont(_sans(8))
            p.drawText(QRectF(cx, box.bottom() + 6.5 * mm, cell, 4 * mm),
                       Qt.AlignLeft | Qt.AlignVCenter, g["date"])
        _footer()
    p.end()

    QMessageBox.information(
        win, t("导出完成", "Export complete"),
        t(f"年鉴已导出（{page_no} 页）：\n{path}\n\nA4 版式可直接打印或分享。",
          f"Yearbook exported ({page_no} pages):\n{path}\n\n"
          "A4 layout, ready to print or share."))
