# -*- coding: utf-8 -*-
"""时间线页: 按年月分组展示全部照片, lifer角标, 点击看大图。
多选模式: 批量从鸟迹移除 / 批量重新识别。"""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout,
                               QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QScrollArea,
                               QSizePolicy, QTreeWidget, QTreeWidgetItem,
                               QTreeWidgetItemIterator, QVBoxLayout, QWidget)

from ..i18n import t, sname
from ..media import ensure_thumbnail
from .. import theme
from ..theme.widgets import (PhotoGridItem, ThemedDateEdit, grid_tile_of,
                             make_grid_tier_control)
from .viewer import PhotoViewer

THUMB = 128


class ThumbWorkerBatch:
    """同步生成缩略图(有缓存, 首次慢), 数据量个人级可接受。"""


class TimelinePage(QWidget):
    open_photo = Signal(int, list)

    def __init__(self, lib, win):
        super().__init__()
        self.lib = lib
        self.win = win
        self._tile = grid_tile_of(lib)   # 网格档位(0.8.5全局持久化)
        self._offline_ids: set[int] = set()
        self._missing_ids: set[int] = set()
        self._group_level = "month"   # 内容区分组级别: month(默认)/day
        self._group_day = None        # day级别下聚焦的日期(YYYY-MM-DD)
        self._tl_sp = None            # 鸟种筛选code(None=全部, 0.8.6胶囊)
        self._chips_key = None        # 鸟种胶囊范围=最近树点击(年/月/日)
        self._raw = {}                # 未过滤时间线数据(胶囊统计用)
        self._thumb_cache: dict[int, QPixmap] = {}
        self._select_mode = False
        self._selected: set[int] = set()
        self._anchor_id: int | None = None   # Shift范围选择的锚点
        self._order_ids: list[int] = []      # 当前显示顺序(refresh填充)
        self._iso_dates: dict[int, str] = {}  # photo_id → YYYY-MM-DD
        self._keep_scroll = 0          # 刷新前位置: 识别完成等刷新不跳顶
        self._tl_sig = None            # 上次构建的数据签名(无变化跳过重建)
        self._grid_items: dict[int, PhotoGridItem] = {}   # id→网格项(全选就地更新)
        self._ym_head: dict[str, QLabel] = {}   # "YYYY-MM"→月标题(时间树锚点)
        self._day_item: dict[str, PhotoGridItem] = {}   # "YYYY-MM|DD"→日首图
        self._cur_cols = 0             # 当前网格列数(窗口变化时自适应重排)
        self._resize_debounce = QTimer(self)
        self._resize_debounce.setSingleShot(True)
        self._resize_debounce.setInterval(250)
        self._resize_debounce.timeout.connect(self._on_relayout)
        self._build_ui()
        self._setup_shortcuts()

    def _setup_shortcuts(self):
        """选片快捷键(1.0冲刺①+⑨, Lightroom式): 1~5打星/0清星,
        K保留/P待定/X拒绝/U清除——只在多选模式且有选中时生效
        (handler自查 _select_mode/_selected/isVisible, 时间线页无
        文本输入框, 单键不与任何输入冲突)。"""
        from PySide6.QtGui import QKeySequence, QShortcut
        acts = {"k": lambda: self._mark_apply("keep"),
                "p": lambda: self._mark_apply("pending"),
                "x": lambda: self._mark_apply("reject"),
                "u": lambda: self._mark_apply(""),
                "0": lambda: self._rate_apply(0)}
        acts.update({str(i): (lambda _n=i: self._rate_apply(_n))
                     for i in range(1, 6)})
        for k, fn in acts.items():
            sc = QShortcut(QKeySequence(k), self)
            sc.activated.connect(fn)

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        head = QHBoxLayout()
        self.title = QLabel(t("时间线", "Timeline"))
        self.title.setStyleSheet(f"font-size:26px;font-weight:800;color:{theme.LABEL};"
                                 "background:transparent;")
        head.addWidget(self.title)
        head.addStretch(1)
        self.burst_btn = QPushButton(t("连拍折叠", "Stack bursts"))
        self.burst_btn.setCheckable(True)
        self.burst_btn.setChecked(self.lib.get_setting("burst_collapse", "1") == "1")
        self.burst_btn.setCursor(Qt.PointingHandCursor)
        self.burst_btn.setToolTip(t(
            "2秒内同鸟种的连拍折成一张封面（角标 ×N），点开看全组；多选时自动展开",
            "Stack same-species burst shots taken within 2s into one cover "
            "(×N badge); click to browse the group. Auto-expanded in select mode"))
        self.burst_btn.toggled.connect(self._toggle_collapse)
        head.addWidget(self.burst_btn)
        self.share_btn = QPushButton(t("批量分享卡…", "Batch share cards…"))
        self.share_btn.setCursor(Qt.PointingHandCursor)
        self.share_btn.clicked.connect(self._batch_share)
        head.addWidget(self.share_btn)
        self.export_btn = QPushButton(t("导出…", "Export…"))
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.clicked.connect(self._export_wizard)
        head.addWidget(self.export_btn)
        self.select_btn = QPushButton(t("选择", "Select"))
        self.select_btn.setObjectName("Primary")
        self.select_btn.setCursor(Qt.PointingHandCursor)
        self.select_btn.clicked.connect(self._toggle_select)
        head.addWidget(self.select_btn)
        head.addWidget(make_grid_tier_control(self.lib, self._tier_changed))
        lay.addLayout(head)

        # 评分/选片筛选(1.0冲刺①+⑨): 作用于当前树选择范围(与鸟种胶囊
        # 叠加); 选"全部"即还原
        from PySide6.QtWidgets import QComboBox
        fbar = QHBoxLayout()
        self.rating_filter = QComboBox()
        self.rating_filter.addItems([
            t("评分: 全部", "Rating: all"), t("★1+", "★1+"), t("★2+", "★2+"),
            t("★3+", "★3+"), t("★4+", "★4+"), t("★5", "★5"),
            t("未评星", "Unrated")])
        self.rating_filter.setCursor(Qt.PointingHandCursor)
        self.rating_filter.currentIndexChanged.connect(
            lambda _: self.refresh(force=True))
        fbar.addWidget(self.rating_filter)
        self.pick_filter = QComboBox()
        self.pick_filter.addItems([
            t("选片: 全部", "Pick: all"), t("保留", "Keep"), t("待定", "Pending"),
            t("拒绝", "Reject"), t("未标", "Unmarked")])
        self.pick_filter.setCursor(Qt.PointingHandCursor)
        self.pick_filter.currentIndexChanged.connect(
            lambda _: self.refresh(force=True))
        fbar.addWidget(self.pick_filter)
        fbar.addStretch(1)
        lay.addLayout(fbar)

        # 多选工具条
        self.sel_bar = QFrame()
        self.sel_bar.setObjectName("Card")
        sb = QHBoxLayout(self.sel_bar)
        sb.setContentsMargins(16, 10, 16, 10)
        sb.setSpacing(8)
        self.sel_count = QLabel(t("已选 0 张", "0 selected"))
        self.sel_count.setStyleSheet(
            f"font-size:14px;font-weight:700;color:{theme.BLUE};background:transparent;")
        sb.addWidget(self.sel_count)
        self.all_btn = QPushButton(t("全选", "Select all"))
        self.all_btn.setCursor(Qt.PointingHandCursor)
        self.all_btn.clicked.connect(self._select_all)
        sb.addWidget(self.all_btn)
        self.date_btn = QPushButton(t("按日期…", "By date…"))
        self.date_btn.setCursor(Qt.PointingHandCursor)
        self.date_btn.setToolTip(t("按拍摄日期范围选择照片（可追加到当前选择）",
                                   "Select photos by shooting-date range "
                                   "(optionally adding to the current selection)"))
        self.date_btn.clicked.connect(self._select_by_date)
        sb.addWidget(self.date_btn)
        sb.addStretch(1)
        self.spot_btn = QPushButton(t("设置鸟点…", "Set spot…"))
        self.spot_btn.setCursor(Qt.PointingHandCursor)
        self.spot_btn.setToolTip(t(
            "给选中的照片批量挂载同一个鸟点（可搜索/新建/取消挂载）",
            "Mount the selected photos to one spot "
            "(search / create / unmount)"))
        self.spot_btn.clicked.connect(self._batch_set_spot)
        sb.addWidget(self.spot_btn)
        self.selshare_btn = QPushButton(t("分享卡…", "Share cards…"))
        self.selshare_btn.setCursor(Qt.PointingHandCursor)
        self.selshare_btn.setToolTip(t(
            "按所选照片逐张导出分享卡", "Export one share card per selected photo"))
        self.selshare_btn.clicked.connect(self._batch_share_sel)
        sb.addWidget(self.selshare_btn)
        self.rere_btn = QPushButton(t("重新识别…", "Re-identify…"))
        self.rere_btn.setObjectName("Primary")
        self.rere_btn.setCursor(Qt.PointingHandCursor)
        self.rere_btn.clicked.connect(self._batch_rerecognize)
        sb.addWidget(self.rere_btn)
        # 标记菜单(1.0冲刺①+⑨): 三态+星级, 也可用快捷键 K/P/X/U/0-5
        from PySide6.QtGui import QKeySequence, QShortcut
        from PySide6.QtWidgets import QMenu
        self.mark_btn = QPushButton(t("标记…", "Mark…"))
        self.mark_btn.setCursor(Qt.PointingHandCursor)
        m = QMenu(self.mark_btn)
        m.addAction(t("保留 (K)", "Keep (K)"),
                    lambda: self._mark_apply("keep"))
        m.addAction(t("待定 (P)", "Pending (P)"),
                    lambda: self._mark_apply("pending"))
        m.addAction(t("拒绝 (X)", "Reject (X)"),
                    lambda: self._mark_apply("reject"))
        m.addAction(t("清除标记 (U)", "Clear pick (U)"),
                    lambda: self._mark_apply(""))
        m.addSeparator()
        for n in range(1, 6):
            m.addAction("★" * n, lambda _n=n: self._rate_apply(_n))
        m.addAction(t("清除星级 (0)", "Clear rating (0)"),
                    lambda: self._rate_apply(0))
        self.mark_btn.setMenu(m)
        sb.addWidget(self.mark_btn)
        self.quar_btn = QPushButton(t("隔离区…", "Quarantine…"))
        self.quar_btn.setCursor(Qt.PointingHandCursor)
        self.quar_btn.setToolTip(t(
            "把选中的照片移入库目录下的隔离区（可预览清单后确认，随时恢复，"
            "绝不覆盖同名文件，不提供永久删除）",
            "Move selected photos into the library quarantine folder "
            "(preview first, restore anytime; never overwrites existing "
            "files, no permanent delete)"))
        self.quar_btn.clicked.connect(self._open_quarantine)
        sb.addWidget(self.quar_btn)
        self.rm_btn = QPushButton(t("从鸟迹移除…", "Remove from BirdTrace…"))
        self.rm_btn.setStyleSheet(
            "QPushButton{color:#FF3B30;background:transparent;"
            "border:1px solid #FF3B30;border-radius:10px;}"
            "QPushButton:disabled{color:#FF9F9A;border-color:#FFB3AE;}")
        self.rm_btn.setCursor(Qt.PointingHandCursor)
        self.rm_btn.clicked.connect(self._batch_remove)
        sb.addWidget(self.rm_btn)
        done_btn = QPushButton(t("完成", "Done"))
        done_btn.setCursor(Qt.PointingHandCursor)
        done_btn.clicked.connect(self._toggle_select)
        sb.addWidget(done_btn)
        self.sel_bar.setVisible(False)
        lay.addWidget(self.sel_bar)

        # 鸟种胶囊行(0.8.6用户: 按选中月/日显示鸟种, 点击筛选):
        # 默认隐藏, 点了时间树节点才出现; FlowLayout自动换行
        from ..theme.widgets import FlowLayout
        self.chips_card = QFrame()
        self.chips_card.setObjectName("Card")
        self.chips_lay = FlowLayout(self.chips_card, spacing=8)
        self.chips_lay.setContentsMargins(16, 10, 16, 10)
        self.chips_card.setVisible(False)
        lay.addWidget(self.chips_card)

        # 主体: 左侧时间树(年→月→日, 点击跳转) + 右侧照片流
        # (2026-10-31用户要求: 只按月份上下翻不方便)
        body = QHBoxLayout()
        body.setSpacing(12)
        self.tree_nav = QTreeWidget()
        self.tree_nav.setHeaderHidden(True)
        self.tree_nav.setFixedWidth(196)
        self.tree_nav.setIndentation(16)
        self.tree_nav.setStyleSheet(
            f"QTreeWidget{{background:{theme.CARD};border:1px solid {theme.SEP};"
            "border-radius:12px;padding:4px;}"
            "QTreeWidget::item{height:26px;border-radius:7px;margin:1px 2px;}"
            "QTreeWidget::item:hover{background:rgba(127,127,127,40);}"
            "QTreeWidget::item:selected{background:rgba(0,122,255,60);}")
        self.tree_nav.itemClicked.connect(self._on_tree_click)
        body.addWidget(self.tree_nav)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.content_lay = QVBoxLayout(self.content)
        self.content_lay.setContentsMargins(0, 0, 16, 24)
        self.content_lay.setSpacing(10)
        self.scroll.setWidget(self.content)
        body.addWidget(self.scroll, 1)
        lay.addLayout(body, 1)

        # 滚动时联动高亮树节点(节流)
        self._nav_sync = QTimer(self)
        self._nav_sync.setSingleShot(True)
        self._nav_sync.setInterval(160)
        self._nav_sync.timeout.connect(self._sync_tree_current)
        self.scroll.verticalScrollBar().valueChanged.connect(
            lambda _v: self._nav_sync.start())


    def _batch_share(self):
        """批量分享卡导出(0.8-⑥): 日期范围+可选鸟种 → 每鸟种一张最美。
        0.8.6: 默认日期=时间线当前选中节点(年/月/日), 没点过=今天。"""
        from .batch_share_dialog import BatchShareDialog
        BatchShareDialog(self.lib, self.win,
                         preset=self._sel_date_range()).exec()

    def _sel_date_range(self):
        """当前树点击节点→(d1,d2); 未点/杂项节点→None(回落今天)。"""
        key = self._chips_key
        if not key:
            return None
        if "|" in key:                 # 日
            d = "-".join(key.split("|", 1))
            return (d, d)
        if len(key) == 7 and key[4] == "-":   # 月
            import calendar
            y, m = key.split("-")
            return (f"{key}-01",
                    f"{key}-{calendar.monthrange(int(y), int(m))[1]:02d}")
        if len(key) == 4 and key.isdigit():   # 年
            return (f"{key}-01-01", f"{key}-12-31")
        return None

    def _export_wizard(self):
        """导出向导(0.8-④): 复制到新位置 / 原地重命名。"""
        from .export_dialog import ExportDialog
        ExportDialog(self.lib, self.win).exec()

    # ---------- 多选模式 ----------
    def _toggle_select(self):
        self._select_mode = not self._select_mode
        if not self._select_mode:
            self._selected.clear()
            self._anchor_id = None
        self.sel_bar.setVisible(self._select_mode)
        self.select_btn.setText(t("选择", "Select") if not self._select_mode
                                else t("选择中…", "Selecting…"))
        self.refresh()

    def _select_all(self):
        ids = [r["id"] for r in self.lib.conn.execute(
            "SELECT id FROM photos ORDER BY id")]
        if len(self._selected) >= len(ids):
            self._selected.clear()
        else:
            self._selected = set(ids)
        self._anchor_id = None
        # 数据签名没变, refresh会跳过重建——选中态必须就地更新到网格项
        # (曾靠refresh重绘, 签名跳过后全选点了没反应)
        for pid, it in self._grid_items.items():
            try:
                it.set_selected(pid in self._selected)
            except RuntimeError:
                pass   # 僵尸控件(重建间隙)忽略
        self._sync_sel_ui()

    def _sync_sel_ui(self):
        n = len(self._selected)
        self.sel_count.setText(t(f"已选 {n} 张", f"{n} selected"))
        self.spot_btn.setEnabled(n > 0)
        self.selshare_btn.setEnabled(n > 0)
        self.rm_btn.setEnabled(n > 0)
        self.rere_btn.setEnabled(n > 0)
        self.all_btn.setText(t("全不选", "Deselect all") if n >= self.lib.photo_count()
                             else t("全选", "Select all"))

    def _on_item_click(self, pid: int, item=None, group_ids=None, ev=None):
        # 0.8.6连拍修错: 封面右键=组级菜单(整组改鸟种/整组重新识别);
        # 非连拍单张不弹(改判走多选工具条, 保持原路径)
        if ev is not None and getattr(ev, "button", None) is not None                 and ev.button() == Qt.RightButton:
            from .burst_actions import make_group_menu
            try:
                make_group_menu(self.lib, self.win, pid, self,
                                ev.globalPos())
            except RuntimeError:
                pass
            return
        if self._select_mode:
                # Shift+click: 以上次点击为锚点, 按显示顺序选中头尾之间全部
            # (2026-11-03用户要求); 锚点无效时退化为普通点击。
            if (QApplication.keyboardModifiers() & Qt.ShiftModifier) \
                    and self._anchor_id in self._order_ids \
                    and pid in self._order_ids:
                self._select_range(self._anchor_id, pid)
                return
            # 就地翻转选中态, 不重建网格(重建会让快速连点落在已删除控件上)
            if pid in self._selected:
                self._selected.discard(pid)
            else:
                self._selected.add(pid)
            self._anchor_id = pid
            if item is not None:
                item.set_selected(pid in self._selected)
            self._sync_sel_ui()
        else:
            if group_ids:
                # 连拍封面: 在组内左右翻看(0.8-③"展开看全组")
                self._open(pid, list(group_ids))
                return
            ids = [r["id"] for r in self.lib.conn.execute(
                "SELECT id FROM photos ORDER BY id")]
            self._open(pid, ids)

    def _select_range(self, anchor: int, target: int):
        """选中显示顺序上 anchor..target 之间(含两端)的全部照片。"""
        if anchor not in self._order_ids or target not in self._order_ids:
            return
        i1 = self._order_ids.index(anchor)
        i2 = self._order_ids.index(target)
        lo, hi = (i1, i2) if i1 <= i2 else (i2, i1)
        for _pid in self._order_ids[lo:hi + 1]:
            self._selected.add(_pid)
            it = self._grid_items.get(_pid)
            if it is not None:
                try:
                    it.set_selected(True)
                except RuntimeError:
                    pass       # 僵尸控件(重建间隙)忽略
        self._sync_sel_ui()

    @staticmethod
    def _iso_date(taken_at) -> str:
        """拍摄时间 → "YYYY-MM-DD"(兼容EXIF冒号与ISO格式); 无效返回""。"""
        s = (taken_at or "")[:10]
        if len(s) >= 10 and s[4] in ":-":
            return s.replace(":", "-")
        return ""

    def _select_by_date(self):
        """按拍摄日期范围选择(可追加)。日期上下限取自当前库内照片。"""
        from PySide6.QtCore import QDate

        dates = sorted(d for d in self._iso_dates.values() if d)
        if not dates:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(t("按日期选择", "Select by date"))
        form = QFormLayout(dlg)
        lo = QDate.fromString(dates[0], "yyyy-MM-dd")
        hi = QDate.fromString(dates[-1], "yyyy-MM-dd")
        # ThemedDateEdit: 弹层年份/月份下拉一点直达+主题配色
        # (QDateEdit原生日历导航栏深色主题下配色不跟随, 用户2026-11-05)
        ed_from = ThemedDateEdit(hi)
        ed_to = ThemedDateEdit(hi)
        for ed in (ed_from, ed_to):
            ed.setDateRange(lo, hi)
        form.addRow(t("从", "From"), ed_from)
        form.addRow(t("到", "To"), ed_to)
        chk = QCheckBox(t("追加到当前选择", "Add to current selection"))
        form.addRow(chk)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        d1 = ed_from.date().toString("yyyy-MM-dd")
        d2 = ed_to.date().toString("yyyy-MM-dd")
        if d1 > d2:
            d1, d2 = d2, d1
        self._select_date_range(d1, d2, append=chk.isChecked())

    def _select_date_range(self, d1: str, d2: str, append: bool = False):
        """选中拍摄日期在 [d1,d2] 的照片(字符串ISO日期可直接比较)。"""
        ids = [pid for pid, d in self._iso_dates.items()
               if d and d1 <= d <= d2]
        if not append:
            self._selected.clear()
            for it in self._grid_items.values():
                try:
                    it.set_selected(False)
                except RuntimeError:
                    pass
        for pid in ids:
            self._selected.add(pid)
            it = self._grid_items.get(pid)
            if it is not None:
                try:
                    it.set_selected(True)
                except RuntimeError:
                    pass
        self._anchor_id = None
        self._sync_sel_ui()
        if not ids:
            QApplication.beep()

    def _batch_share_sel(self):
        ids = sorted(self._selected)
        if not ids:
            return
        from .batch_share_dialog import BatchShareDialog
        dlg = BatchShareDialog(self.lib, self.win, photo_ids=ids)
        dlg.exec()

    # ---------- 标记/隔离(1.0冲刺①+⑨culling) ----------
    # 快捷键只在多选模式且有选中时生效(单张打星走查看器); 就地更新
    # 网格角标避免整页重建(多选模式网格必全展开, _grid_items全覆盖)

    def _mark_apply(self, pick: str):
        if not self._select_mode or not self._selected or not self.isVisible():
            return
        self.lib.set_pick(sorted(self._selected), pick)
        self._after_mark(pick=pick)

    def _rate_apply(self, n: int):
        if not self._select_mode or not self._selected or not self.isVisible():
            return
        self.lib.set_rating(sorted(self._selected), n)
        self._after_mark(stars=n)

    def _after_mark(self, pick: str | None = None, stars: int | None = None):
        """就地刷新选中项角标; 筛选激活时(标记可能让项移出筛选)整页刷。"""
        if (self.rating_filter.currentIndex() or
                self.pick_filter.currentIndex()):
            self.refresh(force=True)
            return
        for pid in self._selected:
            it = self._grid_items.get(pid)
            if it is None:
                continue
            try:
                if stars is not None:
                    it.stars = stars
                if pick is not None:
                    it.pick = pick
                it.update()
            except RuntimeError:
                pass

    def _open_quarantine(self):
        ids = sorted(self._selected)
        from .quarantine_dialog import QuarantineDialog
        dlg = QuarantineDialog(self.lib, self.win, selected=ids)
        dlg.exec()
        if dlg.moved:
            self.refresh(force=True)

    def _batch_set_spot(self):
        ids = sorted(self._selected)
        if not ids:
            return
        from .spot_dialog import BatchSpotDialog
        dlg = BatchSpotDialog(self.lib, self.win, ids)
        dlg.exec()
        if dlg.applied:
            # 挂载/取消不改数据签名, refresh会跳过——但查看器/鸟点页的
            # 信息靠库重查, 发信号让各页跟上即可; 时间线网格不显示鸟点
            self.win.library_changed.emit()

    # ---------- 鸟种胶囊(0.8.6: 范围=树点击节点, 点击筛选) ----------
    def _scope_rows(self) -> list:
        """当前树点击范围内的照片行(年/月/日); 未点过返回[]。"""
        key = self._chips_key
        if not key:
            return []
        if "|" in key:                 # 日 "YYYY-MM|DD"
            day = "-".join(key.split("|", 1))
            return [p for v in self._raw.values() for p in v
                    if self._iso_date(p.get("taken_at")) == day]
        return [p for ym, v in self._raw.items() if ym.startswith(key)
                for p in v]

    def _rebuild_chips(self):
        """重建胶囊行: 范围内鸟种(数量降序)+全部; 无范围且未筛选=隐藏。"""
        rows = self._scope_rows()
        if not rows and not self._tl_sp:
            self.chips_card.setVisible(False)
            return
        while self.chips_lay.count():
            it = self.chips_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

        def _chip(text, code):
            sel = (self._tl_sp == code)
            c = QLabel(text)
            c.setStyleSheet(
                "font-size:13px;padding:4px 14px;border-radius:14px;"
                + (f"background:{theme.BLUE};color:white;" if sel else
                   f"background:{theme.FILL};color:{theme.LABEL};"))
            c.setCursor(Qt.PointingHandCursor)
            c.mousePressEvent = lambda e, cd=code: self._pick_species(cd)
            self.chips_lay.addWidget(c)

        names: dict[str, str] = {}
        for v in self._raw.values():
            for p in v:
                mc = p.get("main_code")
                if mc and mc not in names:
                    names[mc] = sname(p.get("sp_cn") or "", p.get("sp_en") or "")
        agg: dict[str, int] = {}
        for p in rows:
            mc = p.get("main_code")
            if mc:
                agg[mc] = agg.get(mc, 0) + 1
        _chip(t(f"全部 {len(rows)}", f"All {len(rows)}"), None)
        for code, n in sorted(agg.items(), key=lambda kv: (-kv[1], kv[0])):
            _chip(f"{names.get(code, code)} ×{n}", code)
        self.chips_lay.addStretch(1)
        tip = QLabel(t("点鸟种只看该种；再点一次恢复全部",
                       "Click a species to filter; click again for all"))
        tip.setStyleSheet(f"font-size:12px;color:{theme.LABEL_3};"
                          "background:transparent;")
        tip.setWordWrap(True)
        self.chips_lay.addWidget(tip)
        self.chips_card.setVisible(True)

    def _pick_species(self, code):
        """胶囊点击: 筛选/取消该鸟种(整库范围, 与连拍折叠叠加)。"""
        self._tl_sp = None if self._tl_sp == code else code
        self.refresh(force=True)

    def _caption(self, ph: dict) -> str:
        """缩略图说明=鸟种+鸟点(0.8.6用户, 鸟点详情是时间+鸟种的对偶)。"""
        parts = []
        if ph.get("main_code"):
            sp = sname(ph.get("sp_cn") or "", ph.get("sp_en") or "")
            if sp:
                parts.append(sp)
        spot = ph.get("spot_short") or ph.get("spot_name") or ""
        if spot:
            parts.append(spot)
        return " · ".join(parts)

    def _batch_remove(self):
        ids = sorted(self._selected)
        if not ids:
            return
        r = QMessageBox.question(
            self, t("批量从鸟迹移除", "Batch remove from BirdTrace"),
            t(f"从鸟迹移除选中的 {len(ids)} 张照片？\n\n"
              "原始照片文件不会被移动或删除，只是鸟迹不再记录它们"
              "（识别记录、鸟点挂载一并移除）。",
              f"Remove the {len(ids)} selected photos from BirdTrace?\n\n"
              "The original photo files will not be moved or deleted; "
              "BirdTrace simply stops tracking them (recognition records "
              "and hotspot links are removed too)."),
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        for pid in ids:
            self.lib.remove_photo(pid)
        self._selected.clear()
        self.win.library_changed.emit()
        self.refresh()

    def _batch_rerecognize(self):
        ids = sorted(self._selected)
        if not ids:
            return
        # 先检测原文件存在性: 全部丢失时不空跑, 直接给补救指引
        q = ",".join("?" * len(ids))
        rows = self.lib.conn.execute(
            f"SELECT id, path FROM photos WHERE id IN ({q})", ids).fetchall()
        from ..core.offline import classify_paths, drive_label
        cls = classify_paths((r["id"], r["path"]) for r in rows)
        if cls["offline"] and not cls["ok"] and not cls["missing"]:
            # 全部在离线卷上: 不是丢失, 插回硬盘即可(0.8-②)
            drives = "、".join(drive_label(d) for d in cls["offline"])
            QMessageBox.information(
                self, t("原图离线", "Originals offline"),
                t(f"选中的 {len(ids)} 张原图都在未接入的硬盘上（{drives}）。\n"
                  "插回硬盘后再「重新识别」即可，记录与标注不受影响。",
                  f"All {len(ids)} selected originals are on a disconnected "
                  f"drive ({drives}).\nReconnect it and re-identify; records "
                  "and labels are unaffected."))
            return
        missing = [r["path"] for r in rows if r["id"] in cls["missing"]
                   or any(r["id"] in v for v in cls["offline"].values())]
        if missing and len(missing) == len(ids):
            QMessageBox.question(
                self, t("原文件不在这台电脑上",
                        "Original files not on this computer"),
                t(f"选中的 {len(ids)} 张照片的原文件都找不到——引用模式记录的路径"
                  "属于另一台电脑，或文件已被移动/删除。\n\n"
                  f"例如：{missing[0]}\n\n"
                  "处理办法（任选）：\n"
                  "· 把原照片放回上述路径，再点「重新识别」\n"
                  "· 用「从鸟迹移除」清掉这些空记录（清空后编号会归零）\n"
                  "· 重新用「复制/移动到新位置」方式导入一次",
                  f"The original files for all {len(ids)} selected photos are "
                  "missing — the paths recorded in reference mode belong to "
                  "another computer, or the files were moved or deleted.\n\n"
                  f"For example: {missing[0]}\n\n"
                  "Options (pick one):\n"
                  "· Put the original photos back at the path above, then "
                  "click \"Re-identify\"\n"
                  "· Use \"Remove from BirdTrace\" to clear these empty records "
                  "(once cleared, numbering restarts from zero)\n"
                  "· Re-import them once with the \"Copy/move to a new "
                  "location\" option"))
            return
        if missing:
            r = QMessageBox.question(
                self, t("部分原文件缺失", "Some original files missing"),
                t(f"选中的 {len(ids)} 张里有 {len(missing)} 张原文件找不到，"
                  "这些会识别失败，其余正常识别。继续吗？",
                  f"{len(missing)} of the {len(ids)} selected photos have "
                  "missing original files; those will fail to identify, and "
                  "the rest will be identified normally. Continue?"),
                QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        r = QMessageBox.question(
            self, t("批量重新识别", "Batch re-identify"),
            t(f"对选中的 {len(ids)} 张照片重新识别？\n\n"
              "下一步可选识别范围：增量模式只跑未识别/待复核/低置信，"
              "人工确认过的完全不动；全量模式会覆盖包括人工确认在内的"
              "全部识别结果，按照片导入时的地区重新识别。",
              f"Re-identify the {len(ids)} selected photos?\n\n"
              "Scope is chosen next: incremental runs only unidentified/"
              "pending/low-confidence photos and never touches manually "
              "confirmed ones; full re-run overwrites all results including "
              "manual confirmations, using each photo's import region."),
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        # 地区/鸟点可选调整(2026-11-04用户: 导入时可能选错地区和鸟点)
        from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout,
                                       QHBoxLayout, QPushButton)
        dlg = QDialog(self)
        dlg.setWindowTitle(t("识别地区与鸟点", "Region & spot"))
        form = QFormLayout(dlg)
        # 识别范围(1.0冲刺②): 默认增量=不动人工确认(安全默认);
        # 全量=旧行为(覆盖人工确认, 确认框已警告)
        scope_combo = QComboBox()
        scope_combo.addItem(t("增量：只跑未识别/待复核/低置信",
                              "Incremental: unidentified/pending/low conf only"),
                            "pending")
        scope_combo.addItem(t("全量：覆盖全部（含人工确认）",
                              "Full: overwrite all (incl. manual)"), "all")
        form.addRow(t("识别范围", "Scope"), scope_combo)
        regions_mod = __import__("app.core.regions", fromlist=["regions"])
        reg_combo = QComboBox()
        q2 = ",".join("?" * len(ids))
        # 参数必须传: 此前execute()漏了ids→ProgrammingError槽静默崩溃,
        # 用户看到"确认后没有任何反应"(0.8.0-test2复查)
        batch_regions = [r["region_id"] for r in self.lib.conn.execute(
            f"SELECT DISTINCT b.region_id AS region_id FROM batches b "
            f"JOIN photos p ON p.batch_id=b.id WHERE p.id IN ({q2})", ids)
            if r["region_id"]]
        cur = batch_regions[0] if len(set(batch_regions)) == 1 else None
        reg_combo.addItem(t("保持不变", "Keep unchanged"), None)
        tree = regions_mod.build_tree()["countries"]
        for cnode in tree:
            # data必须是地区id: 此前国家级传None与「保持不变」同值,
            # 选国家后if new_region不成立→地区静默不变(0.8.0-test2复查)
            reg_combo.addItem(cnode["name"], cnode["id"])
            for snode in cnode.get("subs") or []:
                reg_combo.addItem("    " + snode["name"], snode["id"])
        if cur:
            idx = reg_combo.findData(cur)
            if idx >= 0:
                reg_combo.setCurrentIndex(idx)
        spot_combo = QComboBox()
        spot_combo.addItem(t("保持不变", "Keep unchanged"), "keep")
        spot_combo.addItem(t("不挂鸟点", "No spot"), None)
        for sp in self.lib.spots_overview():
            spot_combo.addItem(sp["name"], sp["id"])
        form.addRow(t("识别地区", "Region"), reg_combo)
        form.addRow(t("鸟点", "Spot"), spot_combo)
        bb = QHBoxLayout()
        bb.addStretch(1)
        ok = QPushButton(t("开始识别", "Start"))
        ok.setObjectName("Primary")
        ok.clicked.connect(dlg.accept)
        cancel = QPushButton(t("取消", "Cancel"))
        cancel.clicked.connect(dlg.reject)
        bb.addWidget(cancel)
        bb.addWidget(ok)
        form.addRow(bb)
        if not dlg.exec():
            return
        new_region = reg_combo.currentData()
        spot_choice = spot_combo.currentData()
        if new_region:
            self.lib.conn.execute(
                f"UPDATE batches SET region_id=? WHERE id IN ("
                f"SELECT DISTINCT batch_id FROM photos WHERE id IN ({q}))",
                [new_region] + ids)
            self.lib.conn.commit()
        if spot_choice != "keep":
            self.lib.set_photos_spot(ids, spot_choice)
        scope = scope_combo.currentData() or "pending"
        reset_ids = self.lib.reset_recognition(ids, scope=scope)
        if scope == "pending" and len(reset_ids) < len(ids):
            QMessageBox.information(
                self, t("增量重识别", "Incremental re-identify"),
                t(f"{len(ids)} 张中 {len(reset_ids)} 张进入识别队列——"
                  "其余有人工确认痕迹，已跳过（识别永不覆盖人工结果）。",
                  f"{len(reset_ids)} of {len(ids)} queued — the rest have "
                  "manual confirmations and were skipped."))
        self._selected.clear()
        self.win.library_changed.emit()
        self.refresh()
        if reset_ids:
            self.win.start_recognition()

    # ---------- 列表 ----------
    def _data_sig(self):
        """库内容廉价签名: 无变化的切页回来不重建(秒开, 位置天然保持)。
        日期入签名: 每日一鸟横幅跨天要更新。路径总长: 换电脑改路径。"""
        import datetime
        c = self.lib.conn
        p = c.execute("SELECT COUNT(*), IFNULL(SUM(LENGTH(path)),0) "
                      "FROM photos").fetchone()
        r = c.execute("SELECT COUNT(*), IFNULL(MAX(id),0), "
                      "CAST(IFNULL(SUM(CAST(confidence*1000 AS INT)),0) AS INT) "
                      "FROM records").fetchone()
        g = c.execute("SELECT COUNT(DISTINCT group_id) FROM photos "
                      "WHERE group_id IS NOT NULL").fetchone()[0]
        return (p[0], p[1], r[0], r[1], r[2], datetime.date.today(),
                g, self._collapse_on())

    def _collapse_on(self) -> bool:
        """连拍折叠生效: 开关开 且 不在多选模式(多选必须看到每一张)。"""
        return self.burst_btn.isChecked() and not self._select_mode

    def _toggle_collapse(self, on: bool):
        self.lib.set_setting("burst_collapse", "1" if on else "0")
        self.refresh(force=True)

    def _tier_changed(self):
        """网格档位切换(0.8.5实测修): 重读档位+force重建——
        self._tile构造时只读一次会stale, 且数据签名优化会吞掉无变化刷新。"""
        self._tile = grid_tile_of(self.lib)
        self.refresh(force=True)

    def refresh(self, force: bool = False):
        if not force and self._tl_sig == self._data_sig():
            return
        # 重建前记住位置: 识别完成/库变化刷新时用户可能正浏览, 不跳顶
        self._keep_scroll = self.scroll.verticalScrollBar().value()
        self._grid_items = {}
        self._ym_head = {}       # "YYYY-MM"→月份标题QLabel(时间树锚点)
        self._day_item = {}      # "YYYY-MM|DD"→当日首个网格项(时间树锚点)
        self._order_ids = []     # 显示顺序(Shift范围选择/日期选择用)
        self._iso_dates = {}     # photo_id→YYYY-MM-DD
        self._anchor_id = None
        while self.content_lay.count():
            item = self.content_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        raw = self.lib.timeline()
        self._raw = raw             # 未过滤数据(鸟种胶囊范围统计用)
        if self._tl_sp:            # 鸟种筛选(0.8.6胶囊): 只动视图
            raw = {ym: [p for p in v if p.get("main_code") == self._tl_sp]
                   for ym, v in raw.items()}
            raw = {ym: v for ym, v in raw.items() if v}
        # 评分/选片筛选(1.0冲刺①+⑨): 只动视图, 与鸟种胶囊叠加
        ri = self.rating_filter.currentIndex() if hasattr(self, "rating_filter") else 0
        pi = self.pick_filter.currentIndex() if hasattr(self, "pick_filter") else 0
        if ri:
            if ri == 6:        # 未评星
                raw = {ym: [p for p in v if not (p.get("rating") or 0)]
                       for ym, v in raw.items()}
            else:              # ★ri+
                raw = {ym: [p for p in v if (p.get("rating") or 0) >= ri]
                       for ym, v in raw.items()}
            raw = {ym: v for ym, v in raw.items() if v}
        if pi:
            want = ("", "keep", "pending", "reject", "")[pi]
            if pi == 4:        # 未标
                raw = {ym: [p for p in v if not (p.get("pick") or "")]
                       for ym, v in raw.items()}
            else:
                raw = {ym: [p for p in v if (p.get("pick") or "") == want]
                       for ym, v in raw.items()}
            raw = {ym: v for ym, v in raw.items() if v}
        counts = {ym: len(v) for ym, v in raw.items()}
        if self._collapse_on():
            from ..core.burst import collapse_bursts
            data = {ym: collapse_bursts(v) for ym, v in raw.items()}
        else:
            data = raw
        lifer_ids = self.lib.lifer_photo_ids()
        import datetime
        year_ids = self.lib.year_bird_photo_ids(datetime.date.today().strftime('%Y'))
        total = sum(counts.values())
        self.title.setText(t(f"时间线 · {total} 张照片", f"Timeline · {total} photos"))
        self._sync_sel_ui()
        # 原图可用性(0.8-②): 离线卷(移动硬盘没插)与真丢失分开——离线不是
        # 丢失, 缩略图/标注/统计照常, 插回即恢复, 不引导"重新链接"。
        try:
            fs = self.lib.file_status()
        except Exception:
            fs = {"offline": {}, "missing": [], "n_offline": 0}
        self._offline_ids = {i for ids in fs["offline"].values() for i in ids}
        self._missing_ids = set(fs["missing"])
        if fs["n_offline"]:
            from ..core.offline import drive_label
            drives = "、".join(drive_label(d) for d in fs["offline"])
            ob = QFrame()
            ob.setObjectName("Card")
            oh = QHBoxLayout(ob)
            oh.setContentsMargins(14, 10, 14, 10)
            ot = QLabel(t(f"📴 {fs['n_offline']} 张原图离线（{drives} 未接入）"
                          "——缩略图、标注、统计照常可用；插回硬盘后自动恢复，"
                          "只有查看大图/重新识别/分享卡需要原图。",
                          f"📴 {fs['n_offline']} originals offline ({drives} "
                          "not connected) — thumbnails, labels and stats still "
                          "work; reconnect the drive to restore. Only full-size "
                          "view / re-identify / share cards need the originals."))
            ot.setWordWrap(True)
            ot.setStyleSheet(f"font-size:13px;color:{theme.LABEL_2};"
                             "background:transparent;")
            oh.addWidget(ot, 1)
            self.content_lay.addWidget(ob)
        if fs["missing"]:
            mb = QFrame()
            mb.setObjectName("Card")
            mh = QHBoxLayout(mb)
            mh.setContentsMargins(14, 10, 14, 10)
            mt = QLabel(t(f"⚠️ {len(fs['missing'])} 张照片的原文件不在原位置"
                          "（被移动/改名/删除，或引用模式记录的是另一台电脑的路径）。",
                          f"⚠️ The original files for {len(fs['missing'])} photos "
                          "are not at their recorded location (moved, renamed, "
                          "deleted, or the paths belong to another computer)."))
            mt.setWordWrap(True)
            mt.setStyleSheet(f"font-size:13px;color:{theme.ORANGE};"
                             "background:transparent;")
            mh.addWidget(mt, 1)
            rb = QPushButton(t("重新链接…", "Relink…"))
            rb.setCursor(Qt.PointingHandCursor)
            rb.clicked.connect(self._relink)
            mh.addWidget(rb)
            self.content_lay.addWidget(mb)
        banner = self._daily_bird_banner()
        if banner:
            self.content_lay.addWidget(banner)
        if not data:
            # 每次新建: 持久QLabel会被refresh的deleteLater删除, 复用会崩
            empty = QLabel(t("还没有照片 · 去「导入」页添加你的第一张鸟类照片吧",
                             "No photos yet · Add your first bird photo on the "
                             "\"Import\" page"))
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"color:{theme.LABEL_2};font-size:15px;padding:60px;")
            self.content_lay.addWidget(empty)
            self._keep_scroll = 0
            self._tl_sig = self._data_sig()
            self._grid_items = {}
            # 全选删除后照片为空: 必须重建树, 否则年月日与张数留在旧状态
            # (2026-11-03用户实测"得重启才刷新")。此前直接return跳过了
            # 函数末尾的_build_tree。
            self._build_tree({})
            self._rebuild_chips()
            return
        import collections
        for ym, photos in data.items():
            year, month = (ym.split("-") + [""])[:2]
            n_ym = counts.get(ym, len(photos))
            head_txt = (t(f"{year}年{int(month)}月 · {n_ym} 张",
                          f"{year}-{int(month):02d} · {n_ym} photos")
                        if month else ym)
            # day级别: 只渲染聚焦日期所在月, 且月内按日再分小节
            day_mode = getattr(self, "_group_level", "month") == "day"
            if day_mode:
                focus = getattr(self, "_group_day", None)
                ym_of_focus = (focus or "")[:7]
                if focus and ym != ym_of_focus:
                    continue
                by_day = collections.OrderedDict()
                for ph in photos:
                    iso = self._iso_date(ph.get("taken_at")) or ""
                    by_day.setdefault(iso or "?", []).append(ph)
                if focus:
                    by_day = collections.OrderedDict(
                        (d, v) for d, v in by_day.items() if d == focus)
                for d, v in by_day.items():
                    self._render_month_block(ym, v, counts, lifer_ids,
                                             year_ids, day_label=d)
                continue
            self._render_month_block(ym, photos, counts, lifer_ids,
                                     year_ids, head_txt=head_txt)

        self.content_lay.addStretch(1)
        self._build_tree(raw)
        self._rebuild_chips()
        self._restore_scroll_after_rebuild()
        self._tl_sig = self._data_sig()
        self._cur_cols = self._wanted_cols()
        # 初次打开时页面尚未布局, 列数按陈旧宽度算(曾固定4列)——布局
        # 稳定后再校正一次(列数没变则直接返回, 无开销)
        QTimer.singleShot(0, self._on_relayout)

    def _render_month_block(self, ym: str, photos: list, counts: dict,
                            lifer_ids: set, year_ids: set,
                            day_label: str | None = None,
                            head_txt: str | None = None):
        """渲染一个月的标题+网格; day_label给定→插日小标题(按日分组)。"""
        year, month = (ym.split("-") + [""])[:2]
        n_ym = counts.get(ym, len(photos))
        if head_txt is None:
            head_txt = (t(f"{year}年{int(month)}月 · {n_ym} 张",
                          f"{year}-{int(month):02d} · {n_ym} photos")
                        if month else ym)
        head = QLabel(head_txt)
        head.setStyleSheet(f"font-size:17px;font-weight:700;color:{theme.LABEL_2};"
                           "background:transparent;padding:8px 2px 2px 2px;")
        self.content_lay.addWidget(head)
        self._ym_head[ym] = head   # 时间树跳转锚点
        if day_label:
            n_d = len(photos)
            dl = QLabel(t(f"{int(day_label[8:10])}日 · {n_d} 张",
                          f"Day {int(day_label[8:10])} · {n_d} photos"))
            dl.setStyleSheet(f"font-size:14px;font-weight:600;color:{theme.LABEL_3};"
                             "background:transparent;padding:2px 2px 0 2px;")
            self.content_lay.addWidget(dl)

        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 12)
        grid.setSpacing(10)
        cols = self._wanted_cols()
        for i, ph in enumerate(photos):
            if ph["id"] in lifer_ids:
                corner = t("首见", "First sighting")
            elif ph["id"] in year_ids:
                corner = t("年鸟", "Year bird")
            else:
                corner = None
            thumb = self._thumb(ph)
            if ph["id"] in self._offline_ids:
                corner = t("原图离线", "Offline")       # 卷未接入, 插回即恢复
            elif ph["id"] in self._missing_ids:
                corner = t("文件丢失", "File missing")   # 不在原位置
            # 0.8.6用户: 缩略图下显示鸟种+鸟点(与鸟点详情的时间+鸟种对偶)
            # 1.0冲刺①+⑨: 人工星级(左上★)+选片三态(左下色点/拒绝红框)
            item = PhotoGridItem(thumb, label=self._caption(ph),
                                 corner=corner,
                                 stack=ph.get("group_n", 0), tile=self._tile,
                                 stars=ph.get("rating", 0),
                                 pick=ph.get("pick", ""))
            item.setCursor(Qt.PointingHandCursor)
            item.set_selected(ph["id"] in self._selected)
            def _click(_e, _pid=ph["id"], _it=item,
                       _gids=ph.get("group_ids")):
                # 防御: 网格重建后残留的僵尸控件点击直接忽略
                try:
                    self._on_item_click(_pid, _it, _gids, _e)
                except RuntimeError:
                    pass
            item.mousePressEvent = _click
            self._grid_items[ph["id"]] = item
            self._order_ids.append(ph["id"])
            iso = self._iso_date(ph.get("taken_at"))
            if iso:
                self._iso_dates[ph["id"]] = iso
            day = self._day_key(ph.get("taken_at"))
            if day:
                dk = f"{ym}|{day}"
                if dk not in self._day_item:   # 当日首个网格项=跳转锚点
                    self._day_item[dk] = item
            grid.addWidget(item, i // cols, i % cols)
        grid.setColumnStretch(cols, 1)
        self.content_lay.addWidget(grid_widget)

    def _wanted_cols(self) -> int:
        """当前布局下时间线应有的列数(用视口实际宽度——初次打开时
        self.width()还是构造默认值, 曾导致初始固定4列)。

        每列实占 = 格子(THUMB+12) + 列间距10, 首列左缘为0、末列后还有
        content右边距16: 放满条件 150·cols ≤ w−6。曾按140/列预算
        (w-80)//140——视口宽于~1100px时稳定溢出数px~数十px出横向
        滚动条(用户实测最大化也放不下所有列, 2026-11-02)。下限2列:
        加树后窄窗口视口仅400+px, 4列下限本身就会溢出。"""
        w = self.scroll.viewport().width() or self.width()
        return max(2, (w - 8) // (self._tile + 10))

    # ---------- 时间树(年→月→日导航) ----------
    @staticmethod
    def _day_key(taken_at) -> str:
        """taken_at("YYYY:MM:DD…"EXIF或"YYYY-MM-DD…"ISO)→"DD"日号。"""
        s = (taken_at or "")[:10]
        if len(s) >= 10 and s[4] in ":-":
            return s[8:10]
        return ""

    def _build_tree(self, data: dict) -> None:
        """重建左侧时间树。锚点: 月=月份标题QLabel, 日=当日首个网格项;
        点击itemClicked跳转, 滚动反向高亮(_sync_tree_current)。"""
        keep = self.tree_nav.currentItem()
        try:
            keep_key = keep.data(0, Qt.UserRole) if keep else None
        except RuntimeError:      # 上一次refresh的旧item已删(离屏压力下偶发)
            keep_key = None
        self.tree_nav.blockSignals(True)
        self.tree_nav.setCurrentItem(None)   # 清空内部current指针再clear
        self.tree_nav.clear()
        import datetime
        today = datetime.date.today()
        cur_year = None
        for ym, photos in data.items():
            parts = ym.split("-")
            if len(parts) != 2:                    # "未知时间"等杂项
                y_item = QTreeWidgetItem([f"{ym} · {len(photos)}"])
                y_item.setData(0, Qt.UserRole, ym)
                self.tree_nav.addTopLevelItem(y_item)
                continue
            year, month = parts[0], parts[1]
            if year != cur_year:
                cur_year = year
                n_year = sum(len(v) for k, v in data.items()
                             if k.startswith(year + "-"))
                y_item = QTreeWidgetItem([t(f"{year}年 · {n_year} 张",
                                            f"{year} · {n_year}")])
                y_item.setData(0, Qt.UserRole, year)
                f = y_item.font(0)
                f.setBold(True)
                y_item.setFont(0, f)
                self.tree_nav.addTopLevelItem(y_item)
                if year == str(today.year):
                    self.tree_nav.expandItem(y_item)
            m_item = QTreeWidgetItem([t(f"{int(month)}月 · {len(photos)} 张",
                                        f"{int(month):02d} · {len(photos)}")])
            m_item.setData(0, Qt.UserRole, ym)
            y_item.addChild(m_item)
            if ym == today.strftime("%Y-%m"):
                self.tree_nav.expandItem(y_item)
            # 日级(懒展开才生成): 按日计数
            days: dict[str, int] = {}
            for ph in photos:
                d = self._day_key(ph.get("taken_at"))
                if d:
                    days[d] = days.get(d, 0) + 1
            for d in sorted(days):
                d_item = QTreeWidgetItem([t(f"{int(d)}日 · {days[d]} 张",
                                            f"{int(d):02d} · {days[d]}")])
                d_item.setData(0, Qt.UserRole, f"{ym}|{d}")
                m_item.addChild(d_item)
        self.tree_nav.blockSignals(False)
        if keep_key:
            for it in self._tree_all_items():
                if it.data(0, Qt.UserRole) == keep_key:
                    self.tree_nav.setCurrentItem(it)
                    break

    def _tree_all_items(self):
        it = QTreeWidgetItemIterator(self.tree_nav)
        while it.value() is not None:
            yield it.value()
            it += 1

    def _on_tree_click(self, item: QTreeWidgetItem, _col: int) -> None:
        """点击树节点→滚动到对应月份标题/当日首图。

        点具体日期=内容区改按**日**分组(各日小标题, 2026-11-04用户);
        点年/月=按月分组(默认)。级别变化时重建内容区。"""
        key = item.data(0, Qt.UserRole)
        self._chips_key = key      # 鸟种胶囊范围跟树点击(0.8.6)
        target = None
        if key and "|" in key:
            # key="YYYY-MM|DD"——_group_day必须存完整ISO日期"YYYY-MM-DD":
            # refresh的day模式按 iso==focus 与 ym==focus[:7] 过滤,
            # 此前只存日号"26"→全月被continue跳过→内容区空白(test3实测)
            day = "-".join(key.split("|", 1))
            if getattr(self, "_group_level", "month") != "day" \
                    or getattr(self, "_group_day", None) != day:
                # 级别切换: 按日分组并重建(重建后走下方滚动定位)
                self._group_level = "day"
                self._group_day = day
                self.refresh(force=True)
                self._retarget_tree_item(key)
        elif key:
            if getattr(self, "_group_level", "month") != "month":
                self._group_level = "month"
                self._group_day = None
                self.refresh(force=True)
                self._retarget_tree_item(key)
        if key and "|" in key:
            target = self._day_item.get(key)
        elif key:
            target = self._ym_head.get(key)
            if target is None:        # 年节点/杂项: 跳其第一个月
                for k, w in self._ym_head.items():
                    if k.startswith(str(key)) or k == key:
                        target = w
                        break
        if target is None:
            return
        try:
            y = target.mapTo(self.content, QPoint(0, 0)).y()
        except RuntimeError:
            return                    # 刷新竞态: 控件已删, 忽略本次点击
        self.scroll.verticalScrollBar().setValue(max(0, y - 12))

    def _retarget_tree_item(self, key: str) -> None:
        """refresh重建树后, 按key在新树里找回对应节点并选中(旧item已被
        deleteLater——直接setSelected会崩, 0.8按日分组时实测)。"""
        def walk(it):
            for i in range(it.childCount()):
                ch = it.child(i)
                if ch.data(0, Qt.UserRole) == key:
                    return ch
                got = walk(ch)
                if got is not None:
                    return got
            return None
        for top in range(self.tree_nav.topLevelItemCount()):
            node = walk(self.tree_nav.topLevelItem(top))
            if node is not None:
                self.tree_nav.setCurrentItem(node)
                return

    def _sync_tree_current(self) -> None:
        """滚动位置→高亮树中当前区块(视口顶部所在月/日)。"""
        top = self.scroll.verticalScrollBar().value() + 40
        cur_key = None
        for ym, head in self._ym_head.items():
            try:
                if head.mapTo(self.content, QPoint(0, 0)).y() <= top:
                    cur_key = ym
                else:
                    break
            except RuntimeError:
                return
        if cur_key is None:
            return
        # 日级精化
        for dk, item in self._day_item.items():
            if not dk.startswith(cur_key + "|"):
                continue
            try:
                if item.mapTo(self.content, QPoint(0, 0)).y() <= top:
                    cur_key = dk
            except RuntimeError:
                return
        for it in self._tree_all_items():
            if it.data(0, Qt.UserRole) == cur_key:
                self.tree_nav.blockSignals(True)
                self.tree_nav.setCurrentItem(it)
                self.tree_nav.blockSignals(False)
                return

    def showEvent(self, e):
        super().showEvent(e)
        # 页面显示/切换到前台时布局才就绪: 校正列数(初次打开曾固定4列,
        # 须缩放窗口才触发——不依赖resize时序的兜底)
        QTimer.singleShot(0, self._on_relayout)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # 列数随窗口宽度自适应(曾固定为构建时算的列数, 放大不扩展):
        # 列数变化才防抖重建; force绕过数据签名门(纯resize没有数据变化)
        if self.isVisible() and self._wanted_cols() != self._cur_cols \
                and not self._resize_debounce.isActive():
            self._resize_debounce.start()

    def _on_relayout(self):
        if self._wanted_cols() != self._cur_cols:
            self.refresh(force=True)

    def _restore_scroll_after_rebuild(self):
        """重建后恢复刷新前位置: singleShot(0)常规路径 + rangeChanged兜底
        (布局未就绪时早恢复会被旧range/0钳住)。"""
        if self._keep_scroll <= 0:
            return
        bar = self.scroll.verticalScrollBar()

        def _try(_mn: int = 0, _mx: int = 0):
            if bar.maximum() <= 0 or not self._keep_scroll:
                return
            pos, self._keep_scroll = self._keep_scroll, 0
            bar.setValue(min(pos, bar.maximum()))
            try:
                bar.rangeChanged.disconnect(_try)
            except RuntimeError:
                pass

        bar.rangeChanged.connect(_try)
        QTimer.singleShot(0, _try)

    def _relink(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        d = QFileDialog.getExistingDirectory(
            self, t("选择照片现在所在的文件夹（含子文件夹会一并搜索）",
                    "Choose the folder where the photos are now "
                    "(subfolders are searched too)"))
        if not d:
            return
        n = self.lib.relink_photos(Path(d))
        if n:
            QMessageBox.information(self, t("重新链接完成", "Relinking complete"),
                                    t(f"已重新关联 {n} 张照片。\n"
                                      "现在可以正常查看和「重新识别」了。",
                                      f"Re-linked {n} photos.\n"
                                      "You can now view and \"Re-identify\" "
                                      "them normally."))
        else:
            QMessageBox.information(
                self, t("没有找到匹配", "No matches found"),
                t("在新文件夹里没有找到与丢失照片同名的文件。\n"
                  "请确认选择了照片现在所在的文件夹。",
                  "No files matching the missing photos by name were found "
                  "in the new folder.\nPlease make sure you selected the "
                  "folder where the photos are now."))
        self.refresh()

    def _daily_bird_banner(self):
        """每日一鸟横幅: 文化库中确定性轮换, 点击跳转物种详情。"""
        try:
            from ..core.culture import get_culture
            pool = get_culture().daily_pool()
        except Exception:
            return None
        if not pool:
            return None
        import datetime
        doy = datetime.date.today().timetuple().tm_yday
        code = pool[doy % len(pool)]
        sp = self.lib.species_info(code)
        if not sp:
            return None
        stories = get_culture().stories_for(code)
        story = stories[0] if stories else None

        card = QFrame()
        card.setObjectName("Card")
        card.setCursor(Qt.PointingHandCursor)
        h = QHBoxLayout(card)
        h.setContentsMargins(14, 12, 14, 12)
        h.setSpacing(14)
        cover = QLabel()
        cover.setFixedSize(84, 84)
        cover.setAlignment(Qt.AlignCenter)
        cover.setStyleSheet(f"background:{theme.FILL};border-radius:12px;")
        cov_row = self.lib.conn.execute(
            """SELECT p.path, p.file_hash FROM photos p
               WHERE p.id = (SELECT v2.photo_id FROM v_records v2
                              WHERE v2.eff_code=? ORDER BY v2.taken_at ASC LIMIT 1)""",
            (code,)).fetchone()
        if cov_row:
            tp = ensure_thumbnail(self.lib.root, cov_row["path"], cov_row["file_hash"], 180)
            if tp:
                pm = QPixmap(str(tp))
                cover.setPixmap(pm.scaled(84, 84, Qt.KeepAspectRatioByExpanding,
                                          Qt.SmoothTransformation))
        else:
            cover.setText("🐦")
            cover.setStyleSheet(f"font-size:34px;background:{theme.FILL};border-radius:12px;")
        h.addWidget(cover)

        info = QVBoxLayout()
        info.setSpacing(2)
        tag = QLabel(t("每日一鸟 · 文化故事", "Bird of the day · Culture story"))
        tag.setStyleSheet(f"color:{theme.OLIVE};font-size:11px;font-weight:700;"
                          "background:transparent;")
        info.addWidget(tag)
        name = QLabel(sname(sp["cn"], sp["en"]))
        name.setStyleSheet(f"font-size:17px;font-weight:800;color:{theme.LABEL};"
                           "background:transparent;")
        info.addWidget(name)
        if story:
            snippet = (story["summary"] or story["body"] or "")[:76]
            line = QLabel(story["title"] + ("　" + snippet if snippet else ""))
            line.setStyleSheet(f"font-size:12px;color:{theme.LABEL_2};background:transparent;")
            line.setWordWrap(True)
            info.addWidget(line)
        else:
            sci = QLabel(sp["sci"])
            sci.setStyleSheet(f"font-size:12px;color:{theme.LABEL_2};background:transparent;")
            info.addWidget(sci)
        h.addLayout(info, 1)

        go = QLabel(t("查看 ›", "View ›"))
        go.setStyleSheet(f"color:{theme.BLUE};font-size:14px;font-weight:600;"
                         "background:transparent;")
        h.addWidget(go)
        card.mousePressEvent = lambda e: self.win.open_species(code)
        return card

    def _thumb(self, ph: dict) -> QPixmap | None:
        pid = ph["id"]
        if pid in self._thumb_cache:
            return self._thumb_cache[pid]
        from ..db import Library  # noqa
        row = self.lib.conn.execute(
            "SELECT file_hash FROM photos WHERE id=?", (pid,)).fetchone()
        if not row:
            return None
        tp = ensure_thumbnail(self.lib.root, ph["path"], row["file_hash"],
                              max(256, self._tile))
        if tp:
            pm = QPixmap(str(tp))
            self._thumb_cache[pid] = pm
            return pm
        return None

    def _open(self, photo_id: int, ids: list[int]):
        dlg = PhotoViewer(self.lib, self.win, photo_id, ids)
        dlg.exec()
        self.refresh()
