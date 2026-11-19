# -*- coding: utf-8 -*-
"""时间线多选(c8): 多选工具条+快捷键+打星三态/隔离区/重识别/移除/挂点/
加入作品集/按日期选择等批量操作(1.0冲刺①+⑨)。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox,
                               QDialog, QFileDialog,
                               QFrame, QHBoxLayout,
                               QLabel, QMessageBox,
                               QMenu, QPushButton,
                               QVBoxLayout)

from ...i18n import t, sname
from ... import theme
from ...media import ensure_thumbnail
from ...theme.widgets import PhotoGridItem, grid_tile_of, ThemedDateEdit


class SelectBarMixin:
    """SelectBarMixin(c8自timeline_page纯搬家, 方法体零改动)。"""

    def _setup_shortcuts(self):
        """选片快捷键(1.0冲刺①+⑨, Lightroom式): 1~5打星/0清星,
        K保留/P待定/X拒绝/U清除——只在多选模式且有选中时生效
        (handler自查 _select_mode/_selected/isVisible, 时间线页无
        文本输入框, 单键不与任何输入冲突)。"""
        from PySide6.QtGui import QKeySequence, QShortcut
        acts = {"k": lambda: self._mark_apply("keep"),
                "p": lambda: self._mark_apply("pending"),
                "x": lambda: self._mark_apply("reject"),
                "u": lambda: self._mark_apply(""),
                "0": lambda: self._rate_apply(0)}
        acts.update({str(i): (lambda _n=i: self._rate_apply(_n))
                     for i in range(1, 6)})
        for k, fn in acts.items():
            sc = QShortcut(QKeySequence(k), self)
            sc.activated.connect(fn)

    def _sel_date_range(self):
        """当前树点击节点→(d1,d2); 未点/杂项节点→None(回落今天)。"""
        key = self._chips_key
        if not key:
            return None
        if "|" in key:                 # 日
            d = "-".join(key.split("|", 1))
            return (d, d)
        if len(key) == 7 and key[4] == "-":   # 月
            import calendar
            y, m = key.split("-")
            return (f"{key}-01",
                    f"{key}-{calendar.monthrange(int(y), int(m))[1]:02d}")
        if len(key) == 4 and key.isdigit():   # 年
            return (f"{key}-01-01", f"{key}-12-31")
        return None

    def _add_to_collection(self):
        ids = sorted(self._selected)
        if not ids:
            return
        from PySide6.QtWidgets import QInputDialog, QMenu
        m = QMenu(self.col_btn)
        cols = self.lib.collections_list()
        for c in cols[:12]:
            m.addAction(f"{c['name']} ({c['n']})",
                        lambda _c=c: self._apply_collection(_c["id"], ids))
        if cols:
            m.addSeparator()
        m.addAction(t("新建作品集…", "New collection…"),
                    lambda: self._apply_collection(None, ids))
        m.exec(self.col_btn.mapToGlobal(
            self.col_btn.rect().bottomLeft()))

    def _apply_collection(self, col_id, ids):
        from PySide6.QtWidgets import QInputDialog
        if col_id is None:
            name, ok = QInputDialog.getText(
                self, t("新建作品集", "New collection"),
                t("作品集名称：", "Collection name:"))
            if not ok or not name.strip():
                return
            col_id = self.lib.collection_create(name)
        name = next((c["name"] for c in self.lib.collections_list()
                     if c["id"] == col_id), "?")
        mem = self.lib.collection_photos_of(col_id)
        self.lib.collection_set_photos(col_id, mem + ids)
        n_added = len([i for i in ids if i not in mem])
        QMessageBox.information(
            self, t("加入作品集", "Add to collection"),
            t(f"已把 {n_added} 张加入「{name}」。",
              f"Added {n_added} photo(s) to {name}."))

    # ---------- 多选模式 ----------

    def _toggle_select(self):
        self._select_mode = not self._select_mode
        if not self._select_mode:
            self._selected.clear()
            self._anchor_id = None
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
        self._anchor_id = None
        # 数据签名没变, refresh会跳过重建——选中态必须就地更新到网格项
        # (曾靠refresh重绘, 签名跳过后全选点了没反应)
        for pid, it in self._grid_items.items():
            try:
                it.set_selected(pid in self._selected)
            except RuntimeError:
                pass   # 僵尸控件(重建间隙)忽略
        self._sync_sel_ui()

    def _sync_sel_ui(self):
        n = len(self._selected)
        self.sel_count.setText(t(f"已选 {n} 张", f"{n} selected"))
        self.spot_btn.setEnabled(n > 0)
        self.selshare_btn.setEnabled(n > 0)
        self.rm_btn.setEnabled(n > 0)
        self.rere_btn.setEnabled(n > 0)
        self.all_btn.setText(t("全不选", "Deselect all") if n >= self.lib.photo_count()
                             else t("全选", "Select all"))

    def _on_item_click(self, pid: int, item=None, group_ids=None, ev=None):
        # 0.8.6连拍修错: 封面右键=组级菜单(整组改鸟种/整组重新识别);
        # 非连拍单张不弹(改判走多选工具条, 保持原路径)
        if ev is not None and getattr(ev, "button", None) is not None                 and ev.button() == Qt.RightButton:
            from ..burst_actions import make_group_menu
            try:
                make_group_menu(self.lib, self.win, pid, self,
                                ev.globalPos())
            except RuntimeError:
                pass
            return
        if self._select_mode:
                # Shift+click: 以上次点击为锚点, 按显示顺序选中头尾之间全部
            # (2026-11-03用户要求); 锚点无效时退化为普通点击。
            if (QApplication.keyboardModifiers() & Qt.ShiftModifier) \
                    and self._anchor_id in self._order_ids \
                    and pid in self._order_ids:
                self._select_range(self._anchor_id, pid)
                return
            # 就地翻转选中态, 不重建网格(重建会让快速连点落在已删除控件上)
            if pid in self._selected:
                self._selected.discard(pid)
            else:
                self._selected.add(pid)
            self._anchor_id = pid
            if item is not None:
                item.set_selected(pid in self._selected)
            self._sync_sel_ui()
        else:
            if group_ids:
                # 连拍封面: 在组内左右翻看(0.8-③"展开看全组")
                self._open(pid, list(group_ids))
                return
            ids = [r["id"] for r in self.lib.conn.execute(
                "SELECT id FROM photos ORDER BY id")]
            self._open(pid, ids)

    def _select_range(self, anchor: int, target: int):
        """选中显示顺序上 anchor..target 之间(含两端)的全部照片。"""
        if anchor not in self._order_ids or target not in self._order_ids:
            return
        i1 = self._order_ids.index(anchor)
        i2 = self._order_ids.index(target)
        lo, hi = (i1, i2) if i1 <= i2 else (i2, i1)
        for _pid in self._order_ids[lo:hi + 1]:
            self._selected.add(_pid)
            it = self._grid_items.get(_pid)
            if it is not None:
                try:
                    it.set_selected(True)
                except RuntimeError:
                    pass       # 僵尸控件(重建间隙)忽略
        self._sync_sel_ui()

    @staticmethod

    def _iso_date(taken_at) -> str:
        """拍摄时间 → "YYYY-MM-DD"(兼容EXIF冒号与ISO格式); 无效返回""。"""
        s = (taken_at or "")[:10]
        if len(s) >= 10 and s[4] in ":-":
            return s.replace(":", "-")
        return ""

    def _select_by_date(self):
        """按拍摄日期范围选择(可追加)。日期上下限取自当前库内照片。"""
        from PySide6.QtCore import QDate

        dates = sorted(d for d in self._iso_dates.values() if d)
        if not dates:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(t("按日期选择", "Select by date"))
        form = QFormLayout(dlg)
        lo = QDate.fromString(dates[0], "yyyy-MM-dd")
        hi = QDate.fromString(dates[-1], "yyyy-MM-dd")
        # ThemedDateEdit: 弹层年份/月份下拉一点直达+主题配色
        # (QDateEdit原生日历导航栏深色主题下配色不跟随, 用户2026-11-05)
        ed_from = ThemedDateEdit(hi)
        ed_to = ThemedDateEdit(hi)
        for ed in (ed_from, ed_to):
            ed.setDateRange(lo, hi)
        form.addRow(t("从", "From"), ed_from)
        form.addRow(t("到", "To"), ed_to)
        chk = QCheckBox(t("追加到当前选择", "Add to current selection"))
        form.addRow(chk)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        d1 = ed_from.date().toString("yyyy-MM-dd")
        d2 = ed_to.date().toString("yyyy-MM-dd")
        if d1 > d2:
            d1, d2 = d2, d1
        self._select_date_range(d1, d2, append=chk.isChecked())

    def _select_date_range(self, d1: str, d2: str, append: bool = False):
        """选中拍摄日期在 [d1,d2] 的照片(字符串ISO日期可直接比较)。"""
        ids = [pid for pid, d in self._iso_dates.items()
               if d and d1 <= d <= d2]
        if not append:
            self._selected.clear()
            for it in self._grid_items.values():
                try:
                    it.set_selected(False)
                except RuntimeError:
                    pass
        for pid in ids:
            self._selected.add(pid)
            it = self._grid_items.get(pid)
            if it is not None:
                try:
                    it.set_selected(True)
                except RuntimeError:
                    pass
        self._anchor_id = None
        self._sync_sel_ui()
        if not ids:
            QApplication.beep()

    def _batch_share_sel(self):
        ids = sorted(self._selected)
        if not ids:
            return
        from ..batch_share_dialog import BatchShareDialog
        dlg = BatchShareDialog(self.lib, self.win, photo_ids=ids)
        dlg.exec()

    # ---------- 标记/隔离(1.0冲刺①+⑨culling) ----------
    # 快捷键只在多选模式且有选中时生效(单张打星走查看器); 就地更新
    # 网格角标避免整页重建(多选模式网格必全展开, _grid_items全覆盖)

    def _mark_apply(self, pick: str):
        if not self._select_mode or not self._selected or not self.isVisible():
            return
        self.lib.set_pick(sorted(self._selected), pick)
        self._after_mark(pick=pick)

    def _rate_apply(self, n: int):
        if not self._select_mode or not self._selected or not self.isVisible():
            return
        self.lib.set_rating(sorted(self._selected), n)
        self._after_mark(stars=n)

    def _after_mark(self, pick: str | None = None, stars: int | None = None):
        """就地刷新选中项角标; 筛选激活时(标记可能让项移出筛选)整页刷。"""
        if (self.rating_filter.currentIndex() or
                self.pick_filter.currentIndex()):
            self.refresh(force=True)
            return
        for pid in self._selected:
            it = self._grid_items.get(pid)
            if it is None:
                continue
            try:
                if stars is not None:
                    it.stars = stars
                if pick is not None:
                    it.pick = pick
                it.update()
            except RuntimeError:
                pass

    def _open_quarantine(self):
        ids = sorted(self._selected)
        from ..quarantine_dialog import QuarantineDialog
        dlg = QuarantineDialog(self.lib, self.win, selected=ids)
        dlg.exec()
        if dlg.moved:
            self.refresh(force=True)

    def _batch_identify_videos(self):
        """⑬抽帧识别(独立入口): 首/中/尾帧喂现有管线, 最高置信入库;
        不碰识别worker(冻结红线)。QMediaPlayer 仅 GUI 线程可用。"""
        import datetime
        import numpy as np
        from pathlib import Path as _P
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QProgressDialog
        from ..core.video import extract_frames
        from ..paths import assets_dir

        vids = []
        for pid in sorted(self._selected):
            r = self.lib.conn.execute(
                "SELECT p.path, p.duration, p.rec_fail FROM photos p "
                "WHERE p.id=? AND IFNULL(p.is_video,0)=1",
                (pid,)).fetchone()
            if r and r["rec_fail"] < 3:
                vids.append((pid, r["path"], r["duration"]))
        if not vids:
            QMessageBox.information(
                self.win, t("没有所选视频", "No videos selected"),
                t("「识别视频帧」只对视频有效——请先勾选时间线里的视频。",
                  "This works on videos only — select videos on the "
                  "timeline first."))
            return
        if not hasattr(self, "_vpipe"):
            a = assets_dir()
            from ..ai.pipeline import RecognitionPipeline
            self._vpipe = RecognitionPipeline(
                detector_path=str(a / "models/BirdTraceBirdDetector_FP32.onnx"),
                classifier_path=str(
                    a / "models/BirdTraceRecognitionModel.onnx"),
                labels_path=str(a / "data/labels.json"),
                geo_prior_path=str(a / "data/geo_prior.sqlite"))

        def _qimg_rgb(img):
            img = img.convertToFormat(QImage.Format_RGB888)
            w, h = img.width(), img.height()
            if not w or not h:
                return None
            arr = np.frombuffer(img.constBits(), dtype=np.uint8)
            arr = arr.reshape(h, img.bytesPerLine() // 3, 3)[:, :w, :]
            return arr.copy()

        prog = QProgressDialog(t("正在抽帧识别…", "Identifying frames…"),
                               t("取消", "Cancel"), 0, len(vids), self.win)
        prog.setWindowModality(Qt.WindowModal)
        ok = fail = 0
        region = self.lib.get_setting("default_region", "GLOBAL")
        month = datetime.date.today().month
        for i, (pid, vpath, dur) in enumerate(vids):
            if prog.wasCanceled():
                break
            prog.setValue(i)
            if not _P(vpath).is_file():
                fail += 1
                continue
            best = None
            for qimg in extract_frames(vpath, dur):
                arr = _qimg_rgb(qimg)
                if arr is None:
                    continue
                try:
                    recs = self._vpipe.recognize(arr, region, month)
                except Exception:
                    recs = []
                if recs:
                    cand = recs[0]
                    if best is None or cand.get("confidence", 0) > \
                            best.get("confidence", 0):
                        best = cand
            if best:
                self.lib.add_records(pid, [best])
                ok += 1
            else:
                self.lib.bump_rec_fail(pid)
                fail += 1
        prog.close()
        self.win.library_changed.emit()
        QMessageBox.information(
            self.win, t("视频识别完成", "Video identification done"),
            t(f"识别成功 {ok} · 未识别出鸟 {fail}",
              f"Identified {ok} · no bird found {fail}"))

    def _batch_write_xmp(self):
        from ..core.xmp_write import maybe_write_for_photo
        from PySide6.QtWidgets import QMessageBox, QProgressDialog
        if self.lib.get_setting("xmp_writeback", "0") != "1":
            QMessageBox.information(
                self.win, t("XMP 写回未开启", "XMP write-back is off"),
                t("先到 设置 → 版权信息 → 「XMP 鸟种写回」开启（默认关，"
                  "建议先拿副本验证）。",
                  "Enable it first: Settings → Copyright → XMP species "
                  "write-back (off by default; verify on copies first)."))
            return
        ids = sorted(self._selected)
        if not ids:
            return
        prog = QProgressDialog(t("正在写回 XMP…", "Writing XMP…"),
                               t("取消", "Cancel"), 0, len(ids), self.win)
        prog.setWindowModality(Qt.WindowModal)
        ok = skip = fail = 0
        for i, pid in enumerate(ids):
            if prog.wasCanceled():
                break
            r = self.lib.conn.execute(
                "SELECT path FROM photos WHERE id=?", (pid,)).fetchone()
            if r and r["path"] and not str(r["path"]).lower().endswith(
                    (".jpg", ".jpeg")):
                skip += 1
            elif maybe_write_for_photo(self.lib, pid):
                ok += 1
            else:
                fail += 1
            prog.setValue(i + 1)
        prog.close()
        QMessageBox.information(
            self.win, t("XMP 写回完成", "XMP write-back done"),
            t(f"成功 {ok} · 跳过(非JPEG) {skip} · 失败 {fail}",
              f"Written {ok} · skipped (non-JPEG) {skip} · failed {fail}"))

    def _batch_set_spot(self):
        ids = sorted(self._selected)
        if not ids:
            return
        from ..spot_dialog import BatchSpotDialog
        dlg = BatchSpotDialog(self.lib, self.win, ids)
        dlg.exec()
        if dlg.applied:
            # 挂载/取消不改数据签名, refresh会跳过——但查看器/鸟点页的
            # 信息靠库重查, 发信号让各页跟上即可; 时间线网格不显示鸟点
            self.win.library_changed.emit()

    # ---------- 鸟种胶囊(0.8.6: 范围=树点击节点, 点击筛选) ----------

    def _scope_rows(self) -> list:
        """当前树点击范围内的照片行(年/月/日); 未点过返回[]。"""
        key = self._chips_key
        if not key:
            return []
        if "|" in key:                 # 日 "YYYY-MM|DD"
            day = "-".join(key.split("|", 1))
            return [p for v in self._raw.values() for p in v
                    if self._iso_date(p.get("taken_at")) == day]
        return [p for ym, v in self._raw.items() if ym.startswith(key)
                for p in v]

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
        from ...core.offline import classify_paths, drive_label
        cls = classify_paths((r["id"], r["path"]) for r in rows)
        if cls["offline"] and not cls["ok"] and not cls["missing"]:
            # 全部在离线卷上: 不是丢失, 插回硬盘即可(0.8-②)
            drives = "、".join(drive_label(d) for d in cls["offline"])
            QMessageBox.information(
                self, t("原图离线", "Originals offline"),
                t(f"选中的 {len(ids)} 张原图都在未接入的硬盘上（{drives}）。\n"
                  "插回硬盘后再「重新识别」即可，记录与标注不受影响。",
                  f"All {len(ids)} selected originals are on a disconnected "
                  f"drive ({drives}).\nReconnect it and re-identify; records "
                  "and labels are unaffected."))
            return
        missing = [r["path"] for r in rows if r["id"] in cls["missing"]
                   or any(r["id"] in v for v in cls["offline"].values())]
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
              "下一步可选识别范围：增量模式只跑未识别/待复核/低置信，"
              "人工确认过的完全不动；全量模式会覆盖包括人工确认在内的"
              "全部识别结果，按照片导入时的地区重新识别。",
              f"Re-identify the {len(ids)} selected photos?\n\n"
              "Scope is chosen next: incremental runs only unidentified/"
              "pending/low-confidence photos and never touches manually "
              "confirmed ones; full re-run overwrites all results including "
              "manual confirmations, using each photo's import region."),
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        # 地区/鸟点可选调整(2026-11-04用户: 导入时可能选错地区和鸟点)
        from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout,
                                       QHBoxLayout, QPushButton)
        dlg = QDialog(self)
        dlg.setWindowTitle(t("识别地区与鸟点", "Region & spot"))
        form = QFormLayout(dlg)
        # 识别范围(1.0冲刺②): 默认增量=不动人工确认(安全默认);
        # 全量=旧行为(覆盖人工确认, 确认框已警告)
        scope_combo = QComboBox()
        scope_combo.addItem(t("增量：只跑未识别/待复核/低置信",
                              "Incremental: unidentified/pending/low conf only"),
                            "pending")
        scope_combo.addItem(t("全量：覆盖全部（含人工确认）",
                              "Full: overwrite all (incl. manual)"), "all")
        form.addRow(t("识别范围", "Scope"), scope_combo)
        regions_mod = __import__("app.core.regions", fromlist=["regions"])
        reg_combo = QComboBox()
        q2 = ",".join("?" * len(ids))
        # 参数必须传: 此前execute()漏了ids→ProgrammingError槽静默崩溃,
        # 用户看到"确认后没有任何反应"(0.8.0-test2复查)
        batch_regions = [r["region_id"] for r in self.lib.conn.execute(
            f"SELECT DISTINCT b.region_id AS region_id FROM batches b "
            f"JOIN photos p ON p.batch_id=b.id WHERE p.id IN ({q2})", ids)
            if r["region_id"]]
        cur = batch_regions[0] if len(set(batch_regions)) == 1 else None
        reg_combo.addItem(t("保持不变", "Keep unchanged"), None)
        tree = regions_mod.build_tree()["countries"]
        for cnode in tree:
            # data必须是地区id: 此前国家级传None与「保持不变」同值,
            # 选国家后if new_region不成立→地区静默不变(0.8.0-test2复查)
            reg_combo.addItem(cnode["name"], cnode["id"])
            for snode in cnode.get("subs") or []:
                reg_combo.addItem("    " + snode["name"], snode["id"])
        if cur:
            idx = reg_combo.findData(cur)
            if idx >= 0:
                reg_combo.setCurrentIndex(idx)
        spot_combo = QComboBox()
        spot_combo.addItem(t("保持不变", "Keep unchanged"), "keep")
        spot_combo.addItem(t("不挂鸟点", "No spot"), None)
        for sp in self.lib.spots_overview():
            spot_combo.addItem(sp["name"], sp["id"])
        form.addRow(t("识别地区", "Region"), reg_combo)
        form.addRow(t("鸟点", "Spot"), spot_combo)
        bb = QHBoxLayout()
        bb.addStretch(1)
        ok = QPushButton(t("开始识别", "Start"))
        ok.setObjectName("Primary")
        ok.clicked.connect(dlg.accept)
        cancel = QPushButton(t("取消", "Cancel"))
        cancel.clicked.connect(dlg.reject)
        bb.addWidget(cancel)
        bb.addWidget(ok)
        form.addRow(bb)
        if not dlg.exec():
            return
        new_region = reg_combo.currentData()
        spot_choice = spot_combo.currentData()
        if new_region:
            self.lib.conn.execute(
                f"UPDATE batches SET region_id=? WHERE id IN ("
                f"SELECT DISTINCT batch_id FROM photos WHERE id IN ({q}))",
                [new_region] + ids)
            self.lib.conn.commit()
        if spot_choice != "keep":
            self.lib.set_photos_spot(ids, spot_choice)
        scope = scope_combo.currentData() or "pending"
        reset_ids = self.lib.reset_recognition(ids, scope=scope)
        if scope == "pending" and len(reset_ids) < len(ids):
            QMessageBox.information(
                self, t("增量重识别", "Incremental re-identify"),
                t(f"{len(ids)} 张中 {len(reset_ids)} 张进入识别队列——"
                  "其余有人工确认痕迹，已跳过（识别永不覆盖人工结果）。",
                  f"{len(reset_ids)} of {len(ids)} queued — the rest have "
                  "manual confirmations and were skipped."))
        self._selected.clear()
        self.win.library_changed.emit()
        self.refresh()
        if reset_ids:
            self.win.start_recognition()

    # ---------- 列表 ----------

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

    def _build_sel_bar(self):
        """多选工具条(c8自_build_ui切出, 纯搬家)。"""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QHBoxLayout
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
        self.date_btn = QPushButton(t("按日期…", "By date…"))
        self.date_btn.setCursor(Qt.PointingHandCursor)
        self.date_btn.setToolTip(t("按拍摄日期范围选择照片（可追加到当前选择）",
                                   "Select photos by shooting-date range "
                                   "(optionally adding to the current selection)"))
        self.date_btn.clicked.connect(self._select_by_date)
        sb.addWidget(self.date_btn)
        sb.addStretch(1)
        self.spot_btn = QPushButton(t("设置鸟点…", "Set spot…"))
        self.spot_btn.setCursor(Qt.PointingHandCursor)
        self.spot_btn.setToolTip(t(
            "给选中的照片批量挂载同一个鸟点（可搜索/新建/取消挂载）",
            "Mount the selected photos to one spot "
            "(search / create / unmount)"))
        self.spot_btn.clicked.connect(self._batch_set_spot)
        sb.addWidget(self.spot_btn)
        self.selshare_btn = QPushButton(t("分享卡…", "Share cards…"))
        self.selshare_btn.setCursor(Qt.PointingHandCursor)
        self.selshare_btn.setToolTip(t(
            "按所选照片逐张导出分享卡", "Export one share card per selected photo"))
        self.selshare_btn.clicked.connect(self._batch_share_sel)
        sb.addWidget(self.selshare_btn)
        self.rere_btn = QPushButton(t("重新识别…", "Re-identify…"))
        self.rere_btn.setObjectName("Primary")
        self.rere_btn.setCursor(Qt.PointingHandCursor)
        self.rere_btn.clicked.connect(self._batch_rerecognize)
        sb.addWidget(self.rere_btn)
        # 标记菜单(1.0冲刺①+⑨): 三态+星级, 也可用快捷键 K/P/X/U/0-5
        self.mark_btn = QPushButton(t("标记…", "Mark…"))
        self.mark_btn.setCursor(Qt.PointingHandCursor)
        m = QMenu(self.mark_btn)
        m.addAction(t("保留 (K)", "Keep (K)"),
                    lambda: self._mark_apply("keep"))
        m.addAction(t("待定 (P)", "Pending (P)"),
                    lambda: self._mark_apply("pending"))
        m.addAction(t("拒绝 (X)", "Reject (X)"),
                    lambda: self._mark_apply("reject"))
        m.addAction(t("清除标记 (U)", "Clear pick (U)"),
                    lambda: self._mark_apply(""))
        m.addSeparator()
        for n in range(1, 6):
            m.addAction("★" * n, lambda _n=n: self._rate_apply(_n))
        m.addAction(t("清除星级 (0)", "Clear rating (0)"),
                    lambda: self._rate_apply(0))
        self.mark_btn.setMenu(m)
        sb.addWidget(self.mark_btn)
        self.quar_btn = QPushButton(t("隔离区…", "Quarantine…"))
        self.quar_btn.setCursor(Qt.PointingHandCursor)
        self.quar_btn.setToolTip(t(
            "把选中的照片移入库目录下的隔离区（可预览清单后确认，随时恢复，"
            "绝不覆盖同名文件，不提供永久删除）",
            "Move selected photos into the library quarantine folder "
            "(preview first, restore anytime; never overwrites existing "
            "files, no permanent delete)"))
        self.quar_btn.clicked.connect(self._open_quarantine)
        sb.addWidget(self.quar_btn)
        # 加入作品集(1.0冲刺⑮): 选中集追加, 也可现场新建
        self.col_btn = QPushButton(t("加入作品集…", "Add to collection…"))
        self.col_btn.setCursor(Qt.PointingHandCursor)
        self.col_btn.setToolTip(t(
            "把选中的照片加入一个作品集（猛禽专题/某次旅行…自建），"
            "可现场新建；一个作品可属于多个作品集",
            "Add selected photos to a collection (create on the fly); "
            "one photo can belong to many"))
        self.col_btn.clicked.connect(self._add_to_collection)
        sb.addWidget(self.col_btn)
        # ⑪XMP回填(默认关, 开启后可用): 把当前生效鸟种批量写进原图XMP
        self.xmp_btn = QPushButton(t("写回XMP", "Write XMP"))
        self.xmp_btn.setCursor(Qt.PointingHandCursor)
        self.xmp_btn.setToolTip(t(
            "把所选照片当前生效的鸟种关键词/日期/版权写进 JPEG 的 XMP 段"
            "（需先在设置里开启 XMP 写回；只处理 JPEG，失败逐条报告）",
            "Write the effective species keywords/date/copyright into the "
            "JPEG XMP segment (enable in Settings first; JPEG only, "
            "per-file failures reported)"))
        self.xmp_btn.clicked.connect(self._batch_write_xmp)
        sb.addWidget(self.xmp_btn)
        # ⑬抽帧识别: 所选视频抽首/中/尾帧喂现有引擎, 不碰识别worker(冻结)
        self.vrec_btn = QPushButton(t("识别视频帧…", "Identify video frames…"))
        self.vrec_btn.setCursor(Qt.PointingHandCursor)
        self.vrec_btn.setToolTip(t(
            "对所选视频抽首/中/尾三帧送识别，取最高置信结果入库"
            "（低置信自动进待复核；视频不参与自动识别池）",
            "Extract first/middle/last frames of the selected videos for "
            "identification; the best result is recorded (low confidence "
            "goes to pending review)"))
        self.vrec_btn.clicked.connect(self._batch_identify_videos)
        sb.addWidget(self.vrec_btn)
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
        return self.sel_bar
