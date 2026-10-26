# -*- coding: utf-8 -*-
"""Lightroom式导入: 扫描 -> 去重 -> 引用或复制 -> 编目(含EXIF)。

模式:
  ref   引用原位置, 文件不动
  copy  复制到目标目录 <dest>/<拍摄年月>/文件名, 再引用副本
  move  移动到目标目录(Lightroom式), 原位置不再保留
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from PIL import Image, ImageOps

from ..db import Library
from ..exif import SUPPORTED_EXTS, read_exif
from ..media import ensure_thumbnail, file_hash


def scan_sources(paths: list[Path], recursive: bool = True) -> list[Path]:
    """从文件/文件夹列表收集支持的照片, 保持顺序去重; 一律转为绝对路径
    (引用模式记录的是原位置, 不能受程序启动目录影响)。"""
    out: list[Path] = []
    seen: set[str] = set()
    for p in paths:
        p = Path(p).resolve()
        if p.is_file():
            if p.suffix.lower() in SUPPORTED_EXTS:
                key = str(p).lower()
                if key not in seen:
                    seen.add(key)
                    out.append(p)
        elif p.is_dir():
            it = p.rglob("*") if recursive else p.iterdir()
            for f in it:
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS:
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
                        f"检查 {f.name}")

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
                if not w:
                    with Image.open(target) as im:
                        w, h = im.size
                pid = lib.add_photo(str(target), fh, fsize, fmtime, w, h, batch_id)
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
                ensure_thumbnail(lib.root, str(target), fh, 512)
                known.add(fh)
                stats["added"] += 1
            except Exception:
                stats["failed"] += 1
            if progress_cb:
                progress_cb(stats["added"] + stats["skipped_dup"] + stats["failed"],
                            total, f.name)

    lib.conn.execute("UPDATE batches SET count=? WHERE id=?",
                     (stats["added"], batch_id))
    lib.conn.commit()
    return stats
