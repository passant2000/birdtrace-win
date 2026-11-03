# -*- coding: utf-8 -*-
"""先验强度扫描: 以iOS已知正确结果为校准基准, 找不翻错5876的强度区间。

用例: 5876(真值mugfly, iOS对)/5848(同)/鸥#153(真值saugul2)/鹞#443(真值easmah1)
     /鸭#25-30(真值mallar3——已知模型层困难组, 观察不作为主要判据)
用法: .venv/Scripts/python.exe tools/prior_strength_sweep.py
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
    from app.ai.pipeline import load_rgb, square_crop
    from app.ai.geo_prior import GeoPrior  # 若与pipeline内实现不同则跟随pipeline

    con = sqlite3.connect(f"file:{LIB.as_posix()}?mode=ro", uri=True)
    det = BirdDetector(str(PROJ / "assets/models/BirdTraceBirdDetector_YOLO11m.onnx"))
    clf = BirdClassifier(str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
                         str(PROJ / "assets/data/labels.json"))
    prior = GeoPrior(str(PROJ / "assets/data/geo_prior.sqlite"), strength=0.6)
    code_idx = {l["code"]: i for i, l in enumerate(clf.labels)}

    cases = [("5876", PROJ / "data/fly_probe/5876.jpg", "mugfly"),
             ("5848", PROJ / "data/fly_probe/5848.jpg", "mugfly"),
             ("鸥153", 153, "saugul2"),
             ("鹞443", 443, "easmah1"),
             ("鸭25", 25, "mallar3"),
             ("鸭27", 27, "mallar3"),
             ("鸭30", 30, "mallar3")]

    print(f"{'case':6s} {'原始':22s} " +
          " ".join(f"s={s:<4.1f}" for s in (0.0, 0.2, 0.3, 0.4, 0.6)))
    for tag, ref, want in cases:
        path = ref
        if isinstance(ref, int):
            path = con.execute("SELECT path FROM photos WHERE id=?",
                               (ref,)).fetchone()[0]
        img = load_rgb(str(path))
        box = det.detect(img)[0]["box"]
        crop = square_crop(img, box)
        raw = softmax(clf.logits(crop, "square"))
        i = int(np.argmax(raw))
        line = f"{tag:6s} {labels_top(clf, raw):22s}"
        for s in (0.0, 0.2, 0.3, 0.4, 0.6):
            lp, sc = prior.rerank(clf.logits(crop, "square"), "CN-SH", 10)
            prior.strength = s
            lp, sc = prior.rerank(clf.logits(crop, "square"), "CN-SH", 10)
            j = int(np.argmax(sc))
            code = clf.labels[j]["code"]
            mark = "✓" if code == want else "✗"
            line += f" {mark}{code:<10s}"
        print(line, flush=True)


def labels_top(clf, probs):
    import numpy as np
    i = int(np.argmax(probs))
    return f"{clf.labels[i]['code']} {probs[i]:.2f}"


if __name__ == "__main__":
    main()
