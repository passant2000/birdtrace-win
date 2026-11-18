# -*- coding: utf-8 -*-
"""观鸟记录中心导出(1.0冲刺④): 按中国观鸟记录中心(birdreport.cn)
Excel 导入思路输出 CSV(UTF-8 BOM, Excel直开)——日期/鸟种/地点/坐标/
数量/备注; 数量=导出时临时编辑(默认1, 不落库不进sidecar, 专题6定案);
图片归集=每鸟种最美照(美学×置信, 已确认或≥0.5——复用best_share_cards
门)按"鸟种名_日期"复制, 配合记录上传手动挑图。
⚠️记录中心模板列以官方最新版为准, 本导出提供通用列便于手工对齐。"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMessageBox, QPushButton,
                               QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from .. import theme
from ..i18n import t
from ..theme.widgets import ThemedDateEdit

_CLEAN = re.compile(r'[\\/:*?"<>|\r\n]+')
# CSV 列头=记录中心模板字段(输出数据契约, 双语列头在写入时按界面语言
# 选 COLS_ZH/COLS_EN——用户拿到的 CSV 列名跟随界面语言)
COLS_ZH = ["日期", "鸟种中文名", "英文名", "学名", "地点", "纬度", "经度", "数量", "备注"]  # i18n:ok 数据码(记录中心模板字段)
COLS_EN = ["Date", "Species (CN)", "Species (EN)", "Scientific name", "Location", "Latitude", "Longitude", "Count", "Notes"]  # i18n:ok 同上


class BirdReportDialog(QDialog):
    def __init__(self, lib, win):
        super().__init__(win)
        self.lib = lib
        self.win = win
        self.setWindowTitle(t("观鸟记录中心导出", "Bird report export"))
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint |
                            Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.resize(980, 600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)

        hint = QLabel(t(
            "按「日期+鸟种+鸟点」聚合识别记录为上报行；数量默认 1、备注留空，"
            "导出前可逐行修改——只进本次导出文件，不写入鸟迹数据库。"
            "记录中心模板列以官方最新版为准，可复制列粘进官方模板。",
            "Rows aggregate records by date+species+spot; count defaults "
            "to 1 and notes are empty — editable per row, stored only in "
            "the exported file, never in the BirdTrace database. Check the "
            "official template for the latest columns."))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size:12px;color:{theme.LABEL_2};"
                           "background:transparent;")
        lay.addWidget(hint)

        fbar = QHBoxLayout()
        fbar.addWidget(QLabel(t("从", "From")))
        self.d1 = ThemedDateEdit()
        fbar.addWidget(self.d1)
        fbar.addWidget(QLabel(t("到", "To")))
        self.d2 = ThemedDateEdit()
        fbar.addWidget(self.d2)
        gen = QPushButton(t("生成记录表", "Build table"))
        gen.setObjectName("Primary")
        gen.setCursor(Qt.PointingHandCursor)
        gen.clicked.connect(self._build)
        fbar.addWidget(gen)
        fbar.addStretch(1)
        lay.addLayout(fbar)

        self.table = QTableWidget(0, len(COLS_ZH))
        self.table.setHorizontalHeaderLabels(
            [t(c, e) for c, e in zip(COLS_ZH, COLS_EN)])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        lay.addWidget(self.table, 1)
        self.table.horizontalHeader().setSectionResizeMode(
            8, QHeaderView.Stretch)

        self.status = QLabel("")
        self.status.setStyleSheet(f"font-size:12px;color:{theme.LABEL_2};"
                                  "background:transparent;")
        lay.addWidget(self.status)

        btns = QHBoxLayout()
        csv_btn = QPushButton(t("导出 CSV…", "Export CSV…"))
        csv_btn.setObjectName("Primary")
        csv_btn.setCursor(Qt.PointingHandCursor)
        csv_btn.clicked.connect(self._export_csv)
        btns.addWidget(csv_btn)
        img_btn = QPushButton(t("归集最美照…", "Collect best photos…"))
        img_btn.setCursor(Qt.PointingHandCursor)
        img_btn.setToolTip(t(
            "把日期范围内每鸟种一张最美照（美学×置信，已确认或置信≥0.5）"
            "按「鸟种名_日期」复制到你选的文件夹，配合记录上传手动挑图",
            "Copy one best photo per species (aesthetic×confidence, "
            "confirmed or ≥0.5) into a folder as 种名_日期, to hand-pick "
            "when uploading records"))
        img_btn.clicked.connect(self._collect_photos)
        btns.addWidget(img_btn)
        btns.addStretch(1)
        close_btn = QPushButton(t("关闭", "Close"))
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        btns.addWidget(close_btn)
        lay.addLayout(btns)
        self._rows: list[dict] = []

    def _build(self):
        d1 = self.d1.date().toString("yyyy-MM-dd")
        d2 = self.d2.date().toString("yyyy-MM-dd")
        self._rows = self.lib.birdreport_rows(d1, d2)
        self.table.setRowCount(0)
        for r in self._rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            vals = [r["date"] or "", r["cn"] or "", r["en"] or "",
                    r["sci"] or "", r["spot_name"] or "",
                    f"{r['lat']:.5f}" if r["lat"] is not None else "",
                    f"{r['lon']:.5f}" if r["lon"] is not None else ""]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, c, it)
            spin = QSpinBox()
            spin.setRange(1, 100000)
            spin.setValue(1)
            self.table.setCellWidget(row, 7, spin)
            note = QLineEdit()
            self.table.setCellWidget(row, 8, note)
        n_photo = sum(r["photos"] or 0 for r in self._rows)
        self.status.setText(t(
            f"共 {len(self._rows)} 行（覆盖 {n_photo} 张照片）；"
            "数量/备注编辑后点导出。",
            f"{len(self._rows)} rows ({n_photo} photos); edit count/notes "
            "then export."))
        if not self._rows:
            QMessageBox.information(self, t("记录中心导出", "Bird report"),
                                    t("该日期范围内没有识别记录。",
                                      "No records in this date range."))

    def _safe_name(self, s: str) -> str:
        return _CLEAN.sub("_", s or "").strip() or \
            t("未名种", "unknown")

    def _export_csv(self):
        if not self._rows:
            QMessageBox.information(self, t("记录中心导出", "Bird report"),
                                    t("先点「生成记录表」。", "Build the table first."))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, t("导出 CSV", "Export CSV"),
            str(Path.home() / "Documents" / "birdreport.csv"),
            "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow([t(c, e) for c, e in zip(COLS_ZH, COLS_EN)])
                for i, r in enumerate(self._rows):
                    spin = self.table.cellWidget(i, 7)
                    note = self.table.cellWidget(i, 8)
                    w.writerow([
                        r["date"] or "", r["cn"] or "", r["en"] or "",
                        r["sci"] or "", r["spot_name"] or "",
                        (f"{r['lat']:.5f}" if r["lat"] is not None else ""),
                        (f"{r['lon']:.5f}" if r["lon"] is not None else ""),
                        spin.value() if spin else 1,
                        note.text() if note else ""])
        except OSError as e:
            QMessageBox.warning(self, t("导出失败", "Export failed"), str(e))
            return
        self.status.setText(t(f"CSV 已导出: {path}", f"CSV exported: {path}"))
        QMessageBox.information(
            self, t("完成", "Done"),
            t(f"已导出 {len(self._rows)} 行到\n{path}\n\n"
              "列与记录中心官方模板对齐后再粘贴/导入；如官方模板有变，"
              "复制对应列即可。",
              f"{len(self._rows)} rows exported to\n{path}\n\n"
              "Align columns with the official template; copy columns "
              "if the template changed."))

    def _collect_photos(self):
        if not self._rows:
            QMessageBox.information(self, t("记录中心导出", "Bird report"),
                                    t("先点「生成记录表」。", "Build the table first."))
            return
        d1 = self.d1.date().toString("yyyy-MM-dd")
        d2 = self.d2.date().toString("yyyy-MM-dd")
        dest = QFileDialog.getExistingDirectory(
            self, t("选择归集文件夹", "Choose folder"),
            str(Path.home() / "Pictures"))
        if not dest:
            return
        cards = self.lib.best_share_cards(d1, d2, per_species=1)
        n = 0
        for c in cards:
            src = Path(c["path"])
            if not src.is_file():
                continue
            name = self._safe_name(c.get("cn") or c.get("name") or c["eff_code"])
            target = Path(dest) / f"{name}_{(c['taken_at'] or '')[:10]}.jpg"
            k = 1
            while target.exists():
                target = Path(dest) / f"{name}_{(c['taken_at'] or '')[:10]}_{k}.jpg"
                k += 1
            try:
                import shutil
                shutil.copy2(str(src), str(target))
                n += 1
            except OSError:
                continue
        QMessageBox.information(
            self, t("最美照归集", "Best photos"),
            t(f"已复制 {n} 张到\n{dest}\n\n按「鸟种名_日期」命名，"
              "上传记录后照名字挑图即可。",
              f"{n} photo(s) copied to\n{dest}\n\nNamed 种名_日期 — "
              "hand-pick after uploading the records."))
