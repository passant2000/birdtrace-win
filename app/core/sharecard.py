# -*- coding: utf-8 -*-
"""分享卡渲染 v2 —— 参照观鸟社区卡片风格。

布局(宽1600, 整卡圆角, 照片满 bleed 占上部):
  ┌────────────────────┐
  │        照片         │
  ├────────────────────┤
  │ huáng yāo tài yáng… │            ┌ Life # 1 ┐
  │ 黄 腰 太 阳 鸟       │
  │ Crimson Sunbird     │
  │ ─────────────────   │
  │ 2024 · 05 · 12      │
  │ 上海市              │      (小鸟logo)
  │ zhaopaul            │
  └────────────────────┘
"""
from __future__ import annotations

from PySide6.QtCore import QBuffer, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QPainter, QPainterPath, QPen, QPixmap)

from ..i18n import t, sname

CARD_W = 1600
PAD = 112
RADIUS = 60

THEMES = {
    "light": {
        "bg": "#F0EFE4", "title": "#2E2E28", "pinyin": "#8A9455",
        "en": "#A5A596", "meta": "#6E6E5E", "line": "#DCDBCC",
        "pill_bg": "#8A9455", "pill_fg": "#F5F4EA",
    },
    "dark": {
        "bg": "#232320", "title": "#F0EFE4", "pinyin": "#A8B36E",
        "en": "#8A8A7C", "meta": "#A3A392", "line": "#3C3C34",
        "pill_bg": "#A8B36E", "pill_fg": "#232320",
    },
}


# 罕见度档位(内部中文码) -> 英文对照; 绘制时按当前语言取
RARITY_EN = {"常见": "Common", "较常见": "Fairly common",
             "不常见": "Uncommon", "稀有": "Rare", "罕见": "Very rare",
             "数据不足": "Insufficient data"}


def _font(size: int, weight: int = 400, italic: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(["MiSans", "HarmonyOS Sans SC", "PingFang SC",
                   "Microsoft YaHei UI", "Segoe UI"])
    f.setPixelSize(size)
    try:
        f.setWeight(QFont.Weight(weight))
    except ValueError:
        f.setWeight(QFont.Weight.Bold)
    f.setItalic(italic)
    return f


def _card_path(w: float, h: float, r: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), r, r)
    return path


def _draw_bird_logo(p: QPainter, right_x: float, bottom_y: float, s: float):
    """右下角小鸟logo(矢量, 蓝背橙腹, 参考参考图右下角小图标)。"""
    x = right_x - s            # 身体左缘
    y = bottom_y - s * 0.86    # 身体顶
    p.setRenderHint(QPainter.Antialiasing)
    # 树枝
    pen = QPen(QColor("#8A9455"), s * 0.055, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(x - s * 0.12, bottom_y - s * 0.04),
               QPointF(x + s * 1.06, bottom_y - s * 0.04))
    # 尾巴(深蓝, 向左下)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#2E5E8F"))
    tail = QPainterPath()
    tail.moveTo(x + s * 0.14, y + s * 0.34)
    tail.lineTo(x - s * 0.16, y + s * 0.62)
    tail.lineTo(x + s * 0.30, y + s * 0.52)
    tail.closeSubpath()
    p.drawPath(tail)
    # 身体(蓝)
    p.setBrush(QColor("#4A90D9"))
    body = QPainterPath()
    body.addEllipse(QRectF(x, y, s * 0.78, s * 0.66))
    p.drawPath(body)
    # 肚子(橙, 前下)
    p.setBrush(QColor("#F5A623"))
    belly = QPainterPath()
    belly.addEllipse(QRectF(x + s * 0.34, y + s * 0.30, s * 0.44, s * 0.38))
    p.drawPath(belly)
    # 头(蓝, 右上)
    p.setBrush(QColor("#4A90D9"))
    head = QPainterPath()
    head.addEllipse(QRectF(x + s * 0.42, y - s * 0.14, s * 0.44, s * 0.44))
    p.drawPath(head)
    # 嘴(橙三角)
    p.setBrush(QColor("#F5A623"))
    beak = QPainterPath()
    beak.moveTo(x + s * 0.83, y + s * 0.03)
    beak.lineTo(x + s * 0.98, y + s * 0.09)
    beak.lineTo(x + s * 0.83, y + s * 0.15)
    beak.closeSubpath()
    p.drawPath(beak)
    # 眼(白+黑)
    p.setBrush(QColor("white"))
    p.drawEllipse(QRectF(x + s * 0.62, y + s * 0.02, s * 0.13, s * 0.13))
    p.setBrush(QColor("#222"))
    p.drawEllipse(QRectF(x + s * 0.665, y + s * 0.065, s * 0.065, s * 0.065))
    # 腿
    pen = QPen(QColor("#8A9455"), s * 0.045, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(x + s * 0.42, y + s * 0.64), QPointF(x + s * 0.42, bottom_y - s * 0.04))
    p.drawLine(QPointF(x + s * 0.58, y + s * 0.64), QPointF(x + s * 0.58, bottom_y - s * 0.04))


def _logo_pixmap() -> QPixmap:
    """品牌logo(assets/brand/logo.png); 缺失返回空QPixmap。"""
    from ..paths import assets_dir
    pm = QPixmap(str(assets_dir() / "brand" / "logo.png"))
    return pm if not pm.isNull() else QPixmap()


def render_card(photo_path: str, info: dict, theme_name: str = "light") -> QPixmap:
    """info: {cn, pinyin, en, sci, lifer_no|None, photographer, date, place|None}

    date: "2024-05-12 08:31:00" 或 "2024-05-12"
    """
    tc = THEMES.get(theme_name, THEMES["light"])
    W = CARD_W

    src = QPixmap(photo_path)
    if src.isNull():
        src = QPixmap(W, int(W * 0.9))
        src.fill(QColor("#D8D8DE"))

    ratio = src.height() / max(1, src.width())
    ph = int(W * min(1.28, max(0.70, ratio)))       # 照片区高: 裁切填充
    th = 840                                        # 文字区高
    H = ph + th

    card = QPixmap(W, H)
    card.fill(Qt.transparent)
    p = QPainter(card)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.setClipPath(_card_path(W, H, RADIUS))          # 整卡圆角裁剪

    # 背景与照片(满宽 bleed)
    p.fillRect(0, 0, W, H, QColor(tc["bg"]))
    scaled = src.scaled(W, ph, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    sx = (scaled.width() - W) / 2
    sy = (scaled.height() - ph) / 2
    p.drawPixmap(int(-sx), int(-sy), scaled)

    y = ph  # 文字区起点

    # ---- 右侧 Life # N 胶囊(与中文名行居中对齐) ----
    lifer = info.get("lifer_no")
    pill_h = 96
    pill_y = y + 128
    if lifer is not None:
        pill_text = f"Life # {lifer}"
        p.setFont(_font(52, 800))
        tw = p.fontMetrics().horizontalAdvance(pill_text)
        pill_w = tw + 110
        pill_x = W - PAD - pill_w
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(tc["pill_bg"]))
        p.drawRoundedRect(QRectF(pill_x, pill_y, pill_w, pill_h),
                          pill_h / 2, pill_h / 2)
        p.setPen(QColor(tc["pill_fg"]))
        p.drawText(QRectF(pill_x, pill_y, pill_w, pill_h),
                   Qt.AlignCenter, pill_text)

    # ---- 中文名+拼音: 每字竖排单元(音节精确对准汉字) ----
    cn = info.get("cn", "")
    pys = info.get("pinyin") or []
    if isinstance(pys, str):
        pys = pys.split()
    avail = W - PAD * 2 - (pill_w + 40 if lifer is not None else 0)
    gap = 26
    py_size, cn_size = 46, 106
    for _ in range(3):   # 宽度自适应缩放(一般1轮收敛)
        p.setFont(_font(py_size, 600))
        fm_py = p.fontMetrics()
        p.setFont(_font(cn_size, 900))
        fm_cn = p.fontMetrics()
        units = []
        for ch, py in zip(cn, pys or [""] * len(cn)):
            pw = fm_py.horizontalAdvance(py) if py else 0
            cw = fm_cn.horizontalAdvance(ch)
            units.append((ch, py, max(pw, cw), pw, cw))
        total = sum(u[2] for u in units) + gap * max(0, len(units) - 1)
        if total <= avail or not units:
            break
        scale = avail / total
        py_size = max(26, int(py_size * scale))
        cn_size = max(56, int(cn_size * scale))
    x = float(PAD)
    for ch, py, uw, pw, cw in units:
        if py:
            p.setPen(QColor(tc["pinyin"]))
            p.setFont(_font(py_size, 600))
            p.drawText(QRectF(x + (uw - pw) / 2, y + 44, pw + 8, 64),
                       Qt.AlignCenter, py)
        p.setPen(QColor(tc["title"]))
        p.setFont(_font(cn_size, 900))
        p.drawText(QRectF(x + (uw - cw) / 2, y + 112, cw + 8, 176),
                   Qt.AlignCenter, ch)
        x += uw + gap

    # ---- 英文名(斜体) ----
    p.setPen(QColor(tc["en"]))
    p.setFont(_font(56, 500, italic=True))
    p.drawText(QRectF(PAD, y + 320, W - PAD * 2, 80),
               Qt.AlignLeft | Qt.AlignVCenter, info.get("en", ""))

    # ---- 分隔线 ----
    p.setPen(QColor(tc["line"]))
    p.drawLine(PAD, y + 428, W - PAD, y + 428)

    # ---- 日期 / 罕见度胶囊 / 地点 / 拍摄者 ----
    date_raw = (info.get("date") or "")[:10]
    bits = date_raw.split("-")
    date_txt = " · ".join(bits) if len(bits) == 3 else date_raw
    p.setPen(QColor(tc["title"]))
    p.setFont(_font(68, 800))
    p.drawText(QRectF(PAD, y + 462, W - PAD * 2, 100),
               Qt.AlignLeft | Qt.AlignVCenter, date_txt)

    # 罕见度胶囊(日期行右侧; 稀有/罕见醒目红橙, 不常见橙, 常见系灰)
    rarity = info.get("rarity")
    if rarity:
        if rarity in ("稀有", "罕见"):
            bg, fg = "#E5484D", "white"
        elif rarity == "不常见":
            bg, fg = "#F5A623", "white"
        else:
            bg, fg = tc["line"], tc["meta"]
        rarity_txt = t(rarity, RARITY_EN.get(rarity, rarity))
        p.setFont(_font(38, 700))
        tw = p.fontMetrics().horizontalAdvance(rarity_txt)
        pw, ph = tw + 56, 62
        px, py = W - PAD - pw, y + 481
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(bg))
        p.drawRoundedRect(QRectF(px, py, pw, ph), ph / 2, ph / 2)
        p.setPen(QColor(fg))
        p.drawText(QRectF(px, py, pw, ph), Qt.AlignCenter, rarity_txt)

    p.setPen(QColor(tc["meta"]))
    p.setFont(_font(54, 500))
    p.drawText(QRectF(PAD, y + 580, W - PAD * 2, 84),
               Qt.AlignLeft | Qt.AlignVCenter, info.get("place") or "")
    p.drawText(QRectF(PAD, y + 676, W - PAD * 2 - 190, 84),
               Qt.AlignLeft | Qt.AlignVCenter, info.get("photographer") or "")

    # ---- 右下角品牌logo(新logo图; 缺失时退回矢量小鸟) ----
    logo = _logo_pixmap()
    if not logo.isNull():
        lh = 150
        lw = int(logo.width() * lh / logo.height())
        p.drawPixmap(int(W - PAD - lw + 8), int(H - PAD + 22 - lh + 30),
                     logo.scaled(lw, lh, Qt.KeepAspectRatio,
                                 Qt.SmoothTransformation))
    else:
        _draw_bird_logo(p, W - PAD + 8, H - PAD + 22, 108)

    p.end()
    return card


def pixmap_to_png_bytes(pm: QPixmap) -> bytes:
    buf = QBuffer()
    buf.open(QBuffer.ReadWrite)
    pm.save(buf, "PNG")
    return bytes(buf.data())
