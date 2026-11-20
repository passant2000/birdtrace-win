# -*- coding: utf-8 -*-
"""静态图库站生成(1.0, 2026-11-20 按设计稿重做): 多页纯静态站
—— index 首页(沉浸 Hero) / gallery 鸟种图鉴(筛选胶囊+搜索) /
species 鸟种详情(大图+月份分布+作品) / timeline 时间轴 / regions 地区点位图。

约束(设计规范 §4.1/§4.10): 纯 HTML/CSS/JS 零框架; 可拖到任意静态空间;
手机优先; 深浅跟随系统 + 手动切换; 懒加载 + 固定比例占位防 CLS;
图片两档(256/1280 webp), 原图绝不出库。
隐私: 站点数据只到省市; 地区点位**只落在省会/省域中心**, 不含鸟点坐标与名称。
"""
from __future__ import annotations

import json
from pathlib import Path

from ..i18n import t
from ..paths import assets_dir

# 模板目录: 打包态 assets 在 exe 旁(paths.assets_dir), 开发态=项目 assets
_TMPL = assets_dir() / "templates" / "site"

_MON_EN = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP",
           "OCT", "NOV", "DEC"]


def _zh() -> bool:
    from .. import i18n
    return i18n.lang() != "en"


def _labels() -> dict:
    """模板占位与前端标签(集中一处, 保证真模板里没有硬编码文案)。"""
    zh = _zh()
    d = {
        "photos": t("作品", "works"),
        "unit": t("张", "photos"),
        "groups": t("标签 · 作品集", "Tags · Collections"),
        "species": t("鸟种", "species"),
        "spots": t("鸟点", "hotspots"),
        "years": t("年份", "years"),
        "featured": t("精选鸟种", "Featured species"),
        "recent": t("最近记录", "Recent"),
        "all": t("全部", "All"),
        "gallery": t("鸟种图鉴", "Species Gallery"),
        "timeline": t("时间轴", "Timeline"),
        "regions": t("地区", "Regions"),
        "theme": t("切换深浅主题", "Toggle theme"),
        "search": t("搜索鸟种 / 英文名", "Search species / English"),
        "firstLast": t("首见 / 最近", "First / last"),
        "region": t("地区", "Region"),
        "count": t("拍摄次数", "Photos"),
        "works": t("该鸟种的作品", "Photos of this species"),
        "months": t("拍摄月份", "Months"),
        "all_species": t("全部鸟种", "All species"),
        "emptySpecies": t("还没有已识别的鸟种。", "No identified species yet."),
        "emptySearch": t("没有匹配的鸟种。", "No matching species."),
        "emptyMonths": t("还没有照片记录。", "No photos yet."),
        "privacy": t("仅显示省市 · 不公开精确地点",
                     "Provinces only · no exact locations"),
        "privacyNote": t(
            "地区点点只到省级中心，不包含鸟点名称与精确坐标；"
            "原图不出库，站点只含缩略图与展示图。",
            "Map dots are placed at province level only — no hotspot names "
            "or exact coordinates. Originals never leave the library."),
        "tagline": t("用镜头，记录鸟语花香", "Record · Explore · Share"),
    }
    d["navSpecies"] = d["gallery"]
    d["description"] = t("用镜头记录的鸟类摄影作品集", 
                         "A personal bird photography gallery")
    d["published"] = t("发布于", "Published")
    return d


# ---------------- 地图 SVG ----------------
def _simplify(pts, tol=2.0):
    """按距离抽稀(显示用; 只减点数不改形状层级)。"""
    if len(pts) <= 3:
        return pts
    out = [pts[0]]
    for p in pts[1:]:
        dx, dy = p[0] - out[-1][0], p[1] - out[-1][1]
        if dx * dx + dy * dy >= tol * tol:
            out.append(p)
    if out[-1] != pts[-1]:
        out.append(pts[-1])
    return out


def _map_svg(regions: list[dict]) -> str:
    from .yearbook import (map_box, province_centers, province_rings,
                           region_province_name)
    rid_name = region_province_name()
    centers = province_centers()
    hi = {rid_name.get(r.get("region")) for r in regions} - {None}
    parts = []
    for name, rings in province_rings():
        d = []
        for ring in rings:
            pts = _simplify(ring, 2.0)
            if len(pts) < 3:
                continue
            d.append("M" + " ".join(f"{x:.0f},{y:.0f}" for x, y in pts) + "Z")
        if not d:
            continue
        cls = ' class="hi"' if name in hi else ""
        parts.append(f'<path{cls} d="{"".join(d)}">'
                     f"<title>{name}</title></path>")
    dots = []
    for r in regions:
        c = centers.get(rid_name.get(r.get("region")))
        if not c:
            continue
        dots.append(f'<circle class="dot" cx="{c[0]:.0f}" cy="{c[1]:.0f}" '
                    f'r="7"><title>{r.get("name", "")}: {r.get("n", 0)}'
                    f"</title></circle>")
    w, h = map_box()
    return (f'<svg viewBox="0 0 {w:.0f} {h:.0f}" role="img" '
            f'aria-label="{t("地区分布", "Regional distribution")}">'
            + "".join(parts) + "".join(dots) + "</svg>")


def _region_rows(regions: list[dict]) -> str:
    if not regions:
        return ('<div class="empty">'
                + t("还没有带地区的照片。", "No photos with a region yet.")
                + "</div>")
    out = []
    for r in regions:
        nm = r.get("name") or r.get("region") or ""
        out.append(
            f'<a class="rrow" href="gallery.html?r={nm}">'
            f'<span><b>{r["n"]}</b>　{nm}</span>'
            f'<span class="sub">{t("查看", "View")} →</span></a>')
    return "".join(out)


# ---------------- 时间轴 ----------------
def _timeline_html(months: list[dict]) -> str:
    if not months:
        return ('<div class="empty">'
                + t("还没有照片记录。", "No photos yet.") + "</div>")
    out = []
    for m in reversed(months):
        ym = m["ym"]
        mm = ym[5:7]
        lab = (f"{int(mm)}" + t("月", "")).strip()
        en = _MON_EN[int(mm) - 1] if mm.isdigit() and 1 <= int(mm) <= 12 \
            else ""
        entries = []
        for p in (m.get("photos") or [])[:3]:
            href = (f'species.html?code={p["code"]}'
                    if p.get("code") else "gallery.html")
            entries.append(
                f'<a class="entry" href="{href}"><div class="ph">'
                f'<img loading="lazy" decoding="async" '
                f'src="images/{p["h"]}.256.webp" alt="{p.get("cn", "")}" '
                f'onerror="imgErr(this)"></div>'
                f'<div><b>{p.get("cn", "")}</b>'
                f'<span>{ym}</span></div></a>')
        out.append(
            f'<div class="mgroup"><div class="mlab">{mm}'
            f'<span>{en} {ym[:4]}</span>'
            f'<em>{m["n"]} {t("张", "photos")}</em></div>'
            f'<div class="entries">{"".join(entries)}</div></div>')
    return "".join(out)


# ---------------- 主页 ----------------
def _hero_img(meta: dict) -> str:
    hero = meta.get("hero")
    if hero and hero.get("h"):
        return (f'<img class="bg" src="images/{hero["h"]}.1280.webp" '
                f'alt="" fetchpriority="high" decoding="async">')
    # 无照片: 不虚构图片, 用主题渐变兜底
    return ('<div class="bg" style="background:linear-gradient(140deg,'
            '#20302c 0%,#31473f 55%,#4b6357 100%)"></div>')


def _hero_credit(meta: dict) -> str:
    hero = meta.get("hero")
    if not hero:
        return ""
    bits = [x for x in (hero.get("cn"), hero.get("date")) if x]
    return " · ".join(bits)


def _fill(tmpl: str, mapping: dict) -> str:
    out = tmpl
    for k, v in mapping.items():
        out = out.replace(k, str(v))
    return out


def build_site(lib, dest: Path) -> dict:
    """生成多页静态站。返回统计(verify 用)。"""
    from ..media import ensure_thumbnail
    data = lib.site_data()
    dest = Path(dest)
    img_dir = dest / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    # 需要上站的图片 = 鸟种照片 ∪ 月代表图 ∪ Hero
    need: set[str] = set()
    for sp in data["species"]:
        for ph in sp["photos"]:
            need.add(ph["h"])
    for m in data["months"]:
        for ph in (m.get("photos") or []):
            need.add(ph["h"])
    if data["meta"].get("hero"):
        need.add(data["meta"]["hero"]["h"])
    paths: dict[str, str | None] = {}
    for r in lib.conn.execute("SELECT path, file_hash FROM photos"):
        paths.setdefault(r["file_hash"], r["path"])
    n_thumb = n_web = 0
    for h in sorted(need):
        src = paths.get(h)
        if not src or not Path(src).is_file():
            continue                      # 原图离线: 跳过, 不虚构
        tp = ensure_thumbnail(lib.root, src, h, 256)
        if tp:
            (img_dir / f"{h}.256.webp").write_bytes(Path(tp).read_bytes())
            n_thumb += 1
        tw = ensure_thumbnail(lib.root, src, h, 1280)
        if tw:
            (img_dir / f"{h}.1280.webp").write_bytes(Path(tw).read_bytes())
            n_web += 1

    L = _labels()
    m = data["meta"]
    foot = t(f"© {m['creator']} · 由 BirdTrace 生成",
             f"© {m['creator']} · Generated by BirdTrace") \
        if m.get("creator") else t(
            "由 BirdTrace 生成 · 只含缩略与展示图, 原图绝不出库",
            "Generated by BirdTrace · thumbnails only, originals stay local")

    common = {
        "__LANG__": "zh" if _zh() else "en",
        "__THEME__": L["theme"],
        "__FOOT__": foot,
        "__NAV_SPECIES__": L["gallery"],
        "__NAV_TIME__": L["timeline"],
        "__NAV_REGION__": L["regions"],
    }

    # gallery.js: 数据 + 标签(经典 script, file:// 也能用)
    (dest / "gallery.js").write_text(
        "window.G=" + json.dumps(data, ensure_ascii=False) + ";\n"
        "window.L=" + json.dumps(L, ensure_ascii=False) + ";\n",
        encoding="utf-8")
    # 原 gallery.json 保留(外部消费/调试)
    (dest / "gallery.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")
    for name in ("style.css", "app.js"):
        src = _TMPL / name
        if src.is_file():
            (dest / name).write_bytes(src.read_bytes())

    n_species = len(data["species"])
    pages = {}

    def page(name: str, extra: dict) -> str:
        src = _TMPL / name
        if not src.is_file():
            raise FileNotFoundError(f"缺少站点模板: {src}")
        tmpl = src.read_text(encoding="utf-8")
        html = _fill(tmpl, {**common, **extra})
        (dest / name).write_text(html, encoding="utf-8")
        pages[name] = len(html)
        return html

    page("index.html", {
        "__TITLE__": t("BirdTrace 图库", "BirdTrace Gallery"),
        "__DESC__": L["description"],
        "__TAGLINE__": L["tagline"],
        "__HERO_IMG__": _hero_img(m),
        "__HERO_CREDIT__": _hero_credit(m),
        "__N_PHOTOS__": m["photos"],
        "__N_SPECIES__": m["species"],
        "__N_SPOTS__": m.get("spots", 0),
        "__N_YEARS__": m.get("years", 0),
        "__L_PHOTOS__": L["photos"],
        "__L_SPECIES__": L["species"],
        "__L_SPOTS__": L["spots"],
        "__L_YEARS__": L["years"],
        "__L_FEATURED__": L["featured"],
        "__L_ALL__": L["all"],
        "__L_RECENT__": L["recent"],
        "__L_TIMELINE__": L["timeline"],
    })
    page("gallery.html", {
        "__L_GALLERY__": L["gallery"],
        "__L_SEARCH__": L["search"],
        "__COUNT__": f"{n_species} {L['species']}",
    })
    page("species.html", {"__L_GALLERY__": L["gallery"]})
    page("timeline.html", {
        "__L_TIMELINE__": L["timeline"],
        "__TIMELINE__": _timeline_html(data["months"]),
        "__COUNT__": t(
            f"{m['photos']} 张 · {len(data['months'])} 个月",
            f"{m['photos']} photos · {len(data['months'])} months"),
    })
    page("regions.html", {
        "__L_REGIONS__": L["regions"],
        "__PRIVACY__": L["privacy"],
        "__L_PRIVACY_NOTE__": L["privacyNote"],
        "__MAP_SVG__": _map_svg(data["regions"]),
        "__REGION_ROWS__": _region_rows(data["regions"]),
    })

    return {"species": n_species, "photos": m["photos"],
            "thumb": n_thumb, "web": n_web, "dest": str(dest),
            "pages": len(pages), "months": len(data["months"])}
