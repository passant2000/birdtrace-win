# -*- coding: utf-8 -*-
"""Lightroom式导入: 扫描 -> 去重 -> 引用或复制 -> 编目(含EXIF)。

模式:
  ref   引用原位置, 文件不动
  copy  复制到目标目录 <dest>/<拍摄年月>/文件名, 再引用副本
  move  移动到目标目录(Lightroom式), 原位置不再保留
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from PIL import Image, ImageOps

from ..db import Library
from ..exif import SUPPORTED_EXTS, read_exif
from .exporter import RAW_EXTS

# 主导入链可收的扩展名=成品图 + RAW/DNG(1.0冲刺⑧成对编目:
# 同名对JPG做主文件, RAW挂附属; 纯RAW自己当主文件照常识别)
_IMPORT_EXTS = SUPPORTED_EXTS | RAW_EXTS

# 视频归档(1.0冲刺⑬): mp4/mov/avi/mkv 像照片一样编目(时长+抽帧缩略图+
# 抽帧识别+播放); 识别worker跳过视频(pending排除), 抽帧识别走时间线
# 「识别视频帧…」入口(core/video.py, Qt自带多媒体后端, 零新增打包依赖)
from .video import VIDEO_EXTS, is_video
_IMPORT_EXTS = _IMPORT_EXTS | VIDEO_EXTS

from ..i18n import t
from ..media import ensure_thumbnail, file_hash


def scan_sources(paths: list[Path], recursive: bool = True) -> list[Path]:
    """从文件/文件夹列表收集支持的照片, 保持顺序去重; 一律转为绝对路径
    (引用模式记录的是原位置, 不能受程序启动目录影响)。"""
    out: list[Path] = []
    seen: set[str] = set()
    for p in paths:
        p = Path(p).resolve()
        if p.is_file():
            if p.suffix.lower() in _IMPORT_EXTS:
                key = str(p).lower()
                if key not in seen:
                    seen.add(key)
                    out.append(p)
        elif p.is_dir():
            it = p.rglob("*") if recursive else p.iterdir()
            for f in it:
                if f.is_file() and f.suffix.lower() in _IMPORT_EXTS:
                    key = str(f).lower()
                    if key not in seen:
                        seen.add(key)
                        out.append(f.resolve())
    return out


def _copy_dest(dest_root: Path, src: Path, dt_original: str | None) -> Path:
    ym = dt_original[:7].replace("-", "/") if dt_original and len(dt_original) >= 7 \
        else time.strftime("%Y/%m")
    target_dir = dest_root / ym
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / src.name
    stem, suffix = src.stem, src.suffix
    i = 1
    while target.exists():
        target = target_dir / f"{stem} ({i}){suffix}"
        i += 1
    return target


def import_files(lib: Library, files: list[Path], mode: str = "ref",
                 dest_root: Path | None = None, region_id: str | None = None,
                 spot_id: int | None = None, auto_spot: bool = True,
                 progress_cb=None) -> dict:
    """执行导入, 返回 {batch_id, added, skipped_dup, failed, spots_created}。

    spot_id   指定鸟点: 本批全部照片挂到该点
    auto_spot 未指定鸟点时按EXIF GPS自动归组(300m, app.core.spots)
    """
    cur = lib.conn.execute(
        "INSERT INTO batches(mode,dest,region_id,count) VALUES(?,?,?,0)",
        (mode, str(dest_root) if dest_root else None, region_id))
    batch_id = cur.lastrowid
    lib.conn.commit()

    stats = {"batch_id": batch_id, "added": 0, "skipped_dup": 0, "failed": 0,
             "spots_created": 0}
    total = len(files)
    hash_cache: dict[str, str] = {}
    imported: list[tuple[int, str, str]] = []   # (pid, hash, 源文件夹)

    # 先按路径排除已导入的(统一绝对路径: 相对路径会让识别子进程在
    # 别的cwd下找不到文件; UI的QFileDialog天然绝对, 此处防御脚本/API调用)
    todo: list[Path] = []
    for f in files:
        f = f.resolve()
        if lib.photo_by_path(str(f)) is None:
            todo.append(f)
        else:
            stats["skipped_dup"] += 1
        if progress_cb:
            progress_cb(stats["added"] + stats["skipped_dup"] + stats["failed"], total,
                        t(f"检查 {f.name}", f"Checking {f.name}") )

    # 按内容hash去重(分批查库)
    CHUNK = 400
    for i in range(0, len(todo), CHUNK):
        chunk = todo[i:i + CHUNK]
        hashes = {}
        for f in chunk:
            try:
                hashes[f] = file_hash(f)
            except OSError:
                hashes[f] = None
        known = lib.existing_hashes([h for h in hashes.values() if h])
        for f, fh in zip(chunk, hashes.values()):
            try:
                if fh and fh in known:
                    stats["skipped_dup"] += 1
                    continue
                target = f
                if mode in ("copy", "move") and dest_root:
                    ex = read_exif(str(f))
                    target = _copy_dest(dest_root, f, ex.get("dt_original"))
                    if mode == "move":
                        shutil.move(str(f), str(target))
                    else:
                        shutil.copy2(f, target)
                fsize = target.stat().st_size
                fmtime = target.stat().st_mtime
                fh = fh or file_hash(target)
                ex = read_exif(str(target))
                w, h = ex.get("width") or 0, ex.get("height") or 0
                if not w and not is_video(target):
                    with Image.open(target) as im:
                        w, h = im.size
                pid = lib.add_photo(str(target), fh, fsize, fmtime, w, h, batch_id)
                if is_video(target):
                    lib.conn.execute(
                        "UPDATE photos SET is_video=1 WHERE id=?", (pid,))
                lib.add_exif(pid, ex)
                if spot_id is not None:
                    lib.set_photo_spot(pid, spot_id)
                elif auto_spot and ex.get("gps_lat") is not None \
                        and ex.get("gps_lon") is not None:
                    from .spots import auto_assign_spot
                    _sid, created = auto_assign_spot(lib, pid,
                                                     ex["gps_lat"], ex["gps_lon"])
                    if created:
                        stats["spots_created"] += 1
                if not is_video(target):   # 视频缩略图走controller抽帧队列
                    ensure_thumbnail(lib.root, str(target), fh, 512)
                imported.append((pid, fh, str(f.parent)))
                known.add(fh)
                stats["added"] += 1
            except Exception:
                if os.environ.get("BIRDTRACE_IMPORT_DEBUG"):
                    import traceback
                    traceback.print_exc()
                stats["failed"] += 1
            if progress_cb:
                progress_cb(stats["added"] + stats["skipped_dup"] + stats["failed"],
                            total, f.name)

    lib.conn.execute("UPDATE batches SET count=? WHERE id=?",
                     (stats["added"], batch_id))
    lib.conn.commit()
    # 标注随文件夹走(0.8-①): 读源文件夹的 .birdtrace.json 回填
    # (确认码/记录/鸟点/评分/无鸟); 已有编辑优先。引用模式managed目录=
    # 源目录, 之后写回同一份; copy/move的managed目录是库内目标, 导入页
    # 识别完成后的flush会自动在新目录落一份。
    try:
        from .sidecar import apply_for_imports
        stats["sidecar"] = apply_for_imports(lib, imported)
    except Exception:
        stats["sidecar"] = {"restored": 0, "spots": 0, "folders": 0}
    for _pid, _fh, _src in imported:
        lib._sidecar_touch(photo_ids=[_pid])
    try:
        stats["pairs"] = _merge_pairs(lib)
    except Exception:
        stats["pairs"] = 0
    return stats


def _merge_pairs(lib) -> int:
    """RAW/DNG同名成对编目(1.0冲刺⑧, 0.9.0第8条拍板): 本次导入的新照片
    里 同目录同stem的 JPG主文件+RAW附属(DxO降噪DNG/相机RAW) → JPG做主
    文件(识别/美学/缩略图照常, 时间线显示一次), RAW挂 raw_path/raw_hash
    (附属, 不独立参与识别); 只有RAW无JPG时RAW自己当主文件照常识别。
    历史库不受影响(只处理本次导入, 幂等: raw_path已挂的跳过)。"""
    raw_exts = {".arw", ".cr2", ".cr3", ".nef", ".raf", ".orf", ".rw2",
                ".dng", ".pef", ".srw", ".kdc", ".dcr"}
    img_exts = {".jpg", ".jpeg"}
    # 扫全库未挂raw且成对的(jpg侧)——幂等安全(已挂raw_path的jpg跳过)
    rows = lib.conn.execute(
        "SELECT id, path, file_hash FROM photos WHERE raw_path IS NULL").fetchall()
    by_key = {}
    for r in rows:
        p = Path(r["path"])
        by_key.setdefault((str(p.parent).lower(), p.stem.lower(), p.suffix.lower()),
                          r)
    n = 0
    used_raw = set()
    for (d, stem, ext), r in by_key.items():
        if ext not in img_exts:
            continue
        for rext in raw_exts:
            mate = by_key.get((d, stem, rext))
            if mate and mate["id"] not in used_raw:
                lib.conn.execute(
                    "UPDATE photos SET raw_path=?, raw_hash=? WHERE id=?",
                    (mate["path"], mate["file_hash"], r["id"]))
                # 附属行删除: 识别记录/EXIF/标签/作品集关联显式清(与
                # remove_photo同口径), 避免时间线重复出现
                for sql in ("DELETE FROM records WHERE photo_id=?",
                            "DELETE FROM exif WHERE photo_id=?",
                            "DELETE FROM photo_tags WHERE photo_id=?",
                            "DELETE FROM collection_photos WHERE photo_id=?",
                            "DELETE FROM photos WHERE id=?"):
                    lib.conn.execute(sql, (mate["id"],))
                lib._sidecar_touch(photo_ids=[r["id"]])
                used_raw.add(mate["id"])
                n += 1
                break
    if n:
        lib.conn.commit()
    return n
