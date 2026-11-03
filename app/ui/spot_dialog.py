# -*- coding: utf-8 -*-
"""鸟点挂载对话框。

搜索是"二合一": 上半是匹配的已有鸟点(精确位置), 下半是地名POI(粗略位置,
默认MapTiler作者Key, 自填高德Key更准)。选中POI直接按其位置建鸟点
(同名复用), 想精修再到地图上选点。
- SpotPickDialog: 单张照片挂载
- BatchSpotDialog: 导入完成后整批挂载
回车/双击=应用当前项; 单击只选中(不会误跳地图)。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout, QWidget)

from ..core.spots import format_coord
from .. import theme
from ..i18n import t, sname
from .map_page import PoiSearcher, MapPickDialog, poi_location_wgs84

SEP = "__sep__"  # 旧标记常量(未用)


def _poi_coords(poi: dict) -> tuple[float, float] | None:
    """POI数据 → (lat, lon) WGS84。兼容两种形状: 原始poi dict(location字符串,
    高德GCJ/MapTiler WGS)与SpotSearchList信号载荷(坐标已解析在lat/lon,
    原始dict嵌在"poi"键下)。历史bug: 只认location键, 信号载荷静默丢坐标。"""
    raw = poi.get("poi") if isinstance(poi.get("poi"), dict) else None
    w = poi_location_wgs84(raw if raw is not None else poi)
    if w is None and poi.get("lat") is not None and poi.get("lon") is not None:
        try:
            w = (float(poi["lat"]), float(poi["lon"]))
        except (TypeError, ValueError):
            w = None
    return w


def find_or_create_spot_by_poi(lib, poi: dict) -> tuple[int, str, bool]:
    """按POI建鸟点(粗略位置); 同名鸟点已存在则复用——旧点无坐标而本次
    有坐标时自动补上(修复历史无坐标点)。返回(id, 名称, 是否新建)。"""
    name = (poi.get("name") or "").strip() or t("未命名鸟点", "Unnamed spot")
    row = lib.conn.execute("SELECT id, name, lat FROM spots WHERE name=?",
                           (name,)).fetchone()
    w = _poi_coords(poi)
    if row:
        if w and row["lat"] is None:
            lib.update_spot(row["id"], lat=w[0], lon=w[1])
        return row["id"], row["name"], False
    if w:
        sid = lib.create_spot(name, w[0], w[1])
    else:
        sid = lib.create_spot(name)
    return sid, name, True


class SpotSearchList(QWidget):
    """鸟点+地名POI 二合一搜索列表。

    spot_chosen(id, name) — 选中已有鸟点
    poi_chosen({name,lat,lon,poi}) — 选中地名(WGS84)
    """
    spot_chosen = Signal(int, str)
    poi_chosen = Signal(dict)

    def __init__(self, lib, placeholder=None, parent=None):
        super().__init__(parent)
        self.lib = lib
        self._spots: list[dict] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        self.search = QLineEdit()
        # 占位文案在调用时翻译(不能作为默认参数值, 那会在导入期冻结语言)
        self.search.setPlaceholderText(
            placeholder or t("搜索鸟点或地名…", "Search spots or places…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._reload())
        self.search.returnPressed.connect(self.trigger_current)
        v.addWidget(self.search)

        self.listw = QListWidget()
        self.listw.itemActivated.connect(self._trigger_item)   # 回车/双击
        v.addWidget(self.listw, 1)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{theme.LABEL_3};font-size:12px;"
                                  "background:transparent;")
        v.addWidget(self.status)

        self._searcher = PoiSearcher(lib, self)
        self._searcher.results.connect(self._on_pois)
        self._searcher.failed.connect(self._on_search_failed)
        self._pois: list[dict] = []
        self.reload()

    def reload(self):
        """鸟点列表变化后调用; 重新过滤。"""
        self._spots = self.lib.spots_overview()
        self._reload()

    def trigger_current(self):
        it = self.listw.currentItem() or (self.listw.item(0)
                                          if self.listw.count() else None)
        self._trigger_item(it)

    # ---- 内部 ----
    def _reload(self):
        q = self.search.text().strip().lower()
        self._pois = []
        self.listw.clear()
        n = 0
        for sp in self._spots:
            if q and q not in sp["name"].lower():
                continue
            it = QListWidgetItem(
                t(f"📍 {sp['name']}    {sp['n_photos']} 张 · {sp['n_species']} 种"
                  f" · {format_coord(sp['lat'], sp['lon'])}",
                  f"📍 {sp['name']}    {sp['n_photos']} photos · "
                  f"{sp['n_species']} species"
                  f" · {format_coord(sp['lat'], sp['lon'])}"))
            it.setData(Qt.UserRole, {"kind": "spot", "id": sp["id"],
                                     "name": sp["name"]})
            self.listw.addItem(it)
            n += 1
        if not q:
            if not self._spots:
                tip = QListWidgetItem(t(
                    "还没有鸟点：输入地名搜索，或在下方地图选点新建",
                    "No spots yet: type a place name to search, or pick a "
                    "location on the map to create one"))
                tip.setFlags(Qt.NoItemFlags)
                self.listw.addItem(tip)
            self.status.setText("")
            return
        if n == 0:
            tip = QListWidgetItem(t(
                "没有匹配的鸟点，正在搜地名…",
                "No matching spots; searching places…"))
            tip.setFlags(Qt.NoItemFlags)
            self.listw.addItem(tip)
        self._searcher.search(self.search.text().strip())

    def _drop_poi_items(self):
        while self.listw.count():
            it = self.listw.item(self.listw.count() - 1)
            d = it.data(Qt.UserRole)
            if d is None or d.get("kind") in ("poi", "sep"):
                self.listw.takeItem(self.listw.count() - 1)
            else:
                break

    def _on_pois(self, pois: list):
        self._drop_poi_items()
        self._pois = pois
        # 移除"正在搜"占位
        for i in range(self.listw.count()):
            if self.listw.item(i).data(Qt.UserRole) is None:
                self.listw.takeItem(i)
                break
        if pois:
            sep = QListWidgetItem(t(
                "── 搜到的地点（粗略位置，选中即建鸟点）──",
                "── Places (approximate; selecting creates a spot) ──"))
            sep.setFlags(Qt.NoItemFlags)
            sep.setData(Qt.UserRole, {"kind": "sep"})
            self.listw.addItem(sep)
            for p in pois:
                addr = p.get("addr") or ((p.get("pname") or "")
                                         + (p.get("cityname") or "")
                                         + (p.get("adname") or ""))
                label = f"🔎 {p.get('name')}  ·  {addr}" if addr \
                    else f"🔎 {p.get('name')}"
                it = QListWidgetItem(label)
                w = poi_location_wgs84(p)
                it.setData(Qt.UserRole, {
                    "kind": "poi", "name": p.get("name", ""),
                    "lat": w[0] if w else None, "lon": w[1] if w else None,
                    "poi": p})
                self.listw.addItem(it)
            self.status.setText(t(f"{len(pois)} 个地点 · 回车应用当前项",
                                  f"{len(pois)} places · Enter to apply current"))
        else:
            self.status.setText(t("没有匹配的地点", "No matching places"))

    def _on_search_failed(self, msg: str):
        self.status.setText(msg)

    def _trigger_item(self, it):
        if it is None:
            return
        d = it.data(Qt.UserRole)
        if not d:
            return
        if d["kind"] == "spot":
            self.spot_chosen.emit(d["id"], d["name"])
        elif d["kind"] == "poi":
            self.poi_chosen.emit(d)


def _create_spot_via_map(lib, parent) -> int | None:
    """地图选点 → 零输入建点: 名字优先用选点前搜到的POI名(点了公园的
    角落=叫公园名), 完全没搜过才退回坐标名; 同名点已存在则复用。
    返回鸟点id或None。"""
    dlg = MapPickDialog(lib, None, None, parent)
    if not (dlg.exec() and dlg.picked_wgs84):
        return None
    lat, lon = dlg.picked_wgs84
    name = dlg.picked_name or t(f"鸟点 {lat:.4f}, {lon:.4f}",
                                f"Spot {lat:.4f}, {lon:.4f}")
    row = lib.conn.execute("SELECT id, lat FROM spots WHERE name=?",
                           (name,)).fetchone()
    if row:
        if row["lat"] is None:   # 复用同名旧点: 顺带补上缺失的坐标
            lib.update_spot(row["id"], lat=lat, lon=lon)
        return row["id"]
    return lib.create_spot(name, lat, lon)


class SpotPickDialog(QDialog):
    """为一张照片选择鸟点。photo = lib.photo_detail 的照片dict。"""

    def __init__(self, lib, photo: dict, parent=None):
        super().__init__(parent)
        self.lib = lib
        self.photo = photo
        self.changed = False
        self.setWindowTitle(t("挂到鸟点", "Attach to spot"))
        self.setMinimumSize(480, 560)
        v = QVBoxLayout(self)
        v.setSpacing(10)

        cur = self.photo.get("spot_name")
        cur_txt = cur or t("未挂载", "Not attached")
        self.cur_label = QLabel(t(f"当前鸟点：{cur_txt}",
                                  f"Current spot: {cur_txt}"))
        self.cur_label.setStyleSheet(f"font-size:13px;color:{theme.LABEL_2};"
                                     "background:transparent;")
        v.addWidget(self.cur_label)

        self.slist = SpotSearchList(
            lib, t("搜索鸟点或地名（回车应用）…",
                   "Search spots or places (Enter to apply)…"))
        self.slist.spot_chosen.connect(self._attach_spot)
        self.slist.poi_chosen.connect(self._use_poi)
        v.addWidget(self.slist, 1)

        btns = QHBoxLayout()
        self.attach_btn = QPushButton(t("挂到当前选中项", "Attach to selected"))
        self.attach_btn.setObjectName("Primary")
        self.attach_btn.setCursor(Qt.PointingHandCursor)
        self.attach_btn.clicked.connect(self.slist.trigger_current)
        btns.addWidget(self.attach_btn)
        self.detach_btn = QPushButton(t("解除挂载", "Detach"))
        self.detach_btn.setCursor(Qt.PointingHandCursor)
        self.detach_btn.clicked.connect(self._detach)
        btns.addWidget(self.detach_btn)
        btns.addStretch(1)
        v.addLayout(btns)

        new_row = QHBoxLayout()
        self.new_btn = QPushButton(t("从这张照片的GPS新建",
                                     "Create from this photo's GPS"))
        self.new_btn.setCursor(Qt.PointingHandCursor)
        self.new_btn.setEnabled(self.photo.get("gps_lat") is not None
                                and self.photo.get("gps_lon") is not None)
        if not self.new_btn.isEnabled():
            self.new_btn.setToolTip(t("这张照片没有GPS信息",
                                      "This photo has no GPS data"))
        self.new_btn.clicked.connect(self._create_from_gps)
        new_row.addWidget(self.new_btn)
        self.map_btn = QPushButton(t("在地图上选点新建…", "Pick on map to create…"))
        self.map_btn.setCursor(Qt.PointingHandCursor)
        self.map_btn.clicked.connect(self._create_via_map)
        new_row.addWidget(self.map_btn)
        new_row.addStretch(1)
        v.addLayout(new_row)

        tip = QLabel(t("POI是粗略位置（如整个公园），选中即建鸟点；"
                       "要精确到公园角落请用「在地图上选点新建」。",
                       "POIs are approximate locations (e.g. a whole park); "
                       "selecting one creates a spot there. For a precise "
                       "location, use \"Pick on map to create…\"."))
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{theme.LABEL_3};font-size:12px;background:transparent;")
        v.addWidget(tip)

        for b in (self.attach_btn, self.detach_btn, self.new_btn, self.map_btn):
            b.setAutoDefault(False)
            b.setDefault(False)

    def _attach_spot(self, sid: int, _name: str):
        if sid == self.photo.get("spot_id"):
            self.accept()
            return
        self.lib.set_photo_spot(self.photo["id"], sid)
        self.changed = True
        self.accept()

    def _use_poi(self, d: dict):
        sid, _name, _created = find_or_create_spot_by_poi(self.lib, d)
        self._attach_spot(sid, _name)

    def _detach(self):
        if self.photo.get("spot_id"):
            self.lib.set_photo_spot(self.photo["id"], None)
            self.changed = True
        self.accept()

    def _create_from_gps(self):
        lat, lon = self.photo.get("gps_lat"), self.photo.get("gps_lon")
        if lat is None or lon is None:
            return
        name, ok = QInputDialog.getText(self, t("新建鸟点", "New spot"),
                                        t(f"鸟点名称（GPS {lat:.4f}, {lon:.4f}）：",
                                          f"Spot name (GPS {lat:.4f}, {lon:.4f}): "))
        if not (ok and name.strip()):
            return
        sid = self.lib.create_spot(name.strip(), lat, lon)
        self._attach_spot(sid, name.strip())

    def _create_via_map(self):
        sid = _create_spot_via_map(self.lib, self)
        if sid is None:
            return
        info = self.lib.spot_info(sid)
        self._attach_spot(sid, info["name"] if info else "")


class BatchSpotDialog(QDialog):
    """导入完成后为整批照片设置鸟点。

    用法: dlg = BatchSpotDialog(lib, win, photo_ids, note); dlg.exec()
    之后读 dlg.applied(bool) 与 dlg.spot_name。
    """

    def __init__(self, lib, win, photo_ids: list[int], note: str = "",
                 parent=None):
        super().__init__(parent or win)
        self.lib = lib
        self.win = win
        self.photo_ids = photo_ids
        self.applied = False
        self.spot_name: str | None = None
        self.setWindowTitle(t("批量设置鸟点", "Batch-set spot"))
        self.setMinimumSize(500, 600)
        v = QVBoxLayout(self)
        v.setSpacing(10)

        head = QLabel(t(f"为这 {len(photo_ids)} 张照片设置同一个鸟点？",
                        f"Set the same spot for these {len(photo_ids)} photos?"))
        head.setStyleSheet(f"font-size:16px;font-weight:700;color:{theme.LABEL};"
                           "background:transparent;")
        v.addWidget(head)
        if note:
            tip = QLabel(note)
            tip.setWordWrap(True)
            tip.setStyleSheet(f"color:{theme.LABEL_3};font-size:12px;"
                              "background:transparent;")
            v.addWidget(tip)

        self.slist = SpotSearchList(
            lib, t("搜索鸟点或地名（回车应用整批）…",
                   "Search spots or places (Enter to apply to batch)…"))
        self.slist.spot_chosen.connect(self._finish_spot)
        self.slist.poi_chosen.connect(self._use_poi)
        v.addWidget(self.slist, 1)

        row = QHBoxLayout()
        b_map = QPushButton(t("在地图上选点新建…", "Pick on map to create…"))
        b_map.setCursor(Qt.PointingHandCursor)
        b_map.clicked.connect(self._create_via_map)
        row.addWidget(b_map)
        b_new = QPushButton(t("仅名称新建…", "Create by name only…"))
        b_new.setCursor(Qt.PointingHandCursor)
        b_new.clicked.connect(self._create_by_name)
        row.addWidget(b_new)
        row.addStretch(1)
        v.addLayout(row)

        btns = QHBoxLayout()
        skip = QPushButton(t("跳过", "Skip"))
        skip.setCursor(Qt.PointingHandCursor)
        skip.clicked.connect(self.reject)
        btns.addWidget(skip)
        btns.addStretch(1)
        self.apply_btn = QPushButton(t(f"应用到 {len(photo_ids)} 张",
                                       f"Apply to {len(photo_ids)}"))
        self.apply_btn.setObjectName("Primary")
        self.apply_btn.setCursor(Qt.PointingHandCursor)
        self.apply_btn.clicked.connect(self.slist.trigger_current)
        btns.addWidget(self.apply_btn)
        v.addLayout(btns)

        for b in (b_map, b_new, skip, self.apply_btn):
            b.setAutoDefault(False)
            b.setDefault(False)

        tip = QLabel(t("搜到的地名(POI)是粗略位置，选中即建鸟点并挂整批；"
                       "要精确位置请「在地图上选点新建」。",
                       "Searched places (POIs) are approximate; selecting one "
                       "creates a spot and attaches the whole batch. For a "
                       "precise location, use \"Pick on map to create…\"."))
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{theme.LABEL_3};font-size:12px;background:transparent;")
        v.addWidget(tip)

    def _finish(self, spot_id: int, name: str):
        self.lib.set_photos_spot(self.photo_ids, spot_id)
        self.applied = True
        self.spot_name = name
        self.accept()

    def _finish_spot(self, sid: int, name: str):
        self._finish(sid, name)

    def _use_poi(self, d: dict):
        sid, name, created = find_or_create_spot_by_poi(self.lib, d)
        self._finish(sid, name)

    def _create_via_map(self):
        sid = _create_spot_via_map(self.lib, self)
        if sid is None:
            return
        info = self.lib.spot_info(sid)
        self._finish(sid, info["name"] if info else "")

    def _create_by_name(self):
        name, ok = QInputDialog.getText(self, t("新建鸟点", "New spot"),
                                        t("鸟点名称（暂无坐标，可稍后在鸟点地图补选）：",
                                          "Spot name (no coordinates yet; you can "
                                          "add them later on the spot map): "))
        if not (ok and name.strip()):
            return
        sid = self.lib.create_spot(name.strip())
        self._finish(sid, name.strip())
