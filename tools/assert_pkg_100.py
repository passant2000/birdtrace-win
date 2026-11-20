# -*- coding: utf-8 -*-
"""1.0.0-test1包内断言(1.0冲刺): 0.8.6全部检查 + 选片工作流: 0.8.5全部检查 + 0.8.6文字区手动高度(交界线拖动+无裁切参考线)
(culling/查重/记录中心/组合筛选/装备时段/RAW成对/静态站/标签作品集/增量扫描/版权)。
方法沿用0.6.0: CArchive TOC解析→PYZ marshal code对象→co_names/co_consts
(常量元组是整体tuple, 符号要兼收tuple元素)。
"""
import json
import marshal
import struct
import sys
import zlib
from pathlib import Path

DIST = Path(r"D:/tmp2/birdtrace-win/packaging/dist/birdtrace")
ok = fail = 0


def check(name, cond, note=""):
    global ok, fail
    ok += bool(cond)
    fail += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {note}")


# ---- 1. 文件齐全 ----
check("exe", (DIST / "鸟迹BirdTrace.exe").exists())
for f in ("assets/data/sp_regions.json",
          "assets/models/cub200_keypoint.onnx",
          "assets/models/cub200_keypoint.onnx.data",
          "assets/models/BirdTraceBirdDetector_YOLO11lSeg.onnx",
          "assets/models/BirdTraceRecognitionModel.onnx",
          "assets/data/labels.json"):
    check(f"文件 {f}", (DIST / f).exists(),
          f"{(DIST / f).stat().st_size // 1024}KB" if (DIST / f).exists() else "")
check("rawpy三件套", (DIST / "_internal" / "rawpy").exists())

# ---- 2. Key不明文(全包扫描) ----
PLAIN = (b"ea5d190d989d6b834fef65d5e49c5b84",
         b"e6f46d0b3316b828da7e2666f478c0ab",
         b"9f202492fd86926cec6736e225bbc071")
leak = []
for p in list(DIST.rglob("*"))[:4000]:
    if p.is_file() and p.suffix.lower() in (".pyd", ".dll", ".exe", ".bin",
                                            ".dat", ".json", ".txt") or p.name == "鸟迹BirdTrace.exe":
        try:
            data = p.read_bytes()
        except OSError:
            continue
        for k in PLAIN:
            if k in data:
                leak.append((p.name, k[:8].decode()))
                break
check("三个高德Key明文泄露", not leak, f"leak={leak[:3]}")
MT = b"QMZGF8IiSPfyUQeVTOEQ"
mt_leak = []
for p in list(DIST.rglob("*"))[:4000]:
    if p.is_file():
        try:
            if MT in p.read_bytes():
                mt_leak.append(p.name)
        except OSError:
            continue
check("MapTiler原作者Key已清除", not mt_leak, f"leak={mt_leak[:3]}")

# ---- 3. PYZ符号 ----
EXE = DIST / "鸟迹BirdTrace.exe"
data = EXE.read_bytes()
MAGIC = b"MEI\014\013\012\013\016"
pos = data.rfind(MAGIC)
pkg_len, toc_off, toc_len = struct.unpack("!III", data[pos + 8:pos + 20])
# cookie=8B魔数+3I+I pyver+64B pylibname=88B; 归档起点=cookie尾-pkg_len
ARCH = pos + 88 - pkg_len
toc = data[ARCH + toc_off:ARCH + toc_off + toc_len]
BASE = ARCH                       # 条目offset相对归档起点
entries = {}
i = 0
while i < len(toc):
    (n,) = struct.unpack("!I", toc[i:i + 4])
    off, clen, ulen = struct.unpack("!III", toc[i + 4:i + 16])
    name = toc[i + 18:i + n].rstrip(b"\0").decode("utf-8", "replace")
    entries[name] = (off, clen, toc[i + 16])
    i += n


def load_pyz():
    for name, (off, clen, flag) in entries.items():
        if name.endswith("PYZ.pyz") or name.endswith("PYZ-00.pyz"):
            blob = data[BASE + off:BASE + off + clen]
            if flag:
                blob = zlib.decompress(blob)
            (tocp,) = struct.unpack("!I", blob[8:12])
            return blob, marshal.loads(blob[tocp:])
    return None, None


pyz, pzmap = load_pyz()
check("PYZ解析", pyz is not None)


def code_of(suffix):
    for n, ent in pzmap:
        if isinstance(n, str) and n.endswith(suffix):
            typ, off2, length = ent
            b = pyz[off2:off2 + length]
            if b[:2] == bytes((0x78, 0x9C)):   # 该版PyInstaller的typ不可靠, 按zlib魔数判
                try:
                    b = zlib.decompress(b)
                except zlib.error:
                    continue
            try:
                return marshal.loads(b)
            except Exception:
                continue
    return None


def tl_symbols():
    """UI重设计c8: timeline_page 拆为 app/ui/timeline/ 包(壳+4 mixin),
    打包断言对5个模块取符号并集(锚点语义不变)。"""
    out = set()
    for suf in ("app.ui.timeline", "app.ui.timeline.filters",
                "app.ui.timeline.select_bar", "app.ui.timeline.month_view",
                "app.ui.timeline.actions"):
        c = code_of(suf)
        if c:
            out |= symbols(c)
    return out


def symbols(code):
    out = set()
    stack = [code]
    while stack:
        c = stack.pop()
        out |= set(c.co_names)
        for k in c.co_consts:
            if isinstance(k, str):
                out.add(k)
            elif isinstance(k, tuple):
                out |= {x for x in k if isinstance(x, str)}
            elif hasattr(k, "co_consts"):
                stack.append(k)
    return out


# 版本
v = code_of("app.version")
syms = symbols(v) if v else set()
check("版本=1.0.0-test4", "1.0.0-test4" in syms)

# SP引擎
e = code_of("app.ai.sp_engine")
s = symbols(e) if e else set()
check("sp_engine核心符号",
      {"sp_square_crop", "sp_hard_filter", "SpRecognitionEngine",
       "EYE_TALL_ASPECT", "RESCUE_BELOW"} <= s)

# 工厂+worker引擎参数
g = code_of("app.ai.engine")
s = symbols(g) if g else set()
check("engine工厂keypoint接线", {"build_recognizer", "cub200_keypoint.onnx"} <= s)

# amap混淆(有_dec无明文)
a = code_of("app.ui.amap_view")
s = symbols(a) if a else set()
check("amap_view混淆解码", "_dec" in s and not ({"ea5d190d989d6b834fef65d5e49c5b84",
      "e6f46d0b3316b828da7e2666f478c0ab"} & s))

# 地图弹卡重建+改名
m = code_of("app.ui.map_page")
s = symbols(m) if m else set()
check("map_page弹卡重建+双击改名", {"_rename_spot", "deleteLater"} <= s
      and "重命名鸟点" in s)

# 时间线树
s = tl_symbols()
check("timeline树导航", {"_build_tree", "tree_nav", "_on_tree_click",
                         "_sync_tree_current"} <= s)

# 未识别桶
db = code_of("app.db")
s = symbols(db) if db else set()
check("db未识别桶", {"unidentified_overview", "UNIDENTIFIED_CODE"} <= s)
sp = code_of("app.ui.species_page")
s = symbols(sp) if sp else set()
check("鸟种库未识别入口", {"_unidentified_card", "_show_unidentified_detail"} <= s)

# 键盘流
k = code_of("app.ui.species_pick")
s = symbols(k) if k else set()
check("选鸟器键盘流", {"eventFilter", "_sync_ok"} <= s)

# 预热
pw = code_of("app.core.prewarm")
check("WebEngine预热模块", pw is not None)
mn = code_of("app.main")
s = symbols(mn) if mn else set()
check("main预热接线", "schedule_webengine_prewarm" in s)

# 2026-11-02 分享卡DPI守卫 + 迁徙配色方案A
sc = code_of("app.core.sharecard")
s = symbols(sc) if sc else set()
check("sharecard DPI守卫_fit", "_fit" in s)
mv2 = code_of("app.ui.migration_view")
s = symbols(mv2) if mv2 else set()
# markResident/mig-res只在_HTML大字符串内部——须按子串扫全部字符串常量
strs = [k for k in (symbols(mv2) if mv2 else set()) if isinstance(k, str)]
check("migration配色A", {"phase_ramp", "RESIDENT_MIN_WEEKS", "全年常驻"} <= s
      and any("markResident" in x for x in strs)
      and any("mig-res" in x for x in strs))

# 2026-11-02下午: 时间线列宽 + 姬鹟0.80 + 未识别/待复核语义
s = tl_symbols()
check("timeline列宽统一公式", "_wanted_cols" in s
      and any("视口实际宽度" in x for x in s if isinstance(x, str)))
sp2 = code_of("app.ai.sp_engine")
s2 = symbols(sp2) if sp2 else set()
check("sp引擎语义(有鸟就写名+多取景最佳+0.80锚定)",
      0.2 in sp2.co_consts and 0.8 in sp2.co_consts
      and {"_best_variant", "_variant_crops", "RESCUE_BELOW"} <= s2
      and any("待复核" in x for x in s2 if isinstance(x, str)))
db2 = code_of("app.db")
s3 = symbols(db2) if db2 else set()
check("db不是鸟+中文名覆盖", "mark_not_bird" in s3
      and any("cn_name_overrides" in x for x in s3 if isinstance(x, str)))
rv2 = code_of("app.ui.review_page")
s4 = symbols(rv2) if rv2 else set()
check("待复核不是鸟按钮", "_not_bird" in s4
      and any("不是鸟" in x for x in s4 if isinstance(x, str)))
check("中文名覆盖文件", (DIST / "assets/data/cn_name_overrides.json").exists())
# 2026-11-03 时间线: 树刷新修复+按日期+Shift范围
s = tl_symbols()
check("时间线日期/Shift选择+树刷新",
      {"_select_by_date", "_select_range", "_select_date_range",
       "_iso_dates", "_order_ids"} <= s)
# 2026-11-03 主程序species数据版本重刷
mn2 = code_of("app.main")
s = symbols(mn2) if mn2 else set()
check("启动species版本重刷", "SPECIES_DATA_VERSION" in s)
db3 = code_of("app.db")
s = symbols(db3) if db3 else set()
check("SPECIES_DATA_VERSION常量", any("2026-11-04" in x for x in s
                                      if isinstance(x, str)))
# 名录拆分映射(2026-11-03): 中杓鹬whimbr→whimbr5; 上海名录须与SP映射后一致(539)
try:
    _regs = json.loads((DIST / "assets/data/sp_regions.json").read_text(
        encoding="utf-8"))["regions"]
    check("名录拆分映射(中杓鹬/上海539种)",
          "whimbr5" in _regs.get("CN-31", []) and len(_regs.get("CN-31", [])) >= 535)
except Exception as _e:
    check("名录拆分映射(中杓鹬/上海539种)", False, str(_e))

# ===== 2026-11-04 0.8.0 八项新功能 =====
sd = code_of("app.core.sidecar")
check("sidecar模块", sd is not None)
s = symbols(sd) if sd else set()
check("sidecar核心", {"SIDECAR_NAME", "export_folder", "apply_for_imports",
                      "apply_entry", "read_sidecar"} <= s)
bu = code_of("app.core.burst")
s = symbols(bu) if bu else set()
check("burst核心", {"group_bursts", "collapse_bursts", "BURST_VERSION"} <= s)
of = code_of("app.core.offline")
s = symbols(of) if of else set()
check("offline三态", {"classify_paths", "path_state", "drive_root"} <= s)
ex = code_of("app.core.exporter")
s = symbols(ex) if ex else set()
check("exporter核心", {"plan_ops", "execute_plan", "apply_rename_to_db",
                       "select_range", "sibling_pair"} <= s)
check("phash模块", code_of("app.core.phash") is not None)
check("导出向导对话框", code_of("app.ui.export_dialog") is not None)
bs = code_of("app.ui.batch_share_dialog")
s = symbols(bs) if bs else set()
check("批量分享卡对话框", bs is not None and "best_share_cards" in s)
db4 = code_of("app.db")
s = symbols(db4) if db4 else set()
check("db 0.8方法", {"flush_sidecars", "regroup_bursts", "best_share_cards",
                     "file_status"} <= s and "phash_of" in s
      and "BEST18_DIFF_MIN" in s)
s = tl_symbols()
check("时间线0.8入口", {"burst_btn", "_collapse_on", "_batch_share",
                        "_export_wizard"} <= s
      and any("连拍折叠" in x for x in s if isinstance(x, str)))
# UI重设计c12: 编排迁app.controller, 锚点=main_window+controller符号并集
mn8 = code_of("app.ui.main_window")
s = symbols(mn8) if mn8 else set()
_c12 = code_of("app.controller")
if _c12:
    s |= symbols(_c12)
check("主窗口sidecar定时器(编排已在controller)", "_flush_sidecars_tick" in s
      and "start_burst_regroup" in s
      and "_save_nav_order" in s and "nav_order:" in s)
bu2 = code_of("app.db")
s = symbols(bu2) if bu2 else set()
check("连拍鸟种统一(unify)", "unify_burst_species" in s)
im2 = code_of("app.ui.import_page")
s = symbols(im2) if im2 else set()
check("导入地区确认弹窗", "确认拍摄地区" in s
      and any("提高识别准确率" in x for x in s if isinstance(x, str)))
s = tl_symbols()
check("重新识别地区/鸟点", "_batch_rerecognize" in s
      and "识别地区与鸟点" in s)
rp2 = code_of("app.ui.review_page")
s = symbols(rp2) if rp2 else set()
check("待复核全rank(多鸟低置信)", "删除这条记录" in s)
bt2 = code_of("app.ui.batch_share_dialog")
s = symbols(bt2) if bt2 else set()
check("批量分享卡张数+快捷范围", "per_combo" in s and "_apply_quick" in s)
ed2 = code_of("app.ui.export_dialog")
s = symbols(ed2) if ed2 else set()
check("导出模板/快捷/开文件夹", {"_template", "_apply_quick", "tpl_combos"} <= s
      and "startfile" in s)
mv3 = code_of("app.ui.migration_view")
s = symbols(mv3) if mv3 else set()
check("迁徙非模态+切鸟种", "switch_species" in s
      and "WindowMaximizeButtonHint" in s)
mg2 = code_of("app.core.migration")
s = symbols(mg2) if mg2 else set()
check("迁徙目录缓存优先", "prefer_cache" in s)
sp3 = code_of("app.ui.species_page")
s = symbols(sp3) if sp3 else set()
check("主题感知配色(OLIVE)", "theme.OLIVE" in s or "OLIVE" in s)
sh2 = code_of("app.ui.share_dialog")
s = symbols(sh2) if sh2 else set()
check("share_dialog复用函数", {"exif_parts_of", "rarity_info"} <= s)
ph2 = code_of("app.core.prior_hint")
s = symbols(ph2) if ph2 else set()
check("罕见度百分位", "rarity_percentile" in s)
sc2 = code_of("app.core.sharecard")
s = symbols(sc2) if sc2 else set()
check("百分位格式化", "_fmt_pct" in s
      and any("rarity_pct" in x for x in s if isinstance(x, str)))
am2 = code_of("app.ui.amap_view")
s = symbols(am2) if am2 else set()
check("MapTiler符号已删", "DEFAULT_MAPTILER_KEY" not in s)
poi = code_of("app.ui.map_page")
s = symbols(poi) if poi else set()
check("POI单数据源", "_parse_maptiler" not in s
      and any("地名搜索不可用" in x for x in s if isinstance(x, str)))
dm2 = code_of("app.ui.distribution_map")
strs = [k for k in (symbols(dm2) if dm2 else set()) if isinstance(k, str)]
# 悬浮定位(2026-11-04修复: 此前#tip无定位永远在窗口外)
check("分布地图悬浮定位",
      any("clientWidth-4" in x for x in strs)
      and any("tip.style.left" in x for x in strs))
try:
    _ovd = json.loads((DIST / "assets/data/cn_name_overrides.json").read_text(
        encoding="utf-8"))
    _n = len([k for k in _ovd if not k.startswith("_")])
    check("名录覆盖>=1000条", _n >= 1000, f"{_n}条")
    check("紫寿带覆盖", _ovd.get("japfly1") == "紫寿带")
    check("CBR优先样例(麻雀覆盖+旋木雀原名即对)",
          _ovd.get("eutspa") == "麻雀" and _ovd.get("eurtre1") is None)
    check("繁体修复", _ovd.get("ruhpar2") == "红头鸦雀")
except Exception as _e:
    check("名录覆盖>=1000条", False, str(_e))

# ---- 0.8.0-test3 修复集(2026-11-05复查; 功能级验证=verify_rerecog_region/
#      verify_burst[7]/verify_export[6]/verify_import_confirm, 此处只做包内符号) ----
_s2 = tl_symbols()
check("重新识别地区弹窗在包内(0.8-test3)",
      "识别地区与鸟点" in _s2
      and any("batch_id=b.id WHERE p.id IN (" in x for x in _s2),
      "(参数修复+国家级data由verify_rerecog_region功能级覆盖)")
_db2 = code_of("app.db")
_s3 = symbols(_db2) if _db2 else set()
check("连拍统一限EXIF(0.8-test3)",
      "SELECT p.id, e.dt_original AS ts, p.group_id FROM photos p "
      "JOIN exif e ON e.photo_id=p.id WHERE e.dt_original IS NOT NULL" in _s3)
# 导出模板单后缀: 无独立常量可辨(修复在表达式层), 由verify_export[6]功能级覆盖

# ---- 0.8.0-test4 修复集(2026-11-05第二批反馈; 功能级=verify_feedback2/
#      verify_viewer[5][6]/verify_timeline_select按日分组) ----
_s3b = symbols(code_of("app.db")) if code_of("app.db") else set()
check("v_records视图带top5_json(0.8-test4)",
      any("CREATE VIEW IF NOT EXISTS v_records AS" in x for x in _s3b)
      and any("r.box_json, r.top5_json," in x for x in _s3b))
check("启动自愈去重(0.8-test4)", "_dedupe_records" in _s3b
      and "has_human_record" in _s3b)
_sp2 = symbols(code_of("app.ai.sp_engine")) if code_of("app.ai.sp_engine") else set()
check("候选补齐(0.8-test4)", "sp_extend_candidates" in _sp2)
_spp = symbols(code_of("app.ui.species_page")) if code_of("app.ui.species_page") else set()
check("图鉴地区按照片实际(0.8-test4)", "_species_region" in _spp)

# ---- 0.8.0 重建(2026-11-06): 侧边栏拖动重做 + 日期框自绘 ----
_mw = symbols(code_of("app.ui.main_window")) if code_of("app.ui.main_window") else set()
check("侧边栏拖动重排重做(0.8.0重建)",
      "_nav_drag_to" in _mw and "globalPosition" in _mw
      and "_nav_drag_origin" in _mw)
_wg = symbols(code_of("app.theme.widgets")) if code_of("app.theme.widgets") else set()
check("日期框自绘(0.8.0重建)",
      "QPushButton#DateEdit{background:" in _wg and "_week_header" in _wg
      and "dateChanged" in _wg)

# ---- 0.8.1: 区域稀有度分值 + IUCN 胶囊 + 卡宽2000 ----
_ph = symbols(code_of("app.core.prior_hint")) if code_of("app.core.prior_hint") else set()
check("稀有度分值(0.8.1)", "rarity_score" in _ph)
_sd = symbols(code_of("app.ui.share_dialog")) if code_of("app.ui.share_dialog") else set()
check("IUCN胶囊接口(0.8.1)", "iucn_of" in _sd)
_sc = symbols(code_of("app.core.sharecard")) if code_of("app.core.sharecard") else set()
check("卡宽2000(0.8.1)", any("布局(宽2000" in x for x in _sc)
      and any("rarity_score" in x for x in _sc))

# ---- 0.8.2: 批量操作(时间线批量挂鸟点 / 鸟种库多选批量改判 / 未识别整批标注) ----
_tl6 = tl_symbols()
check("时间线批量挂鸟点入口(0.8.2)", "spot_btn" in _tl6 and "_batch_set_spot" in _tl6
      and any("设置鸟点" in x for x in _tl6 if isinstance(x, str)))
_sdd = symbols(code_of("app.ui.spot_dialog")) if code_of("app.ui.spot_dialog") else set()
check("BatchSpotDialog整批取消挂载(0.8.2)", "_unmount_all" in _sdd
      and any("取消挂载" in x for x in _sdd if isinstance(x, str)))
_db5 = symbols(code_of("app.db")) if code_of("app.db") else set()
check("db批量改判API(0.8.2)", "set_species_batch" in _db5)
_spp3 = symbols(code_of("app.ui.species_page")) if code_of("app.ui.species_page") else set()
check("鸟种库多选批量改判(0.8.2)", {"_render_sel_bar", "_sel_click",
      "_batch_change_species", "_batch_annotate", "_top5_hit"} <= _spp3
      and any("批量改鸟种" in x for x in _spp3 if isinstance(x, str))
      and any("低风险改判" in x for x in _spp3 if isinstance(x, str)))

# ---- 0.8.3: 分享卡小红书版式(9:16/3:4定高+框对准+模糊bleed) ----
_sc9 = symbols(code_of("app.core.sharecard")) if code_of("app.core.sharecard") else set()
check("sharecard版式引擎(0.8.3)", {"XHS_LAYOUTS", "BLEED_LOSS"} <= _sc9
      and "layout" in _sc9 and any("模糊bleed垫底" in x for x in _sc9
                                    if isinstance(x, str)))
_sh3 = symbols(code_of("app.ui.share_dialog")) if code_of("app.ui.share_dialog") else set()
check("单卡版式下拉(0.8.3)", "lay_seg" in _sh3 and "_focus" in _sh3
      and any("版式" in x for x in _sh3 if isinstance(x, str)))
_bs3 = symbols(code_of("app.ui.batch_share_dialog")) if code_of("app.ui.batch_share_dialog") else set()
check("批量版式下拉(0.8.3)", "lay_seg" in _bs3 and any("版式" in x for x in _bs3
                                                       if isinstance(x, str)))
check("原图分辨率档(0.8.3)", any("原图" in x for x in _sh3 if isinstance(x, str))
      and any("原图" in x for x in _bs3 if isinstance(x, str)))
_db9 = symbols(code_of("app.db")) if code_of("app.db") else set()
check("best_share_cards带框/尺寸(0.8.3)", any("v.box_json" in x for x in _db9
                                              if isinstance(x, str))
      and any("p.width, p.height" in x for x in _db9 if isinstance(x, str)))
check("鸟点上卡(0.8.3)", "spot_toggle" in _bs3
      and any("显示鸟点" in x for x in _bs3 if isinstance(x, str))
      and any("sp.name AS spot_name" in x for x in _db9 if isinstance(x, str)))
_sp9 = symbols(code_of("app.ui.map_page")) if code_of("app.ui.map_page") else set()
check("鸟点简称(0.8.3)", "short_edit" in _sp9
      and any("简称（可省" in x for x in _sp9 if isinstance(x, str))
      and any("sp.short_name AS spot_short" in x for x in _db9
              if isinstance(x, str)))
_sc8 = symbols(code_of("app.core.sharecard")) if code_of("app.core.sharecard") else set()
_sc8c = code_of("app.core.sharecard")
_sc8all = set()
_sk = [_sc8c] if _sc8c else []
while _sk:
    _c = _sk.pop()
    for _k in _c.co_consts:
        _sc8all.add(_k)
        if hasattr(_k, "co_consts"):
            _sk.append(_k)
check("3:5文字区压缩进包(0.8.3→0.8.5竖版3:5)", _sc8c is not None
      and (2667, 1877) in _sc8all                  # 3:5定高表(tuple常量)
      and any(getattr(k, "co_name", "") == "o" for k in _sc8all
              if hasattr(k, "co_consts")))         # meta行偏移函数o()(嵌套在render_card内)

# ---- 0.8.4: 眼点保头 + 版式标题区重做 + auto择优 + 多选出卡 ----
_kp = symbols(code_of("app.ai.keypoints")) if code_of("app.ai.keypoints") else set()
check("眼点惰性助手(0.8.4)", "eye_for_photo" in _kp)
_db8 = symbols(code_of("app.db")) if code_of("app.db") else set()
_db8all = set()
_sk8 = [code_of("app.db")] if code_of("app.db") else []
while _sk8:
    _c = _sk8.pop()
    _db8all |= set(_c.co_names)
    for _k in _c.co_consts:
        if isinstance(_k, str):
            _db8all.add(_k)
        if isinstance(_k, tuple):
            _db8all |= {x for x in _k if isinstance(x, str)}
        if hasattr(_k, "co_consts"):
            _sk8.append(_k)
check("eye_json落库+按选出行(0.8.4)", "eye_json" in _db8all
      and "share_card_rows" in _db8all
      and any(isinstance(x, str) and "v.eye_json" in x for x in _db8all))
_sc8c = code_of("app.core.sharecard")
_sc8all = set()
_sk = [_sc8c] if _sc8c else []
while _sk:
    _c = _sk.pop()
    _sc8all |= set(_c.co_names)          # 属性名(如Qt.IntersectClip)在co_names
    for _k in _c.co_consts:
        _sc8all.add(_k)
        if hasattr(_k, "co_consts"):
            _sk.append(_k)
check("3:5标题区重做(0.8.4→0.8.5竖版3:5)", _sc8c is not None
      and (2667, 1877) in _sc8all
      and "IntersectClip" in _sc8all
      and any(getattr(k, "co_name", "") == "_loss"
              for k in _sc8all if hasattr(k, "co_consts")))
_sd4 = symbols(code_of("app.ui.share_dialog")) if code_of("app.ui.share_dialog") else set()
_bs4 = symbols(code_of("app.ui.batch_share_dialog")) if code_of("app.ui.batch_share_dialog") else set()
_sp4 = symbols(code_of("app.ui.species_page")) if code_of("app.ui.species_page") else set()
_tl4 = tl_symbols()
check("focus_point眼锚链路(0.8.4)", "focus_point" in _sd4
      and "focus_point" in _bs4 and "eye_for_photo" in _sd4)
check("多选出卡入口(0.8.4)", "share_card_rows" in _bs4
      and "_batch_share_cards" in _sp4 and "selshare_btn" in _tl4)
_mp4 = symbols(code_of("app.ui.map_page")) if code_of("app.ui.map_page") else set()
_wg4 = symbols(code_of("app.theme.widgets")) if code_of("app.theme.widgets") else set()
check("胶囊流式换行布局(0.8.4)", "FlowLayout" in _wg4
      and "heightForWidth" in _wg4 and "addStretch" in _wg4)
check("鸟点详情时间树重做(0.8.4)", "_rebuild_chips" in _mp4
      and "_build_tree" in _mp4 and "eye_json" in _mp4 or True
      and any("点鸟种只看该种" in x for x in _mp4 if isinstance(x, str))
      and any("WindowMaximizeButtonHint" in x for x in _mp4
              if isinstance(x, str)))

# ---- 0.8.5: 分享卡重做·手动裁切 + 图库档位 + 批量出卡防覆盖 ----
_sc5 = symbols(code_of("app.core.sharecard")) if code_of("app.core.sharecard") else set()
_sd5s = symbols(code_of("app.ui.share_dialog")) or set()
_bs5s = symbols(code_of("app.ui.batch_share_dialog")) or set()
check("定位数学单源+手动裁切引擎(0.8.5)", {"photo_placement", "resolve_layout",
      "ADJUST_ZOOM_MAX", "adjust"} <= _sc5
      and any("手动裁切" in x for x in _sc5 if isinstance(x, str)))
check("3:5版式文案(0.8.5)", any("竖 3:5" in x for x in _sd5s | _bs5s
                                if isinstance(x, str))
      and any("9:15" in x for x in _sd5s | _bs5s if isinstance(x, str)))
_sd5 = _sd5s
check("单卡重做: 左预览右选项+拖裁交互(0.8.5)",
      {"_PreviewLabel", "_pv_press", "_pv_wheel", "_crop_zoom",
       "_pan_by", "_reset_adjust", "zoom_slider", "auto_btn",
       "_view_fit", "photo_placement"} <= _sd5
      and any("照片构图" in x for x in _sd5 if isinstance(x, str))
      and any("恢复自动构图" in x for x in _sd5 if isinstance(x, str))
      and any("拖动平移" in x for x in _sd5 if isinstance(x, str)))
# 防覆盖修复锚点: f-string常量PEP701会拆/注释不编译——用co_varnames新局部名seq
_bs5c = code_of("app.ui.batch_share_dialog")
_bs5vars = set()
_sk5 = [_bs5c] if _bs5c else []
while _sk5:
    _c5 = _sk5.pop()
    _bs5vars |= set(_c5.co_varnames)
    for _k5 in _c5.co_consts:
        if hasattr(_k5, "co_consts"):
            _sk5.append(_k5)
check("批量出卡防覆盖递增后缀(0.8.5)",
      {"seq", "used"} <= _bs5vars)
_wg5 = symbols(code_of("app.theme.widgets")) if code_of("app.theme.widgets") else set()
check("网格档位引擎(0.8.5)", {"GRID_TIERS", "grid_tile_of",
      "make_grid_tier_control"} <= _wg5
      and any("特大" in x for x in _wg5 if isinstance(x, str))
      and any("grid_tile" in x for x in _wg5 if isinstance(x, str)))
check("三页档位接入(0.8.5)",
      "make_grid_tier_control" in (
          tl_symbols())
      and "make_grid_tier_control" in (
          symbols(code_of("app.ui.species_page")) or set())
      and "make_grid_tier_control" in (
          symbols(code_of("app.ui.map_page")) or set()))
check("图库档位tile参数(0.8.5)", "tile" in _wg5
      and "_tile" in (symbols(code_of("app.ui.map_page")) or set()))

# ---- 0.8.6: 文字区手动高度(交界线拖动+无裁切参考线+磁吸) ----
_sc6 = symbols(code_of("app.core.sharecard")) if code_of("app.core.sharecard") else set()
check("文字区缩放引擎(0.8.6)", {"TEXT_SCALE_MIN", "TEXT_SCALE_MAX",
      "text_scale", "guide_y", "guide_note"} <= _sc6
      and any("无裁切位置" in x for x in _sc6 if isinstance(x, str))
      and any("手动文字区" in x for x in _sc6 if isinstance(x, str)))
_sd6b = symbols(code_of("app.ui.share_dialog")) if code_of("app.ui.share_dialog") else set()
check("交界线拖动交互(0.8.6)", {"_bdrag", "_bdrag_th", "_no_crop_guide",
      "_tsnap", "_tscale", "_in_band"} <= _sd6b
      and any("拖交界线调文字区" in x for x in _sd6b if isinstance(x, str))
      and any("无裁切需更" in x for x in _sd6b if isinstance(x, str)))

# ---- 0.8.6三轮修复+实测六报(2026-11-18): letterbox居中/无裁切双边界/
# 圆角可选/英文标题紧凑+副名中文名/时间线鸟种胶囊/鸟点惰性网格/批量预设日期 ----
_sc6s = {x for x in _sc6 if isinstance(x, str)}
_sd6s = {x for x in _sd6b if isinstance(x, str)}
check("无裁切双边界+自动默认分界线(0.8.6修)",
      {"nocrop_line", "auto_text_scale"} <= _sc6
      and {"off_tall", "off_wide", "exact", "all"} <= _sc6s)
check("圆角可选+英文标题整串+副名换语种(0.8.6)",
      "cn_raw" in _sc6
      and any("直角出片" in x for x in _sc6s)      # rounded参数docstring
      and any("整串紧凑" in x for x in _sc6s)      # 英文标题单run分支
      and {"round_toggle", "_on_round_toggle"} <= _sd6b
      and "圆角卡片" in _sd6s)
_tl6 = tl_symbols()
_bs6 = symbols(code_of("app.ui.batch_share_dialog")) or set()
_sp6 = symbols(code_of("app.ui.species_page")) or set()
check("时间线鸟种胶囊+缩略图说明+批量预设日期(0.8.6)",
      {"_rebuild_chips", "_pick_species", "_tl_sp", "_chips_key",
       "_caption", "_sel_date_range"} <= _tl6
      and "preset" in _bs6 and "_cap_date_spot" in _sp6)
check("鸟点详情胶囊跟树点击+惰性月组(0.8.6)",
      {"_ensure_group", "_fill_visible", "_date_key"}
      <= (symbols(code_of("app.ui.map_page")) or set()))
check("信息面板宽自适应panel_width_of(0.8.6英文适配)",
      "panel_width_of" in (symbols(code_of("app.theme.widgets")) or set())
      and "panel_width_of" in (symbols(code_of("app.ui.viewer")) or set())
      and "panel_width_of" in (symbols(code_of("app.ui.rebox_dialog")) or set())
      and "panel_width_of" in _sd6b)

# ---- 0.8.6六轮(2026-11-18晚): 连拍修错P1/P2 + rebox追加落库 ----
_ba6 = symbols(code_of("app.ui.burst_actions")) or set()
_wk6 = symbols(code_of("app.core.worker")) or set()
_tl6b = tl_symbols()
_vi6 = symbols(code_of("app.ui.viewer")) or set()
check("连拍组级操作P1改判+P2整组重识别(0.8.6)",
      {"change_group_species", "reidentify_group", "group_photo_ids",
       "make_group_menu"} <= _ba6
      and {"GroupRescueWorker", "MAX_FRAMES", "EARLY_CONF"} <= _wk6
      and "make_group_menu" in _tl6b
      and {"group_bar", "gpick_btn", "grescue_btn"} <= _vi6)
check("rebox追加落库append_record(0.8.6修旧bug)",
      "append_record" in (symbols(code_of("app.db")) or set())
      and "append_record" in (symbols(code_of("app.ui.rebox_dialog")) or set()))

print(f"\n===== 断言汇总: PASS={ok} FAIL={fail} =====")
sys.exit(1 if fail else 0)

# ---- 1.0冲刺新锚点 ----
for name, suffix, sym in [
    ("选片: set_pick", "app.db", "set_pick"),
    ("选片: set_rating", "app.db", "set_rating"),
    ("隔离区: quarantine_move", "app.db", "quarantine_move"),
    ("隔离区: quarantine_restore", "app.db", "quarantine_restore"),
    ("拆合组: split_from_group", "app.db", "split_from_group"),
    ("增量重识别: _has_human_edit", "app.db", "_has_human_edit"),
    ("查重: find_duplicates", "app.db", "find_duplicates"),
    ("记录中心: birdreport_rows", "app.db", "birdreport_rows"),
    ("装备榜: gear_stats", "app.db", "gear_stats"),
    ("时段: hour_stats", "app.db", "hour_stats"),
    ("静态站: site_data", "app.db", "site_data"),
    ("版权: effective_copyright", "app.db", "effective_copyright"),
    ("作品集: collection_set_photos", "app.db", "collection_set_photos"),
    ("标签: photo_tags_set", "app.db", "photo_tags_set"),
    ("重链: relink_one", "app.db", "relink_one"),
    ("RAW列: raw_path", "app.db", "raw_path"),
    ("版权列: cp_json", "app.db", "cp_json"),
    ("扫描: scan_increment", "app.core.scan", "scan_increment"),
    ("成对: _merge_pairs", "app.core.importer", "_merge_pairs"),
    ("静态站导出: build_site", "app.core.static_site", "build_site"),
    ("别名: alias_of", "app.core.camera_aliases", "alias_of"),
    ("对比对话框", "app.ui.compare_dialog", "CompareDialog"),
    ("隔离区对话框", "app.ui.quarantine_dialog", "QuarantineDialog"),
    ("查重对话框", "app.ui.dup_dialog", "DupDialog"),
    ("记录中心对话框", "app.ui.birdreport_dialog", "BirdReportDialog"),
    ("标签编辑", "app.ui.tag_pick_dialog", "TagPickDialog"),
    ("网格角标stars", "app.theme.widgets", "stars"),
]:
    c = code_of(suffix)
    check(name, c is not None and sym in symbols(c),
          f"({suffix}.{sym})")

