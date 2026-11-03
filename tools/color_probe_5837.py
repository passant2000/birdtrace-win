# -*- coding: utf-8 -*-
"""5837色彩/曝光敏感性诊断: 像素统计对比 + 扰动实验。

三张近乎相同的鸲姬鹟雄鸟连拍(5848/5876→mugfly正确, 5837→slbfly1 0.99):
若5837的色温/曝光与另两张有系统性差异, 扰动实验能找到翻正的参数轴,
从而设计通用的测试时增强(TTA)方案。

用法: .venv/Scripts/python.exe tools/color_probe_5837.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))


def main():
    import numpy as np
    from app.ai.detector import BirdDetector
    from app.ai.classifier import BirdClassifier
    from app.ai.pipeline import load_rgb, square_crop

    det = BirdDetector(str(PROJ / "assets/models/BirdTraceBirdDetector_YOLO11m.onnx"))
    clf = BirdClassifier(str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
                         str(PROJ / "assets/data/labels.json"))

    crops = {}
    stats = {}
    for tag in ("5837", "5848", "5876"):
        p = rf"F:\成片\DSC0{tag}-20261027-DxO_DeepPRIME XD3-南汇-.jpg"
        img = load_rgb(p)
        box = det.detect(img)[0]["box"]
        crop = square_crop(img, box, margin=0.08)
        crop = crop.copy()
        crop[int(crop.shape[0] * 0.75):, :] = 114   # 与批量管线一致(下部遮蔽)
        # 只统计鸟体区域(上75%中的中心区)
        h = crop.shape[0]
        body = crop[int(h * 0.15):int(h * 0.70), int(crop.shape[1] * 0.2):int(crop.shape[1] * 0.8)]
        crops[tag] = crop
        stats[tag] = (body.mean(axis=(0, 1)), body.std(axis=(0, 1)))
        print(f"{tag}: 鸟体均值RGB = {np.round(stats[tag][0], 1)}, "
              f"标准差 = {np.round(stats[tag][1], 1)}")

    print("\n== 5837扰动实验(找翻正的参数轴) ==")
    crop = crops["5837"].astype(np.float32)

    def cls(arr, name):
        arr8 = np.clip(arr, 0, 255).astype(np.uint8)
        t = clf.topk(arr8, 2, strategy="square")
        code, conf = (t[0][1], t[0][3]) if t else ("?", 0)
        print(f"  {name:24s} → {code} {conf:.2f}", flush=True)
        return code

    cls(crop, "原样")
    cls(crop * 0.85, "曝光-15%")
    cls(crop * 1.15, "曝光+15%")
    cls(crop ** (1 / 1.2), "伽马提亮1.2")
    cls(crop ** 1.2, "伽马压暗1.2")
    # 灰世界白平衡(把各通道均值拉平)
    means = crop.mean(axis=(0, 1))
    gray = crop.mean()
    gw = crop * (gray / means)[None, None, :]
    cls(gw, "灰世界白平衡")
    # 绿通道抑制(5837背景偏绿)
    gsup = crop.copy()
    gsup[:, :, 1] *= 0.9
    cls(gsup, "绿通道-10%")
    # 饱和度+20%
    gray_l = crop.mean(axis=2, keepdims=True)
    cls(gray_l + (crop - gray_l) * 1.2, "饱和度+20%")
    # 高斯轻度模糊/锐化(用PIL)
    from PIL import Image, ImageFilter
    pil = Image.fromarray(np.clip(crop, 0, 255).astype(np.uint8))
    cls(np.asarray(pil.filter(ImageFilter.GaussianBlur(2)), dtype=np.float32),
        "高斯模糊2px")


if __name__ == "__main__":
    main()
