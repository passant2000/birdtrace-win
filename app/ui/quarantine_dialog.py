# -*- coding: utf-8 -*-
"""拒绝片隔离区(1.0冲刺⑨③): 预览清单→移入<库>/隔离区/<操作编号>/→
可随时恢复原路径。绝不覆盖同名(原路径被占则拒绝并提示); 不提供
永久删除——比回收站轻的可逆删除。照片记录/识别/评分全保留。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout)

from ..i18n import t
from .. import theme


class QuarantineDialog(QDialog):
    """顶部=待移入预览(多选时); 下方=已隔离清单+恢复。"""

    def __init__(self, lib, win, selected: list[int] | None = None):
        super().__init__(win)
        self.lib = lib
        self.win = win
        self.selected = list(selected or [])
        self.moved = False
        self.setWindowTitle(t("隔离区", "Quarantine"))
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint |
                            Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.resize(860, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(12)

        qdir = t("隔离区", "Quarantine")
        hint = QLabel(t(
            f"隔离=把照片文件移入库目录下的「{qdir}」文件夹并随时可恢复；"
            "识别、评分、标注全部保留。不提供永久删除——是否真删由你自己在"
            "文件管理器里决定。",
            f"Quarantine moves photo files into the library's \"{qdir}\" "
            "folder; restore anytime. Recognition, ratings and labels are "
            "kept. No permanent delete — decide that yourself in Explorer."))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size:13px;color:{theme.LABEL_2};"
                           "background:transparent;")
        lay.addWidget(hint)

        # 待移入预览(多选时)
        self.preview_tree = None
        self.move_btn = None
        if self.selected:
            rows = self._preview_rows()
            lab = QLabel(t(f"将移入 {len(rows)} / {len(self.selected)} 张"
                           "（源文件缺失或已在隔离区的自动跳过）",
                           f"Moving {len(rows)} / {len(self.selected)} "
                           "(missing or already quarantined skipped)"))
            lab.setStyleSheet(f"font-size:14px;font-weight:700;"
                              f"color:{theme.LABEL};background:transparent;")
            lay.addWidget(lab)
            self.preview_tree = QTreeWidget()
            self.preview_tree.setColumnCount(3)
            self.preview_tree.setHeaderLabels([
                t("文件", "File"), t("路径", "Path"),
                t("SHA-256 前段", "SHA-256 head")])
            self.preview_tree.setRootIsDecorated(False)
            self.preview_tree.header().setSectionResizeMode(
                1, QHeaderView.Stretch)
            for ph in rows:
                QTreeWidgetItem(self.preview_tree, [
                    Path(ph["path"]).name, ph["path"],
                    (ph["file_hash"] or "")[:16]])
            self.preview_tree.setMinimumHeight(140)
            lay.addWidget(self.preview_tree, 2)
            self.move_btn = QPushButton(t(
                f"移入隔离区（{len(rows)} 张）…",
                f"Move to quarantine ({len(rows)})…"))
            self.move_btn.setObjectName("Primary")
            self.move_btn.setCursor(Qt.PointingHandCursor)
            self.move_btn.clicked.connect(self._do_move)
            lay.addWidget(self.move_btn)

        # 已隔离清单
        lab2 = QLabel(t("已隔离（可恢复）", "Quarantined (restorable)"))
        lab2.setStyleSheet(f"font-size:14px;font-weight:700;"
                           f"color:{theme.LABEL};background:transparent;")
        lay.addWidget(lab2)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels([
            t("文件", "File"), t("原路径", "Original path"),
            t("操作编号", "Operation"), t("移入时间", "Moved at"),
            t("SHA-256 前段", "SHA-256 head")])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        lay.addWidget(self.tree, 3)

        btns = QHBoxLayout()
        self.restore_btn = QPushButton(t("恢复所选到原路径", "Restore selected"))
        self.restore_btn.setObjectName("Primary")
        self.restore_btn.setCursor(Qt.PointingHandCursor)
        self.restore_btn.clicked.connect(self._do_restore)
        btns.addWidget(self.restore_btn)
        btns.addStretch(1)
        close_btn = QPushButton(t("关闭", "Close"))
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        btns.addWidget(close_btn)
        lay.addLayout(btns)

        self._reload()

    def _preview_rows(self) -> list[dict]:
        out = []
        for pid in self.selected:
            r = self.lib.conn.execute(
                "SELECT path, file_hash FROM photos WHERE id=?",
                (pid,)).fetchone()
            if not r:
                continue
            q = self.lib.conn.execute(
                "SELECT 1 FROM quarantine WHERE photo_id=? AND restored_at "
                "IS NULL", (pid,)).fetchone()
            if q:
                continue
            out.append({"id": pid, "path": r["path"],
                        "file_hash": r["file_hash"]})
        return out

    def _reload(self):
        self.tree.clear()
        for q in self.lib.quarantine_list():
            QTreeWidgetItem(self.tree, [
                Path(q["quar_path"]).name, q["orig_path"], q["op_no"],
                q["moved_at"], (q["file_hash"] or "")[:16]])
        if not self.tree.topLevelItemCount():
            QTreeWidgetItem(self.tree, [
                t("（隔离区为空）", "(quarantine is empty)"), "", "", "", ""])

    def _do_move(self):
        rows = self._preview_rows()
        if not rows:
            QMessageBox.information(self, t("隔离区", "Quarantine"),
                                    t("没有可移入的文件。", "Nothing to move."))
            return
        if QMessageBox.question(
                self, t("移入隔离区", "Move to quarantine"),
                t(f"将把 {len(rows)} 张照片文件移入库目录下的「隔离区」"
                  "（识别/评分/标注保留，随时可恢复）。继续？",
                  f"Move {len(rows)} photo file(s) into the library "
                  "quarantine folder (recognition/ratings/labels kept, "
                  "restorable anytime). Continue?")) != QMessageBox.Yes:
            return
        res = self.lib.quarantine_move([r["id"] for r in rows])
        if res["failed"]:
            detail = "\n".join(f"photo#{pid}: {why}" for pid, why in res["failed"])
            QMessageBox.warning(self, t("部分失败", "Partially failed"),
                                t(f"{len(res['moved'])} 张已移入，"
                                  f"{len(res['failed'])} 张失败：\n{detail}",
                                  f"{len(res['moved'])} moved, "
                                  f"{len(res['failed'])} failed:\n{detail}"))
        self.moved = bool(res["moved"])
        self._reload()

    def _do_restore(self):
        items = self.tree.selectedItems()
        qids = []
        for it in items:
            q = self.lib.conn.execute(
                "SELECT id FROM quarantine WHERE op_no=? AND orig_path=? "
                "AND restored_at IS NULL",
                (it.text(2), it.text(1))).fetchone()
            if q:
                qids.append(q["id"])
        if not qids:
            return
        res = self.lib.quarantine_restore(qids)
        if res["failed"]:
            detail = "\n".join(str(why) for _, why in res["failed"])
            QMessageBox.warning(self, t("恢复", "Restore"),
                                t(f"以下条目恢复失败（原路径被占用时绝不覆盖，"
                                  f"请先处理原路径的文件）：\n{detail}",
                                  "Restore failed (never overwrites files "
                                  f"at the original path):\n{detail}"))
        self._reload()
