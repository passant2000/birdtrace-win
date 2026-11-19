# -*- coding: utf-8 -*-
"""个人成就页: 生涯总览 + 成就徽章(参考birdtrace安卓指标体系) + 年度增长图。

成就维度(与安卓版同源): 不重复鸟种/鸟点数/猛禽种数/水鸟种数/连续观鸟天数。
解锁日期 = 达成该数量时的首见/入库日期(可精确回溯)。
"""
from __future__ import annotations

import html as _html

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QScrollArea, QVBoxLayout, QWidget)

from .. import theme
from ..i18n import t, sname

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


class BarChart(QWidget):
    """年度新增(蓝) + 累计(浅蓝)柱状图。"""

    def __init__(self):
        super().__init__()
        self.series: list[dict] = []
        self.setMinimumHeight(240)

    def set_series(self, series: list[dict]):
        self.series = series
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
    """成就徽章: 解锁=彩色+日期; 未解锁=灰+进度条。"""

    def __init__(self, emoji: str, name: str, target: int, cur: int,
                 unlock_date: str | None, parent=None):
        super().__init__(parent)
        self.setFixedSize(150, 132)
        self.emoji, self.name, self.target = emoji, name, target
        self.cur, self.unlock_date = cur, unlock_date
        self.done = cur >= target

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(4, 4, self.width() - 8, self.height() - 8)
        from PySide6.QtGui import QPainterPath, QPen
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
        from PySide6.QtGui import QFont
        ef = QFont()
        ef.setPixelSize(30)
        p.setFont(ef)
        if self.done:
            p.setPen(QColor(theme.LABEL))
        else:
            from PySide6.QtGui import QPixmap
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
            # 进度条
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


class StatsPage(QWidget):
    def __init__(self, lib, win):
        super().__init__()
        self.lib = lib
        self.win = win
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)
        head = QHBoxLayout()
        from ..theme.widgets import PageHeader
        title = PageHeader(t("个人成就", "Achievements"))
        head.addWidget(title, 1)
        from PySide6.QtWidgets import QPushButton
        self.ebird_btn = QPushButton(t("导出eBird记录", "Export eBird records"))
        self.ebird_btn.setCursor(Qt.PointingHandCursor)
        self.ebird_btn.clicked.connect(self._export_ebird)
        title.add_action(self.ebird_btn)
        self.report_btn = QPushButton(t("年度报告…", "Annual report…"))
        self.report_btn.setObjectName("Primary")
        self.report_btn.setCursor(Qt.PointingHandCursor)
        self.report_btn.clicked.connect(self._open_report)
        title.add_action(self.report_btn)
        lay.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        content = QWidget()
        self.content_lay = QVBoxLayout(content)
        self.content_lay.setContentsMargins(0, 0, 16, 24)
        self.content_lay.setSpacing(14)
        self.scroll.setWidget(content)
        lay.addWidget(self.scroll, 1)

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

    def _open_report(self):
        from .report_dialog import YearlyReportDialog
        dlg = YearlyReportDialog(self.lib, self.win, self.win)
        dlg.show()

    def refresh(self):
        # 清空动态区重建(图表等一并重建, 避免复用已删除控件)
        while self.content_lay.count():
            it = self.content_lay.takeAt(0)
            w = it.widget() if it else None
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

        s = self.lib.stats_summary()
        import datetime
        ys = self.lib.year_summary(datetime.date.today().strftime('%Y'))
        ach = self.lib.achievements_summary()

        row = QHBoxLayout()
        row.setSpacing(12)
        for val, label, color in (
                (s['photos'], t("照片总数", "Total photos"), theme.BLUE),
                (s['species'], t("鸟种数（个人图鉴）", "Species (personal list)"), theme.GREEN),
                (ys['new'], t("今年新种", "New this year"), theme.ORANGE),
                (ys['yearbird'], t("今年回归（年鸟）", "Returning (year birds)"), "#8A9455"),
                (ach['shooting_days'], t("拍摄天数", "Days birding"), theme.BLUE),
                (ach['spots'], t("鸟点数", "Hotspots"), theme.GREEN)):
            row.addWidget(_number_card(val, label, color))
        self.content_lay.addLayout(row)

        # 徽章区
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
            cv = QVBoxLayout(card)
            cv.setContentsMargins(18, 14, 18, 16)
            cv.setSpacing(10)
            gl = QLabel(gname)
            gl.setObjectName("CardTitle")
            cv.addWidget(gl)
            grid_host = QWidget()
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(8)
            cols = 5
            for i, b in enumerate(badges):
                grid.addWidget(b, i // cols, i % cols)
            cv.addWidget(grid_host)
            self.content_lay.addWidget(card)

        chart_card = QFrame()
        chart_card.setObjectName("Card")
        cv = QVBoxLayout(chart_card)
        cv.setContentsMargins(20, 16, 20, 16)
        head = QLabel(t("年度鸟种增长  ·  蓝=当年新增  浅蓝=累计",
                        "Yearly species growth  ·  Blue=new  Light blue=cumulative"))
        head.setObjectName("CardTitle")
        cv.addWidget(head)
        self.chart = BarChart()
        cv.addWidget(self.chart, 1)

        lifer_recent = QLabel("")
        lifer_recent.setWordWrap(True)
        lifer_recent.setStyleSheet(f"font-size:13px;color:{theme.LABEL_2};"
                                   "background:transparent;padding:4px;")

        self.content_lay.addWidget(chart_card)
        self.chart.set_series(s["series"])
        self.content_lay.addWidget(lifer_recent)
        lifers = self.lib.lifers()[-8:][::-1]
        if lifers:
            txt = "  ·  ".join(
                f"#{li['lifer_no']} {sname(li['cn'], li['en'])} ({(li['first_at'] or '')[:10]})"
                for li in lifers)
            lifer_recent.setText(t("最近新收录：", "Recent lifers: ") + txt)
        else:
            lifer_recent.setText(t("识别完成后, 这里会展示你的新鸟收录动态",
                                   "Recent lifers will appear here after identifications"))

        # 装备榜+出片时段(1.0冲刺⑥, 数据全在exif表)
        gear = self.lib.gear_stats()
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
            self.content_lay.addWidget(gear_card)

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
            hour_chart.setMinimumHeight(160)
            hour_chart.set_series(hours)
            hv.addWidget(hour_chart, 1)
            self.content_lay.addWidget(hour_card)
        self.content_lay.addStretch(1)
