# -*- coding: utf-8 -*-
"""批量分享卡导出(0.8-⑥): 日期范围(+可选鸟种) → 每鸟种一张"最美"落盘。

"最美" = 美学分 × 置信度 最高, 且只取已确认或原始置信≥0.5的记录
(待复核错名不印进卡, 选取逻辑在 db.best_share_cards)。主题/署名/Life#/
拍摄参数 = 一次批量设置, 对整批生效(用户定"弹一次"——即本对话框的样式卡,
不做逐卡设置)。渲染复用 render_card 纯函数循环调用。

文件名: 拍摄日期_鸟种名.png; 原图离线的候选跳过并在结果中说明。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QComboBox, QDateEdit, QDialog, QFileDialog,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QProgressBar, QPushButton, QVBoxLayout)

from .. import theme
from ..core import regions
from ..core.sharecard import render_card
from ..i18n import t, sname
from ..theme.widgets import SegmentedControl, ToggleSwitch, make_card
from .share_dialog import exif_parts_of, pinyin_spaced, rarity_info


def _safe_name(s: str) -> str:
    """鸟种名 → 文件名安全串(鸟种名可能含"/"、空格等)。"""
    return re.sub(r'[\\/:*?"<>|\s]+', "_", s).strip("_") or "card"


class BatchShareDialog(QDialog):
    def __init__(self, lib, win):
        super().__init__(win)
        self.lib = lib
        self.win = win
        self._exported: list[Path] = []
        self.setWindowTitle(t("批量分享卡", "Batch share cards"))
        self.setModal(True)
        self.setMinimumWidth(560)
        self._build_ui()
        self._update_count()

    # ---------- UI ----------
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(12)

        range_card, rc = make_card(t("范围", "Range"))
        qrow = QHBoxLayout()
        qrow.addWidget(QLabel(t("快捷", "Quick")))
        self.quick_seg = SegmentedControl(
            [t("今天", "Today"), t("近7天", "Last 7d"), t("本月", "This month"),
             t("今年", "This year"), t("全部", "All")])
        self.quick_seg.changed.connect(self._apply_quick)
        qrow.addWidget(self.quick_seg, 1)
        rc.addLayout(qrow)

        drow = QHBoxLayout()
        drow.addWidget(QLabel(t("日期从", "From")))
        today = QDate.currentDate()
        self.from_date = QDateEdit(today)
        self.from_date.setCalendarPopup(True)
        self.from_date.setDisplayFormat("yyyy-MM-dd")
        drow.addWidget(self.from_date)
        self.from_year = QComboBox()
        self.from_year.setMaximumWidth(86)
        drow.addWidget(self.from_year)
        drow.addSpacing(12)
        drow.addWidget(QLabel(t("到", "to")))
        self.to_date = QDateEdit(today)
        self.to_date.setCalendarPopup(True)
        self.to_date.setDisplayFormat("yyyy-MM-dd")
        drow.addWidget(self.to_date)
        self.to_year = QComboBox()
        self.to_year.setMaximumWidth(86)
        drow.addWidget(self.to_year)
        drow.addStretch(1)
        rc.addLayout(drow)

        # 年份下拉: QDateEdit转轮/日历翻页调年份很费劲(用户2026-11-04),
        # 年份一点直达; 日期手动改动时同步回显(信号防回环)
        years = sorted({str(y) for y in self.lib.available_years()}
                       | {str(today.year())}, reverse=True)
        for combo in (self.from_year, self.to_year):
            combo.addItem(t("年份…", "Year…"))
            for y in years:
                combo.addItem(y)
            combo.activated.connect(
                self._on_year_combo if combo is self.from_year
                else self._on_year_combo_to)
        self.from_date.dateChanged.connect(lambda q: self._sync_year_combo())
        self.to_date.dateChanged.connect(lambda q: self._sync_year_combo())

        srow = QHBoxLayout()
        srow.addWidget(QLabel(t("鸟种", "Species")))
        # 每种张数(2026-11-04用户: 可选多张, 不足几张出几张)
        self.per_combo = QComboBox()
        for n in (1, 2, 3, 4):
            self.per_combo.addItem(t(f"每种 {n} 张", f"{n} per species"), n)
        self.per_combo.currentIndexChanged.connect(lambda _i: self._update_count())
        srow.addWidget(self.per_combo)
        self.species_combo = QLineEdit()
        self.species_combo.setReadOnly(True)
        srow.addWidget(self.species_combo, 1)
        b_pick = QPushButton(t("选择…", "Choose…"))
        b_pick.setCursor(Qt.PointingHandCursor)
        b_pick.clicked.connect(self._pick_species)
        srow.addWidget(b_pick)
        b_clear = QPushButton(t("清除", "Clear"))
        b_clear.setCursor(Qt.PointingHandCursor)
        b_clear.clicked.connect(self._clear_species)
        srow.addWidget(b_clear)
        rc.addLayout(srow)

        orow = QHBoxLayout()
        orow.addWidget(QLabel(t("导出到", "Export to")))
        self.dir_edit = QLineEdit(str(self._default_dir()))
        orow.addWidget(self.dir_edit, 1)
        b_dir = QPushButton(t("浏览…", "Browse…"))
        b_dir.setCursor(Qt.PointingHandCursor)
        b_dir.clicked.connect(self._browse_dir)
        orow.addWidget(b_dir)
        rc.addLayout(orow)

        self.count_hint = QLabel()
        self.count_hint.setObjectName("Hint")
        self.count_hint.setWordWrap(True)
        rc.addWidget(self.count_hint)
        lay.addWidget(range_card)

        style_card, sc = make_card(t("卡片样式（对整批生效）",
                                     "Card style (applies to the batch)"))
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel(t("主题", "Theme")))
        self.theme_seg = SegmentedControl([t("浅色", "Light"), t("深色", "Dark")])
        theme_row.addWidget(self.theme_seg, 1)
        sc.addLayout(theme_row)

        life_row = QHBoxLayout()
        life_row.addWidget(QLabel(t("显示 Life # 序号", "Show Life #")))
        self.lifer_toggle = ToggleSwitch(True)
        life_row.addStretch(1)
        life_row.addWidget(self.lifer_toggle)
        sc.addLayout(life_row)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(t("拍摄者", "Photographer")))
        self.name_edit = QLineEdit(self.lib.get_setting("photographer_name", ""))
        self.name_edit.setPlaceholderText(t("留空则用照片EXIF署名",
                                            "Empty = use photo EXIF artist"))
        name_row.addWidget(self.name_edit, 1)
        sc.addLayout(name_row)

        exif_row = QHBoxLayout()
        exif_row.addWidget(QLabel(t("拍摄参数", "Camera data")))
        self.exif_toggle = ToggleSwitch(True)
        exif_row.addStretch(1)
        exif_row.addWidget(self.exif_toggle)
        sc.addLayout(exif_row)
        lay.addWidget(style_card)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        lay.addWidget(self.progress)

        row = QHBoxLayout()
        self.open_btn = QPushButton(t("打开导出文件夹", "Open export folder"))
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.clicked.connect(self._open_dir)
        self.open_btn.setVisible(False)
        row.addWidget(self.open_btn)
        row.addStretch(1)
        self.go_btn = QPushButton(t("开始导出", "Start export"))
        self.go_btn.setObjectName("Primary")
        self.go_btn.setCursor(Qt.PointingHandCursor)
        self.go_btn.clicked.connect(self._export)
        row.addWidget(self.go_btn)
        lay.addLayout(row)

        # 信号 → 计数刷新
        self.from_date.dateChanged.connect(lambda _q: self._update_count())
        self.to_date.dateChanged.connect(lambda _q: self._update_count())

    def _default_dir(self) -> Path:
        """默认导出目录(导出时才创建, 构造不落盘)。"""
        return Path.home() / "Pictures" / t("BirdTrace分享卡", "BirdTrace Cards")

    # ---------- 范围选择 ----------
    def _apply_quick(self, idx: int):
        """快捷范围: 今天/近7天/本月/今年/全部(2000-01-01起)。"""
        today = QDate.currentDate()
        spans = {
            0: (today, today),
            1: (today.addDays(-6), today),
            2: (QDate(today.year(), today.month(), 1), today),
            3: (QDate(today.year(), 1, 1), today),
            4: (QDate(2000, 1, 1), today),
        }
        d1, d2 = spans.get(idx, (today, today))
        self.from_date.setDate(d1)
        self.to_date.setDate(d2)

    def _on_year_combo(self, idx: int):
        self._year_apply(self.from_date, self.from_year, idx)

    def _on_year_combo_to(self, idx: int):
        self._year_apply(self.to_date, self.to_year, idx)

    def _year_apply(self, edit: QDateEdit, combo: QComboBox, idx: int):
        """年份下拉: 只换年份部分(月日保持, 2/29→2/28由QDate钳制)。"""
        y = combo.itemText(idx)
        if not y.isdigit():
            return
        d = edit.date()
        edit.setDate(QDate(int(y), d.month(), d.day()))

    def _sync_year_combo(self):
        """日期手动改动 → 年份下拉回显(防信号回环)。"""
        for edit, combo in ((self.from_date, self.from_year),
                            (self.to_date, self.to_year)):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            y = str(edit.date().year())
            for i in range(combo.count()):
                if combo.itemText(i) == y:
                    combo.setCurrentIndex(i)
                    break
            combo.blockSignals(False)

    def _pick_species(self):
        from .species_pick import SpeciesPickDialog
        dlg = SpeciesPickDialog(self.lib, t("选择鸟种", "Choose species"), self)
        if dlg.exec() and dlg.selected_code:
            info = self.lib.species_info(dlg.selected_code)
            self.species_combo.setProperty("code", dlg.selected_code)
            self.species_combo.setText(
                sname(info["cn"], info["en"]) if info else dlg.selected_code)
            self._update_count()

    def _clear_species(self):
        self.species_combo.setProperty("code", None)
        self.species_combo.setText("")
        self._update_count()

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, t("选择导出文件夹",
                                                     "Choose export folder"),
                                             self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)

    def _selected_code(self) -> str | None:
        return self.species_combo.property("code") or None

    def _update_count(self):
        d1 = self.from_date.date().toString("yyyy-MM-dd")
        d2 = self.to_date.date().toString("yyyy-MM-dd")
        try:
            cands = self.lib.best_share_cards(d1, d2, self._selected_code(),
                                              self.per_combo.currentData() or 1)
        except Exception:
            cands = []
        n = len(cands)
        self.count_hint.setText(t(
            f"共 {n} 张（每鸟种 {self.per_combo.currentData() or 1} 张「最美」："
            "美学×置信，仅已确认或置信≥0.5）",
            f"{n} cards ({self.per_combo.currentData() or 1} “best” per "
            "species: aesthetic × confidence; confirmed or ≥ 0.5 only)"))

    # ---------- 导出 ----------
    def _card_info(self, row: dict) -> dict:
        code = row["eff_code"]
        title = sname(row["cn"], row["en_name"])
        pys = pinyin_spaced(title)
        if len(pys) != len(title):   # 非逐字汉字(英文名)不叠画拼音
            pys = []
        rid = row.get("region_id")
        rarity, pct = rarity_info(code, rid)
        photographer = self.name_edit.text().strip() or \
            (row.get("artist") or "").strip()
        return {
            "cn": title,
            "pinyin": pys,
            "en": row["en_name"] or "",
            "sci": row["sci"] or "",
            "lifer_no": self.lib.lifer_no_for_species(code)
                        if self.lifer_toggle.isChecked() else None,
            "rarity": rarity,
            "rarity_pct": pct,
            "photographer": photographer,
            "date": (row.get("taken_at") or "")[:10],
            "place": regions.region_display(rid)
                      if rid and rid != "GLOBAL" else "",
            "exif": exif_parts_of(row) if self.exif_toggle.isChecked() else {},
        }

    def _export(self):
        d1 = self.from_date.date().toString("yyyy-MM-dd")
        d2 = self.to_date.date().toString("yyyy-MM-dd")
        cands = self.lib.best_share_cards(
            d1, d2, self._selected_code(), self.per_combo.currentData() or 1)
        if not cands:
            QMessageBox.information(self, t("批量分享卡", "Batch share cards"),
                                    t("该范围内没有可出卡的照片",
                                      "No eligible photos in this range"))
            return
        out_dir = Path(self.dir_edit.text().strip())
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        if not out_dir.is_dir():
            QMessageBox.warning(self, t("批量分享卡", "Batch share cards"),
                                t("导出文件夹不存在且无法创建",
                                  "Export folder missing and cannot be created"))
            return
        theme_name = "dark" if self.theme_seg.currentIndex() == 1 else "light"
        self.go_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(cands))
        self._exported = []
        offline: list[str] = []
        used: set[str] = set()
        for i, row in enumerate(cands, 1):
            self.progress.setValue(i - 1)
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
            title = sname(row["cn"], row["en_name"])
            if not os.path.exists(row["path"]):
                offline.append(title)
                continue
            date = (row.get("taken_at") or "")[:10]
            base = f"{date}_{_safe_name(title)}"
            name = base if base not in used else f"{base}_{row['eff_code']}"
            used.add(name)
            pm = render_card(row["path"], self._card_info(row), theme_name)
            dst = out_dir / f"{name}.png"
            pm.save(str(dst), "PNG")
            self._exported.append(dst)
        self.progress.setValue(len(cands))
        self.go_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.open_btn.setVisible(bool(self._exported))
        n = len(self._exported)
        msg = t(f"已导出 {n} 张分享卡到\n{out_dir}",
                f"Exported {n} cards to\n{out_dir}")
        if offline:
            msg += "\n\n" + t(
                f"跳过 {len(offline)} 张（原图离线）：" + "、".join(offline[:6])
                + ("…" if len(offline) > 6 else ""),
                f"Skipped {len(offline)} (original offline): "
                + ", ".join(offline[:6]) + ("…" if len(offline) > 6 else ""))
        QMessageBox.information(self, t("批量分享卡", "Batch share cards"), msg)

    def _open_dir(self):
        d = self.dir_edit.text().strip()
        if d and os.path.isdir(d):
            os.startfile(d)  # noqa: S606 (Windows shell open)
