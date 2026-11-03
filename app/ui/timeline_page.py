# -*- coding: utf-8 -*-
"""时间线页: 按年月分组展示全部照片, lifer角标, 点击看大图。
多选模式: 批量从鸟迹移除 / 批量重新识别。"""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QDateEdit, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout,
                               QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QScrollArea,
                               QSizePolicy, QTreeWidget, QTreeWidgetItem,
                               QTreeWidgetItemIterator, QVBoxLayout, QWidget)

from ..i18n import t, sname
from ..media import ensure_thumbnail
from .. import theme
from ..theme.widgets import PhotoGridItem
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
        self.select_btn = QPushButton(t("选择", "Select"))
        self.select_btn.setObjectName("Primary")
        self.select_btn.setCursor(Qt.PointingHandCursor)
        self.select_btn.clicked.connect(self._toggle_select)
        head.addWidget(self.select_btn)
        lay.addLayout(head)

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
        self.rere_btn = QPushButton(t("重新识别…", "Re-identify…"))
        self.rere_btn.setObjectName("Primary")
        self.rere_btn.setCursor(Qt.PointingHandCursor)
        self.rere_btn.clicked.connect(self._batch_rerecognize)
        sb.addWidget(self.rere_btn)
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
        self.rm_btn.setEnabled(n > 0)
        self.rere_btn.setEnabled(n > 0)
        self.all_btn.setText(t("全不选", "Deselect all") if n >= self.lib.photo_count()
                             else t("全选", "Select all"))

    def _on_item_click(self, pid: int, item=None):
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
        ed_from = QDateEdit(hi)
        ed_to = QDateEdit(hi)
        for ed in (ed_from, ed_to):
            ed.setCalendarPopup(True)
            ed.setDisplayFormat("yyyy-MM-dd")
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
        missing = [r["path"] for r in rows if not Path(r["path"]).exists()]
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
              "现有的识别结果（包括人工确认/改过的鸟种）会被覆盖，"
              "按照片导入时的地区重新识别。",
              f"Re-identify the {len(ids)} selected photos?\n\n"
              "Existing recognition results (including manually confirmed or "
              "corrected species) will be overwritten and re-identified using "
              "the region recorded when each photo was imported."),
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        self.lib.reset_recognition(ids)
        self._selected.clear()
        self.win.library_changed.emit()
        self.refresh()
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
        return (p[0], p[1], r[0], r[1], r[2], datetime.date.today())

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
        data = self.lib.timeline()
        lifer_ids = self.lib.lifer_photo_ids()
        import datetime
        year_ids = self.lib.year_bird_photo_ids(datetime.date.today().strftime('%Y'))
        total = sum(len(v) for v in data.values())
        self.title.setText(t(f"时间线 · {total} 张照片", f"Timeline · {total} photos"))
        self._sync_sel_ui()
        # 原文件丢失统计(引用模式换电脑/移动后): 横幅+重新链接入口
        try:
            all_ids = [r["id"] for r in self.lib.conn.execute(
                "SELECT id, path FROM photos")]
            missing = [r["path"] for r in self.lib.conn.execute(
                "SELECT id, path FROM photos") if not Path(r["path"]).exists()]
        except Exception:
            missing = []
        if missing:
            mb = QFrame()
            mb.setObjectName("Card")
            mh = QHBoxLayout(mb)
            mh.setContentsMargins(14, 10, 14, 10)
            mt = QLabel(t(f"⚠️ {len(missing)} 张照片的原文件不在这台电脑上"
                          "（引用模式记录的是原路径）。",
                          f"⚠️ The original files for {len(missing)} photos are "
                          "not on this computer (reference mode records the "
                          "original paths)."))
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
            return
        for ym, photos in data.items():
            year, month = (ym.split("-") + [""])[:2]
            head_txt = (t(f"{year}年{int(month)}月 · {len(photos)} 张",
                          f"{year}-{int(month):02d} · {len(photos)} photos")
                        if month else ym)
            head = QLabel(head_txt)
            head.setStyleSheet(f"font-size:17px;font-weight:700;color:{theme.LABEL_2};"
                               "background:transparent;padding:8px 2px 2px 2px;")
            self.content_lay.addWidget(head)
            self._ym_head[ym] = head   # 时间树跳转锚点

            grid_widget = QWidget()
            grid = QGridLayout(grid_widget)
            grid.setContentsMargins(0, 0, 0, 12)
            grid.setSpacing(10)
            # 列数统一走_wanted_cols(视口宽)——此处曾另有一套页宽公式,
            # 比视口多算~2列, 网格永远横向溢出(2026-11-02用户实测回归)
            cols = self._wanted_cols()
            for i, ph in enumerate(photos):
                if ph["id"] in lifer_ids:
                    corner = t("首见", "First sighting")
                elif ph["id"] in year_ids:
                    corner = t("年鸟", "Year bird")
                else:
                    corner = None
                thumb = self._thumb(ph)
                if thumb is None and not Path(ph["path"]).exists():
                    corner = t("文件丢失", "File missing")   # 引用模式原文件不在这台电脑
                item = PhotoGridItem(thumb, label="", corner=corner)
                item.setFixedSize(THUMB + 12, THUMB + 12)
                item.setCursor(Qt.PointingHandCursor)
                item.set_selected(ph["id"] in self._selected)
                def _click(_e, _pid=ph["id"], _it=item):
                    # 防御: 网格重建后残留的僵尸控件点击直接忽略
                    try:
                        self._on_item_click(_pid, _it)
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
        self.content_lay.addStretch(1)
        self._build_tree(data)
        self._restore_scroll_after_rebuild()
        self._tl_sig = self._data_sig()
        self._cur_cols = self._wanted_cols()
        # 初次打开时页面尚未布局, 列数按陈旧宽度算(曾固定4列)——布局
        # 稳定后再校正一次(列数没变则直接返回, 无开销)
        QTimer.singleShot(0, self._on_relayout)

    def _wanted_cols(self) -> int:
        """当前布局下时间线应有的列数(用视口实际宽度——初次打开时
        self.width()还是构造默认值, 曾导致初始固定4列)。

        每列实占 = 格子(THUMB+12) + 列间距10, 首列左缘为0、末列后还有
        content右边距16: 放满条件 150·cols ≤ w−6。曾按140/列预算
        (w-80)//140——视口宽于~1100px时稳定溢出数px~数十px出横向
        滚动条(用户实测最大化也放不下所有列, 2026-11-02)。下限2列:
        加树后窄窗口视口仅400+px, 4列下限本身就会溢出。"""
        w = self.scroll.viewport().width() or self.width()
        return max(2, (w - 8) // (THUMB + 12 + 10))

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
        keep_key = keep.data(0, Qt.UserRole) if keep else None
        self.tree_nav.blockSignals(True)
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
        """点击树节点→滚动到对应月份标题/当日首图。"""
        key = item.data(0, Qt.UserRole)
        target = None
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
        tag.setStyleSheet("color:#8A9455;font-size:11px;font-weight:700;"
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
        tp = ensure_thumbnail(self.lib.root, ph["path"], row["file_hash"], THUMB * 2)
        if tp:
            pm = QPixmap(str(tp))
            self._thumb_cache[pid] = pm
            return pm
        return None

    def _open(self, photo_id: int, ids: list[int]):
        dlg = PhotoViewer(self.lib, self.win, photo_id, ids)
        dlg.exec()
        self.refresh()
