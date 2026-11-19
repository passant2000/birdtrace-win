# -*- coding: utf-8 -*-
"""年度年鉴页(1.0主打, 实测反馈10c): 档案组新页面, Apple年度回顾风格
(设计规范-年鉴与静态站 §1/§3): 年度汇总数字卡+年度十八图+新种九宫格+
月度柱状+年度之最; 「导出年鉴 PDF」=A4排版(yearbook_pdf, 与作品集画册
同一设计语言)。数据全复用 yearly_report_data/best_of_year 现成管线。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from .. import theme
from ..i18n import t, sname
from ..media import cached_thumbnail, ensure_thumbnail


class YearbookPage(QWidget):
    def __init__(self, lib, win):
        super().__init__()
        self.lib = lib
        self.win = win
        self._year = None
        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        from ..theme.widgets import PageHeader
        head = QHBoxLayout()
        self.title = PageHeader(t("年度年鉴", "Yearbook"))
        head.addWidget(self.title, 1)
        self.year_combo = QComboBox()
        self.year_combo.setCursor(Qt.PointingHandCursor)
        self.year_combo.currentIndexChanged.connect(
            lambda _i: self.refresh())
        self.title.add_action(self.year_combo)
        self.pdf_btn = QPushButton(t("导出年鉴 PDF…", "Export yearbook PDF…"))
        self.pdf_btn.setObjectName("Primary")
        self.pdf_btn.setCursor(Qt.PointingHandCursor)
        self.pdf_btn.clicked.connect(self._export_pdf)
        self.title.add_action(self.pdf_btn)
        lay.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.content = QWidget()
        self.content_lay = QVBoxLayout(self.content)
        self.content_lay.setContentsMargins(0, 0, 16, 24)
        self.content_lay.setSpacing(14)
        self.scroll.setWidget(self.content)
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
        self._clear()
        if not self._year:
            empty = QLabel(t("还没有照片——导入并识别后，这里生成你的年度年鉴",
                             "Import and identify photos to build your "
                             "yearbook here"))
            empty.setObjectName("Hint")
            self.content_lay.addWidget(empty)
            self.content_lay.addStretch(1)
            return
        self.title.set_title(t(f"年度年鉴 · {self._year}",
                               f"Yearbook · {self._year}"))
        d = self.lib.yearly_report(self._year)
        self._summary_row(d)
        self._best18_card(d)
        self._grid_card(d)
        self._monthly_card(d)
        self._highlights_card(d)
        self.content_lay.addStretch(1)

    def _clear(self):
        while self.content_lay.count():
            it = self.content_lay.takeAt(0)
            w = it.widget() if it else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    # ---------- 区块 ----------
    def _summary_row(self, d: dict):
        row = QHBoxLayout()
        row.setSpacing(12)
        busiest = d.get("busiest")
        items = [
            (d["photos"], t("作品", "Photos"), theme.BLUE),
            (d["new"], t("年度新种", "New species"), theme.ORANGE),
            (d["yearbird"], t("年鸟回归", "Returning"), "#8A9455"),
            (d["days"], t("拍摄天数", "Days out"), theme.GREEN),
            (t(f"{busiest}月", f"M{busiest}") if busiest else "—",
             t("最活跃月", "Busiest month"), theme.BLUE),
            (d["total_species"], t("生涯累计种", "Life total"), theme.GREEN),
        ]
        for val, label, color in items:
            card = QFrame()
            card.setObjectName("Card")
            v = QVBoxLayout(card)
            v.setContentsMargins(18, 12, 18, 12)
            n = QLabel(str(val))
            n.setStyleSheet(f"font-size:28px;font-weight:800;color:{color};"
                            "background:transparent;")
            l = QLabel(label)
            l.setStyleSheet(f"font-size:12px;color:{theme.LABEL_2};"
                            "background:transparent;")
            v.addWidget(n)
            v.addWidget(l)
            row.addWidget(card, 1)
        host = QWidget()
        host.setLayout(row)
        self.content_lay.addWidget(host)

    def _photo_pm(self, path: str, h: str, size: int) -> QPixmap | None:
        tp = cached_thumbnail(self.lib.root, h, size) or \
            (ensure_thumbnail(self.lib.root, path, h, size)
             if path else None)
        if tp:
            pm = QPixmap(str(tp))
            if not pm.isNull():
                return pm
        return None

    def _best18_card(self, d: dict):
        best = d["best18"]
        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)
        v.setContentsMargins(18, 14, 18, 16)
        v.setSpacing(10)
        hl = QLabel(t(f"年度十八图 · {len(best)} 张代表作",
                      f"Top shots · {len(best)} of the year"))
        hl.setObjectName("CardTitle")
        v.addWidget(hl)
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        tile = 168
        cols = 6
        ids = []
        for i, r in enumerate(best):
            pm = self._photo_pm(r["path"], r["hash"], tile * 2)
            item_w = QWidget()
            iv = QVBoxLayout(item_w)
            iv.setContentsMargins(0, 0, 0, 0)
            iv.setSpacing(3)
            pic = QLabel()
            pic.setFixedSize(tile, tile)
            pic.setAlignment(Qt.AlignCenter)
            pic.setStyleSheet(f"background:{theme.FILL};border-radius:10px;")
            if pm is not None:
                pic.setPixmap(pm.scaled(pic.size(),
                                        Qt.KeepAspectRatioByExpanding,
                                        Qt.SmoothTransformation))
            _sp = self.lib.species_info(r["eff_code"])                 if r.get("eff_code") else None
            cap = QLabel(sname(_sp["cn"], _sp["en"])
                         if _sp else r["name"])
            cap.setAlignment(Qt.AlignCenter)
            cap.setStyleSheet(f"font-size:11px;color:{theme.LABEL_2};"
                              "background:transparent;")
            iv.addWidget(pic)
            iv.addWidget(cap)
            ids.append(r["photo_id"])
            pid = r["photo_id"]
            pic.setCursor(Qt.PointingHandCursor)

            def _open(_e, _pid=pid, _ids=list(ids)):
                from .viewer import PhotoViewer
                PhotoViewer(self.lib, self.win, _pid, _ids).exec()
            pic.mousePressEvent = _open
            grid.addWidget(item_w, i // cols, i % cols)
        grid.setColumnStretch(cols, 1)
        v.addWidget(grid_host)
        self.content_lay.addWidget(card)

    def _grid_card(self, d: dict):
        grid9 = d["grid"]
        if not grid9:
            return
        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)
        v.setContentsMargins(18, 14, 18, 16)
        v.setSpacing(10)
        hl = QLabel(t(f"年度新种 · 首见照 ({d['new']} 种)",
                      f"New species · first-seen ({d['new']})"))
        hl.setObjectName("CardTitle")
        v.addWidget(hl)
        row = QHBoxLayout()
        row.setSpacing(10)
        for g in grid9:
            box = QWidget()
            bv = QVBoxLayout(box)
            bv.setContentsMargins(0, 0, 0, 0)
            bv.setSpacing(3)
            pic = QLabel()
            pic.setFixedSize(110, 82)
            pic.setAlignment(Qt.AlignCenter)
            pic.setStyleSheet(f"background:{theme.FILL};border-radius:8px;")
            pm = self._photo_pm(g["path"], g["hash"], 220)
            if pm is not None:
                pic.setPixmap(pm.scaled(pic.size(),
                                        Qt.KeepAspectRatioByExpanding,
                                        Qt.SmoothTransformation))
            cap = QLabel(t(f"{g['cn']}\n{g['date']}",
                           f"{g['en']}\n{g['date']}"))
            cap.setAlignment(Qt.AlignCenter)
            cap.setStyleSheet(f"font-size:10px;color:{theme.LABEL_2};"
                              "background:transparent;")
            bv.addWidget(pic)
            bv.addWidget(cap)
            code_row = self.lib.conn.execute(
                "SELECT eff_code FROM v_records WHERE photo_id=(SELECT "
                "MIN(photo_id) FROM v_records) LIMIT 1").fetchone()
            _ = code_row   # 不强求跳转; 点击=查看器看首见照
            row.addWidget(box)
        row.addStretch(1)
        v.addLayout(row)
        self.content_lay.addWidget(card)

    def _monthly_card(self, d: dict):
        from .life_page import BarChart
        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)
        v.setContentsMargins(20, 16, 20, 16)
        hl = QLabel(t(f"月度出片 · {self._year} 年",
                      f"Photos by month · {self._year}"))
        hl.setObjectName("CardTitle")
        v.addWidget(hl)
        chart = BarChart()
        chart.setMinimumHeight(190)
        series = [{"hour": m + 1, "total": d["monthly"][m]}
                  for m in range(12)]
        chart.set_series(series, x_month_mode=True)
        v.addWidget(chart, 1)
        self.content_lay.addWidget(card)

    def _highlights_card(self, d: dict):
        """年度之最: 拍摄最多物种/最忙一天(年度内)。"""
        year = self._year
        rows = self.lib.conn.execute(
            "SELECT v.eff_code, s.cn, s.en, COUNT(*) c FROM v_records v "
            "JOIN species s ON s.code=v.eff_code "
            "WHERE substr(v.taken_at,1,4)=? GROUP BY v.eff_code "
            "ORDER BY c DESC LIMIT 3", (year,)).fetchall()
        busy = self.lib.conn.execute(
            "SELECT substr(MIN(v.taken_at),1,10) d, COUNT(DISTINCT v.eff_code) c "
            "FROM v_records v WHERE substr(v.taken_at,1,4)=? "
            "GROUP BY substr(v.taken_at,1,10) ORDER BY c DESC LIMIT 1",
            (year,)).fetchone()
        if not rows and not busy:
            return
        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)
        v.setContentsMargins(18, 14, 18, 16)
        v.setSpacing(8)
        hl = QLabel(t("年度之最", "Year highlights"))
        hl.setObjectName("CardTitle")
        v.addWidget(hl)
        if rows:
            txt = "  ·  ".join(f"{sname(r['cn'], r['en'])}×{r['c']}"
                               for r in rows)
            lab = QLabel(t(f"📸 拍摄最多：{txt}", f"📸 Most shot: {txt}"))
            lab.setWordWrap(True)
            lab.setStyleSheet(f"font-size:13px;color:{theme.LABEL};"
                              "background:transparent;")
            v.addWidget(lab)
        if busy and busy["d"]:
            lab2 = QLabel(t(f"🔥 最忙一天：{busy['d']} · 新种 {busy['c']} 个",
                            f"🔥 Biggest day: {busy['d']} · "
                            f"{busy['c']} new species"))
            lab2.setStyleSheet(f"font-size:13px;color:{theme.LABEL};"
                               "background:transparent;")
            v.addWidget(lab2)
        self.content_lay.addWidget(card)

    # ---------- 动作 ----------
    def _export_pdf(self):
        if not self._year:
            return
        from .yearbook_pdf import export_yearbook_pdf
        export_yearbook_pdf(self.lib, self.win, self._year)
