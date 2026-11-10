# -*- coding: utf-8 -*-
"""分享卡DPI边界回归: Windows缩放≥125%时elidedText等宽陷阱(2026-11-02)。

守卫(_fit)后必须在全部缩放系数下:
1. 边界串(参数行=右列最宽, advance==col_w)完整绘制——无省略号;
2. 正常串完整;
3. 真超宽串仍走缩字号/省略(守卫不能放过真溢出)。

用法: .venv/Scripts/python.exe tools/verify_sharecard_dpi.py
(每个缩放系数起独立子进程——QT_SCALE_FACTOR必须在QApplication前设置)
"""
from __future__ import annotations

import os
import subprocess
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


BODY = "SONY ILCE-1M2"
LENS = "FE 600mm F6.3 GM OSS"
# (名称, shot, 期望) 期望: complete=完整 / elide=省略(真溢出)
CASES = [
    ("陷阱·ISO400@1/50s(用户卡1)", "600mm · f/6.3 · 1/50s · ISO 400", "complete"),
    ("陷阱·ISO12800@1/50s", "600mm · f/6.3 · 1/50s · ISO 12800", "complete"),
    ("陷阱·ISO40000@1/50s", "600mm · f/6.3 · 1/50s · ISO 40000", "complete"),
    ("正常·ISO10000@1/200s(用户卡2)", "600mm · f/6.3 · 1/200s · ISO 10000", "complete"),
    ("真溢出·超长串(缩字号后仍超)", "600mm · f/6.3 · 1/8000s · ISO 102400 · "
     "600mm · f/6.3 · 1/8000s · ISO 102400 · 600mm", "elide"),
]
LONG_LENS = "FE 600mm F6.3 GM OSS 1.4x Teleconverter Super Tele Version"


def run_factor(factor: str) -> bool:
    env = dict(os.environ, QT_SCALE_FACTOR=factor)
    r = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--worker", factor],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=PROJ, env=env)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        print(r.stderr[-2000:])
        return False
    return "ALL_OK" in r.stdout


def worker(factor: str):
    sys.path.insert(0, PROJ)
    from PySide6.QtWidgets import QApplication
    app = QApplication([])          # noqa: F841 — 必须先建
    from PySide6.QtGui import QFont, QFontMetrics
    from app.core.sharecard import render_card, _font

    print(f"  —— QT_SCALE_FACTOR={factor} ——")
    f40 = _font(40, 500)
    fm = QFontMetrics(f40)
    ok = True

    def render_info(shot, body=BODY, lens=LENS):
        return {"cn": "测试", "pinyin": ["cè"], "en": "Test", "sci": "",
                "lifer_no": 81, "rarity": "常见", "photographer": "苏坡慢",
                "date": "2026-11-01", "place": "中国·浙江",
                "exif": {"body": body, "lens": lens, "shot": shot}}

    def line_extent(pm, y0, y1, x0):
        """右列一行亮像素范围(深色卡)。"""
        img = pm.toImage()
        xs = []
        for y in range(y0, y1):
            for x in range(x0, pm.width()):
                if img.pixelColor(x, y).lightness() > 120:
                    xs.append(x)
        if not xs:
            return None
        # 尾部40px内的字形高度(区分数字/省略号)
        tail_x0 = max(xs[0], max(xs) - 40)
        rows = set()
        for y in range(y0, y1):
            for x in range(tail_x0, max(xs) + 1):
                if img.pixelColor(x, y).lightness() > 120:
                    rows.add(y)
        return (min(xs), max(xs), (max(rows) - min(rows) + 1) if rows else 0)

    for name, shot, expect in CASES:
        pm = render_card(os.path.join(PROJ, "data", "_no_such.jpg"),
                         render_info(shot), "dark", width=1600)
        ph = pm.height() - 1000   # k=1(1600设计宽)
        adv = fm.horizontalAdvance(shot)
        col_w = min(max(fm.horizontalAdvance(BODY), fm.horizontalAdvance(LENS),
                        adv), 880)
        ext = line_extent(pm, ph + 686, ph + 754, 1600 - 112 - col_w - 80)
        if ext is None:
            check(False, f"{factor} {name}: 参数行无像素")
            ok = False
            continue
        x0, x1, tail_h = ext
        drawn = x1 - x0 + 1
        if expect == "complete":
            good = drawn >= adv - 6 and tail_h >= 12
            check(good, f"{factor} {name}: 宽{drawn}≈advance{adv} 尾高{tail_h}"
                        f"(数字) {'完整' if good else '却被截断!'}")
            ok = ok and good
        else:
            # 真溢出: 缩字号到28仍超→省略; 判宽不判尾高(中间省略尾段
            # 残笔+省略号共存, 高度启发式不可靠)
            good = drawn <= col_w and drawn < adv - 20
            check(good, f"{factor} {name}: 宽{drawn}≤col_w{col_w}"
                        f"(advance{adv}) {'正常省略' if good else '异常!'}")
            ok = ok and good

    # 长镜头走ElideMiddle路径(真溢出才截)
    pm = render_card(os.path.join(PROJ, "data", "_no_such.jpg"),
                     render_info("600mm · f/6.3 · 1/50s · ISO 400",
                                 lens=LONG_LENS), "dark")
    ph = pm.height() - 1000   # k=1(1600设计宽)
    adv_l = fm.horizontalAdvance(LONG_LENS)
    ext = line_extent(pm, ph + 590, ph + 658, 1600 - 112 - 880 - 80)
    good = bool(ext) and ext[1] - ext[0] + 1 <= 880 and adv_l > 880
    check(good, f"{factor} 长镜头ElideMiddle: "
                f"宽{(ext[1]-ext[0]+1) if ext else 0}≤880 (advance{adv_l})")
    ok = ok and good

    print("ALL_OK" if ok else "HAS_FAIL")


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--worker":
        worker(sys.argv[2])
        return
    print("== 分享卡DPI矩阵回归(修复后) ==")
    allok = True
    for factor in ("1", "1.25", "1.5", "1.75", "2"):
        allok &= run_factor(factor)
    print("===== 结论: " + ("全过 PASS" if allok else "存在失败 FAIL") + " =====")
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    main()
