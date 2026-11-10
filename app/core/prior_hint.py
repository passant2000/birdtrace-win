# -*- coding: utf-8 -*-
"""基于地理先验的区域提示与罕见度5档。

先验值是log空间[-4,+2]的清单频率代理:
  区域档位: ≥1 常见 / ≥0 可见 / ≥-1 偶见 / <-1 罕见
  罕见度  : 对所选区域取每物种12个月最大值, 在全部物种中按分位5档
           (前20%常见 … 后20%罕见; 全年无数据的记"数据不足")

月份维度已去掉(2026-10, 作者确认"删掉月份"): CN各行的月度值是常值铺
flat+个别月跳变(家燕1月在北京顶格, 原始字节超clamp), 安卓识别同样按月
消费此表——两端一致只保留区域维度(12个月逐元素最大值, 见
geo_prior.GeoPrior.region_vector)。数据修复后可恢复月度。
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


def value_tier(v: float) -> str:
    """区域先验值 -> 档位内部码(中文, 显示经tier_display)。"""
    for floor, name in MONTH_TIERS:  # i18n:ok
        if v >= floor:
            return name
    return "罕见"  # i18n:ok

RARITY_TIERS = ["常见", "较常见", "不常见", "稀有", "罕见"]  # i18n:ok


class PriorHint:
    def __init__(self, data_dir: Path | None = None):
        data_dir = Path(data_dir) if data_dir else assets_dir() / "data"
        from ..ai.geo_prior import GeoPrior
        self.gp = GeoPrior(data_dir / "geo_prior.sqlite")
        labels = json.loads((data_dir / "labels.json").read_text(encoding="utf-8"))
        self.code_idx = {l["code"]: l["i"] for l in labels}
        self._rarity_cache: dict[str, dict[int, tuple[str, float]]] = {}
        self._peaks_cache: dict[str, dict[str, float]] = {}

    def region_tier(self, code: str, region_id: str | None) -> str | None:
        """该物种在所选区域的档位(区域先验=12月最大值, 与月份无关)。"""
        vec = self.gp.region_vector(region_id or "GLOBAL")
        if vec is None:
            return None
        idx = self.code_idx.get(code)
        if idx is None:
            return None
        return value_tier(float(vec[idx]))

    def _rarity_for_region(self, region_id: str) -> dict[int, tuple[str, float]]:
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
                # 百分位("前X%")=比它更稀有的有数据物种占比: 最稀有→~0%,
                # 最常见→~100%。与档位同源(同 rank), 供分享卡"罕见 · 前 3%"
                # 等口径; 不外泄原始先验值。
                pct = (n - rank) / n * 100.0
                tiers[int(idx)] = (RARITY_TIERS[tier], pct)  # i18n:ok
        self._rarity_cache[region_id] = tiers
        return tiers

    def rarity_tier(self, code: str, region_id: str | None) -> str | None:
        idx = self.code_idx.get(code)
        if idx is None or not region_id or region_id == "GLOBAL":
            return None
        got = self._rarity_for_region(region_id).get(idx)
        return got[0] if got else None

    def rarity_percentile(self, code: str, region_id: str | None) -> float | None:
        """该物种在区域有数据物种中的稀有百分位("前X%", 越小越罕见)。

        与 rarity_tier 同一次排序派生; 无数据/全球区域返回None。"""
        idx = self.code_idx.get(code)
        if idx is None or not region_id or region_id == "GLOBAL":
            return None
        got = self._rarity_for_region(region_id).get(idx)
        return got[1] if got else None

    def rarity_score(self, code: str, region_id: str | None) -> float | None:
        """区域稀有度分值 0-10(越大越罕见, 2026-11-10用户: 懂鸟式9.2分)。

        由同源百分位线性映射: score = 10 - pct/10。档位与分带天然对齐
        (百分位与档位同 rank 派生, 每20%一档):
          常见 80-100% → 0-2 | 较常见 60-80% → 2-4 | 不常见 40-60% → 4-6
          稀有 20-40% → 6-8 | 罕见 0-20% → 8-10
        同一物种在不同地区分数不同(上海少见的鸟在上海分高)。
        口径=区域内清单频率估算(eBird 先验), 与懂鸟全国口径不可比。
        无数据/全球区域返回 None。"""
        pct = self.rarity_percentile(code, region_id)
        if pct is None:
            return None
        return round(max(0.0, min(10.0, 10.0 - pct / 10.0)), 1)

    def region_peaks(self, code: str) -> dict[str, float]:
        """该物种全球各区域的峰值先验 {region_id: max(12个月)}。

        首次调用做一次全表扫描(~0.15s), 之后会话级缓存; 仅供图鉴页
        地区分布表使用。物种不在先验库时返回空dict。
        """
        got = self._peaks_cache.get(code)
        if got is None:
            idx = self.code_idx.get(code)
            got = {}
            if idx is not None:
                rows = self.gp.conn.execute(
                    "SELECT region_id, month, vector FROM priors").fetchall()
                if rows:
                    import numpy as np
                    from ..ai.geo_prior import N_CLASSES, SCALE
                    buf = np.frombuffer(b"".join(r[2] for r in rows),
                                        dtype=np.uint8).reshape(len(rows), N_CLASSES)
                    raw = buf[:, idx]
                    col = (128.0 - raw.astype(np.float32)) * SCALE
                    col[raw == 0] = -4.0
                    np.clip(col, -4.0, 2.0, out=col)
                    acc: dict[str, float] = {}
                    for i, (rid, _m, _blob) in enumerate(rows):
                        v = float(col[i])
                        if v > acc.get(rid, -4.1):
                            acc[rid] = v
                    got = acc
            self._peaks_cache[code] = got
        return got

    def close(self):
        self.gp.close()


_hint: PriorHint | None = None


def get_hint() -> PriorHint:
    global _hint
    if _hint is None:
        _hint = PriorHint()
    return _hint
