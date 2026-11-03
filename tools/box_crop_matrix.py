# -*- coding: utf-8 -*-
"""检测框x裁剪策略矩阵: 找出让5848/5876/鸭子段全对的组合。

用例: 5848/5876(真值mugfly) + 鸭#25-30(真值mallar3)
维度: 检测器{YOLO11m, nano} x 裁剪{square, square+5%外扩, letterbox, squash}
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))


def main():
    from app.ai.detector import BirdDetector
    from app.ai.classifier import BirdClassifier
    from app.ai.pipeline import load_rgb, square_crop, crop_with_margin

    con = sqlite3.connect(
        r"file:C:/Users/zhaohp2116/Documents/BirdTraceWin/catalog.db?mode=ro",
        uri=True)
    det_m = BirdDetector(str(PROJ / "assets/models/BirdTraceBirdDetector_YOLO11m.onnx"))
    det_n = BirdDetector(str(PROJ / "assets/models/BirdTraceBirdDetector_FP32.onnx"))
    clf = BirdClassifier(str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
                         str(PROJ / "assets/data/labels.json"))

    cases = [("5848", PROJ / "data/fly_probe/5848.jpg", "mugfly"),
             ("5876", PROJ / "data/fly_probe/5876.jpg", "mugfly")]
    for pid in range(25, 31):
        p = con.execute("SELECT path FROM photos WHERE id=?", (pid,)).fetchone()[0]
        cases.append((f"#{pid}", p, "mallar3"))

    print(f"{'case':7s} {'det':5s} {'crop':11s} top1")
    for tag, p, want in cases:
        img = load_rgb(str(Path(p).resolve()))
        for dname, det in (("m", det_m), ("nano", det_n)):
            box = det.detect(img)[0]["box"]
            for cname, strategy, margin in (
                    ("square", "square", 0.0),
                    ("square+5%", "square", 0.05),
                    ("letterbox", "letterbox", 0.05),
                    ("squash", "squash", 0.05)):
                crop = (square_crop(img, box, margin=margin)
                        if cname.startswith("square")
                        else crop_with_margin(img, box, margin=margin))
                t = clf.topk(crop, 1, strategy=strategy)
                code = t[0][1] if t else "?"
                conf = t[0][3] if t else 0.0
                mark = "✓" if code == want else " "
                print(f"{mark}{tag:6s} {dname:5s} {cname:11s} {code} {conf:.2f}",
                      flush=True)


if __name__ == "__main__":
    main()
