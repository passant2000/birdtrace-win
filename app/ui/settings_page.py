# -*- coding: utf-8 -*-
"""设置页: 语言 / 拍摄者名 / 默认地区 / 照片库位置 / 识别参数。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from ..core import regions
from .. import theme
from ..i18n import t


class SettingsPage(QWidget):
    def __init__(self, lib, win):
        super().__init__()
        self.lib = lib
        self.win = win
        self._build_ui()

    def _build_ui(self):
        # 整页可滚动: 卡片多时不再撑大窗口最小高度
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        page_scroll = QScrollArea()
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        outer.addWidget(page_scroll)
        page_scroll.setWidget(content)

        lay = QVBoxLayout(content)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        title = QLabel(t("设置", "Settings"))
        title.setStyleSheet(f"font-size:26px;font-weight:800;color:{theme.LABEL};"
                            "background:transparent;")
        lay.addWidget(title)

        from ..theme.widgets import SegmentedControl, make_card

        # ---- 外观 ----
        card_ap, form_ap = make_card(t("外观", "Appearance"))
        lang_row = QHBoxLayout()
        lang_lab = QLabel(t("语言 Language", "Language 语言"))
        lang_lab.setObjectName("RowLabel")
        self.lang_seg = SegmentedControl(["中文", "English"])  # i18n:ok
        self.lang_seg.setCurrent(1 if self.lib.get_setting("lang", "zh") == "en" else 0)
        self.lang_seg.changed.connect(self._save_lang)
        lang_row.addWidget(lang_lab)
        lang_row.addWidget(self.lang_seg, 1)
        form_ap.addLayout(lang_row)

        ap_row = QHBoxLayout()
        ap_lab = QLabel(t("主题", "Theme"))
        ap_lab.setObjectName("RowLabel")
        self.theme_seg = SegmentedControl(
            [t("跟随系统", "System"), t("浅色", "Light"), t("深色", "Dark")])
        saved_theme = self.lib.get_setting("theme", "system")
        self.theme_seg.setCurrent({"system": 0, "light": 1, "dark": 2}.get(saved_theme, 0))
        self.theme_seg.changed.connect(self._save_theme)
        ap_row.addWidget(ap_lab)
        ap_row.addWidget(self.theme_seg, 1)
        form_ap.addLayout(ap_row)
        ap_hint = QLabel(t("切换语言或主题立即生效（窗口自动重建）。",
                           "Language and theme take effect immediately "
                           "(the window is rebuilt)."))
        ap_hint.setObjectName("Hint")
        form_ap.addWidget(ap_hint)
        lay.addWidget(card_ap)

        card, form = make_card(t("个人", "Personal"))

        row = QHBoxLayout()
        lab = QLabel(t("拍摄者名字（分享卡署名）", "Photographer name (share-card credit)"))
        lab.setObjectName("RowLabel")
        self.name_edit = QLineEdit(self.lib.get_setting("photographer_name", ""))
        self.name_edit.setPlaceholderText(
            t("用于分享卡, EXIF作者信息优先",
              "Used on share cards; EXIF artist takes priority"))
        self.name_edit.editingFinished.connect(self._save_name)
        row.addWidget(lab)
        row.addWidget(self.name_edit, 1)
        form.addLayout(row)
        lay.addWidget(card)

        card2, form2 = make_card(t("识别", "Recognition"))
        row2 = QHBoxLayout()
        lab2 = QLabel(t("默认拍摄地区", "Default region"))
        lab2.setObjectName("RowLabel")
        self.region_combo = QComboBox()
        self.sub_combo = QComboBox()
        tree = regions.build_tree()
        self.region_combo.addItem(tree["global_name"], "GLOBAL")
        for c in tree["countries"]:
            self.region_combo.addItem(c["name"], c["id"])
        self.region_combo.currentIndexChanged.connect(self._country_changed)
        self.sub_combo.currentIndexChanged.connect(self._save_region)
        row2.addWidget(lab2)
        row2.addWidget(self.region_combo)
        row2.addWidget(self.sub_combo)
        row2.addStretch(1)
        form2.addLayout(row2)
        reg_hint2 = QLabel(
            t("选到省份识别更准；导入页可临时换地区。新导入的照片生效。",
              "Selecting a province improves accuracy; the Import page can "
              "override per batch. Applies to newly imported photos."))
        reg_hint2.setObjectName("Hint")
        form2.addWidget(reg_hint2)
        # 恢复保存值(可能是国家或省, 如 CN / CN-11→实际为CN-BJ式代码)
        saved = self.lib.get_setting("default_region", "GLOBAL")
        country_id = saved.split("-")[0] if "-" in saved and saved != "GLOBAL" else saved
        self.region_combo.setCurrentIndex(max(0, self.region_combo.findData(country_id)))
        self._country_changed()
        if "-" in saved and saved != "GLOBAL":
            i = self.sub_combo.findData(saved)
            if i > 0:
                self.sub_combo.setCurrentIndex(i)

        row3 = QHBoxLayout()
        lab3 = QLabel(t("检测灵敏度", "Detection sensitivity"))
        lab3.setObjectName("RowLabel")
        self.sens_seg = SegmentedControl(
            [t("低（少误检）", "Low (fewer false hits)"),
             t("中", "Medium"), t("高（多检出）", "High (more detections)")])
        conf = self.lib.get_setting("detect_conf", "0.25")
        self.sens_seg.setCurrent({"0.35": 0, "0.25": 1, "0.15": 2}.get(conf, 1))
        self.sens_seg.changed.connect(self._save_sens)
        row3.addWidget(lab3)
        row3.addWidget(self.sens_seg, 1)
        form2.addLayout(row3)
        hint = QLabel(
            t("灵敏度影响检测器的鸟框召回，新导入的照片生效。",
              "Sensitivity controls how many bird boxes the detector recalls. "
              "Applies to newly imported photos."))
        hint.setObjectName("Hint")
        form2.addWidget(hint)
        lay.addWidget(card2)

        card3, form3 = make_card(t("照片库", "Library"))
        row3 = QHBoxLayout()
        lab3 = QLabel(t("库位置", "Library location"))
        lab3.setObjectName("RowLabel")
        self.lib_label = QLabel(str(self.lib.root))
        self.lib_label.setObjectName("RowValue")
        b = QPushButton(t("在资源管理器中打开", "Open in Explorer"))
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(self._open_lib)
        row3.addWidget(lab3)
        row3.addWidget(self.lib_label, 1)
        row3.addWidget(b)
        form3.addLayout(row3)
        note = QLabel(
            t("catalog.db 为编目数据库, thumbnails/ 为缩略图缓存; "
              "原始照片文件不受影响。",
              "catalog.db is the catalog database, thumbnails/ is the cache; "
              "your original photos are never touched."))
        note.setObjectName("Hint")
        form3.addWidget(note)

        bk_row = QHBoxLayout()
        bk_lab = QLabel(t("自动备份", "Auto backup"))
        bk_lab.setObjectName("RowLabel")
        self.bk_label = QLabel(self.lib.last_backup_info())
        self.bk_label.setObjectName("RowValue")
        bk_btn = QPushButton(t("立即备份", "Back up now"))
        bk_btn.setCursor(Qt.PointingHandCursor)
        bk_btn.clicked.connect(self._backup_now)
        bk_row.addWidget(bk_lab)
        bk_row.addWidget(self.bk_label, 1)
        bk_row.addWidget(bk_btn)
        form3.addLayout(bk_row)
        bk_note = QLabel(
            t("每次启动自动检查，距上次备份超过24小时即备份一份，保留最近7份；"
              "备份在 <库>/backups/，只备数据库，原照片不在内。",
              "Checked on every launch; a new backup is made if the last one is "
              "over 24h old, keeping the most recent 7. Backups live in "
              "<library>/backups/ and contain the database only."))
        bk_note.setObjectName("Hint")
        bk_note.setWordWrap(True)
        form3.addWidget(bk_note)
        lay.addWidget(card3)

        card5, form5 = make_card(t("地图", "Map"))

        eng_row = QHBoxLayout()
        eng_lab = QLabel(t("地图引擎", "Map engine"))
        eng_lab.setObjectName("RowLabel")
        self.engine_seg = SegmentedControl(
            [t("免Key高德底图", "Keyless Amap tiles"),
             t("全球矢量", "Global vector"), t("高德官方", "Amap official")])
        eng_saved = self.lib.get_setting("map_engine", "maplibre_free")
        if eng_saved == "maplibre":
            eng_saved = "maptiler"
        self.engine_seg.setCurrent(
            {"maplibre_free": 0, "maptiler": 1, "amap": 2}.get(eng_saved, 0))
        self.engine_seg.changed.connect(self._save_engine)
        eng_row.addWidget(eng_lab)
        eng_row.addWidget(self.engine_seg, 1)
        form5.addLayout(eng_row)

        row5 = QHBoxLayout()
        lab5 = QLabel(t("高德 Key（地点搜索用，Web服务）",
                        "Amap key (place search, Web service)"))
        lab5.setObjectName("RowLabel")
        self.key_edit = QLineEdit(self.lib.get_setting("amap_key", ""))
        self.key_edit.setPlaceholderText(
            t("填自己的高德Web服务Key后可用地名搜索",
              "Enter your own Amap Web-service key to enable search"))
        self.key_edit.editingFinished.connect(self._save_amap_key)
        row5.addWidget(lab5)
        row5.addWidget(self.key_edit, 1)
        form5.addLayout(row5)

        row_mt = QHBoxLayout()
        lab_mt = QLabel(t("MapTiler Key（开源地图底图）",
                          "MapTiler key (open-source basemap)"))
        lab_mt.setObjectName("RowLabel")
        from .amap_view import DEFAULT_MAPTILER_KEY
        self.mtkey_edit = QLineEdit(self.lib.get_setting("maptiler_key", ""))
        self.mtkey_edit.setPlaceholderText(
            t(f"留空用内置团队Key（{DEFAULT_MAPTILER_KEY[:8]}…，与安卓版同源）",
              f"Empty = built-in team key ({DEFAULT_MAPTILER_KEY[:8]}…, "
              "shared with the Android app)"))
        self.mtkey_edit.editingFinished.connect(self._save_mt_key)
        row_mt.addWidget(lab_mt)
        row_mt.addWidget(self.mtkey_edit, 1)
        form5.addLayout(row_mt)

        row6 = QHBoxLayout()
        lab6 = QLabel(t("高德 Key（地图渲染用，JS API）",
                        "Amap key (map rendering, JS API)"))
        lab6.setObjectName("RowLabel")
        self.jskey_edit = QLineEdit(self.lib.get_setting("map_js_key", ""))
        self.jskey_edit.setPlaceholderText(
            t("仅「高德官方」引擎需要，填自己的Key",
              "Only for the Amap-official engine; enter your own key"))
        self.jskey_edit.editingFinished.connect(self._save_js_key)
        row6.addWidget(lab6)
        row6.addWidget(self.jskey_edit, 1)
        form5.addLayout(row6)

        row7 = QHBoxLayout()
        lab7 = QLabel(t("安全密钥（securityJsCode）", "Security code (securityJsCode)"))
        lab7.setObjectName("RowLabel")
        self.jssec_edit = QLineEdit(self.lib.get_setting("map_js_secret", ""))
        self.jssec_edit.setPlaceholderText(
            t("与高德JS Key成对使用", "Paired with the Amap JS key"))
        self.jssec_edit.setEchoMode(QLineEdit.Password)
        self.jssec_edit.editingFinished.connect(self._save_js_key)
        row7.addWidget(lab7)
        row7.addWidget(self.jssec_edit, 1)
        form5.addLayout(row7)

        key_hint = QLabel(
            t("「免Key高德底图」（默认）= 开源MapLibre引擎 + 高德栅格瓦片，"
              "不需要任何Key，国内速度最快；\n「全球矢量」= MapTiler（海外数据完整，"
              "内置团队Key，可换成自己的）；「高德官方」= 高德JS交互地图"
              "（需填自己的Key）。\n地名搜索走高德Web服务，请填自己的Key。"
              "换引擎或改Key后重开地图页生效。",
              "\"Keyless Amap tiles\" (default) = open-source MapLibre + Amap "
              "raster tiles, no key needed, fastest in China;\n"
              "\"Global vector\" = MapTiler (complete worldwide data, built-in "
              "team key, replaceable with your own);\n\"Amap official\" = the "
              "official Amap JS map (your own key required).\nPlace search uses "
              "the Amap Web service — enter your own key. Reopen the map page "
              "to apply engine/key changes."))
        key_hint.setObjectName("Hint")
        key_hint.setWordWrap(True)
        form5.addWidget(key_hint)
        lay.addWidget(card5)

        card4, form4 = make_card(t("关于", "About"))
        from ..version import VERSION
        about = QLabel(
            f"BirdTrace for Windows {VERSION}\n"
            + t("识别模型: BirdTrace FastViT-MA36 (10480类) · 检测: YOLO11n\n"
                "分类体系: eBird v2025 · 地理先验: eBird Status & Trends · "
                "保护等级: IUCN 2026-1",
                "Recognition: BirdTrace FastViT-MA36 (10,480 species) · "
                "Detector: YOLO11n\nTaxonomy: eBird v2025 · Geo prior: eBird "
                "Status & Trends · Red list: IUCN 2026-1"))
        about.setObjectName("Hint")
        about.setWordWrap(True)
        form4.addWidget(about)
        lay.addWidget(card4)

        lay.addStretch(1)

    def _save_name(self):
        self.lib.set_setting("photographer_name", self.name_edit.text().strip())

    def _rebuild_window(self):
        """整窗重建(语言/主题切换共用): 新窗构建时按当前设置重新取文案。"""
        from PySide6.QtWidgets import QApplication
        old = self.win
        if old.worker and old.worker.isRunning():
            old.worker.stop()
            old.worker.wait(3000)
        if getattr(old, "aes_worker", None) and old.aes_worker.isRunning():
            old.aes_worker.stop()
            old.aes_worker.wait(3000)
        from .main_window import MainWindow
        new = MainWindow(old.lib, old.assets)
        new.show()
        new.switch_to("settings")
        old.hide()
        old.deleteLater()

    def _save_lang(self, idx: int):
        lang = "en" if idx == 1 else "zh"
        if lang == self.lib.get_setting("lang", "zh"):
            return
        self.lib.set_setting("lang", lang)
        from .. import i18n
        i18n.set_lang(lang)
        self._rebuild_window()

    def _save_theme(self, idx: int):
        mode = {0: "system", 1: "light", 2: "dark"}[idx]
        if mode == self.lib.get_setting("theme", "system"):
            return
        self.lib.set_setting("theme", mode)
        # 立即生效: 应用主题后整窗重建(内联样式在窗口构建时求值新色)
        from PySide6.QtWidgets import QApplication
        theme.apply_theme(QApplication.instance(), mode)
        self._rebuild_window()

    def _country_changed(self, *_):
        cid = self.region_combo.currentData()
        tree = regions.build_tree()
        country = next((c for c in tree["countries"] if c["id"] == cid), None)
        self.sub_combo.blockSignals(True)
        self.sub_combo.clear()
        if country and country["subs"]:
            self.sub_combo.addItem(
                t(f"整个{country['name']}", f"All of {country['name']}"),
                country["id"])
            for s in country["subs"]:
                self.sub_combo.addItem(s["name"], s["id"])
            self.sub_combo.setEnabled(True)
        else:
            self.sub_combo.setEnabled(False)
        self.sub_combo.blockSignals(False)
        self._save_region()

    def _save_region(self):
        # 省级选择优先(识别先验更准); 无省国家存国家码
        if self.sub_combo.isEnabled() and self.sub_combo.currentData():
            rid = self.sub_combo.currentData()
        else:
            rid = self.region_combo.currentData() or "GLOBAL"
        self.lib.set_setting("default_region", rid)

    def _save_sens(self, idx: int):
        conf = {0: "0.35", 1: "0.25", 2: "0.15"}[idx]
        self.lib.set_setting("detect_conf", conf)

    def _save_engine(self, idx: int):
        engine = {0: "maplibre_free", 1: "maptiler", 2: "amap"}[idx]
        if engine != self.lib.get_setting("map_engine", "maplibre_free"):
            self.lib.set_setting("map_engine", engine)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, t("地图引擎已切换", "Map engine changed"),
                t("已切换地图引擎，重新打开地图页（或重启鸟迹）后生效。",
                  "Engine switched. Reopen the map page (or restart BirdTrace) "
                  "to apply."))

    def _save_mt_key(self):
        self.lib.set_setting("maptiler_key", self.mtkey_edit.text().strip())

    def _save_amap_key(self):
        self.lib.set_setting("amap_key", self.key_edit.text().strip())

    def _save_js_key(self):
        self.lib.set_setting("map_js_key", self.jskey_edit.text().strip())
        self.lib.set_setting("map_js_secret", self.jssec_edit.text().strip())

    def _backup_now(self):
        dst = self.lib.maybe_backup(force=True)
        self.bk_label.setText(self.lib.last_backup_info())
        if dst:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, t("备份完成", "Backup done"),
                t(f"已备份到：\n{dst}", f"Backed up to:\n{dst}"))

    def _open_lib(self):
        import subprocess
        subprocess.Popen(["explorer", str(self.lib.root)])
