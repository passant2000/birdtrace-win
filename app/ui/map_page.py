# -*- coding: utf-8 -*-
"""鸟点地图: 高德JS API交互地图 + 鸟点管理合一模块。

左侧: 地名搜索(高德Web服务API) + 鸟点列表; 右侧: 高德交互地图。
地图marker点按 → 弹卡(详情/编辑); 选点模式点地图取WGS84坐标, 可直接建点。
鸟点详情(物种清单+照片流)为对话框, 坐标系换算见 amap_view.py。
"""
from __future__ import annotations

import re
from urllib.parse import quote

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import (QNetworkAccessManager, QNetworkReply,
                               QNetworkRequest)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..core.gcj02 import gcj02_to_wgs84
from ..core.spots import format_coord
from ..i18n import t, sname
from ..media import ensure_thumbnail
from .. import theme
from ..version import VERSION
# amap_view(QtWebEngine)惰性导入: 启动不加载194MB WebEngine DLL,
# 首次创建地图控件时再import(模块级导入会被main_window的顶层import连带触发)
from .viewer import PhotoViewer

UA = f"BirdTraceWin/{VERSION} (personal photo map)"


# ============================ 高德POI搜索(共享) ============================
class PoiSearcher(QObject):
    """地名搜索(带350ms防抖), 数据源=高德「Web服务」POI(GCJ02, 中国POI全)。

    内置Key(设置页可覆盖自填)。统一 poi dict:
    {name, location:"lon,lat", wgs:bool, addr:str}。

    results(list)   — poi dicts
    failed(str)     — 网络失败/无Key原因
    """
    results = Signal(list)
    failed = Signal(str)

    def __init__(self, lib, parent=None):
        super().__init__(parent)
        self._lib = lib
        self._nam = QNetworkAccessManager(self)
        self._nam.finished.connect(self._on_reply)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(350)
        self._debounce.timeout.connect(self._do_search)
        self._pending = ""

    def search(self, text: str):
        self._pending = text.strip()
        if not self._pending:
            self._debounce.stop()
            self.results.emit([])
            return
        self._debounce.start()

    def _do_search(self):
        # 高德Key必须是「Web服务」类型——JS API/Android类型Key服务端不认
        # (平台校验)。MapTiler回退已删(2026-11-03): OSM中文POI覆盖极差
        # ("世纪公园"搜不到=5080机元凶), 且内置Key后该分支本就不可达。
        from .amap_view import DEFAULT_WEB_KEY
        amap_key = self._lib.get_setting("amap_key", "") or DEFAULT_WEB_KEY
        if not amap_key:
            self.failed.emit(t(
                "地名搜索不可用：请在 设置 → 地图 填写高德「Web服务」Key（免费申请）。",
                "Place search unavailable: add a free Amap \"Web Service\" "
                "key in Settings → Map."))
            return
        url = (f"https://restapi.amap.com/v3/place/text?key={amap_key}"
               f"&keywords={quote(self._pending)}&offset=8&page=1"
               f"&extensions=base")
        self._nam.get(QNetworkRequest(QUrl(url)))

    def _on_reply(self, reply):
        u = reply.url().toString()
        if "restapi.amap.com" not in u:
            return
        data = bytes(reply.readAll())
        err = reply.error()
        reply.deleteLater()
        import json
        try:
            obj = json.loads(data)
        except (ValueError, TypeError):
            obj = {}
        self.results.emit(self._parse_amap(obj, err))

    def _parse_amap(self, obj: dict, err) -> list:
        if err != QNetworkReply.NetworkError.NoError and not obj.get("pois"):
            info = obj.get("info", t("网络错误", "Network error"))
            self.failed.emit(t(f"搜索失败：{info}", f"Search failed: {info}"))
            return []
        if obj.get("status") != "1":
            msg = obj.get("info", t("搜索失败", "Search failed"))
            s_code = str(obj.get("infocode", ""))
            if "INVALID_USER_KEY" in str(msg):
                msg = t("高德Key无效，请在设置页检查",
                        "Invalid Amap key, please check it in Settings")
            elif "USERKEY_PLAT_NOMATCH" in str(msg) or s_code == "10009":
                # 最常见误区: 填了JS API/Android类型的Key——地点搜索REST
                # 接口只认「Web服务」类型Key, 服务端按类型校验不通用
                msg = t(
                    "Key类型不匹配：地点搜索需要「Web服务」类型Key"
                    "（高德控制台→我的应用→添加Key→服务平台选Web服务）",
                    "Key type mismatch: place search needs a "
                    "\"Web Service\" type key (Amap console → My apps → "
                    "Add key → platform: Web Service)")
            self.failed.emit(t(f"搜索失败：{msg}", f"Search failed: {msg}"))
            return []
        return [dict(p, wgs=False) for p in obj.get("pois", [])]


def poi_location_wgs84(p: dict) -> tuple[float, float] | None:
    """poi dict → (lat, lon) WGS84; 解析失败返回None。

    高德结果为GCJ-02需纠偏; wgs=True的poi(如有)直过。"""
    try:
        lon_s, lat_s = p["location"].split(",")
        g_lat, g_lon = float(lat_s), float(lon_s)
    except (KeyError, ValueError):
        return None
    if p.get("wgs"):
        return g_lat, g_lon
    return gcj02_to_wgs84(g_lat, g_lon)


# ============================ 鸟点编辑/选点 ============================
class SpotEditDialog(QDialog):
    """新建/编辑鸟点: 名称/备注/坐标(可地图选点)。"""

    def __init__(self, lib, spot: dict | None = None, parent=None,
                 preset_lat: float | None = None, preset_lon: float | None = None):
        super().__init__(parent)
        self.lib = lib
        self.spot = spot
        self.created_id: int | None = None
        self.setWindowTitle(t("编辑鸟点", "Edit spot") if spot
                            else t("新建鸟点", "New spot"))
        self.setMinimumWidth(380)
        form = QFormLayout(self)
        form.setSpacing(10)

        self.name_edit = QLineEdit(spot["name"] if spot else "")
        self.name_edit.setPlaceholderText(t("如：奥森南园 / 野鸭湖观鸟堤",
                                           "e.g. Olympic Forest Park / Wild Duck Lake"))
        form.addRow(t("名称", "Name"), self.name_edit)
        self.note_edit = QLineEdit(spot["note"] if spot else "")
        self.note_edit.setPlaceholderText(t("备注（可省）", "Note (optional)"))
        form.addRow(t("备注", "Note"), self.note_edit)
        lat0 = spot["lat"] if spot else preset_lat
        lon0 = spot["lon"] if spot else preset_lon
        self.lat_edit = QLineEdit(f"{lat0:.4f}" if lat0 is not None else "")
        self.lat_edit.setPlaceholderText(t("纬度，如 40.0035", "Latitude, e.g. 40.0035"))
        form.addRow(t("纬度", "Latitude"), self.lat_edit)
        self.lon_edit = QLineEdit(f"{lon0:.4f}" if lon0 is not None else "")
        self.lon_edit.setPlaceholderText(t("经度，如 116.3950", "Longitude, e.g. 116.3950"))
        form.addRow(t("经度", "Longitude"), self.lon_edit)

        pick_row = QHBoxLayout()
        b_pick = QPushButton(t("在地图上选点…", "Pick on map…"))
        b_pick.setCursor(Qt.PointingHandCursor)
        b_pick.clicked.connect(self._pick_on_map)
        pick_row.addWidget(b_pick)
        pick_row.addStretch(1)
        form.addRow(pick_row)

        btns = QHBoxLayout()
        if spot:                      # 编辑态: 删除入口(用户要求随处可删)
            b_del = QPushButton(t("删除鸟点", "Delete spot"))
            b_del.setCursor(Qt.PointingHandCursor)
            b_del.clicked.connect(self._delete)
            btns.addWidget(b_del)
        btns.addStretch(1)
        ok = QPushButton(t("保存", "Save"))
        ok.setObjectName("Primary")
        ok.setCursor(Qt.PointingHandCursor)
        ok.clicked.connect(self._save)
        cancel = QPushButton(t("取消", "Cancel"))
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        form.addRow(btns)

    def _delete(self):
        if not self.spot:
            return
        r = QMessageBox.question(
            self, t("删除鸟点", "Delete spot"),
            t(f"删除「{self.spot['name']}」？\n照片不会被删除，只是解除挂载。",
              f"Delete “{self.spot['name']}”?\nPhotos will not be deleted, "
              "only unlinked from this spot."))
        if r == QMessageBox.Yes:
            self.lib.delete_spot(self.spot["id"])
            self.accept()
            self.spot = None          # 供调用方识别"已删除"而非"保存"

    def _pick_on_map(self):
        try:
            lat = float(self.lat_edit.text().strip())
            lon = float(self.lon_edit.text().strip())
        except ValueError:
            lat = lon = None
        dlg = MapPickDialog(self.lib, lat, lon, self)
        if dlg.exec() and dlg.picked_wgs84:
            self.lat_edit.setText(f"{dlg.picked_wgs84[0]:.4f}")
            self.lon_edit.setText(f"{dlg.picked_wgs84[1]:.4f}")

    def _save(self):
        name = self.name_edit.text().strip()
        if not name:
            self.name_edit.setFocus()
            return
        lat = self._num(self.lat_edit.text())
        lon = self._num(self.lon_edit.text())
        note = self.note_edit.text().strip()
        if self.spot:
            self.lib.update_spot(self.spot["id"], name=name, note=note,
                                 lat=lat, lon=lon)
        else:
            self.created_id = self.lib.create_spot(name, lat, lon, note)
        self.accept()

    @staticmethod
    def _num(s: str) -> float | None:
        try:
            return float(s.strip())
        except (ValueError, AttributeError):
            return None


class MapPickDialog(QDialog):
    """地图选点: 确认后经 picked_wgs84 返回WGS84坐标。顶部可搜地名快速跳转。"""

    def __init__(self, lib, lat=None, lon=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("在地图上选点", "Pick location on map"))
        self.resize(960, 680)
        self.picked_wgs84: tuple[float, float] | None = None
        self.picked_name: str | None = None   # 地名上下文(搜过POI则继承其名)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(8)

        # 搜索行: 搜POI跳到大致位置, 再点精确角落
        srow = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(t(
            "搜地名跳到大致位置（如 奥林匹克森林公园），再点精确角落",
            "Search a place to jump to the rough area "
            "(e.g. Olympic Forest Park), then click the exact spot"))
        self.search_edit.setClearButtonEnabled(True)
        srow.addWidget(self.search_edit, 1)
        self.result_combo = QComboBox()
        self.result_combo.setMinimumWidth(240)
        self.result_combo.setVisible(False)
        srow.addWidget(self.result_combo)
        v.addLayout(srow)

        self._searcher = PoiSearcher(lib, self)
        self._searcher.results.connect(self._on_pois)
        # 搜索失败显性提示(无网络/Key失效等)
        self.search_warn = QLabel()
        self.search_warn.setWordWrap(True)
        self.search_warn.setStyleSheet(
            f"color:{theme.RED};font-size:12px;background:transparent;")
        self.search_warn.hide()
        self._searcher.failed.connect(self._on_search_failed)
        self._pois: list[dict] = []
        self.search_edit.textChanged.connect(self._searcher.search)
        self.search_edit.returnPressed.connect(lambda: self._goto_poi(0))
        self.result_combo.activated.connect(self._goto_poi)

        tip = QLabel(t("在地图上点按选点（拖动为平移）；坐标为GPS/WGS84。",
                       "Click the map to pick a point (drag to pan); "
                       "coordinates are GPS/WGS84."))
        tip.setObjectName("Hint")
        v.addWidget(tip)
        from .amap_view import AmapView
        self.amap = AmapView(lib, self)
        self.amap.picked_wgs84.connect(self._on_picked)
        v.addWidget(self.amap, 1)
        row = QHBoxLayout()
        self.chip = QLabel(t("尚未选点", "No location picked"))
        self.chip.setObjectName("Hint")
        row.addWidget(self.chip, 1)
        ok = QPushButton(t("确定", "OK"))
        ok.setObjectName("Primary")
        ok.setCursor(Qt.PointingHandCursor)
        ok.clicked.connect(self._confirm)
        row.addWidget(ok)
        cancel = QPushButton(t("取消", "Cancel"))
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        v.addLayout(row)
        # 回车交给搜索框, 不触发任何按钮
        for b in (ok, cancel):
            b.setAutoDefault(False)
            b.setDefault(False)

        spots = lib.spots_overview()
        if lat is not None and lon is not None:
            self.amap.focus_wgs84(lat, lon, 15)
        else:
            pts = [(s["lat"], s["lon"]) for s in spots
                   if s["lat"] is not None and s["lon"] is not None]
            if pts:
                self.amap.fit_wgs84(pts)
        self.amap.set_pick(True)

    def _on_search_failed(self, msg: str):
        self.search_warn.setText(msg)
        self.search_warn.show()

    def _on_pois(self, pois: list):
        self.search_warn.hide()
        self._pois = pois
        self.result_combo.blockSignals(True)
        self.result_combo.clear()
        for p in pois:
            addr = p.get("addr") or ((p.get("pname") or "")
                                     + (p.get("cityname") or "")
                                     + (p.get("adname") or ""))
            self.result_combo.addItem(f"{p.get('name')}  ·  {addr}" if addr
                                      else p.get("name", ""))
        self.result_combo.blockSignals(False)
        self.result_combo.setVisible(bool(pois))
        if pois:
            self.result_combo.showPopup()

    def _goto_poi(self, idx: int):
        if not (0 <= idx < len(self._pois)):
            return
        w = poi_location_wgs84(self._pois[idx])
        if not w:
            return
        self.amap.focus_wgs84(w[0], w[1], 15)
        name = self._pois[idx].get("name")
        # 记住地名上下文: 之后点的精确位置直接继承POI名作鸟点名
        # (用户要的是"位置", 名字能自动就自动——搜过POI就不用起名)
        self.picked_name = name or None
        self.chip.setText(t(
            f"已跳到「{name}」，点按选精确位置",
            f"Jumped to “{name}”, click to pick the exact spot"))

    def _on_picked(self, lat: float, lon: float):
        self.picked_wgs84 = (lat, lon)
        self.chip.setText(t(f"已选：{lat:.5f}, {lon:.5f} (GPS)",
                            f"Picked: {lat:.5f}, {lon:.5f} (GPS)"))

    def _confirm(self):
        if self.picked_wgs84:
            self.accept()
        else:
            self.chip.setText(t("请先在地图上点一下选个位置",
                                "Click the map to pick a location first"))


# ============================ 鸟点详情 ============================
class SpotDetailDialog(QDialog):
    """鸟点详情: 基本信息 + 物种清单 + 照片流, 支持编辑/删除。"""

    def __init__(self, lib, win, spot_id: int, parent=None):
        super().__init__(parent or win)
        self.lib = lib
        self.win = win
        self.spot_id = spot_id
        self.deleted = False
        self.setWindowTitle(t("鸟点详情", "Spot details"))
        self.resize(860, 680)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(12)
        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setLayout(self.body)
        scroll.setWidget(content)
        v.addWidget(scroll, 1)
        self._reload()

    def _reload(self):
        while self.body.count():
            it = self.body.takeAt(0)
            w = it.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        sp = self.lib.spot_info(self.spot_id)
        if not sp:
            self.deleted = True
            return
        overview = next((s for s in self.lib.spots_overview()
                         if s["id"] == self.spot_id), None)

        head = QFrame()
        head.setObjectName("Card")
        hv = QVBoxLayout(head)
        hv.setContentsMargins(20, 16, 20, 16)
        hv.setSpacing(6)
        n_photos = overview["n_photos"] if overview else 0
        n_species = overview["n_species"] if overview else 0
        t1 = QLabel(t(f"{sp['name']}    {n_photos} 张照片 · {n_species} 种鸟",
                      f"{sp['name']}    {n_photos} photos · {n_species} species"))
        t1.setStyleSheet(f"font-size:20px;font-weight:800;color:{theme.LABEL};"
                         "background:transparent;")
        t1.setWordWrap(True)
        hv.addWidget(t1)
        t2_text = format_coord(sp["lat"], sp["lon"])
        if sp["note"]:
            t2_text += "  ·  " + sp["note"]
        if overview and overview["last_at"]:
            t2_text += t(
                f"  ·  最近记录 {(overview['last_at'] or '')[:10]}",
                f"  ·  Last record {(overview['last_at'] or '')[:10]}")
        t2 = QLabel(t2_text)
        t2.setStyleSheet(f"font-size:13px;color:{theme.LABEL_2};background:transparent;")
        t2.setWordWrap(True)
        hv.addWidget(t2)
        ops = QHBoxLayout()
        b_edit = QPushButton(t("编辑信息", "Edit info"))
        b_edit.setCursor(Qt.PointingHandCursor)
        b_edit.clicked.connect(self._edit)
        ops.addWidget(b_edit)
        b_del = QPushButton(t("删除鸟点", "Delete spot"))
        b_del.setCursor(Qt.PointingHandCursor)
        b_del.clicked.connect(self._delete)
        ops.addWidget(b_del)
        ops.addStretch(1)
        hv.addLayout(ops)
        self.body.addWidget(head)

        species = self.lib.spot_species(self.spot_id)
        if species:
            card, lay = self._card(t("此处鸟种清单", "Species at this spot"))
            flow = QHBoxLayout()
            flow.setSpacing(8)
            for s in species:
                chip = QLabel(f"{sname(s['cn'], s['en'])} ×{s['n']}")
                chip.setStyleSheet(f"font-size:13px;color:{theme.LABEL};background:{theme.FILL};"
                                   "border-radius:12px;padding:4px 12px;")
                chip.setCursor(Qt.PointingHandCursor)
                chip.mousePressEvent = lambda e, code=s["code"]: \
                    self.win.open_species(code)
                flow.addWidget(chip)
            flow.addStretch(1)
            lay.addLayout(flow)
            self.body.addWidget(card)

        photos = self.lib.spot_photos(self.spot_id)
        card, lay = self._card(t(f"照片流 · {len(photos)} 张",
                                 f"Photo stream · {len(photos)}"))
        if photos:
            grid_widget = QWidget()
            grid = QGridLayout(grid_widget)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(10)
            cols = 6
            ids = [p["id"] for p in photos]
            for i, p in enumerate(photos):
                tp = ensure_thumbnail(self.lib.root, p["path"],
                                      self._hash_of(p["id"]), 240)
                pm = QPixmap(str(tp)) if tp else QPixmap()
                label = ""
                if p["n_species"] and p["main_code"]:
                    info = self.lib.species_info(p["main_code"])
                    if info:
                        label = sname(info["cn"], info["en"])
                item = self._thumb_item(p["id"], pm, label, ids)
                grid.addWidget(item, i // cols, i % cols)
            for c in range(cols):
                grid.setColumnStretch(c, 1)
            lay.addWidget(grid_widget)
        else:
            tip = QLabel(t("该鸟点还没有照片 · 在导入页或照片查看器里把照片挂到这个点",
                           "No photos at this spot yet · attach photos on the "
                           "Import page or in the photo viewer"))
            tip.setObjectName("Hint")
            lay.addWidget(tip)
        self.body.addWidget(card)
        self.body.addStretch(1)

    @staticmethod
    def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)
        v.setContentsMargins(18, 16, 18, 18)
        v.setSpacing(12)
        t = QLabel(title)
        t.setObjectName("CardTitle")
        v.addWidget(t)
        return card, v

    def _hash_of(self, photo_id: int) -> str:
        row = self.lib.conn.execute(
            "SELECT file_hash FROM photos WHERE id=?", (photo_id,)).fetchone()
        return row["file_hash"] if row else ""

    def _thumb_item(self, photo_id: int, pm: QPixmap, label: str, ids: list[int]):
        from ..theme.widgets import PhotoGridItem
        item = PhotoGridItem(pm if not pm.isNull() else None, label=label)
        item.setCursor(Qt.PointingHandCursor)
        item.mousePressEvent = lambda e, pid=photo_id: \
            PhotoViewer(self.lib, self.win, pid, ids).exec()
        return item

    def _edit(self):
        dlg = SpotEditDialog(self.lib, self.lib.spot_info(self.spot_id), self)
        if dlg.exec():
            if self.lib.spot_info(self.spot_id) is None:
                # 编辑对话框里删掉了本鸟点: 详情窗随之关闭
                self.deleted = True
                self.win.library_changed.emit()
                self.reject()
                return
            self._reload()
            self.win.library_changed.emit()

    def _delete(self):
        sp = self.lib.spot_info(self.spot_id)
        if not sp:
            return
        r = QMessageBox.question(
            self, t("删除鸟点", "Delete spot"),
            t(f"删除「{sp['name']}」？\n照片不会被删除，只是解除挂载。",
              f"Delete “{sp['name']}”?\nPhotos will not be deleted, "
              "only unlinked from this spot."))
        if r == QMessageBox.Yes:
            self.lib.delete_spot(self.spot_id)
            self.deleted = True
            self.win.library_changed.emit()
            self.reject()


# ============================ 鸟点地图页 ============================
class MapPage(QWidget):
    SIDEBAR_W = 300

    def __init__(self, lib, win):
        super().__init__()
        self.lib = lib
        self.win = win
        self._spots: dict[int, dict] = {}     # id -> overview row
        self._results: list[dict] = []
        self._popup_spot_id: int | None = None
        self._picked: tuple[float, float] | None = None
        self._initialized = False
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 左侧栏 ----
        side = QFrame()
        side.setFixedWidth(self.SIDEBAR_W)
        side.setStyleSheet(f"QFrame{{background:{theme.CARD};"
                           f"border-right:1px solid {theme.SEP};}}")
        sv = QVBoxLayout(side)
        sv.setContentsMargins(16, 22, 16, 14)
        sv.setSpacing(10)
        self.title = QLabel(t("鸟点地图", "Birding spot map"))
        self.title.setStyleSheet(f"font-size:24px;font-weight:800;color:{theme.LABEL};"
                                 "background:transparent;")
        sv.addWidget(self.title)

        srow = QHBoxLayout()
        srow.setSpacing(6)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(t("搜地名 / 粘贴 纬度,经度",
                                              "Search a place / paste lat,lon"))
        self.search_edit.returnPressed.connect(self._do_search)
        srow.addWidget(self.search_edit, 1)
        search_btn = QPushButton(t("搜索", "Search"))
        search_btn.setCursor(Qt.PointingHandCursor)
        search_btn.clicked.connect(self._do_search)
        srow.addWidget(search_btn)
        sv.addLayout(srow)

        self.result_list = QListWidget()
        self.result_list.setMaximumHeight(170)
        self.result_list.setVisible(False)
        self.result_list.itemClicked.connect(self._goto_result)
        sv.addWidget(self.result_list)

        self.list_title = QLabel(t("鸟点", "Birding spots"))
        self.list_title.setStyleSheet(f"font-size:13px;font-weight:700;"
                                      f"color:{theme.LABEL_3};background:transparent;")
        sv.addWidget(self.list_title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;}"
                             "QWidget{background:transparent;}")
        self.spot_list_area = QWidget()
        self.spot_list = QVBoxLayout(self.spot_list_area)
        self.spot_list.setContentsMargins(0, 0, 4, 0)
        self.spot_list.setSpacing(6)
        scroll.setWidget(self.spot_list_area)
        sv.addWidget(scroll, 1)

        new_btn = QPushButton(t("＋ 新建鸟点", "+ New spot"))
        new_btn.setCursor(Qt.PointingHandCursor)
        new_btn.clicked.connect(self._new_spot)
        sv.addWidget(new_btn)

        root.addWidget(side)

        # ---- 右侧地图区 ----
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        self.map_holder = QWidget()
        mv = QVBoxLayout(self.map_holder)
        mv.setContentsMargins(0, 0, 0, 0)
        from .amap_view import AmapView
        self.amap = AmapView(self.lib, self.map_holder)
        self.amap.spot_clicked.connect(self._on_marker_clicked)
        self.amap.center_moved.connect(self._update_coord_label)
        self.amap.picked_wgs84.connect(self._on_picked)
        mv.addWidget(self.amap)
        rv.addWidget(self.map_holder, 1)

        bar = QHBoxLayout()
        bar.setContentsMargins(14, 8, 14, 8)
        self.pick_btn = QPushButton(t("选点模式", "Pick location"))
        self.pick_btn.setCheckable(True)
        self.pick_btn.setCursor(Qt.PointingHandCursor)
        self.pick_btn.toggled.connect(self._toggle_pick)
        bar.addWidget(self.pick_btn)
        fit_btn = QPushButton(t("回到全部鸟点", "Back to all spots"))
        fit_btn.setCursor(Qt.PointingHandCursor)
        fit_btn.clicked.connect(self._fit_all)
        bar.addWidget(fit_btn)
        self.pick_chip = QLabel("")
        self.pick_chip.setStyleSheet("font-size:13px;font-weight:600;color:#007AFF;"
                                     f"background:{theme.CHIP_BG};border-radius:10px;"
                                     "padding:4px 12px;")
        self.pick_chip.setVisible(False)
        bar.addWidget(self.pick_chip)
        self.new_here_btn = QPushButton(t("在此建鸟点", "Create spot here"))
        self.new_here_btn.setObjectName("Primary")
        self.new_here_btn.setCursor(Qt.PointingHandCursor)
        self.new_here_btn.setVisible(False)
        self.new_here_btn.clicked.connect(self._new_spot_here)
        bar.addWidget(self.new_here_btn)
        self.copy_btn = QPushButton(t("复制坐标", "Copy coordinates"))
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.setVisible(False)
        self.copy_btn.clicked.connect(self._copy_picked)
        bar.addWidget(self.copy_btn)
        bar.addStretch(1)
        self.coord_label = QLabel("")
        self.coord_label.setObjectName("Hint")
        bar.addWidget(self.coord_label)
        rv.addLayout(bar)
        root.addWidget(right, 1)

        # 鸟点弹卡(悬浮在地图上)
        self.popup = QFrame(self.map_holder)
        self.popup.setObjectName("Card")
        self.popup.setVisible(False)
        self.popup.setFixedWidth(300)

    # ---- 数据 ----
    def refresh(self):
        from .amap_view import thumb_data_url
        self.amap.ensure_keys()
        spots = self.lib.spots_overview()
        self._spots = {s["id"]: s for s in spots}
        pts = []
        for s in spots:
            if s["lat"] is None or s["lon"] is None:
                continue
            pts.append({"id": s["id"], "name": s["name"], "lat": s["lat"],
                        "lon": s["lon"],
                        "thumb": thumb_data_url(self.lib, s["cover_photo_id"])})
        fit = not self._initialized
        self._initialized = True
        self.amap.set_spots(pts, fit=fit)
        self._rebuild_spot_list(spots)
        if self._popup_spot_id is not None:
            if self._popup_spot_id in self._spots:
                self._show_popup(self._popup_spot_id)
            else:
                self._hide_popup()
        self._update_coord_label()

    def _rebuild_spot_list(self, spots: list[dict]):
        while self.spot_list.count():
            it = self.spot_list.takeAt(0)
            w = it.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        with_coord = [s for s in spots if s["lat"] is not None]
        self.list_title.setText(t(f"鸟点 · {len(spots)}",
                                  f"Birding spots · {len(spots)}"))
        if not spots:
            tip = QLabel(t("还没有鸟点\n\n· 导入带GPS的照片会自动创建\n"
                           "· 或在地图上选点后「在此建鸟点」",
                           "No spots yet\n\n· Importing GPS-tagged photos "
                           "creates them automatically\n"
                           "· Or pick a location on the map and press "
                           "“Create spot here”"))
            tip.setStyleSheet(f"color:{theme.LABEL_2};font-size:13px;"
                              "background:transparent;")
            tip.setWordWrap(True)
            self.spot_list.addWidget(tip)
            self.spot_list.addStretch(1)
            return
        for s in spots:
            self.spot_list.addWidget(self._spot_row(s))
        self.spot_list.addStretch(1)
        if not with_coord:
            tip = QLabel(t("（部分鸟点没有坐标，不显示在地图上）",
                           "(Some spots have no coordinates and are not "
                           "shown on the map)"))
            tip.setStyleSheet(f"color:{theme.LABEL_3};font-size:12px;"
                              "background:transparent;")
            self.spot_list.insertWidget(0, tip)

    def _spot_row(self, s: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(3)
        name = QLabel(s["name"])
        name.setStyleSheet(f"font-size:14px;font-weight:700;color:{theme.LABEL};"
                           "background:transparent;")
        name.setWordWrap(True)
        v.addWidget(name)
        bits = [t(f"{s['n_photos']} 张", f"{s['n_photos']} photos"),
                t(f"{s['n_species']} 种", f"{s['n_species']} species")]
        if s["last_at"]:
            bits.append(t(f"最近 {(s['last_at'] or '')[:10]}",
                          f"Latest {(s['last_at'] or '')[:10]}"))
        meta = QLabel("  ·  ".join(bits))
        meta.setStyleSheet(f"font-size:12px;color:{theme.LABEL_2};background:transparent;")
        v.addWidget(meta)
        coord = QLabel(format_coord(s["lat"], s["lon"])
                       or t("无坐标", "No coordinates"))
        coord.setStyleSheet(f"font-size:12px;color:{theme.LABEL_3};background:transparent;")
        v.addWidget(coord)
        card.setCursor(Qt.PointingHandCursor)
        card.setToolTip(t("单击定位到地图 · 双击重命名", "Click to locate · Double-click to rename"))
        card.mousePressEvent = lambda e, sid=s["id"]: self._locate(sid)
        card.mouseDoubleClickEvent = lambda e, sid=s["id"], \
            nm=s["name"]: self._rename_spot(sid, nm)
        return card

    def _rename_spot(self, spot_id: int, old: str):
        """鸟点列表卡片双击=重命名(2026-10-31用户要求: 名字得可以直接编辑)。"""
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, t("重命名鸟点", "Rename spot"),
            t(f"鸟点名称（原：{old}）：", f"Spot name (was: {old}): "),
            text=old)
        if not (ok and name.strip() and name.strip() != old):
            return
        self.lib.update_spot(spot_id, name=name.strip())
        self.refresh()
        self.win.library_changed.emit()

    # ---- 定位/弹卡 ----
    def _locate(self, spot_id: int):
        s = self._spots.get(spot_id)
        if not s:
            return
        if s["lat"] is None:
            # 无坐标鸟点静默无反应曾是迷惑源: 直接带去编辑框补选位置
            dlg = SpotEditDialog(self.lib, self.lib.spot_info(spot_id), self)
            if dlg.exec():
                self.refresh()
                self.win.library_changed.emit()
            return
        self.amap.focus_wgs84(s["lat"], s["lon"], 15)
        self._show_popup(spot_id)

    def _on_marker_clicked(self, d: dict):
        sid = d.get("id")
        if sid in self._spots:
            self._show_popup(sid)

    def _show_popup(self, spot_id: int):
        s = self._spots.get(spot_id)
        if not s:
            return
        self._popup_spot_id = spot_id
        # 每次重建全新弹卡(旧路=清空复用布局): takeAt清空后布局sizeHint
        # 会永久塌缩到只剩边距(~26px), 第二个鸟点起弹卡缩成细条=左下角
        # "不显示"; invalidate/activate/行改QWidget容器均救不回(Qt布局
        # 脏标记在已可见控件上的怪癖), 重建=每次都走首次显示的稳定路径。
        if self.popup is not None:
            self.popup.hide()
            self.popup.setParent(None)
            self.popup.deleteLater()
        self.popup = QFrame(self.map_holder)
        self.popup.setObjectName("Card")
        self.popup.setFixedWidth(300)
        lay = QVBoxLayout(self.popup)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        name_lab = QLabel(s["name"])
        name_lab.setStyleSheet(f"font-size:15px;font-weight:700;color:{theme.LABEL};"
                               "background:transparent;")
        name_lab.setWordWrap(True)
        name_lab.setToolTip(t("双击重命名", "Double-click to rename"))
        name_lab.mouseDoubleClickEvent = lambda e, sid=spot_id, \
            nm=s["name"]: self._rename_spot(sid, nm)
        lay.addWidget(name_lab)
        bits = [t(f"{s['n_photos']} 张照片", f"{s['n_photos']} photos"),
                t(f"{s['n_species']} 种鸟", f"{s['n_species']} species")]
        if s.get("last_at"):
            bits.append(t(f"最近 {(s['last_at'] or '')[:10]}",
                          f"Latest {(s['last_at'] or '')[:10]}"))
        meta = QLabel("  ·  ".join(bits))
        meta.setStyleSheet(f"font-size:12px;color:{theme.LABEL_2};background:transparent;")
        lay.addWidget(meta)
        if s.get("lat") is not None:
            gc = QLabel(f"{s['lat']:.4f}, {s['lon']:.4f} (GPS)")
            gc.setStyleSheet(f"font-size:12px;color:{theme.LABEL_3};background:transparent;")
            lay.addWidget(gc)
        row = QHBoxLayout()
        row.setSpacing(6)
        photos = self.lib.spot_photos(spot_id)[:3]
        for p in photos:
            tp = ensure_thumbnail(self.lib.root, p["path"],
                                  self._hash_of(p["id"]), 120)
            lb = QLabel()
            lb.setFixedSize(72, 54)
            lb.setStyleSheet(f"background:{theme.FILL};border-radius:8px;")
            lb.setAlignment(Qt.AlignCenter)
            if tp:
                pm = QPixmap(str(tp))
                lb.setPixmap(pm.scaled(72, 54, Qt.KeepAspectRatioByExpanding,
                                       Qt.SmoothTransformation))
            row.addWidget(lb)
        row.addStretch(1)
        lay.addLayout(row)
        btns = QHBoxLayout()
        b_open = QPushButton(t("查看详情", "View details"))
        b_open.setObjectName("Primary")
        b_open.setCursor(Qt.PointingHandCursor)
        b_open.clicked.connect(lambda: self._open_detail(spot_id))
        btns.addWidget(b_open)
        b_edit = QPushButton(t("编辑", "Edit"))
        b_edit.setCursor(Qt.PointingHandCursor)
        b_edit.clicked.connect(lambda: self._edit_spot(spot_id))
        btns.addWidget(b_edit)
        b_del = QPushButton(t("删除", "Delete"))
        b_del.setCursor(Qt.PointingHandCursor)
        b_del.clicked.connect(lambda: self._delete_spot_quick(spot_id))
        btns.addWidget(b_del)
        b_close = QPushButton("×")
        b_close.setFixedWidth(28)
        b_close.setCursor(Qt.PointingHandCursor)
        b_close.clicked.connect(self._hide_popup)
        btns.addWidget(b_close)
        lay.addLayout(btns)
        self.popup.adjustSize()
        self.popup.move(16, self.map_holder.height() - self.popup.height() - 16)
        self.popup.setVisible(True)
        self.popup.raise_()

    def _hide_popup(self):
        self._popup_spot_id = None
        self.popup.setVisible(False)

    def _delete_spot_quick(self, spot_id: int):
        """弹卡直删(用户要求: 鸟点要能删除)。照片只解除挂载, 绝不删除。"""
        sp = self.lib.spot_info(spot_id)
        if not sp:
            return
        from PySide6.QtWidgets import QMessageBox
        r = QMessageBox.question(
            self, t("删除鸟点", "Delete spot"),
            t(f"删除「{sp['name']}」？\n照片不会被删除，只是解除挂载。",
              f"Delete “{sp['name']}”?\nPhotos will not be deleted, "
              "only unlinked from this spot."))
        if r == QMessageBox.Yes:
            self.lib.delete_spot(spot_id)
            self._hide_popup()
            self.refresh()
            self.win.library_changed.emit()

    def _hash_of(self, photo_id: int) -> str:
        row = self.lib.conn.execute(
            "SELECT file_hash FROM photos WHERE id=?", (photo_id,)).fetchone()
        return row["file_hash"] if row else ""

    def _open_detail(self, spot_id: int):
        self._hide_popup()
        dlg = SpotDetailDialog(self.lib, self.win, spot_id, self)
        dlg.exec()
        if dlg.deleted:
            self.refresh()

    def _edit_spot(self, spot_id: int):
        dlg = SpotEditDialog(self.lib, self.lib.spot_info(spot_id), self)
        if dlg.exec():
            self.refresh()
            self.win.library_changed.emit()

    def _new_spot(self):
        dlg = SpotEditDialog(self.lib, None, self)
        if dlg.exec():
            if dlg.created_id:
                self.refresh()
                self.win.library_changed.emit()
                info = self.lib.spot_info(dlg.created_id)
                if info and info["lat"] is not None:
                    self._locate(dlg.created_id)

    def _new_spot_here(self):
        if not self._picked:
            return
        dlg = SpotEditDialog(self.lib, None, self,
                             preset_lat=self._picked[0],
                             preset_lon=self._picked[1])
        if dlg.exec() and dlg.created_id:
            self.refresh()
            self.win.library_changed.emit()

    # ---- 搜索 ----
    def _do_search(self):
        text = self.search_edit.text().strip()
        if not text:
            return
        m = re.fullmatch(r"\s*([+-]?\d{1,2}(?:\.\d+)?)\s*[,， ]\s*"
                         r"([+-]?\d{1,3}(?:\.\d+)?)\s*", text)
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                self.coord_label.setText(
                    t("坐标超出范围（纬度±90，经度±180）",
                      "Coordinates out of range (lat ±90, lon ±180)"))
                return
            self.amap.focus_wgs84(lat, lon, 15)
            self.coord_label.setText(t(
                f"已定位 {lat:.4f}, {lon:.4f}（按GPS/WGS84）",
                f"Located {lat:.4f}, {lon:.4f} (GPS/WGS84)"))
            return
        if not hasattr(self, "_searcher"):
            self._searcher = PoiSearcher(self.lib, self)
            self._searcher.results.connect(self._on_search_results)
            self._searcher.failed.connect(
                lambda msg: self.coord_label.setText(msg))
        self.coord_label.setText(t("搜索中…", "Searching…"))
        self._searcher.search(text)

    def _on_search_results(self, pois: list):
        self._results = pois
        self.result_list.clear()
        for p in pois:
            name = p.get("name", "")
            addr = ((p.get("pname") or "") + (p.get("cityname") or "")
                    + (p.get("adname") or ""))
            self.result_list.addItem(f"{name}  ·  {addr}" if addr else name)
        self.result_list.setVisible(bool(pois))
        if pois:
            self.coord_label.setText(
                t(f"找到 {len(pois)} 个结果，点选后跳转",
                  f"Found {len(pois)} results, click one to jump"))
        else:
            self.coord_label.setText(t("没有找到该地点", "Place not found"))

    def _goto_result(self, item: QListWidgetItem):
        idx = self.result_list.row(item)
        if not (0 <= idx < len(self._results)):
            return
        p = self._results[idx]
        w = poi_location_wgs84(p)
        if not w:
            return
        self.amap.focus_wgs84(w[0], w[1], 15)
        self.coord_label.setText(t(
            f"{p.get('name')}  GPS坐标 {w[0]:.4f}, {w[1]:.4f}",
            f"{p.get('name')}  GPS coordinates {w[0]:.4f}, {w[1]:.4f}"))

    # ---- 选点 ----
    def _toggle_pick(self, on: bool):
        self.amap.set_pick(on)
        if on:
            self.pick_chip.setText(
                t("点按地图取坐标（拖动为平移）",
                  "Click the map to capture coordinates (drag to pan)"))
            self.pick_chip.setVisible(True)
        elif not self._picked:
            self.pick_chip.setVisible(False)

    def _on_picked(self, lat: float, lon: float):
        self._picked = (lat, lon)
        self.pick_chip.setText(
            t(f"已选点：{lat:.5f}, {lon:.5f} (GPS)",
              f"Picked: {lat:.5f}, {lon:.5f} (GPS)"))
        self.pick_chip.setVisible(True)
        self.copy_btn.setVisible(True)
        self.new_here_btn.setVisible(True)

    def _copy_picked(self):
        if self._picked:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(
                f"{self._picked[0]:.5f}, {self._picked[1]:.5f}")
            self.coord_label.setText(t("坐标已复制", "Coordinates copied"))

    def _fit_all(self):
        pts = [(s["lat"], s["lon"]) for s in self._spots.values()
               if s["lat"] is not None and s["lon"] is not None]
        if pts:
            self.amap.fit_wgs84(pts)
        else:
            self.coord_label.setText(t("还没有带坐标的鸟点",
                                       "No spots with coordinates yet"))

    def _update_coord_label(self, lat=None, lon=None, z=None):
        w_lat, w_lon, w_z = self.amap._center_state
        self.coord_label.setText(t(
            f"中心 {w_lat:.4f}, {w_lon:.4f} · 缩放 {w_z:.0f}",
            f"Center {w_lat:.4f}, {w_lon:.4f} · Zoom {w_z:.0f}"))
