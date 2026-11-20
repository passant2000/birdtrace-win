# -*- coding: utf-8 -*-
"""年度年鉴 PDF 导出(1.0, 2026-11-20 重做): 走 app/core/yearbook.py 统一
A4 页面模型——与软件内预览同一套排版规则(规范 §3.4), 不再单独维护版式。
导出前可选深浅主题与封面样式(A 满版 / B 上下分栏), 中文字体依赖系统
字体嵌入(QPdfWriter 自带子集嵌入, verify 断言)。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, Qt
from PySide6.QtGui import QPageSize, QPainter, QPdfWriter
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout,
                               QMessageBox, QVBoxLayout)

from ..core import yearbook as YB
from ..i18n import t


class _Options(QDialog):
    """导出选项: 主题(浅/深) + 封面样式(A/B)。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("导出年鉴 PDF", "Export yearbook PDF"))
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.theme = QComboBox()
        self.theme.addItem(t("浅色主题", "Light theme"), "light")
        self.theme.addItem(t("深色主题", "Dark theme"), "dark")
        self.cover = QComboBox()
        self.cover.addItem(t("满版照片（推荐）", "Full-bleed photo"), "full")
        self.cover.addItem(t("上下分栏", "Split cover"), "split")
        form.addRow(t("主题", "Theme"), self.theme)
        form.addRow(t("封面", "Cover"), self.cover)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def theme_key(self) -> str:
        return self.theme.currentData()

    def cover_key(self) -> str:
        return self.cover.currentData()


def build_doc(lib, year: str, pal=None, cover: str = "full",
              max_px: int | None = None) -> YB.YearbookDoc:
    """按年份组装文档(预览与导出共用, 实现在 core/yearbook.build_doc)。"""
    return YB.build_doc(lib, year, pal or YB.LIGHT, cover, max_px)


def write_pdf(lib, year: str, path: str, pal=YB.LIGHT, cover: str = "full"):
    """生成 PDF(不做对话框, 供导出与验证直呼)。返回文档对象。"""
    doc = build_doc(lib, year, pal, cover)
    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setResolution(150)
    writer.setPageMargins(QMarginsF(0, 0, 0, 0))   # 边距在页面模型里画
    k = writer.width() / YB.PAGE_W                  # px per mm
    p = QPainter(writer)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    try:
        for i in range(doc.page_count):
            if i:
                writer.newPage()
            doc.draw(p, i, k)
            QApplication.processEvents()
    finally:
        p.end()
    return doc


def export_yearbook_pdf(lib, win, year: str):
    opts = _Options(win)
    if opts.exec() != QDialog.Accepted:
        return
    pal = YB.DARK if opts.theme_key() == "dark" else YB.LIGHT
    cover = opts.cover_key()
    default_path = str(Path.home() / f"{t('年鉴-', 'Yearbook-')}{year}.pdf")
    path, _ = QFileDialog.getSaveFileName(
        win, t("导出年鉴 PDF", "Export yearbook PDF"), default_path,
        "PDF (*.pdf)")
    if not path:
        return

    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        doc = write_pdf(lib, year, path, YB.DARK if opts.theme_key() == "dark"
                        else YB.LIGHT, cover)
    finally:
        QApplication.restoreOverrideCursor()

    QMessageBox.information(
        win, t("导出完成", "Export complete"),
        t(f"年鉴已导出（{doc.page_count} 页）：\n{path}\n\n"
          f"A4 版式可直接打印或分享。",
          f"Yearbook exported ({doc.page_count} pages):\n{path}\n\n"
          "A4 layout, ready to print or share."))
