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

        # 版权信息(1.0冲刺⑰): 库级默认五字段, 三处消费单源
        # (分享卡署名/静态站展示/XMP写回)。原图绝不动(写回走⑪显式开关)
        card_cp, form_cp = make_card(t("版权信息（默认）", "Copyright (defaults)"))
        self.cp_edits: dict[str, QLineEdit] = {}
        defaults = self.lib.copyright_defaults_get()
        cp_labels = [
            ("creator", t("创作者", "Creator"),
             t("如：张三（分享卡署名默认从这里取）", "e.g. Zhang San")),
            ("copyright_owner", t("版权所有者", "Owner"), ""),
            ("copyright_notice", t("版权声明", "Notice"), ""),
            ("credit_line", t("署名行", "Credit line"), ""),
            ("rights_usage_terms", t("使用条款", "Usage terms"), ""),
        ]
        for key, lab_t, ph in cp_labels:
            r2 = QHBoxLayout()
            l2 = QLabel(lab_t)
            l2.setObjectName("RowLabel")
            e2 = QLineEdit(defaults.get(key, ""))
            e2.setPlaceholderText(ph or t("可省", "optional"))
            e2.editingFinished.connect(self._save_copyright)
            self.cp_edits[key] = e2
            r2.addWidget(l2)
            r2.addWidget(e2, 1)
            form_cp.addLayout(r2)
        cp_hint = QLabel(t(
            "库级默认，全部照片共用；只存鸟迹库与 sidecar，不改原图 EXIF。",
            "Library-level defaults shared by all photos; stored in the "
            "BirdTrace DB and sidecar only, original EXIF never touched."))
        cp_hint.setWordWrap(True)
        cp_hint.setObjectName("Hint")
        form_cp.addWidget(cp_hint)
        lay.addWidget(card_cp)

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
        # 识别引擎说明(2026-10-31定版: 彻底移植SuperPicky为唯一引擎, 不设切换;
        # 0.6引擎代码保留在app/ai/pipeline.py, 仅作开发对照不进UI)
        eng_hint = QLabel(
            t("识别引擎：SuperPicky 同款（bbox方形裁剪＋eBird地区名录硬过滤）。"
              "识别不了的照片不写鸟名，进鸟种库「未识别」不计鸟种数。",
              "Engine: identical to SuperPicky (bbox square crop + hard eBird "
              "regional filtering). Photos it cannot identify keep no species "
              "name and appear under \"Unidentified\" in the species library, "
              "not counted as species."))
        eng_hint.setObjectName("Hint")
        eng_hint.setWordWrap(True)
        form2.addWidget(eng_hint)
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
            [t("免Key高德底图", "Keyless Amap tiles"), t("高德官方", "Amap official")])
        eng_saved = self.lib.get_setting("map_engine", "maplibre_free")
        # 旧值 maplibre/maptiler(MapTiler引擎已移除, 政治合规)→默认引擎
        if eng_saved in ("maplibre", "maptiler"):
            eng_saved = "maplibre_free"
        self.engine_seg.setCurrent({"maplibre_free": 0, "amap": 1}.get(eng_saved, 0))
        self.engine_seg.changed.connect(self._save_engine)
        eng_row.addWidget(eng_lab)
        eng_row.addWidget(self.engine_seg, 1)
        form5.addLayout(eng_row)

        row5 = QHBoxLayout()
        lab5 = QLabel(t("高德 Key（地点搜索用，Web服务）",
                        "Amap key (place search, Web service)"))
        lab5.setObjectName("RowLabel")
        # 不回填已存值(用户要求"设置界面不显式显示"): 控件始终为空,
        # 占位文案说明状态; 留空=保持现状, 输入新值=覆盖, 也不用明文/掩码
        # 形式把Key带进界面
        stored = self.lib.get_setting("amap_key", "")
        self.key_edit = QLineEdit("")
        self.key_edit.setEchoMode(QLineEdit.Password)
        if stored:
            self.key_edit.setPlaceholderText(
                t("已保存自填Key（不显示）——留空保持，输入新值替换",
                  "A custom key is saved (hidden) — leave blank to keep, "
                  "type to replace"))
        else:
            self.key_edit.setPlaceholderText(
                t("已内置免费Key（隐藏），开箱可搜；可填自己的替换",
                  "A free built-in key (hidden) works out of the box; "
                  "optionally enter your own"))
        self.key_edit.editingFinished.connect(self._save_amap_key)
        row5.addWidget(lab5)
        row5.addWidget(self.key_edit, 1)
        form5.addLayout(row5)

        row6 = QHBoxLayout()
        lab6 = QLabel(t("高德 Key（地图渲染用，JS API）",
                        "Amap key (map rendering, JS API)"))
        lab6.setObjectName("RowLabel")
        # 同Web Key: 不回填已存值(用户要求不显式显示), 留空=保持现状
        self.jskey_edit = QLineEdit("")
        self.jskey_edit.setEchoMode(QLineEdit.Password)   # Key不明文回显
        self.jskey_edit.setPlaceholderText(
            t("已内置（隐藏），开箱可用；留空保持，输入新值替换",
              "Built-in key (hidden) works out of the box; leave blank "
              "to keep, type to replace"))
        self.jskey_edit.editingFinished.connect(self._save_js_key)
        row6.addWidget(lab6)
        row6.addWidget(self.jskey_edit, 1)
        form5.addLayout(row6)

        row7 = QHBoxLayout()
        lab7 = QLabel(t("安全密钥（securityJsCode）", "Security code (securityJsCode)"))
        lab7.setObjectName("RowLabel")
        self.jssec_edit = QLineEdit("")
        self.jssec_edit.setEchoMode(QLineEdit.Password)
        self.jssec_edit.setPlaceholderText(
            t("已内置（隐藏）；与高德JS Key成对使用，留空保持",
              "Built-in (hidden); paired with the Amap JS key, leave "
              "blank to keep"))
        self.jssec_edit.editingFinished.connect(self._save_js_key)
        row7.addWidget(lab7)
        row7.addWidget(self.jssec_edit, 1)
        form5.addLayout(row7)

        key_hint = QLabel(
            t("「免Key高德底图」（默认）= 开源MapLibre引擎 + 高德栅格瓦片，"
              "不需要任何Key，国内速度最快；\n「高德官方」= 高德JS交互地图"
              "（需填自己的Key）。地名搜索走高德Web服务，请填自己的Key。\n"
              "换引擎或改Key后重开地图页生效。",
              "\"Keyless Amap tiles\" (default) = open-source MapLibre + Amap "
              "raster tiles, no key needed, fastest in China;\n"
              "\"Amap official\" = the official Amap JS map (your own key "
              "required). Place search uses the Amap Web service — enter "
              "your own key.\nReopen the map page to apply engine/key changes."))
        key_hint.setObjectName("Hint")
        key_hint.setWordWrap(True)
        form5.addWidget(key_hint)
        lay.addWidget(card5)

        # 迁徙数据缓存(与安卓 Clear Downloaded Migration Data 同款)
        card_m, form_m = make_card(t("迁徙数据", "Migration data"))
        mrow = QHBoxLayout()
        self.mig_label = QLabel()
        self.mig_label.setObjectName("RowLabel")
        mrow.addWidget(self.mig_label, 1)
        mig_btn = QPushButton(t("清除迁徙缓存", "Clear migration cache"))
        mig_btn.clicked.connect(self._clear_migration)
        mrow.addWidget(mig_btn)
        form_m.addLayout(mrow)
        mig_hint = QLabel(t(
            "迁徙地图按需下载的鸟种数据缓存在照片库 migration 文件夹，"
            "清除后再次打开会重新下载。",
            "Species data downloaded by the migration map is cached in the "
            "library's migration folder; clearing it re-downloads on next "
            "open."))
        mig_hint.setObjectName("Hint")
        mig_hint.setWordWrap(True)
        form_m.addWidget(mig_hint)
        lay.addWidget(card_m)
        self._refresh_mig_size()

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

    def _save_copyright(self):
        self.lib.copyright_defaults_set(
            **{k: e.text() for k, e in self.cp_edits.items()})

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
        engine = {0: "maplibre_free", 1: "amap"}[idx]
        if engine != self.lib.get_setting("map_engine", "maplibre_free"):
            self.lib.set_setting("map_engine", engine)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, t("地图引擎已切换", "Map engine changed"),
                t("已切换地图引擎，重新打开地图页（或重启鸟迹）后生效。",
                  "Engine switched. Reopen the map page (or restart BirdTrace) "
                  "to apply."))

    def _save_amap_key(self):
        txt = self.key_edit.text().strip()
        if not txt:
            return          # 留空=保持现状(内置或已存Key), 不清空
        self.lib.set_setting("amap_key", txt)
        self.key_edit.clear()
        self.key_edit.setPlaceholderText(
            t("已保存自填Key（不显示）——留空保持，输入新值替换",
              "A custom key is saved (hidden) — leave blank to keep, "
              "type to replace"))

    # ---- 迁徙缓存 ----
    def _refresh_mig_size(self):
        root = self.lib.root / "migration"
        total = 0
        if root.is_dir():
            for f in root.rglob("*"):
                try:
                    if f.is_file():
                        total += f.stat().st_size
                except OSError:
                    pass
        mb = total / 1048576
        self.mig_label.setText(
            t(f"已缓存 {mb:.0f} MB", f"{mb:.0f} MB cached"))

    def _clear_migration(self):
        from PySide6.QtWidgets import QMessageBox
        import shutil
        if QMessageBox.question(
                self, t("清除迁徙缓存", "Clear migration cache"),
                t("清除迁徙地图已下载的全部鸟种数据？",
                  "Delete all species data downloaded by the migration map?"),
                ) != QMessageBox.Yes:
            return
        shutil.rmtree(self.lib.root / "migration", ignore_errors=True)
        self._refresh_mig_size()

    def _save_js_key(self):
        k = self.jskey_edit.text().strip()
        s = self.jssec_edit.text().strip()
        if k:
            self.lib.set_setting("map_js_key", k)
        if s:
            self.lib.set_setting("map_js_secret", s)
        # 留空=保持现状(内置或已存), 不清空; 保存后清输入框
        self.jskey_edit.clear()
        self.jssec_edit.clear()

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
