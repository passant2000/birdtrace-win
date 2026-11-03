# -*- coding: utf-8 -*-
"""待复核页: 低置信度/整图兜底记录, 人工确认或纠正鸟种。"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..i18n import t, sname
from ..media import ensure_thumbnail
from .. import theme


class ReviewPage(QWidget):
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
        self.title = QLabel(t("待复核", "Pending review"))
        self.title.setStyleSheet("font-size:26px;font-weight:800;color:#1C1C1E;"
                                 "background:transparent;")
        head.addWidget(self.title)
        head.addStretch(1)
        tip = QLabel(t("识别没把握的照片在这里确认或纠正, 结果计入成就统计",
                       "Confirm or correct photos the recognizer is unsure "
                       "about here; results count toward achievement stats"))
        tip.setObjectName("Hint")
        head.addWidget(tip)
        lay.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.content_lay = QVBoxLayout(self.content)
        self.content_lay.setContentsMargins(0, 0, 16, 24)
        self.content_lay.setSpacing(8)
        self.scroll.setWidget(self.content)
        lay.addWidget(self.scroll, 1)

    def refresh(self):
        while self.content_lay.count():
            it = self.content_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        queue = self.lib.review_queue()
        self.title.setText(t(f"待复核 · {len(queue)} 张", f"Pending review · {len(queue)}"))
        if not queue:
            done = QLabel(t("全部处理完毕 🎉", "All caught up 🎉"))
            done.setAlignment(Qt.AlignCenter)
            done.setStyleSheet("color:#34C759;font-size:15px;padding:60px;"
                               "background:transparent;")
            self.content_lay.addWidget(done)
            return
        for item in queue:
            self.content_lay.addWidget(self._row(item))
        self.content_lay.addStretch(1)

    def _row(self, item: dict) -> QWidget:
        card = QWidget()
        h = QHBoxLayout(card)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(14)
        card.setStyleSheet(
            f"QWidget{{background:{theme.CARD};border-radius:14px;"
            f"border:1px solid {theme.CARD_BORDER};}}")

        cover = QLabel()
        cover.setFixedSize(72, 72)
        cover.setAlignment(Qt.AlignCenter)
        cover.setStyleSheet(f"background:{theme.FILL};border-radius:10px;")
        row = self.lib.conn.execute(
            "SELECT file_hash FROM photos WHERE id=?", (item["photo_id"],)).fetchone()
        if row:
            tp = ensure_thumbnail(self.lib.root, item["path"], row["file_hash"], 160)
            if tp:
                pm = QPixmap(str(tp))
                cover.setPixmap(pm.scaled(72, 72, Qt.KeepAspectRatioByExpanding,
                                          Qt.SmoothTransformation))
        h.addWidget(cover)

        info = QVBoxLayout()
        name = QLabel(sname(item["cn"], item["en"]))
        name.setStyleSheet("font-size:15px;font-weight:700;background:transparent;")
        info.addWidget(name)
        sub = QLabel(t(f"{(item['taken_at'] or '')[:16]}   置信度 "
                       f"{item['confidence']*100:.0f}%",
                       f"{(item['taken_at'] or '')[:16]}   Confidence "
                       f"{item['confidence']*100:.0f}%")
                     + ("   " + t("整图推断", "Whole-image inference")
                        if item["source"] == "whole" else ""))
        sub.setStyleSheet(f"font-size:12px;color:{theme.LABEL_3};background:transparent;")
        info.addWidget(sub)
        h.addLayout(info, 1)

        combo = QComboBox()
        combo.setMinimumWidth(230)
        # 选项: 识别top5 + 最近确认过的物种快捷项
        combo.addItem(f"{sname(item['cn'], item['en'])}{t('（保持）', ' (keep)')}",
                      item["code"])
        rec = self.lib.conn.execute(
            "SELECT top5_json FROM records WHERE id=?",
            (item["record_id"],)).fetchone()
        seen = {item["code"]}
        try:
            top5 = json.loads(rec["top5_json"] or "[]") if rec else []
        except (TypeError, json.JSONDecodeError):
            top5 = []
        for cand in top5:
            if cand["code"] not in seen:
                s = self.lib.species_info(cand["code"])
                if s:
                    combo.addItem(f"{sname(s['cn'], s['en'])}  {cand['prob']*100:.0f}%",
                                  cand["code"])
                    seen.add(cand["code"])
        recent = self.lib.conn.execute(
            "SELECT eff_code AS code, s.cn, s.en FROM v_records v JOIN species s ON s.code=v.eff_code "
            "WHERE v.confirmed_code IS NOT NULL GROUP BY eff_code ORDER BY MAX(v.taken_at) "
            "DESC LIMIT 20").fetchall()
        for r in recent:
            if r["code"] not in seen:
                combo.addItem(f"{sname(r['cn'], r['en'])}{t('（最近）', ' (recent)')}",
                              r["code"])
                seen.add(r["code"])
        h.addWidget(combo)

        ok = QPushButton(t("确认", "Confirm"))
        ok.setCursor(Qt.PointingHandCursor)
        ok.clicked.connect(lambda _=False, it=item, cb=combo: self._confirm(it, cb))
        h.addWidget(ok)

        notbird = QPushButton(t("不是鸟", "Not a bird"))
        notbird.setCursor(Qt.PointingHandCursor)
        notbird.setToolTip(t("这张里没有鸟（如蛇/其他动物误检）——移到「未识别」",
                             "No bird in this photo (e.g. a snake or other "
                             "animal) — move it to \"Unidentified\""))
        notbird.clicked.connect(lambda _=False, it=item: self._not_bird(it))
        h.addWidget(notbird)

        view = QPushButton(t("查看", "View"))
        view.setCursor(Qt.PointingHandCursor)
        view.clicked.connect(lambda _=False, it=item: self._view(it))
        h.addWidget(view)
        return card

    def _confirm(self, item: dict, combo: QComboBox):
        code = combo.currentData()
        if code:
            self.lib.set_confirmed(item["record_id"], code)
            self.refresh()
            self.win.library_changed.emit()

    def _not_bird(self, item: dict):
        from PySide6.QtWidgets import QMessageBox
        r = QMessageBox.question(
            self, t("移到「未识别」", "Move to Unidentified"),
            t("确认这张照片里没有鸟？\n它会从「待复核」移到「未识别」，"
              "以后仍可重新识别或手工标注。",
              "No bird in this photo?\nIt will move from \"Pending review\" "
              "to \"Unidentified\"; you can still re-identify or annotate "
              "it later."))
        if r == QMessageBox.StandardButton.Yes:
            self.lib.mark_not_bird(item["photo_id"])
            self.refresh()
            self.win.library_changed.emit()

    def _view(self, item: dict):
        from .viewer import PhotoViewer
        dlg = PhotoViewer(self.lib, self.win, item["photo_id"], [item["photo_id"]])
        dlg.exec()
        self.refresh()
