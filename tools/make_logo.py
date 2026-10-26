# -*- coding: utf-8 -*-
"""从 Gemini 生成的"伪透明"JPG(棋盘格底)抠出小鸟logo。

管线( v2, 修 v1 把鸟身浅灰阴影打穿的缺陷 ):
  1. 边界BFS: 只清与图像边界连通的棋盘灰(黑轮廓挡住, 鸟身不受影响)
  2. 轮廓外侧光晕: 紧邻已透明区、颜色仍接近底色(放宽阈) → 清
  3. 封闭空隙(腿间/尾下, 边界BFS进不去): 逐连通块判定——
     棋盘格必含大量深灰格(≈195), 鸟身阴影永无此特征;
     块内"严格深灰格"占比≥5% 才整块清除, 否则保留(是鸟身阴影)
产物: assets/brand/logo.png + logo.ico + data/logo_preview.png(深底预览)
"""
from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

PROJ = Path(__file__).resolve().parent.parent
SRC = Path(__file__).resolve().parent.parent / "data" / "model_experiments" / "logo_source.png"   # 生成logo的原始图(本地放, 不随仓库分发)
OUT_DIR = PROJ / "assets" / "brand"
PREVIEW = PROJ / "data" / "logo_preview.png"

BG1 = np.array([195, 195, 195], dtype=np.int16)   # 深灰格
BG2 = np.array([236, 236, 236], dtype=np.int16)   # 浅灰格


def gray_like(arr: np.ndarray, center: np.ndarray, tol: int, max_chroma: int):
    a = arr.astype(np.int16)
    d = np.abs(a - center).max(axis=2)
    chroma = a.max(axis=2) - a.min(axis=2)
    return (d < tol) & (chroma < max_chroma)


def is_bg(arr: np.ndarray, tol: int) -> np.ndarray:
    return gray_like(arr, BG1, tol, 16) | gray_like(arr, BG2, tol, 16)


def label_components(mask: np.ndarray):
    """4邻域连通块, 返回 list[(pixels_y, pixels_x)]。"""
    h, w = mask.shape
    seen = np.zeros_like(mask)
    comps = []
    ys, xs = np.where(mask)
    for y0, x0 in zip(ys, xs):
        if seen[y0, x0]:
            continue
        seen[y0, x0] = True
        dq = deque([(y0, x0)])
        pix = []
        while dq:
            y, x = dq.popleft()
            pix.append((y, x))
            for ny, nx in ((y-1, x), (y+1, x), (y, x-1), (y, x+1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    dq.append((ny, nx))
        comps.append(pix)
    return comps


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    im = Image.open(SRC).convert("RGB")
    arr = np.array(im)
    h, w = arr.shape[:2]

    # 1) 边界多种子BFS
    bg = is_bg(arr, 26)
    visited = np.zeros((h, w), dtype=bool)
    dq = deque()
    for x in range(w):
        for y in (0, h - 1):
            if bg[y, x]:
                visited[y, x] = True
                dq.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if bg[y, x] and not visited[y, x]:
                visited[y, x] = True
                dq.append((y, x))
    while dq:
        y, x = dq.popleft()
        for ny, nx in ((y-1, x), (y+1, x), (y, x-1), (y, x+1)):
            if 0 <= ny < h and 0 <= nx < w and bg[ny, nx] and not visited[ny, nx]:
                visited[ny, nx] = True
                dq.append((ny, nx))

    alpha = np.where(visited, 0, 255).astype(np.uint8)

    # 2) 轮廓外侧光晕: 与透明区相邻(膨胀2圈)且仍接近底色 → 清
    trans = alpha == 0
    for _ in range(2):
        grow = trans.copy()
        grow[1:, :] |= trans[:-1, :]
        grow[:-1, :] |= trans[1:, :]
        grow[:, 1:] |= trans[:, :-1]
        grow[:, :-1] |= trans[:, 1:]
        trans = grow
    halo = trans & (alpha == 255) & is_bg(arr, 45)
    alpha[halo] = 0

    # 3) 封闭空隙逐块判定: 含≥5%严格深灰格 → 棋盘空隙, 整块清; 否则是鸟身阴影, 保留
    cand = (alpha == 255) & is_bg(arr, 26)
    strict_dark = gray_like(arr, BG1, 10, 6)
    cleared = kept = 0
    for comp in label_components(cand):
        if len(comp) < 24:      # 噪点
            continue
        n_dark = sum(1 for y, x in comp if strict_dark[y, x])
        if n_dark >= 0.05 * len(comp):
            for y, x in comp:
                alpha[y, x] = 0
            cleared += len(comp)
        else:
            kept += len(comp)
    print(f"封闭块: 清除棋盘空隙 {cleared} px, 保留鸟身阴影 {kept} px")

    rgba = np.dstack([arr, alpha])
    ys, xs = np.where(alpha > 0)
    y0, y1 = max(0, ys.min() - 12), min(h, ys.max() + 13)
    x0, x1 = max(0, xs.min() - 12), min(w, xs.max() + 13)
    out = Image.fromarray(rgba[y0:y1, x0:x1])
    out.save(OUT_DIR / "logo.png")
    print("logo.png", out.size)

    side = max(out.size)
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(out, ((side - out.width) // 2, (side - out.height) // 2))
    sq.save(OUT_DIR / "logo.ico", sizes=[(256, 256), (128, 128), (64, 64),
                                         (48, 48), (32, 32), (16, 16)])
    print("logo.ico written")

    prev = Image.new("RGB", out.size, (30, 60, 90))
    prev.paste(out, (0, 0), out)
    prev.save(PREVIEW)
    op = (np.array(out)[:, :, 3] == 255)
    print(f"不透明占比: {op.mean()*100:.1f}% (鸟身应占大头, 明显偏低=误清)")


if __name__ == "__main__":
    sys.exit(main())
