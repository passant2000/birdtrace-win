# -*- coding: utf-8 -*-
"""标注随文件夹走(0.8-①): 每个被管理文件夹维护一份 `.birdtrace.json`。

对标 BirdyBank `.birdybank.json`。内容按 file_hash 键(改名/搬家不影响):
鸟种记录(含确认码/框/来源)、无鸟标记、评分(rating)、美学分、鸟点(名+坐标)。
  · 写出: 标注变更时标记该文件夹脏, 主窗口定时(3s)与退出时 flush;
          写入合并既有文件里本库不认识的条目(另一台机器导入得更多的照片)。
  · 读回: 导入时按 hash 回填——**已有编辑优先, 旧记录不覆盖**:
          本地已有人工确认/手工记录的照片不动鸟种; 评分/美学/鸟点/无鸟
          只在本地为空时补。
  · 与"引用导入不动原文件"兼容: 目录里只多一个隐藏 json。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

SIDECAR_NAME = ".birdtrace.json"
FORMAT = "birdtrace-sidecar/1"
HUMAN_SOURCES = ("manual", "rebox")


def sidecar_path(folder: str | Path) -> Path:
    return Path(folder) / SIDECAR_NAME


def read_sidecar(folder: str | Path) -> dict:
    """读文件夹的 sidecar → {hash: entry}; 无文件/坏文件 → {}。"""
    p = sidecar_path(folder)
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(obj, dict) or not str(obj.get("format", "")).startswith(
            "birdtrace-sidecar/"):
        return {}
    photos = obj.get("photos")
    return photos if isinstance(photos, dict) else {}


def _hide(path: Path):
    """Windows 设隐藏属性(点开头在 Windows 不算隐藏); 失败忽略。"""
    if os.name != "nt":
        return
    try:
        import ctypes
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs != -1 and not (attrs & 0x2):
            ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs | 0x2)
    except Exception:
        pass


def _write_atomic(path: Path, text: str):
    # 唯一临时名(0.8.7加固): 固定".tmp"在并发写同目录时会互相覆盖
    import uuid
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(text, encoding="utf-8")
    # 隐藏文件 os.replace 在 Windows 上可能报 PermissionError: 先去隐藏再替换
    if os.name == "nt" and path.exists():
        try:
            import ctypes
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if attrs != -1 and attrs & 0x2:
                ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs & ~0x2)
        except Exception:
            pass
    os.replace(tmp, path)
    _hide(path)


def build_entries(lib, folder: str) -> dict[str, dict]:
    """本库中位于 folder 的照片 → {hash: entry}。"""
    rows = lib.conn.execute(
        "SELECT p.id, p.path, p.file_hash, p.rating, p.rec_fail, p.aesthetic, "
        "  p.pick, p.pick_note, p.cp_json, "
        "  p.spot_id, s.name AS spot_name, s.lat AS spot_lat, s.lon AS spot_lon, "
        "  s.note AS spot_note, s.city AS spot_city "
        "FROM photos p LEFT JOIN spots s ON s.id=p.spot_id").fetchall()
    key = os.path.normcase(os.path.normpath(folder))
    out: dict[str, dict] = {}
    for r in rows:
        if os.path.normcase(os.path.normpath(os.path.dirname(r["path"]))) != key:
            continue
        recs = lib.conn.execute(
            "SELECT r.species_code, r.confirmed_code, r.rank, r.confidence, "
            "  r.source, r.box_json, r.top5_json, r.reviewed, r.eye_json, "
            "  COALESCE(sp.cn, sp.en) AS name "
            "FROM records r LEFT JOIN species sp "
            "  ON sp.code=COALESCE(r.confirmed_code, r.species_code) "
            "WHERE r.photo_id=? ORDER BY r.rank", (r["id"],)).fetchall()
        records = []
        for rec in recs:
            try:
                box = json.loads(rec["box_json"]) if rec["box_json"] else None
            except ValueError:
                box = None
            try:
                top5 = json.loads(rec["top5_json"]) if rec["top5_json"] else None
            except ValueError:
                top5 = None
            try:
                eye = json.loads(rec["eye_json"]) if rec["eye_json"] else None
            except ValueError:
                eye = None
            records.append({
                "code": rec["species_code"], "confirmed": rec["confirmed_code"],
                "name": rec["name"], "rank": rec["rank"],
                "confidence": rec["confidence"], "source": rec["source"],
                "reviewed": int(rec["reviewed"] or 0), "box": box,
                "top5": top5, "eye": eye})
        entry = {
            "file": os.path.basename(r["path"]),
            "records": records,
            "no_bird": bool(not records and (r["rec_fail"] or 0) >= 3),
            "rating": int(r["rating"] or 0),
            "aesthetic": r["aesthetic"],
            "spot": ({"name": r["spot_name"], "lat": r["spot_lat"],
                      "lon": r["spot_lon"], "note": r["spot_note"] or "",
                      "city": r["spot_city"] or ""}
                     if r["spot_id"] else None),
        }
        # 选片三态(1.0冲刺⑨): 非空才写, 旧版本读到未知字段会保留不清
        if r["pick"]:
            entry["pick"] = r["pick"]
            if r["pick_note"]:
                entry["pick_note"] = r["pick_note"]
        # 自定义标签(1.0冲刺⑭): 随文件夹走(多机互通); 作品集是库内
        # 策展语义不进sidecar(两机同改冲突面大, 1.0不跨机)
        tags = [t2["name"] for t2 in lib.conn.execute(
            "SELECT t.name FROM tags t JOIN photo_tags pt ON pt.tag_id=t.id "
            "WHERE pt.photo_id=? ORDER BY t.name", (r["id"],)).fetchall()]
        if tags:
            entry["tags"] = tags
        # 照片级版权覆盖(1.0冲刺⑰): 覆盖/清空三态原样随文件夹走
        cp = r["cp_json"] if "cp_json" in r.keys() else None
        if cp:
            entry["cp"] = cp
        out[r["file_hash"]] = entry
    return out


def export_folder(lib, folder: str | Path) -> Path | None:
    """写出/更新 folder 的 sidecar(合并既有文件中本库不认识的条目)。
    文件夹不可写/盘离线/写入失败 → None(调用方保留脏标记, 0.8.7起调用方
    对一切失败保留, 不再区分目录是否存在)。无可写内容 → folder(成功空
    操作, 0.8.7改: 旧返回None会被flush当失败, 脏标记永不消)。"""
    folder = Path(folder)
    if not folder.is_dir():
        return None
    mine = build_entries(lib, str(folder))
    existing = read_sidecar(folder)
    merged = {h: e for h, e in existing.items() if h not in mine}
    merged.update(mine)
    if not merged:
        return folder
    from ..version import VERSION
    doc = {"format": FORMAT, "app": f"BirdTrace {VERSION}",
           "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "photos": merged}
    try:
        _write_atomic(sidecar_path(folder),
                      json.dumps(doc, ensure_ascii=False, indent=1))
    except OSError:
        return None
    return sidecar_path(folder)


def _has_human_edit(lib, photo_id: int) -> bool:
    row = lib.conn.execute(
        "SELECT COUNT(*) FROM records WHERE photo_id=? AND "
        "(confirmed_code IS NOT NULL OR source IN (?,?))",
        (photo_id, *HUMAN_SOURCES)).fetchone()
    return bool(row and row[0])


def _resolve_spot(lib, spot: dict) -> int | None:
    name = (spot or {}).get("name")
    if not name:
        return None
    row = lib.conn.execute("SELECT id FROM spots WHERE name=?", (name,)).fetchone()
    if row:
        return row["id"]
    lat, lon = spot.get("lat"), spot.get("lon")
    if lat is not None and lon is not None:
        near, _d = lib.nearest_spot(float(lat), float(lon), max_m=50.0)
        if near:
            return near["id"]
    return lib.create_spot(name, lat, lon, spot.get("note") or "",
                           city=spot.get("city") or "")


def apply_entry(lib, photo_id: int, entry: dict) -> dict:
    """把 sidecar 条目回填到本地照片(已有编辑优先)。返回各字段是否应用。"""
    done = {"records": False, "no_bird": False, "rating": False,
            "aesthetic": False, "spot": False, "pick": False, "tags": False}
    p = lib.conn.execute(
        "SELECT rating, rec_fail, aesthetic, spot_id, pick, cp_json "
        "FROM photos WHERE id=?", (photo_id,)).fetchone()
    if not p:
        return done
    n_local = lib.conn.execute(
        "SELECT COUNT(*) FROM records WHERE photo_id=?", (photo_id,)).fetchone()[0]
    recs = entry.get("records") or []
    if recs and not _has_human_edit(lib, photo_id):
        if n_local:
            lib.conn.execute("DELETE FROM records WHERE photo_id=?", (photo_id,))
        valid = {r["code"] for r in lib.conn.execute(
            "SELECT code FROM species WHERE code IN (%s)" % ",".join(
                "?" * len(recs)),
            [r.get("confirmed") or r.get("code") for r in recs])}
        # 按rank去重: 旧版json可能含同rank重复条目, 顺序重编号会凭空
        # 多出"第二只鸟"(2026-11-05双主鸟反馈的连带防护)
        seen_ranks: set = set()
        uniq = []
        for r in sorted(recs, key=lambda x: x.get("rank") or 99):
            rk = int(r.get("rank") or 0)
            if rk in seen_ranks:
                continue
            seen_ranks.add(rk)
            uniq.append(r)
        for i, r in enumerate(uniq, 1):
            code = r.get("code")
            conf = r.get("confirmed")
            if code not in valid and conf not in valid:
                continue
            if code not in valid:
                code = conf
            lib.conn.execute(
                "INSERT INTO records(photo_id,species_code,rank,confidence,source,"
                "box_json,top5_json,reviewed,confirmed_code,eye_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (photo_id, code, i, float(r.get("confidence") or 0),
                 r.get("source") or "sidecar", json.dumps(r.get("box")),
                 json.dumps(r.get("top5")) if r.get("top5") else None,
                 int(r.get("reviewed") or 0),
                 conf if conf in valid else None,
                 json.dumps(r.get("eye")) if r.get("eye") else None))
            done["records"] = True
        if done["records"]:
            lib.conn.execute("UPDATE photos SET rec_fail=0, cand_json=NULL "
                             "WHERE id=?", (photo_id,))
    elif entry.get("no_bird") and not n_local and (p["rec_fail"] or 0) < 3:
        lib.conn.execute("UPDATE photos SET rec_fail=3 WHERE id=?", (photo_id,))
        done["no_bird"] = True
    if entry.get("rating") and not (p["rating"] or 0):
        lib.conn.execute("UPDATE photos SET rating=? WHERE id=?",
                         (int(entry["rating"]), photo_id))
        done["rating"] = True
    # 选片三态(1.0冲刺⑨): 已有编辑优先——本地已标记不动, 空才补
    # (与rating同款; note只在pick应用时随行)
    if entry.get("pick") and not (p["pick"] or ""):
        lib.conn.execute(
            "UPDATE photos SET pick=?, pick_note=? WHERE id=?",
            (entry["pick"], entry.get("pick_note") or "", photo_id))
        done["pick"] = True
    # 标签(1.0冲刺⑭): 本地无标签时才回填(已有编辑优先——本地已打标
    # 的照片不吃机器B的标签集)
    if entry.get("tags") and not lib.conn.execute(
            "SELECT 1 FROM photo_tags WHERE photo_id=? LIMIT 1",
            (photo_id,)).fetchone():
        for name in entry["tags"]:
            tid = lib.tag_create(str(name))
            lib.conn.execute(
                "INSERT OR IGNORE INTO photo_tags(photo_id, tag_id) "
                "VALUES(?,?)", (photo_id, tid))
        done["tags"] = True
    # 照片级版权覆盖(1.0冲刺⑰): 本地未设置过才回填(已有编辑优先)
    if entry.get("cp") and not (p["cp_json"] if "cp_json" in p.keys()
                               else None):
        lib.conn.execute("UPDATE photos SET cp_json=? WHERE id=?",
                         (entry["cp"], photo_id))
        done["cp"] = True
    if entry.get("aesthetic") is not None and p["aesthetic"] is None:
        lib.conn.execute("UPDATE photos SET aesthetic=? WHERE id=?",
                         (float(entry["aesthetic"]), photo_id))
        done["aesthetic"] = True
    if entry.get("spot") and p["spot_id"] is None:
        sid = _resolve_spot(lib, entry["spot"])
        if sid:
            lib.conn.execute("UPDATE photos SET spot_id=? WHERE id=?",
                             (sid, photo_id))
            done["spot"] = True
    lib.conn.commit()
    return done


def apply_for_imports(lib, items: list[tuple[int, str, str]]) -> dict:
    """导入后回填: items=[(photo_id, file_hash, 源文件夹)]。
    返回 {"restored": 带回鸟种的张数, "spots": 挂回鸟点数, "folders": 读到sidecar的文件夹数}。"""
    cache: dict[str, dict] = {}
    out = {"restored": 0, "spots": 0, "folders": 0}
    for pid, fh, src_dir in items:
        key = os.path.normcase(os.path.normpath(src_dir))
        if key not in cache:
            cache[key] = read_sidecar(src_dir)
            if cache[key]:
                out["folders"] += 1
        entry = cache[key].get(fh)
        if not entry:
            continue
        done = apply_entry(lib, pid, entry)
        if done["records"]:
            out["restored"] += 1
        if done["spot"]:
            out["spots"] += 1
    return out
