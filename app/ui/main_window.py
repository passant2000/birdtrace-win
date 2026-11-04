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
from . import map_page, stats_page, species_page, timeline_page
from .import_page import ImportPage
from .review_page import ReviewPage
from .settings_page import SettingsPage


def _nav() -> list[tuple[str, str]]:
    """导航项(构建时求值t(), 语言切换整窗重建后标签随新语言)。"""
    return [
        ("settings", t("设置", "Settings")),
        ("import", t("导入", "Import")),
        ("timeline", t("时间线", "Timeline")),
        ("species", t("鸟种库", "Species")),
        ("map", t("鸟点地图", "Map")),
        ("review", t("待复核", "Pending review")),
        ("stats", t("成就", "Achievements")),
        ("about", t("关于", "About")),
    ]


class MainWindow(QMainWindow):
    library_changed = Signal()   # 照片/记录变化后刷新各页

    def __init__(self, lib: Library, assets_dir: Path):
        super().__init__()
        self.lib = lib
        self.assets = assets_dir
        self.worker = None
        self.aes_worker = None
        self.burst_worker = None
        self._regroup_pending = False   # 识别刚完成: 新照片待分组
        self._regroup_unify = False     # 该次分组是否附带鸟种统一
        # 标注随文件夹走(0.8-①): 标注变更→库标脏目录, 定时flush(识别进行中不动)
        from PySide6.QtCore import QTimer as _QTimer
        self._sc_timer = _QTimer(self)
        self._sc_timer.setInterval(3000)
        self._sc_timer.timeout.connect(self._flush_sidecars_tick)
        self._sc_timer.start()
        self.setWindowTitle(t("鸟迹 · 鸟类照片管理", "BirdTrace · Bird photo manager"))
        self.setWindowIcon(QIcon(str(assets_dir / "brand" / "logo.png")))
        self.setMinimumSize(860, 540)
        self.resize(1280, 820)
        self._build_ui()
        self.library_changed.connect(self._refresh_pages)
        self._refresh_pages()
        self.switch_to("about")   # 默认首页=关于
        # 老库美学分回填: 延后到启动稳定后安静跑(导入/识别进行中会自动让路)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(8000, self.start_aesthetic_backfill)
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance().aboutToQuit.connect(self._stop_bg_workers)

    def _stop_bg_workers(self):
        """退出前让后台QThread有机会收尾, 避免线程销毁告警。"""
        if self.aes_worker and self.aes_worker.isRunning():
            self.aes_worker.stop()
            self.aes_worker.wait(3000)
        if self.burst_worker and self.burst_worker.isRunning():
            self.burst_worker.wait(3000)
        try:
            self.lib.flush_sidecars()   # 退出前把标注写进各文件夹
        except Exception:
            pass

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
        self.pages["timeline"] = timeline_page.TimelinePage(self.lib, self)
        self.pages["import"] = ImportPage(self.lib, self.assets, self)
        self.pages["species"] = species_page.SpeciesPage(self.lib, self)
        # 地图页含WebEngine(重), 首次切入时才创建
        self.pages["map"] = None
        self.pages["review"] = ReviewPage(self.lib, self)
        self.pages["stats"] = stats_page.StatsPage(self.lib, self)
        from .about_page import AboutPage
        self.pages["about"] = AboutPage(self.lib, self, self.assets)
        self.pages["settings"] = SettingsPage(self.lib, self)
        for key, _ in _nav():
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
            logo.mousePressEvent = lambda e: self.switch_to("about")
            lay.addWidget(logo)

        title = QLabel(t("鸟迹", "BirdTrace"))
        title.setObjectName("AppTitle")
        sub = QLabel("BirdTrace for Windows")
        sub.setObjectName("AppSubtitle")
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addSpacing(18)

        self._nav_buttons: dict[str, QPushButton] = {}
        for key, label in _nav():
            b = QPushButton(label)
            b.setObjectName("NavItem")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.switch_to(k))
            lay.addWidget(b)
            self._nav_buttons[key] = b
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
        recognizing = self.worker is not None and self.worker.isRunning()
        skip = set()
        if importing:
            skip |= {"timeline", "species", "stats", "review"}
        if recognizing:
            skip |= {"timeline", "review"}
        self._skipped_pages = skip if skip else getattr(self, "_skipped_pages", set()) & set()
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

    def start_recognition(self):
        """后台识别所有待处理照片(导入后自动调用)。"""
        if self.worker and self.worker.isRunning():
            return  # 已在跑, 会自动拾取新增
        # 防御: species表空会让识别结果"查无此鸟"(鸟种库/成就全0)
        if not self.lib.species_filled():
            self.lib.fill_species()
        from ..core.worker import RecognizeWorker
        pending = self.lib.pending_photo_ids()
        if not pending:
            return
        self.worker = RecognizeWorker(self.lib, self.assets, parent=self)
        self.worker.progress.connect(self._recognition_progress)
        self.worker.finished_all.connect(self._recognition_done)
        self._recognition_progress(0, len(pending), "")
        self.worker.start()

    def _recognition_progress(self, done: int, total: int, name: str):
        # 波次循环下done/total每波归零会闪烁——统一展示"已识别N"(累计)
        self._update_status()

    def _import_progress_tick(self, done: int, total: int):
        """导入进度上报(并行识别时状态栏双计数用)。"""
        self._imp_prog = (done, total)
        self._update_status()

    def _recognition_done(self, summary: dict):
        self.worker = None
        # 导入仍在进行(并行识别的一波结束): 静默收尾, 不抢导入的状态显示,
        # 文件丢失弹窗也等导入结束后由最后一波给出
        imp = self.pages.get("import")
        importing = imp is not None and imp.import_thread is not None \
            and imp.import_thread.isRunning()
        if importing:
            return
        self._rec_done_at = time.time()
        self._rec_last_summary = summary
        # 识别运行中被跳过的页(timeline/review)此刻补刷,
        # 否则停留在这些页的用户会一直看旧列表直到手动切页
        self.library_changed.emit()
        self._refresh_skipped()
        self._update_status()
        # 新识别的照片接着补美学分(鸟种排序/年度十八图要用), 之后重算连拍分组
        self._regroup_pending = True
        self._regroup_unify = True   # 识别完成: 连拍组鸟种统一(学SP)
        self.start_aesthetic_backfill()
        # 大量原文件丢失(典型: 引用模式库拷到别的电脑): 明确告知
        missing = summary.get("missing_files", 0)
        if missing and missing >= max(3, summary.get("total", 0) // 2):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, t("很多照片的原文件不在这台电脑上",
                        "Many photos' original files aren't on this computer"),
                t(f"本次识别有 {missing} 张照片的原文件找不到。\n\n"
                  "它们是用「引用原位置」方式导入的，记录的路径属于"
                  "另一台电脑或已移动的盘。\n\n"
                  "处理办法（任选）：\n"
                  "· 把原照片拷到这台电脑的相同路径下\n"
                  "· 在时间线用「选择」批量移除这些记录\n"
                  "· 重新用「复制/移动到新位置」方式导入",
                  f"Recognition couldn't find the original files for "
                  f"{missing} photos.\n\n"
                  "They were imported in “reference original location” "
                  "mode, so the recorded paths belong to another computer "
                  "or a drive that has moved.\n\n"
                  "To fix it (pick one):\n"
                  "· Copy the original photos to the same paths on this "
                  "computer\n"
                  "· Use “Select” on the Timeline to remove these records "
                  "in bulk\n"
                  "· Re-import with “copy/move to a new location”"))

    def _refresh_skipped(self):
        for key in getattr(self, "_skipped_pages", set()):
            page = self.pages.get(key)
            if page is not None and hasattr(page, "refresh"):
                page.refresh()
        self._skipped_pages = set()

    # ---------- 美学评分回填 ----------
    def start_aesthetic_backfill(self):
        """给未评分照片补美学分(单线程后台; 导入/识别进行中自动让路)。"""
        if self.aes_worker and self.aes_worker.isRunning():
            return
        imp = self.pages.get("import")
        if imp is not None and imp.import_thread is not None \
                and imp.import_thread.isRunning():
            return          # 导入结束后识别完成钩子会再拉起
        if self.worker and self.worker.isRunning():
            return          # _recognition_done 会拉起
        if not self.lib.pending_aesthetic():
            self.start_burst_regroup()   # 没有美学可补也要保证分组是新的
            return
        from ..core.aesthetic_worker import AestheticWorker
        self.aes_worker = AestheticWorker(self.lib, self.assets, parent=self)
        self.aes_worker.progress.connect(self._aes_progress)
        self.aes_worker.finished_all.connect(self._aes_done)
        self.aes_worker.start()
        self._update_status()

    def _aes_progress(self, done: int, total: int):
        self._aes_prog = (done, total)
        self._update_status()

    def _aes_done(self, summary: dict):
        self.aes_worker = None
        self._aes_last = summary
        # 排序变了(封面/详情/报告): 刷新相关页
        self._refresh_skipped()
        sp = self.pages.get("species")
        if sp is not None:
            sp.refresh()
        tl = self.pages.get("timeline")
        if tl is not None:
            tl.refresh()
        self._update_status()
        self.start_burst_regroup(force=True)   # 美学分变了→封面可能变

    # ---------- 连拍分组(0.8-③) ----------
    def start_burst_regroup(self, force: bool = False):
        """后台重算连拍分组: 识别/美学回填完成后(force)或规则版本变化。"""
        if self.burst_worker and self.burst_worker.isRunning():
            return
        imp = self.pages.get("import")
        if imp is not None and imp.import_thread is not None \
                and imp.import_thread.isRunning():
            return
        if self.worker and self.worker.isRunning():
            return
        if not (force or self._regroup_pending or self.lib.bursts_stale()):
            return
        from ..core.aesthetic_worker import BurstWorker
        self.burst_worker = BurstWorker(self.lib, unify=getattr(
            self, "_regroup_unify", False), parent=self)
        self.burst_worker.finished_all.connect(self._burst_done)
        self.burst_worker.start()

    def _burst_done(self, res: dict):
        self.burst_worker = None
        self._regroup_pending = False
        if res.get("changed"):
            for key in ("timeline", "species"):
                page = self.pages.get(key)
                if page is not None:
                    page.refresh()

    def _flush_sidecars_tick(self):
        """定时写 .birdtrace.json; 识别/导入运行中让路(避免与worker抢库)。"""
        if not self.lib.sidecar_dirty_count():
            return
        if self.worker and self.worker.isRunning():
            return
        imp = self.pages.get("import")
        if imp is not None and imp.import_thread is not None \
                and imp.import_thread.isRunning():
            return
        self.lib.flush_sidecars()

    def _update_status(self):
        imp = self.pages.get("import")
        importing = imp is not None and imp.import_thread is not None \
            and imp.import_thread.isRunning()
        # 导入与识别并行: 双计数同时显示(导入x/y · 已识别N), 不互相抢
        if importing:
            idone, itotal = getattr(self, "_imp_prog", (0, 0))
            rec_n = self.lib.conn.execute(
                "SELECT COUNT(DISTINCT photo_id) c FROM records"
            ).fetchone()["c"]
            if self.worker and self.worker.isRunning():
                self.status_chip.setText(
                    t(f"导入中 {idone}/{itotal} · 已识别 {rec_n} 张\n"
                      "导入与识别并行进行，可正常使用其他功能",
                      f"Importing {idone}/{itotal} · {rec_n} photos "
                      "identified\n"
                      "Import and recognition run in parallel; feel free "
                      "to use other features"))
            else:
                self.status_chip.setText(
                    t(f"导入中 {idone}/{itotal} · 已识别 {rec_n} 张\n"
                      "照片入库后自动开始识别",
                      f"Importing {idone}/{itotal} · {rec_n} photos "
                      "identified\n"
                      "Recognition starts automatically as photos are "
                      "added"))
            return
        # 识别刚完成(120s内)优先显示结果摘要, 不被"库内N张"覆盖
        if getattr(self, "_rec_last_summary", None) is not None \
                and time.time() - getattr(self, "_rec_done_at", 0) < 120:
            s = self._rec_last_summary
            # 0张识别出鸟(文件丢失/无鸟/全拒识): 明确说清, 不留"完成0"的困惑
            if s["ok"] == 0 and s["total"] > 0:
                self.status_chip.setText(
                    t("识别完成，但没有照片识别出鸟\n"
                      "可能原因：原文件已被移动或删除（引用模式下）",
                      "Recognition finished, but no photo was identified "
                      "as a bird\n"
                      "Likely cause: the original files were moved or "
                      "deleted (in reference mode)"))
                return
            review_n = self.lib.conn.execute(
                "SELECT COUNT(*) FROM records WHERE rank=1 AND reviewed=0 "
                "AND confirmed_code IS NULL AND (confidence<0.5 OR source='whole')"
            ).fetchone()[0]
            extra = (t(f"待复核 {review_n} 张", f"{review_n} pending review")
                     if review_n else t("全部高置信度", "All high confidence"))
            self.status_chip.setText(
                t(f"识别完成 {s['ok']}/{s['total']}\n{extra}，鸟种库已更新",
                  f"Recognition done: {s['ok']}/{s['total']}\n"
                  f"{extra} — species library updated"))
            return
        if self.worker and self.worker.isRunning():
            rec_n = self.lib.conn.execute(
                "SELECT COUNT(DISTINCT photo_id) c FROM records"
            ).fetchone()["c"]
            pending = len(self.lib.pending_photo_ids())
            self.status_chip.setText(
                t(f"识别中… 已识别 {rec_n} 张",
                  f"Recognizing… {rec_n} photos identified") +
                (t(f"（剩 {pending}）", f" ({pending} to go)") if pending else "") +
                "\n" + t("可正常使用其他功能", "Other features remain usable"))
            return
        # 美学评分回填中(识别/导入之后台任务, 优先级最低)
        if self.aes_worker and self.aes_worker.isRunning():
            adone, atotal = getattr(self, "_aes_prog", (0, 0))
            self.status_chip.setText(
                t(f"美学评分中 {adone}/{atotal}（挑最美照片，可正常使用）",
                  f"Scoring aesthetics {adone}/{atotal} "
                  "(picking your best-looking photos; you can keep working)"))
            return
        pending = len(self.lib.pending_photo_ids())
        if pending:
            self.status_chip.setText(
                t(f"{pending} 张照片待识别\n点击「导入」页开始识别",
                  f"{pending} photos awaiting recognition\n"
                  "Open the Import page to start"))
        else:
            self.status_chip.setText(
                t(f"库内 {self.lib.photo_count()} 张照片",
                  f"{self.lib.photo_count()} photos in library"))
