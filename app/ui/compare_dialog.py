# -*- coding: utf-8 -*-
"""组内对比选片(1.0冲刺⑨②): 连拍组两格并排原像素对比(滚轮缩放/
双击复位, 左右独立) + 组内推荐三档模式。推荐因子=美学×置信, 但
"知道何时闭嘴"(调研 WingScribe 的降级设计):
· 稳妥=组内主体尺度差异过大就不推荐, 只按因子排序交人工;
· 辅助=只给顺序+风险提示(无检测框/低置信);
· 宽松=最多荐3张且须复核。
推荐绝不自动写任何标注——打星/三态都由人工按键。"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel,
                               QPushButton, QSplitter, QVBoxLayout, QWidget)

from .. import theme
from ..i18n import t
from .burst_actions import group_photo_ids
from .viewer import ZoomableView

MODES = ("safe", "assist", "loose")


class CompareDialog(QDialog):
    def __init__(self, lib, win, photo_id: int):
        super().__init__(win)
        self.lib = lib
        self.win = win
        self.ids = group_photo_ids(lib, photo_id)
        self.frames = self._load_frames()
        # A格=组内序列游标; B格=推荐序列游标
        self.a_idx = max(0, self.ids.index(photo_id)) if photo_id in self.ids else 0
        ranked, state = self._recommend("safe")
        self.ranked = ranked
        self.rec_state = state
        self.b_idx = 1 if len(ranked) > 1 else 0
        self.mode = "safe"
        self.setWindowTitle(t("组内对比选片", "Compare & pick in burst"))
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint |
                            Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.resize(1180, 760)

        from PySide6.QtGui import QKeySequence, QShortcut
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        top = QHBoxLayout()
        top.addWidget(QLabel(t("推荐模式", "Suggest mode")))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            t("稳妥（差异大不推荐）", "Safe (no suggest on variance)"),
            t("辅助（顺序+风险提示）", "Assist (order + risk hints)"),
            t("宽松（荐3张须复核）", "Loose (top-3, must review)")])
        self.mode_combo.setCurrentIndex(0)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        top.addWidget(self.mode_combo)
        self.hint_lab = QLabel("")
        self.hint_lab.setStyleSheet(f"font-size:12px;color:{theme.LABEL_2};"
                                    "background:transparent;")
        top.addWidget(self.hint_lab, 1)
        lay.addLayout(top)

        split = QSplitter(Qt.Horizontal)
        lay.addWidget(split, 1)
        self.views = []
        self.labs = []
        for side in range(2):
            w = QWidget()
            wl = QVBoxLayout(w)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.setSpacing(4)
            v = ZoomableView()
            v.setMinimumSize(380, 320)
            wl.addWidget(v, 1)
            lab = QLabel("")
            lab.setWordWrap(True)
            lab.setStyleSheet(f"font-size:12px;color:{theme.LABEL_2};"
                              "background:transparent;")
            wl.addWidget(lab)
            split.addWidget(w)
            self.views.append(v)
            self.labs.append(lab)

        # A格操作行(打星/三态只作用于A格=当前浏览帧)
        ops = QHBoxLayout()
        self.prev_btn = QPushButton(t("◀ 上一帧", "◀ Prev"))
        self.prev_btn.setCursor(Qt.PointingHandCursor)
        self.prev_btn.clicked.connect(lambda: self._move_a(-1))
        ops.addWidget(self.prev_btn)
        self.next_btn = QPushButton(t("下一帧 ▶", "Next ▶"))
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.clicked.connect(lambda: self._move_a(1))
        ops.addWidget(self.next_btn)
        ops.addStretch(1)
        for n in range(1, 6):
            b = QPushButton("★" * n)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(t(f"A格设 {n} 星", f"Set {n} star(s) on A"))
            b.clicked.connect(lambda _=False, _n=n: self._rate(_n))
            ops.addWidget(b)
        b0 = QPushButton(t("清星", "Clear"))
        b0.setCursor(Qt.PointingHandCursor)
        b0.clicked.connect(lambda: self._rate(0))
        ops.addWidget(b0)
        for k, lab2 in [("keep", t("保留", "Keep")),
                        ("pending", t("待定", "Pending")),
                        ("reject", t("拒绝", "Reject")),
                        ("", t("清除", "Clear"))]:
            b = QPushButton(lab2)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, _k=k: self._pick(_k))
            ops.addWidget(b)
        lay.addLayout(ops)

        for k, fn in [("left", lambda: self._move_a(-1)),
                      ("right", lambda: self._move_a(1)),
                      ("1", lambda: self._rate(1)), ("2", lambda: self._rate(2)),
                      ("3", lambda: self._rate(3)), ("4", lambda: self._rate(4)),
                      ("5", lambda: self._rate(5)), ("0", lambda: self._rate(0)),
                      ("k", lambda: self._pick("keep")),
                      ("p", lambda: self._pick("pending")),
                      ("x", lambda: self._pick("reject")),
                      ("u", lambda: self._pick(""))]:
            QShortcut(QKeySequence(k), self, fn)
        self._render()

    # ---------- 数据 ----------
    def _load_frames(self) -> list[dict]:
        out = []
        for pid in self.ids:
            r = self.lib.conn.execute(
                "SELECT p.path, p.aesthetic, p.rating, p.pick, "
                "  (SELECT r.confidence FROM records r WHERE r.photo_id=p.id "
                "   AND r.rank=1 LIMIT 1) AS conf, "
                "  (SELECT r.box_json FROM records r WHERE r.photo_id=p.id "
                "   AND r.rank=1 LIMIT 1) AS box_json, "
                "  (SELECT COUNT(*) FROM records r WHERE r.photo_id=p.id) AS nrec "
                "FROM photos p WHERE p.id=?", (pid,)).fetchone()
            if not r:
                continue
            box_ratio = None
            try:
                box = json.loads(r["box_json"]) if r["box_json"] else None
                if isinstance(box, (list, tuple)) and len(box) == 4:
                    ph = self.lib.conn.execute(
                        "SELECT height FROM photos WHERE id=?", (pid,)).fetchone()
                    if ph and ph["height"]:
                        box_ratio = float(box[3]) / float(ph["height"])
            except (ValueError, TypeError):
                box_ratio = None
            score = (r["aesthetic"] or 0) * (r["conf"] or 0)
            out.append({"id": pid, "path": r["path"],
                        "aesthetic": r["aesthetic"], "rating": r["rating"] or 0,
                        "pick": r["pick"] or "", "conf": r["conf"],
                        "box_ratio": box_ratio, "nrec": r["nrec"],
                        "score": score})
        return out

    def _recommend(self, mode: str):
        """返回(排序后frames, 状态)。稳妥: 主体尺度差(框高比极差)>0.5
        →不推荐(交人工); 宽松: 只标前3。推荐永不自动写标注。"""
        scored = sorted(self.frames, key=lambda f: -f["score"])
        if mode == "safe":
            ratios = [f["box_ratio"] for f in scored if f["box_ratio"]]
            if len(scored) >= 2 and ratios and (max(ratios) - min(ratios)) > 0.5:
                return scored, "varied"
            return scored, "ok"
        if mode == "loose":
            return scored[:3], "loose"
        return scored, "ok"

    # ---------- 交互 ----------
    def _mode_changed(self, i: int):
        self.mode = MODES[i]
        self.ranked, self.rec_state = self._recommend(self.mode)
        self.b_idx = min(self.b_idx, max(0, len(self.ranked) - 1))
        self._render()

    def _move_a(self, d: int):
        if not self.frames:
            return
        self.a_idx = (self.a_idx + d) % len(self.frames)
        self._render()

    def _cur(self):
        return self.frames[self.a_idx] if self.frames else None

    def _b_cur(self):
        return self.ranked[self.b_idx] if self.ranked else None

    def _rate(self, n: int):
        f = self._cur()
        if not f:
            return
        self.lib.set_rating([f["id"]], n)
        f["rating"] = n
        self._render()

    def _pick(self, pick: str):
        f = self._cur()
        if not f:
            return
        self.lib.set_pick([f["id"]], pick)
        f["pick"] = pick
        self._render()

    # ---------- 渲染 ----------
    def _lab_text(self, f, tag: str, is_b: bool) -> str:
        if not f:
            return t("（空）", "(empty)")
        stars = "★" * int(f["rating"] or 0) if f["rating"] else ""
        pickc = {"keep": "🟢", "pending": "🟠", "reject": "🔴"}.get(f["pick"], "")
        marks = []
        if not f["nrec"]:
            marks.append(t("未识别", "unidentified"))
        elif f["conf"] is not None and f["conf"] < 0.5:
            marks.append(t(f"低置信 {f['conf']:.0%}", f"low conf {f['conf']:.0%}"))
        risk = (" · ⚠" + "、".join(marks)) if marks else ""
        recommend = ""
        if is_b and self.rec_state == "loose" and f in self.ranked:
            recommend = t(" · 荐（须复核）", " · suggested (review)")
        return (f"<b>{tag}</b> {Path(f['path']).name}"
                f"{'  ' + stars if stars else ''}{'  ' + pickc if pickc else ''}"
                f"<br>{t('美学', 'aesthetic')} "
                f"{(f['aesthetic'] or 0):.1f} × "
                f"{t('置信', 'conf')} {(f['conf'] or 0):.0%}"
                f" = {f['score']:.1f}{risk}{recommend}")

    def _render(self):
        af, bf = self._cur(), self._b_cur()
        self.views[0].set_image(af["path"] if af else "")
        self.views[1].set_image(bf["path"] if bf else "")
        self.labs[0].setText(self._lab_text(af, "A", False))
        self.labs[1].setText(self._lab_text(bf, t("推荐", "Suggest"), True))
        hints = {"varied": t("组内主体尺度差异过大——不做自动推荐，请人工判断",
                             "Subject scale varies too much — no auto suggestion"),
                 "loose": t("宽松模式：最多荐 3 张，采纳前请逐张复核",
                            "Loose mode: top-3 suggestions, review before keeping"),
                 "ok": t("按 美学×置信 排序；A格 ←→ 换帧，1~5 打星，K/P/X 标记",
                         "Sorted by aesthetic×confidence; ←→ to switch A, "
                         "1-5 to rate, K/P/X to mark")}
        self.hint_lab.setText(hints.get(self.rec_state, ""))
