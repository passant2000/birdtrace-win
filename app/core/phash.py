# -*- coding: utf-8 -*-
"""感知哈希(dHash 64bit) —— 连拍分组(0.8-③)与年度十八图去重(0.8-⑦)共用。

dHash: 9x8灰度逐行比较相邻像素亮度, 64bit; 对缩放/轻微亮度变化鲁棒,
构图/姿态不同则距离大。从缩略图计算(缓存优先), 原图离线也能算(0.8-②)。

缓存: photos.phash(16位hex, NULL=未算), 由 Library.phash_of 读写。
"""
from __future__ import annotations

from pathlib import Path

# 连拍分组: 汉距 ≤ BURST_SAME_MAX 视为"同一构图"(同一次按快门的连拍帧)
BURST_SAME_MAX = 10
# 年度十八图第2张放宽: 汉距 ≥ BEST18_DIFF_MIN 视为"构图/姿态不同"
BEST18_DIFF_MIN = 12


def dhash_image(im) -> str:
    """PIL Image → 64bit dHash(16位hex字符串)。"""
    g = im.convert("L").resize((9, 8))
    px = list(g.getdata())
    bits = 0
    for row in range(8):
        base = row * 9
        for col in range(8):
            bits = (bits << 1) | (1 if px[base + col] > px[base + col + 1] else 0)
    return f"{bits:016x}"


def dhash_file(path: str | Path) -> str | None:
    """图片文件 → dHash; 解码失败返回None。"""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return dhash_image(im)
    except Exception:
        return None


def hamming(a: str | None, b: str | None) -> int | None:
    """两个hex哈希的汉明距离; 任一缺失返回None。"""
    if not a or not b:
        return None
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return None
