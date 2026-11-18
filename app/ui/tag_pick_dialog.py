# -*- coding: utf-8 -*-
"""标签/作品集编辑(1.0冲刺⑭⑮): 单照片的标签勾选+新建(扁平无层级,
用户数据不翻译)与作品集勾选+新建; 整批差量同步。查看器右栏进入。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout)

from .. import theme
from ..i18n import t


class TagPickDialog(QDialog):
    def __init__(self, lib, win, photo_id: int):
        super().__init__(win)
        self.lib = lib
        self.photo_id = photo_id
        self.changed = False
        self.setWindowTitle(t("标签与作品集", "Tags & collections"))
        self.resize(420, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(8)

        lay.addWidget(QLabel(t("标签（可勾选已有，或输入新名回车）",
                               "Tags (check existing, or type a new name)")))
        self.tag_checks: dict[int, QCheckBox] = {}
        have = set(self.lib.tags_of(photo_id))
        for tg in self.lib.tags_list():
            cb = QCheckBox(f"{tg['name']} ({tg['n']})")
            cb.setChecked(tg["name"] in have)
            self.tag_checks[tg["id"]] = cb
            lay.addWidget(cb)
        new_row = QHBoxLayout()
        self.new_edit = QLineEdit()
        self.new_edit.setPlaceholderText(t("新标签名，回车添加",
                                           "New tag name, Enter to add"))
        self.new_edit.returnPressed.connect(self._add_tag)
        new_row.addWidget(self.new_edit, 1)
        lay.addLayout(new_row)

        lay.addSpacing(8)
        lay.addWidget(QLabel(t("作品集（勾选=属于该集）",
                               "Collections (check to belong)")))
        self.col_checks: dict[int, QCheckBox] = {}
        have_cols = {c["id"] for c in self.lib.collections_of(photo_id)}
        for c in self.lib.collections_list():
            cb = QCheckBox(f"{c['name']} ({c['n']})")
            cb.setChecked(c["id"] in have_cols)
            self.col_checks[c["id"]] = cb
            lay.addWidget(cb)
        new_row2 = QHBoxLayout()
        self.col_edit = QLineEdit()
        self.col_edit.setPlaceholderText(t("新作品集名，回车添加",
                                           "New collection name, Enter"))
        self.col_edit.returnPressed.connect(self._add_collection)
        new_row2.addWidget(self.col_edit, 1)
        lay.addLayout(new_row2)

        lay.addStretch(1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        ok = QPushButton(t("保存", "Save"))
        ok.setObjectName("Primary")
        ok.setCursor(Qt.PointingHandCursor)
        ok.clicked.connect(self._save)
        btns.addWidget(ok)
        cancel = QPushButton(t("取消", "Cancel"))
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        lay.addLayout(btns)

    def _add_tag(self):
        name = self.new_edit.text().strip()
        if not name:
            return
        tid = self.lib.tag_create(name)
        if tid not in self.tag_checks:
            cb = QCheckBox(f"{name} (0)")
            cb.setChecked(True)
            self.tag_checks[tid] = cb
            self.new_edit.clear()
            lay = self.layout()
            lay.insertWidget(lay.indexOf(self.new_edit.parentWidget()), cb)
        else:
            self.tag_checks[tid].setChecked(True)
            self.new_edit.clear()

    def _add_collection(self):
        name = self.col_edit.text().strip()
        if not name:
            return
        cid = self.lib.collection_create(name)
        if cid not in self.col_checks:
            cb = QCheckBox(f"{name} (0)")
            cb.setChecked(True)
            self.col_checks[cid] = cb
            self.col_edit.clear()
            lay = self.layout()
            lay.insertWidget(lay.indexOf(self.col_edit.parentWidget()), cb)
        else:
            self.col_checks[cid].setChecked(True)
            self.col_edit.clear()

    def _save(self):
        names = [cb.text().rsplit(" (", 1)[0] for cb in
                 self.tag_checks.values() if cb.isChecked()]
        self.lib.photo_tags_set(self.photo_id, names)
        want = [cid for cid, cb in self.col_checks.items() if cb.isChecked()]
        # 作品集: 勾选的加入(追加), 取消勾选的移出本照片
        cur = {c["id"] for c in self.lib.collections_of(self.photo_id)}
        for cid in want:
            if cid not in cur:
                mem = self.lib.collection_photos_of(cid)
                self.lib.collection_set_photos(cid, mem + [self.photo_id])
        for cid in set(cur) - set(want):
            mem = self.lib.collection_photos_of(cid)
            self.lib.collection_set_photos(
                cid, [p for p in mem if p != self.photo_id])
        self.changed = True
        self.accept()
