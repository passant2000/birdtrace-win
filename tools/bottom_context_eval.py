# -*- coding: utf-8 -*-
"""下部上下文处理A/B: 现行(不处理) vs 去下20% vs 涂灰下25%——全部真值组对照。

动机: 5876实测——检测框下部的栖木/枝干上下文把分类带偏(slbfly1 0.68),
去下20%后mugfly 0.88、涂灰后0.65; 5848不受影响。需验证对其他组无副作用。

用法: .venv/Scripts/python.exe tools/bottom_context_eval.py
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
    from app.ai.pipeline import load_rgb, square_crop

    con = sqlite3.connect(f"file:{LIB.as_posix()}?mode=ro", uri=True)
    det = BirdDetector(str(PROJ / "assets/models/BirdTraceBirdDetector_YOLO11m.onnx"))
    clf = BirdClassifier(str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
                         str(PROJ / "assets/data/labels.json"))

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

    def classify(crop):
        top = clf.topk(crop, 1, strategy="square")
        return (top[0][1], round(top[0][3], 2)) if top else ("?", 0.0)

    stat = {"现行": [0, 0], "去下20%": [0, 0], "涂灰25%": [0, 0]}
    diffs = []
    print(f"{'组':4s} {'id':6s} {'期望':9s} {'现行':22s} {'去下20%':22s} {'涂灰25%':22s}")
    for tag, ref, want in cases:
        path = ref
        if isinstance(ref, int):
            path = con.execute("SELECT path FROM photos WHERE id=?",
                               (ref,)).fetchone()[0]
        img = load_rgb(str(path))
        box = det.detect(img)[0]["box"]
        sq = square_crop(img, box, margin=0.08)
        h = sq.shape[0]
        trim = sq[:int(h * 0.8), :]
        masked = sq.copy()
        masked[int(h * 0.75):, :] = MASK_GREY
        line = {}
        for mode, c in (("现行", sq), ("去下20%", trim), ("涂灰25%", masked)):
            code, conf = classify(c)
            hit = code == want
            stat[mode][0] += hit
            stat[mode][1] += 1
            if mode != "现行":
                hit0 = code == want
                if hit != hit0:
                    diffs.append((tag, str(ref)[:5], mode, code, conf))
            line[mode] = f"{'✓' if hit else '✗'}{code} {conf:.2f}"
        print(f"{tag:4s} {str(ref)[:5]:6s} {want:9s} "
              f"{line['现行']:22s} {line['去下20%']:22s} {line['涂灰25%']:22s}",
              flush=True)

    print()
    for k, (hit, total) in stat.items():
        print(f"{k:8s}: {hit}/{total} = {hit/total*100:.0f}%")
    print("与现行差异的用例:", diffs if diffs else "无")


if __name__ == "__main__":
    main()
