# -*- coding: utf-8 -*-
"""画框识别工具窗口: 在照片上框出一只鸟 -> 松手自动识别 -> 确认加入。

用途: 检测漏鸟/框不准时的人工兜底(如鸟站牛背被漏检)。独立窗口而非
查看器内嵌模式——入口可见、不打扰看图。识别走CPU子进程(单张够快,
不与批量识别的GPU子进程抢DML)。
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from .. import theme
from ..i18n import t, sname
from ..theme.widgets import badge
from .viewer import ZoomableView


class ReboxDialog(QDialog):
    def __init__(self, lib, win, photo_id: int, parent=None):
        super().__init__(parent or win)
        self.lib = lib
        self.win = win
        self.pid = photo_id
        self.photo, _recs = lib.photo_detail(photo_id)
        self.setWindowTitle(t("画框识别", "Box & recognize"))
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint |
                            Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.setModal(True)
        self.resize(1150, 760)
        self._proc = None
        self._buf = ""
        self._last_rec = None          # 最近一次识别结果(等用户确认)
        self._last_box = None
        self._build_ui()
        if Path(self.photo["path"]).exists():
            self.view.set_image(self.photo["path"])
            self._enter_draw()
        else:
            from ..core.offline import OFFLINE, drive_label, drive_root, path_state
            if path_state(self.photo["path"]) == OFFLINE:
                drv = drive_label(drive_root(self.photo["path"]))
                self.hint.setText(t(
                    f"原图离线（{drv} 未接入），插回硬盘后再画框识别。",
                    f"Original offline (drive {drv} not connected); "
                    "reconnect it to box & recognize."))
            else:
                self.hint.setText(t("原始照片文件不存在，无法画框识别。",
                                    "Original photo file not found; cannot box & recognize."))

    # ---------- UI ----------
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        self.view = ZoomableView()
        self.view.setMinimumSize(620, 420)
        root.addWidget(self.view, 1)

        panel = QWidget()
        panel.setFixedWidth(320)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(4, 4, 4, 4)
        pl.setSpacing(10)

        self.hint = QLabel(t("在照片上按住拖拽，框出一只鸟，松手自动识别。\n"
                             "可连续框多只。滚轮缩放 / 拖动空白处平移。",
                             "Drag on the photo to box one bird; release to recognize.\n"
                             "Box as many as you like. Scroll to zoom / drag empty "
                             "space to pan."))
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"font-size:13px;color:{theme.LABEL_2};"
                                "background:transparent;")
        pl.addWidget(self.hint)

        self.result_box = QVBoxLayout()
        self.result_box.setSpacing(6)
        pl.addLayout(self.result_box)
        pl.addStretch(1)

        self.close_btn = QPushButton(t("关闭", "Close"))
        self.close_btn.clicked.connect(self.reject)
        pl.addWidget(self.close_btn)
        root.addWidget(panel)

    def _enter_draw(self):
        self.view.begin_draw(self._on_drawn)

    # ---------- 识别 ----------
    def _on_drawn(self, rect):
        box = [rect.x(), rect.y(), rect.x() + rect.width(),
               rect.y() + rect.height()]
        self._last_box = box
        self._show_status(t("识别中…（第一次需要加载模型，稍等几秒）",
                            "Recognizing… (first run loads the model; a few seconds)"))
        if not self._ensure_proc():
            self._show_status(t("识别进程启动失败",
                                "Failed to start the recognizer process"))
            self._enter_draw()
            return
        from ..exif import month_of
        month = str(month_of(self.photo.get("dt_original")) or "")
        region = self.photo.get("region_id") or ""
        box_s = ",".join(f"{v:.1f}" for v in box)
        line = (f"{self.pid}\t{self.photo['path']}\t{region}\t{month}"
                f"\t{box_s}\n")
        self._proc.write(line.encode("utf-8"))

    def _ensure_proc(self) -> bool:
        if self._proc is not None:
            return self._proc.state() != 0  # 0=NotRunning
        from PySide6.QtCore import QProcess
        from ..ai.recognize_sub import build_worker_cmd
        assets = getattr(self.win, "assets", None)
        if assets is None:
            return False
        cmd, cwd = build_worker_cmd(
            str(assets), self.lib.get_setting("detect_conf", "0.25"),
            use_gpu=False)
        p = QProcess(self)
        p.setProgram(cmd[0])
        p.setArguments(cmd[1:])
        if cwd:
            p.setWorkingDirectory(cwd)
        p.readyReadStandardOutput.connect(self._on_proc_out)
        p.start()
        self._proc = p
        return True

    def _on_proc_out(self):
        if self._proc is None:
            return
        self._buf += bytes(self._proc.readAllStandardOutput()) \
            .decode("utf-8", "replace")
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.strip()
            if not line.startswith("{"):
                continue    # EP告警等杂线
            try:
                res = json.loads(line)
            except ValueError:
                continue
            self._apply(res)

    def _apply(self, res: dict):
        if not res.get("ok"):
            self._show_status(t("识别失败：", "Recognition failed: ")
                              + str(res.get("error", ""))[:120])
            self._enter_draw()
            return
        recs = res.get("records") or []
        if not recs:
            self._show_status(t("这个框里没认出鸟（可能框偏了/框到背景，"
                                "或这个地区的名录里没有该鸟种）。\n"
                                "请把框对准鸟身再试一次。",
                                "No bird recognized in this box (it may be off "
                                "target, on background, or the species is not "
                                "on the regional list).\nTry framing the bird "
                                "more tightly."))
            self._enter_draw()
            return
        self._last_rec = recs[0]
        self._show_result()

    # ---------- 结果展示/确认 ----------
    def _clear_result(self):
        while self.result_box.count():
            it = self.result_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def _show_status(self, text: str):
        self._clear_result()
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setStyleSheet(f"font-size:13px;color:{theme.LABEL_2};")
        self.result_box.addWidget(lab)

    def _show_result(self):
        rec = self._last_rec
        self._clear_result()
        info = self.lib.species_info(rec["species_code"])
        cn = sname(info["cn"], info["en"]) if info and info["cn"] \
            else rec["species_code"]
        head = QHBoxLayout()
        head.addWidget(badge(t("画框", "Box"), "#FF9500"))
        title = QLabel(f"<b>{cn}</b>  "
                       f"<span style='color:#AEAEB2'>"
                       f"{rec['confidence']*100:.0f}%</span>")
        title.setTextFormat(Qt.RichText)
        head.addWidget(title, 1)
        self.result_box.addLayout(head)

        combo = QComboBox()
        for i, cand in enumerate(rec.get("top5") or []):
            s = self.lib.species_info(cand["code"])
            name = sname(s["cn"], s["en"]) if s and s["cn"] else cand["code"]
            mark = "✓ " if i == 0 else ""
            combo.addItem(f"{mark}{name}  {cand['prob']*100:.0f}%", cand["code"])
        combo.setCurrentIndex(0)
        self.result_box.addWidget(combo)

        row = QHBoxLayout()
        ok = QPushButton(t("加入结果", "Add to results"))
        ok.setObjectName("Primary")
        ok.setCursor(Qt.PointingHandCursor)
        ok.setToolTip(t("把这只鸟加入这张照片的识别结果（鸟种库同步更新）",
                        "Add this bird to this photo's recognition results "
                        "(species library updates too)"))
        ok.clicked.connect(lambda: self._accept(combo.currentData()))
        row.addWidget(ok)
        retry = QPushButton(t("重画", "Redraw"))
        retry.setCursor(Qt.PointingHandCursor)
        retry.clicked.connect(self._retry)
        row.addWidget(retry)
        self.result_box.addLayout(row)

    def _accept(self, code: str | None):
        rec = dict(self._last_rec)
        if code and code != rec["species_code"]:
            rec["species_code"] = code
            for cand in rec.get("top5") or []:
                if cand["code"] == code:
                    rec["confidence"] = cand["prob"]
        rec["box"] = self._last_box
        self.lib.add_records(self.pid, [rec])
        self.win.library_changed.emit()
        # 回传三处(用户典型路径: 待复核/鸟种库 -> 查看器 -> 画框识别):
        # ①查看器记录列表 ②鸟种库页 ③待复核页
        parent = self.parent()
        if parent is not None and hasattr(parent, "recs") \
                and hasattr(parent, "_render_records"):
            _, recs = self.lib.photo_detail(self.pid)
            parent.recs = recs
            parent._render_records()
        win = self.win
        if win is not None and hasattr(win, "pages"):
            for key in ("species", "review"):
                page = win.pages.get(key)
                if page is not None and hasattr(page, "refresh"):
                    page.refresh()
            if hasattr(win, "_refresh_pages"):
                win._refresh_pages()      # 状态栏/待复核角标
        self._show_status(t("已加入 ✓ 可以继续框下一只鸟，或关闭。",
                            "Added ✓ Continue with the next bird, or close."))
        self._enter_draw()

    def _retry(self):
        self._show_status(t("请重新框出这只鸟。", "Please box this bird again."))
        self._enter_draw()

    def done(self, r: int):
        # 关窗杀识别子进程(模型占~1GB内存)
        if self._proc is not None:
            try:
                self._proc.kill()
                self._proc.waitForFinished(2000)
            except RuntimeError:
                pass
            self._proc = None
        super().done(r)
