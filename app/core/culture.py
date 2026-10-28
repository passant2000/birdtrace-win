# -*- coding: utf-8 -*-
"""鸟类文化知识库查询 (assets/data/bird_culture.sqlite, 只读)。

表结构 (已验证):
  taxa(taxon_id=species_code, scientific_name, english_name, chinese_name)
  stories(story_id, evidence_confidence, disputed)
  localized_text(story_id, language 'zh-Hans'/'en', title, subtitle, short_summary,
                 summary, body, scientific_note, taxonomy_note,
                 cultural_context_note, source_note)
  story_categories(story_id, category英文键)
  story_taxa(link_id, story_id, taxon_id 可空, scope exactSpecies|probableSpecies|
             uncertain|vernacularGroup, group_label, ...)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..paths import assets_dir

CATEGORY_ZH = {
    "nameOrigin": "名称由来", "naturalHistory": "博物史", "historicalStory": "历史故事",  # i18n:ok
    "conservationCulture": "保护文化", "nationalSymbolism": "国家象征",  # i18n:ok
    "literature": "文学", "symbolism": "象征", "folklore": "民俗",  # i18n:ok
    "art": "艺术", "indigenousTradition": "原住民传统", "etymology": "词源",  # i18n:ok
    "poetry": "诗歌", "mythology": "神话", "traditionalKnowledge": "传统知识",  # i18n:ok
    "music": "音乐", "historicalNaturalHistory": "博物史",  # i18n:ok
    "heraldry": "纹章", "religion": "宗教", "royalSymbolism": "王室象征",  # i18n:ok
    "historicalMisidentification": "历史误认", "omen": "征兆",  # i18n:ok
    "seasonalKnowledge": "季节知识", "ritual": "仪式",  # i18n:ok
}


class Culture:
    def __init__(self, data_dir: Path | None = None):
        data_dir = Path(data_dir) if data_dir else assets_dir() / "data"
        # 文化库是可选资产: 文件损坏/缺失(如U盘拷贝坏)时降级为无文化功能,
        # 绝不让主程序起不来(用户实测malformed库导致启动崩溃)
        try:
            self.conn = sqlite3.connect(
                f"file:{data_dir / 'bird_culture.sqlite'}?mode=ro", uri=True)
            self.conn.row_factory = sqlite3.Row
        except sqlite3.Error:
            self.conn = None

    def _rows(self, sql: str, args=()) -> list:
        """容错查询: 库损坏返回空(调用方按"无数据"降级)。"""
        if self.conn is None:
            return []
        try:
            return self.conn.execute(sql, args).fetchall()
        except sqlite3.Error:
            return []

    def stories_for(self, species_code: str) -> list[dict]:
        """某物种的文化故事(中文), 含分类标签与来源行。"""
        rows = self._rows(
            """
            SELECT s.story_id, s.evidence_confidence, s.disputed,
                   t.title, t.subtitle, t.short_summary, t.summary, t.body,
                   t.scientific_note, t.cultural_context_note, t.source_note,
                   (SELECT group_concat(c.category, '|') FROM story_categories c
                     WHERE c.story_id = s.story_id) AS cats,
                   (SELECT group_concat(ps.title, '|') FROM story_sources ss
                     JOIN production_sources ps ON ps.source_id = ss.source_id
                     WHERE ss.story_id = s.story_id) AS src_names
            FROM story_taxa st
            JOIN stories s ON s.story_id = st.story_id
            JOIN localized_text t ON t.story_id = s.story_id AND t.language = 'zh-Hans'
            WHERE st.taxon_id = ? AND st.scope IN ('exactSpecies', 'probableSpecies')
            ORDER BY s.evidence_confidence DESC
            """,
            (species_code,))
        out = []
        for r in rows:
            cats = [CATEGORY_ZH.get(c, c) for c in (r["cats"] or "").split("|") if c]
            out.append({
                "title": r["title"],
                "subtitle": r["subtitle"] or "",
                "summary": r["short_summary"] or r["summary"] or "",
                "body": r["body"] or "",
                "categories": cats,
                "confidence": r["evidence_confidence"],
                "disputed": bool(r["disputed"]),
                "sources": [s for s in (r["src_names"] or "").split("|") if s],
            })
        return out

    def display_associations(self, species_code: str) -> list[dict]:
        """官方展示关联(带中文标签与caveat)。"""
        rows = self._rows(
            """
            SELECT a.label_zh_hans AS label, a.caveat_zh_hans AS caveat,
                   t.title
            FROM story_display_associations a
            JOIN stories s ON s.story_id = a.story_id
            JOIN localized_text t ON t.story_id = s.story_id AND t.language = 'zh-Hans'
            WHERE a.taxon_id = ?
            """,
            (species_code,))
        return [dict(r) for r in rows]

    def daily_pool(self) -> list[str]:
        """有中文故事的物种代码池(exactSpecies), 排序保证确定性。"""
        rows = self._rows(
            """
            SELECT DISTINCT st.taxon_id AS code
            FROM story_taxa st
            JOIN stories s ON s.story_id = st.story_id
            JOIN localized_text t ON t.story_id = s.story_id AND t.language = 'zh-Hans'
            WHERE st.scope = 'exactSpecies'
            ORDER BY code
            """)
        return [r["code"] for r in rows]

    def close(self):
        if self.conn is not None:
            self.conn.close()


_culture: Culture | None = None


def get_culture() -> Culture:
    global _culture
    if _culture is None:
        _culture = Culture()
    return _culture
