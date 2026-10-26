# -*- coding: utf-8 -*-
"""地理×月份先验 (BirdGeoPrior.sqlite)。

库结构 (已逆向确认):
  regions(region_id TEXT PK, level country|admin1, parent_id)
  priors(region_id, month 1-12, checklist_count, vector BLOB 10480字节)
  metadata(key, value)

解码 (2026-10-22 经 US-NY/US-CA/GB/CN-BJ 多地区鸟况实证校准):
  value = (128 - uint8字节) × 0.03125, 字节0为哨兵=硬-4.0
  依据: 取反后 纽约1月 = 灯草鹀/旅鸫/主红雀(当地冬鸟)✓、加州 = 安娜蜂鸟/金冠带鹀✓、
        北京 = 麻雀+2.0顶格✓、家麻雀-1.5(北京确无)✓、白胸翡翠-3.97(南方鸟)✓、
        大尾拟八哥(美洲)-1.5✓、中位数-1.5=rescue地板✓;
        字节值域[64..255] → [+2.0..-3.97] 与 clamp[-4,+2] 自洽, 字节0违反clamp故为哨兵。
  语义: +2=顶格常见, 0=中性, -1.5/-2.0=无本地数据rescue地板, -4=从不出现
官方融合强度: app_reference_prior_strength = 0.6
GLOBAL 或无匹配区域 -> 中性先验 0 (不重排)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np

SCALE = 0.03125
N_CLASSES = 10480


class GeoPrior:
    def __init__(self, db_path: str | Path, strength: float = 0.6):
        self.conn = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
        self.strength = strength
        self._cache: dict[tuple[str, int], np.ndarray] = {}

    def regions(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT region_id, level, parent_id FROM regions ORDER BY ordinal").fetchall()
        return [{"id": r[0], "level": r[1], "parent": r[2]} for r in rows]

    def has_region(self, region_id: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM regions WHERE region_id=?", (region_id,)).fetchone() is not None

    def vector(self, region_id: str, month: int) -> np.ndarray | None:
        """返回10480维先验(log空间), 无数据时返回None(中性)。"""
        if region_id in (None, "", "GLOBAL"):
            return None
        key = (region_id, month)
        if key not in self._cache:
            row = self.conn.execute(
                "SELECT vector FROM priors WHERE region_id=? AND month=?",
                (region_id, month)).fetchone()
            if row is None:
                self._cache[key] = None
            else:
                b = np.frombuffer(row[0], dtype=np.uint8)
                v = (128.0 - b.astype(np.float32)) * SCALE
                v[b == 0] = -4.0  # 哨兵: 全球无数据 → 硬absent
                # 元数据 clamp[-4,+2]; 个别区域行存在未截断的噪声值(字节<64), 按文档截断
                np.clip(v, -4.0, 2.0, out=v)
                self._cache[key] = v
        return self._cache[key]

    def rerank(self, logits: np.ndarray, region_id: str | None, month: int
               ) -> tuple[np.ndarray, np.ndarray]:
        """返回 (log_probs, rerank_scores)。

        final = log_softmax(logits) + strength * prior[region][month]
        """
        m = logits.max()
        log_probs = logits - m - np.log(np.exp(logits - m).sum())
        prior = self.vector(region_id or "GLOBAL", month)
        if prior is None:
            return log_probs, log_probs
        return log_probs, log_probs + self.strength * prior

    def close(self):
        self.conn.close()
