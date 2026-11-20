# -*- coding: utf-8 -*-
"""年鉴 A4 页面模型与绘制(设计规范-年鉴与静态站 §3, 2026-11-20 重做)。

**单一排版真相**: 页面一律按毫米绘制, 调用方只给 k(每毫米多少设备像素)
——PDF(150dpi→5.906 px/mm)与软件内预览(任意缩放)走同一套 draw()。
规范 §3.4「不要为软件预览和 PDF 分别维护两套布局」由此保证。

页面序: 封面 → 年度回顾 → 鸟种档案(2列×3行, 自动分页) → 年度足迹(地图)
→ 年度时间线 → 年度精选十八图(3×6, 统一 5:3 裁切)。

色板只用规范值(浅色/深色两套); 照片不做任何滤镜/调色(规范 §3.5)。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QPainter, QPainterPath, QPen,
                           QPixmap)

from ..i18n import t, sname
from ..paths import assets_dir

# ---------------- 版面常量(规范 §3.1) ----------------
PAGE_W, PAGE_H = 210.0, 297.0     # mm, A4 竖版
MARGIN = 14.0                     # mm, 四边安全边距
CONTENT_W = PAGE_W - 2 * MARGIN   # 182mm
CONTENT_H = PAGE_H - 2 * MARGIN   # 269mm
GUTTER = 4.0                      # mm, 12 列栅格间距
COL = (CONTENT_W - 11 * GUTTER) / 12.0

SP_PER_PAGE = 6                   # 鸟种档案每页卡数(2列×3行)
GRID_COLS, GRID_ROWS = 3, 6       # 十八图 3×6
GRID_RATIO = 5 / 3                # 统一裁切比例(宽/高)


class Palette:
    """规范 §1.3 色板(浅/深两套, 信息层级一致)。"""

    def __init__(self, bg, card, ink, ink2, ink3, line, accent, map_bg,
                 hi, scrim=(0, 0, 0)):
        self.bg, self.card = bg, card
        self.ink, self.ink2, self.ink3 = ink, ink2, ink3
        self.line, self.accent, self.map_bg = line, accent, map_bg
        self.hi = hi          # 有数据省份浅填充
        self.scrim = scrim    # 封面色调(0=黑)


LIGHT = Palette(bg="#FFFFFF", card="#FFFFFF", ink="#20252B", ink2="#68727D",
                ink3="#929BA5", line="#E7EBEF", accent="#527C70",
                map_bg="#EDF2F5", hi="#E2EFE8")
DARK = Palette(bg="#111820", card="#1B2630", ink="#F3F5F7", ink2="#A6B0BA",
               ink3="#77838F", line="#303C47", accent="#83B5A2",
               map_bg="#202C36", hi="#26352F")


# ---------------- QPainter 毫米助手 ----------------
class Pg:
    """按毫米作画的迷你包装: 所有坐标/字号都乘 k(px per mm)。"""

    def __init__(self, p: QPainter, k: float, pal: Palette):
        self.p, self.k, self.pal = p, k, pal

    def r(self, x, y, w, h) -> QRectF:
        return QRectF(x * self.k, y * self.k, w * self.k, h * self.k)

    def mm(self, v: float) -> float:
        return v * self.k

    def font(self, h_mm: float, bold=False, serif=False, tracking=0.0):
        f = QFont("Georgia" if serif else "Microsoft YaHei")
        if serif:
            f.setFamilies(["Georgia", "Noto Serif SC", "SimSun"])
        else:
            f.setFamilies(["Microsoft YaHei", "Segoe UI", "Noto Sans SC"])
        f.setPixelSize(max(1, round(h_mm * self.k)))
        f.setBold(bold)
        if tracking:
            f.setLetterSpacing(QFont.AbsoluteSpacing, tracking * self.k)
        return f

    def text(self, rect: QRectF, s: str, h_mm: float, color: str,
             bold=False, serif=False, align=Qt.AlignLeft | Qt.AlignVCenter,
             tracking=0.0):
        self.p.setFont(self.font(h_mm, bold, serif, tracking))
        self.p.setPen(QColor(color))
        self.p.drawText(rect, int(align), s)

    def fill(self, rect: QRectF, color: str, radius=0.0):
        self.p.setPen(Qt.NoPen)
        self.p.setBrush(QColor(color))
        if radius:
            self.p.drawRoundedRect(rect, self.mm(radius), self.mm(radius))
        else:
            self.p.drawRect(rect)

    def line(self, x1, y1, x2, y2, color: str, w_mm=0.25):
        self.p.setPen(QPen(QColor(color), max(1.0, self.mm(w_mm))))
        self.p.drawLine(QPointF(self.mm(x1), self.mm(y1)),
                        QPointF(self.mm(x2), self.mm(y2)))

    def photo(self, pm: QPixmap | None, rect: QRectF, radius=0.0,
              pos=(0.5, 0.5)) -> bool:
        """cover 裁切填充(保护主体: pos 控制取景重心)。缺图=浅底占位。"""
        if pm is None or pm.isNull():
            self.fill(rect, self.pal.card if self.pal.bg != self.pal.card
                      else "#F0F1F4", radius)
            return False
        scaled = pm.scaled(int(rect.width()), int(rect.height()),
                           Qt.KeepAspectRatioByExpanding,
                           Qt.SmoothTransformation)
        sx = (scaled.width() - rect.width()) * pos[0]
        sy = (scaled.height() - rect.height()) * pos[1]
        self.p.save()
        if radius:
            clip = QPainterPath()
            clip.addRoundedRect(rect, self.mm(radius), self.mm(radius))
            self.p.setClipPath(clip)
        else:
            self.p.setClipRect(rect)
        self.p.drawPixmap(int(rect.x() - sx), int(rect.y() - sy), scaled)
        self.p.restore()
        return True


# ---------------- 省界几何(地图页共用) ----------------
_LON0, _LON1, _LAT0, _LAT1 = 72.5, 136.0, 17.0, 54.5
_KX = math.cos(math.radians(35.0))
_MAP_UNITS = 1000.0
_geo_cache: dict | None = None


def _load_geo():
    global _geo_cache
    if _geo_cache is not None:
        return _geo_cache
    p = assets_dir() / "map" / "china_provinces.json"
    feats = []
    if p.is_file():
        gj = json.loads(p.read_text(encoding="utf-8"))
        for f in gj.get("features", []):
            props = f.get("properties") or {}
            g = f.get("geometry") or {}
            gt = g.get("type")
            cs = g.get("coordinates") or []
            polys = [cs] if gt == "Polygon" else (
                [x for x in cs if x] if gt == "MultiPolygon" else [])
            if polys:
                feats.append({"name": str(props.get("name") or ""),
                              "adcode": str(props.get("adcode") or ""),
                              "polys": polys})
    raw = [((x - _LON0) * _KX, _LAT1 - y) for f in feats for poly in f["polys"]
           for ring in poly for x, y in ring]
    if raw:
        xs = [q[0] for q in raw]
        ys = [q[1] for q in raw]
        box = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    else:
        box = (0.0, 0.0, 1.0, 1.0)
    _geo_cache = {"feats": feats, "box": box}
    return _geo_cache


def map_box() -> tuple[float, float]:
    """地图坐标空间宽高(1 单位 = box 的 1/1000)。"""
    b = _load_geo()["box"]
    return _MAP_UNITS, _MAP_UNITS * b[3] / b[2] if b[2] else _MAP_UNITS


def proj_geo(lon: float, lat: float) -> tuple[float, float]:
    b = _load_geo()["box"]
    x = (lon - _LON0) * _KX
    y = _LAT1 - lat
    return ((x - b[0]) / b[2] * _MAP_UNITS,
            (y - b[1]) / b[3] * _MAP_UNITS)


def province_paths() -> list[tuple[str, QPainterPath]]:
    """省界 → QPainterPath(地图坐标空间); 一次构建缓存。"""
    g = _load_geo()
    if "paths" in g:
        return g["paths"]
    out = []
    for f in g["feats"]:
        path = QPainterPath()
        path.setFillRule(Qt.OddEvenFill)
        for poly in f["polys"]:
            for ring in poly:
                if len(ring) < 3:
                    continue
                pts = [QPointF(*proj_geo(x, y)) for x, y in ring]
                path.moveTo(pts[0])
                for q in pts[1:]:
                    path.lineTo(q)
                path.closeSubpath()
        out.append((f["name"], path))
    g["paths"] = out
    return out


def province_rings() -> list[tuple[str, list[list[tuple[float, float]]]]]:
    """省界环列表(地图坐标空间, 未缩放) —— 静态站生成 SVG 用。"""
    g = _load_geo()
    if "rings" in g:
        return g["rings"]
    out = []
    for f in g["feats"]:
        rings = []
        for poly in f["polys"]:
            for ring in poly:
                pts = [proj_geo(x, y) for x, y in ring]
                if len(pts) >= 3:
                    rings.append(pts)
        if rings:
            out.append((f["name"], rings))
    g["rings"] = out
    return out


def province_centers() -> dict[str, tuple[float, float]]:
    """省名 → 面积最大环的外接框中心(静态站点位用; 隐私=只到省)。"""
    g = _load_geo()
    if "centers" in g:
        return g["centers"]
    out = {}
    for name, rings in province_rings():
        best = max(rings, key=lambda r: (max(p[0] for p in r) -
                                         min(p[0] for p in r)) *
                   (max(p[1] for p in r) - min(p[1] for p in r)))
        xs = [p[0] for p in best]
        ys = [p[1] for p in best]
        out[name] = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    g["centers"] = out
    return out


def region_province_name() -> dict[str, str]:
    """region_id(CN-XX) → 省名(highlight 与静态站点位共用)。"""
    g = _load_geo()
    if "rid_name" in g:
        return g["rid_name"]
    from ..ui.distribution_map import ADCODE_TO_REGION
    m = {}
    for f in g["feats"]:
        try:
            adcode = int(f["adcode"] or 0)
        except (TypeError, ValueError):
            continue          # 九段线等特殊要素 adcode 形如 "100000_JD"
        rid = ADCODE_TO_REGION.get(adcode)
        if rid:
            m[rid] = f["name"]
    g["rid_name"] = m
    return m


# ---------------- 文档 ----------------
class YearbookDoc:
    """一本年鉴: 页数 + 逐页绘制。数据全部真实(不做填充/不重复照片)。"""

    def __init__(self, rep: dict, species: list[dict], geo: dict,
                 timeline: list[dict], year: str, pal: Palette = LIGHT,
                 cover: str = "full", creator: str = "",
                 photo=None):
        self.rep, self.species, self.geo = rep, species, geo
        self.timeline, self.year = timeline, year
        self.pal, self.cover, self.creator = pal, cover, creator
        self.photo = photo or (lambda h, path, px: None)
        self.sp_pages = max(1, math.ceil(len(species) / SP_PER_PAGE))

    # 页序: 1 封面 / 2 回顾 / 3.. 档案 / +1 地图 / +1 时间线 / +1 十八图
    @property
    def page_count(self) -> int:
        return 2 + self.sp_pages + 1 + 1 + 1

    def draw(self, p: QPainter, index: int, k: float):
        pg = Pg(p, k, self.pal)
        i = index + 1
        if i == 1:
            self._cover(pg)
        elif i == 2:
            self._overview(pg)
        elif i <= 2 + self.sp_pages:
            page = i - 3
            self._species(pg, page)
        elif i == 3 + self.sp_pages:
            self._map(pg)
        elif i == 4 + self.sp_pages:
            self._timeline(pg)
        else:
            self._grid(pg)
        self._footer(pg, i)

    # ---------- 通用 ----------
    def _footer(self, pg: Pg, no: int):
        pg.text(pg.r(MARGIN, PAGE_H - MARGIN + 4, 80, 4),
                f"BirdTrace · {self.year}", 2.6, pg.pal.ink3,
                tracking=0.08)
        pg.text(pg.r(PAGE_W - MARGIN - 20, PAGE_H - MARGIN + 4, 20, 4),
                str(no), 2.6, pg.pal.ink3, align=Qt.AlignRight |
                Qt.AlignVCenter)

    def _head(self, pg: Pg, eyebrow: str, title: str, sub: str = ""):
        pg.text(pg.r(MARGIN, MARGIN, CONTENT_W, 5), eyebrow, 2.6,
                pg.pal.accent, bold=True, tracking=0.22)
        pg.text(pg.r(MARGIN, MARGIN + 7, CONTENT_W, 12), title, 9,
                pg.pal.ink, bold=True, serif=True)
        if sub:
            pg.text(pg.r(MARGIN, MARGIN + 21, CONTENT_W, 5), sub, 3.1,
                    pg.pal.ink2, tracking=0.14)

    # ---------- 1 封面 ----------
    def _cover(self, pg: Pg):
        best = self.rep.get("best18") or []
        hero = best[0] if best else None
        pal = pg.pal
        pm = self.photo(hero["hash"], hero["path"], 1700) if hero else None
        if self.cover == "split":
            pg.fill(pg.r(0, 0, PAGE_W, PAGE_H), pal.bg)
            box = pg.r(0, 0, PAGE_W, PAGE_H * 0.69)
            pg.photo(pm, box, pos=(0.5, 0.4))
            pg.text(pg.r(MARGIN, MARGIN, 60, 4), "BirdTrace", 3.2,
                    "#FFFFFF", serif=True, tracking=0.06)
            pg.text(pg.r(MARGIN + 22, MARGIN, 60, 4), "ANNUAL YEARBOOK",
                    2.2, "#FFFFFF", tracking=0.2)
            y = PAGE_H * 0.69 + 12
            pg.text(pg.r(MARGIN, y, CONTENT_W, 34), self.year, 33,
                    pal.ink, serif=True)
            pg.text(pg.r(MARGIN, y + 34, CONTENT_W, 8),
                    t("年度摄影年鉴", "Annual Photobook"), 6.2, pal.ink,
                    bold=True, tracking=0.28)
            pg.text(pg.r(MARGIN, y + 46, CONTENT_W, 4), "ANNUAL PHOTOBOOK",
                    2.2, pal.ink3, tracking=0.28)
            self._cover_stats(pg, y + 58, pal.ink, pal.ink2)
            return
        # 满版: 深色压暗 + 白字(照片提供色彩, 不做滤镜)
        pg.photo(pm, pg.r(0, 0, PAGE_W, PAGE_H), pos=(0.5, 0.42))
        grad = pg.r(0, 0, PAGE_W, PAGE_H)
        pg.p.save()
        from PySide6.QtGui import QLinearGradient
        lg = QLinearGradient(grad.topLeft(), grad.bottomLeft())
        lg.setColorAt(0.0, QColor(8, 10, 10, 150))
        lg.setColorAt(0.26, QColor(8, 10, 10, 30))
        lg.setColorAt(0.44, QColor(8, 10, 10, 0))
        lg.setColorAt(0.74, QColor(8, 10, 10, 140))
        lg.setColorAt(1.0, QColor(8, 10, 10, 225))
        pg.p.setPen(Qt.NoPen)
        pg.p.setBrush(lg)
        pg.p.drawRect(grad)
        pg.p.restore()
        pg.text(pg.r(MARGIN, MARGIN, 40, 4), "BirdTrace", 3.4, "#FFFFFF",
                serif=True, tracking=0.06)
        pg.line(MARGIN + 26, MARGIN + 2.2, PAGE_W - MARGIN - 60,
                MARGIN + 2.2, "#FFFFFF", 0.2)
        pg.text(pg.r(PAGE_W - MARGIN - 62, MARGIN, 62, 4),
                t("年度摄影年鉴 · ANNUAL YEARBOOK",
                  "ANNUAL YEARBOOK"), 2.4, "#FFFFFF",
                align=Qt.AlignRight | Qt.AlignVCenter, tracking=0.16)
        y = PAGE_H - MARGIN - 72
        pg.text(pg.r(MARGIN - 1, y, CONTENT_W, 40), self.year, 34,
                "#FFFFFF", serif=True)
        pg.text(pg.r(MARGIN, y + 40, CONTENT_W, 9),
                t("年度摄影年鉴", "Annual Photobook"), 6.6, "#FFFFFF",
                bold=True, tracking=0.3)
        pg.text(pg.r(MARGIN, y + 51, CONTENT_W, 4), "ANNUAL PHOTOBOOK",
                2.2, "#E8ECEF", tracking=0.3)
        self._cover_stats(pg, y + 62, "#FFFFFF", "#D8DEE3")
        if self.creator:
            pg.text(pg.r(PAGE_W - MARGIN - 80, y + 65, 80, 4),
                    t(f"摄影 · {self.creator}", f"Photography · {self.creator}"),
                    2.3, "#C9D0D6", align=Qt.AlignRight | Qt.AlignVCenter,
                    tracking=0.08)

    def _cover_stats(self, pg: Pg, y: float, ink: str, ink2: str):
        rep = self.rep
        items = [(rep.get("photos", 0), t("作品", "Photos")),
                 (rep.get("total_species", 0), t("鸟种", "Species")),
                 (len(self.geo.get("spots") or []), t("鸟点", "Spots"))]
        x = MARGIN
        for val, label in items:
            pg.text(pg.r(x, y, 16, 7), str(val), 5.2, ink, serif=True)
            pg.text(pg.r(x + 13, y + 1.4, 18, 5), label, 2.5, ink2,
                    tracking=0.1)
            x += 26

    # ---------- 2 年度回顾 ----------
    def _overview(self, pg: Pg):
        pal = pg.pal
        pg.fill(pg.r(0, 0, PAGE_W, PAGE_H), pal.bg)
        self._head(pg, f"{self.year} YEAR IN REVIEW",
                   t("年度回顾", "A Year in Review"),
                   t("一年的野外记录", "A year in the field"))
        rep = self.rep
        monthly = rep.get("monthly") or [0] * 12
        nums = [(rep.get("photos", 0), t("年度作品", "Photos")),
                (rep.get("new", 0), t("年度新种", "New species")),
                (len(self.geo.get("spots") or []), t("鸟点", "Spots")),
                (sum(1 for v in monthly if v), t("活跃月份", "Active months"))]
        y = MARGIN + 32
        for idx, (val, label) in enumerate(nums):
            x = MARGIN + idx * (COL * 3 + GUTTER)
            pg.text(pg.r(x, y, COL * 3, 16), str(val), 12, pal.ink,
                    serif=True)
            pg.text(pg.r(x, y + 16, COL * 3, 4), label, 2.6, pal.ink2,
                    tracking=0.1)
            pg.line(x, y + 23, x + 7, y + 23, pal.accent, 0.5)
        # 月度双图: 作品分布 + 鸟种发现趋势(规范 §3.2)
        y = MARGIN + 66
        half = (CONTENT_W - 10) / 2
        for ci, (vals, cap) in enumerate(((monthly, t(
                "月度作品分布 · PHOTOS BY MONTH", "PHOTOS BY MONTH")),
                (rep.get("monthly_species") or [0] * 12, t(
                 "月度鸟种发现 · SPECIES BY MONTH", "SPECIES BY MONTH")))):
            x0 = MARGIN + ci * (half + 10)
            pg.text(pg.r(x0, y, half, 4), cap, 2.4, pal.ink3,
                    tracking=0.14)
            pg.line(x0, y + 6, x0 + half, y + 6, pal.line, 0.2)
            ch, base = 32.0, y + 44
            mx = max(vals) or 1
            slot = half / 12
            for i, v in enumerate(vals):
                cx = x0 + slot * i + slot / 2
                bh = (ch - 4) * v / mx if v else 0.6
                bw = min(4.6, slot * 0.52)
                pg.fill(pg.r(cx - bw / 2, base - bh, bw, bh),
                        pal.accent if v else pal.line, 0.4)
                pg.text(pg.r(cx - slot / 2, base + 1.4, slot, 3.2),
                        str(i + 1), 1.9, pal.ink3, align=Qt.AlignCenter)
                if v:
                    pg.text(pg.r(cx - slot / 2, base - bh - 4.2, slot, 3.2),
                            str(v), 1.9, pal.ink2, align=Qt.AlignCenter)
        y = y + 50
        # 年度之最 + 关键词
        pg.line(MARGIN, y, PAGE_W - MARGIN, y, pal.line, 0.2)
        y += 6
        pg.text(pg.r(MARGIN, y, COL * 5, 4),
                t("年度之最 · HIGHLIGHTS", "HIGHLIGHTS"), 2.4, pal.ink3,
                tracking=0.16)
        top = self._top_species()
        busy = self._busiest_day()
        rows = []
        if top:
            rows.append((top[0], t(f"拍摄最多 · {top[1]} 张",
                                   f"Most shot · {top[1]} photos")))
        if busy:
            rows.append((busy[0], t(f"最忙一天 · {busy[1]} 张",
                                    f"Biggest day · {busy[1]} photos")))
        if rep.get("days"):
            rows.append((t(f"{rep['days']} 天", f"{rep['days']} days"),
                         t("有记录的拍摄日", "Days with records")))
        yy = y + 7
        for main, sub in rows:
            pg.text(pg.r(MARGIN, yy, COL * 6, 6), main, 4.2, pal.ink,
                    serif=True)
            pg.text(pg.r(MARGIN + COL * 6, yy + 1.2, COL * 6, 4), sub, 2.5,
                    pal.ink2)
            yy += 8
        # 通栏代表作(有则画, 没有就留白——不虚构)
        best = (rep.get("best18") or [])
        if best:
            r = best[min(1, len(best) - 1)]
            by = yy + 6                      # 紧跟年度之最, 通栏收尾
            bh = min(88.0, PAGE_H - MARGIN - by)
            pm = self.photo(r["hash"], r["path"], 1400)
            pg.photo(pm, pg.r(MARGIN, by, CONTENT_W, bh), 0.8,
                     pos=(0.5, 0.45))
            cap = f"{r['name']} · {(r.get('taken_at') or '')[:10]}"
            pg.text(pg.r(MARGIN + 3, by + bh - 8, CONTENT_W - 6, 5),
                    cap, 2.4, "#FFFFFF")

    def _top_species(self):
        if self.species:
            s = max(self.species, key=lambda x: x["n"])
            return s["cn"], s["n"]
        return None

    def _busiest_day(self):
        # 时间线里月内条目带 n; 用月度峰值代表最忙月(不猜日)
        monthly = self.rep.get("monthly") or [0] * 12
        if any(monthly):
            i = max(range(12), key=lambda x: monthly[x])
            return f"{i + 1:02d}", monthly[i]
        return None

    # ---------- 3.. 鸟种档案 ----------
    def _species(self, pg: Pg, page: int):
        pal = pg.pal
        pg.fill(pg.r(0, 0, PAGE_W, PAGE_H), pal.bg)
        total = len(self.species)
        first = page == 0
        if first:
            pg.text(pg.r(MARGIN, MARGIN, CONTENT_W, 5), "SPECIES ARCHIVE",
                    2.6, pal.accent, bold=True, tracking=0.22)
            pg.text(pg.r(MARGIN, MARGIN + 7, 120, 12),
                    t("年度鸟种档案", "Species Archive"), 9, pal.ink,
                    bold=True, serif=True)
            pg.text(pg.r(PAGE_W - MARGIN - 70, MARGIN + 11, 70, 5),
                    t(f"共 {total} 种 · 按首见日期",
                      f"{total} species · by first sighting"), 2.6,
                    pal.ink2, align=Qt.AlignRight | Qt.AlignVCenter)
            pg.line(MARGIN, MARGIN + 24, PAGE_W - MARGIN, MARGIN + 24,
                    pal.line, 0.2)
            top = MARGIN + 30
        else:
            pg.text(pg.r(MARGIN, MARGIN, CONTENT_W, 5),
                    t(f"年度鸟种档案 · 续", "Species Archive · cont."), 2.6,
                    pal.accent, bold=True, tracking=0.22)
            pg.line(MARGIN, MARGIN + 8, PAGE_W - MARGIN, MARGIN + 8,
                    pal.line, 0.2)
            top = MARGIN + 14
        items = self.species[page * SP_PER_PAGE:(page + 1) * SP_PER_PAGE]
        cw = (CONTENT_W - GUTTER * 2) / 2
        ph_h = cw * 0.60      # 与设计稿一致(87×52mm), 3 行不溢出
        row_h = ph_h + 22
        for idx, s in enumerate(items):
            cx = MARGIN + (idx % 2) * (cw + GUTTER * 2)
            cy = top + (idx // 2) * (row_h + GUTTER * 2)
            box = pg.r(cx, cy, cw, ph_h)
            pm = self.photo(s.get("hash"), s.get("path"), int(cw * 8))
            pg.photo(pm, box, 0.6, pos=(0.5, 0.4))
            pg.text(pg.r(cx, cy + ph_h + 2.5, cw, 5.4), s["cn"], 4.2,
                    pal.ink, bold=True)
            if s.get("en"):
                pg.text(pg.r(cx, cy + ph_h + 8.4, cw, 4), s["en"], 2.4,
                        pal.ink2)
            meta_y = cy + ph_h + 13.5
            if s.get("first_record"):
                bw = 9.0
                pg.p.setPen(QPen(QColor(pal.accent), max(1, pg.mm(0.2))))
                pg.p.setBrush(Qt.NoBrush)
                pg.p.drawRoundedRect(pg.r(cx, meta_y, bw, 4.2),
                                     pg.mm(2.1), pg.mm(2.1))
                pg.text(pg.r(cx, meta_y, bw, 4.2), t("首录", "1st"), 2.0,
                        pal.accent, align=Qt.AlignCenter, tracking=0.08)
                meta_x = cx + bw + 2.5
            else:
                meta_x = cx
            bits = [t(f"{s['n']} 张", f"{s['n']} photos"),
                    (s.get("first") or "")[:10]]
            if s.get("region"):
                bits.append(s["region"])
            pg.text(pg.r(meta_x, meta_y, cw - (meta_x - cx), 4.2),
                    " · ".join(x for x in bits if x), 2.2, pal.ink3,
                    tracking=0.04)

    # ---------- 地图 ----------
    def _map(self, pg: Pg):
        pal = pg.pal
        pg.fill(pg.r(0, 0, PAGE_W, PAGE_H), pal.bg)
        self._head(pg, "FOOTPRINTS", t("年度足迹", "Where I Went Birding"),
                   t("省份与鸟点分布", "Provinces & hotspots"))
        box = pg.r(MARGIN, MARGIN + 32, CONTENT_W, 118)
        pg.fill(box, pal.map_bg, 1.0)
        mw, mh = map_box()
        scale = min(box.width() / mw, box.height() / mh) * 0.92
        ox = box.x() + (box.width() - mw * scale) / 2
        oy = box.y() + (box.height() - mh * scale) / 2
        rid_name = region_province_name()
        hi_names = {rid_name.get(p["rid"]) for p in
                    (self.geo.get("provinces") or [])} - {None}
        pg.p.save()
        pg.p.setRenderHint(QPainter.Antialiasing)
        for name, path in province_paths():
            tpath = QPainterPath(path)
            tp = QPainterPath()
            tp.addPath(tpath)
            pg.p.save()
            pg.p.translate(ox, oy)
            pg.p.scale(scale, scale)
            pg.p.setBrush(QColor(pal.hi if name in hi_names else pal.card))
            pg.p.setPen(QPen(QColor("#C9D4DC" if pal is LIGHT else "#2E3C48"),
                             max(0.6, 1.0 / scale)))
            pg.p.drawPath(tp)
            pg.p.restore()
        # 鸟点(有坐标才画)
        for sp in (self.geo.get("spots") or []):
            x, y = proj_geo(sp["lon"], sp["lat"])
            px, py = ox + x * scale, oy + y * scale
            pg.p.setPen(QPen(QColor("#FFFFFF"), max(0.5, pg.mm(0.3))))
            pg.p.setBrush(QColor(pal.accent))
            r = pg.mm(1.5)
            pg.p.drawEllipse(QPointF(px, py), r, r)
        pg.p.restore()
        # 图例 + 省份行(坐标一律 mm: box 是像素, 不能混用)
        y = MARGIN + 32 + 118 + 4
        n_prov = len(hi_names)
        pg.text(pg.r(MARGIN, y, CONTENT_W / 2, 4),
                t(f"● 鸟点 {len(self.geo.get('spots') or [])} 处",
                  f"● {len(self.geo.get('spots') or [])} hotspots"),
                2.4, pal.ink2)
        pg.text(pg.r(PAGE_W - MARGIN - 70, y, 70, 4),
                t(f"{n_prov} 个省级地区", f"{n_prov} provinces"), 2.4,
                pal.ink2, align=Qt.AlignRight | Qt.AlignVCenter)
        y += 6
        pg.text(pg.r(MARGIN, y, CONTENT_W, 4),
                t("无坐标的照片不显示在地图上（不虚构位置）。",
                  "Photos without coordinates are not placed (no guessing)."),
                2.2, pal.ink3)
        y += 8
        provs = (self.geo.get("provinces") or [])[:5]
        if not provs:
            pg.text(pg.r(MARGIN, y, CONTENT_W, 10),
                    t("这一年还没有带地区/坐标的记录——导入带 GPS 的照片后"
                      "这里会显示省份分布。",
                      "No geo-tagged records this year — import photos with "
                      "GPS to see provinces here."), 2.8, pal.ink2)
            return
        for pv in provs:
            pg.line(MARGIN, y, PAGE_W - MARGIN, y, pal.line, 0.2)
            pg.text(pg.r(MARGIN, y + 1.2, 15, 8), str(pv["n"]), 4.6,
                    pal.ink, serif=True)
            pg.text(pg.r(MARGIN + 16, y + 2.2, CONTENT_W - 46, 6),
                    pv["name"], 3.0, pal.ink)
            pg.text(pg.r(PAGE_W - MARGIN - 40, y + 2.2, 40, 6),
                    t(f"{pv['n']} 张", f"{pv['n']} photos"), 2.4, pal.ink3,
                    align=Qt.AlignRight | Qt.AlignVCenter)
            y += 9
        # 三项统计(与设计稿一致: 鸟点/省级地区/拍摄天数)
        y += 6
        pg.line(MARGIN, y, PAGE_W - MARGIN, y, pal.line, 0.2)
        y += 7
        stats = [(len(self.geo.get("spots") or []), t("鸟点", "Hotspots")),
                 (n_prov, t("省级地区", "Provinces")),
                 (self.rep.get("days", 0), t("拍摄天数", "Days out"))]
        for idx, (val, label) in enumerate(stats):
            x = MARGIN + idx * (COL * 4 + GUTTER)
            pg.text(pg.r(x, y, COL * 4, 12), str(val), 8.5, pal.ink,
                    serif=True)
            pg.text(pg.r(x, y + 12, COL * 4, 4), label, 2.5, pal.ink2,
                    tracking=0.1)

    # ---------- 时间线 ----------
    def _timeline(self, pg: Pg):
        pal = pg.pal
        pg.fill(pg.r(0, 0, PAGE_W, PAGE_H), pal.bg)
        self._head(pg, "TIMELINE", t("年度时间线", "The Year, Month by Month"),
                   t("按月份组织的拍摄记录", "Month by month"))
        y = MARGIN + 32
        pg.line(MARGIN, y, PAGE_W - MARGIN, y, pal.line, 0.2)
        y += 4
        months = self.timeline or []
        if not months:
            pg.text(pg.r(MARGIN, y + 6, CONTENT_W, 12),
                    t("这一年还没有照片记录。",
                      "No photos recorded this year."), 3.0, pal.ink2)
            return
        line_x = MARGIN + 24
        bottom_limit = PAGE_H - MARGIN - 56
        for m in months:
            if y > bottom_limit:
                break
            # 月份标签
            pg.text(pg.r(MARGIN, y, 18, 10), m["ym"][5:7], 8.5, pal.ink,
                    serif=True)
            pg.text(pg.r(MARGIN, y + 8, 18, 4),
                    t(f"{m['n']} 张", f"{m['n']} photos"), 2.1, pal.ink3)
            # 节点
            pg.p.setPen(QPen(QColor("#FFFFFF"), max(1, pg.mm(0.6))))
            pg.p.setBrush(QColor(pal.accent))
            pg.p.drawEllipse(QPointF(pg.mm(line_x), pg.mm(y + 4)),
                             pg.mm(1.2), pg.mm(1.2))
            ey = y
            for it in m["items"]:
                th = pg.r(line_x + 5, ey - 1, 17, 11)
                pm = self.photo(it.get("hash"), it.get("path"),
                                int(th.width() * 1.6))
                pg.photo(pm, th, 0.5)
                pg.text(pg.r(line_x + 25, ey - 1, 60, 5), it["cn"], 3.2,
                        pal.ink, bold=True)
                pg.text(pg.r(line_x + 25, ey + 4, 80, 4),
                        t(f"{it['n']} 张", f"{it['n']} photos"), 2.1,
                        pal.ink3)
                ey += 12
            y = max(ey, y + 14) + 2
        # 线(月份节点连起来)
        pg.line(line_x, MARGIN + 36, line_x, y - 4, pal.line, 0.18)
        # 底部通栏照(有则放)
        grid = self.rep.get("best18") or []
        if grid:
            r = grid[-1]
            ty = PAGE_H - MARGIN - 46
            pm = self.photo(r["hash"], r["path"], 1400)
            pg.photo(pm, pg.r(MARGIN, ty, CONTENT_W, 46), 0.8,
                     pos=(0.5, 0.45))
            pg.text(pg.r(MARGIN + 3, ty + 38, CONTENT_W - 6, 5),
                    f"{r['name']} · {(r.get('taken_at') or '')[:10]}", 2.4,
                    "#FFFFFF")

    # ---------- 十八图 ----------
    def _grid(self, pg: Pg):
        pal = pg.pal
        pg.fill(pg.r(0, 0, PAGE_W, PAGE_H), pal.bg)
        pg.text(pg.r(MARGIN, MARGIN, CONTENT_W, 5), "SELECTED WORKS", 2.6,
                pal.accent, bold=True, tracking=0.22)
        pg.text(pg.r(MARGIN, MARGIN + 7, 130, 12),
                t("年度精选 · 十八图", "Selected Works"), 9, pal.ink,
                bold=True, serif=True)
        pg.text(pg.r(PAGE_W - MARGIN - 60, MARGIN + 11, 60, 5),
                t("按美学 × 置信", "Aesthetic × confidence"), 2.4, pal.ink3,
                align=Qt.AlignRight | Qt.AlignVCenter)
        pg.line(MARGIN, MARGIN + 24, PAGE_W - MARGIN, MARGIN + 24, pal.line,
                0.2)
        items = (self.rep.get("best18") or [])[:GRID_COLS * GRID_ROWS]
        if not items:
            pg.text(pg.r(MARGIN, MARGIN + 40, CONTENT_W, 12),
                    t("这一年还没有可评分的照片。",
                      "No scored photos this year."), 3.0, pal.ink2)
            return
        top = MARGIN + 29
        cw = (CONTENT_W - (GRID_COLS - 1) * 3.5) / GRID_COLS
        ch = cw / GRID_RATIO
        for i, r in enumerate(items):
            cx = MARGIN + (i % GRID_COLS) * (cw + 3.5)
            cy = top + (i // GRID_COLS) * (ch + 5.4)
            box = pg.r(cx, cy, cw, ch)
            pm = self.photo(r["hash"], r["path"], int(cw * 7))
            pg.photo(pm, box, 0.4, pos=(0.5, 0.45))
            # 底部渐变压暗 + 名字/日期(只叠在图上, 不占额外高度)
            from PySide6.QtGui import QLinearGradient
            grad = QRectF(box.x(), box.bottom() - pg.mm(9), box.width(),
                          pg.mm(9))
            lg = QLinearGradient(grad.topLeft(), grad.bottomLeft())
            lg.setColorAt(0.0, QColor(0, 0, 0, 0))
            lg.setColorAt(1.0, QColor(0, 0, 0, 150))
            pg.p.save()
            clip = QPainterPath()
            clip.addRoundedRect(box, pg.mm(0.4), pg.mm(0.4))
            pg.p.setClipPath(clip)
            pg.p.setPen(Qt.NoPen)
            pg.p.setBrush(lg)
            pg.p.drawRect(grad)
            pg.p.restore()
            nm = sname(r["name"], r.get("en", "")) if r.get("en") is not None \
                else r["name"]
            pg.text(QRectF(box.x() + pg.mm(2), box.bottom() - pg.mm(7),
                           box.width() - pg.mm(4), pg.mm(3.4)),
                    nm, 2.3, "#FFFFFF", bold=True)
            pg.text(QRectF(box.x() + pg.mm(2), box.bottom() - pg.mm(3.6),
                           box.width() - pg.mm(4), pg.mm(3)),
                    (r.get("taken_at") or "")[:10], 1.9, "#D5DBE0")


# ---------------- 组装 ----------------
def make_loader(lib, max_px: int | None = None):
    """照片加载器(带内存缓存)。预览传 max_px=512 只用缓存盘里的中图,
    避免为屏幕预览解码原图; PDF 不传=按需生成大图。"""
    from ..media import cached_thumbnail, ensure_thumbnail
    cache: dict[tuple[str, int], QPixmap | None] = {}

    def f(h, path, px):
        if not h:
            return None
        if max_px:
            px = min(px, max_px)
        key = (h, px)
        if key in cache:
            return cache[key]
        try:
            tp = cached_thumbnail(lib.root, h, px) or (
                ensure_thumbnail(lib.root, path, h, px) if path else None)
        except OSError:
            tp = None
        pm = QPixmap(str(tp)) if tp else None
        if pm is not None and pm.isNull():
            pm = None
        cache[key] = pm
        return pm

    return f


def build_doc(lib, year: str, pal: Palette = LIGHT, cover: str = "full",
              max_px: int | None = None) -> YearbookDoc:
    """按年份组装文档(软件内预览与 PDF 导出共用同一份数据与排版)。"""
    rep = lib.yearly_report(year)
    species = lib.year_species(year)
    geo = lib.year_geo(year)
    tl = lib.year_timeline(year)
    creator = lib.copyright_defaults_get().get("creator") or ""
    return YearbookDoc(rep, species, geo, tl, year, pal, cover, creator,
                       photo=make_loader(lib, max_px))
