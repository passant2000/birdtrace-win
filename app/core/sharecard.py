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

# 固定版式: (设计总高, 照片区高)。竖版3:5文字区790(2026-11-17改:
# 小红书竖版全屏图文=3:5即9:15, 用户实测+leoon-crop"小红书全屏(3:5)"
# 预设佐证, 旧9:16偏长会被多裁; 照片区短177px, 文字区布局零改动):
# **标题区(拼音/中文名/英文名/胶囊/分隔线, 0~428)不压缩**——0.8.3实测
# drawText会把字形裁到矩形里, 等比压行距=截掉g/q下降部(用户复现);
# 只压meta行(日期/地点/拍摄者/品牌行, 见render里META_TALL手工表)。
# 3:4文字区保持1000(照片区0.71×宽已近最优, 压了反而更裁)
XHS_LAYOUTS = {
    "3:5": (2667, 1877),
    "3:4": (2133, 1133),
}
BLEED_LOSS = 0.30       # 裁切损失超过30%改用模糊bleed垫底(全景图鸟绝不裁)
# 0.8.6 文字区手动高度: 缩放系数夹在此区间(字号随行高同步缩, 再小不可读)
TEXT_SCALE_MIN = 0.75
TEXT_SCALE_MAX = 1.35
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


ADJUST_ZOOM_MAX = 3.0      # 手动缩放上限(再大就是放大像素, 会糊)


def resolve_layout(src_w: int, src_h: int, layout: str) -> str | None:
    """版式key解析(0.8.5单源): "auto"按方向(两版式裁切量取小者,
    交点h/w=√(两窗口比乘积), 3:5档≈0.91); "classic"→None(自适应);
    其余原样返回。render_card与ShareDialog交互共用。"""
    if layout == "classic":
        return None
    if layout != "auto":
        return layout
    ratio = src_h / max(1, src_w)

    def _loss(pr, wr):
        return 1 - min(pr, wr) / max(pr, wr)

    l9 = _loss(ratio, XHS_LAYOUTS["3:5"][1] / DESIGN_W)
    l3 = _loss(ratio, XHS_LAYOUTS["3:4"][1] / DESIGN_W)
    return "3:5" if l9 <= l3 else "3:4"


def photo_placement(src_w: int, src_h: int, zw: int, zh: int,
                    focus=None, adjust: dict | None = None) -> dict:
    """固定版式照片定位纯数学(0.8.5手动裁切; 渲染与对话框交互共用单源)。

    返回 {w, h, sx, sy, rx, ry, zoom}:
      w,h   = 缩放后照片尺寸(物理px)
      sx,sy = 裁切偏移(绘制画在-sx/-sy处): cover≥0=窗口内裁切起点;
              letterbox<0=居中留边(窗口内正向偏移)——0.8.6实测修复:
              旧实现返回+(zw-w)/2正值, 绘制在-sx把清晰区整体推出左/上边
              (用户9:16竖图卡: 清晰区贴左缘+右侧全糊底, 拉不到中间)
      rx,ry = 可平移范围(缩放后-窗口; 0=该轴填满不可平移)
    照片任一轴小于窗口 → 调用方需先画模糊bleed垫底再叠照片。

    adjust=None → 自动: 全景级损失(>BLEED_LOSS)按fit整图居中;
      否则cover+焦点对准(眼点→框心, 双向夹紧[0,超出量], 无框居中)。
    adjust={zoom, ox, oy} → 手动: 缩放=基准×zoom(全景基准fit/普通基准
      cover, zoom夹[1, ADJUST_ZOOM_MAX]); ox/oy=平移量占可平移范围
      百分比(与分辨率/版式无关, 换版式构图语义保持); 不足窗口的轴居中。
    """
    ratio = src_h / max(1, src_w)
    wr = zh / max(1, zw)
    loss = (1 - wr / ratio) if ratio >= wr else (1 - ratio / wr)
    bleed_mode = loss > BLEED_LOSS
    fw, fh = zw / max(1, src_w), zh / max(1, src_h)
    base = min(fw, fh) if bleed_mode else max(fw, fh)
    zoom = 1.0
    if adjust:
        try:
            zoom = min(ADJUST_ZOOM_MAX,
                       max(1.0, float(adjust.get("zoom", 1.0) or 1.0)))
        except (TypeError, ValueError):
            zoom = 1.0
    f = base * zoom
    w = max(1, round(src_w * f))
    h = max(1, round(src_h * f))
    rx, ry = max(0, w - zw), max(0, h - zh)
    if adjust:
        def _frac(v):
            try:
                return min(1.0, max(0.0, float(v)))
            except (TypeError, ValueError):
                return 0.5
        sx = rx * _frac(adjust.get("ox", 0.5)) if w > zw else -(zw - w) / 2
        sy = ry * _frac(adjust.get("oy", 0.5)) if h > zh else -(zh - h) / 2
    elif bleed_mode:
        sx, sy = -(zw - w) / 2, -(zh - h) / 2
    else:
        sx, sy = rx / 2, ry / 2
        if focus and focus[0] is not None:
            fxn, fyn = focus
            sx = min(max(fxn * w - zw / 2, 0), rx)
            sy = min(max(fyn * h - zh / 2, 0), ry)
    return {"w": w, "h": h, "sx": sx, "sy": sy, "rx": rx, "ry": ry,
            "zoom": zoom}


def nocrop_line(src_w: int, src_h: int, key: str) -> tuple[float | None, str]:
    """无裁切参考线(设计y)与类型(0.8.6修: 按原图比例, 单一ph_nc判断不准)。

    ph_nc=DESIGN_W×原图高/宽(整图满幅精确位)。零裁切区间有**两条**边界
    (bleed=整图fit可见 / cover=裁切, BLEED_LOSS=0.3造成):
      [0, 0.7·ph_nc) 整图但缩小(竖图糊左右) ∪ {ph_nc} 满幅 ∪
      (ph_nc/0.7, ∞) 整图满宽(横图糊上下)
    返回(ph, kind), ph=None仅all:
      exact    ph_nc 可拖达 → 线画在ph_nc(磁吸目标)
      lo       竖图(ph_nc超上限): 0.7·ph_nc 线上=放大裁/线下=整图缩小
      hi       横图(ph_nc低于下限): ph_nc/0.7 线上=整图满宽/线下=侧裁
      off_tall/off_wide  可拖范围全在cover带 → 最近端(线仍画出+注明)
      all      全程无裁切(竖超high/横全bleed)
    """
    h0, ph0 = XHS_LAYOUTS[key]
    base = h0 - ph0
    pmin = h0 - round(base * TEXT_SCALE_MAX)   # 可拖照片区下界(文字最大)
    pmax = h0 - round(base * TEXT_SCALE_MIN)   # 可拖照片区上界(文字最小)
    ph_nc = DESIGN_W * src_h / max(1, src_w)
    lo, hi = (1 - BLEED_LOSS) * ph_nc, ph_nc / (1 - BLEED_LOSS)
    if pmin <= ph_nc <= pmax:
        return ph_nc, "exact"
    if pmax < lo or pmin > hi:
        return None, "all"
    if pmin <= hi <= pmax:
        return hi, "hi"
    if pmin <= lo <= pmax:
        return lo, "lo"
    return (pmax, "off_tall") if ph_nc > pmax else (pmin, "off_wide")


def auto_text_scale(src_w: int, src_h: int, key: str | None) -> float:
    """自动(未手动拖过)默认文字区缩放(0.8.6用户: 分界线直接放无裁切线)。

    exact→精确整图位; lo(竖图)→线上整图最大; hi(横图)→线上整图(默认
    已在无裁切区则1.0不动——横图整图大小恒为满宽×ph_nc, 挪线只改
    糊边/文字占比); off→最近端; all→1.0。classic(None)→1.0历史行为。
    单卡ShareDialog与批量导出共用; 夹[MIN,MAX]返回。
    """
    if not key:
        return 1.0
    h0, ph0 = XHS_LAYOUTS[key]
    base = h0 - ph0
    ph, kind = nocrop_line(src_w, src_h, key)
    if kind == "exact":
        ts = (h0 - ph) / base
    elif kind == "lo":
        ts = (h0 - (ph - 2)) / base    # 留2设计px稳在bleed侧(线是严格>)
    elif kind == "hi":
        if ph0 > ph:                   # 默认已在无裁切区
            return 1.0
        ts = (h0 - (ph + 2)) / base
    elif kind in ("off_tall", "off_wide"):
        ts = (h0 - ph) / base
    else:
        return 1.0
    return min(TEXT_SCALE_MAX, max(TEXT_SCALE_MIN, ts))


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
                width: int | None = None, layout: str = "classic",
                adjust: dict | None = None, text_scale: float = 1.0,
                guide_y: int | None = None,
                guide_note: str | None = None,
                rounded: bool = True) -> QPixmap:
    """info: {cn, pinyin, en, sci, lifer_no|None, photographer, date, place|None,
    exif|None: {"body","lens","shot"} 拍摄参数(勾选后; 三段有什么显示什么),
    focus|None: (fx,fy) 归一化鸟心(检测框中心, 固定版式下裁剪窗口对准它)}

    layout: "classic"=原自适应(照片比例钳0.70~1.28, 居中裁剪, 历史行为);
    "auto"=按方向(横图→3:4 / 竖图方图→3:5); "3:5"/"3:4"=强制档。
    固定版式下裁剪对准focus; 裁切损失>30%改用模糊bleed垫底(整图可见)。
    adjust(0.8.5手动裁切, 仅固定版式生效): {zoom 1~3, ox/oy 0~1}=
    用户手动缩放平移(photo_placement), None=自动定位。
    text_scale(0.8.6手动文字区): 文字区高度缩放系数, 夹[TEXT_SCALE_MIN,
    MAX]; 字号/行高/胶囊同乘kt(同步缩放=字形矩形关系不变, 免截字形坑)。
    固定版式卡高锁死→照片区反向伸缩; classic卡高随th浮动。
    guide_y/guide_note(0.8.6拖动参考线, 设计坐标y): 仅预览渲染传,
    出片不传=参考线永不入成品——交界拖动时标"无裁切位置"用。
    rounded(0.8.6用户: 圆角做成可选项): False=直角出片。
    非中文标题(英文界面): 整串紧凑绘制(旧=逐字符稀排, 英文名占满行);
    副名行英文界面显示中文名(大标题已是英文, 旧版两行重复, 0.8.6用户
    定: 中国软件副名给中文)。info需补 cn_raw(原始中文名)。

    date: "2024-05-12 08:31:00" 或 "2024-05-12"
    """
    try:
        ts = min(TEXT_SCALE_MAX, max(TEXT_SCALE_MIN, float(text_scale)))
    except (TypeError, ValueError):
        ts = 1.0
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
    key = "classic"
    if layout == "classic":
        ph = int(W * min(1.28, max(0.70, ratio)))   # 照片区高(设计坐标)
        th = round(TEXT_ZONE_H * ts)                # 0.8.6可调, H随th浮动
        H = ph + th                                 # 全设计坐标
    else:
        if layout == "auto":
            # 两版式裁切量取小者(0.8.4): 旧固定阈值0.9是拍的, 交点解析
            # 单源resolve_layout(0.8.5)——临界比例归3:4更省
            key = resolve_layout(src.width(), src.height(), "auto")
        else:
            key = layout                            # "3:5" / "3:4"
        H, ph = XHS_LAYOUTS[key]
        th = round((H - ph) * ts)
        ph = H - th     # 0.8.6: 卡高锁版式——文字区伸缩=照片区反向
    compact = (key == "3:5")

    card = QPixmap(round(W * k), round(H * k))
    card.fill(Qt.transparent)
    p = QPainter(card)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.scale(k, k)                                   # 设计→物理 等比映射
    # 整卡圆角裁剪(设计坐标; 0.8.6起可关=直角)
    p.setClipPath(_card_path(W, H, RADIUS if rounded else 0))

    # 背景与照片(满宽 bleed)。照片按**物理**分辨率缩放, 目标矩形用
    # 设计坐标(画笔放大后恰好1:1物理像素, 无二次重采样)
    p.fillRect(0, 0, W, H, QColor(tc["bg"]))
    zw, zh = round(W * k), round(ph * k)
    # 照片只许出现在照片区: classic居中裁剪底边恰好落在ph(构造安全),
    # 但框对准会把窗口上移(鸟偏画面上方时), 底边越过ph压到文字区——
    # 0.8.3用户实测(北红尾鸲卡: 拼音/鸟名画在照片上), 统一裁剪兜底
    p.save()
    # IntersectClip: 与整卡圆角路径相交——默认Replace会顶掉圆角裁剪,
    # 照片把上面两角画成方角(0.8.3用户实测)
    p.setClipRect(QRectF(0, 0, W, ph), Qt.IntersectClip)
    if layout == "classic":
        # 原行为: 居中裁剪(不动历史卡)
        scaled = src.scaled(zw, zh, Qt.KeepAspectRatioByExpanding,
                            Qt.SmoothTransformation)
        sx = (scaled.width() - zw) / 2
        sy = (scaled.height() - zh) / 2
        p.drawPixmap(QRectF(-sx / k, -sy / k,
                            scaled.width() / k, scaled.height() / k),
                     scaled,
                     QRectF(0, 0, scaled.width(), scaled.height()))
    else:
        # 固定版式: 定位数学单源photo_placement(自动=框对准/全景bleed;
        # adjust=用户手动缩放平移, 0.8.5)
        pl = photo_placement(src.width(), src.height(), zw, zh,
                             info.get("focus"), adjust)
        scaled = src.scaled(pl["w"], pl["h"], Qt.IgnoreAspectRatio,
                            Qt.SmoothTransformation)
        if pl["w"] < zw or pl["h"] < zh:
            # 垫底(全景bleed/手动未放大到铺满): 缩到指甲盖再放大=廉价
            # 高斯糊, 上面叠照片(letterbox或部分留白)
            small = src.scaled(max(2, zw // 32), max(2, zh // 32),
                               Qt.KeepAspectRatioByExpanding,
                               Qt.FastTransformation)
            blur = small.scaled(zw, zh, Qt.KeepAspectRatioByExpanding,
                                Qt.SmoothTransformation)
            p.drawPixmap(QRectF(0, 0, zw / k, zh / k), blur,
                         QRectF(0, 0, blur.width(), blur.height()))
        p.drawPixmap(QRectF(-pl["sx"] / k, -pl["sy"] / k,
                            pl["w"] / k, pl["h"] / k),
                     scaled,
                     QRectF(0, 0, pl["w"], pl["h"]))
    p.restore()                                     # 解除照片区裁剪

    y = ph  # 文字区起点
    # 0.8.4: 行距矩形不再等比压缩——实测drawText会把字形裁到矩形里
    # (56px斜体在59px矩形里g/q下降部少17px), 压行距=截中英文名下半。
    # 3:5竖版只压meta行(日期/地点/拍摄者/品牌行), 偏移手工表; 其余原高。
    META_TALL = {462: 452, 100: 82, 482: 472, 62: 58,
                 580: 540, 84: 64, 594: 554, 60: 56,
                 676: 606, 690: 620,
                 790: 676}
    def o(base: int) -> int:
        return META_TALL.get(base, base) if compact else base

    # 0.8.6 文字区等比缩放: 字号/行高/胶囊同乘kt(同步缩放=字形与矩形关系
    # 不变, 天然免疫0.8.3截字形坑); x方向与卡宽不缩。base_th=该版式默认文字区高
    base_th = TEXT_ZONE_H if key == "classic" \
        else (XHS_LAYOUTS[key][0] - XHS_LAYOUTS[key][1])
    kt = th / base_th

    def s(v: float) -> float:
        return v * kt

    # ---- 右侧 Life # N 胶囊(与中文名行居中对齐) ----
    lifer = info.get("lifer_no")
    pill_h = s(o(96))
    pill_y = y + s(o(128))
    if lifer is not None:
        pill_text = f"Life # {lifer}"
        p.setFont(_font(int(s(52)), 800))
        tw = p.fontMetrics().horizontalAdvance(pill_text)
        pill_w = tw + int(s(110))
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
    py_size, cn_size = int(s(54)), int(s(106))   # 0.8.1: 拼音加大; 0.8.6随文字区
    if not pys:
        # 非中文标题(英文界面): 整串紧凑绘制——旧实现逐字符当独立单元排
        # (字母间也吃gap=26+单元内居中), 英文鸟名稀疏占满一整行(0.8.6用户)
        p.setFont(_font(cn_size, 900))
        adv = p.fontMetrics().horizontalAdvance(cn)
        if adv > avail:
            cn_size = max(int(s(56)), int(cn_size * avail / adv))
            p.setFont(_font(cn_size, 900))
        p.setPen(QColor(tc["title"]))
        p.drawText(QRectF(PAD, y + s(o(130)), avail, s(o(170))),
                   Qt.AlignLeft | Qt.AlignVCenter, cn)
    else:
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
            py_size = max(int(s(30)), int(py_size * scale))
            cn_size = max(int(s(56)), int(cn_size * scale))
        x = float(PAD)
        for ch, py, uw, pw, cw in units:
            if py:
                p.setPen(QColor(tc["pinyin"]))
                p.setFont(_font(py_size, 600))
                # y+58: 离照片更远(旧44太贴, 用户2026-11-10)
                p.drawText(QRectF(x + (uw - pw) / 2, y + s(o(58)), pw + 8,
                                  s(o(66))),
                           Qt.AlignCenter, py)
            p.setPen(QColor(tc["title"]))
            p.setFont(_font(cn_size, 900))
            p.drawText(QRectF(x + (uw - cw) / 2, y + s(o(130)), cw + 8,
                              s(o(170))),
                       Qt.AlignCenter, ch)
            x += uw + gap

    # ---- 英文名(斜体) + 罕见度胶囊(同行右侧, Life#正下方) ----
    rarity = info.get("rarity")
    p.setFont(_font(int(s(56)), 500, italic=True))
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
        # 稀有度分值(0-10, 2026-11-10用户: 懂鸟式9.2)——区域相对,
        # 同源百分位映射, 见 prior_hint.rarity_score
        score = info.get("rarity_score")
        if score is not None and rarity in ("稀有", "罕见"):  # i18n:ok
            rarity_txt += f" · {score:.1f}"
        p.setFont(_font(int(s(38)), 700))
        tw = p.fontMetrics().horizontalAdvance(rarity_txt)
        pw, rph = tw + int(s(56)), s(62)
        px, rpy = W - PAD - pw, y + s(o(329))
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
        p.setFont(_font(int(s(38)), 700))
        itw = p.fontMetrics().horizontalAdvance(iucn_txt)
        iw, rph2 = itw + int(s(56)), s(62)
        ix = (W - PAD - pw - 24 - iw) if rarity else (W - PAD - iw)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(IUCN_BG.get(iucn, "#1C1C1E")))
        p.drawRoundedRect(QRectF(ix, y + s(o(329)), iw, rph2),
                          rph2 / 2, rph2 / 2)
        p.setPen(QColor("white"))
        p.drawText(QRectF(ix, y + s(o(329)), iw, rph2), Qt.AlignCenter,
                   iucn_txt)
    p.setPen(QColor(tc["en"]))
    # 副名行=「另一语言」名(0.8.6用户): 中文界面=英文名(旧有); 英文界面
    # 大标题已是英文, 旧版副名重复画英文——改画中文名(无中文名退学名)。
    sub_name = info.get("en") or ""
    if info.get("cn_raw") and info.get("cn") == info.get("en"):
        sub_name = info["cn_raw"] or info.get("sci") or ""
    has_cjk = any("\u4e00" <= c <= "\u9fff" for c in sub_name)  # i18n:ok
    p.setFont(_font(int(s(56)), 500, italic=not has_cjk))
    en_w = (W - PAD * 2) - ((pw + 36) if rarity else 0)            - (iw + 24 if iucn else 0)
    p.drawText(QRectF(PAD, y + s(o(320)), en_w, s(o(80))),
               Qt.AlignLeft | Qt.AlignVCenter, sub_name)

    # ---- 分隔线 ----
    p.setPen(QColor(tc["line"]))
    p.drawLine(PAD, y + s(o(428)), W - PAD, y + s(o(428)))

    # ---- 日期 / 地点 / 拍摄者 (左列) + 机身/镜头/参数 (右列同行对齐) ----
    date_raw = (info.get("date") or "")[:10]
    bits = date_raw.split("-")
    date_txt = " · ".join(bits) if len(bits) == 3 else date_raw
    p.setFont(_font(int(s(40)), 500))
    fm_ex = p.fontMetrics()
    col_w = 0
    for seg in right_col:            # 0.8.6: 循环变量改seg(撞s()缩放助手)
        col_w = max(col_w, fm_ex.horizontalAdvance(seg))
    col_w = min(col_w, EXIF_COL_W)
    left_w = (W - PAD * 2 - col_w - 48) if right_col else (W - PAD * 2)

    p.setPen(QColor(tc["title"]))
    p.setFont(_font(int(s(68)), 800))
    fm68 = p.fontMetrics()
    date_disp = _fit(fm68, date_txt, Qt.ElideRight, left_w) \
        if right_col else date_txt
    p.drawText(QRectF(PAD, y + s(o(462)), left_w, s(o(100))),
               Qt.AlignLeft | Qt.AlignVCenter, date_disp)
    if body:
        p.setPen(QColor(tc["meta"]))
        p.setFont(_font(int(s(40)), 500))
        p.drawText(QRectF(W - PAD - col_w, y + s(o(482)), col_w, s(o(62))),
                   Qt.AlignRight | Qt.AlignVCenter,
                   _fit(fm_ex, body, Qt.ElideMiddle, col_w))

    p.setPen(QColor(tc["meta"]))
    p.setFont(_font(int(s(44)), 500))
    fm_meta = p.fontMetrics()
    place_disp = _fit(fm_meta, info.get("place") or "", Qt.ElideRight,
                      left_w) \
        if right_col else (info.get("place") or "")
    p.drawText(QRectF(PAD, y + s(o(580)), left_w, s(o(84))),
               Qt.AlignLeft | Qt.AlignVCenter, place_disp)
    if lens:
        p.setFont(_font(int(s(40)), 500))
        p.drawText(QRectF(W - PAD - col_w, y + s(o(594)), col_w, s(o(60))),
                   Qt.AlignRight | Qt.AlignVCenter,
                   _fit(fm_ex, lens, Qt.ElideMiddle, col_w))

    p.setFont(_font(int(s(44)), 500))
    photog_disp = _fit(fm_meta, info.get("photographer") or "",
                       Qt.ElideRight, left_w) \
        if right_col else (info.get("photographer") or "")
    p.drawText(QRectF(PAD, y + s(o(676)), left_w, s(o(84))),
               Qt.AlignLeft | Qt.AlignVCenter, photog_disp)
    if shot:
        p.setPen(QColor(tc["meta"]))
        # 参数行兜底: 真超宽先缩字号(40→28), 配合_fit守卫(见_fit docstring,
        # DPI≥125%时elidedText等宽边界陷阱——2026-11-02实测缩字号挡不住
        # 边界情形, 必须由守卫直接画原文)。2026-11-01缩字号, 2026-11-02守卫。
        size = int(s(40))
        p.setFont(_font(size, 500))
        while p.fontMetrics().horizontalAdvance(shot) > col_w \
                and size > int(s(28)):
            size -= 2
            p.setFont(_font(size, 500))
        p.drawText(QRectF(W - PAD - col_w, y + s(o(690)), col_w, s(o(60))),
                   Qt.AlignRight | Qt.AlignVCenter,
                   _fit(p.fontMetrics(), shot, Qt.ElideRight, col_w))

    # ---- 品牌落款行: produced by BirdTrace(与左列对齐) + 右下角logo ----
    logo = _logo_pixmap()
    LOGO_H = int(s(80)) if compact else int(s(110))
    lw = int(logo.width() * LOGO_H / logo.height()) if not logo.isNull() else int(s(108))
    logo_top = y + s(o(790))
    p.setPen(QColor(tc["meta"]))
    p.setFont(_font(int(s(34)), 500, italic=True))
    p.drawText(QRectF(PAD, logo_top + (LOGO_H - int(s(48))) // 2,
                      W - PAD * 2 - lw, int(s(48))),
               Qt.AlignLeft | Qt.AlignVCenter, "produced by BirdTrace")
    if not logo.isNull():
        p.drawPixmap(int(W - PAD - lw + 8), int(logo_top),
                     logo.scaled(lw, LOGO_H, Qt.KeepAspectRatio,
                                 Qt.SmoothTransformation))
    else:
        _draw_bird_logo(p, W - PAD + 8, logo_top + LOGO_H - 10, int(s(108)))

    # ---- 0.8.6 拖动参考线(仅预览渲染传入; 出片不传=永不入成品) ----
    if guide_y is not None and 0 < guide_y < H:
        p.setPen(QPen(QColor("#FF7A00"), 5, Qt.DashLine))
        p.drawLine(0, guide_y, W, guide_y)
        note = guide_note or t("无裁切位置", "No-crop position")
        p.setFont(_font(34, 700))
        tw = p.fontMetrics().horizontalAdvance(note) + 24
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#FF7A00"))
        p.drawRoundedRect(QRectF(PAD, guide_y - 46, tw, 40), 20, 20)
        p.setPen(QColor("white"))
        p.drawText(QRectF(PAD, guide_y - 46, tw, 40), Qt.AlignCenter, note)

    p.end()
    return card


def pixmap_to_png_bytes(pm: QPixmap) -> bytes:
    buf = QBuffer()
    buf.open(QBuffer.ReadWrite)
    pm.save(buf, "PNG")
    return bytes(buf.data())
