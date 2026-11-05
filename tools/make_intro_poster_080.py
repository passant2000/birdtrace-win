# -*- coding: utf-8 -*-
"""生成鸟迹v0.8.0官方介绍长图(1080宽, 手机友好), 重点=新增功能与优化。

产物: data/ui_shots/intro_v0.8.0.png
风格与v0.6.0长图同源(米色系+圆角截图卡)。
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


def f(size: int, weight: int = 400) -> QFont:
    ft = QFont()
    ft.setFamilies(["MiSans", "HarmonyOS Sans SC", "PingFang SC",
                    "Microsoft YaHei UI", "Segoe UI"])
    ft.setPixelSize(size)
    try:
        ft.setWeight(QFont.Weight(weight))
    except ValueError:
        ft.setWeight(QFont.Weight.Bold)
    return ft


def rounded(p: QPainter, x: float, y: float, w: float, h: float, r: float):
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, w, h), r, r)
    return path


def draw_shot(p: QPainter, name: str, x: float, y: float, w: float,
              h: float, caption: str, cap_h: float = 54) -> float:
    pm = QPixmap(str(SH / name))
    src_ratio = pm.width() / pm.height()
    dst_ratio = w / h
    if src_ratio > dst_ratio:
        cw = int(pm.height() * dst_ratio)
        pm = pm.copy((pm.width() - cw) // 2, 0, cw, pm.height())
    else:
        ch = int(pm.width() / dst_ratio)
        pm = pm.copy(0, (pm.height() - ch) // 2, pm.width(), ch)
    clip = rounded(p, x + 3, y + 4, w, h, 18)
    p.fillPath(clip, QColor("#D8D6C4"))
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


def section(p: QPainter, y: float, title: str) -> float:
    p.setPen(QColor(TITLE))
    p.setFont(f(40, 800))
    p.drawText(QRectF(60, y, W - 120, 60), Qt.AlignLeft, title)
    return y + 80


def main():
    app = QApplication([])
    margin = 60
    inner = W - margin * 2

    big_h = inner * 820 / 1280
    half_w = (inner - 30) / 2
    half_h = half_w * 820 / 1280

    # 高度预算: 头部430 + 新功能(4条×124) + 大图1 + 双图3组 + 优化(6条×56+90)
    # + 双图1组 + 怎么用(4×46+56) + 页脚区
    H = int(430 + 4 * 124 + 70 + (big_h + 84) + 3 * (half_h + 86)
            + 6 * 56 + 130 + (half_h + 86) + 300 + 160 + 120)
    pm = QPixmap(W, H)
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
               "Windows 版 · v0.8.0 正式版 · 免费便携")
    p.setPen(QColor(META))
    p.setFont(f(30, 500))
    p.drawText(QRectF(margin, 250, inner, 170), Qt.AlignLeft | Qt.TextWordWrap,
               "v0.8.0 把鸟迹从“识别工具”推进成“随身鸟类工作台”：标注跟着"
               "照片文件夹走、连拍自动折叠、导出向导、批量分享卡——仍然全部"
               "本地离线，一张照片都不外传。")

    y = 430
    # ---- 本版新增 ----
    y = section(p, y, "v0.8.0 新增功能")
    feats = [
        ("🏷️", "标注随文件夹走（多机互通）",
         "每个照片文件夹自动生成隐藏的 .birdtrace.json，确认鸟种/鸟点/评分"
         "按照片内容指纹记录；换电脑、重新导入自动恢复，人工记录优先不被覆盖"),
        ("📸", "连拍智能折叠 + 组内统一",
         "2秒内同种连拍折成一张封面（角标 ×N，封面=最美一张）；"
         "组内鸟种自动统一（学 SuperPicky），人工确认帧绝不改写"),
        ("📤", "导出向导 + 批量分享卡",
         "复制/原地重命名 × CameraRaw式文件名模板（日期/鸟名/序号/鸟点），"
         "RAW+JPG成对同号、绝不覆盖；批量分享卡每种鸟挑1~4张最美一键出图"),
        ("💽", "移动硬盘离线韧性",
         "硬盘没插=“离线”不再报“丢失”，缩略图/统计/标注照常用；"
         "重新链接按内容匹配，文件改名也能找回"),
    ]
    for icon, t1, t2 in feats:
        p.setFont(f(44, 500))
        p.setPen(QColor(ACCENT))
        p.drawText(QRectF(margin, y - 8, 70, 70), Qt.AlignLeft, icon)
        p.setFont(f(32, 700))
        p.setPen(QColor(TITLE))
        p.drawText(QRectF(margin + 84, y - 4, inner - 84, 44), Qt.AlignLeft, t1)
        p.setFont(f(25, 400))
        p.setPen(QColor(META))
        p.drawText(QRectF(margin + 84, y + 42, inner - 84, 76),
                   Qt.AlignLeft | Qt.TextWordWrap, t2)
        y += 150

    # ---- 截图: 时间线大图 ----
    y = section(p, y + 10, "一眼看全")
    y = draw_shot(p, "s080_timeline_light.png", margin, y, inner, big_h,
                  "时间线 · 连拍折叠 ×3，点日期按日分组")

    ya = draw_shot(p, "s080_batch_share.png", margin, y, half_w,
                   half_h * 0.9, "批量分享卡 · 每种1~4张最美")
    yb = draw_shot(p, "s080_export_wizard.png", margin + half_w + 30, y,
                   half_w, half_h * 0.9, "导出向导 · 模板命名+预览")
    y = max(ya, yb)
    ya = draw_shot(p, "s080_species_dex_light.png", margin, y, half_w, half_h,
                   "图鉴 · 地区徽章+罕见度百分位")
    yb = draw_shot(p, "s080_review_light.png", margin + half_w + 30, y,
                   half_w, half_h, "待复核 · top5候选下拉")
    y = max(ya, yb)
    ya = draw_shot(p, "s080_viewer_light.png", margin, y, half_w, half_h,
                   "查看器 · 识别结果与快捷操作")
    yb = draw_shot(p, "s080_species_dex_dark.png", margin + half_w + 30, y,
                   half_w, half_h, "深色主题 · 全面适配")
    y = max(ya, yb)

    # ---- 体验优化 ----
    y = section(p, y + 6, "同期的体验优化")
    items_l = ["中文名全面对齐《中国观鸟年报12.0(2024)》",
               "日期选择弹层：年份/月份下拉一点直达",
               "查看器/待复核显示 top5 候选（点选即改鸟种）",
               "时间线点日期按日分组、点月按月",
               "侧边栏功能面板拖动重排，顺序记忆"]
    items_r = ["识别与标注回填并发保护，双主鸟启动自愈",
               "迁徙地图独立窗口+缓存秒开",
               "图鉴地区按照片实际拍摄地（最美照优先）",
               "深色主题正文/图鉴配色全面修复",
               "年度十八图每种鸟优先一格 · 完整显示不裁切"]
    p.setFont(f(27, 400))
    for i, (a, b) in enumerate(zip(items_l, items_r)):
        yy = y + i * 56
        p.setPen(QColor(META))
        p.drawText(QRectF(margin, yy, half_w, 50), Qt.AlignLeft, f"·  {a}")
        p.drawText(QRectF(margin + half_w + 30, yy, half_w, 50),
                   Qt.AlignLeft, f"·  {b}")
    y += len(items_l) * 56 + 36

    # ---- 导入页 + 关于 ----
    ya = draw_shot(p, "s080_import_light.png", margin, y, half_w, half_h,
                   "导入 · 地区卡提醒+确认弹窗")
    yb = draw_shot(p, "s080_about_light.png", margin + half_w + 30, y,
                   half_w, half_h, "关于 · v0.8.0 正式版")
    y = max(ya, yb)

    # ---- 怎么用 ----
    y += 10
    p.setPen(QColor(TITLE))
    p.setFont(f(34, 700))
    p.drawText(QRectF(margin, y, inner, 50), Qt.AlignLeft, "怎么用")
    y += 56
    p.setFont(f(27, 400))
    p.setPen(QColor(META))
    for line in ("Windows 10 / 11 64位 · 免安装便携版（约1.2GB，解压即用）",
                 "下载解压 → 双击 鸟迹BirdTrace.exe → 导入照片，其余交给AI",
                 "老库直接用：启动自动刷鸟种表/清重复记录；建议整体重新识别一次",
                 "有独立显卡自动用GPU；识别、管理全部本地完成，照片永不外传"):
        p.drawText(QRectF(margin, y, inner, 44), Qt.AlignLeft, f"·  {line}")
        y += 46
    y += 30

    # ---- 页脚 ----
    foot_y = y + 40
    p.setPen(QColor("#DCDBCC"))
    p.drawLine(margin, foot_y, W - margin, foot_y)
    p.setPen(QColor(META))
    p.setFont(f(24, 400))
    p.drawText(QRectF(margin, foot_y + 20, inner, 60), Qt.AlignLeft,
               "免费 · 本地优先 · 照片永不外传    鸟迹 BirdTrace for Windows v0.8.0")
    p.drawText(QRectF(margin, foot_y + 62, inner, 70), Qt.AlignLeft,
               "致谢：识别模型 BirdTrace FastViT-MA36（安卓版作者，CC BY-NC 4.0）"
               " · YOLO11 · eBird · IUCN · 高德地图")
    p.end()

    out = SH / "intro_v0.8.0.png"
    ok = pm.save(str(out), "PNG")
    print("saved", out, pm.width(), "x", pm.height(), ok)


if __name__ == "__main__":
    main()
