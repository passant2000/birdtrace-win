# -*- coding: utf-8 -*-
"""检测质量实证: 47张成片扫conf阈值 + 框可视化(输出标注图供人眼复核)。

输出:
  data/ui_shots/det_check/*.jpg   画了检测框+置信度的照片
  终端: 每张照片在 0.25/0.15/0.10 三档下的框数与置信度
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

from PIL import Image, ImageDraw, ImageFont
from app.ai.detector import BirdDetector
from app.ai.pipeline import load_rgb

SRC = PROJ / "data" / "test_images"
OUT = PROJ / "data" / "ui_shots" / "det_check"
OUT.mkdir(parents=True, exist_ok=True)

det = BirdDetector(str(PROJ / "assets/models/BirdTraceBirdDetector_FP32.onnx"),
                   conf_thr=0.10, use_gpu=False)

rows = []
n_saved = 0
files = sorted(SRC.glob("*.jpg"))
for f in files:
    img = load_rgb(str(f))
    dets = det.detect(img)          # conf>=0.10
    by = {thr: [d for d in dets if d["conf"] >= thr] for thr in (0.25, 0.15, 0.10)}
    rows.append((f.name, img.shape[1], img.shape[0],
                 [(round(d['conf'], 2), [round(v) for v in d['box']]) for d in dets]))
    # 标注图: 每张都画(框=0.10以上全部, 标签带conf; <0.25的框用蓝色区分)
    if n_saved < 50:
        im = Image.fromarray(img)
        if im.width > 1600:
            im = im.resize((1600, round(im.height * 1600 / im.width)))
            sx, sy = im.width / img.shape[1], im.height / img.shape[0]
        else:
            sx = sy = 1.0
        dr = ImageDraw.Draw(im)
        try:
            font = ImageFont.truetype("arial.ttf", 22)
        except OSError:
            font = ImageFont.load_default()
        for d in dets:
            x1, y1, x2, y2 = [v * sx for v in d["box"]], None, None, None
            b = d["box"]
            col = (255, 0, 0) if d["conf"] >= 0.25 else (0, 120, 255)
            dr.rectangle([b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy],
                         outline=col, width=4)
            dr.text((b[0] * sx + 4, b[1] * sy - 26),
                    f"{d['conf']:.2f}", fill=col, font=font)
        im.save(OUT / f"{f.stem[:40]}_det.jpg", quality=85)
        n_saved += 1

print(f"{'照片':38s} {'尺寸':12s} {'>=0.25':>7s} {'>=0.15':>7s} {'>=0.10':>7s}")
miss25 = 0
for name, w, h, dets in rows:
    n25 = sum(1 for c, _ in dets if c >= 0.25)
    n15 = sum(1 for c, _ in dets if c >= 0.15)
    n10 = len(dets)
    if n25 == 0:
        miss25 += 1
    print(f"{name[:36]:38s} {w}x{h:<7d} {n25:7d} {n15:7d} {n10:7d}")
print()
print(f"共{len(rows)}张: 0.25档无鸟{miss25}张; 0.15比0.25多检出"
      f"{sum(1 for _,_,_,d in rows if any(0.15<=c<0.25 for c,_ in d))}张有增量")
print("标注图输出:", OUT)
