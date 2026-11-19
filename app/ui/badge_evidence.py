# -*- coding: utf-8 -*-
"""徽章证据弹窗(实测反馈9): 点徽章看它背后的照片/鸟种/鸟点清单,
点击条目直达(照片→查看器, 鸟种→详情页, 鸟点→地图)。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                               QScrollArea, QVBoxLayout, QWidget)

from .. import theme
from ..i18n import t
from ..media import cached_thumbnail, ensure_thumbnail


class BadgeEvidenceDialog(QDialog):
    def __init__(self, lib, win, badge_name: str, items: list[dict]):
        super().__init__(win)
        self.lib = lib
        self.win = win
        self.items = items
        self.setWindowTitle(t(f"🏆 {badge_name} · 达成证据",
                              f"🏆 {badge_name} · Evidence"))
        self.resize(560, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(8)
        n = len(items)
        hint = QLabel(t(
            f"共 {n} 项 · 点击任意一项直达",
            f"{n} item(s) · click any to jump"))
        hint.setObjectName("Hint")
        lay.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        v = QVBoxLayout(content)
        v.setContentsMargins(0, 0, 8, 8)
        v.setSpacing(4)
        for it in items[:120]:
            row = QFrame()
            row.setObjectName("Card")
            h = QHBoxLayout(row)
            h.setContentsMargins(10, 6, 10, 6)
            h.setSpacing(10)
            if it["kind"] == "photo":
                pic = QLabel()
                pic.setFixedSize(44, 34)
                pic.setAlignment(Qt.AlignCenter)
                pic.setStyleSheet(f"background:{theme.FILL};"
                                  "border-radius:6px;")
                r = lib.conn.execute(
                    "SELECT path, file_hash FROM photos WHERE id=?",
                    (it["id"],)).fetchone()
                if r and r["path"]:
                    tp = cached_thumbnail(lib.root, r["file_hash"], 88) \
                        or ensure_thumbnail(lib.root, r["path"],
                                            r["file_hash"], 88)
                    if tp:
                        pm = QPixmap(str(tp))
                        if not pm.isNull():
                            pic.setPixmap(pm.scaled(
                                pic.size(), Qt.KeepAspectRatioByExpanding,
                                Qt.SmoothTransformation))
                h.addWidget(pic)
                lab = QLabel(t(f"📷 第 {items.index(it) + 1} 张 · "
                               f"{it['label']}",
                               f"📷 #{items.index(it) + 1} · {it['label']}"))
            elif it["kind"] == "species":
                pic = QLabel("🐦")
                pic.setStyleSheet(f"font-size:20px;background:{theme.FILL};"
                                  "border-radius:6px;")
                pic.setAlignment(Qt.AlignCenter)
                pic.setFixedSize(44, 34)
                h.addWidget(pic)
                lab = QLabel(f"🐦 {it['label']}")
            else:
                pic = QLabel("📍")
                pic.setStyleSheet(f"font-size:20px;background:{theme.FILL};"
                                  "border-radius:6px;")
                pic.setAlignment(Qt.AlignCenter)
                pic.setFixedSize(44, 34)
                h.addWidget(pic)
                lab = QLabel(f"📍 {it['label']}")
            lab.setStyleSheet(f"font-size:13px;color:{theme.LABEL};"
                              "background:transparent;")
            lab.setWordWrap(True)
            h.addWidget(lab, 1)
            go = QLabel(t("查看 ›", "View ›"))
            go.setStyleSheet(f"color:{theme.BLUE};font-size:12px;"
                             "background:transparent;")
            h.addWidget(go)
            row.setCursor(Qt.PointingHandCursor)
            kind, iid = it["kind"], it["id"]
            row.mousePressEvent = lambda e, k=kind, p_id=iid: \
                self._goto(k, p_id)
            v.addWidget(row)
        v.addStretch(1)
        scroll.setWidget(content)
        lay.addWidget(scroll, 1)

    def _goto(self, kind: str, item_id):
        self.accept()
        if kind == "photo":
            from .viewer import PhotoViewer
            PhotoViewer(self.lib, self.win, item_id, [item_id]).exec()
        elif kind == "species":
            self.win.open_species(item_id)
        elif kind == "spot":
            self.win.switch_to("map")
