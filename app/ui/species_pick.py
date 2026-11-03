# -*- coding: utf-8 -*-
"""全物种选择器: 默认展示完整鸟种列表, 输入即过滤(增量, 不重查库)。

搜索维度: 中文名 / 拼音全拼 / 拼音首字母(如 ysq) / 学名 / 英文名。
列表同时显示中英文名+学名, 便于跨语言查找(选择器不随语言裁剪)。
"""
from __future__ import annotations

import time

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout)

from ..i18n import t


class SpeciesPickDialog(QDialog):
    """选择一个鸟种, 经 selected_code 返回; 取消返回None。"""

    def __init__(self, lib, title: str | None = None, parent=None):
        super().__init__(parent)
        self.lib = lib
        self.selected_code: str | None = None
        self.setWindowTitle(title or t("选择鸟种", "Select a species"))
        self.setMinimumSize(560, 640)
        v = QVBoxLayout(self)
        v.setSpacing(10)

        self.search = QLineEdit()
        self.search.setPlaceholderText(t(
            "中文名 / 拼音 / 拼音首字母(ysq) / 学名 / 英文名…",
            "Chinese / pinyin / initials (ysq) / scientific / English…"))
        self.search.textChanged.connect(lambda _t: self._filter())
        # 键盘流(2026-10-31用户要求): 输入框内↑↓滚列表、回车确认——
        # 焦点在搜索框时列表收不到方向键, 必须在输入框侧接管转发。
        self.search.installEventFilter(self)
        v.addWidget(self.search)

        self.listw = QListWidget()
        self.listw.setUniformItemSizes(True)
        self.listw.itemDoubleClicked.connect(lambda _it: self._ok())
        self.listw.itemActivated.connect(lambda _it: self._ok())
        # 选中变化同步确定键——旧版_sync_ok无任何调用点, 确定键永远禁用,
        # "只能双击"的根因之一
        self.listw.itemSelectionChanged.connect(self._sync_ok)
        v.addWidget(self.listw, 1)

        self.hint = QLabel("")
        self.hint.setObjectName("Hint")
        v.addWidget(self.hint)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton(t("取消", "Cancel"))
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        self.ok_btn = QPushButton(t("确定", "OK"))
        self.ok_btn.setObjectName("Primary")
        self.ok_btn.setCursor(Qt.PointingHandCursor)
        self.ok_btn.setEnabled(False)
        self.ok_btn.clicked.connect(self._ok)
        btns.addWidget(self.ok_btn)
        v.addLayout(btns)
        for b in (cancel, self.ok_btn):
            b.setAutoDefault(False)
            b.setDefault(False)

        self._load_all()
        self.search.setFocus()

    # ---- 键盘流 ----
    def eventFilter(self, obj, ev):
        """搜索框内: ↑↓(及PgUp/PgDn)滚动候选, 回车=确认当前选中。"""
        if obj is self.search and ev.type() == QEvent.KeyPress:
            k = ev.key()
            n = self.listw.count()
            if k in (Qt.Key_Down, Qt.Key_Up, Qt.Key_PageDown, Qt.Key_PageUp):
                if n == 0:
                    return True
                row = self.listw.currentRow()
                step = 1 if k in (Qt.Key_Down, Qt.Key_Up) else 10
                if k in (Qt.Key_Down, Qt.Key_PageDown):
                    row = min(n - 1, row + step)
                else:
                    row = max(0, row - step)
                self.listw.setCurrentRow(row)
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self._ok()
                return True
        return super().eventFilter(obj, ev)

    # ---- 数据 ----
    def _load_all(self):
        self._all: list[tuple[str, str]] = []   # (展示文本, code)
        rows = self.lib.conn.execute(
            "SELECT code, cn, en, sci, family_cn, cn_pinyin, cn_initials, "
            "in_classifier FROM species "
            "ORDER BY in_classifier DESC, cn_pinyin, code").fetchall()
        guide_mark = t("（图鉴）", " · guide only")
        for r in rows:
            fam = f" · {r['family_cn']}" if r["family_cn"] else ""
            mark = "" if r["in_classifier"] else guide_mark
            text = f"{r['cn']}  {r['en']} · {r['sci']}{fam}{mark}"
            # 匹配键: 名称全拼+首字母+中英学名, 一次预拼好
            key = " ".join([r["cn"] or "", r["en"] or "", r["sci"] or "",
                            r["cn_pinyin"] or "", r["cn_initials"] or "",
                            r["family_cn"] or ""]).lower()
            self._all.append((text, r["code"], key))
        self._render([(t, c) for t, c, _k in self._all])
        self.hint.setText(t(f"全库 {len(self._all)} 种 · 输入即过滤 · ↑↓选择 · 回车/确定 选定",
                            f"{len(self._all)} species · type to filter, "
                            "↑↓ pick, Enter/OK confirm"))

    def _render(self, items):
        self.listw.clear()
        for text, code in items:
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, code)
            self.listw.addItem(it)
        if items:
            self.listw.setCurrentRow(0)
        self._sync_ok()

    def _filter(self):
        q = self.search.text().strip().lower()
        if not q:
            self._render([(t, c) for t, c, _k in self._all])
            self.hint.setText(t(
                f"全库 {len(self._all)} 种 · 输入即过滤 · ↑↓选择 · 回车/确定 选定",
                f"{len(self._all)} species · type to filter, "
                "↑↓ pick, Enter/OK confirm"))
            return
        hits = [(t, c) for t, c, k in self._all if q in k]
        cap = 300
        self._render(hits[:cap])
        if len(hits) > cap:
            self.hint.setText(t(
                f"匹配 {len(hits)} 种，仅显示前 {cap} 种，请继续输入",
                f"{len(hits)} matches — showing first {cap}, keep typing"))
        else:
            self.hint.setText(t(f"匹配 {len(hits)} 种", f"{len(hits)} matches"))

    # ---- 选择 ----
    def _sync_ok(self):
        self.ok_btn.setEnabled(self._selected_code() is not None)

    def _selected_code(self) -> str | None:
        it = self.listw.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _ok(self):
        code = self._selected_code()
        if code:
            self.selected_code = code
            self.accept()
