# -*- coding: utf-8 -*-
"""导出向导(0.8-④): 范围(日期/鸟种/鸟点/评分) → 复制到新位置 | 原地重命名。

用户定案: "导出本质=复制+重命名, 给个只改名不导出的选项"。
  · 复制: 目录层级(时间→鸟种/鸟种→时间/平铺) + 文件名(原名/日期_鸟种_序号),
    树形实时预览; 原图绝不动。
  · 原地重命名: 只改名不复制不移动; 库 path 按 file_hash 同步(先改文件后改库,
    失败的文件不动库记录); 显式确认框列新旧对照; RAW+JPG 同名对成对改名。
两种模式都: 重名安全编号绝不覆盖; 原图离线的跳过并列在结果里。
与 .birdtrace.json 兼容(按 hash 键), 改名后新旧目录的 sidecar 由 flush 更新。
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QProgressBar, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import theme
from ..core import exporter
from ..i18n import t, sname
from ..theme.widgets import (SegmentedControl, ThemedDateEdit,
                             ToggleSwitch, make_card)


class ExportDialog(QDialog):
    PREVIEW_MAX = 300          # 预览树最多行数(防卡)

    def __init__(self, lib, win):
        super().__init__(win)
        self.lib = lib
        self.win = win
        self._plan: dict | None = None
        self._mode = "copy"
        self.setWindowTitle(t("导出照片", "Export photos"))
        self.setModal(True)
        self.resize(860, 760)
        self._build_ui()
        self._update_preview()

    # ---------- UI ----------
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(12)

        # 范围
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
        # 日期控件=ThemedDateEdit(弹层年份/月份下拉一点直达, 主题配色;
        # 原日期旁的"年份…"下拉与控件年份重复且看着没功能, 已移除)
        self.from_date = ThemedDateEdit(QDate(2000, 1, 1))
        self.from_date.setSpecialValueText(" ")     # 空=不限
        self.from_date.setMinimumDate(QDate(2000, 1, 1))
        drow.addWidget(self.from_date)
        drow.addSpacing(10)
        drow.addWidget(QLabel(t("到", "to")))
        self.to_date = ThemedDateEdit(QDate.currentDate())
        drow.addWidget(self.to_date)
        drow.addStretch(1)
        rc.addLayout(drow)

        srow = QHBoxLayout()
        srow.addWidget(QLabel(t("鸟种", "Species")))
        self.species_lab = QLabel(t("全部", "All"))
        self.species_lab.setStyleSheet(
            f"font-weight:600;color:{theme.LABEL};background:transparent;")
        self._species_code = None
        b_sp = QPushButton(t("选择…", "Choose…"))
        b_sp.setCursor(Qt.PointingHandCursor)
        b_sp.clicked.connect(self._pick_species)
        b_spc = QPushButton(t("清除", "Clear"))
        b_spc.setCursor(Qt.PointingHandCursor)
        b_spc.clicked.connect(self._clear_species)
        srow.addWidget(self.species_lab, 1)
        srow.addWidget(b_sp)
        srow.addWidget(b_spc)
        rc.addLayout(srow)

        prow = QHBoxLayout()
        prow.addWidget(QLabel(t("鸟点", "Spot")))
        self.spot_combo = QComboBox()
        self.spot_combo.addItem(t("全部鸟点", "All spots"), None)
        for sp in self.lib.spots_overview():
            self.spot_combo.addItem(sp["name"], sp["id"])
        prow.addWidget(self.spot_combo, 1)
        rated_row = QHBoxLayout()
        rated_row.addWidget(QLabel(t("仅评分照片", "Rated only")))
        self.rated_toggle = ToggleSwitch(False)
        rated_row.addStretch(1)
        rated_row.addWidget(self.rated_toggle)
        prow.addLayout(rated_row)
        # 选片筛选(1.0冲刺⑨): 默认排除拒绝片(通用诉求), 可改为仅保留等
        pickrow = QHBoxLayout()
        pickrow.addWidget(QLabel(t("选片", "Pick")))
        self.pick_combo = QComboBox()
        self.pick_combo.addItem(t("排除拒绝片", "Exclude rejected"), "!reject")
        self.pick_combo.addItem(t("全部", "All"), None)
        self.pick_combo.addItem(t("仅保留", "Keep only"), "keep")
        self.pick_combo.addItem(t("仅待定", "Pending only"), "pending")
        self.pick_combo.addItem(t("仅拒绝", "Rejected only"), "reject")
        self.pick_combo.setCursor(Qt.PointingHandCursor)
        pickrow.addWidget(self.pick_combo, 1)
        rc.addLayout(pickrow)
        rc.addLayout(prow)
        self.range_hint = QLabel()
        self.range_hint.setObjectName("Hint")
        rc.addWidget(self.range_hint)
        lay.addWidget(range_card)

        # 模式
        mode_card, mc = make_card(t("方式", "Mode"))
        self.mode_seg = SegmentedControl([t("复制到新位置", "Copy to folder"),
                                          t("原地重命名（不复制）",
                                            "Rename in place (no copy)")])
        self.mode_seg.changed.connect(self._on_mode)
        mc.addWidget(self.mode_seg)
        self.copy_box = QWidget()
        cb = QVBoxLayout(self.copy_box)
        cb.setContentsMargins(0, 6, 0, 0)
        cb.setSpacing(8)
        drow2 = QHBoxLayout()
        drow2.addWidget(QLabel(t("导出到", "Export to")))
        self.dir_edit = QLineEdit(str(Path.home() / "Pictures" /
                                      t("鸟迹导出", "BirdTrace Export")))
        drow2.addWidget(self.dir_edit, 1)
        b_dir = QPushButton(t("浏览…", "Browse…"))
        b_dir.setCursor(Qt.PointingHandCursor)
        b_dir.clicked.connect(self._browse_dir)
        drow2.addWidget(b_dir)
        cb.addLayout(drow2)
        hrow = QHBoxLayout()
        hrow.addWidget(QLabel(t("目录层级", "Folder layout")))
        self.hier_seg = SegmentedControl([t("时间→鸟种", "Time→Species"),
                                          t("鸟种→时间", "Species→Time"),
                                          t("平铺", "Flat")])
        hrow.addWidget(self.hier_seg, 1)
        cb.addLayout(hrow)
        mc.addWidget(self.copy_box)
        # 文件名模板: CameraRaw式下拉组合(2026-11-04用户)
        # 每段∈ 无/原文件名/日期/鸟名/序号/鸟点, 用"_"连接;
        # 默认 日期+鸟名+序号 (=原"日期_鸟种_序号")
        self._SEG_ITEMS = [t("（无）", "(none)"), t("原文件名", "Filename"),
                           t("置信度", "Confidence"),
                           t("日期", "Date"), t("鸟名", "Species"),
                           t("序号", "No."), t("鸟点", "Spot")]
        self._SEG_KEYS = [None, "filename", "confidence", "date", "name", "seq",
                          "spot"]
        tpl_row = QHBoxLayout()
        tpl_row.addWidget(QLabel(t("文件名", "File names")))
        self.tpl_combos = []
        for _i in range(4):
            combo = QComboBox()
            for it in self._SEG_ITEMS:
                combo.addItem(it)
            combo.setMaximumWidth(110)
            combo.activated.connect(lambda _ix: self._update_preview())
            tpl_row.addWidget(combo)
            self.tpl_combos.append(combo)
        self.tpl_combos[0].setCurrentIndex(self._SEG_ITEMS.index(t("日期", "Date")))
        self.tpl_combos[1].setCurrentIndex(self._SEG_ITEMS.index(t("鸟名", "Species")))
        self.tpl_combos[2].setCurrentIndex(self._SEG_ITEMS.index(t("序号", "No.")))
        tpl_row.addStretch(1)
        mc.addLayout(tpl_row)
        self.warn_lab = QLabel()
        self.warn_lab.setWordWrap(True)
        self.warn_lab.setStyleSheet(
            f"font-size:12px;color:{theme.ORANGE};background:transparent;")
        mc.addWidget(self.warn_lab)
        lay.addWidget(mode_card)

        # 预览
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([t("预览（原 → 新）", "Preview (old → new)"),
                                   ""])
        self.tree.setColumnWidth(0, 480)
        self.tree.setRootIsDecorated(True)
        lay.addWidget(self.tree, 1)

        # 底部
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        lay.addWidget(self.progress)
        row = QHBoxLayout()
        self.hint = QLabel()
        self.hint.setObjectName("Hint")
        self.hint.setWordWrap(True)
        row.addWidget(self.hint, 1)
        self.go_btn = QPushButton(t("开始导出", "Start export"))
        self.go_btn.setObjectName("Primary")
        self.go_btn.setCursor(Qt.PointingHandCursor)
        self.go_btn.clicked.connect(self._run)
        row.addWidget(self.go_btn)
        close = QPushButton(t("关闭", "Close"))
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.reject)
        row.addWidget(close)
        lay.addLayout(row)

        # 信号
        self.from_date.dateChanged.connect(lambda _q: self._update_preview())
        self.to_date.dateChanged.connect(lambda _q: self._update_preview())
        self.spot_combo.currentIndexChanged.connect(lambda _i: self._update_preview())
        self.hier_seg.changed.connect(lambda _i: self._update_preview())
        self.rated_toggle.toggled.connect(lambda _v: self._update_preview())
        self.pick_combo.currentIndexChanged.connect(
            lambda _v: self._update_preview())

    def _apply_quick(self, idx: int):
        # 快捷范围: 今天/近7天/本月/今年/全部(2000-01-01=不限)
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

    def _pick_species(self):
        from .species_pick import SpeciesPickDialog
        dlg = SpeciesPickDialog(self.lib, t("选择鸟种", "Choose species"), self)
        if dlg.exec() and dlg.selected_code:
            self._species_code = dlg.selected_code
            info = self.lib.species_info(self._species_code)
            self.species_lab.setText(
                sname(info["cn"], info["en"]) if info else self._species_code)
            self._update_preview()

    def _clear_species(self):
        self._species_code = None
        self.species_lab.setText(t("全部", "All"))
        self._update_preview()

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, t("选择导出文件夹",
                                                     "Choose export folder"),
                                             self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)

    def _on_mode(self, idx: int):
        self._mode = "copy" if idx == 0 else "rename"
        self.copy_box.setVisible(self._mode == "copy")
        self.warn_lab.setText(
            "" if self._mode == "copy" else t(
                "⚠️ 原地重命名会直接修改硬盘上的文件名（不复制不移动），"
                "鸟迹里的记录、缩略图、统计会自动跟着新名字走。同名 RAW+JPG "
                "会成对改名。此操作不可一键撤销。",
                "⚠️ Rename in place changes file names on disk directly "
                "(no copy, no move). Records, thumbnails and stats follow "
                "automatically. RAW+JPG same-name pairs are renamed together. "
                "This cannot be undone with one click."))
        self._update_preview()

    def _range_rows(self) -> list[dict]:
        d1 = None if self.from_date.date() == self.from_date.minimumDate() \
            else self.from_date.date().toString("yyyy-MM-dd")
        d2 = self.to_date.date().toString("yyyy-MM-dd")
        spot_id = self._spot_id()
        return exporter.select_range(
            self.lib, d1, d2, self._species_code, spot_id,
            rated_only=self.rated_toggle.isChecked(),
            pick_filter=self.pick_combo.currentData())

    def _template(self):
        # 下拉组合 → 段列表(跳过无); 全空=None(原文件名)
        out = [self._SEG_KEYS[c.currentIndex()] for c in self.tpl_combos]
        out = [k for k in out if k]
        return out or None

    def _plan_now(self) -> dict:
        rows = self._range_rows()
        tpl = self._template()
        if self._mode == "copy":
            return exporter.plan_ops(
                rows, Path(self.dir_edit.text().strip()),
                hierarchy=("flat" if self.hier_seg.currentIndex() == 2 else
                           "species_time" if self.hier_seg.currentIndex() == 1
                           else "time_species"),
                naming="date_name" if tpl == ["date", "name", "seq"]
                else "original", template=tpl)
        return exporter.plan_ops(rows, None,
                                 naming="date_name"
                                 if tpl == ["date", "name", "seq"]
                                 else "original", template=tpl)

    def _update_preview(self):
        rows = self._range_rows()
        self.range_hint.setText(t(
            f"范围内 {len(rows)} 张照片（{len({r['eff_code'] for r in rows})} 种）",
            f"{len(rows)} photos in range "
            f"({len({r['eff_code'] for r in rows})} species)"))
        self._plan = self._plan_now()
        self.tree.clear()
        root = self.tree.invisibleRootItem()
        n = 0
        for op in self._plan["ops"][:self.PREVIEW_MAX]:
            src, dst = op["src"], op["dst"]
            it = QTreeWidgetItem([f"{Path(src).name}", f"→  {dst}"])
            it.setToolTip(1, dst)
            root.addChild(it)
            n += 1
        skipped = self._plan["skipped_offline"]
        if skipped:
            it = QTreeWidgetItem([t(f"⚠ {len(skipped)} 张原图离线，跳过",
                                    f"⚠ {len(skipped)} offline, skipped"), ""])
            root.addChild(it)
        mode_txt = t("重命名", "rename") if self._mode == "rename" \
            else t("复制", "copy")
        self.go_btn.setEnabled(bool(self._plan["ops"]))
        self.hint.setText(t(
            f"将{mode_txt} {len(self._plan['ops'])} 个文件"
            f"（含同名成对文件）",
            f"Will {mode_txt} {len(self._plan['ops'])} files "
            "(including same-name pairs)"))

    # ---------- 执行 ----------
    def _spot_id(self) -> int | None:
        return self.spot_combo.currentData()

    def _run(self):
        plan = self._plan_now()          # 以按下时点为准重新计划
        ops = plan["ops"]
        if not ops:
            return
        if self._mode == "rename":
            photos = [o for o in ops if o["photo_id"]]
            r = QMessageBox.question(
                self, t("原地重命名", "Rename in place"),
                t(f"将原地重命名 {len(photos)} 张照片"
                  f"（连同同名成对文件共 {len(ops)} 个文件）。\n\n"
                  "确定要修改硬盘上的文件名吗？",
                  f"Rename {len(photos)} photos in place "
                  f"({len(ops)} files including pairs)?\n\n"
                  "Rename files on disk?"))
            if r != QMessageBox.Yes:
                return
        self.go_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(ops))
        # 分批执行(每批刷新进度; 重命名模式下批次间更新库path)
        done_all: list[dict] = []
        failed: list[dict] = []
        BATCH = 200
        for i in range(0, len(ops), BATCH):
            chunk = ops[i:i + BATCH]
            res = exporter.execute_plan(
                chunk, action="rename" if self._mode == "rename" else "copy")
            if self._mode == "rename":
                exporter.apply_rename_to_db(self.lib, res["done"])
            done_all += res["done"]
            failed += res["failed"]
            self.progress.setValue(min(i + BATCH, len(ops)))
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
        try:
            self.lib.flush_sidecars()
        except Exception:
            pass
        self.progress.setVisible(False)
        self.go_btn.setEnabled(True)
        n = len(done_all)
        msg = t(f"完成：{mode_txt(self._mode)} {n} 个文件",
                f"Done: {n} files")
        if failed:
            msg += "\n" + t(f"失败 {len(failed)} 个（文件被占用/无权限）：",
                            f"{len(failed)} failed (in use / no permission):")
            msg += "\n".join("  " + Path(f["op"]["src"]).name
                             for f in failed[:8])
        skipped = plan["skipped_offline"]
        if skipped:
            msg += "\n\n" + t(
                f"跳过 {len(skipped)} 张原图离线的照片（插回硬盘后再导出）",
                f"Skipped {len(skipped)} photos whose originals are offline "
                "(reconnect the drive and export again)")
        QMessageBox.information(self, t("导出", "Export"), msg)
        # 导出后直接打开新位置文件夹(2026-11-04用户)
        # copy打开所选目标根目录(第一个文件的dst可能深埋在鸟种/年月子
        # 目录里, 打开它用户摸不着头绪); rename原地改名→打开照片原文件夹
        try:
            if self._mode == "copy" and done_all:
                root = self.dir_edit.text().strip()
                os.startfile(root if root
                             else str(Path(done_all[0]["dst"]).parent))
            elif self._mode == "rename" and plan["ops"]:
                os.startfile(str(Path(plan["ops"][0]["src"]).parent))
        except OSError:
            pass
        self._update_preview()


def mode_txt(mode: str) -> str:
    return t("重命名", "renamed") if mode == "rename" else t("复制", "copied")
