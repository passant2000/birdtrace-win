# -*- coding: utf-8 -*-
"""矩形(画框同款) vs 方形(现行) 裁剪全组对照。

背景: 用户实测5876画框识别正确、批量识别错误——两者仅裁剪几何不同
(画框=矩形框+5%外扩+直接缩放; 批量=检测框方形化+8%外扩)。
本评测对全部真值组跑两种裁剪的完整管线(检测→裁剪→分类→CN-SH先验),
对照最终记录与真值, 数据决定批量路径用哪种。

用法: .venv/Scripts/python.exe tools/rect_vs_square_eval.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB = Path(r"C:/Users/zhaohp2116/Documents/BirdTraceWin/catalog.db")


def main():
    import numpy as np
    from app.ai.detector import BirdDetector
    from app.ai.classifier import BirdClassifier, softmax
    from app.ai.geo_prior import GeoPrior
    from app.ai.pipeline import load_rgb, square_crop, crop_with_margin, REJECT_GPROB

    con = sqlite3.connect(f"file:{LIB.as_posix()}?mode=ro", uri=True)
    det = BirdDetector(str(PROJ / "assets/models/BirdTraceBirdDetector_YOLO11m.onnx"))
    clf = BirdClassifier(str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
                         str(PROJ / "assets/data/labels.json"))
    prior = GeoPrior(str(PROJ / "assets/data/geo_prior.sqlite"), strength=0.6)

    def final_record(img, box, mode):
        crop = (square_crop(img, box, margin=0.08) if mode == "square"
                else crop_with_margin(img, box, margin=0.05))
        logits = clf.logits(crop, "square")   # 直接缩放BICUBIC(两种模式同款)
        lp, sc = prior.rerank(logits, "CN-SH", 11)
        j = int(np.argmax(sc))
        gprob = float(np.exp(sc.max() - np.logaddexp.reduce(sc)))
        if gprob < REJECT_GPROB:
            return "REJECT", gprob
        return clf.labels[j]["code"], gprob

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

    stat = {"矩形": [0, 0], "方形": [0, 0]}
    print(f"{'组':4s} {'id':8s} {'期望':9s} {'矩形(画框同款)':24s} {'方形(现行)':24s}")
    for tag, ref, want in cases:
        path = ref
        if isinstance(ref, int):
            path = con.execute("SELECT path FROM photos WHERE id=?",
                               (ref,)).fetchone()[0]
        img = load_rgb(str(path))
        box = det.detect(img)[0]["box"]
        line = {}
        for mode in ("矩形", "方形"):
            code, gprob = final_record(img, box, mode)
            hit = code == want
            stat[mode][0] += hit
            stat[mode][1] += 1
            line[mode] = f"{'✓' if hit else '✗'}{code} {gprob:.2f}"
        print(f"{tag:4s} {str(ref)[:5]:8s} {want:9s} "
              f"{line['矩形']:24s} {line['方形']:24s}", flush=True)

    print()
    for k, (hit, total) in stat.items():
        print(f"{k:6s}: {hit}/{total} = {hit/total*100:.0f}%")


if __name__ == "__main__":
    main()
