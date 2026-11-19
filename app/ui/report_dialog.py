# -*- coding: utf-8 -*-
"""年度报告对话框: 年份选择 + 汇总 + 月度柱状 + 年度新种九宫格 + 导出长图。

长图由 QPainter 渲染(1600x2300), 复用分享卡的字体/配色体系。
"""
from __future__ import annotations

import datetime

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from .. import theme
from ..i18n import t, sname
from ..media import ensure_thumbnail
from ..theme.widgets import make_card

# 长图配色(与分享卡同源的米色系)
R_BG = "#F0EFE4"
R_TITLE = "#2E2E28"
R_ACCENT = "#8A9455"
R_META = "#6E6E5E"

# 英文月份缩写(月度柱状横轴; 中文模式沿用"N月")
MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _f(size: int, weight: int = 400, bold=False) -> QFont:
    f = QFont()
    f.setFamilies(["MiSans", "HarmonyOS Sans SC", "PingFang SC",
                   "Microsoft YaHei UI", "Segoe UI"])
    f.setPixelSize(size)
    try:
        f.setWeight(QFont.Weight(weight))
    except ValueError:
        f.setWeight(QFont.Weight.Bold)
    if bold:
        f.setBold(True)
    return f


class _MonthBars(QWidget):
    def __init__(self, monthly: list[int]):
        super().__init__()
        self.monthly = monthly
        self.setMinimumHeight(150)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        pad_b, pad_t = 26, 14
        mx = max(self.monthly) or 1
        slot = w / 12
        bw = min(30, slot * 0.5)
        p.setFont(_f(10))
        for i, n in enumerate(self.monthly):
            cx = slot * i + slot / 2
            bh = (h - pad_t - pad_b) * n / mx
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.BLUE) if n else QColor("#D9D9DE"))
            p.drawRoundedRect(QRectF(cx - bw / 2, h - pad_b - max(bh, 3 if n else 2),
                                     bw, max(bh, 3 if n else 2)), 3, 3)
            p.setPen(QColor(theme.LABEL_2))
            p.drawText(QRectF(cx - slot / 2, h - pad_b + 2, slot, 16),
                       Qt.AlignCenter, t(f"{i + 1}月", MONTHS_EN[i]))
            if n:
                p.setPen(QColor(theme.LABEL))
                p.drawText(QRectF(cx - slot / 2, h - pad_b - bh - 16, slot, 14),
                           Qt.AlignCenter, str(n))
        p.end()


class YearlyReportDialog(QFrame):
    """非模态年度报告。parent=win, lib 同库。"""

    def __init__(self, lib, win, parent=None):
        super().__init__(parent or win, Qt.Window)
        self.lib = lib
        self.win = win
        self.setWindowTitle(t("年度报告", "Annual report"))
        self.resize(860, 760)
        self.setObjectName("Card")

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(12)

        top = QHBoxLayout()
        title = QLabel(t("年度报告", "Annual report"))
        title.setStyleSheet(f"font-size:22px;font-weight:800;color:{theme.LABEL};"
                            "background:transparent;")
        top.addWidget(title)
        top.addStretch(1)
        self.year_combo = QComboBox()
        for y in lib.available_years():
            self.year_combo.addItem(t(f"{y} 年", str(y)), y)
        self.year_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        top.addWidget(self.year_combo)
        self.export_btn = QPushButton(t("导出报告长图…", "Export report image…"))
        self.export_btn.setObjectName("Primary")
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.clicked.connect(self._export_image)
        top.addWidget(self.export_btn)
        v.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.body = QVBoxLayout(content)
        self.body.setContentsMargins(0, 0, 8, 0)
        self.body.setSpacing(12)
        scroll.setWidget(content)
        v.addWidget(scroll, 1)

        self.refresh()

    def refresh(self):
        while self.body.count():
            it = self.body.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        year = self.year_combo.currentData() or datetime.date.today().strftime("%Y")
        self.data = self.lib.yearly_report(year)
        self.year = year
        d = self.data

        # 汇总数字
        busiest = t("最忙月份", "Busiest month")
        row = QHBoxLayout()
        for num, label in ((d["new"], t("年度新种", "New species")),
                           (d["yearbird"], t("年鸟回归", "Year-bird returns")),
                           (d["photos"], t("照片数", "Photos")),
                           (d["days"], t("拍摄天数", "Days photographed")),
                           (d["busiest"], busiest) if d["busiest"] else (0, busiest)):
            c = QFrame()
            c.setObjectName("Card")
            cv = QVBoxLayout(c)
            cv.setContentsMargins(16, 10, 16, 10)
            n = QLabel(str(num) + (t("月", "") if label == busiest and num else ""))
            n.setStyleSheet(f"font-size:30px;font-weight:800;color:{theme.GREEN};"
                            "background:transparent;")
            n.setAlignment(Qt.AlignCenter)
            lb = QLabel(label)
            lb.setStyleSheet(f"font-size:12px;color:{theme.LABEL_2};background:transparent;")
            lb.setAlignment(Qt.AlignCenter)
            cv.addWidget(n)
            cv.addWidget(lb)
            row.addWidget(c)
        self.body.addLayout(row)

        # 月度柱状
        card, cv = make_card(t(f"{year} 年月度照片数", f"Monthly photos in {year}"))
        cv.addWidget(_MonthBars(d["monthly"]))
        self.body.addWidget(card)

        # 年度新种九宫格
        card2, cv2 = make_card(
            t(f"年度新种 · {d['new']} 种" + ("（展示前9种）" if d["new"] > 9 else ""),
              f"New species · {d['new']}"
              + (" (showing first 9)" if d["new"] > 9 else "")))
        if d["grid"]:
            host = QWidget()
            from PySide6.QtWidgets import QGridLayout
            g = QGridLayout(host)
            g.setContentsMargins(0, 0, 0, 0)
            g.setSpacing(10)
            for i, item in enumerate(d["grid"]):
                cell = QVBoxLayout()
                thumb = QLabel()
                thumb.setFixedSize(150, 112)
                thumb.setAlignment(Qt.AlignCenter)
                thumb.setStyleSheet(f"background:{theme.FILL};border-radius:10px;")
                if item["path"]:
                    tp = ensure_thumbnail(self.lib.root, item["path"],
                                          item["hash"], 300)
                    if tp:
                        pm = QPixmap(str(tp))
                        thumb.setPixmap(pm.scaled(
                            150, 112, Qt.KeepAspectRatioByExpanding,
                            Qt.SmoothTransformation))
                nm = QLabel(sname(item["cn"], item["en"]))
                nm.setStyleSheet(f"font-size:13px;font-weight:700;"
                                 f"color:{theme.LABEL};background:transparent;")
                nm.setAlignment(Qt.AlignCenter)
                dt = QLabel(item["date"])
                dt.setStyleSheet(f"font-size:11px;color:{theme.LABEL_3};"
                                 "background:transparent;")
                dt.setAlignment(Qt.AlignCenter)
                cell.addWidget(thumb)
                cell.addWidget(nm)
                cell.addWidget(dt)
                holder = QWidget()
                holder.setLayout(cell)
                g.addWidget(holder, i // 3, i % 3)
            cv2.addWidget(host)
        else:
            tip = QLabel(t("这一年还没有新种收录",
                           "No new species recorded this year"))
            tip.setObjectName("Hint")
            cv2.addWidget(tip)
        self.body.addWidget(card2)

        # 年度十八图(AI美学评选)
        best = d.get("best18") or []
        card3, cv3 = make_card(
            t("✨ 年度十八图 · AI美学评选"
              + (f"（已选 {len(best)} 张）" if 0 < len(best) < 18 else ""),
              "✨ Best 18 of the year · AI aesthetic picks"
              + (f" ({len(best)} selected)" if 0 < len(best) < 18 else "")))
        if best:
            host3 = QWidget()
            from PySide6.QtWidgets import QGridLayout as _QGL
            g3 = _QGL(host3)
            g3.setContentsMargins(0, 0, 0, 0)
            g3.setSpacing(10)
            for i, item in enumerate(best):
                thumb = QLabel()
                thumb.setFixedSize(120, 90)
                thumb.setAlignment(Qt.AlignCenter)
                thumb.setStyleSheet(f"background:{theme.FILL};border-radius:8px;")
                if item["path"]:
                    tp = ensure_thumbnail(self.lib.root, item["path"],
                                          item["hash"], 240)
                    if tp:
                        pm = QPixmap(str(tp))
                        # 完整显示(同长图, 2026-11-04用户)
                        thumb.setPixmap(pm.scaled(
                            120, 90, Qt.KeepAspectRatio,
                            Qt.SmoothTransformation))
                g3.addWidget(thumb, i // 6, i % 6)
            cv3.addWidget(host3)
            cap = QLabel(t("按美学评分自动挑选 · 每种鸟最多两张",
                           "Auto-picked by aesthetic score · max two per species"))
            cap.setObjectName("Hint")
            cv3.addWidget(cap)
        else:
            tip3 = QLabel(t("照片完成美学评分后，这里会展示年度最佳"
                            "（识别完成会自动在后台评分）",
                            "Once photos have aesthetic scores, the year's "
                            "best will appear here (scoring runs automatically "
                            "in the background after recognition)"))
            tip3.setObjectName("Hint")
            cv3.addWidget(tip3)
        self.body.addWidget(card3)
        self.body.addStretch(1)

    def _export_image(self):
        default = t(f"鸟迹年度报告_{self.year}.png",
                    f"BirdTrace_annual_report_{self.year}.png")
        path, _ = QFileDialog.getSaveFileName(
            self, t("导出年度报告长图", "Export annual report image"),
            default, t("PNG 图片 (*.png)", "PNG image (*.png)"))
        if not path:
            return
        pm = self._render_poster()
        pm.save(path, "PNG")

    def _render_poster(self) -> QPixmap:
        d = self.data
        W = 1600
        # 画布高度随九宫格/十八图行数动态, 柱状图/页脚不再溢出或留大片空白
        cell_w = (W - 180 - 2 * 36) // 3
        ch = cell_w * 3 // 4
        import math
        grid_rows = max(1, math.ceil(len(d["grid"][:9]) / 3)) if d["grid"] else 0
        gy0 = 790 + grid_rows * (ch + 96) + 60
        # 年度十八图区块
        best = d.get("best18") or []
        b_cols, b_gap = 6, 16
        cw2 = (W - 180 - (b_cols - 1) * b_gap) // b_cols
        ch2 = cw2 * 3 // 4
        b_rows = math.ceil(len(best) / b_cols) if best else 0
        y0 = gy0 + (116 + b_rows * (ch2 + 18) + 70 if best else 0)
        H = max(1620, y0 + 260 + 34 + 150)
        pm = QPixmap(W, H)
        pm.fill(QColor(R_BG))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        # 年份大字
        p.setPen(QColor(R_TITLE))
        p.setFont(_f(56, 500))
        p.drawText(QRectF(90, 70, W - 180, 70), Qt.AlignLeft,
                   t("鸟迹 · 年度报告", "BirdTrace · Annual report"))
        p.setFont(_f(190, 900))
        p.drawText(QRectF(80, 130, W - 160, 240), Qt.AlignLeft, self.year)
        p.setFont(_f(40, 500))
        p.setPen(QColor(R_META))
        who = self.lib.copyright_defaults_get().get("creator", "")
        p.drawText(QRectF(90, 380, W - 180, 56), Qt.AlignLeft,
                   t(f"{who} 的观鸟一年", f"{who}'s year of birding")
                   if who else t("我的观鸟一年", "My year of birding"))
        # 汇总
        stats = [(d["new"], t("新种", "New species")),
                 (d["yearbird"], t("年鸟回归", "Year-bird returns")),
                 (d["photos"], t("照片", "Photos")),
                 (d["days"], t("拍摄天数", "Days photographed")),
                 (d["total_species"], t("生涯总种数", "Lifetime species"))]
        sx = 90
        for num, label in stats:
            p.setPen(QColor(R_ACCENT))
            p.setFont(_f(88, 900))
            p.drawText(QRectF(sx, 470, 280, 110), Qt.AlignLeft, str(num))
            p.setPen(QColor(R_META))
            p.setFont(_f(34, 500))
            p.drawText(QRectF(sx + 4, 586, 280, 46), Qt.AlignLeft, label)
            sx += 292
        p.setPen(QColor("#DCDBCC"))
        p.drawLine(90, 680, W - 90, 680)
        # 九宫格
        p.setFont(_f(44, 800))
        p.setPen(QColor(R_TITLE))
        p.drawText(QRectF(90, 706, W - 180, 60), Qt.AlignLeft,
                   t(f"年度新种 · {d['new']}", f"New species · {d['new']}"))
        cell_w = (W - 180 - 2 * 36) // 3
        for i, item in enumerate(d["grid"][:9]):
            cx = 90 + (i % 3) * (cell_w + 36)
            cy = 790 + (i // 3) * (cell_w * 3 // 4 + 96)
            ch = cell_w * 3 // 4
            path_ = QPainterPath()
            path_.addRoundedRect(QRectF(cx, cy, cell_w, ch), 18, 18)
            p.save()
            p.setClipPath(path_)
            p.fillRect(QRectF(cx, cy, cell_w, ch), QColor("#E4E3D6"))
            if item["path"]:
                tp = ensure_thumbnail(self.lib.root, item["path"],
                                      item["hash"], 640)
                if tp:
                    im = QPixmap(str(tp))
                    sc = im.scaled(cell_w, ch, Qt.KeepAspectRatioByExpanding,
                                   Qt.SmoothTransformation)
                    p.drawPixmap(int(cx - (sc.width() - cell_w) / 2),
                                 int(cy - (sc.height() - ch) / 2), sc)
            p.restore()
            p.setPen(QColor(R_TITLE))
            p.setFont(_f(38, 700))
            p.drawText(QRectF(cx, cy + ch + 8, cell_w, 50), Qt.AlignLeft,
                       sname(item["cn"], item["en"]))
            p.setPen(QColor(R_META))
            p.setFont(_f(28, 400))
            p.drawText(QRectF(cx, cy + ch + 56, cell_w, 40), Qt.AlignLeft,
                       item["date"])
        # 年度十八图(6列小图, 每张圆角裁切)
        if best:
            p.setPen(QColor(R_TITLE))
            p.setFont(_f(44, 800))
            p.drawText(QRectF(90, gy0, W - 180, 60), Qt.AlignLeft,
                       t("✨ 年度十八图", "✨ Best 18 of the year"))
            p.setPen(QColor(R_META))
            p.setFont(_f(26, 400))
            p.drawText(QRectF(90, gy0 + 58, W - 180, 40), Qt.AlignLeft,
                       t("AI 按美学评分挑选 · 每种鸟最多两张",
                         "AI-picked by aesthetic score · max two per species"))
            for i, item in enumerate(best):
                bx = 90 + (i % b_cols) * (cw2 + b_gap)
                by = gy0 + 116 + (i // b_cols) * (ch2 + 18)
                path_ = QPainterPath()
                path_.addRoundedRect(QRectF(bx, by, cw2, ch2), 12, 12)
                p.save()
                p.setClipPath(path_)
                p.fillRect(QRectF(bx, by, cw2, ch2), QColor("#E4E3D6"))
                if item["path"]:
                    tp = ensure_thumbnail(self.lib.root, item["path"],
                                          item["hash"], cw2 * 2)
                    if tp:
                        im = QPixmap(str(tp))
                        # 完整显示照片(KeepAspectRatio居中, 不足处留底色)
                        # ——裁切填充会只见局部(2026-11-04用户)
                        sc = im.scaled(cw2, ch2, Qt.KeepAspectRatio,
                                       Qt.SmoothTransformation)
                        p.drawPixmap(int(bx + (cw2 - sc.width()) / 2),
                                     int(by + (ch2 - sc.height()) / 2), sc)
                p.restore()
        # 月度简表(y0已在画布计算处按实际行数得出)
        p.setPen(QColor(R_TITLE))
        p.setFont(_f(44, 800))
        p.drawText(QRectF(90, y0, W - 180, 60), Qt.AlignLeft,
                   t("月度照片数", "Monthly photos"))
        mx = max(d["monthly"]) or 1
        bw = (W - 180 - 11 * 14) / 12
        p.setFont(_f(26, 500))
        for i, n in enumerate(d["monthly"]):
            bx = 90 + i * (bw + 14)
            bh = 170 * n / mx
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(R_ACCENT) if n else QColor("#DCDBCC"))
            p.drawRoundedRect(QRectF(bx, y0 + 260 - max(bh, 6), bw, max(bh, 6)),
                              6, 6)
            p.setPen(QColor(R_META))
            p.drawText(QRectF(bx - 8, y0 + 268, bw + 16, 34), Qt.AlignCenter,
                       t(f"{i + 1}月", MONTHS_EN[i]))
            if n:
                p.setPen(QColor(R_TITLE))
                p.drawText(QRectF(bx - 8, y0 + 260 - max(bh, 6) - 40,
                                  bw + 16, 34), Qt.AlignCenter, str(n))
        # 页脚
        p.setPen(QColor(R_META))
        p.setFont(_f(30, 500))
        p.drawText(QRectF(90, H - 100, W - 180, 44), Qt.AlignLeft,
                   f"BirdTrace Windows · {datetime.date.today().isoformat()}")
        if who:
            p.drawText(QRectF(90, H - 100, W - 180, 44), Qt.AlignRight, who)
        p.end()
        return pm
