# -*- coding: utf-8 -*-
"""5837深挖: 检测框来源x裁剪形状x缩放插值x颜色通道 全矩阵扫描。

背景: iOS(作者管线)识别5837正确(mugfly), Win端全策略slbfly1。
同一E15模型下必然存在输入差异——全矩阵找出mugfly出现的条件。

用法: .venv/Scripts/python.exe tools/probe_5837.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))


def main():
    import numpy as np
    from PIL import Image
    from app.ai.pipeline import load_rgb, square_crop, crop_with_margin
    from app.ai.detector import BirdDetector
    from app.ai.classifier import BirdClassifier, INPUT_SIZE

    p = r"F:\成片\DSC05837-20261027-DxO_DeepPRIME XD3-南汇-.jpg"
    img = load_rgb(p)
    H, W = img.shape[:2]
    det_m = BirdDetector(str(PROJ / "assets/models/BirdTraceBirdDetector_YOLO11m.onnx"))
    det_n = BirdDetector(str(PROJ / "assets/models/BirdTraceBirdDetector_FP32.onnx"))
    clf = BirdClassifier(str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
                         str(PROJ / "assets/data/labels.json"))

    def top(arr):
        t = np.asarray(Image.fromarray(arr).resize(
            (INPUT_SIZE, INPUT_SIZE), Image.BICUBIC), dtype=np.float32) / 255.0
        t = np.ascontiguousarray(t.transpose(2, 0, 1)[None])
        p = np.exp(t * 0)  # placeholder
        # 用classifier的session直接跑(避免normalize重复)
        tt = np.ascontiguousarray(np.asarray(
            Image.fromarray(arr).resize((INPUT_SIZE, INPUT_SIZE),
                                        Image.BICUBIC),
            dtype=np.float32).transpose(2, 0, 1)[None] / 255.0)
        pr = np.exp(clf.session.run([clf.output_name],
                                    {clf.input_name: tt})[0][0] -
                    clf.session.run([clf.output_name],
                                    {clf.input_name: tt})[0][0].max())
        pr = pr / pr.sum()
        i = int(np.argmax(pr))
        return clf.labels[i]["code"], round(float(pr[i]), 2)

    for dtag, det in (("m", det_m), ("nano", det_n)):
        box = det.detect(img)[0]["box"]
        x1, y1, x2, y2 = [int(v) for v in box]
        bw, bh = x2 - x1, y2 - y1
        cx, cy = x1 + bw / 2, y1 + bh / 2
        print(f"== {dtag}检测框 {bw}x{bh} ==")
        variants = [
            ("原始矩形", img[y1:y2, x1:x2]),
            ("矩形+5%", img[max(0, y1 - int(bh * .05)):min(H, y2 + int(bh * .05)),
                            max(0, x1 - int(bw * .05)):min(W, x2 + int(bw * .05))]),
            ("矩形+15%", img[max(0, y1 - int(bh * .15)):min(H, y2 + int(bh * .15)),
                             max(0, x1 - int(bw * .15)):min(W, x2 + int(bw * .15))]),
            ("方形+0%", square_crop(img, box, margin=0.0)),
            ("方形+8%", square_crop(img, box, margin=0.08)),
            ("方形+20%", square_crop(img, box, margin=0.20)),
        ]
        for name, crop in variants:
            rgb = top(crop)
            bgr = top(crop[::-1, :, ::-1] if False else crop[:, :, ::-1])
            print(f"  {name:10s} RGB→{rgb[0]} {rgb[1]:5.2f} | "
                  f"BGR→{bgr[0]} {bgr[1]:5.2f}", flush=True)


if __name__ == "__main__":
    main()
