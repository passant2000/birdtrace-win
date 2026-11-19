# -*- coding: utf-8 -*-
"""首页(UI重设计c7, Phase 2): 默认启动页——每日一鸟横幅(自时间线搬入) +
最近导入 + 快速入口 + 档案速览 + 「1.0 新功能导览」卡(直击"功能太隐蔽"
实测反馈: 关闭后写库 seen_tour=1, 不再显示)。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from .. import theme
from ..i18n import t, sname
from ..media import cached_thumbnail, ensure_thumbnail

# 1.0 新功能导览(UI重设计): (emoji, 名称(中,英对), 说明(中,英对), 跳转key)
# 双语规范第3条: 模块级常量存元组, 显示时 t(*pair) 求值——不存已翻译串
TOUR_ITEMS = [
    ("🗂️", ("选片工作流", "Culling workflow"),
     ("时间线 → 选择 → 打星/保留/拒绝，隔离区可恢复，连拍封面右键组内对比",
      "Timeline → Select → star/keep/reject; quarantine is recoverable; "
      "right-click a burst cover to compare"), "timeline"),
    ("🔍", ("增量重识别", "Incremental re-identify"),
     ("选择模式下「重新识别…」可选只跑未识别/待复核，人工确认永不覆盖",
      "Select mode → Re-identify can run only on unidentified/pending; "
      "manual verdicts are never overwritten"), "timeline"),
    ("👀", ("视觉查重", "Visual duplicates"),
     ("时间线顶部「查重…」找重复/相似照片，逐组确认才移除",
      "Timeline → Find duplicates: review each group before removing"),
      "timeline"),
    ("📤", ("记录中心导出", "Bird report export"),
     ("「记录中心…」导出 birdreport.cn 上报 CSV + 每鸟种最美照归集",
      "Bird report exports CSV rows plus one best photo per species"),
      "timeline"),
    ("🧰", ("组合筛选", "Combined filters"),
     ("时间线第二行：评分×选片×标签×作品集×鸟点×置信度 多维叠加过滤视图",
      "Timeline's second row stacks rating×pick×tag×collection×spot×"
      "confidence view filters"), "timeline"),
    ("🏷️", ("标签 & 作品集", "Tags & collections"),
     ("多选「标记…」打标签、「加入作品集…」；档案组「作品集」页可浏览/导出",
      "Select mode: Mark for tags, Add to collection; browse them on the "
      "Collections page"), "collections"),
    ("📈", ("观鸟生涯", "Birding life"),
     ("新种收录流/足迹地图/徽章/装备榜都在「观鸟生涯」页（原成就页并入）",
      "Life list stream, footprint map, badges and gear live on the "
      "Birding life page (former Achievements)"), "life"),
    ("🌐", ("静态站", "Static site"),
     ("时间线顶部「工具 ▾」→「静态站…」一键生成可部署的个人图库站",
      "Timeline → Tools ▾ → Static site builds a deployable gallery site"),
      "timeline"),
    ("©️", ("版权三态", "Copyright tri-state"),
     ("设置页设库级默认；查看器右栏「版权…」按照片覆盖/置空",
      "Set library defaults in Settings; the viewer's Copyright… "
      "overrides per photo"), None),
    ("🗄️", ("RAW/DNG 成对", "RAW/DNG pairs"),
     ("导入时同名 RAW/DNG 自动挂在 JPG 附属，识别只跑一次",
      "Same-name RAW/DNG files attach to the JPG on import; recognition "
      "runs once"), None),
    ("📡", ("增量扫描", "Incremental scan"),
     ("导入页登记常用目录 → 「扫描增量」只导新照片/发现移动改名",
      "Register folders on the Import page → Scan for new/renamed files"),
      "import"),
]


def daily_bird_card(lib, win) -> QFrame | None:
    """每日一鸟横幅(自 timeline_page._daily_bird_banner 搬家): 文化库
    确定性轮换, 点击跳转物种详情。"""
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
    sp = lib.species_info(code)
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
    cov_row = lib.conn.execute(
        """SELECT p.path, p.file_hash FROM photos p
           WHERE p.id = (SELECT v2.photo_id FROM v_records v2
                          WHERE v2.eff_code=? ORDER BY v2.taken_at ASC LIMIT 1)""",
        (code,)).fetchone()
    if cov_row:
        tp = ensure_thumbnail(lib.root, cov_row["path"], cov_row["file_hash"], 180)
        if tp:
            pm = QPixmap(str(tp))
            cover.setPixmap(pm.scaled(84, 84, Qt.KeepAspectRatioByExpanding,
                                      Qt.SmoothTransformation))
    else:
        cover.setText("🐦")
        cover.setStyleSheet(f"font-size:34px;background:{theme.FILL};"
                            "border-radius:12px;")
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
        line.setStyleSheet(f"font-size:12px;color:{theme.LABEL_2};"
                           "background:transparent;")
        line.setWordWrap(True)
        info.addWidget(line)
    else:
        sci = QLabel(sp["sci"])
        sci.setStyleSheet(f"font-size:12px;color:{theme.LABEL_2};"
                          "background:transparent;")
        info.addWidget(sci)
    h.addLayout(info, 1)

    go = QLabel(t("查看 ›", "View ›"))
    go.setStyleSheet(f"color:{theme.BLUE};font-size:14px;font-weight:600;"
                     "background:transparent;")
    h.addWidget(go)
    card.mousePressEvent = lambda e: win.open_species(code)
    return card


class HomePage(QWidget):
    def __init__(self, lib, win):
        super().__init__()
        self.lib = lib
        self.win = win
        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        from ..theme.widgets import PageHeader
        head = QHBoxLayout()
        self.title = PageHeader(t("首页", "Home"))
        head.addWidget(self.title, 1)
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

    def on_page_hidden(self):
        pass

    # ---------- 数据 ----------
    def refresh(self):
        while self.content_lay.count():
            it = self.content_lay.takeAt(0)
            w = it.widget() if it else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._tour_card()
        self._daily_card()
        self._recent_card()
        self._quick_card()
        self._archive_row()
        self.content_lay.addStretch(1)

    # ---------- 新功能导览 ----------
    def _tour_card(self):
        if self.lib.get_setting("seen_tour", "") == "1":
            return
        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)
        v.setContentsMargins(18, 14, 18, 16)
        v.setSpacing(8)
        head = QHBoxLayout()
        hl = QLabel(t("🎉 1.0 新功能导览", "🎉 What's new in 1.0"))
        hl.setObjectName("CardTitle")
        head.addWidget(hl)
        head.addStretch(1)
        close = QPushButton(t("知道了，不再显示", "Got it"))
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(lambda: (
            self.lib.set_setting("seen_tour", "1"),
            card.setVisible(False)))
        head.addWidget(close)
        v.addLayout(head)
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        cols = 2
        for i, (em, name_pair, desc_pair, key) in enumerate(TOUR_ITEMS):
            item = QLabel(
                f"<b style='color:{theme.LABEL}'>{em} {t(*name_pair)}</b>　"
                f"<span style='color:{theme.LABEL_2}'>{t(*desc_pair)}</span>")
            item.setWordWrap(True)
            item.setStyleSheet("background:transparent;font-size:13px;")
            if key:
                item.setCursor(Qt.PointingHandCursor)
                item.mousePressEvent = lambda e, k=key: self.win.switch_to(k)
            grid.addWidget(item, i // cols, i % cols)
        v.addWidget(grid_host)
        self.content_lay.addWidget(card)

    # ---------- 每日一鸟 ----------
    def _daily_card(self):
        card = daily_bird_card(self.lib, self.win)
        if card is not None:
            self.content_lay.addWidget(card)

    # ---------- 最近导入 ----------
    def _recent_card(self):
        row = self.lib.conn.execute(
            "SELECT id, created_at FROM batches ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return
        phs = self.lib.conn.execute(
            "SELECT p.id, p.path FROM photos p WHERE p.batch_id=? "
            "ORDER BY p.id DESC LIMIT 8", (row["id"],)).fetchall()
        if not phs:
            return
        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)
        v.setContentsMargins(18, 14, 18, 16)
        v.setSpacing(10)
        head = QHBoxLayout()
        hl = QLabel(t("最近导入", "Recent imports"))
        hl.setObjectName("CardTitle")
        head.addWidget(hl)
        head.addStretch(1)
        cnt = self.lib.conn.execute(
            "SELECT COUNT(*) c FROM photos WHERE batch_id=?",
            (row["id"],)).fetchone()["c"]
        when = (row["created_at"] or "")[:16]
        info = QLabel(t(f"{cnt} 张 · {when}", f"{cnt} photos · {when}"))
        info.setObjectName("Hint")
        head.addWidget(info)
        seeall = QPushButton(t("查看全部 ›", "See all ›"))
        seeall.setCursor(Qt.PointingHandCursor)
        seeall.clicked.connect(lambda: self.win.switch_to("timeline"))
        head.addWidget(seeall)
        v.addLayout(head)
        thumbs = QHBoxLayout()
        thumbs.setSpacing(8)
        ids = []
        for ph in phs:
            box = QLabel()
            box.setFixedSize(96, 72)
            box.setAlignment(Qt.AlignCenter)
            box.setCursor(Qt.PointingHandCursor)
            box.setStyleSheet(f"background:{theme.FILL};border-radius:8px;")
            r = self.lib.conn.execute(
                "SELECT file_hash FROM photos WHERE id=?", (ph["id"],)).fetchone()
            if r and ph["path"]:
                tp = cached_thumbnail(self.lib.root, r["file_hash"], 192) \
                    or ensure_thumbnail(self.lib.root, ph["path"],
                                        r["file_hash"], 192)
                if tp:
                    pm = QPixmap(str(tp))
                    if not pm.isNull():
                        box.setPixmap(pm.scaled(
                            box.size(), Qt.KeepAspectRatioByExpanding,
                            Qt.SmoothTransformation))
            ids.append(ph["id"])
            box.mousePressEvent = lambda e, p_id=ph["id"], i2=list(ids): \
                self._open(p_id, i2)
            thumbs.addWidget(box)
        thumbs.addStretch(1)
        v.addLayout(thumbs)
        self.content_lay.addWidget(card)

    def _open(self, photo_id: int, ids: list[int]):
        from .viewer import PhotoViewer
        dlg = PhotoViewer(self.lib, self.win, photo_id, ids)
        dlg.exec()
        self.refresh()

    # ---------- 快速入口 ----------
    def _quick_card(self):
        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)
        v.setContentsMargins(18, 14, 18, 16)
        v.setSpacing(10)
        hl = QLabel(t("快速开始", "Quick start"))
        hl.setObjectName("CardTitle")
        v.addWidget(hl)
        row = QHBoxLayout()
        row.setSpacing(10)
        n_review = self.lib.conn.execute(
            "SELECT COUNT(*) c FROM records WHERE rank=1 AND reviewed=0 "
            "AND confirmed_code IS NULL AND (confidence<0.5 OR source='whole')"
        ).fetchone()["c"]
        for text, key in ((t("📥 导入照片", "📥 Import photos"), "import"),
                          (t(f"待复核 {n_review}", f"Review ({n_review})"),
                           "review")):
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.win.switch_to(k))
            row.addWidget(b, 1)
        b_tl = QPushButton(t("🖼️ 时间线 · 静态站 · 记录中心", "🖼️ Timeline · Site · Report"))
        b_tl.setCursor(Qt.PointingHandCursor)
        b_tl.setObjectName("Primary")
        b_tl.clicked.connect(lambda: self.win.switch_to("timeline"))
        row.addWidget(b_tl, 1)
        row.addStretch(0)
        v.addLayout(row)
        self.content_lay.addWidget(card)

    # ---------- 档案速览 ----------
    def _archive_row(self):
        s = self.lib.stats_summary()
        spots = self.lib.achievements_summary()["spots"]
        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)
        v.setContentsMargins(18, 14, 18, 16)
        v.setSpacing(10)
        hl = QLabel(t("我的档案", "My archive"))
        hl.setObjectName("CardTitle")
        v.addWidget(hl)
        row = QHBoxLayout()
        row.setSpacing(10)
        for text, key in (
                (t(f"生涯鸟种 {s['species']}", f"Life species {s['species']}"), "life"),
                (t(f"照片 {s['photos']}", f"Photos {s['photos']}"), "timeline"),
                (t(f"鸟点 {spots}", f"Spots {spots}"), "life")):
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.win.switch_to(k))
            row.addWidget(b, 1)
        col_btn = QPushButton(t("作品集", "Collections"))
        col_btn.setCursor(Qt.PointingHandCursor)
        col_btn.clicked.connect(lambda: self.win.switch_to("collections"))
        row.addWidget(col_btn, 1)
        row.addStretch(0)
        v.addLayout(row)
        self.content_lay.addWidget(card)
