# -*- coding: utf-8 -*-
"""作品集页(UI重设计c4, 补⑮"只能加不能看"缺口): 页内 list↔detail 双模式
(仿 species_page)。list=作品集卡片(封面=集内美学最高照); detail=集内照片
网格 + 在时间线查看 / 导出本集 / 选择移出。数据层全复用 collections_*
现成接口, db 零 schema 改动。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QMessageBox, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from .. import theme
from ..i18n import t
from ..media import cached_thumbnail, ensure_thumbnail


class CollectionsPage(QWidget):
    def __init__(self, lib, win):
        super().__init__()
        self.lib = lib
        self.win = win
        self._mode = "list"          # list | detail
        self._cur_cid: int | None = None
        self._sel_mode = False
        self._sel: set[int] = set()
        self._build_ui()
        self.refresh()

    # ---------- UI ----------
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        from ..theme.widgets import PageHeader
        head = QHBoxLayout()
        self.title = PageHeader(t("作品集", "Collections"))
        head.addWidget(self.title, 1)
        self.new_btn = QPushButton(t("＋ 新建作品集", "＋ New collection"))
        self.new_btn.setObjectName("Primary")
        self.new_btn.setCursor(Qt.PointingHandCursor)
        self.new_btn.clicked.connect(self._new_collection)
        self.title.add_action(self.new_btn)
        lay.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.content = QWidget()
        self.content_lay = QVBoxLayout(self.content)
        self.content_lay.setContentsMargins(0, 0, 16, 24)
        self.content_lay.setSpacing(14)
        self.scroll.setWidget(self.content)
        lay.addWidget(self.scroll, 1)

    # ---------- 数据 ----------
    def refresh(self):
        if self._mode == "detail" and self._cur_cid is not None:
            exists = self.lib.conn.execute(
                "SELECT 1 FROM collections WHERE id=?",
                (self._cur_cid,)).fetchone()
            if not exists:
                self._mode = "list"
                self._cur_cid = None
        if self._mode == "list":
            self._show_list()
        else:
            self._show_detail(self._cur_cid, restore=True)

    def on_page_hidden(self):
        pass

    # ---------- list 模式 ----------
    def _show_list(self):
        self._clear_content()
        self.title.set_title(t("作品集", "Collections"))
        self.new_btn.setVisible(True)
        cols_all = self.lib.collections_list()
        if not cols_all:
            empty = QFrame()
            empty.setObjectName("Card")
            ev = QVBoxLayout(empty)
            ev.setContentsMargins(24, 28, 24, 28)
            ev.setSpacing(10)
            big = QLabel(t("还没有作品集", "No collections yet"))
            big.setAlignment(Qt.AlignHCenter)
            big.setStyleSheet(f"font-size:17px;font-weight:700;"
                              f"color:{theme.LABEL};background:transparent;")
            ev.addWidget(big)
            hint = QLabel(t(
                "作品集=主题精选辑（猛禽专题 / 某次旅行 / 中国鸟类…）。\n"
                "入口：时间线 → 选择 → 选中照片 → 「加入作品集…」；"
                "鸟种详情照片也可从查看器右栏「标签/作品集…」勾入。",
                "A collection is a themed selection (raptors / a trip / "
                "China birds…).\nAdd photos via Timeline → Select → "
                "\"Add to collection…\", or from the viewer's right panel "
                "\"Tags & collections…\"."))
            hint.setAlignment(Qt.AlignHCenter)
            hint.setWordWrap(True)
            hint.setObjectName("Hint")
            ev.addWidget(hint)
            self.content_lay.addWidget(empty)
            self.content_lay.addStretch(1)
            return
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 12)
        grid.setSpacing(14)
        cw = 220
        cols = max(2, (self.width() - 60) // (cw + 14))
        for i, c in enumerate(cols_all):
            card = self._collection_card(c)
            grid.addWidget(card, i // cols, i % cols)
        grid.setColumnStretch(cols, 1)
        self.content_lay.addWidget(grid_widget)
        self.content_lay.addStretch(1)

    def _collection_card(self, c: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        card.setFixedWidth(220)
        card.setCursor(Qt.PointingHandCursor)
        v = QVBoxLayout(card)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        cover = QLabel()
        cover.setFixedSize(196, 130)
        cover.setAlignment(Qt.AlignCenter)
        cover.setStyleSheet(f"background:{theme.FILL};border-radius:10px;")
        cid = c["id"]
        cov_pid = self.lib.collection_cover(cid)
        if cov_pid is not None:
            row = self.lib.conn.execute(
                "SELECT path, file_hash FROM photos WHERE id=?",
                (cov_pid,)).fetchone()
            if row and row["path"]:
                tp = cached_thumbnail(self.lib.root, row["file_hash"], 392) \
                    or ensure_thumbnail(self.lib.root, row["path"],
                                        row["file_hash"], 392)
                if tp:
                    pm = QPixmap(str(tp))
                    if not pm.isNull():
                        cover.setPixmap(pm.scaled(
                            cover.size(), Qt.KeepAspectRatioByExpanding,
                            Qt.SmoothTransformation))
        v.addWidget(cover)
        name = QLabel(c["name"])
        name.setWordWrap(True)
        name.setStyleSheet(f"font-size:15px;font-weight:700;"
                           f"color:{theme.LABEL};background:transparent;")
        v.addWidget(name)
        st = self.lib.collection_stats(cid)
        span = ""
        if st["first"]:
            a = (st["first"] or "")[:10]
            b = (st["last"] or "")[:10]
            span = f" · {a}" if a == b else f" · {a}~{b}"
        meta = QLabel(t(f"{st['n']} 张 · {st['species']} 种{span}",
                        f"{st['n']} photos · {st['species']} species{span}"))
        meta.setObjectName("Hint")
        v.addWidget(meta)
        # 点击→detail; 右键→重命名/删除
        card.mousePressEvent = lambda e, _cid=cid: (
            self._context_menu(_cid) if e.button() == Qt.RightButton
            else self._open_detail(_cid))
        return card

    def _context_menu(self, cid: int):
        from PySide6.QtGui import QCursor
        name = self.lib.conn.execute(
            "SELECT name FROM collections WHERE id=?", (cid,)).fetchone()
        if not name:
            return
        m = QMenu(self)
        a_ren = m.addAction(t("重命名…", "Rename…"))
        m.addSeparator()
        a_del = m.addAction(t("删除作品集…", "Delete collection…"))
        act = m.exec(QCursor.pos())
        if act == a_ren:
            self._rename_collection(cid, name["name"])
        elif act == a_del:
            self._delete_collection(cid, name["name"])

    # ---------- detail 模式 ----------
    def _open_detail(self, cid: int):
        self._mode = "detail"
        self._cur_cid = cid
        self._sel_mode = False
        self._sel = set()
        self._show_detail(cid)

    def _show_detail(self, cid: int | None, restore: bool = False):
        if cid is None:
            self._mode = "list"
            return self._show_list()
        self._clear_content()
        row = self.lib.conn.execute(
            "SELECT name FROM collections WHERE id=?", (cid,)).fetchone()
        name = row["name"] if row else "?"
        self.title.set_title(name)
        self.new_btn.setVisible(False)

        # 头部动作: 返回 / 在时间线查看 / 导出本集 / 选择(移出用)
        back = QPushButton(t("← 返回列表", "← Back"))
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self._back)
        self.title.add_action(back)
        self.view_btn = QPushButton(t("在时间线查看", "View in timeline"))
        self.view_btn.setToolTip(t(
            "跳到时间线并按本作品集过滤（再点筛选条「作品集: 全部」还原）",
            "Jump to the timeline filtered by this collection"))
        self.view_btn.setCursor(Qt.PointingHandCursor)
        self.view_btn.clicked.connect(self._view_in_timeline)
        self.title.add_action(self.view_btn)
        self.export_btn = QPushButton(t("导出本集…", "Export this collection…"))
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.clicked.connect(self._export_this)
        self.title.add_action(self.export_btn)
        self.sel_btn = QPushButton(t("选择", "Select"))
        self.sel_btn.setCheckable(True)
        self.sel_btn.setCursor(Qt.PointingHandCursor)
        self.sel_btn.clicked.connect(self._toggle_sel)
        self.title.add_action(self.sel_btn)

        pids = self.lib.collection_photos_of(cid)
        if not pids:
            empty = QLabel(t("这个作品集还是空的——去时间线选中照片后"
                             "「加入作品集…」",
                             "This collection is empty — select photos on "
                             "the timeline and \"Add to collection…\""))
            empty.setObjectName("Hint")
            self.content_lay.addWidget(empty)
            self.content_lay.addStretch(1)
            self._sync_sel_ui()
            return

        # 移出工具条(选择模式)
        self.sel_bar = QFrame()
        self.sel_bar.setObjectName("Card")
        sb = QHBoxLayout(self.sel_bar)
        sb.setContentsMargins(16, 10, 16, 10)
        sb.setSpacing(8)
        self.sel_count = QLabel(t("已选 0 张", "0 selected"))
        self.sel_count.setStyleSheet(
            f"font-size:14px;font-weight:700;color:{theme.BLUE};"
            "background:transparent;")
        sb.addWidget(self.sel_count)
        sb.addStretch(1)
        self.rm_btn = QPushButton(t("移出本集", "Remove from collection"))
        self.rm_btn.setCursor(Qt.PointingHandCursor)
        self.rm_btn.clicked.connect(self._remove_selected)
        sb.addWidget(self.rm_btn)
        done = QPushButton(t("完成", "Done"))
        done.setCursor(Qt.PointingHandCursor)
        done.clicked.connect(self._toggle_sel)
        sb.addWidget(done)
        self.sel_bar.setVisible(False)
        self.content_lay.addWidget(self.sel_bar)

        from ..theme.widgets import PhotoGridItem, grid_tile_of
        tile = grid_tile_of(self.lib)
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 12)
        grid.setSpacing(10)
        cols = max(3, (self.width() - 80) // (tile + 10))
        for i, pid in enumerate(pids):
            row = self.lib.conn.execute(
                "SELECT path, file_hash FROM photos WHERE id=?",
                (pid,)).fetchone()
            pm = None
            if row and row["path"]:
                tsize = max(256, tile)
                tp = cached_thumbnail(self.lib.root, row["file_hash"], tsize) \
                    or ensure_thumbnail(self.lib.root, row["path"],
                                        row["file_hash"], tsize)
                if tp:
                    pm = QPixmap(str(tp))
            item = PhotoGridItem(pm, tile=tile)
            item.setCursor(Qt.PointingHandCursor)
            if self._sel_mode:
                item.set_selected(pid in self._sel)
                item.mousePressEvent = lambda e, p=pid, it=item: \
                    self._sel_click(p, it)
            else:
                ids = list(pids)
                item.mousePressEvent = lambda e, p=pid, i2=ids: \
                    self._open(p, i2)
            grid.addWidget(item, i // cols, i % cols)
        grid.setColumnStretch(cols, 1)
        self.content_lay.addWidget(grid_widget)
        self.content_lay.addStretch(1)
        self._sync_sel_ui()

    # ---------- 选择/移出 ----------
    def _toggle_sel(self):
        self._sel_mode = not self._sel_mode
        if not self._sel_mode:
            self._sel = set()
        self._show_detail(self._cur_cid, restore=True)

    def _sel_click(self, pid: int, item):
        if pid in self._sel:
            self._sel.discard(pid)
        else:
            self._sel.add(pid)
        item.set_selected(pid in self._sel)
        self._sync_sel_ui()

    def _sync_sel_ui(self):
        bar = getattr(self, "sel_bar", None)
        if bar is not None:
            bar.setVisible(self._sel_mode)
        cnt = getattr(self, "sel_count", None)
        if cnt is not None:
            cnt.setText(t(f"已选 {len(self._sel)} 张",
                          f"{len(self._sel)} selected"))
        btn = getattr(self, "sel_btn", None)
        if btn is not None:
            btn.setChecked(self._sel_mode)

    def _remove_selected(self):
        if not self._sel or self._cur_cid is None:
            return
        mem = self.lib.collection_photos_of(self._cur_cid)
        self.lib.collection_set_photos(
            self._cur_cid, [p for p in mem if p not in self._sel])
        self._sel = set()
        self._show_detail(self._cur_cid, restore=True)

    # ---------- 动作 ----------
    def _back(self):
        self._mode = "list"
        self._cur_cid = None
        self._sel_mode = False
        self._sel = set()
        self.refresh()

    def _view_in_timeline(self):
        if self._cur_cid is None:
            return
        self.win.switch_to("timeline")
        tl = self.win.pages.get("timeline")
        if tl is not None and hasattr(tl, "apply_collection_filter"):
            tl.apply_collection_filter(self._cur_cid)

    def _export_this(self):
        if self._cur_cid is None:
            return
        from .export_dialog import ExportDialog
        dlg = ExportDialog(self.lib, self.win, preset_collection=self._cur_cid)
        dlg.exec()

    def _new_collection(self):
        name, ok = self._ask_name(t("新建作品集", "New collection"), "")
        if ok and name.strip():
            try:
                cid = self.lib.collection_create(name.strip())
            except ValueError:
                QMessageBox.information(
                    self, t("已存在", "Exists"),
                    t("同名作品集已存在，已为你打开。",
                      "A collection with this name already exists; "
                      "opening it."))
                row = self.lib.conn.execute(
                    "SELECT id FROM collections WHERE name=?",
                    (name.strip(),)).fetchone()
                self._open_detail(row["id"])
                return
            self._open_detail(cid)

    def _rename_collection(self, cid: int, old: str):
        name, ok = self._ask_name(t("重命名作品集", "Rename collection"), old)
        if not ok or not name.strip() or name.strip() == old:
            return
        try:
            self.lib.collection_rename(cid, name.strip())
        except ValueError:
            QMessageBox.warning(
                self, t("无法重命名", "Cannot rename"),
                t("名字为空或与其他作品集重名。", "The name is empty or "
                  "duplicates another collection."))
        self.refresh()

    def _delete_collection(self, cid: int, name: str):
        r = QMessageBox.question(
            self, t("删除作品集", "Delete collection"),
            t(f"删除作品集「{name}」？\n\n只解散本作品集与照片的关联，"
              "照片与其标注安全保留在库中。",
              f"Delete collection \"{name}\"?\n\nOnly the membership is "
              "removed; photos and their annotations stay in the library."))
        if r == QMessageBox.Yes:
            self.lib.collection_delete(cid)
            if self._cur_cid == cid:
                self._cur_cid = None
                self._mode = "list"
            self.refresh()

    def _ask_name(self, title: str, text: str):
        from PySide6.QtWidgets import QInputDialog
        s, ok = QInputDialog.getText(
            self, title, t("名称：", "Name:"), QLineEdit.Normal, text)
        return (s or "").strip(), ok

    def _open(self, photo_id: int, ids: list[int]):
        from .viewer import PhotoViewer
        dlg = PhotoViewer(self.lib, self.win, photo_id, ids)
        dlg.exec()
        self.refresh()

    # ---------- 通用 ----------
    def _clear_content(self):
        # 断开 title 动作区里的本页动态按钮(每次 show 重建, 防重复堆积)
        for w in ("view_btn", "export_btn", "sel_btn"):
            b = getattr(self, w, None)
            if b is not None:
                b.setParent(None)
                b.deleteLater()
                setattr(self, w, None)
        while self.content_lay.count():
            it = self.content_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
