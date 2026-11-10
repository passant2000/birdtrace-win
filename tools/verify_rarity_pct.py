# -*- coding: utf-8 -*-
"""0.8-⑤ 分享卡罕见度百分位验证。

验证:
  [1] rarity_percentile 与 rarity_tier 同源单调(同一次排序): 档位越罕见
      百分位越小; 罕见≤20% / 稀有(20,40] / 不常见(40,60] 边界一致。
  [2] 百分位不外泄原始先验值(0<pct≤100)。
  [3] _fmt_pct 格式(整数/一位小数/<0.1)。
  [4] render_card 带 rarity_pct 渲染冒烟(稀有/罕见 pill 文本含百分位)。

用法: .venv/Scripts/python.exe tools/verify_rarity_pct.py  (离线, 真实先验库)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)

    from app.core.prior_hint import get_hint
    from app.core.sharecard import _fmt_pct, render_card

    hint = get_hint()
    rid = "CN-SH"   # 库内/先验库一致的真实区域id(eBird码)

    # 与 rarity_tier 共用排序: 按百分位升序=先验值升序, 档位应随之从罕见→常见
    idx_by_code = hint.code_idx
    from app.core.prior_hint import RARITY_TIERS
    pairs = []
    for code, idx in idx_by_code.items():
        tier = hint.rarity_tier(code, rid)
        if tier is None:
            continue
        pct = hint.rarity_percentile(code, rid)
        pairs.append((code, tier, pct))
    check(len(pairs) > 300, f"CN-SH 有数据物种 {len(pairs)} 种(名录映射后)")
    check(all(p is not None and 0 < p <= 100 for _c, _t, p in pairs),
          "百分位全部在 (0,100] 且非None(不外泄先验值)")

    def tier_of(p):
        return RARITY_TIERS[min(4, int((100 - p) / 100 * 5))]  # 由pct反推档位

    bad = [(c, t, p) for c, t, p in pairs if tier_of(p) != t]
    check(not bad, f"档位与百分位同源一致 (反例{len(bad)}: {bad[:2]})")
    rare = sorted((p, c, t) for c, t, p in pairs if t == "罕见")
    common = sorted((p, c, t) for c, t, p in pairs if t == "常见")
    check(rare and rare[0][0] > 0 and rare[0][0] <= 20,
          f"最罕见物种 pct={rare[0][0]:.2f}% ∈ (0,20] ({rare[0][1]})")
    check(common and common[-1][0] > 60,
          f"最常见物种 pct={common[-1][0]:.1f}% > 60 ({common[-1][1]})")

    print("\n[3] _fmt_pct 格式")
    check(_fmt_pct(37.4) == "37", "37.4 → '37'")
    check(_fmt_pct(3.24) == "3.2", "3.24 → '3.2'")
    check(_fmt_pct(0.19) == "0.2", "0.19 → '0.2'")
    check(_fmt_pct(0.04) == "<0.1", "0.04 → '<0.1'")
    check(_fmt_pct(10.0) == "10", "10.0 → '10'")

    print("\n[4] render_card 冒烟(带/不带百分位)")
    import json
    labels = json.loads((PROJ / "assets/data/labels.json").read_text(encoding="utf-8"))
    code_of = {}
    for l in labels:
        code_of.setdefault(hint.rarity_tier(l["code"], rid), l["code"])
    rare_code = code_of.get("罕见") or code_of.get("稀有")
    info = {"cn": "测试鸟种", "pinyin": ["cè", "shì", "niǎo"], "en": "Test Bird",
            "sci": "Testus birdus", "lifer_no": 1,
            "rarity": hint.rarity_tier(rare_code, rid),
            "rarity_pct": hint.rarity_percentile(rare_code, rid),
            "photographer": "测试者", "date": "2026-11-03",
            "place": "中国·上海", "exif": {}}
    pm = render_card("", info, "light")
    check(not pm.isNull() and pm.width() == 2000, "rarity+pct 渲染出卡")
    from app.core.sharecard import _fit, _font
    from PySide6.QtGui import QFontMetrics
    tier_txt = "罕见"  # 内部码→按当前语言(默认zh)绘制
    exp = tier_txt + " · 前 " + _fmt_pct(info["rarity_pct"]) + "%"
    fm = QFontMetrics(_font(38, 700))
    check(fm.horizontalAdvance(exp) < 800,
          f"pill 文本宽度合理 ({exp})")
    no_pct = dict(info, rarity_pct=None)
    pm2 = render_card("", no_pct, "light")
    check(not pm2.isNull(), "rarity_pct=None 回退纯档位渲染")

    print()
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
