# -*- coding: utf-8 -*-
"""2877/2826批量误识(gubter3澳洲燕鸥)诊断: 检测框内容物目视 + 多框/多裁剪分类。

背景: 用户实测这两张画框识别正确、批量识别为澳洲燕鸥(上海地理不可能)。
全策略对照显示四种裁剪全给gubter3——需确认检测框是否框错对象/含第二只鸟。

用法: .venv/Scripts/python.exe tools/tern_probe.py
输出: data/duck_probe/tern_*.jpg (带框原图+各裁剪) + 控制台分类结果
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

OUT = PROJ / "data/duck_probe"


def main():
    from PIL import Image, ImageDraw
    from app.ai.detector import BirdDetector
    from app.ai.classifier import BirdClassifier
    from app.ai.pipeline import load_rgb, square_crop, crop_with_margin

    det = BirdDetector(str(PROJ / "assets/models/BirdTraceBirdDetector_YOLO11m.onnx"))
    clf = BirdClassifier(str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
                         str(PROJ / "assets/data/labels.json"))
    OUT.mkdir(exist_ok=True)

    for tag, p in (("2877", r"F:\成片\DSC02877-20261027-DxO_DeepPRIME XD3 拷贝.jpg"),
                   ("2826", r"F:\成片\DSC02826-20261027-DxO_DeepPRIME XD3 拷贝.jpg")):
        img = load_rgb(p)
        boxes = det.detect(img)
        print(f"== {tag} {img.shape[1]}x{img.shape[0]} 检测框{len(boxes)}个 ==")
        for i, b in enumerate(boxes):
            print(f"  框{i}: conf={b['conf']:.2f} box={[round(v) for v in b['box']]}")
        # 标注全部检测框
        im = Image.fromarray(img)
        dr = ImageDraw.Draw(im)
        for i, b in enumerate(boxes):
            dr.rectangle(b["box"], outline=(255, 0, 0), width=8)
            dr.text((b["box"][0], max(0, b["box"][1] - 60)),
                    f"#{i} {b['conf']:.2f}", fill=(255, 0, 0))
        im.save(str(OUT / f"tern_{tag}_boxes.jpg"), quality=90)
        # 主框方形裁剪(现行管线输入)
        if boxes:
            crop = square_crop(img, boxes[0]["box"], margin=0.08)
            Image.fromarray(crop).save(str(OUT / f"tern_{tag}_crop.jpg"), quality=90)
            top = clf.topk(crop, 3, strategy="square")
            print("  现行分类:", [(t[1], round(t[3], 2)) for t in top])
    print(f"标注图已存 {OUT}")


if __name__ == "__main__":
    main()
