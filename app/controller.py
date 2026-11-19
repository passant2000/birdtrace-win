# -*- coding: utf-8 -*-
"""后台编排控制器(UI重设计c12): 自 MainWindow 纯搬家的后台任务编排——
识别 worker / 美学回填 / 连拍分组 / sidecar 定时写 / 状态文案。
红线: RecognizeWorker(core/worker.py) 一行未动, 纯编排搬家;
MainWindow 持本实例并以同签名方法/property 委托, 全部调用点零改动。
状态属性(worker/aes_worker/burst_worker/_imp_prog/_aes_prog/
_rec_last_summary/_rec_done_at/_skipped_pages)随迁到本类, MainWindow
经 property 只读转发。"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal

from .i18n import t


class AppController(QObject):
    # 识别刚完成且库有变化: MainWindow.library_changed 原样透传
    # (信号本体仍在 MainWindow, controller 经 win.library_changed.emit 触发)

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.worker = None
        self.aes_worker = None
        self.burst_worker = None
        self._regroup_pending = False   # 识别刚完成: 新照片待分组
        self._regroup_unify = False     # 该次分组是否附带鸟种统一
        # 标注随文件夹走(0.8-①): 标注变更→库标脏目录, 定时flush(识别进行中不动)
        self._sc_timer = QTimer(self)
        self._sc_timer.setInterval(3000)
        self._sc_timer.timeout.connect(self._flush_sidecars_tick)
        self._sc_timer.start()
        # ⑬视频后处理队列: 新入库视频补时长+首帧缩略图(GUI线程, Qt多媒体
        # 只能在主线程; 每拍处理1个不卡UI, 处理完自停)
        self._vid_timer = QTimer(self)
        self._vid_timer.setInterval(1200)
        self._vid_timer.timeout.connect(self._video_tick)
        self._vid_timer.start()

    # ---------- ⑬视频后处理 ----------
    def _video_tick(self):
        """队列式补视频元数据: duration + 首帧缩略图(webp进缩略图缓存)。"""
        row = self.win.lib.conn.execute(
            "SELECT p.id, p.path, p.file_hash h FROM photos p "
            "WHERE p.is_video=1 AND (p.duration IS NULL) ORDER BY p.id "
            "LIMIT 1").fetchone()
        if not row:
            self._vid_timer.stop()   # 队列空: 自停, 新导入时 refresh 唤醒
            return
        from .core.video import probe_duration, extract_frame
        from .media import thumb_path
        dur = probe_duration(row["path"], timeout_ms=8000)
        if dur:
            self.win.lib.conn.execute(
                "UPDATE photos SET duration=? WHERE id=?",
                (dur, row["id"]))
            self.win.lib.conn.commit()
        img = extract_frame(row["path"], at_ms=int((dur or 0.5) * 500),
                            timeout_ms=8000)
        if img is not None and not img.isNull():
            for size in (256, 512):
                tp = thumb_path(self.win.lib.root, row["h"], size)
                tp.parent.mkdir(parents=True, exist_ok=True)
                img.scaled(size, size, Qt.KeepAspectRatio,
                           Qt.SmoothTransformation).save(str(tp), "WEBP")
        self._update_status()

    def wake_video_queue(self):
        if not self._vid_timer.isActive():
            self._vid_timer.start()

    # ---------- 识别(自 main_window 纯搬家) ----------
    def start_recognition(self):
        """后台识别所有待处理照片(导入后自动调用)。"""
        if self.worker and self.worker.isRunning():
            return  # 已在跑, 会自动拾取新增
        # 防御: species表空会让识别结果"查无此鸟"(鸟种库/成就全0)
        if not self.win.lib.species_filled():
            self.win.lib.fill_species()
        from .core.worker import RecognizeWorker
        pending = self.win.lib.pending_photo_ids()
        if not pending:
            return
        self.worker = RecognizeWorker(self.win.lib, self.win.assets, parent=self)
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
        imp = self.win.pages.get("import")
        importing = imp is not None and imp.import_thread is not None \
            and imp.import_thread.isRunning()
        if importing:
            return
        self._rec_done_at = time.time()
        self._rec_last_summary = summary
        # 识别运行中被跳过的页(timeline/review)此刻补刷,
        # 否则停留在这些页的用户会一直看旧列表直到手动切页
        self.win.library_changed.emit()
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
                self.win, t("很多照片的原文件不在这台电脑上",
                            "Many photos' original files aren't on this "
                            "computer"),
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
            page = self.win.pages.get(key)
            if page is not None and hasattr(page, "refresh"):
                page.refresh()
        self._skipped_pages = set()

    # ---------- 美学评分回填(自 main_window 纯搬家) ----------
    def start_aesthetic_backfill(self):
        """给未评分照片补美学分(单线程后台; 导入/识别进行中自动让路)。"""
        if self.aes_worker and self.aes_worker.isRunning():
            return
        imp = self.win.pages.get("import")
        if imp is not None and imp.import_thread is not None \
                and imp.import_thread.isRunning():
            return          # 导入结束后识别完成钩子会再拉起
        if self.worker and self.worker.isRunning():
            return          # _recognition_done 会拉起
        if not self.win.lib.pending_aesthetic():
            self.start_burst_regroup()   # 没有美学可补也要保证分组是新的
            return
        from .core.aesthetic_worker import AestheticWorker
        self.aes_worker = AestheticWorker(self.win.lib, self.win.assets,
                                          parent=self)
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
        sp = self.win.pages.get("species")
        if sp is not None:
            sp.refresh()
        tl = self.win.pages.get("timeline")
        if tl is not None:
            tl.refresh()
        self._update_status()
        self.start_burst_regroup(force=True)   # 美学分变了→封面可能变

    # ---------- 连拍分组(0.8-③, 自 main_window 纯搬家) ----------
    def start_burst_regroup(self, force: bool = False):
        """后台重算连拍分组: 识别/美学回填完成后(force)或规则版本变化。"""
        if self.burst_worker and self.burst_worker.isRunning():
            return
        imp = self.win.pages.get("import")
        if imp is not None and imp.import_thread is not None \
                and imp.import_thread.isRunning():
            return
        if self.worker and self.worker.isRunning():
            return
        if not (force or self._regroup_pending
                or self.win.lib.bursts_stale()):
            return
        from .core.aesthetic_worker import BurstWorker
        self.burst_worker = BurstWorker(self.win.lib, unify=getattr(
            self, "_regroup_unify", False), parent=self)
        self.burst_worker.finished_all.connect(self._burst_done)
        self.burst_worker.start()

    def _burst_done(self, res: dict):
        self.burst_worker = None
        self._regroup_pending = False
        if res.get("changed"):
            for key in ("timeline", "species"):
                page = self.win.pages.get(key)
                if page is not None:
                    page.refresh()

    def _flush_sidecars_tick(self):
        """定时写 .birdtrace.json; 识别/导入运行中让路(避免与worker抢库)。"""
        if not self.win.lib.sidecar_dirty_count():
            return
        if self.worker and self.worker.isRunning():
            return
        imp = self.win.pages.get("import")
        if imp is not None and imp.import_thread is not None \
                and imp.import_thread.isRunning():
            return
        self.win.lib.flush_sidecars()

    def stop_bg_workers(self):
        """退出前让后台QThread有机会收尾, 避免线程销毁告警。"""
        if self.aes_worker and self.aes_worker.isRunning():
            self.aes_worker.stop()
            self.aes_worker.wait(3000)
        if self.burst_worker and self.burst_worker.isRunning():
            self.burst_worker.wait(3000)
        try:
            self.win.lib.flush_sidecars()   # 退出前把标注写进各文件夹
        except Exception:
            pass

    # ---------- 状态文案(自 main_window 纯搬家) ----------
    def _update_status(self):
        imp = self.win.pages.get("import")
        importing = imp is not None and imp.import_thread is not None \
            and imp.import_thread.isRunning()
        # 导入与识别并行: 双计数同时显示(导入x/y · 已识别N), 不互相抢
        if importing:
            idone, itotal = getattr(self, "_imp_prog", (0, 0))
            rec_n = self.win.lib.conn.execute(
                "SELECT COUNT(DISTINCT photo_id) c FROM records"
            ).fetchone()["c"]
            if self.worker and self.worker.isRunning():
                self.win.status_chip.setText(
                    t(f"导入中 {idone}/{itotal} · 已识别 {rec_n} 张\n"
                      "导入与识别并行进行，可正常使用其他功能",
                      f"Importing {idone}/{itotal} · {rec_n} photos "
                      "identified\n"
                      "Import and recognition run in parallel; feel free "
                      "to use other features"))
            else:
                self.win.status_chip.setText(
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
                self.win.status_chip.setText(
                    t("识别完成，但没有照片识别出鸟\n"
                      "可能原因：原文件已被移动或删除（引用模式下）",
                      "Recognition finished, but no photo was identified "
                      "as a bird\n"
                      "Likely cause: the original files were moved or "
                      "deleted (in reference mode)"))
                return
            review_n = self.win.lib.conn.execute(
                "SELECT COUNT(*) FROM records WHERE rank=1 AND reviewed=0 "
                "AND confirmed_code IS NULL AND (confidence<0.5 OR "
                "source='whole')").fetchone()[0]
            extra = (t(f"待复核 {review_n} 张", f"{review_n} pending review")
                     if review_n else t("全部高置信度", "All high confidence"))
            self.win.status_chip.setText(
                t(f"识别完成 {s['ok']}/{s['total']}\n{extra}，鸟种库已更新",
                  f"Recognition done: {s['ok']}/{s['total']}\n"
                  f"{extra} — species library updated"))
            return
        if self.worker and self.worker.isRunning():
            rec_n = self.win.lib.conn.execute(
                "SELECT COUNT(DISTINCT photo_id) c FROM records"
            ).fetchone()["c"]
            pending = len(self.win.lib.pending_photo_ids())
            self.win.status_chip.setText(
                t(f"识别中… 已识别 {rec_n} 张",
                  f"Recognizing… {rec_n} photos identified") +
                (t(f"（剩 {pending}）", f" ({pending} to go)") if pending
                 else "") +
                "\n" + t("可正常使用其他功能", "Other features remain usable"))
            return
        # 美学评分回填中(识别/导入之后台任务, 优先级最低)
        if self.aes_worker and self.aes_worker.isRunning():
            adone, atotal = getattr(self, "_aes_prog", (0, 0))
            self.win.status_chip.setText(
                t(f"美学评分中 {adone}/{atotal}（挑最美照片，可正常使用）",
                  f"Scoring aesthetics {adone}/{atotal} "
                  "(picking your best-looking photos; you can keep working)"))
            return
        pending = len(self.win.lib.pending_photo_ids())
        if pending:
            self.win.status_chip.setText(
                t(f"{pending} 张照片待识别\n点击「导入」页开始识别",
                  f"{pending} photos awaiting recognition\n"
                  "Open the Import page to start"))
        else:
            self.win.status_chip.setText(
                t(f"库内 {self.win.lib.photo_count()} 张照片",
                  f"{self.win.lib.photo_count()} photos in library"))
