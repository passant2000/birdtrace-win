# -*- coding: utf-8 -*-
"""导入页: Lightroom式导入。

来源: 选择图片文件(可多选) 或 文件夹(+子文件夹开关)
模式: 引用原位置 / 复制到新位置
地区: 级联选择 全球/国家/省份, 识别时作为地理先验
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QProgressBar, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ..core import regions
from ..core.importer import import_files, scan_sources
from ..db import Library
from ..i18n import t
from ..media import ensure_thumbnail, file_hash
from .. import theme
from ..theme.widgets import PhotoGridItem, SegmentedControl, ToggleSwitch, make_card

PREVIEW_THUMB = 120
GRID_COLS = 7


class PreviewThread(QThread):
    """后台扫描+hash+缩略图: 选文件夹后UI不冻结(每张回传一个预览项)。"""
    item_ready = Signal(object, str, object, bool)   # Path, hash|None, QPixmap|None, imported
    scan_done = Signal(int, int)                     # total, duplicated

    def __init__(self, lib: Library, files, parent=None):
        super().__init__(parent)
        self.lib = lib
        self.files = files
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        total = len(self.files)
        dup = 0
        # 批量hash后一次性查库, 减少SQLite往返
        CHUNK = 200
        known_paths = set()
        for f in self.files:
            if self.lib.photo_by_path(str(f)):
                known_paths.add(str(f))
        for i in range(0, total, CHUNK):
            if self._stop:
                break
            chunk = self.files[i:i + CHUNK]
            hashes = {}
            for f in chunk:
                try:
                    hashes[f] = file_hash(f)
                except OSError:
                    hashes[f] = None
            known = self.lib.existing_hashes([h for h in hashes.values() if h])
            for f in chunk:
                if self._stop:
                    break
                fh = hashes.get(f)
                imported = str(f) in known_paths or (fh in known if fh else False)
                if imported:
                    dup += 1
                pm = None
                if fh:
                    tp = ensure_thumbnail(self.lib.root, f, fh, PREVIEW_THUMB * 2)
                    if tp:
                        pm = QPixmap(str(tp))
                self.item_ready.emit(f, fh, pm, imported)
        self.scan_done.emit(total, dup)


class ImportThread(QThread):
    progress = Signal(int, int, str)
    done = Signal(dict)

    def __init__(self, lib: Library, files, mode, dest, region_id,
                 spot_id=None, auto_spot=True, parent=None):
        super().__init__(parent)
        self.lib = lib
        self.files = files
        self.mode = mode
        self.dest = dest
        self.region_id = region_id
        self.spot_id = spot_id
        self.auto_spot = auto_spot

    def run(self):
        stats = import_files(self.lib, self.files, self.mode, self.dest,
                             self.region_id, spot_id=self.spot_id,
                             auto_spot=self.auto_spot,
                             progress_cb=lambda d, t, name: self.progress.emit(d, t, name))
        self.done.emit(stats)


class ImportPage(QWidget):
    def __init__(self, lib: Library, assets_dir: Path, win):
        super().__init__()
        self.lib = lib
        self.assets = assets_dir
        self.win = win
        self.files: list[Path] = []
        self.existing: set[str] = set()   # 已在库中的内容hash
        self.import_thread = None
        self.preview_thread = None
        self._known_hashes: dict = {}     # Path -> hash(预览线程回传)
        self._build_ui()

    def _build_ui(self):
        # 整页可滚动: 卡片多时不再撑大窗口最小高度(窗口可自由缩小)
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

        title = QLabel(t("导入照片", "Import photos"))
        title.setStyleSheet(f"font-size:26px;font-weight:800;color:{theme.LABEL};"
                            "background:transparent;")
        lay.addWidget(title)

        # ---- 地区(重要: 边框高亮——选错地区=识别按错误名录跑, 2026-11-04用户) ----
        card3, form3 = make_card(t("拍摄地区（提高识别准确率）", "Region (improves ID accuracy)"))
        card3.setStyleSheet("QFrame{border:2px solid #F5A623;border-radius:12px;}")
        reg_row = QHBoxLayout()
        self.country_combo = QComboBox()
        self.sub_combo = QComboBox()
        self.country_combo.setMinimumWidth(220)
        self.sub_combo.setMinimumWidth(220)
        self.country_combo.currentIndexChanged.connect(self._country_changed)
        reg_row.addWidget(self.country_combo)
        reg_row.addWidget(self.sub_combo)
        reg_row.addStretch(1)
        form3.addLayout(reg_row)
        reg_hint = QLabel(t("识别时会结合所选地区与拍摄月份的物种分布先验重新排序识别结果。",
                            "Identification results are reranked using species distribution "
                            "priors for the selected region and capture month."))
        reg_hint.setObjectName("Hint")
        form3.addWidget(reg_hint)
        lay.addWidget(card3)
        # ---- 来源 ----
        card, form = make_card(t("来源", "Source"))
        row = QHBoxLayout()
        row.setSpacing(10)
        b_files = QPushButton(t("选择图片文件…", "Select photos…"))
        b_files.setCursor(Qt.PointingHandCursor)
        b_files.clicked.connect(self._pick_files)
        b_folder = QPushButton(t("选择文件夹…", "Select folder…"))
        b_folder.setCursor(Qt.PointingHandCursor)
        b_folder.clicked.connect(self._pick_folder)
        row.addWidget(b_files)
        row.addWidget(b_folder)
        # 开始导入放在来源卡里(顶部): 选完文件夹按钮就在手边,
        # 不用再滚到底部(用户需求; 预览后台化后选完即可导入)
        self.go_btn = QPushButton(t("开始导入", "Start import"))
        self.go_btn.setObjectName("Primary")
        self.go_btn.setCursor(Qt.PointingHandCursor)
        self.go_btn.setEnabled(False)
        self.go_btn.clicked.connect(self._start_import)
        row.addWidget(self.go_btn)
        # 临时识别: 截图/任选图片直接识别, 不入库
        self.tempid_btn = QPushButton(t("🔍 临时识别…", "🔍 Quick ID…"))
        self.tempid_btn.setCursor(Qt.PointingHandCursor)
        self.tempid_btn.setToolTip(t(
            "对剪贴板截图或任选图片直接识别鸟种，不保存到照片库",
            "Recognize a pasted screenshot or any image without saving it "
            "to the library"))
        self.tempid_btn.clicked.connect(self._open_temp_id)
        row.addWidget(self.tempid_btn)

        self.recursive = ToggleSwitch(True)
        row.addStretch(1)
        lab = QLabel(t("包含子文件夹", "Include subfolders"))
        lab.setObjectName("RowLabel")
        row.addWidget(lab)
        row.addWidget(self.recursive)
        form.addLayout(row)

        self.src_label = QLabel(t("尚未选择 · 支持JPG / PNG / WebP / HEIC",
                                  "Nothing selected · JPG / PNG / WebP / HEIC supported"))
        self.src_label.setObjectName("Hint")
        form.addWidget(self.src_label)
        lay.addWidget(card)

        # ---- 目标 ----
        card2, form2 = make_card(t("导入方式", "Import mode"))
        self.mode_seg = SegmentedControl(
            [t("引用原位置（文件不动）", "Reference (files stay in place)"),
             t("复制到新位置", "Copy to new location"),
             t("移动到新位置", "Move to new location")])
        form2.addWidget(self.mode_seg)
        self.mode_seg.changed.connect(self._mode_changed)

        dest_row = QHBoxLayout()
        self.dest_edit = QLineEdit()
        self.dest_edit.setPlaceholderText(t("选择复制目标文件夹…", "Choose destination folder…"))
        self.dest_edit.setReadOnly(True)
        b_dest = QPushButton(t("选择…", "Browse…"))
        b_dest.setCursor(Qt.PointingHandCursor)
        b_dest.clicked.connect(self._pick_dest)
        dest_row.addWidget(self.dest_edit, 1)
        dest_row.addWidget(b_dest)
        self.dest_row_widget = QWidget()
        self.dest_row_widget.setLayout(dest_row)
        self.dest_row_widget.setVisible(False)
        form2.addWidget(self.dest_row_widget)

        hint = QLabel(t("引用：文件留在原地，鸟迹只做记录（最安全）；"
                        "复制：按 拍摄年月/ 归档副本到目标目录；"
                        "移动：把文件移入目标目录归档（原位置不再保留，Lightroom式）。",
                        "Reference: files stay in place and BirdTrace only records them "
                        "(safest); Copy: archives copies to the destination folder by "
                        "year/month taken; Move: moves files into the destination folder "
                        "(originals not kept, Lightroom-style)."))
        hint.setObjectName("Hint")
        form2.addWidget(hint)
        lay.addWidget(card2)


        # ---- 鸟点 ----
        card4, form4 = make_card(t("挂到鸟点（可省）", "Assign to spot (optional)"))
        spot_row = QHBoxLayout()
        self.spot_combo = QComboBox()
        self.spot_combo.setMinimumWidth(280)
        self.spot_combo.currentIndexChanged.connect(self._spot_changed)
        spot_row.addWidget(self.spot_combo)
        spot_row.addStretch(1)
        form4.addLayout(spot_row)
        self.spot_hint = QLabel(t("自动：按照片EXIF的GPS归组，300米内并入已有鸟点，"
                                  "没有就自动新建。相机没有GPS时，导入完成后"
                                  "会询问是否为整批照片设置鸟点。",
                                  "Auto: groups photos by EXIF GPS, merging into existing "
                                  "spots within 300 meters and creating new ones as needed. "
                                  "If the camera has no GPS, you'll be asked after import "
                                  "whether to assign a spot to the whole batch."))
        self.spot_hint.setObjectName("Hint")
        self.spot_hint.setWordWrap(True)
        form4.addWidget(self.spot_hint)
        lay.addWidget(card4)

        # ---- 预览网格 ----
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(10)
        self.scroll.setWidget(self.grid_host)
        self.scroll.setMinimumHeight(160)
        lay.addWidget(self.scroll, 1)

        # ---- 底部状态条(开始导入已挪到顶部来源卡) ----
        bottom = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setFixedHeight(10)
        self.progress.setVisible(False)
        self.status = QLabel("")
        self.status.setObjectName("Hint")
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.progress, 2)
        lay.addLayout(bottom)

        self._load_regions()
        self._load_spots()
        self._mode_changed(0)

    # ---------- 鸟点 ----------
    AUTO = "__auto__"
    NONE = "__none__"
    NEW = "__new__"

    def _load_spots(self):
        """刷新鸟点下拉, 尽量保持当前选择。"""
        cur = self.spot_combo.currentData()
        self.spot_combo.blockSignals(True)
        self.spot_combo.clear()
        self.spot_combo.addItem(t("自动按GPS归组（推荐）", "Auto-group by GPS (recommended)"), self.AUTO)
        self.spot_combo.addItem(t("不挂鸟点", "No spot"), self.NONE)
        for sp in self.lib.spots_overview():
            self.spot_combo.addItem(
                t(f"📍 {sp['name']}（{sp['n_photos']} 张）",
                  f"📍 {sp['name']} ({sp['n_photos']} photos)"), sp["id"])
        self.spot_combo.addItem(t("＋ 新建鸟点…", "＋ New spot…"), self.NEW)
        idx = self.spot_combo.findData(cur) if cur is not None else 0
        self.spot_combo.setCurrentIndex(max(0, idx))
        self.spot_combo.blockSignals(False)
        self._update_spot_hint()

    def _spot_changed(self, *_):
        data = self.spot_combo.currentData()
        if data != self.NEW:
            self._update_spot_hint()
            return
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, t("新建鸟点", "New spot"),
                                        t("鸟点名称（导入后可在「鸟点」页修改）：",
                                          "Spot name (can be edited later on the Spots page):"))
        self.spot_combo.blockSignals(True)
        if ok and name.strip():
            sid = self.lib.create_spot(name.strip())
            n = self.spot_combo.count()
            self.spot_combo.insertItem(
                n - 1, t(f"📍 {name.strip()}（0 张）", f"📍 {name.strip()} (0 photos)"), sid)
            self.spot_combo.setCurrentIndex(n - 1)
        else:
            self.spot_combo.setCurrentIndex(0)
        self.spot_combo.blockSignals(False)
        self._update_spot_hint()

    def _update_spot_hint(self):
        data = self.spot_combo.currentData()
        if data == self.AUTO:
            self.spot_hint.setText(
                t("自动：按照片EXIF的GPS归组，300米内并入已有鸟点，没有就自动新建。",
                  "Auto: groups photos by EXIF GPS, merging into existing spots within "
                  "300 meters and creating new ones as needed."))
        elif data == self.NONE:
            self.spot_hint.setText(t("本次导入的照片不关联任何鸟点。",
                                     "Photos in this import won't be linked to any spot."))
        else:
            self.spot_hint.setText(t("本批导入的全部照片将挂到所选鸟点。",
                                     "All photos in this batch will be assigned to the selected spot."))

    def refresh(self):
        """库变化后刷新鸟点列表(main_window统一调用)。"""
        self._load_spots()

    # ---------- 地区 ----------
    def _load_regions(self):
        tree = regions.build_tree()
        self.country_combo.blockSignals(True)
        self.country_combo.clear()
        self.country_combo.addItem(tree["global_name"], "GLOBAL")
        for c in tree["countries"]:
            self.country_combo.addItem(c["name"], c["id"])
        self.country_combo.blockSignals(False)
        # 恢复默认地区(可能是国家或省级, 如 CN / CN-11)
        saved = self.lib.get_setting("default_region", "GLOBAL")
        country_id = saved.split("-")[0] if saved not in ("GLOBAL", "") and "-" in saved else saved
        idx = self.country_combo.findData(country_id)
        self.country_combo.setCurrentIndex(max(0, idx))
        self._country_changed()
        if country_id != saved:
            i = self.sub_combo.findData(saved)
            if i > 0:
                self.sub_combo.setCurrentIndex(i)

    def _country_changed(self, *_):
        cid = self.country_combo.currentData()
        tree = regions.build_tree()
        country = next((c for c in tree["countries"] if c["id"] == cid), None)
        self.sub_combo.blockSignals(True)
        self.sub_combo.clear()
        if country and country["subs"]:
            self.sub_combo.addItem(t(f"整个{country['name']}", f"Entire {country['name']}"), country["id"])
            for s in country["subs"]:
                self.sub_combo.addItem(s["name"], s["id"])
            self.sub_combo.setEnabled(True)
        else:
            self.sub_combo.setEnabled(False)
        self.sub_combo.blockSignals(False)

    def current_region(self) -> str:
        cid = self.country_combo.currentData() or "GLOBAL"
        if self.sub_combo.isEnabled() and self.sub_combo.currentData():
            return self.sub_combo.currentData()
        return cid

    # ---------- 来源选择 ----------
    def _open_temp_id(self):
        # 局部import: 识别子进程QProcess在对话框内自管, 非模态(可边导入边用)
        from .temp_id_dialog import TempIdDialog
        if getattr(self, "_tempid", None) is not None \
                and self._tempid.isVisible():
            self._tempid.raise_()
            self._tempid.activateWindow()
            return
        self._tempid = TempIdDialog(self.lib, self.win, parent=self.win)
        self._tempid.show()

    def _pick_files(self):
        exts = " ".join(f"*{e}" for e in
                        [".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".tif"])
        files, _ = QFileDialog.getOpenFileNames(
            self, t("选择图片", "Select photos"), self.lib.get_setting("last_import_dir", ""),
            t(f"图片文件 ({exts})", f"Image files ({exts})"))
        if files:
            self._set_sources([Path(f) for f in files])

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(
            self, t("选择文件夹", "Select folder"), self.lib.get_setting("last_import_dir", ""))
        if d:
            self._set_sources([Path(d)], folder=True)

    def _set_sources(self, paths: list[Path], folder: bool = False):
        self.lib.set_setting("last_import_dir", str(paths[0].parent if not folder else paths[0]))
        self.files = scan_sources(paths, self.recursive.isChecked())
        n = len(self.files)
        folder_txt = t(f"文件夹 {paths[0].name}", f"Folder {paths[0].name}") + (t("（含子文件夹）", " (with subfolders)") if folder else "")
        self.src_label.setText(
            f"{folder_txt if folder else t(f'{len(paths)} 个文件', f'{len(paths)} files')}"
            + t(f" · 扫描到 {n} 张照片，预览在后台生成，可直接开始导入",
                f" · {n} photos found, previews build in the background — you can start importing now"))
        # 预览只是可视化(hash/已导入角标), 导入流程不依赖它——
        # 立即放开按钮, 大文件夹不必等全量缩略图(用户实测等很久)
        self.go_btn.setEnabled(n > 0)
        self._start_preview()

    def _start_preview(self):
        # 预览后台化(修bug: 大文件夹选完卡死几十秒): hash+缩略图全在子线程
        if self.preview_thread and self.preview_thread.isRunning():
            self.preview_thread.stop()
            self.preview_thread.wait(2000)
        self._known_hashes = {}
        # 网格占位: 先放空位, item_ready逐个回填
        self._populate_grid()
        self.preview_thread = PreviewThread(self.lib, list(self.files))
        self.preview_thread.item_ready.connect(self._on_preview_item)
        self.preview_thread.scan_done.connect(self._on_preview_done)
        self.preview_thread.start()

    def _on_preview_item(self, f, fh, pm, imported):
        self._known_hashes[f] = fh
        if imported:
            self.existing.add(fh) if fh else None
        item = self.grid.itemAt(self.files.index(f)) if f in self.files else None
        w = item.widget() if item else None
        if w is None:
            return
        corner = t("已导入", "Imported") if imported else None
        w.pixmap = pm
        w.corner = corner
        w.setToolTip(t("已在照片库中, 导入时将自动跳过",
                       "Already in the library; will be skipped during import") if imported else "")
        w.update()

    def _on_preview_done(self, total, dup):
        self.status.setText(t(f"{total} 张待导入", f"{total} photos to import") +
                            (t(f" · {dup} 张已在库中将跳过", f" · {dup} already in the library, will be skipped") if dup else ""))
        self.go_btn.setEnabled(bool(self.files))

    def _populate_grid(self):
        # 轻量占位网格: 重活(hash/查库/缩略图)在PreviewThread, 这里只铺位
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, f in enumerate(self.files):
            item = PhotoGridItem(None, label=f.name)
            self.grid.addWidget(item, i // GRID_COLS, i % GRID_COLS)
        for c in range(GRID_COLS):
            self.grid.setColumnStretch(c, 1)
        self.status.setText(t(f"{len(self.files)} 张待导入 · 预览生成中…",
                              f"{len(self.files)} photos to import · building previews…"))

    # ---------- 模式 ----------
    def _mode_changed(self, idx: int):
        # 复制和移动都需要目标文件夹(此前移动模式漏了)
        self.dest_row_widget.setVisible(idx >= 1)
        if idx >= 1:
            self.dest_edit.setPlaceholderText(
                t("选择目标文件夹…（按 拍摄年月/ 自动分目录）",
                  "Choose destination folder… (organized by year/month taken)"))

    def _pick_dest(self):
        d = QFileDialog.getExistingDirectory(self, t("选择复制目标文件夹", "Choose destination folder"))
        if d:
            self.dest_edit.setText(d)

    # ---------- 导入 ----------
    def _start_import(self):
        mode = {0: "ref", 1: "copy", 2: "move"}[self.mode_seg.currentIndex()]
        dest = None
        if mode in ("copy", "move"):
            dest = self.dest_edit.text().strip()
            if not dest:
                self.status.setText(
                    t(f"请先选择{'复制' if mode == 'copy' else '移动'}目标文件夹（点「选择…」）",
                      "Choose a destination folder first (click Browse…)"))
                return
        region = self.current_region()
        # 拍摄地区确认(2026-11-04用户: 地区太重要, 开始导入前确认一次;
        # 不对→返回修改地区再点开始导入)
        from ..core import regions as _regions
        region_txt = _regions.region_display(region) if region and region != "GLOBAL"             else t("全球（未指定地区）", "Global (no region set)")
        spot_txt = t("不挂鸟点", "No spot")
        spot_data = self.spot_combo.currentData()
        if spot_data == self.AUTO:
            spot_txt = t("按GPS自动归点", "Auto by GPS")
        elif isinstance(spot_data, int):
            info = self.lib.spot_info(spot_data)
            spot_txt = info["name"] if info else str(spot_data)
        mode_txt = {0: t("引用原位置", "Reference originals"),
                    1: t("复制到新位置", "Copy to new location"),
                    2: t("移动到新位置", "Move to new location")}[mode]
        from PySide6.QtWidgets import QMessageBox
        r = QMessageBox.question(
            self, t("确认拍摄地区", "Confirm shooting region"),
            t(f"拍摄地区：{region_txt}\n"
              f"鸟点：{spot_txt}\n"
              f"导入方式：{mode_txt}\n\n"
              "地区决定识别使用的物种名录与先验——确认无误再开始导入。"
              "\n（选错了？点 No 返回修改后再点「开始导入」）",
              f"Shooting region: {region_txt}\n"
              f"Spot: {spot_txt}\n"
              f"Import mode: {mode_txt}\n\n"
              "The region decides which species list and prior are used "
              "for ID — confirm before importing.\n"
              "(Wrong? Click No to go back and fix it.)"))
        if r != QMessageBox.Yes:
            return
        self.lib.set_setting("default_region", region)
        spot_data = self.spot_combo.currentData()
        self._last_spot_choice = spot_data
        spot_id = spot_data if isinstance(spot_data, int) else None
        auto_spot = spot_data == self.AUTO
        self.go_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.status.setText(t("导入中…", "Importing…"))
        self.import_thread = ImportThread(self.lib, list(self.files), mode,
                                          Path(dest) if dest else None, region,
                                          spot_id=spot_id, auto_spot=auto_spot)
        self.import_thread.progress.connect(self._import_progress)
        self.import_thread.done.connect(self._import_done)
        self.import_thread.start()

    def _import_progress(self, done, total, name):
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)
        # 状态栏双计数: 上报导入进度(并行识别时同屏显示 导入x/y·已识别N)
        tick = getattr(self.win, "_import_progress_tick", None)
        if tick is not None:
            tick(done, total)
        # 导入识别并行: 有照片入库即拉起识别(已在跑则跳过; worker的
        # 波次循环会自动拾取后续入库的照片——无需等全部导入完成)
        if self.win is not None and hasattr(self.win, "start_recognition"):
            self.win.start_recognition()

    def _import_done(self, stats: dict):
        self.progress.setVisible(False)
        txt = (t(f"导入完成：新增 {stats['added']}，跳过重复 {stats['skipped_dup']}",
                 f"Import complete: {stats['added']} added, {stats['skipped_dup']} duplicates skipped")
               + (t(f"，失败 {stats['failed']}", f", {stats['failed']} failed") if stats['failed'] else ""))
        if stats.get("spots_created"):
            txt += t(f"，自动新建 {stats['spots_created']} 个鸟点",
                     f", auto-created {stats['spots_created']} spot(s)")
        self.status.setText(txt)
        self.files = []

        # 导入后批量挂鸟点: 选了"不挂"或"自动但没有任何GPS可归组"时询问
        added_ids = [r["id"] for r in self.lib.conn.execute(
            "SELECT id FROM photos WHERE batch_id=? ORDER BY id",
            (stats["batch_id"],))]
        choice = getattr(self, "_last_spot_choice", None)
        note = ""
        if choice == self.NONE:
            note = t("这批照片还没有鸟点。国内相机大多没有GPS，\n"
                     "如果是同一个地方拍的，在这里一次挂好最省事。",
                     "These photos have no spot yet. Most cameras in China have no GPS.\n"
                     "If they were all taken at the same place, assign a spot to the whole batch here.")
        elif choice == self.AUTO and not stats.get("spots_created"):
            note = t("这批照片都没有GPS信息，无法自动归组。\n"
                     "如果是同一个地方拍的，在这里一次挂好最省事。",
                     "None of these photos have GPS data, so they can't be grouped automatically.\n"
                     "If they were all taken at the same place, assign a spot to the whole batch here.")
        # 识别立即启动(不等待挂点对话框——对话框模态阻塞期间识别也要跑,
        # 否则用户体感"识别完成0张/鸟种库空")
        self.win.library_changed.emit()
        self.win.start_recognition()

        if added_ids and note:
            from .spot_dialog import BatchSpotDialog
            dlg = BatchSpotDialog(self.lib, self.win, added_ids, note, self)
            dlg.exec()
            if dlg.applied:
                txt += t(f"，已挂到「{dlg.spot_name}」", f", assigned to “{dlg.spot_name}”")
                self.status.setText(txt)
                self.win.library_changed.emit()
