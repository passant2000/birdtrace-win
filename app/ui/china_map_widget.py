# -*- coding: utf-8 -*-
"""省级足迹图·自绘版(实测反馈8, 2026-11-19): QPaint 直接画 choropleth
——色深=该省收录鸟种数, 有数据的省**直接标注省名+数字**(不用悬浮才能看),
悬浮仍有 tooltip。免 WebEngine(生涯页轻加载)。几何复用 DataV 省界
GeoJSON(distribution_map 同源), 简单线性投影(省级填色对投影误差不敏感)。"""
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
        self.setMinimumHeight(430)
        self.setMouseTracking(True)
        self._name_for_region = {}
        from .distribution_map import ADCODE_TO_REGION
        from ..core import regions
        for adcode, rid in ADCODE_TO_REGION.items():
            # GeoJSON adcode 解析为 str, 映射键是 int——统一 str 化
            self._name_for_region[str(adcode)] = rid

    # ---------- 投影 ----------
    def _proj(self, lon, lat):
        # 简单等距圆柱+纬度中值压缩(省级填色够用); 加 0.82 经度系数保比例
        x = (lon - _LON0) / (_LON1 - _LON0)
        y = (_LAT1 - lat) / (_LAT1 - _LAT0)
        return x * self._w * 0.92 + self._w * 0.04, \
            y * self._h * 0.94 + self._h * 0.03

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

    def mouseMoveEvent(self, e):
        name = self._feature_at(e.position())
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

    # ---------- 绘制 ----------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._w = float(self.width())
        self._h = float(self.height())
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
                p.setPen(QPen(QColor(theme.BLUE), 1.4))
                fill = QColor(fill).lighter(105) if n else QColor(LAND)
            else:
                p.setPen(QPen(QColor("#DDE1E6"), 0.7))
            p.setBrush(fill)
            p.drawPath(path)
        # 九段线/界线
        for name, adcode, lines, kind in self._paths_cache:
            if kind != "line":
                continue
            p.setPen(QPen(QColor("#C6CDD6"), 1.0))
            for line in lines:
                pts = [QPointF(*self._proj(x, y)) for x, y in line]
                for i in range(len(pts) - 1):
                    p.drawLine(pts[i], pts[i + 1])
        # 文字标注: 有收录且非小省 → 省名+数字直接显示(反馈8)
        p.setFont(QFont("", 8, QFont.Bold))
        for name, adcode, rings, kind in self._paths_cache:
            if kind != "poly":
                continue
            n = self._region_count(adcode)
            if n <= 0 or name in TINY:
                continue
            cx, cy = self._ring_center(rings[0])
            short = SHORT.get(name, name[:2])
            p.setPen(QColor("#1F4D3F"))
            rect = QRectF(cx - 26, cy - 14, 52, 30)
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
            p.setPen(QPen(QColor("#1F4D3F"), 1.2))
            p.setBrush(QColor("#34C759"))
            p.drawEllipse(QPointF(cx, cy), 4.5, 4.5)
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
    lb = QLabel(t(f"收录鸟种数：{swatch}", f"Species recorded: {swatch}"))
    lb.setTextFormat(Qt.RichText)
    lb.setStyleSheet("background:transparent;font-size:12px;")
    return lb
