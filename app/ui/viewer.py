# -*- coding: utf-8 -*-
"""大图查看器: 左右切换 / 缩放平移 / EXIF信息 / 识别确认 / 分享。"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, QRect, Qt, Signal
from PySide6.QtGui import (QColor, QKeySequence, QPainter, QPainterPath,
                           QPen, QPixmap, QShortcut)
from PySide6.QtWidgets import (QComboBox, QDialog, QGraphicsPixmapItem,
                               QGraphicsRectItem, QGraphicsScene,
                               QGraphicsView, QHBoxLayout,
                               QLabel, QPushButton, QSplitter, QVBoxLayout,
                               QWidget)

from ..core import regions
from ..i18n import t, sname
from .. import theme
from ..theme.widgets import badge


class ZoomableView(QGraphicsView):
    """滚轮缩放(以鼠标为中心) + 拖拽平移 + 双击复位。

    自适应规则: 未手动缩放时, 图片始终自动适配视口大小(窗口拉伸/最大化
    都会重新适配, 不留四周空白); 一旦滚轮/加减键手动缩放, 则尊重用户的
    缩放, 不再自动变; 双击回到自适应。

    画框模式(begin_draw): 按住拖拽框出一个矩形, 松手回调; 供画框识别
    工具使用, 平时(查看器)不启用。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = QGraphicsPixmapItem()
        self._scene.addItem(self._item)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QColor(theme.VIEWER_BG))
        self.setFrameShape(QGraphicsView.NoFrame)
        self._zoom = 1.0
        self._need_fit = False
        self._user_zoomed = False
        self._draw_cb = None         # 重画模式回调(QRectF)

    def set_image(self, path: str):
        pm = QPixmap(path)
        self._item.setPixmap(pm)
        self._scene.setSceneRect(QRectF(pm.rect()))
        self._need_fit = True
        self._user_zoomed = False
        self._fit_if_ready()

    def set_placeholder(self, text: str | None):
        """原图不可读时在视口上覆盖说明文字; None=撤掉。

        不动场景/_item(此前用 _scene.clear() 连 _item 一起删了, 之后
        _render_records 取裁剪缩略图/左右切图再碰 _item 就崩; 改用
        QGraphicsProxyWidget 又在 removeItem 时触发 Qt 断言——0.8-②
        离线验证两次踩坑, 覆盖层最省事也最稳)。"""
        ov = getattr(self, "_overlay", None)
        if text is None:
            if ov is not None:
                ov.hide()
            return
        if ov is None:
            ov = QLabel(self.viewport())
            ov.setWordWrap(True)
            ov.setAlignment(Qt.AlignCenter)
            ov.setStyleSheet(f"color:{theme.LABEL_2};font-size:13px;"
                             "background:#F7F7FA;border-radius:10px;"
                             "padding:20px;")
            self._overlay = ov
        ov.setText(text)
        ov.show()
        self._place_overlay()

    def _place_overlay(self):
        ov = getattr(self, "_overlay", None)
        if ov is None or not ov.isVisible():
            return
        vw, vh = self.viewport().width(), self.viewport().height()
        w = max(240, min(640, vw - 80))
        ov.setFixedWidth(w)
        ov.adjustSize()
        ov.move((vw - w) // 2, max(20, (vh - ov.height()) // 2))

    def _fit_if_ready(self):
        # 必须已可见且拿到真实视口尺寸: 构造期视口还是占位大小,
        # 提前fit会让图片按错误尺寸渲染(打开后四周一圈空白)
        if self._need_fit and self.isVisible() and self.viewport().width() > 10:
            self.fit()
            self._need_fit = False

    def fit(self):
        self.resetTransform()
        self.fitInView(self._item, Qt.KeepAspectRatio)
        self._zoom = 1.0

    def showEvent(self, e):
        super().showEvent(e)
        self._fit_if_ready()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_overlay()
        # 用户没动过缩放时跟随窗口大小, 手动缩放后不抢用户的视角
        if self.isVisible() and not self._user_zoomed:
            self._need_fit = False
            self.fit()

    def wheelEvent(self, e):
        delta = e.angleDelta().y()
        factor = 1.25 if delta > 0 else 1 / 1.25
        self._zoom_by(factor)

    def _zoom_by(self, factor: float):
        if not (0.15 <= self._zoom * factor <= 12):
            return
        self._zoom *= factor
        self._user_zoomed = True
        self.scale(factor, factor)

    def mouseDoubleClickEvent(self, e):
        self._user_zoomed = False
        self.fit()
        super().mouseDoubleClickEvent(e)

    # ---- 重画模式: 框选新检测框 ----
    def begin_draw(self, on_drawn):
        """进入重画模式: 在图上按住拖拽框一个矩形, 松手回调
        on_drawn(QRectF 图像坐标); Esc取消。"""
        self._draw_cb = on_drawn
        self._draw_start = None
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.viewport().setCursor(Qt.CrossCursor)

    def cancel_draw(self):
        self._draw_cb = None
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.viewport().unsetCursor()

    def drawing(self) -> bool:
        return getattr(self, "_draw_cb", None) is not None

    def mousePressEvent(self, e):
        if self.drawing() and e.button() == Qt.MouseButton.LeftButton:
            self._draw_start = self.mapToScene(e.position().toPoint())
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if self.drawing() and e.button() == Qt.MouseButton.LeftButton                 and self._draw_start is not None:
            p2 = self.mapToScene(e.position().toPoint())
            rect = QRectF(self._draw_start, p2).normalized()                 .intersected(self._scene.sceneRect())
            cb = self._draw_cb
            self.cancel_draw()
            super().mouseReleaseEvent(e)
            # 太小的框当误触忽略(不触发识别)
            if rect.width() >= 8 and rect.height() >= 8:
                cb(rect)
            return
        super().mouseReleaseEvent(e)


class PhotoViewer(QDialog):
    def __init__(self, lib, win, photo_id: int, ids: list[int]):
        super().__init__(win)
        self.lib = lib
        self.win = win
        self.ids = ids
        self.index = ids.index(photo_id) if photo_id in ids else 0
        self.setWindowTitle(t("照片查看", "Photo viewer"))
        # 带最小化/最大化按钮: 大图查看时用户习惯先把窗口最大化
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint |
                            Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.setModal(True)
        self.resize(1200, 780)
        self._build_ui()
        QShortcut(QKeySequence(Qt.Key_Left), self, self._prev)
        QShortcut(QKeySequence(Qt.Key_Right), self, self._next)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.reject)
        QShortcut(QKeySequence("+"), self, lambda: self.view._zoom_by(1.25))
        QShortcut(QKeySequence("-"), self, lambda: self.view._zoom_by(1 / 1.25))
        # 选片快捷键(1.0冲刺①+⑨): 模态对话框内, 与缩放+/-不冲突
        for k, fn in [("1", lambda: self._rate(1)), ("2", lambda: self._rate(2)),
                      ("3", lambda: self._rate(3)), ("4", lambda: self._rate(4)),
                      ("5", lambda: self._rate(5)), ("0", lambda: self._rate(0)),
                      ("k", lambda: self._pick("keep")),
                      ("p", lambda: self._pick("pending")),
                      ("x", lambda: self._pick("reject")),
                      ("u", lambda: self._pick(""))]:
            QShortcut(QKeySequence(k), self, fn)
        self._load()

    @property
    def assets(self):
        return getattr(self.win, "assets", None)

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

        # 左: 大图(可缩放)
        self.view = ZoomableView()
        self.view.setMinimumSize(600, 400)
        split.addWidget(self.view)

        # 右: 信息面板(宽随内容自适应: 340下英文2×2动作钮两端裁切
        # "reate share car"/"nove from BirdTrac", 0.8.6英文适配实测;
        # 用按钮行sizeHint推导, 语言/DPI变了自动跟)
        panel = QWidget()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(4, 4, 4, 4)
        pl.setSpacing(10)

        self.navi = QLabel("")
        self.navi.setObjectName("Hint")
        self.navi.setText(t("1 / 1  ·  ← → 切换\n滚轮缩放 · 拖动平移 · 双击复位",
                            "1 / 1  ·  ← → to switch\nWheel zoom · drag to pan · "
                            "double-click to reset"))
        pl.addWidget(self.navi)

        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.RichText)
        self.info.setStyleSheet(f"background:transparent;font-size:13px;color:{theme.LABEL_2};")
        self.info.setOpenExternalLinks(False)
        self.info.linkActivated.connect(self._path_clicked)
        pl.addWidget(self.info)

        pl.addWidget(QLabel(t("识别结果", "Identification results")))
        self.records_box = QVBoxLayout()
        self.records_box.setSpacing(8)
        pl.addLayout(self.records_box)

        # 选片块(1.0冲刺①+⑨): 星级/三态/备注——人工值与AI美学互不干扰;
        # 快捷键 1~5打星 0清星 K保留 P待定 X拒绝 U清除
        pl.addWidget(QLabel(t("选片", "Culling")))
        star_row = QHBoxLayout()
        star_row.setSpacing(4)
        self.star_btns = []
        for n in range(1, 6):
            b = QPushButton("★")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedSize(36, 30)
            b.setToolTip(t(f"{n} 星（快捷键 {n}）", f"{n} star (shortcut {n})"))
            b.clicked.connect(lambda _=False, _n=n: self._rate(_n))
            self.star_btns.append(b)
            star_row.addWidget(b)
        self.star_clear = QPushButton(t("清星", "Clear"))
        self.star_clear.setCursor(Qt.PointingHandCursor)
        self.star_clear.setToolTip(t("清除星级（快捷键 0）",
                                     "Clear rating (shortcut 0)"))
        self.star_clear.clicked.connect(lambda: self._rate(0))
        star_row.addWidget(self.star_clear)
        star_row.addStretch(1)
        pl.addLayout(star_row)

        pick_row = QHBoxLayout()
        pick_row.setSpacing(4)
        self.pick_btns = {}
        for k, lab in [("keep", t("保留 (K)", "Keep (K)")),
                       ("pending", t("待定 (P)", "Pending (P)")),
                       ("reject", t("拒绝 (X)", "Reject (X)")),
                       ("", t("清除 (U)", "Clear (U)"))]:
            b = QPushButton(lab)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, _k=k: self._pick(_k))
            self.pick_btns[k] = b
            pick_row.addWidget(b)
        pick_row.addStretch(1)
        pl.addLayout(pick_row)

        from PySide6.QtWidgets import QLineEdit
        self.pick_note_edit = QLineEdit()
        self.pick_note_edit.setPlaceholderText(t(
            "备注（只记在鸟迹，不碰文件；回车保存）",
            "Note (stored in BirdTrace only; Enter to save)"))
        self.pick_note_edit.textEdited.connect(self._note_started)
        self.pick_note_edit.editingFinished.connect(self._note_commit)
        pl.addWidget(self.pick_note_edit)
        self._note_pid = None

        # 标签/作品集(1.0冲刺⑭⑮): 一行展示+编辑入口(勾选式编辑器)
        tag_row = QHBoxLayout()
        self.tags_lab = QLabel("")
        self.tags_lab.setWordWrap(True)
        self.tags_lab.setStyleSheet(f"font-size:12px;color:{theme.LABEL_2};"
                                    "background:transparent;")
        tag_row.addWidget(self.tags_lab, 1)
        self.tag_edit_btn = QPushButton(t("标签/作品集…", "Tags…"))
        self.tag_edit_btn.setCursor(Qt.PointingHandCursor)
        self.tag_edit_btn.setToolTip(t(
            "编辑本照片的自定义标签(飞行/捕食/逆光…自建)与所属作品集",
            "Edit custom tags (flight/hunting/backlight…) and collections "
            "for this photo"))
        self.tag_edit_btn.clicked.connect(self._edit_tags)
        tag_row.addWidget(self.tag_edit_btn)
        pl.addLayout(tag_row)

        pl.addStretch(1)

        # 连拍组级操作(0.8.6用户: 连拍一组都识别错): 当前照片属于连拍组
        # 时显示——整组改鸟种(P1)/整组重识别=多取景全局最优(P2)
        from .burst_actions import change_group_species, reidentify_group
        self.group_bar = QWidget()
        gb = QHBoxLayout(self.group_bar)
        gb.setContentsMargins(0, 0, 0, 0)
        gb.setSpacing(8)
        self.gpick_btn = QPushButton(t("整组改鸟种…",
                                       "Change species for burst…"))
        self.gpick_btn.setCursor(Qt.PointingHandCursor)
        self.gpick_btn.setToolTip(t(
            "当前照片所属的连拍整组一次改判（弹一次选鸟器，全组生效；"
            "人工改判不会被自动识别/连拍统一覆盖）",
            "Re-assign the whole burst this photo belongs to (one picker "
            "for all; manual verdicts are never overwritten)"))
        self.gpick_btn.clicked.connect(
            lambda: (change_group_species(self.lib, self.win, self,
                                          self.ids[self.index]),
                     self._load()))
        gb.addWidget(self.gpick_btn)
        self.grescue_btn = QPushButton(t("整组重新识别…",
                                         "Re-identify burst…"))
        self.grescue_btn.setCursor(Qt.PointingHandCursor)
        self.grescue_btn.setToolTip(t(
            "每帧尝试多种取景、取全局最优结果应用到整组——连拍各帧姿态"
            "不同，常有一帧换个取景就认对",
            "Each frame is tried with several crops; the globally best "
            "result is applied to the whole group — a different pose often "
            "gets identified correctly"))
        self.grescue_btn.clicked.connect(
            lambda: reidentify_group(self.lib, self.win, self,
                                     self.ids[self.index],
                                     on_done=lambda _s: self._load()))
        gb.addWidget(self.grescue_btn)
        gb.addStretch(1)
        pl.addWidget(self.group_bar)

        # 底部操作区: 2×2等宽网格, 按用途分组
        #   上行=常用(补识别/分享)  下行=管理(挂点/移除)
        from PySide6.QtWidgets import QGridLayout
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        self.rebox_btn = QPushButton(t("✚ 画框识别…", "✚ Box identify…"))
        self.rebox_btn.setCursor(Qt.PointingHandCursor)
        self.rebox_btn.setToolTip(
            t("打开画框识别工具：在照片上框出一只鸟，\n"
              "松手自动识别，确认后加入这张照片的结果。\n"
              "适合补识别被漏掉的鸟。",
              "Open the box-identification tool: drag a box around a bird,\n"
              "release to identify it automatically, then confirm to add it "
              "to this photo's results.\n"
              "Good for recovering birds the first pass missed."))
        self.rebox_btn.clicked.connect(self._rebox_dialog)
        grid.addWidget(self.rebox_btn, 0, 0)

        self.share_btn = QPushButton(t("生成分享卡", "Create share card"))
        self.share_btn.setObjectName("Primary")
        self.share_btn.setCursor(Qt.PointingHandCursor)
        self.share_btn.clicked.connect(self._share)
        grid.addWidget(self.share_btn, 0, 1)

        self.spot_btn = QPushButton(t("设为鸟点", "Set as birding spot"))
        self.spot_btn.setCursor(Qt.PointingHandCursor)
        self.spot_btn.clicked.connect(self._pick_spot)
        grid.addWidget(self.spot_btn, 1, 0)

        self.remove_btn = QPushButton(t("从鸟迹移除…", "Remove from BirdTrace…"))
        self.remove_btn.setCursor(Qt.PointingHandCursor)
        self.remove_btn.setToolTip(
            t("只从鸟迹库移除，原始照片文件不会被动",
              "Removes it from the BirdTrace library only; "
              "the original photo file is untouched"))
        self.remove_btn.setStyleSheet(
            f"QPushButton{{color:{theme.RED};}}")
        self.remove_btn.clicked.connect(self._remove_photo)
        grid.addWidget(self.remove_btn, 1, 1)
        pl.addLayout(grid)

        split.addWidget(panel)
        split.setStretchFactor(0, 1)
        # 面板宽=内容自适应(0.8.6): 2×2按钮行sizeHint推导, 夹[320,460]
        from ..theme.widgets import panel_width_of
        panel.setFixedWidth(panel_width_of(panel, 320, 460, pad=16))

    # ---------- 数据 ----------
    def _load(self):
        photo, recs = self.lib.photo_detail(self.ids[self.index])
        self.photo = photo
        self.recs = recs
        # 连拍组级操作行: 属于连拍组(≥2张)才显示(0.8.6)
        from .burst_actions import group_photo_ids
        try:
            gids = group_photo_ids(self.lib, photo["id"])
        except Exception:
            gids = [photo["id"]]
        self.group_bar.setVisible(len(gids) >= 2)
        missing = not Path(photo["path"]).exists()
        if missing:
            # 引用模式下原文件不可读: 区分"硬盘没插"(0.8-②, 插回即好)与
            # "被移动/删除", 明示原因+去向建议, 不留空白
            from ..core.offline import OFFLINE, drive_label, drive_root, path_state
            if path_state(photo["path"]) == OFFLINE:
                drv = drive_label(drive_root(photo["path"]))
                body = (t(f"原图离线：所在硬盘（{drv}）未接入\n\n",
                          f"Original offline: drive {drv} is not connected\n\n")
                        + t(f"记录的路径：{photo['path']}\n\n",
                            f"Recorded path: {photo['path']}\n\n")
                        + t("插回硬盘后即可查看大图；缩略图、标注、统计、分享卡文字"
                            "等不受影响。",
                            "Reconnect the drive to view the full image; "
                            "thumbnails, labels, stats and card text are "
                            "unaffected."))
            else:
                body = (t("原始照片文件不存在\n\n", "Original photo file not found\n\n")
                        + t(f"记录的路径：{photo['path']}\n\n",
                            f"Recorded path: {photo['path']}\n\n")
                        + t("可能被移动、重命名或删除。"
                            "把文件放回原位置后点「重新识别」可恢复；"
                            "在时间线用「重新链接」按内容找回；"
                            "或直接「从鸟迹移除」这条记录。",
                            "It may have been moved, renamed or deleted. "
                            "Put the file back and click \"Re-identify\" to "
                            "restore it, use \"Relink\" on the Timeline to find "
                            "it by content, or \"Remove from BirdTrace\" to drop "
                            "this record."))
            self.view.set_image("")
            self.view.set_placeholder(body)
        else:
            self.view.set_placeholder(None)
            self.view.set_image(photo["path"])
        self.navi.setText(
            t(f"{self.index + 1} / {len(self.ids)}  ·  ← → 切换\n"
              "滚轮缩放 · 拖动平移 · 双击复位",
              f"{self.index + 1} / {len(self.ids)}  ·  ← → to switch\n"
              "Wheel zoom · drag to pan · double-click to reset"))

        taken = photo.get("dt_original") or (photo.get("added_at") or "")
        make = (photo.get("make") or "").strip()
        model = (photo.get("model") or "").strip()
        if make and model.lower().startswith(make.lower()):
            cam = model
        else:
            cam = " ".join(x for x in [make, model] if x)
        params = "  ".join(x for x in [
            f"ISO{photo['iso']}" if photo.get("iso") else None,
            photo.get("exposure") or None,
            f"ƒ/{photo['fnum']:g}" if photo.get("fnum") else None,
            f"{photo['focal_len']:g}mm" if photo.get("focal_len") else None,
        ] if x)
        region = regions.region_display(photo.get("region_id"))
        fname = Path(photo["path"]).name
        lines = [f"<b>{fname}</b>",
                 f"<a href='open-path' style='text-decoration:none'>"
                 f"{photo['path']}</a>",
                 f"<b>{taken[:19]}</b>"]
        if cam:
            lines.append(cam)
        if params:
            lines.append(params)
        if photo.get("lens"):
            lines.append(str(photo["lens"]))
        lines.append(t(f"地区：{region}", f"Region: {region}"))
        lines.append(t(f"位置：{photo.get('spot_name') or '未挂鸟点'}",
                       f"Location: {photo.get('spot_name') or t('未挂鸟点', 'no birding spot')}"))
        if photo.get("aesthetic") is not None:
            lines.append(t(f"美学：✨ {float(photo['aesthetic']):.1f} / 10",
                           f"Aesthetic: ✨ {float(photo['aesthetic']):.1f} / 10"))
        if photo.get("gps_lat") is not None and photo.get("gps_lon") is not None:
            lines.append(t(f"GPS：{photo['gps_lat']:.4f}, {photo['gps_lon']:.4f}",
                           f"GPS: {photo['gps_lat']:.4f}, {photo['gps_lon']:.4f}"))
        # RAW/DNG附属(1.0冲刺⑧): 成对编目后主文件行显示附属位置
        rp = (photo.get("raw_path") or "").strip()
        if rp:
            lines.append(t(
                f"附属RAW/DNG：{Path(rp).name}",
                f"Attached RAW/DNG: {Path(rp).name}"))
        self.info.setText("<br/>".join(lines))

        self._render_records()
        self._sync_pick_ui()
        self._sync_tags_lab()

    # ---------- 选片(1.0冲刺①+⑨) ----------
    def _rate(self, n: int):
        if not self.photo:
            return
        pid = self.ids[self.index]
        self.lib.set_rating([pid], n)
        self.photo["rating"] = n
        self._sync_pick_ui()

    def _pick(self, pick: str):
        if not self.photo:
            return
        pid = self.ids[self.index]
        note = self.pick_note_edit.text().strip() if pick else ""
        self.lib.set_pick([pid], pick, note)
        self.photo["pick"] = pick
        self.photo["pick_note"] = note
        self._sync_pick_ui()

    def _note_started(self):
        # 用户真正敲字才记录目标照片; 程序化setText(textChanged)不触发,
        # 切图时不会把上一张的备注误写进下一张
        self._note_pid = self.ids[self.index]

    def _note_commit(self):
        pid = getattr(self, "_note_pid", None)
        if pid is None or not self.photo or pid != self.ids[self.index]:
            return
        self._note_pid = None
        pick = self.photo.get("pick") or ""
        self.lib.set_pick([pid], pick, self.pick_note_edit.text().strip())
        self.photo["pick_note"] = self.pick_note_edit.text().strip()

    def _sync_pick_ui(self):
        rating = int((self.photo or {}).get("rating") or 0)
        pick = (self.photo or {}).get("pick") or ""
        for i, b in enumerate(self.star_btns, 1):
            b.blockSignals(True)
            b.setChecked(i <= rating)
            b.blockSignals(False)
            b.setStyleSheet(
                f"QPushButton{{font-size:16px;color:{theme.LABEL_3};"
                f"background:transparent;border:1px solid {theme.SEP};"
                f"border-radius:8px;}}"
                f"QPushButton:checked{{color:#FFD60A;background:transparent;"
                f"border:1px solid #FFD60A;}}")
        for k, b in self.pick_btns.items():
            b.blockSignals(True)
            b.setChecked(k == pick)
            b.blockSignals(False)
            on = {"keep": "#34C759", "pending": "#FF9F0A",
                  "reject": "#FF453A"}.get(k, theme.BLUE)
            b.setStyleSheet(
                "QPushButton{background:transparent;border:1px solid %s;"
                "border-radius:8px;padding:3px 8px;}"
                "QPushButton:checked{color:white;background:%s;"
                "border:1px solid %s;}" % (theme.SEP, on, on))
        if getattr(self, "_note_pid", None) is None:
            self.pick_note_edit.blockSignals(True)
            self.pick_note_edit.setText(
                (self.photo or {}).get("pick_note") or "")
            self.pick_note_edit.blockSignals(False)

    def _edit_tags(self):
        if not self.photo:
            return
        from .tag_pick_dialog import TagPickDialog
        pid = self.ids[self.index]
        dlg = TagPickDialog(self.lib, self.win, pid)
        dlg.exec()
        self._sync_tags_lab()

    def _sync_tags_lab(self):
        pid = self.ids[self.index]
        tags = self.lib.tags_of(pid)
        cols = [c["name"] for c in self.lib.collections_of(pid)]
        parts = []
        if tags:
            parts.append(t("标签: ", "Tags: ") + "、".join(tags))
        if cols:
            parts.append(t("作品集: ", "Collections: ") + "、".join(cols))
        self.tags_lab.setText("\n".join(parts) or
                              t("（未打标签）", "(no tags)"))

    def _path_clicked(self, link: str):
        """点击路径: 资源管理器打开所在文件夹并选中该文件。"""
        if link != "open-path":
            return
        import subprocess
        p = (self.photo or {}).get("path", "")
        if p and Path(p).exists():
            subprocess.Popen(["explorer", "/select,", p])

    def _render_records(self):
        while self.records_box.count():
            item = self.records_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for rec in self.recs:
            w = QWidget()
            row = QHBoxLayout(w)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)

            # 左: 该记录对应的检测框裁剪图(多鸟照片一眼分清哪条是哪只)
            try:
                box = json.loads(rec.get("box_json") or "null")
            except (TypeError, json.JSONDecodeError):
                box = None
            pm = self.view._item.pixmap()
            if box and len(box) == 4 and not pm.isNull():
                crop = pm.copy(QRect(int(box[0]), int(box[1]),
                                     int(box[2] - box[0]), int(box[3] - box[1])))
                thumb = QLabel()
                thumb.setPixmap(crop.scaled(
                    72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                row.addWidget(thumb, 0, Qt.AlignTop)

            # 右: 名称/操作/候选
            body = QWidget()
            v = QVBoxLayout(body)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(4)
            head = QHBoxLayout()
            conf_pct = f"{rec['confidence']*100:.0f}%" if rec["confidence"] else ""
            if rec["source"] == "whole":
                head.addWidget(badge(t("整图", "Whole image"), "#8E8E93"))
            if rec["source"] == "manual":
                head.addWidget(badge(t("手工", "Manual"), "#34C759"))
            if rec["source"] == "rebox":
                head.addWidget(badge(t("改框", "Reboxed"), "#FF9500"))
            if len(self.recs) > 1:
                if rec["rank"] == 1:
                    head.addWidget(badge(t("主鸟", "Main bird"), "#007AFF"))
                else:
                    main_btn = QPushButton(t("设为主鸟", "Set as main bird"))
                    main_btn.setCursor(Qt.PointingHandCursor)
                    main_btn.setStyleSheet("QPushButton{font-size:12px;padding:3px 9px;}")
                    main_btn.clicked.connect(
                        lambda _=False, rid=rec["record_id"]: self._set_main(rid))
                    head.addWidget(main_btn)
            title = QLabel(f"{sname(rec['cn'], rec['en'])}  "
                           f"<span style='color:#AEAEB2'>{conf_pct}</span>")
            title.setTextFormat(Qt.RichText)
            # 纯展示标签: 点鸟种名弹候选改鸟的功能已按用户要求移除
            # (2026-11-05)——改鸟种走下方候选下拉或「改鸟种…」按钮
            head.addWidget(title, 1)
            fix = QPushButton(t("改鸟种…", "Change species…"))
            fix.setCursor(Qt.PointingHandCursor)
            fix.setStyleSheet("QPushButton{font-size:12px;padding:3px 9px;}")
            fix.clicked.connect(lambda _=False, rid=rec["record_id"]:
                                self._pick_species(rid))
            head.addWidget(fix)
            # 单条删除: 清掉误识的次要鸟(如同种鸟只拍到屁股被认成别的种)
            dele = QPushButton(t("删除", "Delete"))
            dele.setCursor(Qt.PointingHandCursor)
            dele.setStyleSheet(
                f"QPushButton{{font-size:12px;padding:3px 9px;color:{theme.RED};}}")
            dele.setToolTip(
                t("删除这条识别记录（鸟种库同步去掉该鸟种）\n"
                  "适合清掉误识的次要鸟；主鸟用「设为主鸟」调整",
                  "Delete this identification record (the species library "
                  "is updated accordingly)\n"
                  "Good for clearing misidentified secondary birds; adjust "
                  "the main bird with \"Set as main bird\""))
            dele.clicked.connect(lambda _=False, rid=rec["record_id"]:
                                  self._delete_record(rid))
            head.addWidget(dele)
            v.addLayout(head)

            combo = QComboBox()
            options: list[tuple[str, str]] = []
            current_idx = 0
            try:
                top5 = json.loads(rec.get("top5_json") or "[]")
            except (TypeError, json.JSONDecodeError):
                top5 = []
            for cand in top5:
                s = self.lib.species_info(cand["code"])
                nm = sname(s["cn"], s["en"]) if s else cand["code"]
                mark = "✓ " if cand["code"] == rec["eff_code"] else ""
                options.append((f"{mark}{nm}  {cand.get('prob', 0)*100:.0f}%",
                                cand["code"]))
                if cand["code"] == rec["eff_code"]:
                    current_idx = len(options) - 1
            if not options:
                options = [(sname(rec["cn"], rec["en"]), rec["species_code"])]
            for label, code in options:
                combo.addItem(label, code)
            combo.setCurrentIndex(current_idx)
            combo.currentIndexChanged.connect(
                lambda _=0, rid=rec["record_id"], cb=combo:
                self._confirm(rid, cb.currentData()))
            v.addWidget(combo)
            row.addWidget(body, 1)
            self.records_box.addWidget(w)
        if not self.recs:
            tip = QLabel(t("尚未识别", "Not identified yet"))
            tip.setObjectName("Hint")
            self.records_box.addWidget(tip)
            add = QPushButton(t("＋ 标注鸟种…", "＋ Add species…"))
            add.setCursor(Qt.PointingHandCursor)
            add.clicked.connect(self._add_species)
            self.records_box.addWidget(add)

    def _delete_record(self, record_id: int):
        from PySide6.QtWidgets import QMessageBox
        rec = next((r for r in self.recs if r["record_id"] == record_id), None)
        name = sname(rec["cn"], rec["en"]) if rec else t("该记录", "this record")
        r = QMessageBox.question(
            self, t("删除识别记录", "Delete identification record"),
            t(f"从这张照片删除「{name}」的识别记录？\n\n"
              f"鸟种库里这个鸟种的照片数会同步减一"
              f"（如果它只出现在这张照片，鸟种会从库里消失）。",
              f"Delete the identification record for \"{name}\" from this "
              f"photo?\n\n"
              f"The species' photo count in the library drops by one "
              f"(if this is its only photo, the species disappears from "
              f"the library)."),
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        self.lib.remove_record(record_id)
        _, recs = self.lib.photo_detail(self.ids[self.index])
        self.recs = recs
        self._render_records()
        self.win.library_changed.emit()

    def _rebox_dialog(self):
        """工具栏「画框识别…」: 打开独立工具窗口框鸟重识别。"""
        if self.win is not None and self.win.worker is not None \
                and self.win.worker.isRunning():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, t("稍等", "Please wait"),
                t("后台正在批量识别，等它结束后再画框识别。",
                  "Batch recognition is running in the background; wait for "
                  "it to finish before using box identification."))
            return
        if self.assets is None:
            return
        from .rebox_dialog import ReboxDialog
        dlg = ReboxDialog(self.lib, self.win, self.ids[self.index], self)
        dlg.exec()

    def _confirm(self, record_id: int, code: str):
        self.lib.set_confirmed(record_id, code)
        _, recs = self.lib.photo_detail(self.ids[self.index])
        self.recs = recs
        self._render_records()
        self.win.library_changed.emit()

    def _set_main(self, record_id: int):
        self.lib.set_main_record(self.ids[self.index], record_id)
        _, recs = self.lib.photo_detail(self.ids[self.index])
        self.recs = recs
        self._render_records()
        self.win.library_changed.emit()

    def _pick_species(self, record_id: int):
        from .species_pick import SpeciesPickDialog
        dlg = SpeciesPickDialog(self.lib, t("改鸟种", "Change species"), self)
        if dlg.exec() and dlg.selected_code:
            self._confirm(record_id, dlg.selected_code)

    def _add_species(self):
        from .species_pick import SpeciesPickDialog
        dlg = SpeciesPickDialog(self.lib, t("标注鸟种", "Add species"), self)
        if dlg.exec() and dlg.selected_code:
            self.lib.add_manual_record(self.ids[self.index], dlg.selected_code)
            self._load()
            self.win.library_changed.emit()

    def _remove_photo(self):
        from PySide6.QtWidgets import QMessageBox
        photo, _ = self.lib.photo_detail(self.ids[self.index])
        r = QMessageBox.question(
            self, t("从鸟迹移除", "Remove from BirdTrace"),
            t("从鸟迹移除这张照片？\n\n"
              "原始照片文件不会被移动或删除，"
              "只是鸟迹不再记录它（识别记录、鸟点挂载一并移除）。",
              "Remove this photo from BirdTrace?\n\n"
              "The original photo file is not moved or deleted; BirdTrace "
              "simply stops tracking it (identification records and spot "
              "links are removed too)."),
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        pid = self.ids[self.index]
        self.lib.remove_photo(pid)
        self.ids.pop(self.index)
        if self.index >= len(self.ids):
            self.index = max(0, len(self.ids) - 1)
        self.win.library_changed.emit()
        if not self.ids:
            self.reject()
            return
        self._load()

    def _pick_spot(self):
        from .spot_dialog import SpotPickDialog
        dlg = SpotPickDialog(self.lib, self.photo, self)
        dlg.exec()
        if dlg.changed:
            self.win.library_changed.emit()
            self._load()

    def _share(self):
        from .share_dialog import ShareDialog
        dlg = ShareDialog(self.lib, self.win, self.ids[self.index])
        dlg.exec()

    # ---------- 导航 ----------
    def _prev(self):
        if self.index > 0:
            self.index -= 1
            self._load()

    def _next(self):
        if self.index < len(self.ids) - 1:
            self.index += 1
            self._load()
