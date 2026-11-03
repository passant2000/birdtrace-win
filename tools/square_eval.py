# -*- coding: utf-8 -*-
"""方形裁剪A/B: SuperPicky式(square+BICUBIC) vs 现行letterbox vs ensemble。

对照组(全部来自用户真实拍摄):
  姬鹟 5848/5876 (真值mugfly, iOS确认) / 鸭子#25-30 (真值mallar3雌鸟)
  鸥#153-176 (真值saugul2) / 鹞#442-471 (真值easmah1) / 锚点6张
只读真实库, 打印对照表, 不写任何库。

用法: .venv/Scripts/python.exe tools/square_eval.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB = Path(r"C:/Users/zhaohp2116/Documents/BirdTraceWin/catalog.db")


def main():
    from PIL import Image
    from app.ai.detector import BirdDetector
    from app.ai.classifier import BirdClassifier
    from app.ai.pipeline import load_rgb, square_crop, crop_with_margin

    con = sqlite3.connect(f"file:{LIB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    det = BirdDetector(str(PROJ / "assets/models/BirdTraceBirdDetector_YOLO11m.onnx"))
    clf = BirdClassifier(str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
                         str(PROJ / "assets/data/labels.json"))

    cases = []   # (组, 照片id或路径, 期望)
    for tag, p in (("姬鹟", PROJ / "data/fly_probe/5848.jpg"),
                   ("姬鹟", PROJ / "data/fly_probe/5876.jpg")):
        cases.append((tag, p, "mugfly"))
    for pid in range(25, 31):
        cases.append(("鸭", pid, "mallar3"))
    for pid in (153, 156, 160, 164, 168):
        cases.append(("鸥", pid, "saugul2"))
    for pid in (443, 450, 455, 461, 466):
        cases.append(("鹞", pid, "easmah1"))
    for tag, p, want in (("锚", PROJ / "data/frozen_060_src/普通翠鸟中文.jpg", "comkin1"),
                         ("锚", PROJ / "data/demo_src/Anas_platyrhynchos.jpg", "mallar3"),
                         ("锚", PROJ / "data/demo_src/Ardea_cinerea.jpg", "graher1"),
                         ("锚", PROJ / "data/demo_src/Passer_montanus.jpg", "eutspa"),
                         ("锚", PROJ / "data/demo_src/Cyanistes_caeruleus.jpg", "blutit")):
        cases.append((tag, p, want))

    stat = {"letterbox": [0, 0], "square": [0, 0], "square_m5": [0, 0]}
    print(f"{'组':4s} {'id':6s} {'期望':9s} {'letterbox':26s} {'square':26s} {'square+5%':26s}")
    for tag, ref, want in cases:
        path = ref
        if isinstance(ref, int):
            path = con.execute("SELECT path FROM photos WHERE id=?",
                               (ref,)).fetchone()[0]
        img = load_rgb(str(path))
        boxes = det.detect(img)
        line = {}
        for sname, strategy, cutter, margin in (
                ("letterbox", "letterbox", crop_with_margin, 0.05),
                ("square", "square", square_crop, 0.0),
                ("square_m5", "square", square_crop, 0.05)):
            crop = cutter(img, boxes[0]["box"], margin=margin) if cutter is square_crop \
                else cutter(img, boxes[0]["box"], margin=margin)
            top = clf.topk(crop, 1, strategy=strategy)
            code = top[0][1] if top else "?"
            conf = top[0][3] if top else 0.0
            hit = code == want
            stat[sname][0] += hit
            stat[sname][1] += 1
            line[sname] = f"{'✓' if hit else '✗'}{code} {conf:.2f}"
        print(f"{tag:4s} {str(ref):6s} {want:9s} "
              f"{line['letterbox']:26s} {line['square']:26s} {line['square_m5']:26s}",
              flush=True)

    print()
    for k, (hit, total) in stat.items():
        print(f"{k:12s}: {hit}/{total} = {hit/total*100:.0f}%")


if __name__ == "__main__":
    main()
