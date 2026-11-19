# -*- coding: utf-8 -*-
"""静态图库站导出(1.0冲刺⑩): 一键生成纯静态站(HTML+图+gallery.json),
可直接拖到 Cloudflare Pages/GitHub Pages。手机优先+深浅跟随系统+
三视图(鸟种/时间轴/地区)+搜索; 图片两档(thumb256缩略管线复用/
web1280展示), file_hash 命名天然增量。隐私拍板: 鸟点名/坐标绝不进
站点数据(只到省市); 原图绝不出库。版权=effective_copyright.creator。
tags/collections 字段已预留(⑭⑮筛选视图1.0前补)。"""
from __future__ import annotations

import json
from pathlib import Path

from ..i18n import t

_TMPL_PATH = Path(__file__).resolve().parents[2] / "assets" / "templates" / "site_index.html"


def i18n_cur_zh() -> bool:
    from .. import i18n
    return i18n.lang() != "en"

# 模板缺失时的自愈底稿(全英文占位, 文案由 build_site 按界面语言注入;
# 底稿不含硬编码文案)。完整样式版=打包内 assets/templates/site_index.html
_FALLBACK_TMPL = """<!DOCTYPE html>
<html lang="__LANG__"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title><style>:root{--bg:#F7F8FA;--card:#fff;--tx:#20252B;--tx2:#68727D;--line:#E7EBEF;--ac:#527C70}
@media(prefers-color-scheme:dark){:root{--bg:#111820;--card:#1B2630;--tx:#F3F5F7;--tx2:#A6B0BA;--line:#303C47;--ac:#83B5A2}}
*{box-sizing:border-box;margin:0;padding:0}body{background:var(--bg);color:var(--tx);font:15px/1.5 "Segoe UI","Microsoft YaHei",sans-serif}
header{padding:48px 20px 28px;text-align:center}header h1{font-size:30px}.sub{color:var(--tx2);font-size:13px;margin-top:6px}
.stats{display:flex;gap:28px;justify-content:center;margin:18px 0 8px;flex-wrap:wrap}.stats b{font-size:26px;display:block}.stats span{color:var(--tx2);font-size:12px}
nav{display:flex;gap:8px;justify-content:center;flex-wrap:wrap;padding:12px}nav button{border:1px solid var(--line);background:var(--card);color:var(--tx);padding:7px 16px;border-radius:999px;cursor:pointer}
nav button.on{background:var(--ac);color:#fff;border-color:var(--ac)}#q{display:block;margin:10px auto;max-width:320px;width:90%;padding:9px 14px;border:1px solid var(--line);border-radius:999px;background:var(--card);color:var(--tx)}
main{max-width:1180px;margin:0 auto;padding:16px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px}
.card{background:var(--card);border-radius:12px;overflow:hidden;border:1px solid var(--line)}.card img{width:100%;aspect-ratio:1;object-fit:cover;display:block;background:var(--line)}
.card .cap{padding:8px 10px}.card .cap b{font-size:14px;display:block}.card .cap span{color:var(--tx2);font-size:12px}
.chip{display:inline-block;border:1px solid var(--line);background:var(--card);color:var(--tx);border-radius:999px;padding:8px 16px;margin:6px 4px;cursor:pointer;font-size:14px}.chip:hover{border-color:var(--ac)}.chip.on{background:var(--ac);color:#fff;border-color:var(--ac)}.ah{margin:20px 4px 6px;color:var(--tx2);font-size:13px;font-weight:600}
.tl{border-left:2px solid var(--line);margin-left:10px;padding-left:18px}.tl .item{margin:0 0 14px}.tl .item b{font-size:14px}.tl .item span{color:var(--tx2);font-size:12px;margin-left:8px}
.empty{text-align:center;color:var(--tx2);padding:48px 0}footer{text-align:center;color:var(--tx2);font-size:12px;padding:28px 12px}</style></head>
<body><header><h1>__TITLE__</h1><div class="sub">__SUB__</div>
<div class="stats"><div><b>__NP__</b><span>__L_PHOTOS__</span></div><div><b>__NS__</b><span>__L_SPECIES__</span></div><div><b>__NM__</b><span>__L_MONTHS__</span></div></div></header>
<nav id="tabs"><button data-v="species" class="on">__L_TAB_SPECIES__</button><button data-v="time">__L_TAB_TIME__</button><button data-v="region">__L_TAB_REGION__</button><button data-v="albums" id="tab-albums">__L_TAB_ALBUMS__</button></nav>
<input id="q" placeholder="__L_SEARCH__"><main id="view"></main><footer>__FOOT__</footer>
<script>const G=__G__;const im=(h,s)=>`images/${h}.${s}.webp`;
function esc(s){return (s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
let view="species";function render(){const q=(document.getElementById("q").value||"").toLowerCase().trim();const v=document.getElementById("view");
if(view==="species"){const list=G.species.filter(s=>!q||(s.cn+s.en+s.code).toLowerCase().includes(q));
v.innerHTML=list.length?`<div class="grid">`+list.map(s=>`<div class="card"><img loading="lazy" src="${im(s.best,256)}" alt="${esc(s.cn)}"><div class="cap"><b>${esc(s.cn)}</b><span>${esc(s.en)} · ${s.count} __L_N_PHOTOS__</span></div></div>`).join("")+`</div>`:`<div class="empty">__EMPTY__</div>`}
else if(view==="time"){v.innerHTML=`<div class="tl">`+G.months.map(m=>`<div class="item"><b>${esc(m.ym)}</b><span>${m.n} __L_N_PHOTOS__</span></div>`).join("")+`</div>`}
else if(view==="region"){v.innerHTML=`<div class="grid">`+G.regions.map(r=>`<div class="card"><div class="cap" style="padding:22px 14px"><b>${esc(r.region||"")}</b><span>${r.n} __L_N_PHOTOS__</span></div></div>`).join("")+`</div>`}
else if(view==="albums"){(function(v){const secs=[];const sec=(tt,arr)=>{if(arr&&arr.length)secs.push(`<div class="ah">${esc(tt)}</div>`+arr.map(a=>`<div class="chip" data-t="${esc(a.name)}">${esc(a.name)} · ${a.photos.length}</div>`).join(""))};sec(__L_TAGS__,G.tags);sec(__L_COLLECTIONS__,G.collections);v.innerHTML=secs.length?secs.join(""):`<div class="empty">__EMPTY2__</div>`;v.querySelectorAll(".chip").forEach(c=>c.addEventListener("click",()=>{const name=c.dataset.t;const all=[...(G.tags||[]),...(G.collections||[])];const grp=all.find(x=>x.name===name);if(!grp)return;v.innerHTML=`<div class="chip on" id="back-albums">‹ __L_TAB_ALBUMS__</div>`+`<div class="grid">`+grp.photos.map(p=>`<div class="card"><img loading="lazy" src="${im(p.h,256)}"><div class="cap"><b>${esc(p.cn||"")}</b></div></div>`).join("")+`</div>`;document.getElementById("back-albums").addEventListener("click",render)}))})(v)}
if(!(G.tags&&G.tags.length)&&!(G.collections&&G.collections.length)){const tb=document.getElementById("tab-albums");if(tb)tb.style.display="none"}
document.getElementById("tabs").addEventListener("click",e=>{if(e.target.dataset.v){view=e.target.dataset.v;document.querySelectorAll("#tabs button").forEach(b=>b.classList.toggle("on",b===e.target));render()}});
document.getElementById("q").addEventListener("input",render);render();</script></body></html>
"""


def _template() -> str:
    """HTML 模板: 优先 assets/templates/site_index.html(可自定义样式),
    缺失时用内置英文占位底稿并自动写出(自愈, fresh clone 也有)。"""
    if _TMPL_PATH.is_file():
        try:
            return _TMPL_PATH.read_text(encoding="utf-8")
        except OSError:
            pass
    try:
        _TMPL_PATH.parent.mkdir(parents=True, exist_ok=True)
        _TMPL_PATH.write_text(_FALLBACK_TMPL, encoding="utf-8")
    except OSError:
        pass
    return _FALLBACK_TMPL



def build_site(lib, dest: Path) -> dict:
    """生成站点 → {species, photos_thumb, photos_web, months, regions}。
    纯静态零依赖; 生成失败不碰已有文件(目标目录由调用方选)。"""
    from ..media import ensure_thumbnail
    data = lib.site_data()
    dest = Path(dest)
    img_dir = dest / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    n_thumb = n_web = 0
    seen: set[str] = set()
    paths: dict[str, str | None] = {}   # file_hash → 主文件路径
    for r in lib.conn.execute("SELECT path, file_hash FROM photos"):
        paths.setdefault(r["file_hash"], r["path"])
    for sp in data["species"]:
        for ph in sp["photos"]:
            h = ph["h"]
            if h in seen:
                continue
            seen.add(h)
            src = paths.get(h)
            if not src or not Path(src).is_file():
                continue   # 原图离线: 跳过, 不虚构
            tp = ensure_thumbnail(lib.root, src, h, 256)
            if tp:
                (img_dir / f"{h}.256.webp").write_bytes(Path(tp).read_bytes())
                n_thumb += 1
            tw = ensure_thumbnail(lib.root, src, h, 1280)
            if tw:
                (img_dir / f"{h}.1280.webp").write_bytes(Path(tw).read_bytes())
                n_web += 1
    gpath = dest / "gallery.json"
    gpath.write_text(json.dumps(data, ensure_ascii=False),
                     encoding="utf-8")
    m = data["meta"]
    foot = t(f"由 BirdTrace 生成 · 只含缩略与展示图, 原图绝不出库",
             "Generated by BirdTrace · thumbnails/web sizes only, "
             "originals never leave the library")
    if m.get("creator"):
        foot = t(f"© {m['creator']} · 由 BirdTrace 生成",
                 f"© {m['creator']} · Generated by BirdTrace")
    sub = t("记录 · 发现 · 分享", "Record · Explore · Share")
    html = (_template()
            .replace("__G__", json.dumps(data, ensure_ascii=False))
            .replace("__TITLE__", t("BirdTrace 图库", "BirdTrace Gallery"))
            .replace("__EMPTY__", t("没有匹配的鸟种", "No matching species"))
            .replace("__LANG__", "zh" if i18n_cur_zh() else "en")
            .replace("__L_PHOTOS__", t("作品", "Photos"))
            .replace("__L_SPECIES__", t("鸟种", "Species"))
            .replace("__L_MONTHS__", t("月份", "Months"))
            .replace("__L_TAB_SPECIES__", t("鸟种", "Species"))
            .replace("__L_TAB_TIME__", t("时间轴", "Timeline"))
            .replace("__L_TAB_REGION__", t("地区", "Regions"))
            .replace("__L_TAB_ALBUMS__", t("标签 · 作品集",
                                           "Tags · Collections"))
            .replace("__L_TAGS__", "'" + t("标签", "Tags") + "'")
            .replace("__L_COLLECTIONS__", "'" + t("作品集", "Collections")
                     + "'")
            .replace("__EMPTY2__", t("还没有标签或作品集",
                                     "No tags or collections yet"))
            .replace("__L_SEARCH__", t("搜索鸟种名 / 拼音缩写",
                                       "Search species / pinyin"))
            .replace("__L_N_PHOTOS__", t("张", "photos"))
            .replace("__SUB__", sub)
            .replace("__NP__", str(m["photos"]))
            .replace("__NS__", str(m["species"]))
            .replace("__NM__", str(len(data["months"])))
            .replace("__FOOT__", foot))
    (dest / "index.html").write_text(html, encoding="utf-8")
    return {"species": len(data["species"]), "photos": m["photos"],
            "thumb": n_thumb, "web": n_web, "dest": str(dest)}
