# -*- coding: utf-8 -*-
"""照片级版权三态编辑(UI重设计c6, 补⑰照片级UI缺口):
五字段(创作者/版权所有者/版权声明/署名行/使用条款), 每字段三态——
留空=继承库级默认 · 填写=覆盖 · ∅置空=明确不用默认(即使默认有值)。
保存走现成 set_photo_copyright(值=覆盖/None=置空/缺省=继承), db零改动。
入口: 查看器右栏「版权…」。"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout)

from .. import theme
from ..i18n import t

# (字段键, 标签(中,英))——键与 db.CP_FIELDS/settings_page 同源
FIELDS = [
    ("creator", ("创作者", "Creator")),
    ("copyright_owner", ("版权所有者", "Owner")),
    ("copyright_notice", ("版权声明", "Notice")),
    ("credit_line", ("署名行", "Credit line")),
    ("rights_usage_terms", ("使用条款", "Usage terms")),
]


class CopyrightDialog(QDialog):
    def __init__(self, lib, win, photo_id: int):
        super().__init__(win)
        self.lib = lib
        self.photo_id = photo_id
        self.changed = False
        self.setWindowTitle(t("版权信息（本照片）", "Copyright (this photo)"))
        self.resize(520, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(8)

        defaults = lib.copyright_defaults_get()
        row = self.conn_row = lib.conn.execute(
            "SELECT cp_json FROM photos WHERE id=?", (photo_id,)).fetchone()
        over: dict = {}
        if row and row["cp_json"]:
            try:
                got = json.loads(row["cp_json"])
                if isinstance(got, dict):
                    over = got
            except ValueError:
                over = {}

        self.edits: dict[str, QLineEdit] = {}
        self.clears: dict[str, QPushButton] = {}
        intro = QLabel(t(
            "留空=继承库级默认；填写=本照片覆盖；∅ 置空=明确不使用默认。"
            "只记在鸟迹库与 sidecar，不改原图 EXIF。",
            "Empty = inherit library defaults; type = override for this "
            "photo; ∅ = explicitly none. Stored in the library and sidecar "
            "only, original EXIF never touched."))
        intro.setWordWrap(True)
        intro.setObjectName("Hint")
        lay.addWidget(intro)
        lay.addSpacing(4)

        for key, name in FIELDS:
            r = QHBoxLayout()
            lab = QLabel(t(*name))
            lab.setObjectName("RowLabel")
            lab.setMinimumWidth(76)
            r.addWidget(lab)
            e = QLineEdit()
            default_val = defaults.get(key, "")
            if key in over:
                if over[key] is None:
                    e.setText("")
                    e.setEnabled(False)
                else:
                    e.setText(str(over[key]))
            else:
                e.setPlaceholderText(
                    default_val and
                    t(f"继承默认：{default_val}", f"inherits: {default_val}")
                    or t("（继承库级默认）", "(inherits library default)"))
            self.edits[key] = e
            r.addWidget(e, 1)
            c = QPushButton(t("∅ 置空", "∅ none"))
            c.setCheckable(True)
            c.setCursor(Qt.PointingHandCursor)
            c.setToolTip(t("明确置空：本照片不使用库级默认值",
                           "Explicitly blank: this photo ignores the "
                           "library default"))
            c.setChecked(key in over and over[key] is None)
            def _sync(checked, _k=key):
                self.edits[_k].setEnabled(not checked)
            c.toggled.connect(_sync)
            self.clears[key] = c
            r.addWidget(c)
            lay.addLayout(r)

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

    def _save(self):
        overrides: dict = {}
        for key, _name in FIELDS:
            if self.clears[key].isChecked():
                overrides[key] = None          # 明确置空
            else:
                val = self.edits[key].text().strip()
                if val:
                    overrides[key] = val       # 覆盖
                # 空=继承: 不进 overrides
        self.lib.set_photo_copyright(self.photo_id, overrides)
        self.changed = True
        self.accept()
