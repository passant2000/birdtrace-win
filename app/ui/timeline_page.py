# -*- coding: utf-8 -*-
"""时间线页: 按年月分组展示全部照片, lifer角标, 点击看大图。
多选模式: 批量从鸟迹移除 / 批量重新识别。"""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

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

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.content_lay = QVBoxLayout(self.content)
        self.content_lay.setContentsMargins(0, 0, 16, 24)
        self.content_lay.setSpacing(10)
        self.scroll.setWidget(self.content)
        lay.addWidget(self.scroll, 1)


    # ---------- 多选模式 ----------
    def _toggle_select(self):
        self._select_mode = not self._select_mode
        if not self._select_mode:
            self._selected.clear()
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
        self.refresh()

    def _sync_sel_ui(self):
        n = len(self._selected)
        self.sel_count.setText(t(f"已选 {n} 张", f"{n} selected"))
        self.rm_btn.setEnabled(n > 0)
        self.rere_btn.setEnabled(n > 0)
        self.all_btn.setText(t("全不选", "Deselect all") if n >= self.lib.photo_count()
                             else t("全选", "Select all"))

    def _on_item_click(self, pid: int, item=None):
        if self._select_mode:
            # 就地翻转选中态, 不重建网格(重建会让快速连点落在已删除控件上)
            if pid in self._selected:
                self._selected.discard(pid)
            else:
                self._selected.add(pid)
            if item is not None:
                item.set_selected(pid in self._selected)
            self._sync_sel_ui()
        else:
            ids = [r["id"] for r in self.lib.conn.execute(
                "SELECT id FROM photos ORDER BY id")]
            self._open(pid, ids)

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
    def refresh(self):
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

            grid_widget = QWidget()
            grid = QGridLayout(grid_widget)
            grid.setContentsMargins(0, 0, 0, 12)
            grid.setSpacing(10)
            cols = max(4, (self.width() - 80) // (THUMB + 12))
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
                grid.addWidget(item, i // cols, i % cols)
            grid.setColumnStretch(cols, 1)
            self.content_lay.addWidget(grid_widget)
        self.content_lay.addStretch(1)

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
