# -*- coding: utf-8 -*-
"""0.8.0-test2包内断言: 0.7全部检查 + 0.8八项新功能 + 名录1097 + MapTilerKey清除。
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
check("版本=0.8.0-test3", "0.8.0-test3" in syms)

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
tl = code_of("app.ui.timeline_page")
s = symbols(tl) if tl else set()
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
tl2 = code_of("app.ui.timeline_page")
s = symbols(tl2) if tl2 else set()
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
tl3 = code_of("app.ui.timeline_page")
s = symbols(tl3) if tl3 else set()
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
tl4 = code_of("app.ui.timeline_page")
s = symbols(tl4) if tl4 else set()
check("时间线0.8入口", {"burst_btn", "_collapse_on", "_batch_share",
                        "_export_wizard"} <= s
      and any("连拍折叠" in x for x in s if isinstance(x, str)))
mn8 = code_of("app.ui.main_window")
s = symbols(mn8) if mn8 else set()
check("主窗口sidecar定时器", "_flush_sidecars_tick" in s
      and "start_burst_regroup" in s
      and "_save_nav_order" in s and "nav_order" in s)
bu2 = code_of("app.db")
s = symbols(bu2) if bu2 else set()
check("连拍鸟种统一(unify)", "unify_burst_species" in s)
im2 = code_of("app.ui.import_page")
s = symbols(im2) if im2 else set()
check("导入地区确认弹窗", "确认拍摄地区" in s
      and any("提高识别准确率" in x for x in s if isinstance(x, str)))
tl5 = code_of("app.ui.timeline_page")
s = symbols(tl5) if tl5 else set()
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
_tl2 = code_of("app.ui.timeline_page")
_s2 = symbols(_tl2) if _tl2 else set()
check("重新识别地区弹窗在包内(0.8-test3)",
      "识别地区与鸟点" in _s2
      and "JOIN photos p ON p.batch_id=b.id WHERE p.id IN (" in _s2,
      "(参数修复+国家级data由verify_rerecog_region功能级覆盖)")
_db2 = code_of("app.db")
_s3 = symbols(_db2) if _db2 else set()
check("连拍统一限EXIF(0.8-test3)",
      "SELECT p.id, e.dt_original AS ts, p.group_id FROM photos p "
      "JOIN exif e ON e.photo_id=p.id WHERE e.dt_original IS NOT NULL" in _s3)
# 导出模板单后缀: 无独立常量可辨(修复在表达式层), 由verify_export[6]功能级覆盖

print(f"\n===== 断言汇总: PASS={ok} FAIL={fail} =====")
sys.exit(1 if fail else 0)
