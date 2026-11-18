# -*- coding: utf-8 -*-
"""视觉查重(1.0冲刺③): 两层候选——完全相同文件(SHA-256 跨月)+
画面相似(同月 dHash 汉距≤8)。只列候选, 移除必须人工确认; 移除
=删库记录+缩略图, 原始文件绝不动(remove_photo 既有语义)。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout)

from .. import theme
from ..i18n import t


class DupDialog(QDialog):
    def __init__(self, lib, win):
        super().__init__(win)
        self.lib = lib
        self.setWindowTitle(t("视觉查重", "Find duplicates"))
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint |
                            Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.resize(820, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)

        self.summary = QLabel(t("正在扫描…", "Scanning…"))
        self.summary.setStyleSheet(f"font-size:14px;font-weight:700;"
                                   f"color:{theme.LABEL};background:transparent;")
        lay.addWidget(self.summary)
        hint = QLabel(t(
            "两层候选：①完全相同文件（内容哈希一致，含重复导入）；"
            "②画面相似（同月内感知哈希汉距≤8，不同裁切/重新导出）。"
            "相似照片≠重复照片——是否移除由你逐组确认；"
            "移除只删鸟迹记录，原始文件绝不动。",
            "Two layers: (1) identical files (same content hash, incl. "
            "re-imports); (2) visually similar (same month, perceptual "
            "distance ≤8). Similar is not duplicate — confirm each group "
            "yourself. Removing deletes the BirdTrace record only, the "
            "original file is never touched."))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size:12px;color:{theme.LABEL_2};"
                           "background:transparent;")
        lay.addWidget(hint)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([t("照片", "Photo"), t("路径", "Path")])
        self.tree.setRootIsDecorated(True)
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        lay.addWidget(self.tree, 1)

        btns = QHBoxLayout()
        self.rm_btn = QPushButton(t("移除所选记录…", "Remove selected…"))
        self.rm_btn.setObjectName("Primary")
        self.rm_btn.setCursor(Qt.PointingHandCursor)
        self.rm_btn.clicked.connect(self._remove_selected)
        btns.addWidget(self.rm_btn)
        btns.addStretch(1)
        close_btn = QPushButton(t("关闭", "Close"))
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        btns.addWidget(close_btn)
        lay.addLayout(btns)

        self._scan()

    def _scan(self):
        self.tree.clear()
        try:
            res = self.lib.find_duplicates()
        except Exception as e:
            self.summary.setText(t(f"扫描失败: {e}", f"Scan failed: {e}"))
            return
        ne, ns = len(res["exact"]), len(res["similar"])
        self.summary.setText(t(
            f"扫描 {res['scanned']} 张：完全相同 {ne} 组 · 画面相似 {ns} 组",
            f"Scanned {res['scanned']}: {ne} identical · {ns} similar"))
        if not ne and not ns:
            QTreeWidgetItem(self.tree, [t("未发现重复候选", "No duplicates found"), ""])
            self.rm_btn.setEnabled(False)
            return
        self.rm_btn.setEnabled(True)

        def add_group(top, ids):
            node = QTreeWidgetItem(top, [t(f"{len(ids)} 张", f"{len(ids)} photos"),
                                         ""])
            node.setExpanded(True)
            for pid in ids:
                r = self.lib.conn.execute(
                    "SELECT path FROM photos WHERE id=?", (pid,)).fetchone()
                if not r:
                    continue
                child = QTreeWidgetItem(node, [
                    f"#{pid} {Path(r['path']).name}", r["path"]])
                child.setData(0, Qt.UserRole, pid)

        top1 = QTreeWidgetItem(self.tree, [t("① 完全相同文件", "① Identical files"),
                                           ""])
        top1.setExpanded(True)
        for ids in res["exact"]:
            add_group(top1, ids)
        top2 = QTreeWidgetItem(self.tree, [t("② 画面相似（同月）",
                                               "② Similar (same month)"), ""])
        top2.setExpanded(True)
        for ids in res["similar"]:
            add_group(top2, ids)

    def _selected_ids(self) -> list[int]:
        out = []
        for it in self.tree.selectedItems():
            pid = it.data(0, Qt.UserRole)
            if pid:
                out.append(pid)
        return out

    def _remove_selected(self):
        ids = self._selected_ids()
        if not ids:
            return
        r = QMessageBox.question(
            self, t("从鸟迹移除", "Remove from BirdTrace"),
            t(f"移除选中的 {len(ids)} 条记录？\n\n"
              "只删鸟迹记录与缩略图缓存，原始文件绝不会被移动或删除。",
              f"Remove {len(ids)} record(s)?\n\nOnly the BirdTrace record "
              "and thumbnail cache are deleted; original files are never "
              "touched."),
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        for pid in ids:
            self.lib.remove_photo(pid)
        if hasattr(self.win, "library_changed"):
            try:
                self.win.library_changed.emit()
            except RuntimeError:
                pass
        self._scan()
