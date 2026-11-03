# -*- coding: utf-8 -*-
"""iOS分类模型评测: 在全部真值组上对比iOS模型 vs 现行E15(square策略)。

真值组(用户实拍+目检确认):
  鸭#25-30→mallar3(绿头鸭雌鸟) / 姬鹟5848,5876→mugfly(鸲姬鹟, iOS一致)
  鸥#153,156,160,164,168→saugul2 / 鹞#443,450,455,461,466→easmah1
  锚点5张(翠鸟/绿头鸭/苍鹭/麻雀/蓝山雀)
用法: .venv/Scripts/python.exe tools/ios_model_eval.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB = Path(r"C:/Users/zhaohp2116/Documents/BirdTraceWin/catalog.db")
IOS_MODEL = PROJ / "data/model_experiments/BirdClassifier_iOS.onnx"


def main():
    import numpy as np
    from PIL import Image
    from app.ai.detector import BirdDetector
    from app.ai.classifier import BirdClassifier, softmax, INPUT_SIZE
    from app.ai.pipeline import load_rgb, square_crop, crop_with_margin

    con = sqlite3.connect(f"file:{LIB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    det = BirdDetector(str(PROJ / "assets/models/BirdTraceBirdDetector_YOLO11m.onnx"))
    e15 = BirdClassifier(str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
                         str(PROJ / "assets/data/labels.json"))
    import onnxruntime as ort
    ios_sess = ort.InferenceSession(str(IOS_MODEL),
                                    providers=["DmlExecutionProvider",
                                               "CPUExecutionProvider"])
    ios_in = ios_sess.get_inputs()[0].name
    labels = e15.labels

    def top1_ios(crop):
        r = Image.fromarray(crop).resize((INPUT_SIZE, INPUT_SIZE), Image.BICUBIC)
        t = np.ascontiguousarray(
            np.asarray(r, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0)
        p = softmax(ios_sess.run(None, {ios_in: t})[0][0])
        i = int(np.argmax(p))
        return labels[i]["code"], float(p[i])

    def top1_e15(crop):
        top = e15.topk(crop, 1, strategy="square")
        return (top[0][1], top[0][3]) if top else ("?", 0.0)

    cases = []
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

    stat = {"E15": [0, 0], "iOS": [0, 0]}
    print(f"{'组':4s} {'id':6s} {'期望':9s} {'E15(square)':24s} {'iOS(square)':24s}")
    for tag, ref, want in cases:
        path = ref
        if isinstance(ref, int):
            path = con.execute("SELECT path FROM photos WHERE id=?",
                               (ref,)).fetchone()[0]
        img = load_rgb(str(path))
        box = det.detect(img)[0]["box"]
        crop = square_crop(img, box)
        c15, p15 = top1_e15(crop)
        cio, pio = top1_ios(crop)
        stat["E15"][0] += c15 == want
        stat["E15"][1] += 1
        stat["iOS"][0] += cio == want
        stat["iOS"][1] += 1
        print(f"{tag:4s} {str(ref)[:5]:6s} {want:9s} "
              f"{'✓' if c15 == want else '✗'}{c15} {p15:.2f}"
              f"{'':12s} {'✓' if cio == want else '✗'}{cio} {pio:.2f}", flush=True)

    print()
    for k, (hit, total) in stat.items():
        print(f"{k:6s}: {hit}/{total} = {hit/total*100:.0f}%")


if __name__ == "__main__":
    main()
