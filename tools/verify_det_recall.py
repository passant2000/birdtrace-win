# -*- coding: utf-8 -*-
"""两阶段检测验证: 分块召回生效/有检出路径不变/无误检/确定性。

覆盖:
[1] Z8全画幅难例: 全图原本0检出, 分块召回须在已知鸟区检出(conf≥0.5)
[2] 对照图(已知可检): 走全图快路径, 结果与历史一致
[3] 纯色大图: 分块不产生误检(FP)
[4] 小图无鸟: 不触发分块(门槛), 快速返回0
[5] 确定性: 同一输入两遍detect结果逐位一致(DML mem_pattern修复)

用法: .venv/Scripts/python.exe tools/verify_det_recall.py
需要检测模型与 data/raw_probe_extract.jpg 夹具(Z8 NEF内嵌JPEG提取件)。
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB_DIR = PROJ / "data/det_recall_check"
FAILED = {"v": False}
BIRD_REGION = (2000, 3300, 3900, 4150)   # 已知鸟区(x1,y1,x2,y2), 原型实测框


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def main():
    if LIB_DIR.exists():
        shutil.rmtree(LIB_DIR)
    LIB_DIR.mkdir(parents=True)

    import numpy as np
    from PIL import Image
    from app import paths
    from app.ai.detector import DETECTOR_MODEL
    from app.ai.detector_seg import SEG_DETECTOR_MODEL, BirdSegDetector

    mp = paths.assets_dir() / "models" / DETECTOR_MODEL
    check(mp.exists(), f"检测模型存在({DETECTOR_MODEL})")
    if DETECTOR_MODEL == SEG_DETECTOR_MODEL:
        det = BirdSegDetector(str(mp), conf_thr=0.25, use_gpu=True)
    else:
        from app.ai.detector import BirdDetector
        det = BirdDetector(str(mp), conf_thr=0.25, use_gpu=True)

    print("\n[1] Z8全画幅难例(分块召回)")
    frame = np.asarray(Image.open(
        PROJ / "data/raw_probe_extract.jpg").convert("RGB"))
    check(frame.shape[0] > 5000, f"夹具为全尺寸帧 {frame.shape[1]}x{frame.shape[0]}")
    t0 = time.perf_counter()
    boxes = det.detect(frame)
    dt = (time.perf_counter() - t0) * 1000
    check(len(boxes) >= 1, f"分块召回检出 {len(boxes)} 个 ({dt:.0f}ms)")
    if boxes:
        x1, y1, x2, y2 = boxes[0]["box"]
        ix1, iy1, ix2, iy2 = BIRD_REGION
        inter = (min(x2, ix2) - max(x1, ix1)) * (min(y2, iy2) - max(y1, iy1))
        area = (x2 - x1) * (y2 - y1)
        check(boxes[0]["conf"] >= 0.5 and area > 0
              and inter / area > 0.5,
              f"框落在已知鸟区且conf达标 ({boxes[0]['conf']:.3f}, "
              f"[{x1:.0f},{y1:.0f},{x2:.0f},{y2:.0f}])")

    print("\n[2] 对照图(全图快路径, 行为不变)")
    kf = np.asarray(Image.open(
        PROJ / "data/frozen_060_src/普通翠鸟中文.jpg").convert("RGB"))
    bk = det.detect(kf)
    check(len(bk) == 1 and bk[0]["conf"] > 0.9,
          f"翠鸟对照1检出 conf={bk[0]['conf'] if bk else None:.3f}"
          if bk else "翠鸟对照0检出")
    t0 = time.perf_counter()
    det.detect(kf)
    dt = (time.perf_counter() - t0) * 1000
    # l-seg@1024 CPU约2s(DML几十ms); m@640时代标准是200ms
    check(dt < 3500, f"有检出路径不分块, 耗时 {dt:.0f}ms")

    print("\n[3] 纯色大图(分块不误检)")
    plain = np.full((4000, 3000, 3), (90, 140, 90), np.uint8)
    check(det.detect(plain) == [], "纯色大图0误检")

    print("\n[4] 小图无鸟(不触发分块)")
    small = np.full((600, 450, 3), (90, 140, 90), np.uint8)
    t0 = time.perf_counter()
    check(det.detect(small) == [], "小图无鸟0误检")
    # l-seg@1024 CPU单趟约2s, 分块是9趟~18s; 快路径语义=不触发分块
    check((time.perf_counter() - t0) * 1000 < 3500, "小图走快路径")

    print("\n[5] 确定性(DML mem_pattern修复)")
    r1 = det.detect(frame)
    r2 = det.detect(frame)
    same = (len(r1) == len(r2) and all(
        a["box"] == b["box"] and a["conf"] == b["conf"]
        for a, b in zip(r1, r2)))
    check(same, "同输入两遍detect结果完全一致")

    shutil.rmtree(LIB_DIR, ignore_errors=True)
    print()
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
