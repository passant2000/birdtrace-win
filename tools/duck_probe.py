# -*- coding: utf-8 -*-
"""鸭子误识诊断: 对指定照片跑现行管线, 双检测器对比, 裁剪落盘供目视。

用法: .venv/Scripts/python.exe tools/duck_probe.py F:\\成片\\xxx.jpg [更多路径...]
输出: data/duck_probe/<n>_m框.jpg / <n>_nano框.jpg (带框标注原图) + 控制台结果
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

OUT = PROJ / "data/duck_probe"
OUT.mkdir(exist_ok=True)


def main():
    from PIL import Image, ImageDraw
    from app.ai.detector import BirdDetector
    from app.ai.pipeline import RecognitionPipeline, load_rgb
    from app.exif import month_of

    paths = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not paths:
        print("usage: duck_probe.py <photo.jpg> ...")
        sys.exit(1)

    det_m = BirdDetector(str(PROJ / "assets/models/BirdTraceBirdDetector_YOLO11m.onnx"))
    det_n = BirdDetector(str(PROJ / "assets/models/BirdTraceBirdDetector_FP32.onnx"))
    pipe = RecognitionPipeline(
        detector_path=str(PROJ / "assets/models/BirdTraceBirdDetector_YOLO11m.onnx"),
        classifier_path=str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
        labels_path=str(PROJ / "assets/data/labels.json"),
        geo_prior_path=str(PROJ / "assets/data/geo_prior.sqlite"))

    for i, p in enumerate(paths):
        img = load_rgb(p)
        print(f"\n=== [{i}] {Path(p).name}  {img.shape[1]}x{img.shape[0]} ===")
        bm = det_m.detect(img)
        bn = det_n.detect(img)
        print(f"m框:    {len(bm)}个", [(round(b['conf'], 2), [round(v) for v in b['box']]) for b in bm])
        print(f"nano框: {len(bn)}个", [(round(b['conf'], 2), [round(v) for v in b['box']]) for b in bn])
        recs = pipe.recognize(img, "CN-SH", month_of(None, 10))
        for r in recs:
            print(f"  现行识别: {r['species_code']} {r['confidence']:.3f} "
                  f"框{[round(v) for v in r['box']]}")
            print("    top5:", [(t['code'], round(t['prob'], 3)) for t in r['top5']])
        # 带框标注图
        im = Image.fromarray(img)
        for tag, boxes, color in (("m", bm, (255, 0, 0)), ("nano", bn, (0, 160, 255))):
            d = ImageDraw.Draw(im)
            for b in boxes:
                d.rectangle(b["box"], outline=color, width=6)
        im.save(OUT / f"{i}_boxes.jpg", quality=90)
        # m框+0.05外扩的分类裁剪(管线同款)
        from app.ai import pipeline as pl
        try:
            margin = pl.CROP_MARGIN
        except AttributeError:
            margin = 0.05
        for j, b in enumerate(bm[:3]):
            x1, y1, x2, y2 = b["box"]
            mx, my = (x2 - x1) * margin, (y2 - y1) * margin
            crop = im.crop((max(0, int(x1 - mx)), max(0, int(y1 - my)),
                            min(im.width, int(x2 + mx)), min(im.height, int(y2 + my))))
            crop.save(OUT / f"{i}_crop{j}.jpg", quality=90)
    print(f"\n标注图/裁剪已存 {OUT}")
    pipe.close()


if __name__ == "__main__":
    main()
