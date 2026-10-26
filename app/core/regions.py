# -*- coding: utf-8 -*-
"""识别区域表: RecognitionRegions.json + 国名中文名表。

提供级联结构: GLOBAL -> 国家(249) -> 省级行政区(8国254个, 含中国34个)。
显示名优先级: JSON自带 zh-Hans > 本地国名表(assets/data/country_zh.json,
由babel CLDR预生成, 免打包31MB babel) > sourceName英文。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ..paths import assets_dir as _assets_dir


@lru_cache(maxsize=1)
def _country_zh() -> dict[str, str]:
    """ISO 3166-1 alpha-2 -> 中文名 (babel CLDR 预生成表)。"""
    try:
        p = _assets_dir() / "data" / "country_zh.json"
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


@lru_cache(maxsize=1)
def load_regions() -> list[dict]:
    raw = json.loads((_assets_dir() / "data" / "regions.json").read_text(encoding="utf-8"))
    return raw["regions"]


_TREE_CACHE: dict[str, dict] = {}


def build_tree() -> dict:
    """返回 {countries: [{id, name, subs: [{id, name}]}], global_name}。

    名称随app.i18n当前语言: 中文模式中文名, 英文模式sourceName英文名。
    """
    from .. import i18n
    key = i18n.lang()
    if key not in _TREE_CACHE:
        _TREE_CACHE[key] = _build_tree_impl(key == "en")
    return _TREE_CACHE[key]


def _build_tree_impl(en: bool) -> dict:
    zh = _country_zh()
    countries: dict[str, dict] = {}
    global_name = "World" if en else "全球"
    for r in load_regions():
        names = r.get("localizedNames") or {}
        rid = r["id"]
        if r["administrativeLevel"] == "global":
            global_name = (r.get("sourceName") if en
                           else names.get("zh-Hans", "全球"))
            continue
        if r["administrativeLevel"] == "country":
            cn_name = names.get("zh-Hans") or zh.get(rid) or r["sourceName"]
            countries[rid] = {"id": rid,
                              "name": (r["sourceName"] or cn_name) if en else cn_name,
                              "subs": []}
    for r in load_regions():
        if r["administrativeLevel"] != "admin1":
            continue
        names = r.get("localizedNames") or {}
        parent = r.get("parentID")
        cn_name = names.get("zh-Hans") or r["sourceName"]
        sub = {"id": r["id"],
               "name": (r["sourceName"] or cn_name) if en else cn_name}
        if parent in countries:
            countries[parent]["subs"].append(sub)
    for c in countries.values():
        c["subs"].sort(key=lambda s: s["name"])
    listed = sorted(countries.values(), key=lambda c: c["name"])
    return {"global_name": global_name, "countries": listed}


def region_display(region_id: str | None) -> str:
    tree = build_tree()
    if not region_id or region_id == "GLOBAL":
        return tree["global_name"]
    for c in tree["countries"]:
        if c["id"] == region_id:
            return c["name"]
        for s in c["subs"]:
            if s["id"] == region_id:
                return f"{c['name']}·{s['name']}"
    return region_id
