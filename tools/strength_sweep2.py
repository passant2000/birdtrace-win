# -*- coding: utf-8 -*-
"""先验强度扫描v2: square+mask裁剪 × 强度{0.6,0.7,0.8,1.0}全真值组对照。

背景: 2877/2826鸥嘴噪鸥raw分差2.41 logits, 先验修正需强度≥0.70才翻正
(gubter3澳洲种-1.44 vs gubter2本尊+2.00)。扫描各强度在全部真值组的表现,
确认提升强度无副作用(锚点/鸥/鹞/姬鹟不回归)。
用法: .venv/Scripts/python.exe tools/strength_sweep2.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB = Path(r"C:/Users/zhaohp2116/Documents/BirdTraceWin/catalog.db")
MASK_GREY = 114


def main():
    import numpy as np
    from app.ai.detector import BirdDetector
    from app.ai.classifier import BirdClassifier
    from app.ai.geo_prior import GeoPrior
    from app.ai.pipeline import load_rgb, square_crop

    con = sqlite3.connect(f"file:{LIB.as_posix()}?mode=ro", uri=True)
    det = BirdDetector(str(PROJ / "assets/models/BirdTraceBirdDetector_YOLO11m.onnx"))
    clf = BirdClassifier(str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
                         str(PROJ / "assets/data/labels.json"))
    prior = GeoPrior(str(PROJ / "assets/data/geo_prior.sqlite"), strength=0.6)

    cases = []
    for tag, p in (("姬鹟", PROJ / "data/fly_probe/5848.jpg"),
                   ("姬鹟", PROJ / "data/fly_probe/5876.jpg")):
        cases.append((tag, p, "mugfly"))
    for pid in range(25, 31):
        cases.append(("鸭", pid, "mallar3"))
    for pid in (153, 160, 168):
        cases.append(("鸥", pid, "saugul2"))
    for pid in (443, 455, 466):
        cases.append(("鹞", pid, "easmah1"))
    for tag, p, want in (("锚", PROJ / "data/frozen_060_src/普通翠鸟中文.jpg", "comkin1"),
                         ("锚", PROJ / "data/demo_src/Anas_platyrhynchos.jpg", "mallar3"),
                         ("锚", PROJ / "data/demo_src/Ardea_cinerea.jpg", "graher1"),
                         ("锚", PROJ / "data/demo_src/Passer_montanus.jpg", "eutspa"),
                         ("锚", PROJ / "data/demo_src/Cyanistes_caeruleus.jpg", "blutit")):
        cases.append((tag, p, want))

    # 预计算每例的logits与先验向量
    items = []
    for tag, ref, want in cases:
        path = ref
        if isinstance(ref, int):
            path = con.execute("SELECT path FROM photos WHERE id=?",
                               (ref,)).fetchone()[0]
        img = load_rgb(str(path))
        box = det.detect(img)[0]["box"]
        crop = square_crop(img, box, margin=0.08)
        crop = crop.copy()
        crop[int(crop.shape[0] * 0.75):, :] = MASK_GREY
        logits = clf.logits(crop, "square")
        pv = prior.region_vector("CN-SH")
        items.append((tag, str(ref)[:5], want, logits, pv))

    print(f"{'case':8s} {'原始':22s} " +
          " ".join(f"s={s:<4.2f}" for s in (0.6, 0.7, 0.8, 1.0)))
    stat = {s: [0, 0] for s in (0.6, 0.7, 0.8, 1.0)}
    for tag, cid, want, logits, pv in items:
        lp = logits - logits.max() - np.log(np.exp(logits - logits.max()).sum())
        line = {}
        for s in (0.6, 0.7, 0.8, 1.0):
            sc = lp + s * pv
            j = int(np.argmax(sc))
            code = clf.labels[j]["code"]
            hit = code == want
            stat[s][0] += hit
            stat[s][1] += 1
            line[s] = f"{'✓' if hit else '✗'}{code}"
        raw_j = int(np.argmax(logits))
        raw_code = clf.labels[raw_j]["code"]
        raw_hit = raw_code == want
        print(f"{tag:4s} {cid:6s} {want:9s} "
              f"{'✓' if raw_hit else '✗'}{raw_code:10s} "
              + " ".join(f"{line[s]:12s}" for s in (0.6, 0.7, 0.8, 1.0)), flush=True)

    print()
    for s, (hit, total) in stat.items():
        print(f"strength={s}: {hit}/{total} = {hit/total*100:.0f}%")


if __name__ == "__main__":
    main()
