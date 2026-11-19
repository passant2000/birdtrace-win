# -*- coding: utf-8 -*-
"""主窗口: iOS风格侧栏导航 + 六个功能页。"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMainWindow,
                               QPushButton, QSizePolicy, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..db import Library
from ..i18n import t
from . import life_page, map_page, species_page
from .timeline import TimelinePage
from .home_page import HomePage
from .import_page import ImportPage
from .review_page import ReviewPage
from .settings_page import SettingsPage


def _nav() -> list[tuple[str, str, str]]:
    """导航项(key, 标签, 分组)。构建时求值t(), 语言切换整窗重建后随新语言。
    分组(UI重设计c2): gallery图库 / archive档案 / tidy整理 / bottom底部
    ——档案组=生涯/作品集(年鉴随后插入此组); 首页(c7)置顶无分组。"""
    return [
        ("home", t("首页", "Home"), ""),
        ("timeline", t("时间线", "Timeline"), "gallery"),
        ("species", t("鸟种库", "Species"), "gallery"),
        ("map", t("鸟点地图", "Map"), "gallery"),
        ("life", t("观鸟生涯", "Birding life"), "archive"),
        ("collections", t("作品集", "Collections"), "archive"),
        ("yearbook", t("年度年鉴", "Yearbook"), "archive"),
        ("review", t("待复核", "Pending review"), "tidy"),
        ("import", t("导入", "Import"), "tidy"),
        ("settings", t("设置", "Settings"), "bottom"),
        ("about", t("关于", "About"), "bottom"),
    ]


def _nav_group_label(group: str) -> str:
    """分组标题(组内拖排/持久化按组; bottom组不显示标题, 用分隔线)。"""
    return {
        "gallery": t("图库", "Gallery"),
        "archive": t("档案", "Archive"),
        "tidy": t("整理", "Organize"),
    }.get(group, "")


class MainWindow(QMainWindow):
    library_changed = Signal()   # 照片/记录变化后刷新各页

    def __init__(self, lib: Library, assets_dir: Path):
        super().__init__()
        self.lib = lib
        self.assets = assets_dir
        # 后台编排(UI重设计c12): 识别/美学/连拍/sidecar定时/状态文案
        # 迁入 AppController(纯搬家); 同名方法/property 委托, 调用点零改动
        from ..controller import AppController
        self._ctl = AppController(self)
        self.setWindowTitle(t("鸟迹 · 鸟类照片管理", "BirdTrace · Bird photo manager"))
        self.setWindowIcon(QIcon(str(assets_dir / "brand" / "logo.png")))
        self.setMinimumSize(860, 540)
        self.resize(1280, 820)
        self._build_ui()
        self.library_changed.connect(self._refresh_pages)
        self._refresh_pages()
        self.switch_to("home")   # 默认启动页=首页(UI重设计c7)
        # 老库美学分回填: 延后到启动稳定后安静跑(导入/识别进行中会自动让路)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(8000, self.start_aesthetic_backfill)
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance().aboutToQuit.connect(self._stop_bg_workers)

    def eventFilter(self, obj, ev):
        # 侧边栏导航按钮拖动重排(2026-11-06重做): 光标拖到哪就插到哪——
        # 旧实现按"移动超过18px交换一格并重置起点", 拖快一点就一格一格
        # 顿着走, 且交换后按钮跳位会让阈值反复触发(用户反馈不顺畅)。
        # 现在直接按光标Y相对各按钮中心算目标位置, 一次到位、无抖动。
        from PySide6.QtCore import QEvent, Qt
        if obj not in self._nav_buttons.values():
            return super().eventFilter(obj, ev)
        et = ev.type()
        if et == QEvent.MouseButtonPress:
            if ev.button() == Qt.LeftButton:
                self._nav_drag_btn = obj
                self._nav_drag_origin = ev.globalPosition().toPoint()
                self._nav_dragged = False
                # 组内拖排(c2): 记住拖的是哪个键, 插入位只在同组内算
                self._nav_drag_key = next(
                    (k for k, b in self._nav_buttons.items() if b is obj),
                    None)
        elif et == QEvent.MouseMove and getattr(self, "_nav_drag_btn", None):
            pos = ev.globalPosition().toPoint()
            if not self._nav_dragged:
                if abs(pos.y() - self._nav_drag_origin.y()) < 5:
                    return super().eventFilter(obj, ev)
                self._nav_dragged = True
                self._nav_drag_btn.setCursor(Qt.ClosedHandCursor)
            self._nav_drag_to(pos.y())
        elif et == QEvent.MouseButtonRelease \
                and getattr(self, "_nav_drag_btn", None):
            if self._nav_dragged:
                self._save_nav_order()
                self._nav_drag_btn.setCursor(Qt.PointingHandCursor)
                # clicked在release处理内同步发出, 先保留标志吞掉这一次;
                # 事件循环下一拍再清(拖到按钮外松手时不会吞掉下次点击)
                from PySide6.QtCore import QTimer
                QTimer.singleShot(
                    0, lambda: setattr(self, "_nav_dragged", False))
            self._nav_drag_btn = None
            self._nav_drag_origin = None
        return super().eventFilter(obj, ev)

    def _nav_drag_to(self, cursor_y: int):
        """按光标全局Y把拖动中的按钮插到目标位置(以其他按钮中心为界)。
        c2起限制在分组内: others=同组按钮, 跨组拖动不动。"""
        b = self._nav_drag_btn
        lay = self._nav_lay
        if b is None or lay.indexOf(b) < 0:
            return
        drag_group = self._nav_group.get(getattr(self, "_nav_drag_key", ""), None)
        others = [w for k, w in self._nav_buttons.items()
                  if w is not b and lay.indexOf(w) >= 0
                  and self._nav_group.get(k) == drag_group]
        others.sort(key=lay.indexOf)
        pos = 0
        for w in others:
            if w.mapToGlobal(w.rect().center()).y() < cursor_y:
                pos += 1
        cur_pos = sum(1 for w in others if lay.indexOf(w) < lay.indexOf(b))
        if pos == cur_pos:
            return
        # 注意: 导航布局前面还有标题/副标题/间距项, 按钮的布局索引不从0
        # 开始——必须按"其他按钮的实际布局索引"插入(2026-11-06实测:
        # 直接insertWidget(pos)会插到标题区, 拖动只挪一格)
        lay.removeWidget(b)
        others = [w for k, w in self._nav_buttons.items()
                  if w is not b and lay.indexOf(w) >= 0
                  and self._nav_group.get(k) == drag_group]
        others.sort(key=lay.indexOf)
        if not others:
            lay.insertWidget(0, b)
        elif pos <= 0:
            lay.insertWidget(lay.indexOf(others[0]), b)
        elif pos >= len(others):
            lay.insertWidget(lay.indexOf(others[-1]) + 1, b)
        else:
            lay.insertWidget(lay.indexOf(others[pos]), b)
        lay.activate()

    def _save_nav_order(self):
        # c2起按组持久化(nav_order:<group>); 旧版整条nav_order(无冒号)
        # 是分组前顺序, 不再适用——读到处直接丢弃, 不迁移
        for g in set(self._nav_group.values()):
            keys = [k for k, b in self._nav_buttons.items()
                    if self._nav_group[k] == g
                    and self._nav_lay.indexOf(b) >= 0]
            keys.sort(key=lambda k: self._nav_lay.indexOf(self._nav_buttons[k]))
            self.lib.set_setting(f"nav_order:{g}", ",".join(keys))

    def _nav_click(self, key: str):
        # 拖动重排刚发生过: 松手仍落在按钮内会触发clicked——不切页
        if getattr(self, "_nav_dragged", False):
            self._nav_dragged = False
            return
        self.switch_to(key)

    # ---- 后台编排委托(c12): 同签名, 调用点零改动 ----
    @property
    def worker(self):
        return self._ctl.worker

    @property
    def aes_worker(self):
        return self._ctl.aes_worker

    @property
    def burst_worker(self):
        return self._ctl.burst_worker

    def start_recognition(self):
        self._ctl.start_recognition()

    def start_aesthetic_backfill(self):
        self._ctl.start_aesthetic_backfill()

    def start_burst_regroup(self, force: bool = False):
        self._ctl.start_burst_regroup(force=force)

    def _update_status(self):
        self._ctl._update_status()

    def _refresh_skipped(self):
        self._ctl._refresh_skipped()

    def _import_progress_tick(self, done: int, total: int):
        self._ctl._import_progress_tick(done, total)

    def _stop_bg_workers(self):
        self._ctl.stop_bg_workers()

    # ---------- UI ----------
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("Root")
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        root.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.pages: dict[str, QWidget] = {}
        self.pages["home"] = HomePage(self.lib, self)
        self.pages["timeline"] = TimelinePage(self.lib, self)
        self.pages["import"] = ImportPage(self.lib, self.assets, self)
        self.pages["species"] = species_page.SpeciesPage(self.lib, self)
        # 地图页含WebEngine(重), 首次切入时才创建
        self.pages["map"] = None
        self.pages["review"] = ReviewPage(self.lib, self)
        self.pages["life"] = life_page.LifePage(self.lib, self)
        from .collections_page import CollectionsPage
        self.pages["collections"] = CollectionsPage(self.lib, self)
        from .yearbook_page import YearbookPage
        self.pages["yearbook"] = YearbookPage(self.lib, self)
        from .about_page import AboutPage
        self.pages["about"] = AboutPage(self.lib, self, self.assets)
        self.pages["settings"] = SettingsPage(self.lib, self)
        for key, _l, _g in _nav():
            if self.pages[key] is not None:
                self.stack.addWidget(self.pages[key])
        root.addWidget(self.stack, 1)

    def _build_sidebar(self) -> QFrame:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(190)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 22, 14, 16)
        lay.setSpacing(4)

        logo = QLabel()
        lp = str(self.assets / "brand" / "logo.png")
        pm = QIcon(lp).pixmap(72, 72)
        if not pm.isNull():
            logo.setPixmap(pm)
            logo.setAlignment(Qt.AlignHCenter)
            logo.setCursor(Qt.PointingHandCursor)
            logo.setToolTip(t("回到首页", "Back to home"))
            logo.mousePressEvent = lambda e: self.switch_to("home")
            lay.addWidget(logo)

        title = QLabel(t("鸟迹", "BirdTrace"))
        title.setObjectName("AppTitle")
        sub = QLabel("BirdTrace for Windows")
        sub.setObjectName("AppSubtitle")
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addSpacing(18)

        self._nav_buttons: dict[str, QPushButton] = {}
        self._nav_group: dict[str, str] = {}
        self._nav_lay = lay
        # 分组渲染(UI重设计c2): 组标题+组内按钮; bottom组用分隔线不用标题
        nav_items = _nav()
        groups: list[tuple[str | None, list[tuple[str, str]]]] = []
        seen: dict[str | None, int] = {}
        for key, label, group in nav_items:
            if group not in seen:
                seen[group] = len(groups)
                groups.append((group, []))
            groups[seen[group]][1].append((key, label))
        # 组内自定义顺序(nav_order:<group>, 拖动重排持久化);
        # 旧版nav_order(无冒号)=分组前整条顺序, 不再适用——丢弃按默认序
        for gi, (g, members) in enumerate(groups):
            if g:
                raw = self.lib.get_setting(f"nav_order:{g}", "")
                if raw:
                    names = dict(members)
                    order = [k for k in raw.split(",") if k in names]
                    order += [k for k, _l in members if k not in order]
                    groups[gi] = (g, [(k, names[k]) for k in order])
        for gi, (g, members) in enumerate(groups):
            if gi:
                lay.addSpacing(8)
            glab_text = _nav_group_label(g) if g else ""
            if g == "":
                pass   # 首页(c7): 置顶无分组, 不渲染标题/分隔线
            elif glab_text:
                glab = QLabel(glab_text)
                glab.setObjectName("SidebarGroup")
                lay.addWidget(glab)
            else:
                # bottom组(设置/关于): 分隔线隔开, 不设组标题
                sep = QFrame()
                sep.setFrameShape(QFrame.HLine)
                sep.setObjectName("SidebarSep")
                lay.addWidget(sep)
            for key, label in members:
                b = QPushButton(label)
                b.setObjectName("NavItem")
                b.setCheckable(True)
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, k=key: self._nav_click(k))
                lay.addWidget(b)
                self._nav_buttons[key] = b
                self._nav_group[key] = g or ""
                b.installEventFilter(self)
        self._nav_buttons["about"].setChecked(True)

        lay.addStretch()

        self.status_chip = QLabel("")
        self.status_chip.setObjectName("Hint")
        self.status_chip.setWordWrap(True)
        lay.addWidget(self.status_chip)

        self.review_badge_btn = self._nav_buttons["review"]
        return side

    # ---------- 行为 ----------
    def switch_to(self, key: str):
        # 旧键映射(UI重设计c5): 成就页已并入生涯页, 旧调用/--open-page
        # stats 继续可用
        if key == "stats":
            key = "life"
        # 离开当前页的清理钩子(如鸟种页停掉后台缩略图任务, 释放线程池
        # 与磁盘给即将到来的重页——2026-10-31地图首切卡顿治理的一环)
        old = self.stack.currentWidget()
        if old is not None and old is not self.pages.get(key):
            hook = getattr(old, "on_page_hidden", None)
            if callable(hook):
                hook()
        if key == "map" and self.pages["map"] is None:
            self.pages["map"] = map_page.MapPage(self.lib, self)
            self.stack.addWidget(self.pages["map"])
        for k, b in self._nav_buttons.items():
            b.setChecked(k == key)
        # 离开时间线时退出多选模式(用户预期: 切页回来=浏览状态)
        if key != "timeline":
            tl = self.pages.get("timeline")
            if tl is not None and getattr(tl, "_select_mode", False):
                tl._toggle_select()
        self.stack.setCurrentWidget(self.pages[key])
        page = self.pages[key]
        if page is not None and hasattr(page, "refresh"):
            page.refresh()

    def _refresh_pages(self):
        # 后台任务(导入线程/识别worker)运行中: 跳过重型页refresh,
        # 防与写库抢锁导致UI假死(用户实测: 导入完挂点后切页卡死)
        imp = self.pages.get("import")
        importing = imp is not None and imp.import_thread is not None             and imp.import_thread.isRunning()
        recognizing = self._ctl.worker is not None and self._ctl.worker.isRunning()
        skip = set()
        if importing:
            skip |= {"timeline", "species", "life", "review"}
        if recognizing:
            skip |= {"timeline", "review"}
        self._ctl._skipped_pages = (skip if skip else getattr(self._ctl, "_skipped_pages", set()) & set())
        for key, page in self.pages.items():
            if key in skip:
                continue
            if page is not None and key != "settings" and hasattr(page, "refresh"):
                page.refresh()
        n = self.lib.conn.execute(
            "SELECT COUNT(*) FROM records WHERE rank=1 AND reviewed=0 "
            "AND confirmed_code IS NULL AND (confidence<0.5 OR source='whole')"
        ).fetchone()[0]
        self.review_badge_btn.setText(t("待复核", "Pending review") + (f"  ● {n}" if n else ""))
        self._update_status()

    def open_species(self, code: str):
        """从时间线/每日一鸟跳转到鸟种详情。"""
        self.switch_to('species')
        self.pages['species']._open_detail(code)


