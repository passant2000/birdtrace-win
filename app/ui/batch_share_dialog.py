# -*- coding: utf-8 -*-
"""批量分享卡导出(0.8-⑥): 日期范围(+可选鸟种) → 每鸟种一张"最美"落盘。

"最美" = 美学分 × 置信度 最高, 且只取已确认或原始置信≥0.5的记录
(待复核错名不印进卡, 选取逻辑在 db.best_share_cards)。主题/署名/Life#/
拍摄参数 = 一次批量设置, 对整批生效(用户定"弹一次"——即本对话框的样式卡,
不做逐卡设置)。渲染复用 render_card 纯函数循环调用。

文件名: 拍摄日期_鸟种名.png; 原图离线的候选跳过并在结果中说明。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QProgressBar, QPushButton, QVBoxLayout)

from .. import theme
from ..core import regions
from ..core.sharecard import auto_text_scale, render_card, resolve_layout
from ..i18n import t, sname
from ..theme.widgets import (SegmentedControl, ThemedDateEdit, ToggleSwitch,
                             make_card)
from .share_dialog import (exif_parts_of, focus_point, iucn_of, pinyin_spaced,
                           rarity_info)


def _place_with_spot(row: dict, rid: str | None) -> str:
    """地点行: 市有值时=市·鸟点(⑫③升级), 否则 国别·省级·鸟点;
    分隔点统一紧排"·"; 简称优先(单卡同款)。"""
    spot = row.get("spot_short") or row.get("spot_name") or ""
    city = (row.get("spot_city") or "").strip()
    if city:
        return f"{city}·{spot}" if spot else city
    if not rid or rid == "GLOBAL":
        return spot
    place = regions.region_display(rid)
    if spot:
        place += "·" + spot
    return place


def _safe_name(s: str) -> str:
    """鸟种名 → 文件名安全串(鸟种名可能含"/"、空格等)。"""
    return re.sub(r'[\\/:*?"<>|\s]+', "_", s).strip("_") or "card"


class BatchShareDialog(QDialog):
    def __init__(self, lib, win, photo_ids: list[int] | None = None,
                 preset: tuple[str, str] | None = None):
        super().__init__(win)
        self.lib = lib
        self.win = win
        self._photo_ids = list(photo_ids) if photo_ids else None
        self._preset = preset          # (d1,d2)初始日期范围(0.8.6
                                      # 时间线: 默认=当前选中日期非今天)
        self._exported: list[Path] = []
        self.setWindowTitle(t("批量分享卡", "Batch share cards")
                            if not self._photo_ids else
                            t(f"批量分享卡 · 已选 {len(self._photo_ids)} 张",
                              f"Batch share cards · {len(self._photo_ids)} selected"))
        self.setModal(True)
        self.setMinimumWidth(560)
        self._build_ui()
        if self._preset:
            self.quick_seg.setCurrent(-1)   # 已带日期范围, 快捷段不点亮
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
        # 日期控件=ThemedDateEdit: 弹层里年份/月份都是下拉一点直达,
        # 配色跟随主题。此前日期旁还有"年份…"下拉, 与控件年份重复且
        # 常驻显示单一库年份=看着像坏的(用户2026-11-05反馈), 已移除。
        d1 = QDate.fromString(self._preset[0], "yyyy-MM-dd") if self._preset else None
        d2 = QDate.fromString(self._preset[1], "yyyy-MM-dd") if self._preset else None
        if self._preset and (not d1.isValid() or not d2.isValid()):
            d1 = d2 = None            # 非法预设回落今天
        if d1 and d2 and d1 > d2:
            d1, d2 = d2, d1
        self.from_date = ThemedDateEdit(d1 or today)
        drow.addWidget(self.from_date)
        drow.addSpacing(12)
        drow.addWidget(QLabel(t("到", "to")))
        self.to_date = ThemedDateEdit(d2 or today)
        drow.addWidget(self.to_date)
        drow.addStretch(1)
        rc.addLayout(drow)

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

        # 圆角卡片开关(0.8.6用户; 与单卡共用库设置card_rounded)
        round_row = QHBoxLayout()
        round_row.addWidget(QLabel(t("圆角卡片", "Rounded corners")))
        round_row.addStretch(1)
        self.round_toggle = ToggleSwitch(
            self.lib.get_setting("card_rounded", "1") == "1")
        self.round_toggle.toggled.connect(
            lambda on: self.lib.set_setting("card_rounded",
                                             "1" if on else "0"))
        round_row.addWidget(self.round_toggle)
        sc.addLayout(round_row)

        # 分辨率档位(与单卡同款, 2026-11-10用户; 0.8.3加原图档)
        res_row = QHBoxLayout()
        res_row.addWidget(QLabel(t("分辨率", "Resolution")))
        self.res_seg = SegmentedControl([t("标准 2000", "Standard 2000"),
                                         t("高清 3000", "HD 3000"),
                                         t("原图", "Original")])
        self.res_seg.setToolTip(t(
            "原图档：卡片宽度=照片自身像素宽（竖图即原图短边），"
            "照片不做任何缩放；超大原图文件会非常大。",
            "Original: card width = photo's own pixels (the short side "
            "for portrait photos), photo untouched; very large originals "
            "produce very large files."))
        res_row.addWidget(self.res_seg, 1)
        sc.addLayout(res_row)

        # 版式(与单卡同款; 2026-11-17竖版改3:5即9:15): 自动=横3:4/竖3:5
        lay_row = QHBoxLayout()
        lay_row.addWidget(QLabel(t("版式", "Layout")))
        # 0.8.6: 英文段名缩短(3:5/3:4), 长英文挤溢出窄面板
        self.lay_seg = SegmentedControl(
            [t("自动", "Auto"), t("竖 3:5", "3:5"),
             t("横 3:4", "3:4"), t("经典", "Classic")])
        self.lay_seg.setToolTip(t(
            "自动：每张照片按方向选版式（横图3:4，竖图/方图3:5）。\n"
            "3:5（=9:15）=小红书竖版全屏图文；3:4=信息流预览完整；"
            "经典=旧自适应。",
            "Auto: pick per photo by orientation (landscape 3:4, "
            "portrait/square 3:5).\n3:5 (= 9:15) is Xiaohongshu's "
            "fullscreen post; 3:4 previews fully in the feed; "
            "Classic = old adaptive."))
        lay_row.addWidget(self.lay_seg, 1)
        sc.addLayout(lay_row)

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

        # 鸟点上卡(0.8.3): 地点行追加" · 鸟点名"; 发稀有鸟记得关——
        # 分享卡常发公开平台, 鸟点=精确位置(防盗猎/骚扰)
        spot_row = QHBoxLayout()
        spot_row.addWidget(QLabel(t("显示鸟点", "Show birding spot")))
        self.spot_toggle = ToggleSwitch(True)
        spot_row.addStretch(1)
        spot_row.addWidget(self.spot_toggle)
        sc.addLayout(spot_row)
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
        if self._photo_ids:
            self.count_hint.setText(t(
                f"将按所选 {len(self._photo_ids)} 张照片逐张出卡（以照片当前鸟种命名）。",
                f"Exports one card per selected photo ({len(self._photo_ids)}), "
                "named by each photo's species."))
            return
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
        rarity, pct, score = rarity_info(code, rid)
        # 署名单源化(1.0冲刺⑫同批⑰): cp.creator(照片级>库级)>EXIF Artist
        # >手填设置; 框内手填仍是最高(显式临时覆盖)
        cp = self.lib.effective_copyright(row["photo_id"])
        photographer = self.name_edit.text().strip() or \
            cp.get("creator") or (row.get("artist") or "").strip()
        # 框对准锚点(0.8.4保头): 眼睛点优先(惰性算一次落库)→框心→None
        focus = focus_point(self.lib, row, row)
        return {
            "cn": title,
            "cn_raw": row["cn"] or "",
            "en_raw": row["en_name"] or "",
            "pinyin": pys,
            "en": row["en_name"] or "",
            "sci": row["sci"] or "",
            "lifer_no": self.lib.lifer_no_for_species(code)
                        if self.lifer_toggle.isChecked() else None,
            "rarity": rarity,
            "rarity_pct": pct,
            "rarity_score": score,
            "iucn": iucn_of(self.lib, code),
            "photographer": photographer,
            "date": (row.get("taken_at") or "")[:10],
            "place": _place_with_spot(row, rid) if self.spot_toggle.isChecked()
                      else (regions.region_display(rid)
                            if rid and rid != "GLOBAL" else ""),
            "exif": exif_parts_of(row) if self.exif_toggle.isChecked() else {},
            "focus": focus,
        }

    def _export(self):
        d1 = self.from_date.date().toString("yyyy-MM-dd")
        d2 = self.to_date.date().toString("yyyy-MM-dd")
        cands = (self.lib.share_card_rows(self._photo_ids)
                 if self._photo_ids else
                 self.lib.best_share_cards(
                     d1, d2, self._selected_code(),
                     self.per_combo.currentData() or 1))
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
            # 同种同日多张(连拍/多选出卡, 0.8.4用户实测5张只剩2张):
            # 旧兜底只拼一次eff_code, 第3张起同名静默覆盖——循环递增绝不覆盖
            name = base
            seq = 2
            while name in used:
                name = f"{base}_{seq}"
                seq += 1
            used.add(name)
            if self.res_seg.currentIndex() == 2:
                # 原图档: 卡宽=照片像素宽(竖图即短边), 1:1零重采样
                w = max(1200, int(row.get("width") or 2000))
            else:
                w = 3000 if self.res_seg.currentIndex() == 1 else 2000
            layout = ("auto", "3:5", "3:4", "classic")[
                self.lay_seg.currentIndex()]
            # 0.8.6: 自动默认分界线=无裁切线(与单卡ShareDialog同源;
            # 按每张原图比例算, 批量不做逐卡手动, 全走自动默认)
            ts = 1.0
            try:
                rw, rh = int(row["width"]), int(row["height"])
                if rw > 0 and rh > 0:
                    key = resolve_layout(rw, rh, layout)
                    ts = auto_text_scale(rw, rh, key)
            except (KeyError, IndexError, TypeError, ValueError):
                pass
            pm = render_card(row["path"], self._card_info(row), theme_name,
                             width=w, layout=layout, text_scale=ts,
                             rounded=self.round_toggle.isChecked())
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
