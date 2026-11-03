# -*- coding: utf-8 -*-
"""导出SuperPicky名录资产(一次性, 产物进assets/data/sp_regions.json)。

来源: study/SuperPicky/birdid/data/
  - ebird_regions.db  (regions + region_species: 区域→OSEA类别号)
  - bird_reference.sqlite (BirdCountInfo: OSEA类别号→ebird_code)
映射到我们 labels.json 的物种code(=ebird code)。区域id映射:
  国家级两边都是ISO alpha-2(CN/AU/...), 直接同名;
  省州级我们是ISO字母码(CN-SH), eBird用数字码(CN-31)——按英文
  名称+同国家双条件匹配(SHANGHAI/上海 唯一)。
产物: {"regions": {ebird_region: [我们的code, ...]},
       "id_map": {我们的region_id: ebird_region}}
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
SP = Path(r"D:/tmp2/study/SuperPicky")


def norm_name(name: str | None) -> str:
    """英文名归一化(与SP class_mapping.norm_name同法): 只留小写字母。"""
    import re
    return re.sub(r"[^a-z]", "", (name or "").lower())


def main() -> None:
    conn = sqlite3.connect(str(SP / "birdid/data/ebird_regions.db"))
    ref = sqlite3.connect(str(SP / "birdid/data/bird_reference.sqlite"))
    ref.row_factory = sqlite3.Row

    labels = json.loads((PROJ / "assets/data/labels.json").read_text(encoding="utf-8"))
    ours: set[str] = {l["code"] for l in labels}
    by_sci: dict[str, str] = {}
    by_en: dict[str, str] = {}
    for l in labels:
        sci = (l.get("sci") or "").strip().lower()
        if sci:
            by_sci.setdefault(sci, l["code"])
        en = norm_name(l.get("en"))
        if en:
            by_en.setdefault(en, l["code"])

    # 鸟种库类别 → 我们的模型code。三级回退(与SP class_mapping.build_class_map
    # 同思路, 方向相反): eBird代码 → 学名 → 归一化英文名。
    # 背景(2026-11-03): SP鸟种库沿用旧分类(whimbr=中杓鹬), 我们的模型用拆分后
    # 的whimbr5/whimbr3; 只按代码匹配会把中杓鹬等15种从上海名录里丢掉,
    # 导致硬过滤永远排除正确答案(画框也认不出)。
    cid2code: dict[int, str] = {}
    stats = {"code": 0, "sci": 0, "en": 0, "miss": 0}
    misses: list[tuple] = []
    for r in ref.execute(
            "SELECT model_class_id, ebird_code, english_name, scientific_name "
            "FROM BirdCountInfo WHERE model_class_id IS NOT NULL"):
        cid = r["model_class_id"]
        code = r["ebird_code"]
        if code and code in ours:
            cid2code[cid] = code
            stats["code"] += 1
            continue
        sci = (r["scientific_name"] or "").strip().lower()
        if sci and sci in by_sci:
            cid2code[cid] = by_sci[sci]
            stats["sci"] += 1
            continue
        en = norm_name(r["english_name"])
        if en and en in by_en:
            cid2code[cid] = by_en[en]
            stats["en"] += 1
            continue
        stats["miss"] += 1
        if len(misses) < 15:
            misses.append((code, r["english_name"], r["scientific_name"]))
    print(f"类别映射: 代码 {stats['code']} / 学名 {stats['sci']} / 英文名 {stats['en']} "
          f"/ 无法映射 {stats['miss']}")
    if misses:
        print("  无法映射样例:", misses)

    regions: dict[str, set[str]] = {}
    miss = hit = 0
    for reg, cid in conn.execute("SELECT region, class_id FROM region_species"):
        code = cid2code.get(cid)
        if code is None:
            miss += 1
            continue
        regions.setdefault(reg, set()).add(code)
        hit += 1
    print(f"region_species行: 命中我们物种 {hit}, 丢弃 {miss}")
    print(f"eBird区域数: {len(regions)} (有名录)")
    sub = [r for r in regions if "-" in r]
    print(f"  省州级: {len(sub)}, 国家级: {len(regions) - len(sub)}")

    # ---- 区域id映射 ----
    our_regions = json.loads(
        (PROJ / "assets/data/regions.json").read_text(encoding="utf-8"))["regions"]
    id_map: dict[str, str] = {}

    # 国家: ISO alpha-2 直接同名
    ebird_countries = {r for r in regions if "-" not in r}
    for r in our_regions:
        if r["administrativeLevel"] == "country" and r["id"] in ebird_countries:
            id_map[r["id"]] = r["id"]

    # 省州: (国家, 英文名小写) 匹配
    ebird_meta = {code: (parent, name_en) for code, parent, name_en in conn.execute(
        "SELECT code, parent, name_en FROM regions")}
    ebird_sub_by_key = {}
    for code, (parent, name_en) in ebird_meta.items():
        if parent and name_en:
            ebird_sub_by_key[(parent, name_en.strip().lower())] = code
    amb = 0
    for r in our_regions:
        if r["administrativeLevel"] != "admin1":
            continue
        cc = r.get("countryCode")
        en = (r.get("localizedNames", {}).get("en") or r.get("sourceName") or "").strip().lower()
        key = (cc, en)
        if key in ebird_sub_by_key:
            if ebird_sub_by_key[key] in regions:   # 有名录才映射
                id_map[r["id"]] = ebird_sub_by_key[key]
        else:
            amb += 1
    print(f"id_map: {len(id_map)} 条 (未匹配省州 {amb})")
    # 抽查
    for probe in ("CN-SH", "CN-BJ", "AU-NSW", "US-CA", "CN", "AU", "US"):
        print(f"  {probe} -> {id_map.get(probe)}")

    out = {"regions": {k: sorted(v) for k, v in sorted(regions.items())},
           "id_map": id_map}
    dest = PROJ / "assets/data/sp_regions.json"
    dest.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print("saved:", dest, dest.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
