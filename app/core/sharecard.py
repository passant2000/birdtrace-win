# -*- coding: utf-8 -*-
"""分享卡渲染 v3 —— 参照观鸟社区卡片风格。

布局(宽2000, 整卡圆角, 照片满 bleed 占上部; 0.8.1 起 2000 保数毛细节):
  ┌────────────────────────────┐
  │          照片               │
  ├────────────────────────────┤
  │ huáng yāo tài yáng… │  ┌ Life # 1 ┐
  │ 黄 腰 太 阳 鸟       │                │
  │ Crimson Sunbird     │      [稀有]     │ ← 罕见度与英文名同行(Life下方)
  │ ─────────────────── │                │
  │ 2024 · 05 · 12      │      NIKON Z 8  │ ← 右列: 机身(与日期同行)
  │ 上海市               │  RF100-500mm…   │          镜头(与地点同行)
  │ zhaopaul            │  500mm · f/6.3… │          参数(与拍摄者同行)
  │        produced by BirdTrace (logo)  │ ← 底行: 品牌落款+logo
  └────────────────────────────┘
"""
from __future__ import annotations

from PySide6.QtCore import QBuffer, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QPainter,
                           QPainterPath, QPen, QPixmap)

from ..i18n import t, sname

CARD_W = 2000          # 默认输出宽(物理)
DESIGN_W = 1600         # 设计坐标基准(布局/字体按此绘制, 渲染时等比放大)
PAD = 112
RADIUS = 60

# 文字区总高(v3): 左列日期/地点/拍摄者三行 + 底部品牌行(produced by+logo)
TEXT_ZONE_H = 1000
# 右列(机身/镜头/参数)单行高与最大宽(超宽省略号截断; 上限给足——
# 左列日期/地点/拍摄者实际字宽远小于此)
EXIF_COL_W = 880

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
RARITY_EN = {"常见": "Common", "较常见": "Fairly common",  # i18n:ok
             "不常见": "Uncommon", "稀有": "Rare", "罕见": "Very rare",  # i18n:ok
             "数据不足": "Insufficient data"}  # i18n:ok


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


def _fit(fm: QFontMetrics, text: str, mode, width: int) -> str:
    """省略号守卫: advance 不超上限直接返回原文, 真超才走 elidedText。

    Windows 显示缩放 ≥125% 时 elidedText 内部按浮点宽度比较,
    取整 advance 恰好等于上限的串(如右列最宽的参数行)会被误判
    "装不下"而截断(用户实测 ISO 400 → "ISO 4…", 2026-11-02 本机
    QT_SCALE_FACTOR=1.25/1.5/1.75 100%复现)。守卫使结果与DPI无关。
    """
    return text if fm.horizontalAdvance(text) <= width \
        else fm.elidedText(text, mode, width)


def _fmt_pct(p: float) -> str:
    """百分位显示: ≥10%取整, <10%留一位小数(0.2%/3.5%), 舍入到0给<0.1。"""
    if p >= 10:
        return str(int(round(p)))
    s = f"{p:.1f}".rstrip("0").rstrip(".")
    return "<0.1" if not s or s == "0" else s


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


def render_card(photo_path: str, info: dict, theme_name: str = "light",
                width: int | None = None) -> QPixmap:
    """info: {cn, pinyin, en, sci, lifer_no|None, photographer, date, place|None,
    exif|None: {"body","lens","shot"} 拍摄参数(勾选后; 三段有什么显示什么)}

    date: "2024-05-12 08:31:00" 或 "2024-05-12"
    """
    tc = THEMES.get(theme_name, THEMES["light"])
    # width=分辨率档(2026-11-10用户: 标准2000/高清3000), 默认CARD_W。
    # **整卡按比例渲染**: 布局/字体全部用 DESIGN_W(1600) 设计坐标绘制,
    # 画笔 scale(k) 等比放大到物理宽度——否则绝对字号在高宽卡上相对
    # 变小(0.8.1首轮实测: 3000宽卡拼音看着没变大)。照片先按物理分辨率
    # 缩放(保住数毛细节), 再经画笔1:1映射, 不做二次重采样。
    k = (int(width or CARD_W)) / DESIGN_W
    W = DESIGN_W
    exif = info.get("exif") or {}
    body = str(exif.get("body") or "").strip()
    lens = str(exif.get("lens") or "").strip()
    shot = str(exif.get("shot") or "").strip()
    right_col = [s for s in (body, lens, shot) if s]

    src = QPixmap(photo_path)
    if src.isNull():
        src = QPixmap(round(W * k), round(W * 0.9 * k))
        src.fill(QColor("#D8D8DE"))

    ratio = src.height() / max(1, src.width())
    ph = int(W * min(1.28, max(0.70, ratio)))       # 照片区高(设计坐标)
    th = TEXT_ZONE_H
    H = ph + th                                     # 全设计坐标

    card = QPixmap(round(W * k), round(H * k))
    card.fill(Qt.transparent)
    p = QPainter(card)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.scale(k, k)                                   # 设计→物理 等比映射
    p.setClipPath(_card_path(W, H, RADIUS))          # 整卡圆角裁剪(设计坐标)

    # 背景与照片(满宽 bleed)。照片按**物理**分辨率缩放, 目标矩形用
    # 设计坐标(画笔放大后恰好1:1物理像素, 无二次重采样)
    p.fillRect(0, 0, W, H, QColor(tc["bg"]))
    scaled = src.scaled(round(W * k), round(ph * k),
                        Qt.KeepAspectRatioByExpanding,
                        Qt.SmoothTransformation)
    sx = (scaled.width() - round(W * k)) / 2
    sy = (scaled.height() - round(ph * k)) / 2
    p.drawPixmap(QRectF(-sx / k, -sy / k,
                        scaled.width() / k, scaled.height() / k),
                 scaled,
                 QRectF(0, 0, scaled.width(), scaled.height()))

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
    py_size, cn_size = 54, 106   # 0.8.1: 拼音加大(用户反馈字小)
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
        py_size = max(30, int(py_size * scale))
        cn_size = max(56, int(cn_size * scale))
    x = float(PAD)
    for ch, py, uw, pw, cw in units:
        if py:
            p.setPen(QColor(tc["pinyin"]))
            p.setFont(_font(py_size, 600))
            # y+58: 离照片更远(旧44太贴, 用户2026-11-10)
            p.drawText(QRectF(x + (uw - pw) / 2, y + 58, pw + 8, 66),
                       Qt.AlignCenter, py)
        p.setPen(QColor(tc["title"]))
        p.setFont(_font(cn_size, 900))
        p.drawText(QRectF(x + (uw - cw) / 2, y + 130, cw + 8, 170),
                   Qt.AlignCenter, ch)
        x += uw + gap

    # ---- 英文名(斜体) + 罕见度胶囊(同行右侧, Life#正下方) ----
    rarity = info.get("rarity")
    p.setFont(_font(56, 500, italic=True))
    if rarity:
        if rarity in ("稀有", "罕见"):  # i18n:ok
            bg, fg = "#E5484D", "white"
        elif rarity == "不常见":  # i18n:ok
            bg, fg = "#F5A623", "white"
        else:
            bg, fg = tc["line"], tc["meta"]
        rarity_txt = t(rarity, RARITY_EN.get(rarity, rarity))  # i18n:ok
        # 稀有/罕见追加百分位口径("罕见 · 前 3%")——地区相对, 卡上已带地区
        pct = info.get("rarity_pct")
        if pct is not None and rarity in ("稀有", "罕见"):  # i18n:ok
            rarity_txt += t(f" · 前 {_fmt_pct(pct)}%",
                            f" · Top {_fmt_pct(pct)}%")
        # 稀有度分值(0-10, 2026-11-10用户: 懂鸟式9.2分)——区域相对,
        # 同源百分位映射, 见 prior_hint.rarity_score
        score = info.get("rarity_score")
        if score is not None and rarity in ("稀有", "罕见"):  # i18n:ok
            rarity_txt += f" · {score:.1f}"
        p.setFont(_font(38, 700))
        tw = p.fontMetrics().horizontalAdvance(rarity_txt)
        pw, rph = tw + 56, 62
        px, rpy = W - PAD - pw, y + 329
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(bg))
        p.drawRoundedRect(QRectF(px, rpy, pw, rph), rph / 2, rph / 2)
        p.setPen(QColor(fg))
        p.drawText(QRectF(px, rpy, pw, rph), Qt.AlignCenter, rarity_txt)
    # ---- IUCN 受威胁胶囊(罕见度左侧; 2026-11-10用户: 濒危/易危) ----
    # 只标受威胁等级(NT/VU/EN/CR/EW/EX), 无危不显示
    iucn = info.get("iucn")
    iw = 0
    if iucn:
        IUCN_ZH = {"NT": "近危", "VU": "易危", "EN": "濒危",  # i18n:ok
                   "CR": "极危", "EW": "野外灭绝", "EX": "灭绝"}  # i18n:ok
        IUCN_EN = {"NT": "Near Threatened", "VU": "Vulnerable",
                   "EN": "Endangered", "CR": "Critically Endangered",
                   "EW": "Extinct in the Wild", "EX": "Extinct"}
        IUCN_BG = {"NT": "#C7A519", "VU": "#E07B1F", "EN": "#DE3730",
                   "CR": "#8B1A12", "EW": "#3A3A3C", "EX": "#1C1C1E"}
        iucn_txt = t(f"{IUCN_ZH[iucn]} {iucn}",
                     f"{iucn} · {IUCN_EN[iucn]}")  # i18n:ok
        p.setFont(_font(38, 700))
        itw = p.fontMetrics().horizontalAdvance(iucn_txt)
        iw, rph2 = itw + 56, 62
        ix = (W - PAD - pw - 24 - iw) if rarity else (W - PAD - iw)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(IUCN_BG.get(iucn, "#1C1C1E")))
        p.drawRoundedRect(QRectF(ix, y + 329, iw, rph2),
                          rph2 / 2, rph2 / 2)
        p.setPen(QColor("white"))
        p.drawText(QRectF(ix, y + 329, iw, rph2), Qt.AlignCenter, iucn_txt)
    p.setPen(QColor(tc["en"]))
    p.setFont(_font(56, 500, italic=True))
    en_w = (W - PAD * 2) - ((pw + 36) if rarity else 0)            - (iw + 24 if iucn else 0)
    p.drawText(QRectF(PAD, y + 320, en_w, 80),
               Qt.AlignLeft | Qt.AlignVCenter, info.get("en", ""))

    # ---- 分隔线 ----
    p.setPen(QColor(tc["line"]))
    p.drawLine(PAD, y + 428, W - PAD, y + 428)

    # ---- 日期 / 地点 / 拍摄者 (左列) + 机身/镜头/参数 (右列同行对齐) ----
    date_raw = (info.get("date") or "")[:10]
    bits = date_raw.split("-")
    date_txt = " · ".join(bits) if len(bits) == 3 else date_raw
    p.setFont(_font(40, 500))
    fm_ex = p.fontMetrics()
    col_w = 0
    for s in right_col:
        col_w = max(col_w, fm_ex.horizontalAdvance(s))
    col_w = min(col_w, EXIF_COL_W)
    left_w = (W - PAD * 2 - col_w - 48) if right_col else (W - PAD * 2)

    p.setPen(QColor(tc["title"]))
    p.setFont(_font(68, 800))
    fm68 = p.fontMetrics()
    date_disp = _fit(fm68, date_txt, Qt.ElideRight, left_w) \
        if right_col else date_txt
    p.drawText(QRectF(PAD, y + 462, left_w, 100),
               Qt.AlignLeft | Qt.AlignVCenter, date_disp)
    if body:
        p.setPen(QColor(tc["meta"]))
        p.setFont(_font(40, 500))
        p.drawText(QRectF(W - PAD - col_w, y + 482, col_w, 62),
                   Qt.AlignRight | Qt.AlignVCenter,
                   _fit(fm_ex, body, Qt.ElideMiddle, col_w))

    p.setPen(QColor(tc["meta"]))
    p.setFont(_font(54, 500))
    fm54 = p.fontMetrics()
    place_disp = _fit(fm54, info.get("place") or "", Qt.ElideRight,
                      left_w) \
        if right_col else (info.get("place") or "")
    p.drawText(QRectF(PAD, y + 580, left_w, 84),
               Qt.AlignLeft | Qt.AlignVCenter, place_disp)
    if lens:
        p.setFont(_font(40, 500))
        p.drawText(QRectF(W - PAD - col_w, y + 594, col_w, 60),
                   Qt.AlignRight | Qt.AlignVCenter,
                   _fit(fm_ex, lens, Qt.ElideMiddle, col_w))

    p.setFont(_font(54, 500))
    photog_disp = _fit(fm54, info.get("photographer") or "",
                       Qt.ElideRight, left_w) \
        if right_col else (info.get("photographer") or "")
    p.drawText(QRectF(PAD, y + 676, left_w, 84),
               Qt.AlignLeft | Qt.AlignVCenter, photog_disp)
    if shot:
        p.setPen(QColor(tc["meta"]))
        # 参数行兜底: 真超宽先缩字号(40→28), 配合_fit守卫(见_fit docstring,
        # DPI≥125%时elidedText等宽边界陷阱——2026-11-02实测缩字号挡不住
        # 边界情形, 必须由守卫直接画原文)。2026-11-01缩字号, 2026-11-02守卫。
        size = 40
        p.setFont(_font(size, 500))
        while p.fontMetrics().horizontalAdvance(shot) > col_w and size > 28:
            size -= 2
            p.setFont(_font(size, 500))
        p.drawText(QRectF(W - PAD - col_w, y + 690, col_w, 60),
                   Qt.AlignRight | Qt.AlignVCenter,
                   _fit(p.fontMetrics(), shot, Qt.ElideRight, col_w))

    # ---- 品牌落款行: produced by BirdTrace(与左列对齐) + 右下角logo ----
    logo = _logo_pixmap()
    LOGO_H = 150
    lw = int(logo.width() * LOGO_H / logo.height()) if not logo.isNull() else 108
    logo_top = y + 790
    p.setPen(QColor(tc["meta"]))
    p.setFont(_font(34, 500, italic=True))
    p.drawText(QRectF(PAD, logo_top + (LOGO_H - 48) // 2,
                      W - PAD * 2 - lw, 48),
               Qt.AlignLeft | Qt.AlignVCenter, "produced by BirdTrace")
    if not logo.isNull():
        p.drawPixmap(int(W - PAD - lw + 8), int(logo_top),
                     logo.scaled(lw, LOGO_H, Qt.KeepAspectRatio,
                                 Qt.SmoothTransformation))
    else:
        _draw_bird_logo(p, W - PAD + 8, logo_top + LOGO_H - 10, 108)

    p.end()
    return card


def pixmap_to_png_bytes(pm: QPixmap) -> bytes:
    buf = QBuffer()
    buf.open(QBuffer.ReadWrite)
    pm.save(buf, "PNG")
    return bytes(buf.data())
