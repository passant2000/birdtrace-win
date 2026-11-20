# -*- coding: utf-8 -*-
"""省级足迹图·自绘版(实测反馈8, 2026-11-19): QPaint 直接画 choropleth
——色深=该省收录鸟种数, 有数据的省**直接标注省名+数字**(不用悬浮才能看),
悬浮仍有 tooltip。免 WebEngine(生涯页轻加载)。几何复用 DataV 省界
GeoJSON(distribution_map 同源)。投影=等距圆柱+经度中纬cos压缩, **等比
缩放居中**(test3反馈: 原各自铺满宽高把中国拉宽~2.6倍); 支持滚轮缩放
(光标锚点1-8倍)+拖动平移+双击复位(test3反馈"不能缩放")。"""
from __future__ import annotations

import json
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..i18n import t
from .. import theme

# 色阶(与生涯页热力图同系绿档)
TIERS = [(1, "#D7EEDD"), (3, "#A8E0BC"), (6, "#6FC992"), (12, "#34C759")]
LAND = "#F0F1F4"

# 太小省不画文字标注(悬浮可见); 名单=DataV properties.name
# i18n:ok 以下省名对照表=数据(GeoJSON properties.name 匹配键, 不翻译)
TINY = {"北京市", "天津市", "上海市", "重庆市", "香港特别行政区",  # i18n:ok
        "澳门特别行政区", "宁夏回族自治区", "海南省"}  # i18n:ok
SHORT = {"北京市": "北京", "天津市": "天津", "上海市": "上海",  # i18n:ok
         "重庆市": "重庆", "河北省": "河北", "山西省": "山西",  # i18n:ok
         "内蒙古自治区": "内蒙古", "辽宁省": "辽宁", "吉林省": "吉林",  # i18n:ok
         "黑龙江省": "黑龙江", "江苏省": "江苏", "浙江省": "浙江",  # i18n:ok
         "安徽省": "安徽", "福建省": "福建", "江西省": "江西",  # i18n:ok
         "山东省": "山东", "河南省": "河南", "湖北省": "湖北",  # i18n:ok
         "湖南省": "湖南", "广东省": "广东", "广西壮族自治区": "广西",  # i18n:ok
         "四川省": "四川", "贵州省": "贵州", "云南省": "云南",  # i18n:ok
         "西藏自治区": "西藏", "陕西省": "陕西", "甘肃省": "甘肃",  # i18n:ok
         "青海省": "青海", "宁夏回族自治区": "宁夏",  # i18n:ok
         "新疆维吾尔自治区": "新疆", "台湾省": "台湾",  # i18n:ok
         "香港特别行政区": "香港", "澳门特别行政区": "澳门",  # i18n:ok
         "海南省": "海南"}  # i18n:ok

_LON0, _LON1 = 72.5, 136.0
_LAT0, _LAT1 = 17.0, 54.5
# 等比投影画布(test3反馈"比例不对"): 原实现经/纬各自独立铺满控件宽高,
# 宽扁控件上中国被横向拉宽~2.6倍。改为经度按中纬度cos压缩进"等距圆柱"
# 画布, 统一缩放居中(不满宽留白), 形状比例恒定; 再叠加缩放/平移视口。
_KX = math.cos(math.radians((_LAT0 + _LAT1) / 2))   # ≈0.81 中纬度经度压缩
_CW = (_LON1 - _LON0) * _KX                          # 画布全宽(度)
_CH = _LAT1 - _LAT0                                  # 画布全高(度)
_feats_cache: list | None = None


def _load_features() -> list:
    """解析省界 GeoJSON → [(name, adcode, QPainterPath构造点集, type)]。
    path 用未投影的 (lon,lat) 原始点, 投影在 paint 时按当前尺寸做。"""
    global _feats_cache
    if _feats_cache is not None:
        return _feats_cache
    from .distribution_map import _load_geojson
    gj = _load_geojson()
    out = []
    for feat in gj.get("features", []):
        props = feat.get("properties", {}) or {}
        name = str(props.get("name") or "")
        adcode = str(props.get("adcode") or props.get("id") or "")
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        rings = []
        if gtype == "Polygon":
            rings = list(geom.get("coordinates") or [])   # [环,环…]=孔洞
        elif gtype == "MultiPolygon":
            rings = [poly[0] for poly in (geom.get("coordinates") or [])
                     if poly]
        elif gtype in ("LineString", "MultiLineString"):
            lines = (geom.get("coordinates") if gtype == "MultiLineString"
                     else [geom.get("coordinates")]) or []
            out.append((name, adcode, lines, "line"))
            continue
        if not rings:
            continue
        out.append((name, adcode, rings, "poly"))
    _feats_cache = out
    return out


class ChinaMapWidget(QWidget):
    """省级 choropleth。counts: {region_id(CN-XX): 鸟种数}。"""

    def __init__(self, counts: dict[str, int], parent=None):
        super().__init__(parent)
        self._counts = counts
        self._hover: str | None = None   # 悬浮省名
        self._paths_cache: list | None = None
        self._w = 0
        self._h = 0
        # 视口状态(test3反馈"不能缩放"): 滚轮缩放(光标锚点)+拖动平移+双击复位
        self._zoom = 1.0                 # 1=全图, 上限8
        self._vx, self._vy = _CW / 2, _CH / 2   # 视口中心(画布坐标)
        self._drag = None                # 拖动平移: 上次按下的鼠标位置
        self.setMinimumHeight(430)
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)
        self._name_for_region = {}
        from .distribution_map import ADCODE_TO_REGION
        from ..core import regions
        for adcode, rid in ADCODE_TO_REGION.items():
            # GeoJSON adcode 解析为 str, 映射键是 int——统一 str 化
            self._name_for_region[str(adcode)] = rid

    # ---------- 投影(等比+视口) ----------
    def _view_scale(self) -> float:
        """像素/画布度。min(宽高比)适配+0.96留白边, 全图时地图完整居中。"""
        w, h = max(self._w, 1.0), max(self._h, 1.0)
        return min(w / _CW, h / _CH) * 0.96 * self._zoom

    def _clamp_view(self):
        """视口中心夹在全图范围内(缩小时回中)。"""
        self._zoom = min(max(self._zoom, 1.0), 8.0)
        s = self._view_scale()
        hw, hh = self._w / (2 * s), self._h / (2 * s)
        self._vx = min(max(self._vx, min(hw, _CW / 2)), max(_CW - hw, _CW / 2))
        self._vy = min(max(self._vy, min(hh, _CH / 2)), max(_CH - hh, _CH / 2))

    def _proj(self, lon, lat):
        # 等距圆柱(经度cos压缩)+等比缩放居中, 视口偏移(_vx,_vy)*zoom
        s = self._view_scale()
        return (self._w / 2 + ((lon - _LON0) * _KX - self._vx) * s,
                self._h / 2 + ((_LAT1 - lat) - self._vy) * s)

    def _unproj(self, sx, sy) -> tuple[float, float]:
        """屏幕坐标→画布坐标(缩放锚点用)。"""
        s = self._view_scale()
        return (self._vx + (sx - self._w / 2) / s,
                self._vy + (sy - self._h / 2) / s)

    def _region_count(self, adcode: str) -> int:
        rid = self._name_for_region.get(adcode)
        return self._counts.get(rid, 0) if rid else 0

    def _tier_color(self, n: int) -> QColor:
        c = QColor(LAND)
        for th, col in TIERS:
            if n >= th:
                c = QColor(col)
        return c

    # ---------- 事件 ----------
    def _feature_at(self, pos) -> str | None:
        for name, adcode, rings, kind in (self._paths_cache or []):
            if kind != "poly":
                continue
            path = QPainterPath()
            path.setFillRule(Qt.OddEvenFill)
            for ring in rings:
                poly = [QPointF(*self._proj(x, y)) for x, y in ring]
                path.addPolygon(_make_polygon(poly))
                path.closeSubpath()
            if path.contains(QPointF(pos.x(), pos.y())):
                return name
        return None

    # ---------- 事件: 拖动平移/滚轮缩放/双击复位(test3反馈"不能缩放") ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.position()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag is not None:
            s = self._view_scale()
            self._vx -= (pos.x() - self._drag.x()) / s
            self._vy -= (pos.y() - self._drag.y()) / s
            self._drag = pos
            self._clamp_view()
            self.update()
            super().mouseMoveEvent(e)
            return
        name = self._feature_at(pos)
        if name != self._hover:
            self._hover = name
        n = 0
        for name2, adcode, _r, _k in (self._paths_cache or []):
            if name2 == name:
                n = self._region_count(adcode)
                break
        if name:
            self.setToolTip(t(f"{name}：{n} 种" if n else f"{name}：尚无收录",
                              f"{name}: {n} species" if n
                              else f"{name}: no records"))
        else:
            self.setToolTip("")
        self.update()
        super().mouseMoveEvent(e)

    def wheelEvent(self, e):
        # 滚轮缩放(光标锚点); accept吃掉事件, 不让外层页面跟着滚
        pos = e.position()
        cx, cy = self._unproj(pos.x(), pos.y())
        self._zoom = min(max(
            self._zoom * (1.25 if e.angleDelta().y() > 0 else 0.8),
            1.0), 8.0)
        s = self._view_scale()
        self._vx = cx - (pos.x() - self._w / 2) / s
        self._vy = cy - (pos.y() - self._h / 2) / s
        self._clamp_view()
        self.update()
        e.accept()

    def mouseDoubleClickEvent(self, e):
        self._zoom = 1.0
        self._vx, self._vy = _CW / 2, _CH / 2
        self.update()
        e.accept()

    # ---------- 绘制 ----------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._w = float(self.width())
        self._h = float(self.height())
        k = min(self._zoom, 2.0)   # 线宽/字号/圆点随缩放放大, 封顶2倍
        if self._paths_cache is None:
            self._paths_cache = []
            for name, adcode, rings, kind in _load_features():
                self._paths_cache.append((name, adcode, rings, kind))
        # 底: 全部省份填色
        for name, adcode, rings, kind in self._paths_cache:
            if kind != "poly":
                continue
            n = self._region_count(adcode)
            path = QPainterPath()
            path.setFillRule(Qt.OddEvenFill)
            for ring in rings:
                poly = [QPointF(*self._proj(x, y)) for x, y in ring]
                path.addPolygon(_make_polygon(poly))
                path.closeSubpath()
            fill = self._tier_color(n)
            if name == self._hover:
                p.setPen(QPen(QColor(theme.BLUE), 1.4 * k))
                fill = QColor(fill).lighter(105) if n else QColor(LAND)
            else:
                p.setPen(QPen(QColor("#DDE1E6"), 0.7 * k))
            p.setBrush(fill)
            p.drawPath(path)
        # 九段线/界线
        for name, adcode, lines, kind in self._paths_cache:
            if kind != "line":
                continue
            p.setPen(QPen(QColor("#C6CDD6"), 1.0 * k))
            for line in lines:
                pts = [QPointF(*self._proj(x, y)) for x, y in line]
                for i in range(len(pts) - 1):
                    p.drawLine(pts[i], pts[i + 1])
        # 文字标注: 有收录且非小省 → 省名+数字直接显示(反馈8)
        p.setFont(QFont("", max(8, round(8 * k)), QFont.Bold))
        for name, adcode, rings, kind in self._paths_cache:
            if kind != "poly":
                continue
            n = self._region_count(adcode)
            if n <= 0 or name in TINY:
                continue
            cx, cy = self._ring_center(rings[0])
            short = SHORT.get(name, name[:2])
            p.setPen(QColor("#1F4D3F"))
            rect = QRectF(cx - 26 * k, cy - 14 * k, 52 * k, 30 * k)
            p.drawText(rect, Qt.AlignCenter,
                       t(f"{short}\n{n} 种", f"{short}\n{n}") if n else short)
        # 小省有收录: 画圆点提示(数字走悬浮)
        for name, adcode, rings, kind in self._paths_cache:
            if kind != "poly" or name not in TINY:
                continue
            n = self._region_count(adcode)
            if n <= 0:
                continue
            cx, cy = self._ring_center(rings[0])
            p.setPen(QPen(QColor("#1F4D3F"), 1.2 * k))
            p.setBrush(QColor("#34C759"))
            p.drawEllipse(QPointF(cx, cy), 4.5 * k, 4.5 * k)
        p.end()

    def _ring_center(self, ring) -> tuple[float, float]:
        if not ring:
            return self._w / 2, self._h / 2
        xs = [x for x, _y in ring]
        ys = [y for _x, y in ring]
        return self._proj((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)


def _make_polygon(pts: list[QPointF]):
    from PySide6.QtGui import QPolygonF
    return QPolygonF(pts)


def map_legend() -> QLabel:
    """色阶图例(紧凑行)。"""
    swatch = "  ".join(
        f'<span style="background:{c};color:{c}">▉▉</span>'
        f'<span style="color:{theme.LABEL_2}">{lb}</span>'
        for lb, c in zip(
            (t("1-2 种", "1-2"), t("3-5 种", "3-5"), t("6-11 种", "6-11"),
             t("≥12 种", "12+")),
            ("#D7EEDD", "#A8E0BC", "#6FC992", "#34C759")))
    lb = QLabel(t(f"收录鸟种数：{swatch}　·　滚轮缩放 / 拖动平移 / 双击复位",
                  f"Species recorded: {swatch}  ·  wheel zoom / drag pan / "
                  f"double-click reset"))
    lb.setTextFormat(Qt.RichText)
    lb.setStyleSheet("background:transparent;font-size:12px;")
    return lb
