# -*- coding: utf-8 -*-
"""分享卡对话框: 预览 + 主题/署名/地点选项 + 复制剪贴板 / 保存。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QScrollArea, QSlider,
                               QVBoxLayout, QWidget)

import json
import os

from ..core import regions
from ..core.sharecard import (ADJUST_ZOOM_MAX, DESIGN_W, XHS_LAYOUTS,
                              photo_placement, render_card, resolve_layout)
from ..i18n import t, sname
from ..theme.widgets import SegmentedControl, ToggleSwitch, make_card


def pinyin_spaced(cn: str) -> list[str]:
    """逐字音节列表(带声调), 与汉字一一对应; 多音节异常时回退整串。"""
    from pypinyin import Style, lazy_pinyin
    if not cn:
        return []
    pys = lazy_pinyin(cn, style=Style.TONE)
    return pys if len(pys) == len(cn) else ["".join(pys)]


def exif_parts_of(p: dict) -> dict:
    """拍摄参数三段(机身/镜头/焦·孔·快·ISO); 库里有什么显示什么。

    纯函数, 供单卡ShareDialog与批量导出(0.8-⑥)共用; 字段取自库内
    EXIF(照片文件丢失也能显示)。"""
    make = (p.get("make") or "").strip()
    model = (p.get("model") or "").strip()
    body = model if model and make and model.startswith(make) \
        else " ".join(x for x in (make, model) if x)
    shot: list[str] = []
    if p.get("focal_len"):
        try:
            shot.append(f"{float(p['focal_len']):g}mm")
        except (TypeError, ValueError):
            pass
    if p.get("fnum"):
        try:
            shot.append(f"f/{float(p['fnum']):g}")
        except (TypeError, ValueError):
            pass
    if p.get("exposure"):
        shot.append(f"{str(p['exposure']).strip()}s")
    if p.get("iso"):
        shot.append(f"ISO {p['iso']}")
    return {"body": body, "lens": str(p.get("lens") or "").strip(),
            "shot": " · ".join(shot)}


def rarity_info(code: str | None, region_id: str | None
                ) -> tuple[str | None, float | None, float | None]:
    """(罕见度档位, 百分位, 分值0-10) — 百分位/分值仅稀有/罕见档返回。

    分值=懂鸟式9.2风格(2026-11-10用户), 由同源百分位映射, 见
    prior_hint.rarity_score。异常/无数据/全球区域 = (None,)*3。
    单卡与批量导出共用。"""
    if not code:
        return None, None, None
    try:
        from ..core.prior_hint import get_hint
        hint = get_hint()
        tier = hint.rarity_tier(code, region_id)
        if tier not in ("稀有", "罕见"):  # i18n:ok
            return tier, None, None
        pct = hint.rarity_percentile(code, region_id)
        score = hint.rarity_score(code, region_id)
        return tier, pct, score
    except Exception:
        return None, None, None


def iucn_of(lib, code: str | None) -> str | None:
    """物种 IUCN 受威胁等级码(NT/VU/EN/CR/EW/EX); LC/无数据返回 None。

    供分享卡"濒危/易危"胶囊(2026-11-10用户): 只标受威胁物种,
    无危不显示。数据=species.iucn(assets iucn_status.json, 10812种)。"""
    if not code:
        return None
    try:
        # species_info返回sqlite3.Row(无.get方法), 用键访问+异常兜底
        row = lib.species_info(code)
        if row is None:
            return None
        v = row["iucn"]
        return v if v in ("NT", "VU", "EN", "CR", "EW", "EX") else None
    except (KeyError, IndexError, Exception):
        return None


def focus_point(lib, rec: dict | None, photo: dict) -> list | None:
    """框对准锚点(归一化[fx,fy], 0.8.4保头): 眼睛点优先(eye_json缓存,
    无则惰性算一次并落库)→检测框中心→None(裁剪居中)。
    rec=单卡v_records行(有id)或批量share_card行(有record_id)均可;
    眼点推理在导出/渲染路径, 与识别管线零耦合(keypoints.eye_for_photo)。"""
    if not rec or not photo.get("width") or not photo.get("height"):
        return None
    if rec.get("eye_json"):
        try:
            v = json.loads(rec["eye_json"])
            return [float(v[0]), float(v[1])]
        except Exception:
            pass
    box = None
    if rec.get("box_json"):
        try:
            box = json.loads(rec["box_json"])
        except Exception:
            box = None
    w, h = photo["width"], photo["height"]
    center = [(box[0] + box[2]) / 2 / w, (box[1] + box[3]) / 2 / h]         if box else None
    if not box:
        return center
    from ..ai.keypoints import eye_for_photo
    pt = eye_for_photo(photo.get("path") or "", box)
    if not pt:
        return center                      # 无眼点回落框心(下次再试)
    pt[0] = min(max(pt[0], 0.0), 1.0)
    pt[1] = min(max(pt[1], 0.0), 1.0)
    try:
        rid = rec.get("record_id") or rec.get("id")
        if rid:
            lib.conn.execute("UPDATE records SET eye_json=? WHERE id=?",
                             (json.dumps(pt), rid))
        else:
            lib.conn.execute("UPDATE records SET eye_json=? "
                             "WHERE photo_id=? AND rank=1",
                             (json.dumps(pt), rec.get("photo_id")))
        lib.conn.commit()
    except Exception:
        pass
    return pt


class _PreviewLabel(QLabel):
    """卡预览宿主(0.8.5): 鼠标/滚轮事件转发给ShareDialog做手动构图。
    必须AlignCenter——_pv_phys按居中算坐标, 左对齐时命中测试整体偏移
    (0.8.5实测: 卡贴左+拖动"不灵"的真因)。"""

    def __init__(self, host):
        super().__init__()
        self.host = host
        self.setAlignment(Qt.AlignCenter)

    def mousePressEvent(self, e):
        self.host._pv_press(e)

    def mouseMoveEvent(self, e):
        self.host._pv_move(e)

    def mouseReleaseEvent(self, e):
        self.host._pv_release(e)

    def mouseDoubleClickEvent(self, e):
        self.host._pv_dbl(e)

    def wheelEvent(self, e):
        self.host._pv_wheel(e)


class ShareDialog(QDialog):
    def __init__(self, lib, win, photo_id: int):
        super().__init__(win)
        self.lib = lib
        self.win = win
        self.photo_id = photo_id
        self.setWindowTitle(t("生成分享卡", "Create share card"))
        self.setModal(True)
        # 0.8.5重做(用户: 下方预览太小看不清): 左预览右选项+默认最大化
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        self.setMinimumSize(980, 640)
        self._adjust = None             # 手动构图{zoom,ox,oy}; None=自动
        self._view = {"mode": "fit"}    # 预览缩放: fit=适应 | pct=百分比
        self._view_s = 1.0              # 预览像素/卡物理像素
        self._lay_key = None            # 解析出的固定版式key(classic=None)
        self._zh = 0                    # 照片区物理高(px)
        self._drag = None
        self._build_ui()
        self._update()
        # 默认窗口(0.8.5用户: 卡都是竖图, 不要最大化——竖向用满屏幕,
        # 左右紧凑: 宽=最宽卡(3:4)按高适配的宽度+右栏, 留最大化按钮可手动放大)
        scr = QGuiApplication.primaryScreen().availableGeometry()
        h = scr.height() - 48
        w = min(scr.width() - 80, round(h * 0.78) + 430)
        self.resize(max(self.minimumWidth(), w), h)

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(12)

        # ---- 左: 预览(视图缩放工具条+滚动视口, 0.8.5) ----
        left = QVBoxLayout()
        left.setSpacing(8)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.vz_out = QPushButton("−")
        self.vz_out.setFixedWidth(34)
        self.vz_out.setToolTip(t("缩小预览", "Zoom out preview"))
        self.vz_out.clicked.connect(lambda: self._view_zoom(1 / 1.25))
        self.vz_pct = QLabel(t("适应", "Fit"))
        self.vz_pct.setMinimumWidth(56)
        self.vz_pct.setAlignment(Qt.AlignCenter)
        self.vz_in = QPushButton("＋")
        self.vz_in.setFixedWidth(34)
        self.vz_in.setToolTip(t("放大预览", "Zoom in preview"))
        self.vz_in.clicked.connect(lambda: self._view_zoom(1.25))
        self.vz_fit = QPushButton(t("适应窗口", "Fit window"))
        self.vz_fit.setCursor(Qt.PointingHandCursor)
        self.vz_fit.clicked.connect(self._view_fit)
        self.vz_100 = QPushButton("100%")
        self.vz_100.setCursor(Qt.PointingHandCursor)
        self.vz_100.clicked.connect(lambda: self._view_set(1.0))
        for w in (self.vz_out, self.vz_pct, self.vz_in, self.vz_fit,
                  self.vz_100):
            bar.addWidget(w)
        bar.addStretch(1)
        self.crop_hint = QLabel(
            t("照片区拖动平移 · 滚轮缩放构图 · 双击复位 · Ctrl+滚轮缩放预览",
              "Drag the photo to pan · wheel to zoom framing · "
              "double-click resets · Ctrl+wheel zooms the preview"))
        self.crop_hint.setObjectName("Hint")
        bar.addWidget(self.crop_hint)
        left.addLayout(bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.preview_host = _PreviewLabel(self)
        self.preview_host.setCursor(Qt.OpenHandCursor)
        self.scroll.setWidget(self.preview_host)
        left.addWidget(self.scroll, 1)
        root.addLayout(left, 1)

        # ---- 右: 选项面板(固定宽可滚动) + 底部动作钮 ----
        right = QVBoxLayout()
        right.setSpacing(10)
        panel = QScrollArea()
        panel.setWidgetResizable(True)
        panel.setFixedWidth(368)
        host = QWidget()
        pv = QVBoxLayout(host)
        pv.setContentsMargins(0, 0, 8, 0)
        pv.setSpacing(10)

        # 样式卡(选项与旧版一致)
        opt_card, opt = make_card(t("样式", "Style"))
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel(t("主题", "Theme")))
        self.theme_seg = SegmentedControl([t("浅色", "Light"), t("深色", "Dark")])
        self.theme_seg.changed.connect(lambda _=0: self._update())
        theme_row.addWidget(self.theme_seg, 1)
        opt.addLayout(theme_row)

        # 分辨率档位(2026-11-10用户: 数毛细节): 标准2000/高清3000/原图,
        # 高清单卡文件更大, 适合存档/图床; 原图=卡宽取照片像素宽,
        # 照片1:1零重采样(竖图即原图短边)
        res_row = QHBoxLayout()
        res_row.addWidget(QLabel(t("分辨率", "Resolution")))
        self.res_seg = SegmentedControl([t("标准 2000", "Standard 2000"),
                                         t("高清 3000", "HD 3000"),
                                         t("原图", "Original")])
        self.res_seg.setToolTip(t(
            "原图档：卡片宽度=照片自身像素宽（竖图即原图短边），"
            "照片不做任何缩放；小图钳到1200防止文字过小。",
            "Original: card width = photo's own pixels (the short side "
            "for portrait photos), photo untouched; tiny photos clamp "
            "to 1200 so text stays readable."))
        self.res_seg.changed.connect(lambda _=0: self._update())
        res_row.addWidget(self.res_seg, 1)
        opt.addLayout(res_row)

        # 版式(2026-11-11小红书; 2026-11-17竖版改3:5即9:15): 自动=按照片
        # 方向(横3:4/竖3:5全屏); 3:4=feed预览不裁字; 经典=原自适应高度
        lay_row = QHBoxLayout()
        lay_row.addWidget(QLabel(t("版式", "Layout")))
        self.lay_seg = SegmentedControl(
            [t("自动", "Auto"), t("竖 3:5", "Tall 3:5"),
             t("横 3:4", "Wide 3:4"), t("经典", "Classic")])
        self.lay_seg.setToolTip(t(
            "自动：按照片方向选版式（横图3:4，竖图/方图3:5）。\n"
            "3:5（=9:15）=小红书竖版全屏图文；3:4=信息流预览完整；"
            "经典=旧自适应。",
            "Auto: pick by photo orientation (landscape 3:4, "
            "portrait/square 3:5).\n3:5 (= 9:15) is Xiaohongshu's "
            "fullscreen post; 3:4 previews fully in the feed; "
            "Classic = old adaptive."))
        self.lay_seg.changed.connect(lambda _=0: self._update())
        lay_row.addWidget(self.lay_seg, 1)
        opt.addLayout(lay_row)

        life_row = QHBoxLayout()
        life_row.addWidget(QLabel(t("显示 Life # 序号", "Show Life #")))
        self.lifer_toggle = ToggleSwitch(True)
        self.lifer_toggle.toggled.connect(lambda _v: self._update())
        life_row.addStretch(1)
        life_row.addWidget(self.lifer_toggle)
        opt.addLayout(life_row)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(t("拍摄者", "Photographer")))
        self.name_edit = QLineEdit(self.lib.get_setting("photographer_name", ""))
        self.name_edit.setPlaceholderText(t("你的名字", "Your name"))
        self.name_edit.setClearButtonEnabled(True)
        self.name_edit.textChanged.connect(lambda _t: self._update())
        name_row.addWidget(self.name_edit, 1)
        opt.addLayout(name_row)

        place_row = QHBoxLayout()
        place_row.addWidget(QLabel(t("地点", "Location")))
        self.place_edit = QLineEdit(self._default_place())
        self.place_edit.setPlaceholderText(
            t("如: 上海市 / 崇明东滩", "e.g. Shanghai / Chongming Dongtan"))
        self.place_edit.textChanged.connect(lambda _t: self._update())
        place_row.addWidget(self.place_edit, 1)
        opt.addLayout(place_row)

        # 拍摄参数(EXIF: 机身/镜头/焦距/光圈/快门/ISO, 有什么显示什么)
        exif_row = QHBoxLayout()
        exif_row.addWidget(QLabel(t("拍摄参数", "Camera data")))
        self.exif_toggle = ToggleSwitch(True)
        self.exif_toggle.toggled.connect(self._on_exif_toggle)
        exif_row.addStretch(1)
        exif_row.addWidget(self.exif_toggle)
        opt.addLayout(exif_row)
        self.exif_hint = QLabel()
        self.exif_hint.setObjectName("Hint")
        self.exif_hint.setWordWrap(True)
        self.exif_hint.setTextInteractionFlags(Qt.TextSelectableByMouse)
        opt.addWidget(self.exif_hint)
        pv.addWidget(opt_card)

        # 照片构图卡(0.8.5手动裁切: 滑杆缩放+自动复位)
        crop_card, crop = make_card(t("照片构图", "Photo framing"))
        zr = QHBoxLayout()
        zr.addWidget(QLabel(t("缩放", "Zoom")))
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(100, 300)
        self.zoom_slider.setValue(100)
        self.zoom_slider.valueChanged.connect(self._on_slider)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(46)
        zr.addWidget(self.zoom_slider, 1)
        zr.addWidget(self.zoom_label)
        crop.addLayout(zr)
        self.auto_btn = QPushButton(t("恢复自动构图", "Reset to auto"))
        self.auto_btn.setCursor(Qt.PointingHandCursor)
        self.auto_btn.clicked.connect(self._reset_adjust)
        crop.addWidget(self.auto_btn)
        self.crop_hint2 = QLabel(
            t("自动构图＝眼睛优先对准鸟心；手动调整后以你为准，出片即所见。",
              "Auto framing targets the bird's eye; once you adjust, "
              "yours wins — what you see is what you get."))
        self.crop_hint2.setObjectName("Hint")
        self.crop_hint2.setWordWrap(True)
        crop.addWidget(self.crop_hint2)
        pv.addWidget(crop_card)
        pv.addStretch(1)
        panel.setWidget(host)
        right.addWidget(panel, 1)

        # 动作(右栏底部固定, 不随选项滚动)
        row = QHBoxLayout()
        b_copy = QPushButton(t("复制到剪贴板", "Copy to clipboard"))
        b_copy.setObjectName("Primary")
        b_copy.setCursor(Qt.PointingHandCursor)
        b_copy.clicked.connect(self._copy)
        b_save = QPushButton(t("保存为图片…", "Save as image…"))
        b_save.setCursor(Qt.PointingHandCursor)
        b_save.clicked.connect(self._save)
        row.addWidget(b_copy, 1)
        row.addWidget(b_save, 1)
        right.addLayout(row)
        root.addLayout(right)

        self._build_info()


    def _default_place(self) -> str:
        """地点行默认值: 国别·省级, 有鸟点追加紧排"·鸟点名"(简称优先,
        可编辑; 发稀有鸟前手动删, 鸟点=精确位置)。"""
        photo, _recs = self.lib.photo_detail(self.photo_id)
        rid = (photo or {}).get("region_id")
        if not rid or rid == "GLOBAL":
            return ""
        place = regions.region_display(rid)
        spot = (photo or {}).get("spot_short") or (photo or {}).get("spot_name")
        if spot:
            place += "·" + spot
        return place

    def _build_info(self):
        photo, recs = self.lib.photo_detail(self.photo_id)
        self.photo = photo
        # 原图(手动构图交互数学用; 文件缺失=null→交互自动禁用)
        self._src = QPixmap(photo.get("path") or "")
        rec = recs[0] if recs else None
        code = rec["eff_code"] if rec else None
        self.species = self.lib.species_info(code) if code else None
        # 框对准锚点(0.8.4保头): 眼睛点优先(惰性算一次落库)→框心→None
        self._focus = focus_point(self.lib, rec, photo)
        if rec and rec.get("box_json") and photo.get("width") \
                and photo.get("height"):
            try:
                x1, y1, x2, y2 = json.loads(rec["box_json"])
                w, h = photo["width"], photo["height"]
                self._focus = ((x1 + x2) / 2 / w, (y1 + y2) / 2 / h)
            except Exception:
                self._focus = None
        self.taken = (photo.get("dt_original") or photo.get("added_at") or "")[:10]
        # 拍摄者: EXIF Artist 优先, 否则设置里的名字
        self.photographer = photo.get("artist") or self.lib.get_setting("photographer_name", "")
        if self.photographer and not self.name_edit.text():
            self.name_edit.setText(self.photographer)
        # 拍摄参数摘要(取自库内EXIF字段, 照片文件丢失也能显示)
        parts = self._exif_parts(respect_toggle=False)
        summary = " · ".join(v for v in parts.values() if v)
        text = summary if summary else t("照片未检测到拍摄参数",
                                         "No camera data in this photo")
        # 原图不可读(0.8-②): 卡片会没有照片, 提前说清原因
        from ..core.offline import OFFLINE, OK, drive_label, drive_root, path_state
        st = path_state(photo["path"])
        if st == OFFLINE:
            drv = drive_label(drive_root(photo["path"]))
            text = t(f"⚠️ 原图离线（{drv} 未接入），插回硬盘后再生成分享卡。\n",
                     f"⚠️ Original offline (drive {drv} not connected); "
                     "reconnect it before making the card.\n") + text
        elif st != OK:
            text = t("⚠️ 原图不在原位置，分享卡将没有照片。\n",
                     "⚠️ Original not at its recorded location; the card "
                     "will have no photo.\n") + text
        self.exif_hint.setText(text)
        self.exif_hint.setEnabled(self.exif_toggle.isChecked())

    def _on_exif_toggle(self, on: bool):
        self.exif_hint.setEnabled(on)
        self._update()

    def _exif_parts(self, respect_toggle: bool = True) -> dict:
        """拍摄参数三段(勾选后); 取自库内EXIF字段。"""
        if respect_toggle and not self.exif_toggle.isChecked():
            return {}
        return exif_parts_of(self.photo or {})

    def _card_info(self) -> dict:
        species = self.species
        cn = species["cn"] if species else None
        # 大字标题: sname取当前语言名(英文模式为英文名)
        title = sname(cn, species["en"]) if species \
            else t("未识别", "Unidentified")
        pys = pinyin_spaced(title)
        if len(pys) != len(title):   # 英文标题(非逐字汉字)不叠画拼音
            pys = []
        lifer_no = None
        if species and self.lifer_toggle.isChecked():
            lifer_no = self.lib.lifer_no_for_species(species["code"])
        # 罕见度(参考birdtrace/慧眼观鸟分享卡): 按照片批次地区计算;
        # 稀有/罕见再取百分位("罕见 · 前 3%", 0.8方案⑤)
        code = species["code"] if species else None
        rarity, rarity_pct, rarity_score = rarity_info(
            code, self.photo.get("region_id"))
        return {
            "cn": title,
            "pinyin": pys,
            "en": species["en"] if species else "",
            "sci": species["sci"] if species else "",
            "lifer_no": lifer_no,
            "rarity": rarity,
            "rarity_pct": rarity_pct,
            "rarity_score": rarity_score,
            "iucn": iucn_of(self.lib, code),
            "photographer": self.name_edit.text().strip(),
            "date": self.taken,
            "place": self.place_edit.text().strip(),
            "exif": self._exif_parts(),
            "focus": getattr(self, "_focus", None),
        }

    def _update(self, interact_w: int | None = None):
        """重渲卡片。interact_w=拖动中的低清预览宽(松手/出片前必回全分辨率)。"""
        theme = "dark" if self.theme_seg.currentIndex() == 1 else "light"
        # BIRDTRACE_CARD_WIDTH: 测试钩子(强制卡宽→k=1)。offscreen无字体
        # 环境下画笔scale(k≠1)时drawText不出墨(tofu都不画), ink类测试
        # 需k=1才能断言文字渲染; 真实运行不受影响(见sharecard DESIGN_W)
        env_w = os.environ.get("BIRDTRACE_CARD_WIDTH")
        if env_w:
            w = int(env_w)
        elif interact_w:
            w = interact_w
        elif getattr(self, "res_seg", None) is not None \
                and self.res_seg.currentIndex() == 2:
            # 原图档: 卡宽=照片像素宽(竖图即短边), 照片1:1零重采样;
            # 小图下限1200(再小文字物理尺寸过小)
            w = max(1200, int(self.photo.get("width") or 2000))
        elif getattr(self, "res_seg", None) is not None \
                and self.res_seg.currentIndex() == 1:
            w = 3000
        else:
            w = 2000
        layout = ("auto", "3:5", "3:4", "classic")[
            self.lay_seg.currentIndex()
            if getattr(self, "lay_seg", None) is not None else 0]
        self.pm = render_card(self.photo["path"], self._card_info(), theme,
                              width=w, layout=layout, adjust=self._adjust)
        # 版式key与照片区几何(手动构图交互用, 数学与渲染单源)
        if not self._src.isNull():
            self._lay_key = resolve_layout(self._src.width(),
                                           self._src.height(), layout)
        else:
            self._lay_key = None
        self._zh = round(XHS_LAYOUTS[self._lay_key][1]
                         * self.pm.width() / DESIGN_W) if self._lay_key else 0
        manual_ok = self._lay_key is not None
        self.zoom_slider.setEnabled(manual_ok)
        self.crop_hint2.setEnabled(manual_ok)
        self.auto_btn.setEnabled(manual_ok and self._adjust is not None)
        self._sync_slider()
        self._show_preview()

    # ---- 预览缩放(看图辅助, 不影响出片分辨率) ----
    def _show_preview(self):
        if not hasattr(self, "pm") or self.pm.isNull():
            return
        if self._view["mode"] == "fit":
            # 整卡一屏看全: 宽高都适配视口(卡是长图, 只按宽缩看不到底)
            vw = max(200, self.scroll.width() - 28)
            vh = max(240, self.scroll.height() - 28)
            scaled = self.pm.scaled(vw, vh, Qt.KeepAspectRatio,
                                    Qt.SmoothTransformation)
        else:
            scaled = self.pm.scaled(
                max(40, round(self.pm.width() * self._view["pct"])),
                max(40, round(self.pm.height() * self._view["pct"])),
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._view_s = scaled.width() / max(1, self.pm.width())
        self.preview_host.setPixmap(scaled)
        self.vz_pct.setText(t("适应", "Fit")
                            if self._view["mode"] == "fit"
                            else f"{round(self._view_s * 100)}%")

    def _view_zoom(self, factor: float):
        self._view_set(self._view_s * factor)

    def _view_set(self, pct: float):
        self._view = {"mode": "pct", "pct": min(4.0, max(0.1, pct))}
        self._show_preview()

    def _view_fit(self):
        self._view = {"mode": "fit"}
        self._show_preview()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._view["mode"] == "fit":
            self._show_preview()

    # ---- 手动构图(0.8.5): 拖动平移/滚轮缩放(锚=光标)/双击与按钮复位 ----
    def _pv_phys(self, e):
        """事件位置→卡物理像素坐标(None=卡外)。"""
        pm = self.preview_host.pixmap()
        if pm is None or pm.isNull() or self._view_s <= 0:
            return None
        ox = (self.preview_host.width() - pm.width()) / 2
        oy = (self.preview_host.height() - pm.height()) / 2
        pos = e.position()
        return ((pos.x() - ox) / self._view_s,
                (pos.y() - oy) / self._view_s)

    def _in_photo(self, xy) -> bool:
        return (self._lay_key is not None and xy is not None
                and 0 <= xy[0] <= self.pm.width()
                and 0 <= xy[1] <= self._zh)

    def _placement(self, adj=None):
        """当前几何下的照片定位: adj=None且未手动=自动(带focus); 其余按adj。"""
        if adj is None and self._adjust is None:
            return photo_placement(self._src.width(), self._src.height(),
                                   self.pm.width(), self._zh, self._focus)
        a = self._adjust if adj is None else adj
        return photo_placement(self._src.width(), self._src.height(),
                               self.pm.width(), self._zh, None, a)

    def _ensure_adjust(self):
        """进入手动模式: 以自动定位结果为起点(无缝衔接)。"""
        if self._adjust is None:
            pl = self._placement()
            self._adjust = {"zoom": 1.0,
                            "ox": pl["sx"] / pl["rx"] if pl["rx"] else 0.5,
                            "oy": pl["sy"] / pl["ry"] if pl["ry"] else 0.5}
        return self._adjust

    def _sync_slider(self):
        z = round((self._adjust or {}).get("zoom", 1.0) * 100)
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(min(300, max(100, z)))
        self.zoom_slider.blockSignals(False)
        self.zoom_label.setText(f"{z}%")

    def _on_slider(self, val: int):
        if self._lay_key is None:
            return
        adj = self._ensure_adjust()
        pl = self._placement(adj)
        new = min(ADJUST_ZOOM_MAX, max(1.0, val / 100))
        self.zoom_label.setText(f"{round(new * 100)}%")
        if abs(new - adj["zoom"]) < 1e-6:
            return
        grow = new / adj["zoom"]
        adj["zoom"] = new
        pl2 = photo_placement(self._src.width(), self._src.height(),
                              self.pm.width(), self._zh, None,
                              {"zoom": new, "ox": 0.0, "oy": 0.0})
        ax, ay = self.pm.width() / 2, self._zh / 2      # 锚=窗口中心
        if pl2["rx"]:
            adj["ox"] = min(1.0, max(0.0,
                                     ((pl["sx"] + ax) * grow - ax)
                                     / pl2["rx"]))
        if pl2["ry"]:
            adj["oy"] = min(1.0, max(0.0,
                                     ((pl["sy"] + ay) * grow - ay)
                                     / pl2["ry"]))
        self.auto_btn.setEnabled(True)
        self._update()

    def _reset_adjust(self):
        self._adjust = None
        self._update()

    def _pv_press(self, e):
        if e.button() != Qt.LeftButton \
                or not self._in_photo(self._pv_phys(e)):
            e.ignore()
            return
        self._ensure_adjust()
        self.auto_btn.setEnabled(True)
        self._drag = e.globalPosition().toPoint()
        self.preview_host.setCursor(Qt.ClosedHandCursor)

    def _pv_move(self, e):
        if not self._drag:
            return
        now = e.globalPosition().toPoint()
        self._pan_by((now.x() - self._drag.x()) / self._view_s,
                     (now.y() - self._drag.y()) / self._view_s)
        self._drag = now

    def _pv_release(self, e):
        if self._drag:
            self._drag = None
            self.preview_host.setCursor(Qt.OpenHandCursor)
            self._update()               # 松手回全分辨率

    def _pv_dbl(self, e):
        if self._in_photo(self._pv_phys(e)):
            self._reset_adjust()

    def _pv_wheel(self, e):
        if e.modifiers() & Qt.ControlModifier:
            d = e.angleDelta().y()
            if d:
                self._view_zoom(1.1 if d > 0 else 1 / 1.1)
            return
        xy = self._pv_phys(e)
        if not self._in_photo(xy):
            e.ignore()                   # 照片区外=正常滚动翻页
            return
        d = e.angleDelta().y()
        if d:
            self._crop_zoom(xy[0], xy[1], 1.1 if d > 0 else 1 / 1.1)

    def _pan_by(self, dx: float, dy: float):
        """抓取式平移(0.8.5实测修方向): 照片跟手——手往右(dx>0)照片右移
        =裁切窗口左移(sx减小)。旧实现sx+dx正好相反, 手和画面各走各的。"""
        adj = self._adjust
        pl = self._placement(adj)
        if pl["rx"]:
            adj["ox"] = min(1.0, max(0.0, (pl["sx"] - dx) / pl["rx"]))
        if pl["ry"]:
            adj["oy"] = min(1.0, max(0.0, (pl["sy"] - dy) / pl["ry"]))
        self._update(interact_w=1400)     # 拖动中低清, 松手回全分辨率

    def _crop_zoom(self, ax: float, ay: float, factor: float):
        adj = self._ensure_adjust()
        pl = self._placement(adj)                      # 旧窗口
        old = adj["zoom"]
        adj["zoom"] = min(ADJUST_ZOOM_MAX, max(1.0, old * factor))
        if adj["zoom"] == old:
            return
        grow = adj["zoom"] / old
        pl2 = photo_placement(self._src.width(), self._src.height(),
                              self.pm.width(), self._zh, None,
                              {"zoom": adj["zoom"], "ox": 0.0, "oy": 0.0})
        if pl2["rx"]:                    # 锚=光标: 该点画面不动
            adj["ox"] = min(1.0, max(0.0,
                                     ((pl["sx"] + ax) * grow - ax)
                                     / pl2["rx"]))
        if pl2["ry"]:
            adj["oy"] = min(1.0, max(0.0,
                                     ((pl["sy"] + ay) * grow - ay)
                                     / pl2["ry"]))
        self.auto_btn.setEnabled(True)
        self._update()

    def _copy(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setPixmap(self.pm)
        self.accept()

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(
            self, t("保存分享卡", "Save share card"),
            f"bird_{self.species['cn'] if self.species else 'card'}.png",
            t("PNG 图片 (*.png)", "PNG image (*.png)"))
        if path:
            self.pm.save(path, "PNG")
            self.accept()
