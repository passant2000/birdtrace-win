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
        """从照片批次地区取短名(省级取省名, 国家取国名)。"""
        photo, _recs = self.lib.photo_detail(self.photo_id)
        rid = (photo or {}).get("region_id")
        if not rid or rid == "GLOBAL":
            return ""
        if "-" in rid:  # admin1, 如 CN-31
            for c in regions.build_tree()["countries"]:
                for s in c["subs"]:
                    if s["id"] == rid:
                        return s["name"]
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
        # 罕见度(参考birdtrace/慧眼观鸟分享卡): 按照片批次地区计算
        rarity = None
        if species:
            try:
                from ..core.prior_hint import get_hint
                rarity = get_hint().rarity_tier(
                    species["code"], self.photo.get("region_id"))
            except Exception:
                rarity = None
        return {
            "cn": title,
            "pinyin": pys,
            "en": species["en"] if species else "",
            "sci": species["sci"] if species else "",
            "lifer_no": lifer_no,
            "rarity": rarity,
            "photographer": self.name_edit.text().strip(),
            "date": self.taken,
            "place": self.place_edit.text().strip(),
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
