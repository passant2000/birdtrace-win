# -*- coding: utf-8 -*-
"""缩略图缓存与图像加载。

缓存: <库>/thumbnails/<hash前2位>/<hash>_<size>.webp
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageOps


def file_hash(path: str | Path) -> str:
    """内容指纹: 大小 + 首尾256KB 的 SHA1 (快速去重足够)。"""
    p = Path(path)
    h = hashlib.sha1()
    size = p.stat().st_size
    h.update(str(size).encode())
    with open(p, "rb") as f:
        head = f.read(262144)
        h.update(head)
        if size > 262144:
            f.seek(-262144, 2)
            h.update(f.read())
    return h.hexdigest()


def thumb_path(lib_root: Path, fhash: str, size: int) -> Path:
    d = lib_root / "thumbnails" / fhash[:2]
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{fhash}_{size}.webp"


def cached_thumbnail(lib_root: Path, fhash: str, size: int) -> Path | None:
    """只查缓存: 精确尺寸缩略图已存在则返回路径, 缺失不生成。"""
    tp = lib_root / "thumbnails" / fhash[:2] / f"{fhash}_{size}.webp"
    return tp if tp.exists() else None


def _cached_usable(lib_root: Path, fhash: str, size: int) -> Path | None:
    """找一张已缓存且尺寸≥size的最小缩略图(作降采样源), 无则None。"""
    best: Path | None = None
    best_sz = 10 ** 9
    try:
        for p in (lib_root / "thumbnails" / fhash[:2]).glob(f"{fhash}_*.webp"):
            try:
                sz = int(p.stem.rsplit("_", 1)[1])
            except (IndexError, ValueError):
                continue
            if size <= sz < best_sz:
                best, best_sz = p, sz
    except OSError:
        return None
    return best


def ensure_thumbnail(lib_root: Path, path: str | Path, fhash: str,
                     size: int = 512) -> Path | None:
    """生成(若缺)并返回缩略图路径。

    缺失时优先用已有的更大尺寸缓存缩略图降采样——导入时已生成512px,
    各页面要的尺寸(96~336)不必再解码高像素原图(首次打开大量图卡的
    卡顿根源); 没有任何可用缓存才回退解码原文件。
    """
    tp = thumb_path(lib_root, fhash, size)
    if tp.exists():
        return tp
    try:
        src = _cached_usable(lib_root, fhash, size)
        if src is not None:
            with Image.open(src) as im:
                im = im.convert("RGB")
                im.thumbnail((size, size), Image.LANCZOS)
                im.save(tp, "WEBP", quality=82)
            return tp
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((size, size), Image.LANCZOS)
            im.save(tp, "WEBP", quality=82)
        return tp
    except Exception:
        return None
