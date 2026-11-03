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
        """返回某月10480维先验(log空间), 无数据时返回None(中性)。

        注意: 自2026-10起识别重排不再使用本方法(月度维度失真, 见region_vector);
        保留是为了数据核查与未来数据修复后恢复月度重排。
        """
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

    def region_vector(self, region_id: str) -> np.ndarray | None:
        """区域先验(与月份无关): 12个月逐元素最大值。

        月度维度失真(CN各行的月度值是常值铺flat+个别月跳变, 家燕1月在北京
        顶格+3.72超clamp; 经作者确认"删掉月份"), 且安卓识别同样按月消费此表
        ——双方一致去掉月份维度, 保留区域维度(哪些物种在该地区常见)。
        取12月max = "该物种在该地区的最常见程度", 数据修复后可恢复月度。
        """
        if region_id in (None, "", "GLOBAL"):
            return None
        key = ("R", region_id)
        if key not in self._cache:
            mats = [self.vector(region_id, m) for m in range(1, 13)]
            if all(v is None for v in mats):
                self._cache[key] = None
            else:
                stack = np.stack([v if v is not None
                                  else np.full(N_CLASSES, -4.0, dtype=np.float32)
                                  for v in mats])
                self._cache[key] = stack.max(axis=0)
        return self._cache[key]

    def region_parents(self) -> dict[str, str | None]:
        """{region_id: 父区域id(国家级为None)} — 分布表选行时取所在国用。"""
        return {r["id"]: r["parent"] for r in self.regions()}

    def rerank(self, logits: np.ndarray, region_id: str | None, month: int = 0
               ) -> tuple[np.ndarray, np.ndarray]:
        """返回 (log_probs, rerank_scores)。

        final = log_softmax(logits) + strength * prior[region]
        month参数已废弃(保留兼容调用方签名), 先验与月份无关, 见region_vector。
        """
        m = logits.max()
        log_probs = logits - m - np.log(np.exp(logits - m).sum())
        prior = self.region_vector(region_id or "GLOBAL")
        if prior is None:
            return log_probs, log_probs
        return log_probs, log_probs + self.strength * prior

    def close(self):
        self.conn.close()
