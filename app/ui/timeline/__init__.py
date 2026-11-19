# -*- coding: utf-8 -*-
"""时间线页(c8拆包): 壳=组装+refresh调度; mixin分件——
filters(六维筛选+胶囊) / select_bar(多选+批量) / month_view(月块+时间树) /
actions(工具与批量对话框)。方法体自原 timeline_page.py 纯搬家零改动。"""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ...i18n import t
from ... import theme
from ...theme.widgets import (PhotoGridItem, grid_tile_of,
                              make_grid_tier_control)
from ..viewer import PhotoViewer
from .actions import ActionsMixin
from .filters import FiltersMixin
from .select_bar import SelectBarMixin
from .month_view import MonthViewMixin


class TimelinePage(FiltersMixin, SelectBarMixin, MonthViewMixin, ActionsMixin,
                   QWidget):
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

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        head = QHBoxLayout()
        from ...theme.widgets import PageHeader
        self.title = PageHeader(t("时间线", "Timeline"))
        head.addWidget(self.title, 1)
        self.burst_btn = QPushButton(t("连拍折叠", "Stack bursts"))
        self.burst_btn.setCheckable(True)
        self.burst_btn.setChecked(
            self.lib.get_setting("burst_collapse", "1") == "1")
        self.burst_btn.setCursor(Qt.PointingHandCursor)
        self.burst_btn.setToolTip(t(
            "2秒内同鸟种的连拍折成一张封面（角标 ×N），点开看全组；多选时自动展开",
            "Stack same-species burst shots taken within 2s into one cover "
            "(×N badge); click to browse the group. Auto-expanded in select mode"))
        self.burst_btn.toggled.connect(self._toggle_collapse)
        self.title.add_action(self.burst_btn)
        self.share_btn = QPushButton(t("批量分享卡…", "Batch share cards…"))
        self.share_btn.setCursor(Qt.PointingHandCursor)
        self.share_btn.clicked.connect(self._batch_share)
        self.title.add_action(self.share_btn)
        # 低频工具收纳(UI重设计c8): 导出/查重/记录中心/静态站 → 「工具 ▾」
        self.title.add_action(self._build_tools_button())
        self.select_btn = QPushButton(t("选择", "Select"))
        self.select_btn.setObjectName("Primary")
        self.select_btn.setCursor(Qt.PointingHandCursor)
        self.select_btn.clicked.connect(self._toggle_select)
        self.title.add_action(self.select_btn)
        self.title.add_action(make_grid_tier_control(self.lib, self._tier_changed))
        lay.addLayout(head)

        # 筛选条(c8: filters._build_fbar)
        lay.addLayout(self._build_fbar())

        # 多选工具条(c8: select_bar._build_sel_bar)
        lay.addWidget(self._build_sel_bar())

        # 鸟种胶囊行(0.8.6用户: 按选中月/日显示鸟种, 点击筛选):
        # 默认隐藏, 点了时间树节点才出现; FlowLayout自动换行
        from ...theme.widgets import FlowLayout
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
        self._body_lay = body
        self.tree_nav = self._make_tree()
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
        if hasattr(self, "tag_filter"):
            self._refresh_tag_filter()
            self._refresh_col_filter()
            self._refresh_spot_filter()
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
        # 标签筛选(1.0冲刺⑭): 批量map避免逐张查询
        ti = self.tag_filter.currentIndex() if hasattr(self, "tag_filter") else 0
        if ti:
            tag_id = self.tag_filter.itemData(ti)
            tagged = {r["photo_id"] for r in self.lib.conn.execute(
                "SELECT photo_id FROM photo_tags WHERE tag_id=?", (tag_id,))}
            raw = {ym: [p for p in v if p["id"] in tagged]
                   for ym, v in raw.items()}
            raw = {ym: v for ym, v in raw.items() if v}
        # 作品集筛选(UI重设计c3): 同标签套路, 批量map避免逐张查询
        ci_col = (self.col_filter.currentIndex()
                  if hasattr(self, "col_filter") else 0)
        if ci_col:
            cid = self.col_filter.itemData(ci_col)
            in_col = {r["photo_id"] for r in self.lib.conn.execute(
                "SELECT photo_id FROM collection_photos WHERE collection_id=?",
                (cid,))}
            raw = {ym: [p for p in v if p["id"] in in_col]
                   for ym, v in raw.items()}
            raw = {ym: v for ym, v in raw.items() if v}
        # 鸟点筛选(1.0冲刺⑤)
        si = self.spot_filter.currentIndex() if hasattr(self, "spot_filter") else 0
        if si:
            spot_name = self.spot_filter.currentText()
            spot_name = spot_name.split(" (")[0] if " (" in spot_name else spot_name
            raw = {ym: [p for p in v
                        if (p.get("spot_name") or "") == spot_name]
                   for ym, v in raw.items()}
            raw = {ym: v for ym, v in raw.items() if v}
        # 置信度筛选(1.0冲刺⑤): 待复核<0.5即既有语义
        ci = self.conf_filter.currentIndex() if hasattr(self, "conf_filter") else 0
        if ci:
            if ci == 1:
                raw = {ym: [p for p in v if p.get("main_conf") is not None
                            and p["main_conf"] < 0.5]
                       for ym, v in raw.items()}
            elif ci == 2:
                raw = {ym: [p for p in v if (p.get("main_conf") or 0) >= 0.5]
                       for ym, v in raw.items()}
            elif ci == 3:
                raw = {ym: [p for p in v if (p.get("main_conf") or 0) >= 0.8]
                       for ym, v in raw.items()}
            else:            # 无识别
                raw = {ym: [p for p in v if p.get("main_conf") is None]
                       for ym, v in raw.items()}
            raw = {ym: v for ym, v in raw.items() if v}
        counts = {ym: len(v) for ym, v in raw.items()}
        if self._collapse_on():
            from ...core.burst import collapse_bursts
            data = {ym: collapse_bursts(v) for ym, v in raw.items()}
        else:
            data = raw
        lifer_ids = self.lib.lifer_photo_ids()
        import datetime
        year_ids = self.lib.year_bird_photo_ids(datetime.date.today().strftime('%Y'))
        total = sum(counts.values())
        self.title.set_title(t(f"时间线 · {total} 张照片", f"Timeline · {total} photos"))
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
            from ...core.offline import drive_label
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
        # 重建后强制几何重算: offscreen/个别DPI下 QScrollArea收不到
        # LayoutRequest时 content 被压到 viewport 高, 网格行塌缩
        # (1.0冲刺实测verify_scroll_restore max=0px); 真实GUI此调用
        # 无害(sizeHint未变时零开销)
        self.content.adjustSize()
        # 初次打开时页面尚未布局, 列数按陈旧宽度算(曾固定4列)——布局
        # 稳定后再校正一次(列数没变则直接返回, 无开销)
        QTimer.singleShot(0, self._on_relayout)

    def _open(self, photo_id: int, ids: list[int]):
        dlg = PhotoViewer(self.lib, self.win, photo_id, ids)
        dlg.exec()
        self.refresh()
