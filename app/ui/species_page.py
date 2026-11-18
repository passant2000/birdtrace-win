# -*- coding: utf-8 -*-
"""鸟种库: 卡片流(首见时间排序) + 搜索 + 鸟种详情(概览/图鉴/文化标签页)。"""
from __future__ import annotations

import json

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ..core import regions
from ..core.birddex import get_dex
from ..core.culture import get_culture
from ..core.prior_hint import get_hint, tier_display, value_tier
from ..i18n import t, sname
from ..media import cached_thumbnail, ensure_thumbnail
from .. import theme
from .viewer import PhotoViewer

IUCN_CN = {"LC": "无危", "NT": "近危", "VU": "易危", "EN": "濒危", "CR": "极危",  # i18n:ok
           "EW": "野外灭绝", "EX": "灭绝", "DD": "数据缺乏", "NE": "未评估"}  # i18n:ok
IUCN_EN = {"LC": "Least Concern", "NT": "Near Threatened", "VU": "Vulnerable",
           "EN": "Endangered", "CR": "Critically Endangered",
           "EW": "Extinct in the Wild", "EX": "Extinct", "DD": "Data Deficient",
           "NE": "Not Evaluated"}
COVER_W, COVER_H = 168, 126
CARD_COLS = 5
# 罕见度徽章配色(与分享卡胶囊一致): 稀有/罕见醒目红, 不常见橙, 常见系灰
RARITY_PILL = {("稀有", "罕见"): ("#E5484D", "white"),  # i18n:ok
               ("不常见",): ("#F5A623", "white")}  # i18n:ok

DEX_FIELDS = [
    ("summary", "概述", "Overview"), ("id_points", "识别要点", "ID points"),
    ("range", "分布区系", "Range"), ("habitat", "栖息地与海拔", "Habitat & elevation"),
    ("behavior", "行为生态", "Behavior"), ("diet", "食性", "Diet"),
    ("clutch", "每窝卵数", "Clutch size"),
]


def _info_row(label: str, value_html: str) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(12)
    lab = QLabel(label)
    lab.setStyleSheet(f"color:{theme.LABEL_2};font-size:13px;background:transparent;")
    lab.setFixedWidth(92)
    lab.setAlignment(Qt.AlignTop)
    val = QLabel(value_html)
    val.setWordWrap(True)
    val.setTextFormat(Qt.RichText)
    # 主题感知: 此前硬编码浅色#1C1C1E, 深色主题下图鉴正文与背景同色
    # (2026-11-05用户实测"文字和背景几乎一个颜色")
    val.setStyleSheet(f"color:{theme.LABEL};font-size:13px;background:transparent;")
    h.addWidget(lab)
    h.addWidget(val, 1)
    return w


def _pill(text: str, bg: str, fg: str) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(f"font-size:12px;font-weight:700;color:{fg};"
                      f"background:{bg};border-radius:11px;padding:5px 12px;")
    return lab


_HEAT_LO = (0xED, 0xF2, 0xDF)   # 浅橄榄(丰度低)
_HEAT_HI = (0x55, 0x63, 0x1F)   # 深橄榄(丰度顶格, 与强调色#8A9455同系)


def _heat_css(v: float) -> str:
    """区域先验值 → 单元格背景色; ≤-1.49(缺席/rescue地板)用主题占位灰。"""
    if v <= -1.49:
        return theme.FILL
    frac = max(0.0, min(1.0, (v + 1.5) / 3.5))
    rgb = tuple(round(lo + (hi - lo) * frac) for lo, hi in zip(_HEAT_LO, _HEAT_HI))
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _cell_tip(rid: str, v: float) -> str:
    reg = regions.region_display(rid)
    if v <= -1.49:
        return t(f"{reg}：无记录", f"{reg}: no records")
    tier = tier_display(value_tier(v))
    return t(f"{reg}：{tier} ({v:+.1f})", f"{reg}: {tier} ({v:+.1f})")


def _heat_rows(peaks: dict[str, float], parents: dict,
               region_id: str | None) -> tuple[list[str], int]:
    """热力表选行: 默认地区与其所在国置顶, 该国省级行次之(≤PROV_MAX),
    其余按峰值降序补齐到ROWS_MAX; 返回(行, 未展示地区数)。"""
    rows: list[str] = []
    if region_id and region_id != "GLOBAL" and region_id in peaks:
        rows.append(region_id)
        parent = parents.get(region_id)
        if parent and parent in peaks:
            rows.append(parent)
            provs = sorted((p for p, par in parents.items()
                            if par == parent and p in peaks and p not in rows),
                           key=lambda p: (-peaks[p], p))
            rows += provs[: _HeatTable.PROV_MAX]
    rest = sorted((p for p in peaks if p not in rows),
                  key=lambda p: (-peaks[p], p))
    rows += rest[: max(0, _HeatTable.ROWS_MAX - len(rows))]
    return rows, len(peaks) - len(rows)


class _HeatTable(QFrame):
    """地区分布表: 行=地区, 色块=该地区峰值丰度(与月份无关)。

    数据=geo_prior priors表12个月最大值(log先验[-4,+2], 清单频率代理);
    值≤-1.49(缺席/rescue地板-1.5/-2.0)按"无记录"处理。月份维度已按
    作者指示去掉(CN各行月度值失真, 详见prior_hint模块docstring)。
    """
    ROWS_MAX = 14   # 最多展示行数
    PROV_MAX = 6    # 默认地区所在国的省级行数上限
    NAME_W = 168
    CELL_H = 18

    def __init__(self, rows: list[str], peaks: dict, hidden: int,
                 region_id: str | None, on_open_map, on_open_migration):
        super().__init__()
        self._on_open_map = on_open_map
        self._on_open_migration = on_open_migration
        self.setObjectName("Card")
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 16, 20, 14)
        v.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel(t("地区分布", "Regional abundance"))
        title.setStyleSheet(f"font-size:15px;font-weight:700;color:{theme.LABEL};"
                            "background:transparent;")
        head.addWidget(title)
        head.addStretch(1)

        def _chip(text_pair):
            btn = QPushButton(t(*text_pair))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                f"font-size:12px;font-weight:600;color:{theme.BLUE};"
                f"background:{theme.CHIP_BG};border:none;border-radius:10px;"
                "padding:5px 12px;")
            return btn

        mig_btn = _chip(("🌍 迁徙地图…", "🌍 Migration map…"))
        mig_btn.clicked.connect(self._on_open_migration)
        head.addWidget(mig_btn)
        map_btn = _chip(("🗺️ 分布地图…", "🗺️ Distribution map…"))
        map_btn.clicked.connect(self._on_open_map)
        head.addWidget(map_btn)
        v.addLayout(head)
        sub = QLabel(t("行=地区 · 色块越深=越常见（按清单频率估算）",
                       "Rows = regions · darker = more common "
                       "(from checklist frequency)"))
        sub.setStyleSheet(f"font-size:12px;color:{theme.LABEL_3};"
                          "background:transparent;")
        v.addWidget(sub)

        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setSpacing(4)
        for r, rid in enumerate(rows):
            val = peaks[rid]
            disp = regions.region_display(rid)
            if rid == region_id:
                disp = "📍 " + disp
            name_lab = QLabel(disp)
            name_lab.setObjectName("HeatName")
            name_lab.setFixedWidth(self.NAME_W)
            name_lab.setToolTip(disp)
            name_lab.setStyleSheet(f"color:{theme.LABEL_2};font-size:12px;"
                                   "background:transparent;")
            fm = name_lab.fontMetrics()
            name_lab.setText(fm.elidedText(disp, Qt.ElideRight, self.NAME_W - 8))
            grid.addWidget(name_lab, r, 0)
            cell = QLabel()
            cell.setObjectName("HeatCell")
            cell.setFixedSize(120, self.CELL_H)
            cell.setStyleSheet(f"background:{_heat_css(val)};"
                               "border-radius:4px;")
            cell.setToolTip(_cell_tip(rid, val))
            grid.addWidget(cell, r, 1)
            tier_lab = QLabel(tier_display(value_tier(val)))
            tier_lab.setStyleSheet(f"color:{theme.LABEL_2};font-size:11px;"
                                   "background:transparent;")
            grid.addWidget(tier_lab, r, 2)
        grid.setColumnStretch(3, 1)
        v.addLayout(grid)

        leg = QHBoxLayout()
        leg.setSpacing(8)
        lo = QLabel(t("少", "Less"))
        lo.setStyleSheet(f"color:{theme.LABEL_3};font-size:11px;background:transparent;")
        grad = QLabel()
        grad.setFixedSize(120, 10)
        grad.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                           "stop:0 #EDF2DF, stop:1 #55631F);border-radius:5px;")
        hi = QLabel(t("多", "More"))
        hi.setStyleSheet(f"color:{theme.LABEL_3};font-size:11px;background:transparent;")
        note = QLabel(t("浅色 = 无记录", "Pale = no records"))
        note.setStyleSheet(f"color:{theme.LABEL_3};font-size:11px;background:transparent;")
        leg.addWidget(lo)
        leg.addWidget(grad)
        leg.addWidget(hi)
        leg.addSpacing(14)
        leg.addWidget(note)
        if hidden > 0:
            more = QLabel(t(f"另有 {hidden} 个地区有记录",
                            f"+ {hidden} more regions with records"))
            more.setStyleSheet(f"color:{theme.LABEL_3};font-size:11px;"
                               "background:transparent;")
            leg.addSpacing(14)
            leg.addWidget(more)
        leg.addStretch(1)
        v.addLayout(leg)


class _ThumbSignals(QObject):
    ready = Signal(int, str, str)   # gen, file_hash, 缩略图路径


class _ThumbJob(QRunnable):
    """后台补齐缺失的缩略图并逐张回传(不阻塞UI, 不碰数据库)。

    ensure_thumbnail内部优先从导入时生成的512px缓存降采样,
    单张开销很小; stop为共享标记dict, 离开详情页即置{True:}作废。
    """

    def __init__(self, lib_root, gen: int, items: list, sig: _ThumbSignals,
                 stop: dict):
        super().__init__()
        self._root = lib_root
        self._gen = gen
        self._items = items
        self._sig = sig
        self._stop = stop

    def run(self):
        for path, fhash in self._items:
            if self._stop.get("stop"):
                return
            tp = ensure_thumbnail(self._root, path, fhash, 512)
            if tp:
                self._sig.ready.emit(self._gen, fhash, str(tp))


class SpeciesPage(QWidget):
    def __init__(self, lib, win):
        super().__init__()
        self.lib = lib
        self.win = win
        self.current_code = None
        self._sel_mode = False         # 照片流多选模式(概览/未识别共用)
        self._sel: set[int] = set()    # 选中的photo_id
        self._sel_pool: list[int] = [] # 当前照片流全部id(全选用)
        self._sel_actions: list = []   # [(文案, 回调)], 渲染前设置
        self._sel_cnt_lbl = None       # 多选工具条控件引用(每次渲染重建)
        self._sel_all_btn = None
        self._sel_act_btns: list = []
        self.detail_tab = 0
        self._mode = "list"            # 当前视图(list/detail): 恢复滚动用
        self._list_scroll = 0          # 列表滚动位置(进详情前记住, 返回恢复)
        self._list_filter: str | None = None   # 上次列表构建的搜索词
        self._detail_scroll: dict[int, int] = {}   # 详情各tab的滚动位置
        self._pending_scroll = 0       # 待恢复的滚动位置(布局就绪后落位)
        self._list_sig = None          # 上次列表构建的数据签名(无变化跳过重建)
        self._thumb_gen = 0            # 代际号: 详情页重建即+1, 旧回传作废
        self._thumb_stop: dict = {}    # 当前任务的中断标记
        self._thumb_items: dict[str, object] = {}   # file_hash -> 网格项
        self._thumb_sig = _ThumbSignals(self)
        self._thumb_sig.ready.connect(self._thumb_ready)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        head = QHBoxLayout()
        self.title = QLabel(t("鸟种库", "Species"))
        self.title.setStyleSheet(f"font-size:26px;font-weight:800;color:{theme.LABEL};"
                                 "background:transparent;")
        head.addWidget(self.title)
        head.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            t("搜索 中文名 / 拼音 / 学名 / 英文名…",
              "Search Chinese / pinyin / Latin / English name…"))
        self.search.setFixedWidth(300)
        self.search.textChanged.connect(lambda _t: self.refresh())
        head.addWidget(self.search)
        self.back_btn = QPushButton(t("← 返回列表", "← Back to list"))
        self.back_btn.setVisible(False)
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.clicked.connect(self._back)
        head.addWidget(self.back_btn)
        lay.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.content_lay = QVBoxLayout(self.content)
        self.content_lay.setContentsMargins(0, 0, 16, 24)
        self.content_lay.setSpacing(10)
        self.scroll.setWidget(self.content)
        lay.addWidget(self.scroll, 1)

    # ---------- 列表 ----------
    def on_page_hidden(self):
        """被切走时(main_window.switch_to钩子)停掉后台缩略图任务:
        释放线程池与磁盘IO——地图等重页首开时不再与缩略图解码抢资源。
        回到本页时refresh按数据签名决定是否重建, 缺的缩略图会重新排队。"""
        self._cancel_thumb_job()

    def _cancel_thumb_job(self):
        self._thumb_gen += 1
        self._thumb_stop["stop"] = True   # 原地标记, 在跑的任务读到即退出
        self._thumb_items = {}

    def _data_sig(self):
        """库内容廉价签名(照片/鸟点/记录的计数与内容摘要), 判断要不要重建。"""
        c = self.lib.conn
        n_ph = c.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
        n_sp = c.execute("SELECT COUNT(*) FROM spots").fetchone()[0]
        r = c.execute("SELECT COUNT(*), IFNULL(MAX(id),0), "
                      "CAST(IFNULL(SUM(CAST(confidence*1000 AS INT)),0) AS INT), "
                      "COUNT(DISTINCT species_code) FROM records").fetchone()
        return (n_ph, n_sp, r[0], r[1], r[2], r[3])

    def refresh(self):
        if self.current_code:
            if self._mode == "detail":
                # 同一详情重建(查看器关闭/库刷新): 记住当前tab位置再重建
                self._detail_scroll[self.detail_tab] = \
                    self.scroll.verticalScrollBar().value()
            self._show_detail(self.current_code, restore=True)
        else:
            # 数据无变化的切页回来: 不重建(秒开, 位置/状态天然保持)
            if (self._mode == "list"
                    and self.search.text().strip() == self._list_filter
                    and self._list_sig == self._data_sig()):
                return
            self._show_list()

    def _back(self):
        self.current_code = None
        self.back_btn.setVisible(False)
        self.search.setVisible(True)
        # 返回列表恢复进详情前的位置(2026-11-04用户: 每次都得从头拉)
        self._pending_scroll = self._list_scroll
        self._show_list()

    def _on_range_for_restore(self, _mn: int, _mx: int):
        self._restore_pending_scroll()

    def _restore_pending_scroll(self):
        pos = self._pending_scroll
        if pos <= 0:
            return
        bar = self.scroll.verticalScrollBar()
        if bar.maximum() <= 0:
            return   # 布局未就绪, 留着位置等rangeChanged再试
        try:
            bar.rangeChanged.disconnect(self._on_range_for_restore)
        except RuntimeError:
            pass
        self._pending_scroll = 0
        bar.setValue(min(pos, bar.maximum()))

    def _schedule_restore(self, pos: int):
        """重建后恢复滚动位置: singleShot(0)走常规路径, rangeChanged兜底
        (大列表重建时范围可能晚一轮才就绪, 早恢复会被钳回0)。"""
        if pos <= 0:
            return
        self._pending_scroll = pos
        self.scroll.verticalScrollBar().rangeChanged.connect(
            self._on_range_for_restore)
        QTimer.singleShot(0, self._restore_pending_scroll)

    def _show_list(self):
        self._cancel_thumb_job()
        search = self.search.text().strip()
        same_filter = (search == self._list_filter)
        if self._mode == "list" and same_filter:
            # 列表仍在前台的重建(切页回来/识别完成刷新): 保持滚动位置
            self._list_scroll = self.scroll.verticalScrollBar().value()
        elif not same_filter:
            self._list_scroll = 0   # 换了搜索词=新列表, 从头看
        self._mode = "list"
        self._list_filter = search
        while self.content_lay.count():
            it = self.content_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        search = self.search.text().strip()
        items = self.lib.species_overview(search)
        lifer = {li["code"]: li for li in self.lib.lifers()}
        year_codes = set(self.lib.year_bird_codes(
            __import__('datetime').date.today().strftime('%Y')))
        self.title.setText(t(f"鸟种库 · {len(items)} 种", f"Species · {len(items)}"))
        # 识别进行中提示(照片已导入但鸟种尚未生成, 用户会以为"库里没有")
        win = self.win
        if win.worker is not None and win.worker.isRunning():
            tip = QLabel(t("后台识别进行中——刚导入的照片识别完成后才会出现在这里，"
                           "不用等待，稍后再回来看即可。",
                           "Background recognition in progress — newly imported "
                           "photos appear here once recognized. No need to wait, "
                           "just check back later."))
            tip.setWordWrap(True)
            tip.setStyleSheet(f"font-size:13px;color:{theme.BLUE};"
                              f"background:{theme.CHIP_BG};border-radius:10px;"
                              "padding:8px 14px;")
            self.content_lay.addWidget(tip)
        unid_n = self.lib.unidentified_overview()["n"]
        if not items and not unid_n:
            empty = QLabel(t("还没有识别记录 · 先去「导入」页添加照片",
                             "No sightings yet · add photos on the Import page first"))
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"color:{theme.LABEL_2};font-size:15px;padding:60px;")
            self.content_lay.addWidget(empty)
            self._pending_scroll = 0
            return
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        cell = 0
        # 「未识别」伪种卡(2026-10-31 bug4: 识别完成但没写出鸟种的照片;
        # 展示在鸟种库但不计入种数——标题的"· N 种"来自species_overview,
        # 不含此项)。搜索鸟名时不显示。
        if not search:
            unid = self.lib.unidentified_overview()
            if unid["n"] > 0:
                grid.addWidget(self._unidentified_card(unid), 0, 0)
                cell = 1
        for i, sp in enumerate(items):
            grid.addWidget(self._species_card(sp, lifer.get(sp["code"]),
                                              sp["code"] in year_codes),
                           (cell + i) // CARD_COLS, (cell + i) % CARD_COLS)
        for c in range(CARD_COLS):
            grid.setColumnStretch(c, 1)
        self.content_lay.addWidget(grid_widget)
        self.content_lay.addStretch(1)
        self._schedule_restore(self._list_scroll)
        self._list_sig = self._data_sig()

    def _unidentified_card(self, unid: dict) -> QFrame:
        """「未识别」卡片: 封面灰底问号 + 张数; 点击进照片流(可逐张标注)。"""
        from ..db import Library
        card = QFrame()
        card.setObjectName("Card")
        card.setFixedWidth(190)
        v = QVBoxLayout(card)
        v.setContentsMargins(10, 10, 10, 12)
        v.setSpacing(4)
        cover = QLabel("?")
        cover.setFixedSize(COVER_W, COVER_H)
        cover.setAlignment(Qt.AlignCenter)
        cover.setStyleSheet(f"background:{theme.FILL};border-radius:10px;"
                            f"color:{theme.LABEL_3};font-size:64px;font-weight:800;")
        if unid["cover_photo_id"]:
            row = self.lib.conn.execute(
                "SELECT path, file_hash FROM photos WHERE id=?",
                (unid["cover_photo_id"],)).fetchone()
            if row:
                tp = ensure_thumbnail(self.lib.root, row["path"],
                                      row["file_hash"], COVER_W * 2)
                if tp:
                    pm = QPixmap(str(tp))
                    cover.setPixmap(pm.scaled(COVER_W, COVER_H,
                                              Qt.KeepAspectRatioByExpanding,
                                              Qt.SmoothTransformation))
                    cover.setText("")
        v.addWidget(cover)
        name = QLabel(t("未识别", "Unidentified"))
        name.setStyleSheet(f"font-size:15px;font-weight:700;color:{theme.LABEL};"
                           "background:transparent;")
        v.addWidget(name)
        meta = QLabel(t(f"{unid['n']} 张 · 不计入鸟种数",
                        f"{unid['n']} photos · not counted as species"))
        meta.setStyleSheet(f"font-size:12px;color:{theme.LABEL_2};background:transparent;")
        meta.setWordWrap(True)
        v.addWidget(meta)
        card.setCursor(Qt.PointingHandCursor)
        code = getattr(Library, "UNIDENTIFIED_CODE", "__unid__")
        card.mousePressEvent = lambda e: self._open_detail(code)
        return card

    def _species_card(self, sp: dict, li: dict | None, is_year: bool) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        card.setFixedWidth(190)
        v = QVBoxLayout(card)
        v.setContentsMargins(10, 10, 10, 12)
        v.setSpacing(4)
        cover = QLabel()
        cover.setFixedSize(COVER_W, COVER_H)
        cover.setAlignment(Qt.AlignCenter)
        cover.setStyleSheet(f"background:{theme.FILL};border-radius:10px;")
        if sp["cover_photo_id"]:
            row = self.lib.conn.execute(
                "SELECT path, file_hash FROM photos WHERE id=?",
                (sp["cover_photo_id"],)).fetchone()
            if row:
                tp = ensure_thumbnail(self.lib.root, row["path"], row["file_hash"], COVER_W * 2)
                if tp:
                    pm = QPixmap(str(tp))
                    cover.setPixmap(pm.scaled(COVER_W, COVER_H,
                                              Qt.KeepAspectRatioByExpanding,
                                              Qt.SmoothTransformation))
        v.addWidget(cover)
        badges = []
        if li:
            badges.append(f"👑#{li['lifer_no']}")
        if is_year:
            badges.append(t("🌿年鸟", "🌿 Year bird"))
        if badges:
            b = QLabel(" ".join(badges))
            b.setStyleSheet(f"font-size:12px;font-weight:700;color:{theme.OLIVE};"
                            "background:transparent;")
            v.addWidget(b)
        name = QLabel(sname(sp["cn"], sp["en"]))
        name.setStyleSheet(f"font-size:15px;font-weight:700;color:{theme.LABEL};"
                           "background:transparent;")
        name.setWordWrap(True)
        v.addWidget(name)
        meta_bits = [t(f"{sp['n']} 张", f"{sp['n']} photos")]
        if sp["iucn"]:
            meta_bits.append(t(IUCN_CN.get(sp["iucn"], sp["iucn"]),
                               IUCN_EN.get(sp["iucn"], sp["iucn"])))
        meta = QLabel("  ·  ".join(meta_bits))
        meta.setStyleSheet(f"font-size:12px;color:{theme.LABEL_2};background:transparent;")
        v.addWidget(meta)
        first = QLabel(t(f"首见 {(sp['first_at'] or '')[:10]}",
                         f"First seen {(sp['first_at'] or '')[:10]}"))
        first.setStyleSheet(f"font-size:12px;color:{theme.LABEL_3};background:transparent;")
        v.addWidget(first)
        card.setCursor(Qt.PointingHandCursor)
        card.mousePressEvent = lambda e, code=sp["code"]: self._open_detail(code)
        return card

    def _open_detail(self, code: str):
        if self._mode == "list":
            # 正在列表: 记住位置(时间线/地图跳转进来时列表不在前台, 不覆盖)
            self._list_scroll = self.scroll.verticalScrollBar().value()
        if code != self.current_code:
            # 换鸟种: 多选状态作废(残留选中会误伤下一个鸟种)
            self._sel_mode = False
            self._sel.clear()
        self.current_code = code
        self.back_btn.setVisible(True)
        self.search.setVisible(False)
        self._show_detail(code)

    def _show_unidentified_detail(self):
        """「未识别」详情: 照片流 + 说明(打开查看器可手工标注鸟种)。"""
        while self.content_lay.count():
            it = self.content_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        photos = self.lib.unidentified_photos()
        head = QFrame()
        head.setObjectName("Card")
        hv = QVBoxLayout(head)
        hv.setContentsMargins(20, 16, 20, 16)
        hv.setSpacing(6)
        t1 = QLabel(t("未识别", "Unidentified"))
        t1.setStyleSheet(f"font-size:22px;font-weight:800;color:{theme.LABEL};"
                         "background:transparent;")
        hv.addWidget(t1)
        t2 = QLabel(t(f"{len(photos)} 张 · 没有识别出鸟种的照片（没检测到鸟、"
                      "或置信度过低不写名，不计入鸟种统计）。低置信但给出了"
                      "鸟名的在「待复核」页把关；这里可点开照片手工标注，"
                      "或点「选择」整批标注。",
                      f"{len(photos)} photos · no bird could be named "
                      "(none detected, or confidence below the naming "
                      "threshold; not counted as species). Low-confidence "
                      "names are handled in \"Pending review\"; open a "
                      "photo to annotate it manually, or use \"Select\" "
                      "to annotate a batch."))
        t2.setWordWrap(True)
        t2.setStyleSheet(f"font-size:13px;color:{theme.LABEL_2};background:transparent;")
        hv.addWidget(t2)
        self.content_lay.addWidget(head)
        if not photos:
            empty = QLabel(t("没有未识别的照片", "No unidentified photos"))
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"color:{theme.LABEL_2};font-size:15px;padding:40px;")
            self.content_lay.addWidget(empty)
            self.content_lay.addStretch(1)
            return
        self._sel_pool = [p["photo_id"] for p in photos]
        self._sel_actions = [(t("标注鸟种…", "Annotate species…"),
                              self._batch_annotate)]
        self._render_sel_bar()
        from ..theme.widgets import PhotoGridItem, grid_tile_of
        tile = grid_tile_of(self.lib)       # 0.8.5网格档位
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 12)
        grid.setSpacing(10)
        cols = max(3, (self.width() - 80) // (tile + 10))
        ids = [p["photo_id"] for p in photos]
        for i, ph in enumerate(photos):
            row = self.lib.conn.execute(
                "SELECT path, file_hash FROM photos WHERE id=?",
                (ph["photo_id"],)).fetchone()
            pm = None
            if row:
                tsize = max(256, tile)
                tp = cached_thumbnail(self.lib.root, row["file_hash"], tsize) \
                    or (ensure_thumbnail(self.lib.root, row["path"],
                                         row["file_hash"], tsize)
                        if row["path"] else None)
                if tp:
                    pm = QPixmap(str(tp))
            item = PhotoGridItem(pm, label=self._cap_date_spot(ph),
                                 tile=tile)
            item.setCursor(Qt.PointingHandCursor)
            pid = ph["photo_id"]
            if self._sel_mode:
                # 多选: 点击=翻转选中, 不开查看器
                item.mousePressEvent = lambda e, p=pid, it=item: \
                    self._sel_click(p, it)
            else:
                item.mousePressEvent = lambda e, p=pid, i2=list(ids): \
                    self._open(p, i2)
            item.set_selected(pid in self._sel)
            grid.addWidget(item, i // cols, i % cols)
        grid.setColumnStretch(cols, 1)
        self.content_lay.addWidget(grid_widget)
        self.content_lay.addStretch(1)

    # ---------- 详情 ----------
    def _show_detail(self, code: str, restore: bool = False):
        self._mode = "detail"
        if not restore:
            self._pending_scroll = 0   # 新进的详情从顶部看
        from ..db import Library
        if code == getattr(Library, "UNIDENTIFIED_CODE", "__unid__"):
            self._show_unidentified_detail()
            return
        self._cancel_thumb_job()
        while self.content_lay.count():
            it = self.content_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        sp_info = self.lib.species_info(code)
        if not sp_info:
            return
        li = None
        for item in self.lib.lifers():
            if item["code"] == code:
                li = item
                break

        # 头部卡片
        head = QFrame()
        head.setObjectName("Card")
        hv = QVBoxLayout(head)
        hv.setContentsMargins(20, 16, 20, 16)
        hv.setSpacing(6)
        badges = []
        if li:
            badges.append(t(f"👑 生涯 #{li['lifer_no']}", f"👑 Lifer #{li['lifer_no']}"))
        if code in set(self.lib.year_bird_codes(
                __import__('datetime').date.today().strftime('%Y'))):
            badges.append(t("🌿 年鸟", "🌿 Year bird"))
        t1_text = sname(sp_info["cn"], sp_info["en"]) \
            + ("    " + "   ".join(badges) if badges else "")
        t1 = QLabel(t1_text)
        t1.setStyleSheet(f"font-size:22px;font-weight:800;color:{theme.LABEL};"
                         "background:transparent;")
        hv.addWidget(t1)
        iucn = sp_info["iucn"]
        iucn_txt = ("    IUCN " + t(IUCN_CN.get(iucn, iucn), IUCN_EN.get(iucn, iucn))
                    if iucn else "")
        t2 = QLabel(f"{sp_info['en']}  ·  {sp_info['sci']}{iucn_txt}"
                    + (f"    {sp_info['family_cn']}" if sp_info["family_cn"] else ""))
        t2.setStyleSheet(f"font-size:13px;color:{theme.LABEL_2};background:transparent;")
        t2.setWordWrap(True)
        hv.addWidget(t2)
        self.content_lay.addWidget(head)

        # 标签页(右挂网格档位, 0.8.5; 实测修: 标签页不吃stretch+中间加
        # 弹性分隔, 两组分段控件同行硬挤会视觉叠压)
        from ..theme.widgets import SegmentedControl, make_grid_tier_control
        seg = SegmentedControl([t("概览", "Overview"), t("图鉴", "Field guide"),
                                t("文化", "Culture")],
                               current=self.detail_tab)
        seg.changed.connect(self._tab_changed)
        tab_row = QHBoxLayout()
        tab_row.addWidget(seg)
        tab_row.addStretch(1)
        # 评分/选片筛选(1.0冲刺①+⑨): 概览网格内过滤, 状态跨鸟种保持
        from PySide6.QtWidgets import QComboBox
        if not hasattr(self, "sp_rating_filter"):
            self.sp_rating_filter = QComboBox()
            self.sp_rating_filter.addItems([
                t("评分: 全部", "Rating: all"), t("★1+", "★1+"), t("★2+", "★2+"),
                t("★3+", "★3+"), t("★4+", "★4+"), t("★5", "★5"),
                t("未评星", "Unrated")])
            self.sp_pick_filter = QComboBox()
            self.sp_pick_filter.addItems([
                t("选片: 全部", "Pick: all"), t("保留", "Keep"), t("待定", "Pending"),
                t("拒绝", "Reject"), t("未标", "Unmarked")])
            self.sp_rating_filter.currentIndexChanged.connect(
                lambda _: self._show_detail(code, restore=True))
            self.sp_pick_filter.currentIndexChanged.connect(
                lambda _: self._show_detail(code, restore=True))
            self.sp_rating_filter.setCursor(Qt.PointingHandCursor)
            self.sp_pick_filter.setCursor(Qt.PointingHandCursor)
            self.sp_rating_filter.setToolTip(t(
                "只显示达到星级的照片（作用于概览网格）",
                "Show only photos at or above the stars (overview grid)"))
            self.sp_pick_filter.setToolTip(t(
                "只显示所选选片状态的照片（作用于概览网格）",
                "Show only photos in the picked state (overview grid)"))
        tab_row.addWidget(self.sp_rating_filter)
        tab_row.addWidget(self.sp_pick_filter)
        tab_row.addWidget(make_grid_tier_control(
            self.lib, lambda: self._show_detail(code, restore=True)))
        # 宿主widget: 本页清理循环只deleteLater(it.widget()), 裸layout会整行
        # 漏删——旧档位控件以旧几何残留+新行叠加=重影(0.8.5实测)
        tab_host = QWidget()
        tab_host.setLayout(tab_row)
        self.content_lay.addWidget(tab_host)

        if self.detail_tab == 1:
            self._render_dex(code)
        elif self.detail_tab == 2:
            self._render_culture(code)
        else:
            self._render_overview(code, li)
        if restore:
            self._schedule_restore(self._detail_scroll.get(self.detail_tab, 0))

    # ---------- 照片流多选(概览/未识别共用) ----------
    def _render_sel_bar(self):
        """照片流顶部多选工具条: 非多选=右侧一个「选择」; 多选=计数+全选+
        动作按钮+完成。动作来自 self._sel_actions(渲染前设置)。"""
        bar = QHBoxLayout()
        bar.addStretch(1)
        self._sel_cnt_lbl = None
        self._sel_all_btn = None
        self._sel_act_btns = []
        if self._sel_mode:
            self._sel_cnt_lbl = QLabel(t(f"已选 {len(self._sel)} 张",
                                         f"{len(self._sel)} selected"))
            self._sel_cnt_lbl.setStyleSheet(
                f"font-size:14px;font-weight:700;color:{theme.BLUE};"
                "background:transparent;")
            bar.addWidget(self._sel_cnt_lbl)
            self._sel_all_btn = QPushButton(t("全选", "Select all"))
            self._sel_all_btn.setCursor(Qt.PointingHandCursor)
            self._sel_all_btn.clicked.connect(self._sel_toggle_all)
            bar.addWidget(self._sel_all_btn)
            for txt, cb in self._sel_actions:
                b = QPushButton(txt)
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(cb)
                bar.addWidget(b)
                self._sel_act_btns.append(b)
        done = QPushButton(t("完成", "Done") if self._sel_mode
                           else t("选择", "Select"))
        done.setObjectName("Primary")
        done.setCursor(Qt.PointingHandCursor)
        done.clicked.connect(self._toggle_sel)
        bar.addWidget(done)
        self.content_lay.addLayout(bar)
        self._sync_sel_bar()

    def _sync_sel_bar(self):
        n = len(self._sel)
        if not self._sel_mode or self._sel_cnt_lbl is None:
            return
        try:
            self._sel_cnt_lbl.setText(t(f"已选 {n} 张", f"{n} selected"))
            self._sel_all_btn.setText(
                t("全不选", "Deselect all") if n else t("全选", "Select all"))
            for b in self._sel_act_btns:
                b.setEnabled(n > 0)
        except RuntimeError:
            pass   # 重建间隙的僵尸控件忽略

    def _toggle_sel(self):
        self._sel_mode = not self._sel_mode
        self._sel.clear()
        self.refresh()

    def _sel_click(self, pid: int, item):
        # 就地翻转选中态, 不重建(重建会让快速连点落在已删除控件上)
        if pid in self._sel:
            self._sel.discard(pid)
        else:
            self._sel.add(pid)
        item.set_selected(pid in self._sel)
        self._sync_sel_bar()

    def _sel_toggle_all(self):
        if self._sel:
            self._sel.clear()
        else:
            self._sel |= set(self._sel_pool)
        self.refresh()

    def _batch_change_species(self):
        """多选批量改判: 选中照片从当前鸟种改到目标鸟种(写人工确认,
        AI原值不动)。典型场景: 同批同种被识别成两个种, 把错的一半挪过来。"""
        ids = sorted(self._sel)
        if not ids:
            return
        from .species_pick import SpeciesPickDialog
        dlg = SpeciesPickDialog(
            self.lib, t(f"改鸟种 · 已选 {len(ids)} 张",
                        f"Change species · {len(ids)} selected"), self)
        dlg.exec()
        code = dlg.selected_code
        if not code:
            return
        sp = self.lib.species_info(code)
        name = (sp["cn"] if sp else code)
        # 候选命中提示: 所选里多少张的top5本就包含目标种(改判更放心)
        n_hit = self._top5_hit(ids, code)
        msg = t(
            f"把所选 {len(ids)} 张照片的鸟种改为「{name}」？\n\n"
            "将写入人工确认标记（覆盖这些照片现有的人工确认状态）；"
            "AI识别原值保留，统计与鸟种库随即更新。\n\n"
            "一图多鸟的照片请到查看器里逐张处理。",
            f"Change the species of the {len(ids)} selected photos to "
            f"\"{sp['en'] if sp else code}\"?\n\nA manual confirmation is "
            "written (overriding any existing one); the AI's raw value is "
            "kept, and stats & the species library update at once.\n\n"
            "Photos showing several birds: handle them one by one in "
            "the viewer.")
        if n_hit:
            msg += "\n\n" + t(
                f"所选中有 {n_hit} 张的候选列表里本就包含目标鸟种（低风险改判）。",
                f"{n_hit} of them already had the target species among "
                "their candidates (low-risk correction).")
        r = QMessageBox.question(self, t("批量改鸟种", "Batch change species"),
                                 msg, QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        self.lib.set_species_batch(ids, code, from_code=self.current_code)
        self._sel.clear()
        self._sel_mode = False
        self.win.library_changed.emit()
        self.refresh()

    def _top5_hit(self, ids: list[int], code: str) -> int:
        """所选照片里生效鸟种=当前鸟种 且 top5候选含目标种的记录数。"""
        q = ",".join("?" * len(ids))
        n = 0
        for r in self.lib.conn.execute(
                f"SELECT species_code, confirmed_code, top5_json FROM records "
                f"WHERE photo_id IN ({q})", ids).fetchall():
            if (r["confirmed_code"] or r["species_code"]) != self.current_code:
                continue
            try:
                top5 = json.loads(r["top5_json"] or "[]")
            except Exception:
                top5 = []
            if any(c.get("code") == code for c in top5):
                n += 1
        return n

    def _batch_share_cards(self):
        """多选批量出分享卡: 所选照片逐张一张(0.8.4)。"""
        ids = sorted(self._sel)
        if not ids:
            return
        from .batch_share_dialog import BatchShareDialog
        dlg = BatchShareDialog(self.lib, self.win, photo_ids=ids)
        dlg.exec()

    def _batch_annotate(self):
        """未识别照片流多选: 整批手工标注同一个鸟种(无记录照片专用)。"""
        ids = sorted(self._sel)
        if not ids:
            return
        from .species_pick import SpeciesPickDialog
        dlg = SpeciesPickDialog(
            self.lib, t(f"标注鸟种 · 已选 {len(ids)} 张",
                        f"Annotate species · {len(ids)} selected"), self)
        dlg.exec()
        code = dlg.selected_code
        if not code:
            return
        sp = self.lib.species_info(code)
        name = (sp["cn"] if sp else code)
        r = QMessageBox.question(
            self, t("批量标注鸟种", "Batch annotate species"),
            t(f"把所选 {len(ids)} 张未识别照片手工标注为「{name}」？\n\n"
              "标注后计入鸟种统计；之后可在查看器里删除该条标注。",
              f"Manually annotate the {len(ids)} selected unidentified "
              f"photos as \"{sp['en'] if sp else code}\"?\n\nThey will "
              "count toward species stats; the annotation can be removed "
              "later in the viewer."),
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        for pid in ids:
            self.lib.add_manual_record(pid, code)
        self._sel.clear()
        self._sel_mode = False
        self.win.library_changed.emit()
        self.refresh()

    def _apply_sp_filters(self, photos: list[dict]) -> list[dict]:
        """鸟种概览的评分/选片过滤(1.0冲刺①+⑨); 筛选在下拉上, 状态跨鸟种保持。"""
        out = photos
        if getattr(self, "sp_rating_filter", None) and \
                self.sp_rating_filter.currentIndex():
            i = self.sp_rating_filter.currentIndex()
            if i == 6:      # 未评星
                out = [p for p in out if not (p.get("rating") or 0)]
            else:           # ★i+
                out = [p for p in out if (p.get("rating") or 0) >= i]
        if getattr(self, "sp_pick_filter", None) and \
                self.sp_pick_filter.currentIndex():
            i = self.sp_pick_filter.currentIndex()
            if i == 4:      # 未标
                out = [p for p in out if not (p.get("pick") or "")]
            else:
                out = [p for p in out if
                       (p.get("pick") or "") == ("keep", "pending", "reject")[i - 1]]
        return out

    def _render_overview(self, code: str, li):
        photos = self._apply_sp_filters(self.lib.photos_of_species(code))
        # 多选模式下不折叠连拍: 每张都要能单独选中(同时间线的约定)
        if not self._sel_mode and \
                self.lib.get_setting("burst_collapse", "1") == "1":
            # 连拍折叠(0.8-③): 组内美学最高者为封面, 最美照必是封面不会被藏
            from ..core.burst import collapse_bursts
            photos = collapse_bursts(photos, id_key="photo_id")
        self._sel_pool = [p["photo_id"] for p in photos]
        self._sel_actions = [(t("改鸟种…", "Change species…"),
                              self._batch_change_species),
                             (t("分享卡…", "Share cards…"),
                              self._batch_share_cards)]
        if photos:
            self._render_sel_bar()
        if not photos:
            tip = QLabel(t("库里还没有这个物种的照片 · 去导入页添加后识别即可",
                           "No photos of this species yet · import some and "
                           "they will be recognized"))
            tip.setAlignment(Qt.AlignCenter)
            tip.setStyleSheet(f"color:{theme.LABEL_2};font-size:14px;padding:40px;")
            self.content_lay.addWidget(tip)
            return
        scored = [p for p in photos if p.get("aesthetic") is not None]
        if scored:
            hint = QLabel(t("✨ 按AI美学评分排序 · 最美的在前（用于封面与年度十八图）",
                           "✨ Sorted by AI aesthetic score · best first "
                           "(used for the cover and the year's top 18)"))
            hint.setObjectName("Hint")
            self.content_lay.addWidget(hint)
        from ..theme.widgets import PhotoGridItem, grid_tile_of
        tile = grid_tile_of(self.lib)       # 0.8.5网格档位
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 12)
        grid.setSpacing(10)
        cols = max(3, (self.width() - 80) // (tile + 10))
        ids = [p["photo_id"] for p in photos]
        gen = self._thumb_gen
        stop = self._thumb_stop = {}     # 新任务的新中断标记
        pending = []                     # 缓存缺失, 交后台补齐
        best_pid = scored[0]["photo_id"] if scored else None
        for i, ph in enumerate(photos):
            row = self.lib.conn.execute(
                "SELECT path, file_hash FROM photos WHERE id=?",
                (ph["photo_id"],)).fetchone()
            pm = None
            if row:
                tp = cached_thumbnail(self.lib.root, row["file_hash"],
                                      max(256, tile))
                if tp:
                    pm = QPixmap(str(tp))
            corner = t("★最美", "★ Best") if (ph["photo_id"] == best_pid
                                              and len(photos) > 1) else None
            item = PhotoGridItem(pm, label=self._cap_date_spot(ph),
                                 corner=corner, stack=ph.get("group_n", 0),
                                 tile=tile, stars=ph.get("rating", 0),
                                 pick=ph.get("pick", ""))
            item.setCursor(Qt.PointingHandCursor)
            pid = ph["photo_id"]
            if self._sel_mode:
                # 多选: 点击=翻转选中, 不开查看器
                item.mousePressEvent = lambda e, p=pid, it=item: \
                    self._sel_click(p, it)
            else:
                item.mousePressEvent = lambda e, p=pid, i2=list(
                    ph.get("group_ids") or ids): self._open(p, i2)
            item.set_selected(pid in self._sel)
            grid.addWidget(item, i // cols, i % cols)
            if pm is None and row and row["path"]:
                self._thumb_items[row["file_hash"]] = item
                pending.append((row["path"], row["file_hash"]))
        grid.setColumnStretch(cols, 1)
        self.content_lay.addWidget(grid_widget)
        self.content_lay.addStretch(1)
        if pending:   # 图多首开不再同步等全部缩略图: 先占位, 后台补齐逐张点亮
            QThreadPool.globalInstance().start(
                _ThumbJob(self.lib.root, gen, pending, self._thumb_sig, stop))

    def _thumb_ready(self, gen: int, fhash: str, tp: str):
        if gen != self._thumb_gen:
            return
        item = self._thumb_items.pop(fhash, None)
        if item is None:
            return
        pm = QPixmap(tp)
        if not pm.isNull():
            try:
                item.set_pixmap(pm)
            except RuntimeError:   # 控件已随页面重建销毁
                pass

    def _render_dex(self, code: str):
        sp_info = self.lib.species_info(code)
        dex = get_dex().detail(sp_info["sci"])
        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)
        v.setContentsMargins(20, 16, 20, 18)
        v.setSpacing(12)

        hint = get_hint()

        # 顶部: 我的最美照片 + 地区/罕见度徽章
        photos = self.lib.photos_of_species(code)
        # 地区徽章/分布表按**该鸟种照片的实际拍摄地区**(最美照优先),
        # 不是全局默认地区——此前用default_region, 最后一批导入安徽后
        # 所有物种都显示安徽(2026-11-05用户反馈), 而首批照片是上海
        region_id = self._species_region(photos)
        top = QHBoxLayout()
        top.setSpacing(18)
        if photos:
            top.addWidget(self._best_photo_widget(photos))
        badges = self._dex_badges(hint, code, region_id,
                                  sp_info["in_classifier"])
        if badges:
            bl = QHBoxLayout()
            bl.setSpacing(8)
            for b in badges:
                bl.addWidget(b)
            bl.addStretch(1)
            bl.setAlignment(Qt.AlignTop)
            top.addLayout(bl, 1)
        if top.count():
            v.addLayout(top)

        # 地区分布表
        heat = self._heat_card(hint, code, region_id)
        if heat is not None:
            v.addWidget(heat)

        if dex:
            for key, zh_label, en_label in DEX_FIELDS:
                zh = dex[key]["zh"]
                if not zh:
                    continue
                text = zh.replace("\n- ", "\n• ").replace("- ", "• ", 1) \
                    if zh.startswith("- ") else zh.replace("\n- ", "\n• ")
                v.addWidget(_info_row(t(zh_label, en_label),
                                      text.replace("\n", "<br>")))
        else:
            none_tip = QLabel(t("暂无图鉴条目", "No field-guide entry yet"))
            none_tip.setObjectName("Hint")
            v.addWidget(none_tip)
        self.content_lay.addWidget(card)
        self.content_lay.addStretch(1)

    @staticmethod
    def _cap_date_spot(ph: dict) -> str:
        """缩略图说明=日期·鸟点(0.8.6用户: 与鸟点详情的时间+鸟种对偶)。"""
        parts = [(ph.get("taken_at") or "")[:10]]
        spot = ph.get("spot_short") or ph.get("spot_name") or ""
        if spot:
            parts.append(spot)
        return " · ".join(p for p in parts if p)

    def _best_photo_widget(self, photos: list[dict]) -> QWidget:
        """图鉴页顶部「我的最美照片」: 美学评分最高一张, 点击进查看器。"""
        from ..theme.widgets import PhotoGridItem
        box = QWidget()
        bv = QVBoxLayout(box)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(6)
        cap = QLabel(t("我的最美照片", "My best photo"))
        cap.setStyleSheet(f"color:{theme.LABEL_2};font-size:12px;font-weight:700;"
                          "background:transparent;")
        bv.addWidget(cap)
        best = photos[0]   # photos_of_species已按美学评分降序
        ids = [p["photo_id"] for p in photos]
        row = self.lib.conn.execute(
            "SELECT path, file_hash FROM photos WHERE id=?",
            (best["photo_id"],)).fetchone()
        pm = None
        if row:
            tp = cached_thumbnail(self.lib.root, row["file_hash"], 256)
            if not tp:
                # 导入只生成512px缓存, 256未命中时从更大缓存降采样一张(毫秒级)
                tp = ensure_thumbnail(self.lib.root, row["path"],
                                      row["file_hash"], 256)
            if tp:
                pm = QPixmap(str(tp))
        item = PhotoGridItem(pm, label=self._cap_date_spot(best),
                             corner=t("★最美", "★ Best"))
        item.setCursor(Qt.PointingHandCursor)
        item.mousePressEvent = lambda e, pid=best["photo_id"], i2=list(ids): \
            self._open(pid, i2)
        bv.addWidget(item)
        return box

    def _species_region(self, photos: list[dict]) -> str:
        """该物种照片的实际拍摄地区(2026-11-05用户反馈: 图鉴曾把最后
        一次导入的地区安到所有物种头上)。

        优先=最美照所属批次的地区(非GLOBAL); 否则该物种最近一张照片的
        地区; 都没有才退回全局默认地区(default_region)。"""
        if photos:
            row = self.lib.conn.execute(
                "SELECT b.region_id FROM photos p "
                "JOIN batches b ON b.id=p.batch_id WHERE p.id=?",
                (photos[0]["photo_id"],)).fetchone()
            if row and row["region_id"] not in (None, "", "GLOBAL"):
                return row["region_id"]
        row = self.lib.conn.execute(
            "SELECT b.region_id FROM v_records v "
            "JOIN photos p ON p.id=v.photo_id "
            "JOIN batches b ON b.id=p.batch_id "
            "WHERE v.eff_code=? AND b.region_id IS NOT NULL "
            "  AND b.region_id NOT IN ('', 'GLOBAL') "
            "ORDER BY v.taken_at DESC LIMIT 1",
            (self.current_code,)).fetchone()
        if row:
            return row["region_id"]
        return self.lib.get_setting("default_region", "GLOBAL")

    def _dex_badges(self, hint, code: str, region_id: str,
                    in_classifier) -> list[QLabel]:
        pills = []
        if region_id not in ("GLOBAL", ""):
            mt = hint.region_tier(code, region_id)
            if mt:
                reg = regions.region_display(region_id)
                tier = tier_display(mt)
                pills.append(_pill(
                    t(f"📍 {reg}：{tier}", f"📍 {reg}: {tier}"),
                    theme.FILL, theme.LABEL_2))
            rt = hint.rarity_tier(code, region_id)
            if rt:
                shown = tier_display(rt)
                bg, fg = theme.FILL, theme.LABEL_2
                for tiers, colors in RARITY_PILL.items():
                    if rt in tiers:  # i18n:ok
                        bg, fg = colors
                pills.append(_pill(
                    t(f"🎯 罕见度·{shown}", f"🎯 Rarity · {shown}"), bg, fg))
        if not in_classifier:
            pills.append(_pill(
                t("ℹ️ 该物种不在AI识别范围(图鉴-only)",
                  "ℹ️ Not covered by AI recognition (field-guide only)"),
                theme.FILL, theme.LABEL_2))
        return pills

    def _heat_card(self, hint, code: str, region_id: str | None):
        """地区分布卡片; 物种无任何分布数据时返回None。"""
        try:
            peaks = {rid: v for rid, v in hint.region_peaks(code).items()
                     if v > -1.49}
        except Exception:
            return None
        if not peaks:
            return None
        parents = hint.gp.region_parents()
        rows, hidden = _heat_rows(peaks, parents, region_id)
        return _HeatTable(rows, peaks, hidden, region_id,
                          self._open_distribution_map,
                          self._open_migration_map)

    def _open_migration_map(self):
        # 局部import: WebEngine(194MB DLL)只在用户点击迁徙地图后才拉起
        from PySide6.QtWidgets import QMessageBox
        from .migration_view import MigrationMapDialog
        # 非模态独立窗口: 已开着就切鸟种复用, 不重复开窗(下载慢, 用户
        # 要边等边用其他功能)
        existing = getattr(self, "_mig_dlg", None)
        if existing is not None and existing.isVisible():
            existing.switch_species(self.current_code)
            existing.raise_()
            existing.activateWindow()
            return
        try:
            dlg = MigrationMapDialog(self.lib, self.win, self.current_code,
                                     parent=self)
        except FileNotFoundError as e:   # git源码库缺maplibre等资产
            QMessageBox.warning(self, t("迁徙地图", "Migration map"), str(e))
            return
        self._mig_dlg = dlg
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.destroyed.connect(lambda: setattr(self, "_mig_dlg", None))
        dlg.show()

    def _open_distribution_map(self):
        # 局部import: WebEngine(194MB DLL)只在用户点击分布地图后才拉起
        from PySide6.QtWidgets import QMessageBox
        from .distribution_map import DistributionMapDialog
        try:
            dlg = DistributionMapDialog(self.lib, self.win, self.current_code,
                                        parent=self)
        except FileNotFoundError as e:   # git源码库缺省界GeoJSON等资产
            QMessageBox.warning(self, t("分布地图", "Distribution map"), str(e))
            return
        dlg.exec()

    def _render_culture(self, code: str):
        stories = get_culture().stories_for(code)
        assocs = get_culture().display_associations(code)
        if not stories and not assocs:
            empty = QLabel(t("暂无文化故事 · 文化库覆盖约 965 个物种",
                             "No culture stories yet · the culture library "
                             "covers about 965 species"))
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"color:{theme.LABEL_3};font-size:14px;padding:40px;")
            self.content_lay.addWidget(empty)
            return
        for a in assocs:
            if a.get("label"):
                txt = f"📌 {a['label']}"
                if a.get("caveat"):
                    txt += f"　<span style='color:{theme.LABEL_3}'>{a['caveat']}</span>"
                lab = QLabel(txt)
                lab.setTextFormat(Qt.RichText)
                lab.setWordWrap(True)
                lab.setStyleSheet(f"color:{theme.OLIVE};font-size:13px;background:transparent;"
                                  "padding:2px 4px;")
                self.content_lay.addWidget(lab)
        for s in stories:
            card = QFrame()
            card.setObjectName("Card")
            v = QVBoxLayout(card)
            v.setContentsMargins(20, 16, 20, 18)
            v.setSpacing(8)
            if s["categories"]:
                cat = QLabel(" · ".join(s["categories"]))
                cat.setStyleSheet(f"color:{theme.OLIVE};font-size:12px;font-weight:700;"
                                  "background:transparent;")
                v.addWidget(cat)
            title = QLabel(s["title"] or "")
            title.setStyleSheet(f"font-size:17px;font-weight:800;color:{theme.LABEL};"
                                "background:transparent;")
            title.setWordWrap(True)
            v.addWidget(title)
            if s["subtitle"]:
                sub = QLabel(s["subtitle"])
                sub.setStyleSheet(f"font-size:13px;color:{theme.LABEL_2};background:transparent;")
                sub.setWordWrap(True)
                v.addWidget(sub)
            body = QLabel(s["body"].replace("\n", "<br>"))
            body.setWordWrap(True)
            body.setTextFormat(Qt.RichText)
            body.setStyleSheet(f"color:{theme.LABEL_2};font-size:14px;line-height:150%;"
                               "background:transparent;")
            v.addWidget(body)
            foot_bits = []
            if s["disputed"]:
                foot_bits.append(t("⚠️ 真实性存争议", "⚠️ Authenticity disputed"))
            elif s["confidence"] == "veryHigh":
                foot_bits.append(t("证据：非常充分", "Evidence: very strong"))
            if s["sources"]:
                foot_bits.append(t("来源：" + "、".join(s["sources"][:3])
                                   + ("…" if len(s["sources"]) > 3 else ""),
                                   "Sources: " + ", ".join(s["sources"][:3])
                                   + ("…" if len(s["sources"]) > 3 else "")))
            if foot_bits:
                foot = QLabel(t("　", "   ").join(foot_bits))
                foot.setWordWrap(True)
                foot.setStyleSheet(f"font-size:11px;color:{theme.LABEL_3};background:transparent;")
                v.addWidget(foot)
            self.content_lay.addWidget(card)
        self.content_lay.addStretch(1)

    def _tab_changed(self, idx: int):
        if self._mode == "detail" and self.current_code:
            # 离开当前tab前记住其滚动位置, 切回来时恢复
            self._detail_scroll[self.detail_tab] = \
                self.scroll.verticalScrollBar().value()
        self.detail_tab = idx
        if self.current_code:
            self._show_detail(self.current_code, restore=True)

    def _open(self, photo_id: int, ids: list[int]):
        dlg = PhotoViewer(self.lib, self.win, photo_id, ids)
        dlg.exec()
        self.refresh()
