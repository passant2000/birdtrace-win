# -*- coding: utf-8 -*-
"""分享卡对话框: 预览 + 主题/署名/地点选项 + 复制剪贴板 / 保存。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from ..core import regions
from ..core.sharecard import render_card
from ..i18n import t, sname
from ..theme.widgets import SegmentedControl, ToggleSwitch, make_card


def pinyin_spaced(cn: str) -> list[str]:
    """逐字音节列表(带声调), 与汉字一一对应; 多音节异常时回退整串。"""
    from pypinyin import Style, lazy_pinyin
    if not cn:
        return []
    pys = lazy_pinyin(cn, style=Style.TONE)
    return pys if len(pys) == len(cn) else ["".join(pys)]


def exif_parts_of(p: dict) -> dict:
    """拍摄参数三段(机身/镜头/焦·孔·快·ISO); 库里有什么显示什么。

    纯函数, 供单卡ShareDialog与批量导出(0.8-⑥)共用; 字段取自库内
    EXIF(照片文件丢失也能显示)。"""
    make = (p.get("make") or "").strip()
    model = (p.get("model") or "").strip()
    body = model if model and make and model.startswith(make) \
        else " ".join(x for x in (make, model) if x)
    shot: list[str] = []
    if p.get("focal_len"):
        try:
            shot.append(f"{float(p['focal_len']):g}mm")
        except (TypeError, ValueError):
            pass
    if p.get("fnum"):
        try:
            shot.append(f"f/{float(p['fnum']):g}")
        except (TypeError, ValueError):
            pass
    if p.get("exposure"):
        shot.append(f"{str(p['exposure']).strip()}s")
    if p.get("iso"):
        shot.append(f"ISO {p['iso']}")
    return {"body": body, "lens": str(p.get("lens") or "").strip(),
            "shot": " · ".join(shot)}


def rarity_info(code: str | None, region_id: str | None
                ) -> tuple[str | None, float | None, float | None]:
    """(罕见度档位, 百分位, 分值0-10) — 百分位/分值仅稀有/罕见档返回。

    分值=懂鸟式9.2风格(2026-11-10用户), 由同源百分位映射, 见
    prior_hint.rarity_score。异常/无数据/全球区域 = (None,)*3。
    单卡与批量导出共用。"""
    if not code:
        return None, None, None
    try:
        from ..core.prior_hint import get_hint
        hint = get_hint()
        tier = hint.rarity_tier(code, region_id)
        if tier not in ("稀有", "罕见"):  # i18n:ok
            return tier, None, None
        pct = hint.rarity_percentile(code, region_id)
        score = hint.rarity_score(code, region_id)
        return tier, pct, score
    except Exception:
        return None, None, None


def iucn_of(lib, code: str | None) -> str | None:
    """物种 IUCN 受威胁等级码(NT/VU/EN/CR/EW/EX); LC/无数据返回 None。

    供分享卡"濒危/易危"胶囊(2026-11-10用户): 只标受威胁物种,
    无危不显示。数据=species.iucn(assets iucn_status.json, 10812种)。"""
    if not code:
        return None
    try:
        # species_info返回sqlite3.Row(无.get方法), 用键访问+异常兜底
        row = lib.species_info(code)
        if row is None:
            return None
        v = row["iucn"]
        return v if v in ("NT", "VU", "EN", "CR", "EW", "EX") else None
    except (KeyError, IndexError, Exception):
        return None


class ShareDialog(QDialog):
    def __init__(self, lib, win, photo_id: int):
        super().__init__(win)
        self.lib = lib
        self.win = win
        self.photo_id = photo_id
        self.setWindowTitle(t("生成分享卡", "Create share card"))
        self.setModal(True)
        self.resize(560, 800)
        self._build_ui()
        self._update()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(12)

        # 选项卡
        opt_card, opt = make_card(t("样式", "Style"))
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel(t("主题", "Theme")))
        self.theme_seg = SegmentedControl([t("浅色", "Light"), t("深色", "Dark")])
        self.theme_seg.changed.connect(lambda _=0: self._update())
        theme_row.addWidget(self.theme_seg, 1)
        opt.addLayout(theme_row)

        life_row = QHBoxLayout()
        life_row.addWidget(QLabel(t("显示 Life # 序号", "Show Life #")))
        self.lifer_toggle = ToggleSwitch(True)
        self.lifer_toggle.toggled.connect(lambda _v: self._update())
        life_row.addStretch(1)
        life_row.addWidget(self.lifer_toggle)
        opt.addLayout(life_row)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(t("拍摄者", "Photographer")))
        self.name_edit = QLineEdit(self.lib.get_setting("photographer_name", ""))
        self.name_edit.setPlaceholderText(t("你的名字", "Your name"))
        self.name_edit.setClearButtonEnabled(True)
        self.name_edit.textChanged.connect(lambda _t: self._update())
        name_row.addWidget(self.name_edit, 1)
        opt.addLayout(name_row)

        place_row = QHBoxLayout()
        place_row.addWidget(QLabel(t("地点", "Location")))
        self.place_edit = QLineEdit(self._default_place())
        self.place_edit.setPlaceholderText(
            t("如: 上海市 / 崇明东滩", "e.g. Shanghai / Chongming Dongtan"))
        self.place_edit.textChanged.connect(lambda _t: self._update())
        place_row.addWidget(self.place_edit, 1)
        opt.addLayout(place_row)

        # 拍摄参数(EXIF: 机身/镜头/焦距/光圈/快门/ISO, 有什么显示什么)
        exif_row = QHBoxLayout()
        exif_row.addWidget(QLabel(t("拍摄参数", "Camera data")))
        self.exif_toggle = ToggleSwitch(True)
        self.exif_toggle.toggled.connect(self._on_exif_toggle)
        exif_row.addStretch(1)
        exif_row.addWidget(self.exif_toggle)
        opt.addLayout(exif_row)
        self.exif_hint = QLabel()
        self.exif_hint.setObjectName("Hint")
        self.exif_hint.setWordWrap(True)
        self.exif_hint.setTextInteractionFlags(Qt.TextSelectableByMouse)
        opt.addWidget(self.exif_hint)
        lay.addWidget(opt_card)

        # 预览
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.preview_host = QLabel()
        self.preview_host.setAlignment(Qt.AlignCenter)
        self.scroll.setWidget(self.preview_host)
        lay.addWidget(self.scroll, 1)

        # 动作
        row = QHBoxLayout()
        b_copy = QPushButton(t("复制到剪贴板", "Copy to clipboard"))
        b_copy.setObjectName("Primary")
        b_copy.setCursor(Qt.PointingHandCursor)
        b_copy.clicked.connect(self._copy)
        b_save = QPushButton(t("保存为图片…", "Save as image…"))
        b_save.setCursor(Qt.PointingHandCursor)
        b_save.clicked.connect(self._save)
        row.addWidget(b_copy, 1)
        row.addWidget(b_save, 1)
        lay.addLayout(row)

        self._build_info()

    def _default_place(self) -> str:
        """从照片批次地区取显示名: 国别·省级(如 中国·上海)——用户要求
        分享卡带国别, region_display 本身就是 country·sub 格式。"""
        photo, _recs = self.lib.photo_detail(self.photo_id)
        rid = (photo or {}).get("region_id")
        if not rid or rid == "GLOBAL":
            return ""
        return regions.region_display(rid)

    def _build_info(self):
        photo, recs = self.lib.photo_detail(self.photo_id)
        self.photo = photo
        rec = recs[0] if recs else None
        code = rec["eff_code"] if rec else None
        self.species = self.lib.species_info(code) if code else None
        self.taken = (photo.get("dt_original") or photo.get("added_at") or "")[:10]
        # 拍摄者: EXIF Artist 优先, 否则设置里的名字
        self.photographer = photo.get("artist") or self.lib.get_setting("photographer_name", "")
        if self.photographer and not self.name_edit.text():
            self.name_edit.setText(self.photographer)
        # 拍摄参数摘要(取自库内EXIF字段, 照片文件丢失也能显示)
        parts = self._exif_parts(respect_toggle=False)
        summary = " · ".join(v for v in parts.values() if v)
        text = summary if summary else t("照片未检测到拍摄参数",
                                         "No camera data in this photo")
        # 原图不可读(0.8-②): 卡片会没有照片, 提前说清原因
        from ..core.offline import OFFLINE, OK, drive_label, drive_root, path_state
        st = path_state(photo["path"])
        if st == OFFLINE:
            drv = drive_label(drive_root(photo["path"]))
            text = t(f"⚠️ 原图离线（{drv} 未接入），插回硬盘后再生成分享卡。\n",
                     f"⚠️ Original offline (drive {drv} not connected); "
                     "reconnect it before making the card.\n") + text
        elif st != OK:
            text = t("⚠️ 原图不在原位置，分享卡将没有照片。\n",
                     "⚠️ Original not at its recorded location; the card "
                     "will have no photo.\n") + text
        self.exif_hint.setText(text)
        self.exif_hint.setEnabled(self.exif_toggle.isChecked())

    def _on_exif_toggle(self, on: bool):
        self.exif_hint.setEnabled(on)
        self._update()

    def _exif_parts(self, respect_toggle: bool = True) -> dict:
        """拍摄参数三段(勾选后); 取自库内EXIF字段。"""
        if respect_toggle and not self.exif_toggle.isChecked():
            return {}
        return exif_parts_of(self.photo or {})

    def _card_info(self) -> dict:
        species = self.species
        cn = species["cn"] if species else None
        # 大字标题: sname取当前语言名(英文模式为英文名)
        title = sname(cn, species["en"]) if species \
            else t("未识别", "Unidentified")
        pys = pinyin_spaced(title)
        if len(pys) != len(title):   # 英文标题(非逐字汉字)不叠画拼音
            pys = []
        lifer_no = None
        if species and self.lifer_toggle.isChecked():
            lifer_no = self.lib.lifer_no_for_species(species["code"])
        # 罕见度(参考birdtrace/慧眼观鸟分享卡): 按照片批次地区计算;
        # 稀有/罕见再取百分位("罕见 · 前 3%", 0.8方案⑤)
        code = species["code"] if species else None
        rarity, rarity_pct, rarity_score = rarity_info(
            code, self.photo.get("region_id"))
        return {
            "cn": title,
            "pinyin": pys,
            "en": species["en"] if species else "",
            "sci": species["sci"] if species else "",
            "lifer_no": lifer_no,
            "rarity": rarity,
            "rarity_pct": rarity_pct,
            "rarity_score": rarity_score,
            "iucn": iucn_of(self.lib, code),
            "photographer": self.name_edit.text().strip(),
            "date": self.taken,
            "place": self.place_edit.text().strip(),
            "exif": self._exif_parts(),
        }

    def _update(self):
        theme = "dark" if self.theme_seg.currentIndex() == 1 else "light"
        self.pm = render_card(self.photo["path"], self._card_info(), theme)
        self._show_preview()

    def _show_preview(self):
        if not hasattr(self, "pm"):
            return
        # 整卡一屏看全: 宽高都适配视口(卡片是长图, 只按宽缩放会看不到底部logo)
        vw = max(200, self.scroll.width() - 40)
        vh = max(240, self.scroll.height() - 16)
        scaled = self.pm.scaled(vw, vh, Qt.KeepAspectRatio,
                                Qt.SmoothTransformation)
        self.preview_host.setPixmap(scaled)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._show_preview()

    def _copy(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setPixmap(self.pm)
        self.accept()

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(
            self, t("保存分享卡", "Save share card"),
            f"bird_{self.species['cn'] if self.species else 'card'}.png",
            t("PNG 图片 (*.png)", "PNG image (*.png)"))
        if path:
            self.pm.save(path, "PNG")
            self.accept()
