# -*- coding: utf-8 -*-
"""iOS风格控件: 开关 / 分段控件 / 徽章 / 缩略图网格项。"""
from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, QPointF, Property, QPropertyAnimation,
                            QRectF, QSize, Qt, Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from . import theme
from ..i18n import t


class ToggleSwitch(QWidget):
    """iOS样式开关。"""
    toggled = Signal(bool)

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.setFixedSize(51, 31)
        self.setCursor(Qt.PointingHandCursor)

    def isChecked(self):
        return self._checked

    def setChecked(self, v: bool, animate=True):
        if v == self._checked:
            return
        self._checked = v
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if v else 0.0)
        if animate:
            self._anim.start()
        else:
            self.setKnob(1.0 if v else 0.0)
        self.toggled.emit(v)

    def mousePressEvent(self, e):
        self.setChecked(not self._checked)

    def getKnob(self):
        return self._pos

    def setKnob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, getKnob, setKnob)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        track = QColor(theme.BLUE) if self._checked else QColor("#E9E9EA")
        # 未选中时轨道随knob微亮, 选中时即BLUE
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 4
        x = 2 + self._pos * (r.width() - d - 4)
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(x + d / 2, r.height() / 2), d / 2, d / 2)
        # 阴影省略, iOS开关本体无描边
        p.end()


class SegmentedControl(QWidget):
    """iOS分段控件。"""
    changed = Signal(int)

    def __init__(self, items: list[str], current: int = 0, parent=None):
        super().__init__(parent)
        self.buttons: list[QPushButton] = []
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        for i, text in enumerate(items):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(30)
            b.clicked.connect(lambda _=False, idx=i: self._on_click(idx))
            lay.addWidget(b, 1)
            self.buttons.append(b)
        self.setCurrent(current)

    def _on_click(self, idx):
        self.setCurrent(idx)
        self.changed.emit(idx)

    def setCurrent(self, idx: int):
        for i, b in enumerate(self.buttons):
            b.setChecked(i == idx)
            if i == idx:
                b.setStyleSheet(
                    f"QPushButton{{background:{theme.CARD};color:{theme.LABEL};font-weight:600;"
                    f"border:none;border-radius:8px;padding:5px 14px;}}")
            else:
                b.setStyleSheet(
                    f"QPushButton{{background:transparent;color:{theme.LABEL_3};"
                    f"border:none;border-radius:8px;padding:5px 14px;}}")

    def currentIndex(self) -> int:
        for i, b in enumerate(self.buttons):
            if b.isChecked():
                return i
        return 0


def make_card(title: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    """白色圆角卡片容器, 返回(卡片, 内容布局)。"""
    card = QFrame()
    card.setObjectName("Card")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(18, 16, 18, 18)
    lay.setSpacing(12)
    if title:
        t = QLabel(title)
        t.setObjectName("CardTitle")
        lay.addWidget(t)
    return card, lay


def badge(text: str, color: str | None = None) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("Badge")
    if color:
        lb.setStyleSheet(f"color:white;background:{color};border-radius:9px;"
                         "font-size:11px;font-weight:700;padding:2px 8px;")
    lb.setAlignment(Qt.AlignCenter)
    return lb


class PhotoGridItem(QWidget):
    """缩略图网格项: 图片 + 角标(已导入/lifer) + 选中框。"""

    def __init__(self, pixmap: QPixmap | None, label: str = "",
                 corner: str | None = None, parent=None, stack: int = 0):
        super().__init__(parent)
        self.setFixedSize(120, 140)
        self.selected = False
        self.pixmap = pixmap
        self.label = label
        self.corner = corner
        self.stack = stack          # 连拍封面: 组内张数(≥2才画 ×N 角标)

    def set_selected(self, v: bool):
        self.selected = v
        self.update()

    def set_pixmap(self, pixmap: QPixmap | None):
        """后台缩略图补齐后更新图片(异步加载场景)。"""
        self.pixmap = pixmap
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(0, 0, 120, 120)
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        p.setClipPath(path)
        if self.pixmap and not self.pixmap.isNull():
            scaled = self.pixmap.scaled(
                120, 120, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = (scaled.width() - 120) / 2
            y = (scaled.height() - 120) / 2
            p.drawPixmap(QPointF(-x, -y), scaled)
        else:
            p.fillRect(rect, QColor(theme.FILL))
        p.setClipping(False)
        if self.corner:
            p.setPen(Qt.NoPen)
            c = QColor(theme.LABEL_3) if self.corner == t("已导入", "Imported") \
                else QColor(theme.ORANGE)
            p.setBrush(c)
            tw = p.fontMetrics().horizontalAdvance(self.corner) + 14
            pr = QPainterPath()
            pr.addRoundedRect(QRectF(120 - tw - 6, 6, tw, 20), 10, 10)
            p.drawPath(pr)
            p.setPen(QColor("white"))
            f = QFont(self.font())
            f.setPointSize(7)
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(120 - tw - 6, 6, tw, 20), Qt.AlignCenter, self.corner)
        if self.stack and self.stack > 1:
            # 连拍封面角标(右下): 叠层小图标 + ×N (0.8-③)
            txt = f"❐ ×{self.stack}"
            f = QFont(self.font())
            f.setPointSize(7)
            f.setBold(True)
            p.setFont(f)
            tw = p.fontMetrics().horizontalAdvance(txt) + 14
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 150))
            pr = QPainterPath()
            pr.addRoundedRect(QRectF(120 - tw - 6, 120 - 20 - 6, tw, 20), 10, 10)
            p.drawPath(pr)
            p.setPen(QColor("white"))
            p.drawText(QRectF(120 - tw - 6, 120 - 20 - 6, tw, 20),
                       Qt.AlignCenter, txt)
        if self.label:
            p.setPen(QColor(theme.LABEL_2))
            f = QFont(self.font())
            f.setPointSize(8)
            p.setFont(f)
            p.drawText(QRectF(0, 122, 120, 16), Qt.AlignCenter,
                       p.fontMetrics().elidedText(self.label, Qt.ElideMiddle, 118))
        if self.selected:
            from PySide6.QtGui import QPen
            pen = QPen(QColor(theme.BLUE), 2.5)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(1, 1, 118, 118), 12, 12)
        p.end()
