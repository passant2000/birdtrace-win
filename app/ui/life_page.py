# -*- coding: utf-8 -*-
"""观鸟生涯页(UI重设计c5): 个人观鸟编年史, 吸纳原成就页(stats_page 已删)。

四Tab: 总览(档案头卡/数字卡/里程碑/生涯之最/年度卡/热力图) ·
时间线(lifer_feed 新种收录流=鸟种+首见日期+拍摄地点, 可筛可导CSV) ·
足迹(region_id 口径省级 choropleth + 鸟点足迹卡) ·
徽章(24徽章6组/年度增长图/装备榜[过机镜别名+同别名聚合]/出片时段——
自 stats_page 纯搬家)。
"""
from __future__ import annotations

import html as _html

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QScrollArea,
                               QStackedWidget, QVBoxLayout, QWidget)

from .. import theme
from ..core.camera_aliases import alias_of
from ..i18n import t, sname
from ..media import cached_thumbnail, ensure_thumbnail

# (emoji, 名称(中,英对), 目标) 名称存(中,英)对, 展示时t(*对)以支持运行时切语言
SPECIES_MILESTONES = [
    ("🐣", ("初出茅庐", "Fledgling"), 10), ("🐤", ("渐入佳境", "Warming up"), 50),
    ("🐦", ("观鸟能手", "Century club"), 100), ("🦜", ("百鸟齐鸣", "Dawn chorus"), 200),
    ("🦚", ("生态图鉴", "Field guide"), 300), ("🦅", ("五百飞羽", "Five hundred feathers"), 500),
    ("👑", ("千种传奇", "Thousand-species legend"), 1000),
]
PHOTO_MILESTONES = [("📸", ("快门一百", "First hundred shots"), 100),
                    ("🎞️", ("千张时刻", "Thousand-shot moment"), 1000),
                    ("🎬", ("五千连拍", "Five thousand burst"), 5000),
                    ("🗂️", ("万张俱乐部", "Ten K club"), 10000)]
SPOT_MILESTONES = [("📍", ("五点连线", "Five hotspots"), 5),
                   ("🧭", ("十五驿站", "Fifteen waypoints"), 15),
                   ("🗺️", ("三十要冲", "Thirty crossroads"), 30),
                   ("🌍", ("五十据点", "Fifty outposts"), 50)]
STREAK_MILESTONES = [("🔥", ("三日之约", "Three-day streak"), 3),
                     ("🗓️", ("七日同行", "Seven-day streak"), 7),
                     ("⭐", ("卅日铁人", "Thirty-day ironman"), 30)]
RAPTOR_MILESTONES = [("🦉", ("夜行猎手", "Night hunter"), 5),
                     ("🦅", ("鹰隼之友", "Raptor ally"), 15),
                     ("👑", ("猛禽收藏家", "Raptor collector"), 30)]
WATERBIRD_MILESTONES = [("🦆", ("水畔常客", "Waterside regular"), 5),
                        ("🏓", ("浪里白条", "Wave rider"), 15),
                        ("🏝️", ("湿地专家", "Wetland expert"), 30)]

# 热力图色阶(GREEN系5档, GitHub贡献图式; 色板不含新颜色, 取主题绿系明度)
HEAT_STEPS = [(0, None), (1, "#D7EEDD"), (3, "#A8E0BC"), (6, "#6FC992"),
              (10, "#34C759"), (20, "#1F9D4C")]


class BarChart(QWidget):
    """年度新增(蓝) + 累计(浅蓝)柱状图(自 stats_page 搬家)。
    兼容 hour_stats 的 {hour,total} 序列与 year_summary 的 {year,new,total}。"""

    def __init__(self):
        super().__init__()
        self.series: list[dict] = []
        self._x_month_mode = False
        self.setMinimumHeight(240)

    def set_series(self, series: list[dict], x_month_mode: bool = False):
        """x_month_mode: 12个横轴=月份(标"1月"…), 缺省=小时/年份原样。"""
        self.series = series
        self._x_month_mode = x_month_mode
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        pad_l, pad_b, pad_t = 44, 34, 16
        if not self.series:
            p.setPen(QColor(theme.LABEL_3))
            p.drawText(self.rect(), Qt.AlignCenter, t("暂无数据", "No data yet"))
            p.end()
            return
        # {hour,total}形态(出片时段): 无累计层, 单柱
        hours_mode = "total" in self.series[0] and "new" not in self.series[0]
        max_total = max(s["total"] for s in self.series) or 1
        raw_step = max(1, int(max_total / 4 + 0.999))
        mag = 1
        while raw_step > 10:
            raw_step = (raw_step + 9) // 10
            mag *= 10
        step = {1: 1, 2: 2, 3: 5, 4: 5}.get(raw_step, 10) * mag
        top = step * 4
        n = len(self.series)
        slot = (w - pad_l - 16) / n
        bw = min(38, slot * 0.55)
        p.setPen(QColor(theme.LABEL_3))
        f = p.font()
        f.setPointSize(8)
        p.setFont(f)
        for i in range(5):
            y = pad_t + (h - pad_t - pad_b) * i / 4
            val = top * (4 - i) / 4
            p.drawLine(int(pad_l), int(y), int(w - 12), int(y))
            p.drawText(QRectF(0, y - 8, pad_l - 6, 16), Qt.AlignRight | Qt.AlignVCenter,
                       f"{val:g}")
        for i, s in enumerate(self.series):
            cx = pad_l + slot * i + slot / 2
            if hours_mode:
                th = (h - pad_t - pad_b) * s["total"] / top
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(theme.BLUE))
                p.drawRoundedRect(QRectF(cx - bw / 2, h - pad_b - th, bw, th),
                                  3, 3)
                # 数值标注(反馈9: 简陋→可读): 柱顶直接标数值
                if s["total"]:
                    p.setPen(QColor(theme.LABEL))
                    p.drawText(QRectF(cx - slot / 2, h - pad_b - th - 16,
                                      slot, 14),
                               Qt.AlignCenter, str(s["total"]))
                p.setPen(QColor(theme.LABEL_2))
                lab = str(s.get("hour", i))
                if self._x_month_mode:
                    lab = t(f"{s.get('hour', i)}月", str(s.get("hour", i)))
                p.drawText(QRectF(cx - slot / 2, h - pad_b + 4, slot, 16),
                           Qt.AlignCenter, lab)
                continue
            th = (h - pad_t - pad_b) * s["total"] / top
            nh = (h - pad_t - pad_b) * s["new"] / top
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#B8D6FF"))
            p.drawRoundedRect(QRectF(cx - bw / 2, h - pad_b - th, bw, th), 4, 4)
            p.setBrush(QColor(theme.BLUE))
            p.drawRoundedRect(QRectF(cx - bw / 2, h - pad_b - nh, bw, nh), 4, 4)
            p.setPen(QColor(theme.LABEL_2))
            p.drawText(QRectF(cx - slot / 2, h - pad_b + 4, slot, 16),
                       Qt.AlignCenter, s["year"])
            p.setPen(QColor(theme.LABEL))
            p.drawText(QRectF(cx - slot / 2, h - pad_b - nh - 20, slot, 16),
                       Qt.AlignCenter, f"+{s['new']}")
        p.end()


def _number_card(num, label: str, color: str) -> QFrame:
    card = QFrame()
    card.setObjectName("Card")
    v = QVBoxLayout(card)
    v.setContentsMargins(20, 14, 20, 14)
    n = QLabel(f"{num}")
    n.setStyleSheet(f"font-size:34px;font-weight:800;color:{color};background:transparent;")
    l = QLabel(label)
    l.setStyleSheet(f"font-size:12px;color:{theme.LABEL_2};background:transparent;")
    v.addWidget(n)
    v.addWidget(l)
    return card


class _Badge(QWidget):
    """成就徽章: 解锁=彩色+日期; 未解锁=灰+进度条(自 stats_page 搬家)。
    实测反馈9: set_click(回调)=点击看徽章背后的证据(照片/鸟种/鸟点)。"""

    def __init__(self, emoji: str, name: str, target: int, cur: int,
                 unlock_date: str | None, parent=None):
        super().__init__(parent)
        self.setFixedSize(150, 132)
        self.emoji, self.name, self.target = emoji, name, target
        self.cur, self.unlock_date = cur, unlock_date
        self.done = cur >= target
        self._click = None

    def set_click(self, fn):
        self._click = fn
        if fn and self.done:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(t("点击查看达成证据", "Click to see the evidence"))

    def mousePressEvent(self, e):
        if self._click and self.done:
            self._click()
        super().mousePressEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(4, 4, self.width() - 8, self.height() - 8)
        path = QPainterPath()
        path.addRoundedRect(r, 14, 14)
        p.setClipPath(path)
        if self.done:
            p.fillRect(r, QColor(theme.CARD))
            p.setPen(QPen(QColor(theme.ORANGE), 2))
        else:
            p.fillRect(r, QColor(theme.CARD))
            p.setPen(QPen(QColor("#D9D9DE"), 1))
        p.drawPath(path)
        p.setClipping(False)
        em = p.font()
        ef = QFont()
        ef.setPixelSize(30)
        p.setFont(ef)
        if self.done:
            p.setPen(QColor(theme.LABEL))
        else:
            p.setPen(QColor("#B9B9BF"))
        p.drawText(QRectF(0, 10, self.width(), 40), Qt.AlignCenter, self.emoji)
        f = QFont()
        f.setPixelSize(13)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.LABEL) if self.done else QColor(theme.LABEL_3))
        p.drawText(QRectF(6, 52, self.width() - 12, 18), Qt.AlignCenter, self.name)
        sf = QFont()
        sf.setPixelSize(11)
        p.setFont(sf)
        if self.done:
            p.setPen(QColor(theme.GREEN))
            txt = self.unlock_date or t("已达成", "Achieved")
            p.drawText(QRectF(6, 70, self.width() - 12, 16), Qt.AlignCenter, txt)
        else:
            p.setPen(QColor(theme.LABEL_3))
            p.drawText(QRectF(6, 68, self.width() - 12, 14), Qt.AlignCenter,
                       f"{self.cur} / {self.target}")
            bw = self.width() - 48
            by, bh = 92, 7
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#E6E6EB"))
            p.drawRoundedRect(QRectF(24, by, bw, bh), 3, 3)
            frac = 0.0 if self.target <= 0 else min(1.0, self.cur / self.target)
            if frac > 0:
                p.setBrush(QColor(theme.BLUE))
                p.drawRoundedRect(QRectF(24, by, max(6.0, bw * frac), bh), 3, 3)
        p.end()


def _badge_row(items, cur: int, unlock_fn) -> list[_Badge]:
    return [_Badge(em, t(*nm), target, cur, unlock_fn(target))
            for em, nm, target in items]


class HeatMap(QWidget):
    """观鸟热力图(UI重设计c5): 近12个月 日×照片数, GitHub贡献图式。
    数据=lib.day_counts() 的 {YYYY-MM-DD: n}; hover 显示日期与张数。"""

    CELL = 13
    GAP = 3

    def __init__(self, counts: dict[str, int]):
        super().__init__()
        import datetime
        self._counts = counts
        self._today = datetime.date.today()
        # 从本周一回溯53周, 对齐GitHub式周列
        self._start = self._today - __import__("datetime").timedelta(
            days=self._today.weekday() + 7 * 52)
        self._cells: list[tuple[int, int, str, int]] = []   # x,y,date,n
        weeks = 53
        w = weeks * (self.CELL + self.GAP) + 10
        h = 7 * (self.CELL + self.GAP) + 10
        self.setFixedSize(w, h)
        self.setMouseTracking(True)

    def _cell_at(self, pos):
        for x, y, d, n in self._cells:
            if x <= pos.x() <= x + self.CELL and y <= pos.y() <= y + self.CELL:
                return d, n
        return None, 0

    def mouseMoveEvent(self, e):
        d, n = self._cell_at(e.position().toPoint())
        if d:
            self.setToolTip(t(f"{d} · {n} 张", f"{d} · {n} photos"))
        else:
            self.setToolTip("")
        super().mouseMoveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        import datetime
        self._cells = []
        d0 = self._start
        col = 0
        while d0 <= self._today:
            for dow in range(7):
                d = d0 + datetime.timedelta(days=dow)
                if d > self._today:
                    break
                key = d.isoformat()
                n = self._counts.get(key, 0)
                color = QColor(theme.FILL)
                for th, c in HEAT_STEPS:
                    if th and n >= th:
                        color = QColor(c)
                x = 5 + col * (self.CELL + self.GAP)
                y = 5 + dow * (self.CELL + self.GAP)
                p.setBrush(color)
                p.drawRoundedRect(QRectF(x, y, self.CELL, self.CELL), 3, 3)
                self._cells.append((x, y, key, n))
            d0 = d0 + datetime.timedelta(days=7)
            col += 1
        p.end()


class LifePage(QWidget):
    def __init__(self, lib, win):
        super().__init__()
        self.lib = lib
        self.win = win
        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        from ..theme.widgets import PageHeader, SegmentedControl
        self.header = PageHeader(t("观鸟生涯", "Birding life"))
        head = QHBoxLayout()
        head.addWidget(self.header, 1)
        self.ebird_btn = QPushButton(t("导出eBird记录", "Export eBird records"))
        self.ebird_btn.setCursor(Qt.PointingHandCursor)
        self.ebird_btn.clicked.connect(self._export_ebird)
        self.header.add_action(self.ebird_btn)
        self.report_btn = QPushButton(t("年度报告…", "Annual report…"))
        self.report_btn.setObjectName("Primary")
        self.report_btn.setCursor(Qt.PointingHandCursor)
        self.report_btn.clicked.connect(self._open_report)
        self.header.add_action(self.report_btn)
        self.list_btn = QPushButton(t("导出生涯清单…", "Export life list…"))
        self.list_btn.setCursor(Qt.PointingHandCursor)
        self.list_btn.setToolTip(t(
            "把生涯全部鸟种导出为 CSV（编号/中文名/学名/英文名/首见日期/"
            "地点/罕见度档），供 eBird/记录中心/自建台账使用",
            "Export your life list as CSV (no/CN/Latin/EN/first date/"
            "spot/rarity) for eBird, checklists or your own records"))
        self.list_btn.clicked.connect(self._export_life_list)
        self.header.add_action(self.list_btn)
        lay.addLayout(head)

        self.seg = SegmentedControl([t("总览", "Overview"), t("时间线", "Timeline"),
                                     t("足迹", "Footprints"), t("徽章", "Badges")])
        self.seg.changed.connect(self._tab_changed)
        lay.addWidget(self.seg)
        # 时间线Tab筛选行(实测反馈6修复): 只建一次——原实现每次refresh
        # 重建控件, 打一个字/选一个鸟点就被清零, 搜索与下拉"不能用"
        self._tl_filter_host = self._make_tl_filters()

        self.stack = QStackedWidget()
        self.tabs: list[QScrollArea] = []
        for _ in range(4):
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.NoFrame)
            content = QWidget()
            cv = QVBoxLayout(content)
            cv.setContentsMargins(0, 0, 16, 24)
            cv.setSpacing(14)
            sc._cv = cv
            sc.setWidget(content)
            self.stack.addWidget(sc)
            self.tabs.append(sc)
        lay.addWidget(self.stack, 1)

    def _tab_changed(self, idx: int):
        self.stack.setCurrentIndex(idx)
        self.refresh()

    def on_page_hidden(self):
        pass

    # ---------- 数据小件 ----------
    def _span(self) -> tuple[str, str, str]:
        """(最早日期, 最新日期, 跨度文案)。口径=exif回落added_at。"""
        row = self.lib.conn.execute(
            "SELECT MIN(COALESCE(e.dt_original, p.added_at)) a, "
            "  MAX(COALESCE(e.dt_original, p.added_at)) b "
            "FROM photos p LEFT JOIN exif e ON e.photo_id=p.id").fetchone()
        a, b = (row["a"] or "")[:10], (row["b"] or "")[:10]
        span = ""
        if a and b:
            import datetime
            try:
                days = (datetime.date.fromisoformat(b)
                        - datetime.date.fromisoformat(a)).days
                span = t(f"{a} 起 · {days / 365.25:.1f} 年",
                         f"since {a} · {days / 365.25:.1f} yr")
            except ValueError:
                span = f"{a} ~ {b}"
        return a, b, span

    def _milestone(self, n: int) -> tuple[str, float]:
        """下一百位种进度 → (文案, 进度0~1)。n<100 距第100种。"""
        if n <= 0:
            return t("收录第 1 种鸟，从这里开始", "Your first species starts here"), 0.0
        nxt = (n // 100 + 1) * 100
        return t(f"已收录 {n} 种 · 下一站 #{nxt}，还差 {nxt - n} 种",
                 f"{n} species · next milestone #{nxt}, {nxt - n} to go"), \
            (n % 100) / 100.0

    # ---------- 刷新 ----------
    def refresh(self):
        sc = self.tabs[self.stack.currentIndex()]
        cv = sc._cv
        host = getattr(self, "_tl_filter_host", None)
        while cv.count():
            it = cv.takeAt(0)
            w = it.widget() if it else None
            if w is not None and w is not host:
                w.setParent(None)
                w.deleteLater()
        _a, _b, span = self._span()
        self.header.set_subtitle(span or t("导入照片后开始记录你的生涯",
                                           "Import photos to start your life list"))
        idx = self.stack.currentIndex()
        if idx == 0:
            self._build_overview(cv)
        elif idx == 1:
            self._build_timeline(cv)
        elif idx == 2:
            self._build_footprint(cv)
        else:
            self._build_badges(cv)
        cv.addStretch(1)

    # ---------- Tab1 总览 ----------
    def _build_overview(self, cv: QVBoxLayout):
        s = self.lib.stats_summary()
        import datetime
        ys = self.lib.year_summary(datetime.date.today().strftime('%Y'))
        ach = self.lib.achievements_summary()

        # 档案头卡: 创作者 + 起点 + 首尾种
        head_card = QFrame()
        head_card.setObjectName("Card")
        hv = QHBoxLayout(head_card)
        hv.setContentsMargins(20, 16, 20, 16)
        hv.setSpacing(16)
        creator = self.lib.copyright_defaults_get().get("creator") or \
            t("观鸟者", "Birder")
        _a, _b, _span = self._span()
        left = QVBoxLayout()
        who = QLabel(creator)
        who.setStyleSheet(f"font-size:22px;font-weight:800;color:{theme.LABEL};"
                          "background:transparent;")
        left.addWidget(who)
        sub = QLabel(_span or t("生涯待开始", "Life list yet to begin"))
        sub.setObjectName("Hint")
        left.addWidget(sub)
        hv.addLayout(left, 1)
        lifers = self.lib.lifers()
        if lifers:
            for lab_txt, li in ((t("生涯第 1 种", "First species"), lifers[0]),
                                (t("最新收录", "Latest"), lifers[-1])):
                box = QVBoxLayout()
                cap = QLabel(lab_txt)
                cap.setObjectName("Hint")
                nm = QLabel(sname(li["cn"], li["en"]))
                nm.setStyleSheet(f"font-size:14px;font-weight:700;"
                                 f"color:{theme.BLUE};background:transparent;")
                nm.setCursor(Qt.PointingHandCursor)
                code = li["code"]
                nm.mousePressEvent = lambda e, c=code: self.win.open_species(c)
                box.addWidget(cap)
                box.addWidget(nm)
                wrap = QWidget()
                wrap.setLayout(box)
                hv.addWidget(wrap)
        cv.addWidget(head_card)

        # 6 数字卡(自stats_page搬家)
        row = QHBoxLayout()
        row.setSpacing(12)
        for val, label, color in (
                (s['species'], t("生涯鸟种", "Life species"), theme.GREEN),
                (s['photos'], t("照片总数", "Total photos"), theme.BLUE),
                (ach['spots'], t("鸟点数", "Hotspots"), theme.GREEN),
                (ach['shooting_days'], t("拍摄天数", "Days birding"), theme.BLUE),
                (ys['new'], t("今年新种", "New this year"), theme.ORANGE),
                (ys['yearbird'], t("今年回归（年鸟）", "Returning (year birds)"), "#8A9455")):
            row.addWidget(_number_card(val, label, color))
        host = QWidget()
        host.setLayout(row)
        cv.addWidget(host)

        # 下一里程碑卡
        m_txt, m_frac = self._milestone(s['species'])
        m_card = QFrame()
        m_card.setObjectName("Card")
        mv = QVBoxLayout(m_card)
        mv.setContentsMargins(20, 14, 20, 14)
        mv.setSpacing(8)
        m_lab = QLabel(t("🎯 生涯里程碑", "🎯 Life milestone"))
        m_lab.setObjectName("CardTitle")
        mv.addWidget(m_lab)
        m_val = QLabel(m_txt)
        m_val.setStyleSheet(f"font-size:15px;font-weight:600;color:{theme.LABEL};"
                            "background:transparent;")
        mv.addWidget(m_val)
        from PySide6.QtWidgets import QProgressBar
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(m_frac * 100))
        bar.setFixedHeight(8)
        bar.setTextVisible(False)
        # 坑(PLAN.md#4): 非f-string续行里 }} 不折叠——整段保持单花括号字面
        bar.setStyleSheet("QProgressBar{background:" + theme.FILL +
                          ";border-radius:4px;}"
                          "QProgressBar::chunk{background:" + theme.GREEN +
                          ";border-radius:4px;}")
        mv.addWidget(bar)
        cv.addWidget(m_card)

        # 生涯之最卡
        best = self._life_best()
        if best:
            cv.addWidget(best)

        # 年度卡行
        years = self.lib.conn.execute(
            "SELECT DISTINCT substr(COALESCE(e.dt_original, p.added_at),1,4) y "
            "FROM photos p LEFT JOIN exif e ON e.photo_id=p.id "
            "WHERE y IS NOT NULL AND y<>'' ORDER BY y DESC").fetchall()
        if years:
            ycard = QFrame()
            ycard.setObjectName("Card")
            yv = QVBoxLayout(ycard)
            yv.setContentsMargins(18, 14, 18, 16)
            yv.setSpacing(10)
            yl = QLabel(t("年度档案", "Yearly archive"))
            yl.setObjectName("CardTitle")
            yv.addWidget(yl)
            yrow = QHBoxLayout()
            yrow.setSpacing(10)
            for yr in years:
                y = yr["y"]
                ysummary = self.lib.year_summary(y)
                n_ph = self.lib.day_counts(y)
                total = sum(n_ph.values())
                box = QFrame()
                box.setStyleSheet(f"background:{theme.FILL};border-radius:10px;")
                bv = QVBoxLayout(box)
                bv.setContentsMargins(12, 8, 12, 8)
                ybig = QLabel(y)
                ybig.setStyleSheet(f"font-size:18px;font-weight:800;"
                                   f"color:{theme.LABEL};background:transparent;")
                bv.addWidget(ybig)
                ymeta = QLabel(t(f"{ysummary['new']} 新种 · {total} 张",
                                 f"{ysummary['new']} new · {total} photos"))
                ymeta.setObjectName("Hint")
                bv.addWidget(ymeta)
                ybtn = QPushButton(t("年报…", "Report…"))
                ybtn.setCursor(Qt.PointingHandCursor)
                ybtn.clicked.connect(lambda _=False, yy=y: self._open_report(yy))
                bv.addWidget(ybtn)
                yrow.addWidget(box)
            yrow.addStretch(1)
            yv.addLayout(yrow)
            cv.addWidget(ycard)

        # 热力图卡
        cv.addWidget(self._heat_card())

    def _heat_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)
        v.setContentsMargins(20, 16, 20, 16)
        h = QLabel(t("观鸟热力图  ·  近 12 个月每天拍摄张数",
                     "Birding heatmap  ·  photos per day, last 12 months"))
        h.setObjectName("CardTitle")
        v.addWidget(h)
        import datetime
        year = str(self._today().year)
        v.addWidget(HeatMap(self.lib.day_counts()))
        hint = QLabel(t("颜色越深=拍得越多", "Darker = more photos"))
        hint.setObjectName("Hint")
        v.addWidget(hint)
        return card

    def _today(self):
        import datetime
        return datetime.date.today()

    def _life_best(self) -> QFrame | None:
        """生涯之最卡: 拍摄最多TOP3/罕见度之王/美学冠军/最常去鸟点/
        最忙一天/最早一拍。全部现成数据。"""
        items: list[tuple[str, str]] = []
        # 拍摄最多物种TOP3
        rows = self.lib.conn.execute(
            "SELECT v.eff_code, s.cn, s.en, COUNT(*) c FROM v_records v "
            "JOIN species s ON s.code=v.eff_code "
            "GROUP BY v.eff_code ORDER BY c DESC LIMIT 3").fetchall()
        if rows:
            txt = "  ·  ".join(
                f"{sname(r['cn'], r['en'])}×{r['c']}" for r in rows)
            items.append((t("📸 拍摄最多", "📸 Most photographed"), txt))
        # 罕见度之王(rarity_score 最高; 地区=当前默认地区)
        region = self.lib.get_setting("default_region", "GLOBAL")
        if region and region != "GLOBAL":
            from ..core.prior_hint import get_hint, tier_display
            hint = get_hint()
            best_code, best_val, best_tier = None, -1.0, ""
            for li in self.lib.lifers():
                sc = hint.rarity_score(li["code"], region)
                if sc is not None and sc > best_val:
                    best_val, best_code = sc, li["code"]
                    best_tier = tier_display(hint.rarity_tier(li["code"], region) or "")
            if best_code is not None:
                sp = self.lib.species_info(best_code)
                items.append((t("👑 罕见度之王", "👑 Rarity king"),
                              f"{sname(sp['cn'], sp['en'])} · "
                              f"{best_tier} {best_val:.1f}/10"))
        # 美学冠军(缩略图可点开查看器)
        arow = self.lib.conn.execute(
            "SELECT p.id, p.path, p.file_hash, p.aesthetic FROM photos p "
            "WHERE p.aesthetic IS NOT NULL "
            "ORDER BY p.aesthetic DESC LIMIT 1").fetchone()
        # 最常去鸟点
        srow = self.lib.conn.execute(
            "SELECT sp.name, COUNT(*) c FROM photos p "
            "JOIN spots sp ON sp.id=p.spot_id GROUP BY sp.id "
            "ORDER BY c DESC LIMIT 1").fetchone()
        if srow:
            items.append((t("📍 最常去鸟点", "📍 Top spot"),
                          f"{srow['name']} ×{srow['c']}"))
        # 最忙一天(按当日新种数)
        brows = self.lib.conn.execute(
            "SELECT substr(MIN(v.taken_at),1,10) d, COUNT(DISTINCT v.eff_code) c "
            "FROM v_records v GROUP BY substr(v.taken_at,1,10) "
            "ORDER BY c DESC LIMIT 1").fetchone()
        if brows and brows["c"] and brows["d"]:
            items.append((t("🔥 最忙一天", "🔥 Biggest day"),
                          t(f"{brows['d']} · 新种 {brows['c']} 个",
                            f"{brows['d']} · {brows['c']} new species")))
        if not items and arow is None:
            return None
        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)
        v.setContentsMargins(18, 14, 18, 16)
        v.setSpacing(10)
        hl = QLabel(t("生涯之最", "Life highlights"))
        hl.setObjectName("CardTitle")
        v.addWidget(hl)
        body = QHBoxLayout()
        # 美学冠军缩略图
        if arow:
            pic = QLabel()
            pic.setFixedSize(96, 72)
            pic.setAlignment(Qt.AlignCenter)
            pic.setCursor(Qt.PointingHandCursor)
            pic.setStyleSheet(f"background:{theme.FILL};border-radius:8px;")
            tp = cached_thumbnail(self.lib.root, arow["file_hash"], 192) \
                or ensure_thumbnail(self.lib.root, arow["path"],
                                    arow["file_hash"], 192)
            if tp:
                pm = QPixmap(str(tp))
                if not pm.isNull():
                    pic.setPixmap(pm.scaled(
                        pic.size(), Qt.KeepAspectRatioByExpanding,
                        Qt.SmoothTransformation))
            tip = t(f"美学冠军 ✨ {float(arow['aesthetic']):.1f}/10（点击查看）",
                    f"Aesthetic champion ✨ {float(arow['aesthetic']):.1f}/10 (click)")
            pic.setToolTip(tip)
            pid = arow["id"]

            def _open_champ(_e, _pid=pid):
                from .viewer import PhotoViewer
                PhotoViewer(self.lib, self.win, _pid, [_pid]).exec()
            pic.mousePressEvent = _open_champ
            body.addWidget(pic)
        kv = QVBoxLayout()
        kv.setSpacing(6)
        for k, val in items:
            rowt = QLabel(f"<b style='color:{theme.LABEL}'>{k}</b>　"
                          f"<span style='color:{theme.LABEL_2}'>"
                          f"{_html.escape(val)}</span>")
            rowt.setWordWrap(True)
            rowt.setStyleSheet("background:transparent;font-size:13px;")
            kv.addWidget(rowt)
        body.addLayout(kv, 1)
        v.addLayout(body)
        return card

    # ---------- Tab2 时间线(新种收录流) ----------
    def _build_timeline(self, cv: QVBoxLayout):
        import datetime
        year_now = str(self._today().year)
        s = self.lib.stats_summary()
        m_txt, _f = self._milestone(s['species'])
        banner = QLabel(f"🎯 {m_txt}")
        banner.setStyleSheet(f"background:{theme.FILL};border-radius:10px;"
                             f"padding:10px 14px;font-size:13px;font-weight:600;"
                             f"color:{theme.LABEL_2};")
        cv.addWidget(banner)

        feed = self.lib.lifer_feed()
        # 持久筛选行(控件只建一次, 见 __init__)
        cv.addWidget(self._tl_filter_host)
        self._sync_tl_filter_items(feed)

        # 过滤
        q = (self._tl_search.text() or "").strip().lower()
        yf = self._tl_year.currentData()
        sf = self._tl_spot.currentData()
        spot_name = ""
        if sf is not None:
            # test3反馈"点选鸟点啥也不显示": 旧=在生涯首见流里按首见照片
            # 地点筛(首见在别处的种全消失→几乎必空); 改=换口径成该点
            # 收录流(该点拍到的每种鸟+在该点的首见), db.spot_lifer_feed。
            spot_name = self._tl_spot.currentText()
            feed = self.lib.spot_lifer_feed(sf)
            self._sync_tl_filter_items(feed, spots=False)  # 年份选项集换口径
            card = self._spot_drill_card(sf, spot_name)
            if card is not None:
                cv.addWidget(card)   # 下钻: 去过几次/鸟种清单(可点)
        years = sorted({(li["first_at"] or "")[:4] for li in feed
                        if li["first_at"]}, reverse=True)
        if q:
            matches = [li for li in feed if self._tl_match(li, q)]
            if len(matches) == 1:
                # 下钻: 该鸟种所有拍摄日期+鸟点(可点开图)
                cv.addWidget(self._species_drill_card(matches[0]["code"]))
        shown = 0
        for y in years:
            group = [li for li in feed if (li["first_at"] or "")[:4] == y]
            if yf and y != yf:
                continue
            if q:
                group = [li for li in group if self._tl_match(li, q)]
            if not group:
                continue
            if spot_name:
                # 鸟点口径下列的不是"新种"是该点收录, 照片数也是全库口径
                # 不再展示, 头部文案如实换掉
                head = QPushButton(t(f"▾ {y} · 收录 {len(group)} 种",
                                     f"▾ {y} · {len(group)} species"))
            else:
                n_ph_year = sum(self.lib.day_counts(y).values())
                head = QPushButton(
                    t(f"▾ {y} · 新种 {len(group)} · 照片 {n_ph_year}",
                      f"▾ {y} · {len(group)} new · {n_ph_year} photos"))
            head.setCursor(Qt.PointingHandCursor)
            head.setStyleSheet(f"text-align:left;background:{theme.FILL};"
                               "border-radius:10px;padding:8px 12px;"
                               f"font-weight:700;color:{theme.LABEL};")
            list_w = QWidget()
            lv = QVBoxLayout(list_w)
            lv.setContentsMargins(0, 4, 0, 4)
            lv.setSpacing(6)
            for li in group:
                lv.addWidget(self._lifer_row(li))
            head.clicked.connect(lambda _=False, w=list_w: w.setVisible(
                not w.isVisible()))
            cv.addWidget(head)
            cv.addWidget(list_w)
            shown += len(group)
        if not shown:
            if spot_name:
                empty = QLabel(t(f"{spot_name} 还没有已识别的鸟种",
                                 f"No identified species at {spot_name} yet"))
            else:
                empty = QLabel(t("还没有收录——识别完成后这里按时间记录你的新种",
                                 "Nothing yet — new species will appear here "
                                 "after recognition"))
            empty.setObjectName("Hint")
            cv.addWidget(empty)

    # ---------- 时间线Tab: 筛选行(持久) + 下钻卡(实测反馈6) ----------
    @staticmethod
    def _tl_match(li: dict, q: str) -> bool:
        """鸟种搜索匹配(test3反馈"只支持中文"): 中/英/学名/拼音全拼/
        拼音首字母全命中——与鸟种库搜索(species_overview)同口径。"""
        return (q in (li["cn"] or "").lower()
                or q in (li["en"] or "").lower()
                or q in (li["sci"] or "").lower()
                or q in (li["cn_pinyin"] or "").lower()
                or q in (li["cn_initials"] or "").lower())

    def _make_tl_filters(self) -> QWidget:
        """筛选行控件只建一次; 选项在 _sync_tl_filter_items 里重填。"""
        host = QWidget()
        frow = QHBoxLayout(host)
        frow.setContentsMargins(0, 0, 0, 0)
        frow.setSpacing(8)
        self._tl_year = QComboBox()
        self._tl_year.addItem(t("全部年份", "All years"), None)
        self._tl_spot = QComboBox()
        self._tl_spot.addItem(t("全部鸟点", "All spots"), None)
        self._tl_search = QLineEdit()
        self._tl_search.setPlaceholderText(
            t("搜鸟种名（中文/拼音/英文/学名）…",
              "Search species (CN / pinyin / EN / Latin)…"))
        self._tl_search.setFixedWidth(200)
        self._tl_search.setClearButtonEnabled(True)
        self._tl_year.currentIndexChanged.connect(lambda _i: self.refresh())
        self._tl_spot.currentIndexChanged.connect(lambda _i: self.refresh())
        self._tl_search.textChanged.connect(lambda _t: self.refresh())
        frow.addWidget(self._tl_year)
        frow.addWidget(self._tl_spot)
        frow.addWidget(self._tl_search, 1)
        return host

    def _sync_tl_filter_items(self, feed: list[dict], spots: bool = True):
        """重填年份/鸟点选项, 保留当前选择(blockSignals防重入)。
        spots=False=只重填年份(选了鸟点后feed换口径, 年份选项集跟着换,
        鸟点选项不动防递归)。"""
        years = sorted({(li["first_at"] or "")[:4] for li in feed
                        if li["first_at"]}, reverse=True)
        cur_y = self._tl_year.currentData()
        self._tl_year.blockSignals(True)
        self._tl_year.clear()
        self._tl_year.addItem(t("全部年份", "All years"), None)
        self._tl_year.addItems(years)
        if cur_y:
            idx = self._tl_year.findData(cur_y)
            self._tl_year.setCurrentIndex(idx if idx >= 0 else 0)
        self._tl_year.blockSignals(False)
        if not spots:
            return
        cur_s = self._tl_spot.currentData()
        self._tl_spot.blockSignals(True)
        self._tl_spot.clear()
        self._tl_spot.addItem(t("全部鸟点", "All spots"), None)
        for sp in self.lib.spots_overview():
            self._tl_spot.addItem(sp["name"], sp["id"])
        if cur_s is not None:
            idx = self._tl_spot.findData(cur_s)
            self._tl_spot.setCurrentIndex(idx if idx >= 0 else 0)
        self._tl_spot.blockSignals(False)

    def _spot_drill_card(self, spot_id: int, spot_name: str) -> QFrame | None:
        """选鸟点→概览卡: 到访天数/首末日期/鸟种清单胶囊(点=看该种明细)。"""
        v = self.lib.spot_visits(spot_id)
        if not v["species"]:
            return None
        card = QFrame()
        card.setObjectName("Card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 14)
        lay.setSpacing(6)
        hl = QLabel(t(
            f"📍 {spot_name} · 到访 {v['days']} 天 · 鸟种 {len(v['species'])} 种"
            + (f" · 首次 {v['first_at']}" if v["first_at"] else ""),
            f"📍 {spot_name} · {v['days']} visit day(s) · "
            f"{len(v['species'])} species"
            + (f" · first {v['first_at']}" if v["first_at"] else "")))
        hl.setObjectName("CardTitle")
        hl.setWordWrap(True)
        lay.addWidget(hl)
        sub = QLabel(t(
            f"{v['first_at']} ~ {v['last_at']}（点下面的鸟种看它的拍摄记录）",
            f"{v['first_at']} ~ {v['last_at']} (click a species below to "
            "see its records)"))
        sub.setObjectName("Hint")
        lay.addWidget(sub)
        from ..theme.widgets import FlowLayout   # 一级模块两个点(三个点
        # =超出顶层包, test3抓出的潜伏bug: 选有鸟种的点→此行ImportError
        # →refresh中途断→时间线整页空白)
        chips_host = QWidget()
        flow = FlowLayout(chips_host, spacing=6)
        flow.setContentsMargins(0, 0, 0, 0)
        for it in v["species"][:40]:
            chip = QLabel(f"{sname(it['cn'], it['en'])} ×{it['n']}")
            chip.setStyleSheet(
                f"background:{theme.FILL};border-radius:10px;"
                "padding:3px 10px;font-size:12px;"
                f"color:{theme.LABEL};")
            chip.setCursor(Qt.PointingHandCursor)
            code = it["code"]
            nm = it["cn"] or it["en"] or ""

            def _go(_e, _nm=nm):
                self._tl_search.setText(_nm)
                self.refresh()
            chip.mousePressEvent = _go
            flow.addWidget(chip)
        lay.addWidget(chips_host)
        return card

    def _species_drill_card(self, code: str) -> QFrame:
        """搜中唯一命中→该鸟种明细卡: 每次拍摄(日期+鸟点), 点=开当日首图。"""
        sp = self.lib.species_info(code)
        rows = self.lib.species_sightings(code)
        spots_n = len({r["spot_name"] for r in rows if r["spot_name"]})
        card = QFrame()
        card.setObjectName("Card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 14)
        lay.setSpacing(6)
        nm = sname(sp["cn"], sp["en"]) if sp else code
        hl = QLabel(t(
            f"🔎 {nm} · {len(rows)} 次拍摄 · 到过 {spots_n} 个鸟点",
            f"🔎 {nm} · {len(rows)} shot(s) · {spots_n} spot(s)"))
        hl.setObjectName("CardTitle")
        hl.setWordWrap(True)
        lay.addWidget(hl)
        for r in rows[:60]:
            line = QLabel(t(
                f"{r['d']} · {r['spot_name'] or '未挂鸟点'}（点击查看）",
                f"{r['d']} · {r['spot_name'] or 'no spot'} (click to view)"))
            line.setStyleSheet(f"font-size:13px;color:{theme.LABEL_2};"
                               "background:transparent;padding:1px 0;")
            line.setCursor(Qt.PointingHandCursor)
            pid = r["pid"]

            def _open(_e, _pid=pid):
                from .viewer import PhotoViewer
                if _pid:
                    PhotoViewer(self.lib, self.win, _pid, [_pid]).exec()
            line.mousePressEvent = _open
            lay.addWidget(line)
        if len(rows) > 60:
            more = QLabel(t(f"…其余 {len(rows) - 60} 次见时间线",
                            f"… {len(rows) - 60} more in the timeline"))
            more.setObjectName("Hint")
            lay.addWidget(more)
        return card

    def _lifer_row(self, li: dict) -> QFrame:
        row = QFrame()
        row.setObjectName("Card")
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 8, 14, 8)
        h.setSpacing(12)
        no = QLabel(f"#{li['no']}")
        no.setStyleSheet(f"font-size:16px;font-weight:800;color:{theme.ORANGE};"
                         "background:transparent;min-width:44px;")
        h.addWidget(no)
        pic = QLabel()
        pic.setFixedSize(56, 56)
        pic.setAlignment(Qt.AlignCenter)
        pic.setStyleSheet(f"background:{theme.FILL};border-radius:8px;")
        if li["photo_id"]:
            r = self.lib.conn.execute(
                "SELECT path, file_hash FROM photos WHERE id=?",
                (li["photo_id"],)).fetchone()
            if r and r["path"]:
                tp = cached_thumbnail(self.lib.root, r["file_hash"], 112) \
                    or ensure_thumbnail(self.lib.root, r["path"],
                                        r["file_hash"], 112)
                if tp:
                    pm = QPixmap(str(tp))
                    if not pm.isNull():
                        pic.setPixmap(pm.scaled(
                            pic.size(), Qt.KeepAspectRatioByExpanding,
                            Qt.SmoothTransformation))
        h.addWidget(pic)
        mid = QVBoxLayout()
        name = QLabel(f"{sname(li['cn'], li['en'])}  "
                      f"<span style='color:{theme.LABEL_3};font-style:italic'>"
                      f"{_html.escape(li['sci'] or '')}</span>")
        name.setStyleSheet(f"font-size:15px;font-weight:700;color:{theme.LABEL};"
                           "background:transparent;")
        mid.addWidget(name)
        place = li["spot_name"] or li["region"] or \
            t("未挂鸟点", "no spot")
        meta = QLabel(t(f"{(li['first_at'] or '')[:10]} · 📍{place}",
                        f"{(li['first_at'] or '')[:10]} · 📍{place}"))
        meta.setObjectName("Hint")
        mid.addWidget(meta)
        h.addLayout(mid, 1)
        if li["year_bird"]:
            from ..theme.widgets import badge
            h.addWidget(badge(t("🌿年鸟", "🌿 Year bird"), theme.GREEN))
        row.setCursor(Qt.PointingHandCursor)
        code = li["code"]
        row.mousePressEvent = lambda e, c=code: self.win.open_species(c)
        return row

    # ---------- Tab3 足迹 ----------
    def _build_footprint(self, cv: QVBoxLayout):
        provs = self.lib.province_species_counts()
        spots = self.lib.spots_overview()
        years = self.lib.conn.execute(
            "SELECT COUNT(DISTINCT substr(COALESCE(e.dt_original, "
            "p.added_at),1,4)) c FROM photos p LEFT JOIN exif e "
            "ON e.photo_id=p.id").fetchone()["c"]
        n_prov = len([r for r in provs if r[0] and r[0].startswith("CN-")])
        summary = QLabel(t(
            f"足迹：{n_prov} 个省级地区 · {len(spots)} 个鸟点 · {years} 个年份",
            f"Footprints: {n_prov} provinces · {len(spots)} spots · "
            f"{years} years"))
        summary.setStyleSheet(f"font-size:15px;font-weight:600;"
                              f"color:{theme.LABEL};background:transparent;")
        cv.addWidget(summary)

        # 省级足迹地图直接内嵌(实测反馈8): 自绘choropleth, 省名+数字
        # 直接标注在图上, 悬浮看详情; 免WebEngine轻加载
        if provs:
            from .china_map_widget import ChinaMapWidget, map_legend
            cv.addWidget(ChinaMapWidget(dict(provs)))
            cv.addWidget(map_legend())

        # 鸟点足迹卡列表
        if not spots:
            empty = QLabel(t("还没有鸟点——在时间线给照片挂点，或地图页新建",
                             "No spots yet — mount photos on the timeline "
                             "or create one on the map page"))
            empty.setObjectName("Hint")
            cv.addWidget(empty)
            return
        srow = QHBoxLayout()
        srow.setSpacing(12)
        for sp in spots[:6]:
            card = QFrame()
            card.setObjectName("Card")
            card.setFixedWidth(230)
            v = QVBoxLayout(card)
            v.setContentsMargins(14, 12, 14, 12)
            v.setSpacing(4)
            nm = QLabel(sp["name"])
            nm.setStyleSheet(f"font-size:14px;font-weight:700;"
                             f"color:{theme.LABEL};background:transparent;")
            nm.setWordWrap(True)
            v.addWidget(nm)
            city = sp.get("city") or ""
            n_ph = sp.get("n_photos", 0)
            n_sp = sp.get("n_species", 0)
            meta = QLabel(t(f"{city + ' · ' if city else ''}{n_ph} 张 · "
                            f"{n_sp} 种",
                            f"{city + ' · ' if city else ''}{n_ph} photos · "
                            f"{n_sp} species"))
            meta.setObjectName("Hint")
            v.addWidget(meta)
            first_last = self._spot_range(sp["id"])
            if first_last:
                fr = QLabel(first_last)
                fr.setObjectName("Hint")
                v.addWidget(fr)
            go = QPushButton(t("查看", "View"))
            go.setCursor(Qt.PointingHandCursor)
            go.clicked.connect(lambda _=False, sid=sp["id"]: self._open_spot(sid))
            v.addWidget(go)
            srow.addWidget(card)
        srow.addStretch(1)
        host = QWidget()
        host.setLayout(srow)
        cv.addWidget(host)

    def _spot_range(self, spot_id: int) -> str:
        row = self.lib.conn.execute(
            "SELECT MIN(COALESCE(e.dt_original, p.added_at)) a, "
            "MAX(COALESCE(e.dt_original, p.added_at)) b "
            "FROM photos p LEFT JOIN exif e ON e.photo_id=p.id "
            "WHERE p.spot_id=?", (spot_id,)).fetchone()
        a, b = (row["a"] or "")[:10], (row["b"] or "")[:10]
        if not a:
            return ""
        return a if a == b else f"{a} ~ {b}"

    def _open_spot(self, spot_id: int):
        """点击鸟点卡: 开现成 SpotDetailDialog(不强造地图定位接口)。"""
        from .map_page import SpotDetailDialog
        dlg = SpotDetailDialog(self.lib, self.win, spot_id)
        dlg.exec()

    # ---------- Tab4 徽章(stats_page 搬家) ----------
    def _build_badges(self, cv: QVBoxLayout):
        ach = self.lib.achievements_summary()
        s = self.lib.stats_summary()
        groups = [
            (t("生涯鸟种", "Life list"), _badge_row(SPECIES_MILESTONES, ach['species'],
                                                    ach['species_unlock'])),
            (t("照片收藏", "Photo collection"), _badge_row(PHOTO_MILESTONES, ach['photos'],
                                                           ach['photos_unlock'])),
            (t("鸟点足迹", "Hotspot trail"), _badge_row(SPOT_MILESTONES, ach['spots'],
                                                        ach['spots_unlock'])),
            (t("连续观鸟", "Birding streak"), _badge_row(STREAK_MILESTONES, ach['max_streak'],
                                                         lambda target: None)),
            (t("猛禽图鉴", "Raptor list"), _badge_row(RAPTOR_MILESTONES, ach['raptors'],
                                                     lambda target: None)),
            (t("水鸟图鉴", "Waterbird list"), _badge_row(WATERBIRD_MILESTONES, ach['waterbirds'],
                                                         lambda target: None)),
        ]
        for gname, badges in groups:
            card = QFrame()
            card.setObjectName("Card")
            cvv = QVBoxLayout(card)
            cvv.setContentsMargins(18, 14, 18, 16)
            cvv.setSpacing(10)
            gl = QLabel(t("💡 点击徽章看它背后的照片/鸟种", 
                          "💡 Click a badge to see the photos/species behind it")
                        if gname == groups[0][0] else gname)
            gl.setObjectName("CardTitle")
            cvv.addWidget(gl)
            grid_host = QWidget()
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(8)
            cols = 5
            for i, b in enumerate(badges):
                b.set_click(self._badge_evidence(gname, b))
                grid.addWidget(b, i // cols, i % cols)
            cvv.addWidget(grid_host)
            cv.addWidget(card)

        chart_card = QFrame()
        chart_card.setObjectName("Card")
        cvv = QVBoxLayout(chart_card)
        cvv.setContentsMargins(20, 16, 20, 16)
        head = QLabel(t("年度鸟种增长  ·  蓝=当年新增  浅蓝=累计",
                        "Yearly species growth  ·  Blue=new  Light blue=cumulative"))
        head.setObjectName("CardTitle")
        cvv.addWidget(head)
        chart = BarChart()
        cvv.addWidget(chart, 1)
        chart.set_series(s["series"])
        cv.addWidget(chart_card)

        # 装备榜(过机镜别名+同别名聚合——修复docstring声称但漏用) + 出片时段
        gear = self.lib.gear_stats()

        def _alias_merge(pairs: list[tuple[str, int]]) -> list[tuple[str, int]]:
            merged: dict[str, int] = {}
            for name, n in pairs:
                k = alias_of(name)
                if k == name and " " in name:
                    # gear_stats 存 "make model" 拼串, 别名表键=裸型号——
                    # 剥品牌前缀再查(与分享卡口径一致, 见exif_parts_of)
                    tail = name.split(" ", 1)[1]
                    k2 = alias_of(tail)
                    if k2 != tail:
                        k = k2
                merged[k] = merged.get(k, 0) + n
            return sorted(merged.items(), key=lambda kv: kv[1], reverse=True)

        gear = {"body": _alias_merge(gear["body"]),
                "lens": _alias_merge(gear["lens"])}
        if gear["body"] or gear["lens"]:
            gear_card = QFrame()
            gear_card.setObjectName("Card")
            glay = QVBoxLayout(gear_card)
            glay.setContentsMargins(20, 16, 20, 16)
            gh = QLabel(t("装备榜  ·  出片数", "Gear ranking  ·  photo counts"))
            gh.setObjectName("CardTitle")
            glay.addWidget(gh)
            grow = QHBoxLayout()
            for lab_key, items in ((t("机身", "Bodies"), gear["body"]),
                                   (t("镜头", "Lenses"), gear["lens"])):
                txt = "<br>".join(
                    f"{i + 1}. {_html.escape(name)} — {n}" for i, (name, n)
                    in enumerate(items[:6])) or \
                    t("（暂无该类数据）", "(no data)")
                gl2 = QLabel(f"<b>{lab_key}</b><br>{txt}")
                gl2.setWordWrap(True)
                gl2.setStyleSheet(f"font-size:13px;color:{theme.LABEL_2};"
                                  "background:transparent;")
                grow.addWidget(gl2, 1)
            glay.addLayout(grow)
            cv.addWidget(gear_card)

        hours = self.lib.hour_stats()
        if any(h["total"] for h in hours):
            hour_card = QFrame()
            hour_card.setObjectName("Card")
            hv = QVBoxLayout(hour_card)
            hv.setContentsMargins(20, 16, 20, 16)
            hh = QLabel(t("出片时段  ·  按拍摄小时(0~23点)",
                          "Shooting hours  ·  by hour of day (0-23)"))
            hh.setObjectName("CardTitle")
            hv.addWidget(hh)
            hour_chart = BarChart()
            hour_chart.setMinimumHeight(180)
            hour_chart.set_series(hours)
            hv.addWidget(hour_chart, 1)
            cv.addWidget(hour_card)

        # 出片月份 + 鸟种月份(反馈9: 让数据有趣起来, 历年累计)
        m_ph = self.lib.conn.execute(
            "SELECT CAST(substr(COALESCE(e.dt_original, p.added_at),6,2) "
            "AS INTEGER) m, COUNT(*) c FROM photos p LEFT JOIN exif e "
            "ON e.photo_id=p.id GROUP BY m").fetchall()
        m_sp = self.lib.conn.execute(
            "SELECT CAST(substr(COALESCE(e.dt_original, p.added_at),6,2) "
            "AS INTEGER) m, COUNT(DISTINCT v.eff_code) c FROM v_records v "
            "JOIN photos p ON p.id=v.photo_id LEFT JOIN exif e "
            "ON e.photo_id=p.id GROUP BY m").fetchall()
        ph_map = {r["m"]: r["c"] for r in m_ph if r["m"]}
        sp_map = {r["m"]: r["c"] for r in m_sp if r["m"]}
        if ph_map or sp_map:
            two = QHBoxLayout()
            two.setSpacing(12)
            for title, data, series in (
                    (t("出片月份  ·  历年按月(1~12月)",
                       "Photos by month  ·  all years"),
                     ph_map, [{"hour": m, "total": ph_map.get(m, 0)}
                              for m in range(1, 13)]),
                    (t("鸟种月份  ·  每月拍到过多少种",
                       "Species by month  ·  distinct species"),
                     sp_map, [{"hour": m, "total": sp_map.get(m, 0)}
                              for m in range(1, 13)])):
                if not data:
                    continue
                mc = QFrame()
                mc.setObjectName("Card")
                mv = QVBoxLayout(mc)
                mv.setContentsMargins(20, 16, 20, 16)
                ml = QLabel(title)
                ml.setObjectName("CardTitle")
                mv.addWidget(ml)
                chart = BarChart()
                chart.setMinimumHeight(180)
                chart.set_series(series, x_month_mode=True)
                mv.addWidget(chart, 1)
                two.addWidget(mc, 1)
            if two.count():
                host2 = QWidget()
                host2.setLayout(two)
                cv.addWidget(host2)

    # ---------- 徽章证据链(实测反馈9) ----------
    def _badge_evidence(self, gname: str, badge):
        """点徽章→看背后的证据。按组取证: 生涯鸟种=按序lifers,
        照片=按时间前N张, 鸟点=鸟点清单, 猛禽/水鸟=该目已收录种。"""
        target = badge.target
        cur = badge.cur

        def photo_items() -> list[dict]:
            rows = self.lib.conn.execute(
                "SELECT p.id, COALESCE(e.dt_original, p.added_at) ts "
                "FROM photos p LEFT JOIN exif e ON e.photo_id=p.id "
                "ORDER BY ts LIMIT ?", (max(target, 1),)).fetchall()
            return [{"kind": "photo", "id": r["id"],
                     "label": (r["ts"] or "")[:10]} for r in rows]

        def species_items(orders=None) -> list[dict]:
            q = ("SELECT DISTINCT v.eff_code code, s.cn, s.en, "
                 "MIN(v.taken_at) ts FROM v_records v "
                 "JOIN species s ON s.code=v.eff_code ")
            args: list = []
            if orders:
                q += f"WHERE s.order_cn IN ({','.join('?' * len(orders))})"
                args = list(orders)
            q += " GROUP BY v.eff_code ORDER BY ts"
            return [{"kind": "species", "id": r["code"],
                     "label": f"{sname(r['cn'], r['en'])} · "
                              f"{(r['ts'] or '')[:7]}"}
                    for r in self.lib.conn.execute(q, args).fetchall()]

        def spot_items() -> list[dict]:
            return [{"kind": "spot", "id": sp["id"], "label": sp["name"]}
                    for sp in self.lib.spots_overview()]

        if gname == t("生涯鸟种", "Life list"):
            items = [{"kind": "species", "id": li["code"],
                      "label": f"#{li['lifer_no']} "
                               f"{sname(li['cn'], li['en'])} · "
                               f"{(li['first_at'] or '')[:7]}"}
                     for li in self.lib.lifers()[:max(cur, target)]]
        elif gname == t("照片收藏", "Photo collection"):
            items = photo_items()
        elif gname == t("鸟点足迹", "Hotspot trail"):
            items = spot_items()
        elif gname == t("猛禽图鉴", "Raptor list"):
            items = species_items(self.lib.RAPTOR_ORDERS)
        elif gname == t("水鸟图鉴", "Waterbird list"):
            items = species_items(self.lib.WATERBIRD_ORDERS)
        else:
            return None   # 连续观火等无实物证据组

        def _open():
            from .badge_evidence import BadgeEvidenceDialog
            dlg = BadgeEvidenceDialog(self.lib, self.win, badge.name, items)
            dlg.exec()
        return _open if items else None

    # ---------- 动作 ----------
    def _export_ebird(self):
        import csv
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        rows = self.lib.ebird_export_rows()
        if not rows:
            QMessageBox.information(self, t("导出eBird", "Export eBird"),
                                    t("还没有可导出的识别记录。",
                                      "No identification records to export yet."))
            return
        default = "birdtrace_ebird.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, t("导出eBird CSV", "Export eBird CSV"), default, "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        QMessageBox.information(
            self, t("导出完成", "Export complete"),
            t(f"已导出 {len(rows)} 条观测记录。\n"
              "可到 eBird.org → 提交观测 → 导入数据 上传。",
              f"Exported {len(rows)} observation records.\n"
              "Upload them via eBird.org → Submit → Import data."))

    def _export_life_list(self):
        import csv
        import datetime
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        feed = self.lib.lifer_feed()
        if not feed:
            QMessageBox.information(self, t("导出生涯清单", "Export life list"),
                                    t("还没有收录鸟种。", "No species recorded yet."))
            return
        region = self.lib.get_setting("default_region", "GLOBAL")
        default = (t("生涯清单-", "Life list-")
                   + f"{self._today().strftime('%Y%m%d')}.csv")
        path, _ = QFileDialog.getSaveFileName(
            self, t("导出生涯清单 CSV", "Export life list CSV"), default,
            "CSV (*.csv)")
        if not path:
            return
        from ..core.prior_hint import get_hint, tier_display
        hint = get_hint()
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow([t("编号", "No"), t("中文名", "Chinese"), t("学名", "Scientific"),
                        t("英文名", "English"), t("首见日期", "First seen"),
                        t("地点", "Spot"), t("罕见度", "Rarity")])
            for li in feed:
                rt = hint.rarity_tier(li["code"], region) if \
                    region and region != "GLOBAL" else None
                w.writerow([li["no"], li["cn"], li["sci"], li["en"],
                            (li["first_at"] or "")[:10],
                            li["spot_name"] or li["region"],
                            tier_display(rt) if rt else ""])
        QMessageBox.information(
            self, t("导出完成", "Export complete"),
            t(f"已导出 {len(feed)} 种的生涯清单。",
              f"Exported life list with {len(feed)} species."))

    def _open_report(self, year: str | None = None):
        from .report_dialog import YearlyReportDialog
        dlg = YearlyReportDialog(self.lib, self.win, self.win)
        if year:
            idx = dlg.year_combo.findText(str(year))
            if idx >= 0:
                dlg.year_combo.setCurrentIndex(idx)
        dlg.show()
