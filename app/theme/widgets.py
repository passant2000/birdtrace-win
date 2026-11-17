# -*- coding: utf-8 -*-
"""iOS风格控件: 开关 / 分段控件 / 徽章 / 缩略图网格项。"""
from __future__ import annotations

from PySide6.QtCore import (QDate, QEasingCurve, QEvent, QPointF, Property,
                            QPropertyAnimation, QRectF, QSize, Qt, Signal,
                               QPoint, QRect)
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QPainter,
                           QPainterPath, QPixmap)
from PySide6.QtWidgets import (QCalendarWidget, QComboBox, QDialog,
                               QHeaderView,
                               QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget, QLayout)

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
    """缩略图网格项: 图片 + 角标(已导入/lifer) + 选中框。
    tile=缩略图边长(0.8.5档位, 默认120=历史尺寸; 标签/角标随tile缩放)。"""

    def __init__(self, pixmap: QPixmap | None, label: str = "",
                 corner: str | None = None, parent=None, stack: int = 0,
                 tile: int = 120):
        super().__init__(parent)
        self.tile = max(48, int(tile))
        self.selected = False
        self.pixmap = pixmap
        self.label = label
        self.corner = corner
        self.stack = stack          # 连拍封面: 组内张数(≥2才画 ×N 角标)
        self._lh = max(18, round(self.tile / 6))    # 标签带高
        self.setFixedSize(self.tile, self.tile + self._lh)
        self._disp = self._scaled_disp()

    def _scaled_disp(self):
        """预缩放显示图(0.8.5: 信纸式**整图可见**——用户要Windows超大图标
        那种横竖图都不裁; 旧paintEvent每次重采样→只在set时做一次,
        传入更大缓存(如512)自动降到tile)。"""
        if self.pixmap and not self.pixmap.isNull():
            return self.pixmap.scaled(self.tile, self.tile,
                                      Qt.KeepAspectRatio,
                                      Qt.SmoothTransformation)
        return None

    def set_selected(self, v: bool):
        self.selected = v
        self.update()

    def set_pixmap(self, pixmap: QPixmap | None):
        """后台缩略图补齐后更新图片(异步加载场景)。"""
        self.pixmap = pixmap
        self._disp = self._scaled_disp()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        s = self.tile
        rect = QRectF(0, 0, s, s)
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        p.setClipPath(path)
        # 信纸式整图可见(0.8.5用户实测: Windows超大图标式, 横图竖图都
        # 不裁切): 短边方向留主题底色, 照片完整居中
        p.fillRect(rect, QColor(theme.FILL))
        if self._disp:
            p.drawPixmap(QPointF((s - self._disp.width()) / 2,
                                 (s - self._disp.height()) / 2), self._disp)
        p.setClipping(False)
        bh = max(20, s // 8)         # 角标胶囊高(随档位)
        if self.corner:
            p.setPen(Qt.NoPen)
            c = QColor(theme.LABEL_3) if self.corner == t("已导入", "Imported") \
                else QColor(theme.ORANGE)
            p.setBrush(c)
            f = QFont(self.font())
            f.setPointSize(max(7, s // 22))
            f.setBold(True)
            p.setFont(f)
            tw = p.fontMetrics().horizontalAdvance(self.corner) + 14
            pr = QPainterPath()
            pr.addRoundedRect(QRectF(s - tw - 6, 6, tw, bh), bh / 2, bh / 2)
            p.drawPath(pr)
            p.setPen(QColor("white"))
            p.drawText(QRectF(s - tw - 6, 6, tw, bh), Qt.AlignCenter, self.corner)
        if self.stack and self.stack > 1:
            # 连拍封面角标(右下): 叠层小图标 + ×N (0.8-③)
            txt = f"❐ ×{self.stack}"
            f = QFont(self.font())
            f.setPointSize(max(7, s // 22))
            f.setBold(True)
            p.setFont(f)
            tw = p.fontMetrics().horizontalAdvance(txt) + 14
            yb = s - bh - 6
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 150))
            pr = QPainterPath()
            pr.addRoundedRect(QRectF(s - tw - 6, yb, tw, bh), bh / 2, bh / 2)
            p.drawPath(pr)
            p.setPen(QColor("white"))
            p.drawText(QRectF(s - tw - 6, yb, tw, bh), Qt.AlignCenter, txt)
        if self.label:
            p.setPen(QColor(theme.LABEL_2))
            f = QFont(self.font())
            f.setPointSize(max(8, s // 20))
            p.setFont(f)
            p.drawText(QRectF(0, s + 1, s, self._lh - 2), Qt.AlignCenter,
                       p.fontMetrics().elidedText(self.label, Qt.ElideMiddle,
                                                  s - 2))
        if self.selected:
            from PySide6.QtGui import QPen
            pen = QPen(QColor(theme.BLUE), 2.5)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(1, 1, s - 2, s - 2), 12, 12)
        p.end()


# ---------------- 网格档位(0.8.5: Windows超大图标式缩略图大小) ----------------
GRID_TIERS = [132, 180, 240, 320]


def grid_tile_of(lib) -> int:
    """全局网格档位: 库设置grid_tile; 非法/未设回退132(≈0.8.4视觉)。"""
    try:
        v = int((lib.get_setting("grid_tile", "") or "").strip() or 0)
        if v in GRID_TIERS:
            return v
    except Exception:
        pass
    return 132


def make_grid_tier_control(lib, on_change):
    """档位切换控件(小/中/大/特大): 写库持久化+回调刷新所在页面。
    注意setCurrent不发changed(SegmentedControl既有坑), 初值手动对齐。"""
    seg = SegmentedControl([t("小", "S"), t("中", "M"),
                            t("大", "L"), t("特大", "XL")])

    def _apply(idx: int):
        lib.set_setting("grid_tile", str(GRID_TIERS[idx]))
        on_change()

    seg.changed.connect(_apply)
    seg.setCurrent(GRID_TIERS.index(grid_tile_of(lib)))
    seg.setToolTip(t("缩略图大小（照片网格全局通用，自动记忆）",
                     "Thumbnail size (shared across photo grids, "
                     "remembered)"))
    return seg


# ---------------- 日期选择(主题化, 年份/月份都用下拉) ----------------
_EN_MONTHS = ["January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December"]


class _DatePopup(QDialog):
    """日期弹层: 年份/月份下拉 + 日网格(纯主题配色)。

    QDateEdit原生日历弹层在深色主题下导航栏配色不跟随(月份下拉黑底、
    年份只能上下箭头点), 用户2026-11-05反馈; 这里自绘弹层:
    年份、月份都是一点直达的下拉, 日网格走当前主题。"""

    date_selected = Signal(QDate)

    def __init__(self, date: QDate, edit):
        super().__init__(edit, Qt.Popup)
        self.setObjectName("DatePopup")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        lo, hi = edit.minimumDate(), edit.maximumDate()
        y_lo = lo.year() if lo.isValid() else 1970
        y_hi = hi.year() if hi.isValid() else QDate.currentDate().year() + 1
        # 下拉年份范围收敛到"照片可能的年份"(QDateEdit默认1752~9999
        # 会塞八千多项): 前80年~后10年, 并尊重显式日期范围
        y_lo = max(y_lo, date.year() - 80)
        y_hi = min(y_hi, date.year() + 10)
        y_lo = min(y_lo, date.year())
        y_hi = max(y_hi, date.year())
        self.year_combo = QComboBox()
        for y in range(y_hi, y_lo - 1, -1):
            self.year_combo.addItem(str(y), y)
        self.year_combo.setCurrentIndex(
            max(0, self.year_combo.findData(date.year())))
        self.year_combo.setMinimumWidth(88)
        self.month_combo = QComboBox()
        for m in range(1, 13):
            self.month_combo.addItem(t(f"{m}月", _EN_MONTHS[m - 1]), m)
        self.month_combo.setCurrentIndex(date.month() - 1)
        self.month_combo.setMinimumWidth(96)
        prev_btn = QPushButton("‹")
        next_btn = QPushButton("›")
        for b in (prev_btn, next_btn):
            b.setFixedWidth(32)
            b.setCursor(Qt.PointingHandCursor)
        bar.addWidget(self.year_combo)
        bar.addWidget(self.month_combo)
        bar.addStretch(1)
        bar.addWidget(prev_btn)
        bar.addWidget(next_btn)
        lay.addLayout(bar)

        self.cal = QCalendarWidget()
        self.cal.setNavigationBarVisible(False)
        self.cal.setGridVisible(False)
        self.cal.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        # 原生星期表头是QCalendarWidget自绘的黑条(QSS改不动) → 关闭,
        # 用_week_header()自绘的7个标签跟随主题(2026-11-06)
        self.cal.setHorizontalHeaderFormat(
            QCalendarWidget.HorizontalHeaderFormat.NoHorizontalHeader)
        if lo.isValid():
            self.cal.setMinimumDate(lo)
        if hi.isValid():
            self.cal.setMaximumDate(hi)
        hv = self.cal.findChild(QHeaderView)
        if hv is not None:
            hv.hide()          # 原生黑条表头彻底隐藏(见_week_header)
        self.cal.setCurrentPage(date.year(), date.month())
        lay.addLayout(self._week_header())
        lay.addWidget(self.cal)
        self.setStyleSheet(
            f"QDialog#DatePopup{{background:{theme.CARD};"
            f"border:1px solid {theme.CARD_BORDER};border-radius:12px;}}"
            f"QCalendarWidget QWidget{{background:{theme.CARD};"
            f"color:{theme.LABEL};}}"
            f"QCalendarWidget QAbstractItemView{{background:{theme.CARD};"
            f"color:{theme.LABEL};outline:none;"
            f"selection-background-color:{theme.BLUE};"
            f"selection-color:white;}}"
            f"QCalendarWidget QAbstractItemView:disabled{{"
            f"color:{theme.LABEL_3};}}"
            f"QCalendarWidget QTableView{{background:{theme.CARD};"
            f"color:{theme.LABEL};selection-background-color:{theme.BLUE};}}"
            f"QCalendarWidget QHeaderView::section{{background:{theme.CARD};"
            f"color:{theme.LABEL_2};border:none;padding:4px 2px;"
            f"font-size:11px;}}"
            f"QCalendarWidget QToolButton{{background:transparent;"
            f"color:{theme.LABEL};border:none;padding:4px 8px;}}")
        self.year_combo.currentIndexChanged.connect(self._sync_page)
        self.month_combo.currentIndexChanged.connect(self._sync_page)
        prev_btn.clicked.connect(lambda: self._step(-1))
        next_btn.clicked.connect(lambda: self._step(1))
        self.cal.clicked.connect(self._pick)
        self.cal.activated.connect(self._pick)

    def _week_header(self) -> QHBoxLayout:
        """自绘星期表头(周一开头由firstDayOfWeek决定, 周末红色)。"""
        zh = ["一", "二", "三", "四", "五", "六", "日"]  # i18n:ok (走t配对en)
        en = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        first = self.cal.firstDayOfWeek().value   # Qt.Monday=1
        row = QHBoxLayout()
        row.setSpacing(0)
        row.setContentsMargins(0, 0, 0, 2)
        for i in range(7):
            idx = (first - 1 + i) % 7            # 0=周一 ... 6=周日
            lab = QLabel(t(zh[idx], en[idx]))
            color = theme.RED if idx >= 5 else theme.LABEL_2
            lab.setAlignment(Qt.AlignCenter)
            lab.setStyleSheet(
                f"color:{color};font-size:11px;background:transparent;")
            row.addWidget(lab, 1)
        return row

    def _sync_page(self, *_):
        self.cal.setCurrentPage(int(self.year_combo.currentData()),
                                int(self.month_combo.currentData()))

    def _step(self, delta: int):
        y = int(self.year_combo.currentData())
        m = int(self.month_combo.currentData()) + delta
        if m < 1:
            m, y = 12, y - 1
        elif m > 12:
            m, y = 1, y + 1
        self.year_combo.setCurrentIndex(max(0, self.year_combo.findData(y)))
        self.month_combo.setCurrentIndex(m - 1)

    def _pick(self, qdate: QDate):
        self.date_selected.emit(qdate)
        self.accept()


class ThemedDateEdit(QPushButton):
    """日期输入(自绘按钮式, 非QDateEdit)。

    为什么不用QDateEdit: 只要QSS里出现QDateEdit选择器, Qt会把内部
    输入框宽度压成1px→日期文字完全不可见(2026-11-06用户实测0.8.0
    日期框全空白)。改用QPushButton自绘: 配色完全跟主题、点击弹
    _DatePopup(年份/月份都是下拉)。

    API与QDateEdit兼容: date()/setDate()/dateChanged/minimumDate/
    setMinimumDate/maximumDate/setMaximumDate/setDateRange/
    setSpecialValueText/setDisplayFormat/setCalendarPopup。
    """

    dateChanged = Signal(QDate)

    def __init__(self, date: QDate | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("DateEdit")
        self.setCursor(Qt.PointingHandCursor)
        self._date = QDate(date) if date is not None else QDate.currentDate()
        self._min = QDate(1752, 9, 14)
        self._max = QDate(9999, 12, 31)
        self._special = ""
        self._apply_style()
        self.clicked.connect(self._open_popup)
        self._refresh()

    def _apply_style(self):
        self.setStyleSheet(
            f"QPushButton#DateEdit{{background:{theme.FILL};"
            f"color:{theme.LABEL};border:none;border-radius:10px;"
            f"padding:9px 14px;font-size:14px;text-align:left;}}"
            f"QPushButton#DateEdit:hover{{background:{theme.HOVER};}}"
            f"QPushButton#DateEdit:pressed{{background:{theme.PRESSED};}}"
            f"QPushButton#DateEdit:focus{{border:2px solid {theme.BLUE};"
            f"padding:7px 12px;}}")

    def _refresh(self):
        if self._special and self._date == self._min:
            self.setText(self._special)
        else:
            self.setText(self._date.toString("yyyy-MM-dd"))
        self.setMinimumWidth(120)

    # ---- QDateEdit兼容API ----
    def date(self) -> QDate:
        return QDate(self._date)

    def setDate(self, d: QDate):
        if not isinstance(d, QDate):
            d = QDate(d)
        if not d.isValid():
            return
        if self._min.isValid() and d < self._min:
            d = self._min
        if self._max.isValid() and d > self._max:
            d = self._max
        if d == self._date:
            self._refresh()
            return
        self._date = QDate(d)
        self._refresh()
        self.dateChanged.emit(QDate(self._date))

    def minimumDate(self) -> QDate:
        return QDate(self._min)

    def maximumDate(self) -> QDate:
        return QDate(self._max)

    def setMinimumDate(self, d: QDate):
        self._min = QDate(d)

    def setMaximumDate(self, d: QDate):
        self._max = QDate(d)

    def setDateRange(self, lo: QDate, hi: QDate):
        self._min, self._max = QDate(lo), QDate(hi)
        self.setDate(self._date)

    def setSpecialValueText(self, text: str):
        self._special = text
        self._refresh()

    def setDisplayFormat(self, _fmt: str):
        pass                      # 固定 yyyy-MM-dd 展示

    def setCalendarPopup(self, _on: bool):
        pass                      # 兼容旧调用; 弹层始终自绘

    def calendarPopup(self) -> bool:
        return False

    def setButtonSymbols(self, *_a):
        pass                      # 兼容旧调用; 没有上下箭头

    def lineEdit(self):
        return None               # 兼容旧调用(自绘控件无内部输入框)

    # ---- 弹层 ----
    def _open_popup(self):
        popup = _DatePopup(self._date, self)
        popup.date_selected.connect(self._on_picked)
        popup.setAttribute(Qt.WA_DeleteOnClose)
        popup.adjustSize()
        g = self.mapToGlobal(self.rect().bottomLeft())
        screen = QGuiApplication.screenAt(g)
        if screen is not None:
            avail = screen.availableGeometry()
            if g.y() + popup.height() > avail.bottom():
                g.setY(self.mapToGlobal(self.rect().topLeft()).y()
                       - popup.height())
            if g.x() + popup.width() > avail.right():
                g.setX(avail.right() - popup.width())
        popup.move(g)
        self._popup = popup          # 持有引用防GC(非exec的弹出层)
        popup.show()

    def _on_picked(self, qdate: QDate):
        self.setDate(qdate)


class FlowLayout(QLayout):
    """流式布局: 子项按宽度自动换行(鸟种胶囊/标签云用)。
    Qt经典FlowLayout样例的PySide移植, 精简为只管item几何。"""

    def __init__(self, parent=None, margin=0, spacing=8):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self._spacing = spacing
        self._items: list = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def addStretch(self, stretch=0):
        from PySide6.QtWidgets import QSpacerItem
        self.addItem(QSpacerItem(0, 0))   # 流式布局里占位无宽, 兼容QBox风格调用

    def expandingDirections(self):
        return Qt.Orientations(Qt.Horizontal)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do_layout(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        x, y = rect.x() + m.left(), rect.y() + m.top()
        line_h = 0
        right = rect.right() - m.right()
        for it in self._items:
            hint = it.sizeHint()
            nx = x + hint.width() + self._spacing
            if nx - self._spacing > right and line_h > 0:
                x = rect.x() + m.left()
                y = y + line_h + self._spacing
                nx = x + hint.width() + self._spacing
                line_h = 0
            if not test_only:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x = nx
            line_h = max(line_h, hint.height())
        m2 = self.contentsMargins()
        return y + line_h + m2.bottom() - rect.y()
