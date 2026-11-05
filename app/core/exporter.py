# -*- coding: utf-8 -*-
"""导出向导核心(0.8-④): 范围筛选 + 复制/原地重命名 两种执行计划。

原则(用户定):
  · 导出本质 = 复制 + 重命名; 「原地重命名」= 只改名不复制不移动,
    库里 path 同步按 file_hash 更新(缩略图/识别记录/时间线不受影响)。
  · 重名安全编号绝不覆盖; RAW+JPG 同名对(如 DSC05868.ARW/.jpg)成对处理;
  · 鸟种名等里的非法字符(\\ / : * ? " < > |)清洗;
  · 与标注随文件夹走兼容: sidecar 按 file_hash 键, 改名不影响(改名后
    标脏目录由调用方 flush, 新旧目录各得一份)。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from ..i18n import t

RAW_EXTS = {".arw", ".cr2", ".cr3", ".nef", ".raf", ".orf", ".rw2",
            ".dng", ".pef", ".srw", ".kdc", ".dcr"}
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif",
            ".tiff", ".bmp", ".avif"}
ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def safe_component(s: str, fallback: str | None = None) -> str:
    """路径段安全化: 非法字符→下划线, 去首尾空格点; 空回退。"""
    out = ILLEGAL.sub("_", (s or "").strip()).strip(". ")
    return out or (fallback or t("未命名", "Unnamed"))


def fmt_stem(template: str, date: str, name: str, seq: int) -> str:
    """'2026-05-01_鸲姬鹟_0001' 风格; seq 从1起, 4位补零。"""
    return f"{date}_{safe_component(name)}_{seq:04d}"


def select_range(lib, date_from: str | None = None,
                 date_to: str | None = None, code: str | None = None,
                 spot_id: int | None = None, rated_only: bool = False
                 ) -> list[dict]:
    """导出范围 → [{photo_id, path, eff_code, name(cn), en, taken_at}] 按时间升序。"""
    sql = (
        "SELECT DISTINCT v.photo_id, p.path, v.eff_code, "
        "  COALESCE(s.cn, s.en, v.eff_code) AS name, s.en AS en_name, "
        "  COALESCE(e.dt_original, p.added_at) AS taken_at, p.rating, "
        "  p.spot_id, sp.name AS spot_name "
        "FROM v_records v "
        "JOIN photos p ON p.id=v.photo_id "
        "LEFT JOIN species s ON s.code=v.eff_code "
        "LEFT JOIN exif e ON e.photo_id=p.id "
        "LEFT JOIN spots sp ON sp.id=p.spot_id "
        "WHERE v.rank=1")
    args: list = []
    if date_from:
        sql += " AND substr(COALESCE(e.dt_original, p.added_at),1,10) >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND substr(COALESCE(e.dt_original, p.added_at),1,10) <= ?"
        args.append(date_to)
    if code:
        sql += " AND v.eff_code=?"
        args.append(code)
    if spot_id is not None:
        sql += " AND p.spot_id=?"
        args.append(spot_id)
    if rated_only:
        sql += " AND p.rating >= 1"
    sql += " ORDER BY taken_at, v.photo_id"
    return [dict(r) for r in lib.conn.execute(sql, args).fetchall()]


def sibling_pair(path: Path) -> Path | None:
    """同名成对文件: 照片是图片→找同stem的RAW; 照片是RAW→找同stem的JPG。"""
    ext = path.suffix.lower()
    stems = [path.with_suffix(e) for e in (".jpg", ".jpeg")] \
        if ext in RAW_EXTS else \
        [path.with_suffix(e) for e in RAW_EXTS]
    for cand in stems:
        try:
            if cand.exists() and cand != path:
                return cand
        except OSError:
            continue
    return None


def _unique(dst: Path, taken: set[str]) -> Path:
    """重名安全编号: 'name (2).ext' 起; taken=本轮已占用(含被改走前的旧名)。"""
    cand = dst
    i = 1
    while os.path.normcase(str(cand)) in taken or cand.exists():
        cand = dst.with_name(f"{dst.stem} ({i}){dst.suffix}")
        i += 1
    taken.add(os.path.normcase(str(cand)))
    return cand


def plan_ops(rows: list[dict], dest_root: Path | None = None,
             hierarchy: str = "time_species", naming: str = "original",
             extra_pairs: bool = True,
             template: list[str] | None = None) -> dict:
    """生成执行计划(不落盘)。

    dest_root None = 原地重命名(只改名)。
    hierarchy: time_species(年/月→鸟种) | species_time(鸟种→年月) | flat
    naming:    original(原名) | date_name(日期_鸟种_序号)

    返回 {"ops": [{"src", "dst", "pair": bool, "photo_id": int|None}],
          "skipped_offline": [路径], "errors": [str]}。
    """
    ops: list[dict] = []
    skipped: list[str] = []
    errors: list[str] = []
    taken: set[str] = set()
    seen_stems: set[str] = set()      # date_name 模式下 (date|code) → 已用序号
    seq_by_key: dict[str, int] = {}
    for r in rows:
        src = Path(r["path"])
        if not src.exists():
            skipped.append(r["path"])
            continue
        date = (r.get("taken_at") or "")[:10]
        name = r.get("name") or r.get("en_name") or r.get("eff_code") or "photo"
        targets: list[tuple[Path, Path, int | None]] = []   # (src, dst, photo_id)

        def dst_for(f: Path) -> Path:
            if template:
                # CameraRaw式组合模板: 段∈ filename/date/name/seq/spot,
                # 用"_"连接; 序号按 段组合键(日期|鸟种|鸟点) 递增
                seq_key = f"{date}|{r.get('eff_code') or ''}|{r.get('spot_name') or ''}"
                seq = 0
                parts_out = []
                for seg in template:
                    if seg == "filename":
                        # 只放stem: 扩展名由末尾统一追加一次——段内先加一次
                        # 会产生 DSC0001.arw.arw 双后缀(0.8.0-test2复查)
                        parts_out.append(safe_component(f.stem, "photo"))
                    elif seg == "date":
                        parts_out.append(date)
                    elif seg == "name":
                        parts_out.append(safe_component(name, "photo"))
                    elif seg == "spot":
                        sn = r.get("spot_name")
                        if sn:
                            parts_out.append(safe_component(sn, "spot"))
                    elif seg == "seq":
                        if not seq:
                            seq_by_key[seq_key] = seq_by_key.get(seq_key, 0) + 1
                            seq = seq_by_key[seq_key]
                        parts_out.append(f"{seq:04d}")
                stem = "_".join(parts_out) or f.stem   # f.name会双后缀
                return Path(stem + f.suffix.lower())
            if naming == "date_name":
                key = f"{date}|{r.get('eff_code') or ''}"
                seq_by_key[key] = seq_by_key.get(key, 0) + 1
                stem = fmt_stem("", date, name, seq_by_key[key])
                return Path(stem + f.suffix.lower())
            return Path(f.name)

        if dest_root is None:                      # 原地重命名
            base = src.parent
        else:
            ym = date[:7].replace("-", "-")
            year, month = (ym.split("-") + [""])[:2]
            sp = safe_component(r.get("name"),
                                t("未识别", "Unidentified"))
            if hierarchy == "flat":
                parts = []
            elif hierarchy == "species_time":
                parts = [sp, f"{year}-{month}" if month
                         else t("未知时间", "Unknown date")]
            else:                                  # time_species
                parts = ([year] if year else []) + \
                        ([t(f"{int(month)}月", str(int(month))) if month
                          else t("未知时间", "Unknown date")]) + [sp]
            base = dest_root.joinpath(*parts) if parts else dest_root
        new = dst_for(src)
        if new != Path(src.name) or dest_root is not None:
            targets.append((src, base / new.name, r["photo_id"]))
        else:
            taken.add(os.path.normcase(str(src)))   # 原名保留: 占位防撞
        if extra_pairs:
            pair = sibling_pair(src)
            if pair is not None and all(t[0] != pair for t in targets):
                # 成对文件与照片同号: 共用新stem, 各保留自己的后缀
                # (模板含filename段时主文件保留原名, pair名=主stem, 仍成对)
                targets.append((pair, base / (new.stem + pair.suffix), None))
        for s, d, pid in targets:
            if s == d:
                taken.add(os.path.normcase(str(s)))
                continue
            ops.append({"src": str(s), "dst": str(d), "pair": pid is None,
                        "photo_id": pid})
    # 重名编号(统一在本计划内分配; 盘上已存在的目标同样让位编号——
    # 复制模式绝不覆盖既有文件)
    used = set(taken)
    for op in ops:
        d = Path(op["dst"])
        if os.path.normcase(str(d)) in used or d.exists():
            d = _unique(d, used)
            op["dst"] = str(d)
        else:
            used.add(os.path.normcase(str(d)))
    return {"ops": ops, "skipped_offline": skipped, "errors": errors}


def _conflict_needs_two_phase(ops: list[dict]) -> bool:
    """目标名与盘上现存文件冲突, 或与本计划内其他op的源名/目标名互撞
    (A↔B换名等) → 全部走 临时名两段式。"""
    srcs = {os.path.normcase(o["src"]) for o in ops}
    dsts = [os.path.normcase(o["dst"]) for o in ops]
    if len(dsts) != len(set(dsts)):
        return True
    for o in ops:
        d = os.path.normcase(o["dst"])
        if d == os.path.normcase(o["src"]):
            continue
        if os.path.exists(o["dst"]) or d in srcs:
            return True
    return False


def execute_plan(ops: list[dict], action: str = "copy") -> dict:
    """执行计划。action: "copy"(复制, 原图不动) | "rename"(原地改名)。

    rename 且存在冲突(换名/目标已存在/计划内互撞)→两段式临时名, 保证
    不覆盖不丢失; copy 模式计划期已编号让位, 执行期冲突按失败计。
    返回 {"done": [...op], "failed": [{"op", "error"}]}。
    调用方负责之后按 photo_id 更新库里 path(只对done且photo_id非空)。"""
    two = action == "rename" and _conflict_needs_two_phase(ops)
    done: list[dict] = []
    failed: list[dict] = []
    tmps: list[tuple[str, str]] = []
    if two:
        import shutil
        for i, op in enumerate(ops):
            src = Path(op["src"])
            if src == Path(op["dst"]):
                done.append(op)
                continue
            tmp = src.with_name(f"{src.stem}.__bt{os.getpid()}_{i}{src.suffix}")
            try:
                os.rename(src, tmp)
                tmps.append((str(tmp), op["dst"]))
            except OSError as e:
                failed.append({"op": op, "error": str(e)})
        for tmp_s, dst_s in tmps:
            try:
                os.rename(tmp_s, dst_s)
                done.append(next(o for o in ops if o["dst"] == dst_s))
            except OSError as e:
                failed.append({"op": {"src": tmp_s, "dst": dst_s},
                               "error": str(e)})
    else:
        import shutil
        for op in ops:
            try:
                if action == "rename":
                    os.rename(op["src"], op["dst"])
                else:
                    os.makedirs(Path(op["dst"]).parent, exist_ok=True)
                    shutil.copy2(op["src"], op["dst"])
                done.append(op)
            except OSError as e:
                failed.append({"op": op, "error": str(e)})
    return {"done": done, "failed": failed}


def apply_rename_to_db(lib, done: list[dict]) -> int:
    """原地重命名后按 file_hash 更新 photos.path(只动真实成功的行)。"""
    n = 0
    for op in done:
        pid = op.get("photo_id")
        if not pid:
            continue
        row = lib.conn.execute(
            "SELECT file_hash FROM photos WHERE id=?", (pid,)).fetchone()
        if not row:
            continue
        lib.conn.execute(
            "UPDATE photos SET path=?, missing=0, size=("
            "  SELECT size FROM photos WHERE id=?) WHERE id=?",
            (op["dst"], pid, pid))
        n += 1
    lib.conn.commit()
    if n:
        try:
            old_dirs = {os.path.dirname(o["src"]) for o in done
                        if o.get("photo_id")}
            new_dirs = {os.path.dirname(o["dst"]) for o in done
                        if o.get("photo_id")}
            lib._sidecar_touch(paths=list(old_dirs | new_dirs))
        except Exception:
            pass
        lib.invalidate_file_status()
    return n
