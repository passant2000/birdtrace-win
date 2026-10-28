# -*- coding: utf-8 -*-
"""基于地理先验的当月活性提示与罕见度5档。

先验值是log空间[-4,+2]的清单频率代理:
  当月档位: ≥1 常见 / ≥0 可见 / ≥-1 偶见 / <-1 罕见
  罕见度  : 对所选区域取每物种12个月最大值, 在全部物种中按分位5档
           (前20%常见 … 后20%罕见; 全年无数据的记"数据不足")
"""
from __future__ import annotations

import json
from pathlib import Path

from ..paths import assets_dir

MONTH_TIERS = [(1.0, "常见"), (0.0, "可见"), (-1.0, "偶见"), (-4.01, "罕见")]  # i18n:ok
RARITY_TIERS = ["常见", "较常见", "不常见", "稀有", "罕见"]  # i18n:ok

# 中文层级码的英文显示(内部码保持中文, 展示点用tier_display)
TIER_EN = {"常见": "Common", "可见": "Seen", "偶见": "Occasional",  # i18n:ok
           "罕见": "Rare", "较常见": "Fairly common", "不常见": "Uncommon",  # i18n:ok
           "稀有": "Very rare"}  # i18n:ok


def tier_display(tier: str) -> str:
    from ..i18n import t
    return t(tier, TIER_EN.get(tier, tier))
RARITY_TIERS = ["常见", "较常见", "不常见", "稀有", "罕见"]  # i18n:ok


class PriorHint:
    def __init__(self, data_dir: Path | None = None):
        data_dir = Path(data_dir) if data_dir else assets_dir() / "data"
        from ..ai.geo_prior import GeoPrior
        self.gp = GeoPrior(data_dir / "geo_prior.sqlite")
        labels = json.loads((data_dir / "labels.json").read_text(encoding="utf-8"))
        self.code_idx = {l["code"]: l["i"] for l in labels}
        self._rarity_cache: dict[str, dict[int, str]] = {}

    def monthly_tier(self, code: str, region_id: str | None, month: int) -> str | None:
        """当月活性档位; 区域/物种无数据返回 None。"""
        vec = self.gp.vector(region_id or "GLOBAL", month)
        if vec is None:
            return None
        idx = self.code_idx.get(code)
        if idx is None:
            return None
        v = float(vec[idx])
        for floor, name in MONTH_TIERS:  # i18n:ok
            if v >= floor:
                return name
        return None

    def _rarity_for_region(self, region_id: str) -> dict[int, str]:
        tiers = self._rarity_cache.get(region_id)
        if tiers is not None:
            return tiers
        import numpy as np
        mats = []
        for m in range(1, 13):
            v = self.gp.vector(region_id, m)
            mats.append(v if v is not None else np.full(10480, -128.0))
        maxima = np.max(np.stack(mats), axis=0)  # 每物种12月最大先验
        present = np.where(maxima > -4.0)[0]     # 有清单数据的物种
        tiers = {}
        if present.size:
            order = present[np.argsort(maxima[present])[::-1]]  # 降序
            n = len(order)
            for rank, idx in enumerate(order):
                tier = min(4, int(rank / n * 5))  # i18n:ok
                tiers[int(idx)] = RARITY_TIERS[tier]  # i18n:ok
        self._rarity_cache[region_id] = tiers
        return tiers

    def rarity_tier(self, code: str, region_id: str | None) -> str | None:
        idx = self.code_idx.get(code)
        if idx is None or not region_id or region_id == "GLOBAL":
            return None
        return self._rarity_for_region(region_id).get(idx)

    def close(self):
        self.gp.close()


_hint: PriorHint | None = None


def get_hint() -> PriorHint:
    global _hint
    if _hint is None:
        _hint = PriorHint()
    return _hint
