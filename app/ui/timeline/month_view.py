# -*- coding: utf-8 -*-
"""时间线月视图(c8): 月块渲染+时间树(整树重建加固)+自适应重排+缩略图。"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout,
                               QHBoxLayout, QLabel,
                               QPushButton, QScrollArea,
                               QTreeWidget,
                               QTreeWidgetItem,
                               QTreeWidgetItemIterator,
                               QVBoxLayout, QWidget)

from ...i18n import t, sname
from ... import theme
from ...media import ensure_thumbnail
from ...theme.widgets import PhotoGridItem, grid_tile_of, ThemedDateEdit


class MonthViewMixin:
    """MonthViewMixin(c8自timeline_page纯搬家, 方法体零改动)。"""

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
            # ⑬视频: label 前缀 ▶+时长
            cap = self._caption(ph)
            if ph.get("is_video"):
                cap = t("▶ 视频", "▶ Video") + (
                    f" {int(ph['duration'] // 60)}:{int(ph['duration'] % 60):02d}"
                    if ph.get("duration") else "") + (f" · {cap}" if cap else "")
            item = PhotoGridItem(thumb, label=cap,
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

    def _make_tree(self) -> QTreeWidget:
        """构造时间树控件(样式+点击连接)。
        UI重设计c7加固: _build_tree改为整树重建——原tree_nav.clear()在
        offscreen/高负载下偶发access violation(2026-11-19实测复现, 同
        PLAN.md"deleteLater半删对象"陷阱类; 真实GUI无害但测试不稳),
        deleteLater旧树整体替换可绕开C++ clear()的崩溃路径。"""
        w = QTreeWidget()
        w.setHeaderHidden(True)
        w.setFixedWidth(196)
        w.setIndentation(16)
        w.setStyleSheet(
            f"QTreeWidget{{background:{theme.CARD};border:1px solid {theme.SEP};"
            "border-radius:12px;padding:4px;}"
            "QTreeWidget::item{height:26px;border-radius:7px;margin:1px 2px;}"
            "QTreeWidget::item:hover{background:rgba(127,127,127,40);}"
            "QTreeWidget::item:selected{background:rgba(0,122,255,60);}")
        w.itemClicked.connect(self._on_tree_click)
        return w

    def _build_tree(self, data: dict) -> None:
        """重建左侧时间树(整树重建替换)。锚点: 月=月份标题QLabel,
        日=当日首个网格项; 点击itemClicked跳转, 滚动反向高亮
        (_sync_tree_current)。"""
        keep = self.tree_nav.currentItem()
        try:
            keep_key = keep.data(0, Qt.UserRole) if keep else None
        except RuntimeError:      # 上一次refresh的旧item已删(离屏压力下偶发)
            keep_key = None
        # 整树替换: 新树插入旧树位置, 旧树摘除+deleteLater(不再用clear())
        old = self.tree_nav
        self.tree_nav = self._make_tree()
        idx = self._body_lay.indexOf(old)
        self._body_lay.insertWidget(idx, self.tree_nav)
        self._body_lay.removeWidget(old)
        old.hide()
        old.deleteLater()
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

    def _thumb(self, ph: dict) -> QPixmap | None:
        pid = ph["id"]
        if pid in self._thumb_cache:
            return self._thumb_cache[pid]
        from ...db import Library  # noqa
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
