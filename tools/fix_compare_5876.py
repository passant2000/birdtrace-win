# -*- coding: utf-8 -*-
"""5876/5848修法对比: nano框 / 去栖木下缘 / 框外涂灰。"""
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

import numpy as np
from app.ai.pipeline import load_rgb, square_crop
from app.ai.detector import BirdDetector
from app.ai.classifier import BirdClassifier

clf = BirdClassifier(str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
                     str(PROJ / "assets/data/labels.json"))
det_m = BirdDetector(str(PROJ / "assets/models/BirdTraceBirdDetector_YOLO11m.onnx"))
det_n = BirdDetector(str(PROJ / "assets/models/BirdTraceBirdDetector_FP32.onnx"))


def t(crop):
    top = clf.topk(crop, 1, strategy="square")
    return (top[0][1], round(top[0][3], 2)) if top else ("?", 0)


for tag, p, want in (("5876", r"F:\成片\DSC05876-20261027-DxO_DeepPRIME XD3-南汇-.jpg", "mugfly"),
                     ("5848", r"F:\成片\DSC05848-20261027-DxO_DeepPRIME XD3-南汇-.jpg", "mugfly")):
    img = load_rgb(p)
    bm = det_m.detect(img)[0]["box"]
    bn = det_n.detect(img)[0]["box"]
    print(f"== {tag} (真值{want}) ==")
    print(f"  m框 {[round(v) for v in bm]} | nano框 {[round(v) for v in bn]}")
    print("  [1] nano框+square:", t(square_crop(img, bn)))
    x1, y1, x2, y2 = [int(v) for v in bm]
    bh = y2 - y1
    crop_trim = img[y1:int(y1 + bh * 0.8), x1:x2]
    print("  [2] m框去下20%+square:",
          t(crop_trim))
    sq = square_crop(img, bm, margin=0.08)
    sq2 = sq.copy()
    sq2[int(sq2.shape[0] * 0.75):, :] = 114
    print("  [3] square+涂灰下25%:", t(sq2))
