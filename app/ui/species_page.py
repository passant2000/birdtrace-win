# -*- coding: utf-8 -*-
"""鸟种库: 卡片流(首见时间排序) + 搜索 + 鸟种详情(概览/图鉴/文化标签页)。"""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from ..core import regions
from ..core.birddex import get_dex
from ..core.culture import get_culture
from ..core.prior_hint import get_hint, tier_display
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
    val.setStyleSheet("color:#1C1C1E;font-size:13px;background:transparent;")
    h.addWidget(lab)
    h.addWidget(val, 1)
    return w


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
            tp = ensure_thumbnail(self._root, path, fhash, 256)
            if tp:
                self._sig.ready.emit(self._gen, fhash, str(tp))


class SpeciesPage(QWidget):
    def __init__(self, lib, win):
        super().__init__()
        self.lib = lib
        self.win = win
        self.current_code = None
        self.detail_tab = 0
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
    def _cancel_thumb_job(self):
        self._thumb_gen += 1
        self._thumb_stop["stop"] = True   # 原地标记, 在跑的任务读到即退出
        self._thumb_items = {}

    def refresh(self):
        if self.current_code:
            self._show_detail(self.current_code)
        else:
            self._show_list()

    def _back(self):
        self.current_code = None
        self.back_btn.setVisible(False)
        self.search.setVisible(True)
        self._show_list()

    def _show_list(self):
        self._cancel_thumb_job()
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
        if not items:
            empty = QLabel(t("还没有识别记录 · 先去「导入」页添加照片",
                             "No sightings yet · add photos on the Import page first"))
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"color:{theme.LABEL_2};font-size:15px;padding:60px;")
            self.content_lay.addWidget(empty)
            return
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        for i, sp in enumerate(items):
            grid.addWidget(self._species_card(sp, lifer.get(sp["code"]),
                                              sp["code"] in year_codes),
                           i // CARD_COLS, i % CARD_COLS)
        for c in range(CARD_COLS):
            grid.setColumnStretch(c, 1)
        self.content_lay.addWidget(grid_widget)
        self.content_lay.addStretch(1)

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
            b.setStyleSheet("font-size:12px;font-weight:700;color:#8A9455;"
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
        self.current_code = code
        self.back_btn.setVisible(True)
        self.search.setVisible(False)
        self._show_detail(code)

    # ---------- 详情 ----------
    def _show_detail(self, code: str):
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

        # 标签页
        from ..theme.widgets import SegmentedControl
        seg = SegmentedControl([t("概览", "Overview"), t("图鉴", "Field guide"),
                                t("文化", "Culture")],
                               current=self.detail_tab)
        seg.changed.connect(self._tab_changed)
        self.content_lay.addWidget(seg)

        if self.detail_tab == 1:
            self._render_dex(code)
        elif self.detail_tab == 2:
            self._render_culture(code)
        else:
            self._render_overview(code, li)

    def _render_overview(self, code: str, li):
        photos = self.lib.photos_of_species(code)
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
        from ..theme.widgets import PhotoGridItem
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 12)
        grid.setSpacing(10)
        cols = max(4, (self.width() - 80) // 140)
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
                tp = cached_thumbnail(self.lib.root, row["file_hash"], 256)
                if tp:
                    pm = QPixmap(str(tp))
            corner = t("★最美", "★ Best") if (ph["photo_id"] == best_pid
                                              and len(photos) > 1) else None
            item = PhotoGridItem(pm, label=(ph["taken_at"] or "")[:10],
                                 corner=corner)
            item.setFixedSize(132, 150)
            item.setCursor(Qt.PointingHandCursor)
            item.mousePressEvent = lambda e, pid=ph["photo_id"], i2=list(ids): self._open(pid, i2)
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

        # 当月出现提示 + 罕见度
        region_id = self.lib.get_setting("default_region", "GLOBAL")
        month = __import__('datetime').date.today().month
        hint = get_hint()
        chips = []
        if region_id not in ("GLOBAL", ""):
            mt = hint.monthly_tier(code, region_id, month)
            if mt:
                chips.append(t(f"📍 本月·{regions.region_display(region_id)}：{mt}",
                               f"📍 This month · {regions.region_display(region_id)}: {mt}"))
            rt = hint.rarity_tier(code, region_id)
            if rt:
                chips.append(t(f"🎯 罕见度：{rt}", f"🎯 Rarity: {rt}"))
        if not sp_info["in_classifier"]:
            chips.append(t("ℹ️ 该物种不在AI识别范围(图鉴-only)",
                           "ℹ️ Not covered by AI recognition (field-guide only)"))
        if chips:
            chip_row = QLabel("    ".join(chips))
            chip_row.setWordWrap(True)
            chip_row.setStyleSheet("color:#8A9455;font-size:13px;font-weight:600;"
                                   "background:transparent;")
            v.addWidget(chip_row)

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
                    txt += f"　<span style='color:#AEAEB2'>{a['caveat']}</span>"
                lab = QLabel(txt)
                lab.setTextFormat(Qt.RichText)
                lab.setWordWrap(True)
                lab.setStyleSheet("color:#8A9455;font-size:13px;background:transparent;"
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
                cat.setStyleSheet("color:#8A9455;font-size:12px;font-weight:700;"
                                  "background:transparent;")
                v.addWidget(cat)
            title = QLabel(s["title"] or "")
            title.setStyleSheet("font-size:17px;font-weight:800;color:#1C1C1E;"
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
            body.setStyleSheet("color:#3A3A32;font-size:14px;line-height:150%;"
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
        self.detail_tab = idx
        if self.current_code:
            self._show_detail(self.current_code)

    def _open(self, photo_id: int, ids: list[int]):
        dlg = PhotoViewer(self.lib, self.win, photo_id, ids)
        dlg.exec()
        self.refresh()
