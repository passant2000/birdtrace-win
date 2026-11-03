# -*- coding: utf-8 -*-
"""生成鸟迹v0.6.0官方介绍长图(手机友好, 1080宽), 供网站专版介绍转发。

产物: data/ui_shots/intro_v0.6.0.png
风格与分享卡/年报同源(米色系), 截图圆角卡片化。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication

PROJ = Path(__file__).resolve().parent.parent
SH = PROJ / "data/ui_shots"

W = 1080
BG = "#F0EFE4"
TITLE = "#2E2E28"
ACCENT = "#8A9455"
META = "#6E6E5E"
CARD = "#FFFFFF"


def f(size: int, weight: int = 400, bold=False) -> QFont:
    ft = QFont()
    ft.setFamilies(["MiSans", "HarmonyOS Sans SC", "PingFang SC",
                    "Microsoft YaHei UI", "Segoe UI"])
    ft.setPixelSize(size)
    try:
        ft.setWeight(QFont.Weight(weight))
    except ValueError:
        ft.setWeight(QFont.Weight.Bold)
    if bold:
        ft.setBold(True)
    return ft


def rounded(p: QPainter, x: float, y: float, w: float, h: float, r: float):
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, w, h), r, r)
    return path


def draw_shot(p: QPainter, name: str, x: float, y: float, w: float,
              h: float, caption: str, cap_h: float = 54) -> float:
    """截图按宽高比裁中间, 圆角卡片+下方说明; 返回下一行的y。"""
    pm = QPixmap(str(SH / name))
    src_ratio = pm.width() / pm.height()
    dst_ratio = w / h
    if src_ratio > dst_ratio:      # 截图更宽: 裁左右
        cw = int(pm.height() * dst_ratio)
        pm = pm.copy((pm.width() - cw) // 2, 0, cw, pm.height())
    else:                          # 更高: 裁上下
        ch = int(pm.width() / dst_ratio)
        pm = pm.copy(0, (pm.height() - ch) // 2, pm.width(), ch)
    clip = rounded(p, x + 3, y + 4, w, h, 18)
    p.fillPath(clip, QColor("#D8D6C4"))          # 底部"投影"
    clip = rounded(p, x, y, w, h, 18)
    p.save()
    p.setClipPath(clip)
    p.drawPixmap(int(x), int(y), int(w), int(h), pm)
    p.restore()
    p.setPen(QColor("#E2E0D0"))
    p.drawPath(clip)
    p.setPen(QColor(TITLE))
    p.setFont(f(26, 600))
    p.drawText(QRectF(x, y + h + 10, w, cap_h), Qt.AlignCenter, caption)
    return y + h + cap_h + 26


def main():
    app = QApplication([])
    margin = 60
    inner = W - margin * 2

    # 高度先算: 头部420 + 亮点4条 + 大图1 + 双图2组 + 功能 + 门槛 + 页脚
    big_h = inner * 820 / 1280            # 1280x820 等比
    half_w = (inner - 30) / 2
    half_h = half_w * 820 / 1280
    report_h = inner * 0.62               # 年报长图缩放高度
    sc_h = inner * 0.30 * 800 / 560       # 分享卡竖图高度
    H = 470 + 4 * 124 + 70 + (big_h + 84) + 3 * (half_h + 86) + (report_h + 90) + 460 + 240 + 150 + 700
    pm = QPixmap(W, int(H))
    pm.fill(QColor(BG))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)

    # ---- 头部 ----
    logo = QPixmap(str(PROJ / "assets/brand/logo.png")).scaledToWidth(150)
    p.drawPixmap(margin, 64, logo)
    p.setPen(QColor(TITLE))
    p.setFont(f(64, 800))
    p.drawText(QRectF(margin + 170, 56, inner - 170, 90), Qt.AlignLeft,
               "鸟迹 BirdTrace")
    p.setFont(f(30, 500))
    p.setPen(QColor(ACCENT))
    p.drawText(QRectF(margin + 172, 148, inner - 170, 50), Qt.AlignLeft,
               "Windows 版 · v0.6.0 · 免费便携")
    p.setPen(QColor(META))
    p.setFont(f(30, 500))
    p.drawText(QRectF(margin, 250, inner, 200), Qt.AlignLeft | Qt.TextWordWrap,
               "观鸟摄影人的本地照片管家——AI认鸟、时间线回顾、鸟点地图、"
               "迁徙地图、成就徽章。你的照片永远留在自己电脑上，一张都不外传。")

    y = 470
    # ---- 核心亮点 ----
    p.setPen(QColor(TITLE))
    p.setFont(f(40, 800))
    p.drawText(QRectF(margin, y, inner, 60), Qt.AlignLeft, "为什么是鸟迹")
    y += 80
    feats = [
        ("🤖", "AI识别引擎大修 · 11171 种鸟",
         "分割检测+两档取景+地理先验，栖枝不再带偏、澳洲鸟不再乱入；"
         "支持GPU加速与RAW原片，照片不出电脑"),
        ("🗂️", "Lightroom 式照片管理",
         "引用/复制/移动三种导入，绝不移动你的原片文件夹；"
         "TOPIQ美学评分帮你挑出每种鸟最美的照片"),
        ("🗺️", "鸟点地图 + 迁徙地图",
         "鸟点高德底图免Key即用；图鉴里看任意鸟种52周全球迁徙动画"),
        ("🏅", "观鸟成就体系",
         "生涯lifer编号、年鸟、24枚徽章、eBird导出、年度报告、"
         "分享卡；全软件中英双语"),
    ]
    for icon, t1, t2 in feats:
        p.setFont(f(44, 500))
        p.setPen(QColor(ACCENT))
        p.drawText(QRectF(margin, y - 8, 70, 70), Qt.AlignLeft, icon)
        p.setFont(f(32, 700))
        p.setPen(QColor(TITLE))
        p.drawText(QRectF(margin + 84, y - 4, inner - 84, 44), Qt.AlignLeft, t1)
        p.setFont(f(26, 400))
        p.setPen(QColor(META))
        p.drawText(QRectF(margin + 84, y + 40, inner - 84, 44), Qt.AlignLeft, t2)
        y += 124

    # ---- 界面截图 ----
    p.setPen(QColor(TITLE))
    p.setFont(f(40, 800))
    p.drawText(QRectF(margin, y, inner, 60), Qt.AlignLeft, "一眼看全")
    y += 80
    y = draw_shot(p, "s060_species.png", margin, y, inner, big_h,
                  "鸟种库 · 11171种图鉴，按鸟种归档浏览")
    ya = draw_shot(p, "s060_timeline.png", margin, y, half_w, half_h,
                   "时间线 · 按月回顾")
    yb = draw_shot(p, "s060_map.png", margin + half_w + 30, y, half_w, half_h,
                   "鸟点地图 · 高德底图")
    y = max(ya, yb)
    ya = draw_shot(p, "migration_map_real_barswa_w26.png", margin, y, half_w,
                   half_h, "迁徙地图 · 家燕52周全球动画（图鉴页直达）")
    yb = draw_shot(p, "multibird_viewer.png", margin + half_w + 30, y, half_w,
                   half_h, "照片查看器 · 多鸟画框识别")
    y = max(ya, yb)
    ya = draw_shot(p, "s060_achievements.png", margin, y, half_w, half_h,
                   "成就 · 徽章与年度统计")
    yb = draw_shot(p, "distribution_map.png", margin + half_w + 30, y, half_w,
                   half_h, "图鉴 · 地区分布图")
    y = max(ya, yb)
    # 年报长图(左) + 分享卡(右) 同行
    ya = draw_shot(p, "report_poster.png", margin, y, inner * 0.48, report_h,
                   "年度报告长图 · 可导出分享")
    yb = draw_shot(p, "share.png", margin + inner * 0.48 + 40, y,
                   inner * 0.30, min(sc_h, report_h) - 30, "物种分享卡")
    y = max(ya, yb)

    # ---- 功能清单 ----
    p.setPen(QColor(TITLE))
    p.setFont(f(40, 800))
    p.drawText(QRectF(margin, y, inner, 60), Qt.AlignLeft, "还有这些")
    y += 76
    items_l = ["画框识别：框出漏掉的鸟单独补识别", "待复核：低置信度逐张人工确认",
               "RAW原片直接识别（NEF/ARW/CR3/DNG等）", "HEIC格式支持（iPhone直出）",
               "AI识别与导入并行，边导边认", "深色/浅色主题 · 中英双语"]
    items_r = ["物种分享卡（含罕见度徽章+拍摄参数）", "eBird CSV观察记录导出",
               "智能建点：GPS照片自动归组", "中文路径/中文文件名完全支持",
               "便携免安装，U盘可带走", "数据库自动备份（保留7份）· 无显卡也能跑"]
    p.setFont(f(27, 400))
    for i, (a, b) in enumerate(zip(items_l, items_r)):
        yy = y + i * 56
        p.setPen(QColor(META))
        p.drawText(QRectF(margin, yy, half_w, 50), Qt.AlignLeft, f"·  {a}")
        p.drawText(QRectF(margin + half_w + 30, yy, half_w, 50),
                   Qt.AlignLeft, f"·  {b}")
    y += len(items_l) * 56 + 40

    # ---- 使用门槛 ----
    p.setPen(QColor(TITLE))
    p.setFont(f(34, 700))
    p.drawText(QRectF(margin, y, inner, 50), Qt.AlignLeft, "怎么用")
    y += 56
    p.setFont(f(27, 400))
    p.setPen(QColor(META))
    for line in ("Windows 10 / 11 64位 · 免安装便携版（约1GB，解压即用）",
                 "下载解压 → 双击 鸟迹BirdTrace.exe → 导入照片，其余交给AI",
                 "有独立显卡自动用GPU（更快）；没有也能跑",
                 "地图底图需要联网；识别、管理全部在本地完成"):
        p.drawText(QRectF(margin, y, inner, 44), Qt.AlignLeft, f"·  {line}")
        y += 46
    y += 30   # 与页脚的间隔

    # ---- 页脚(固定画在画布底部) ----
    foot_y = H - 150
    p.setPen(QColor("#DCDBCC"))
    p.drawLine(margin, foot_y, W - margin, foot_y)
    p.setPen(QColor(META))
    p.setFont(f(24, 400))
    p.drawText(QRectF(margin, foot_y + 20, inner, 60), Qt.AlignLeft,
               "免费 · 本地优先 · 照片永不外传    鸟迹 BirdTrace for Windows v0.6.0")
    p.drawText(QRectF(margin, foot_y + 62, inner, 70), Qt.AlignLeft,
               "致谢：识别模型 BirdTrace FastViT-MA36（安卓版作者） · YOLO11 · "
               "eBird · IUCN · 高德地图")
    assert y < foot_y - 10, f"内容超出页脚区: y={y} foot={foot_y}"
    p.end()

    out = SH / "intro_v0.6.0.png"
    ok = pm.save(str(out), "PNG")
    print("saved", out, pm.width(), "x", pm.height(), ok)


if __name__ == "__main__":
    main()
