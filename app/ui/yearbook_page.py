# -*- coding: utf-8 -*-
"""年度年鉴页(1.0, 2026-11-20 按设计稿重做): 软件内直接预览 **A4 页面**
——与导出的 PDF 同一套排版(app/core/yearbook.py, 规范 §3.4 单一边界),
支持适应宽度/缩放预览; 页头选年份与导出(导出可选深浅主题+封面样式)。

数据全部真实: yearly_report / year_species / year_geo / year_timeline,
不虚构位置、不重复照片填格。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .. import theme
from ..core import yearbook as YB
from ..i18n import t


class _Preview(QWidget):
    """A4 页面竖向排布的预览画布(按毫米坐标系绘制, 与 PDF 同源)。"""

    GAP = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc: YB.YearbookDoc | None = None
        self.fit = True
        self.factor = 1.0
        self.setMinimumHeight(400)

    def set_doc(self, doc: YB.YearbookDoc | None):
        self.doc = doc
        self._relayout()

    def set_zoom(self, fit: bool, factor: float = 1.0):
        self.fit, self.factor = fit, factor
        self._relayout()

    def _k(self) -> float:
        if self.fit:
            return max(self.width(), 200) / YB.PAGE_W
        return 3.7795 * self.factor          # A4 @96dpi × 缩放

    def _ph(self) -> float:
        return YB.PAGE_H * self._k()

    def _relayout(self):
        n = self.doc.page_count if self.doc else 1
        h = int(n * (self._ph() + self.GAP) + self.GAP)
        self.setMinimumHeight(h)
        self.updateGeometry()
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fit:
            self._relayout()

    def sizeHint(self) -> QSize:
        n = self.doc.page_count if self.doc else 1
        return QSize(int(YB.PAGE_W * self._k()),
                     int(n * (self._ph() + self.GAP) + self.GAP))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.fillRect(self.rect(), QColor("#E9ECEF"))
        if self.doc is None:
            return
        k = self._k()
        pw, ph = YB.PAGE_W * k, YB.PAGE_H * k
        x = (self.width() - pw) / 2
        for i in range(self.doc.page_count):
            y = self.GAP + i * (ph + self.GAP)
            p.save()
            p.translate(x, y)
            self.doc.draw(p, i, k)
            p.restore()
            p.setPen(QColor("#C7CDD4"))
            p.drawRect(int(x), int(y), int(pw), int(ph))


class YearbookPage(QWidget):
    def __init__(self, lib, win):
        super().__init__()
        self.lib = lib
        self.win = win
        self._year = None
        self._doc = None
        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(12)

        from ..theme.widgets import PageHeader
        head = QHBoxLayout()
        self.title = PageHeader(t("年度年鉴", "Yearbook"))
        head.addWidget(self.title, 1)
        self.year_combo = QComboBox()
        self.year_combo.setCursor(Qt.PointingHandCursor)
        self.year_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        self.title.add_action(self.year_combo)
        self.zoom_combo = QComboBox()
        self.zoom_combo.setCursor(Qt.PointingHandCursor)
        for label, data in ((t("适应宽度", "Fit width"), ("fit", 1.0)),
                            ("75%", (False, 0.75)), ("100%", (False, 1.0)),
                            ("125%", (False, 1.25))):
            self.zoom_combo.addItem(label, data)
        self.zoom_combo.currentIndexChanged.connect(self._zoom_changed)
        self.title.add_action(self.zoom_combo)
        self.pdf_btn = QPushButton(t("导出年鉴 PDF…", "Export yearbook PDF…"))
        self.pdf_btn.setObjectName("Primary")
        self.pdf_btn.setCursor(Qt.PointingHandCursor)
        self.pdf_btn.clicked.connect(self._export_pdf)
        self.title.add_action(self.pdf_btn)
        lay.addLayout(head)

        self.hint = QLabel(t("下方为 A4 页面预览，与导出的 PDF 排版一致（浅色主题）。",
                             "A4 page preview below — identical layout to the "
                             "exported PDF (light theme)."))
        self.hint.setObjectName("Hint")
        lay.addWidget(self.hint)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.preview = _Preview()
        self.scroll.setWidget(self.preview)
        lay.addWidget(self.scroll, 1)

    def on_page_hidden(self):
        pass

    # ---------- 数据 ----------
    def _years(self) -> list[str]:
        rows = self.lib.conn.execute(
            "SELECT DISTINCT substr(COALESCE(e.dt_original, p.added_at),1,4) y "
            "FROM photos p LEFT JOIN exif e ON e.photo_id=p.id "
            "WHERE y IS NOT NULL AND y<>'' ORDER BY y DESC").fetchall()
        return [r["y"] for r in rows]

    def refresh(self):
        years = self._years()
        cur = self.year_combo.currentData()
        if [self.year_combo.itemData(i) for i in range(
                self.year_combo.count())] != years:
            self.year_combo.blockSignals(True)
            self.year_combo.clear()
            for y in years:
                self.year_combo.addItem(t(f"{y} 年", str(y)), y)
            if cur in years:
                self.year_combo.setCurrentIndex(
                    self.year_combo.findData(cur))
            self.year_combo.blockSignals(False)
        self._year = self.year_combo.currentData() or (
            years[0] if years else None)
        if not self._year:
            self.title.set_title(t("年度年鉴", "Yearbook"))
            self._doc = None
            self.preview.set_doc(None)
            self.hint.setText(t("还没有照片——导入并识别后，这里生成你的年度年鉴",
                                "Import and identify photos to build your "
                                "yearbook here"))
            return
        self.title.set_title(t(f"年度年鉴 · {self._year}",
                               f"Yearbook · {self._year}"))
        self._doc = YB.build_doc(self.lib, self._year, YB.LIGHT, "full",
                                 max_px=512)
        self.preview.set_doc(self._doc)
        self.hint.setText(t(
            f"共 {self._doc.page_count} 页 · A4 210×297mm · "
            f"与导出的 PDF 排版一致（页头可缩放预览）",
            f"{self._doc.page_count} pages · A4 210×297mm · same layout as "
            f"the exported PDF (use the zoom control to inspect)"))

    def _zoom_changed(self, _i):
        fit, factor = self.zoom_combo.currentData() or (True, 1.0)
        self.preview.set_zoom(fit, factor)

    # ---------- 动作 ----------
    def _export_pdf(self):
        if not self._year:
            return
        from .yearbook_pdf import export_yearbook_pdf
        export_yearbook_pdf(self.lib, self.win, self._year)
