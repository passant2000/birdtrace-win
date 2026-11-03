# -*- coding: utf-8 -*-
"""全策略对照: 5种预处理 x 已确认真值组 + 3张待复核问题图。

已确认真值组(用户+iOS+目检):
  姬鹟5848/5876/5837→mugfly(鸲姬鹟; 5837为用户目检与正确组几乎一致)
  鸭#25-30→mallar3(绿头鸭雌鸟, 子代理目检) / 锚点5张
待复核组(用户报告识别错, 真值待用户确认具体物种):
  2877/2826(批量gubter3澳洲燕鸥=地理不可能) / 鹞/鸥抽检
策略: center448(test4-era) / letterbox(test5-era) / square+mask(现行) / squash(BICUBIC)
用法: .venv/Scripts/python.exe tools/strategy_bakeoff.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB = Path(r"C:/Users/zhaohp2116/Documents/BirdTraceWin/catalog.db")
STRATEGIES = ("center448", "letterbox", "squash", "square")


def main():
    import numpy as np
    from PIL import Image
    from app.ai.detector import BirdDetector
    from app.ai.classifier import BirdClassifier
    from app.ai.pipeline import (load_rgb, square_crop, crop_with_margin,
                                 SQUARE_MARGIN)

    con = sqlite3.connect(f"file:{LIB.as_posix()}?mode=ro", uri=True)
    det = BirdDetector(str(PROJ / "assets/models/BirdTraceBirdDetector_YOLO11m.onnx"))
    clf = BirdClassifier(str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
                         str(PROJ / "assets/data/labels.json"))

    def crop_for(img, box, strategy):
        if strategy == "square":
            c = square_crop(img, box, margin=SQUARE_MARGIN)
            # 现行批量: 下25%涂灰遮蔽
            c = c.copy()
            c[int(c.shape[0] * 0.75):, :] = 114
            return c
        return crop_with_margin(img, box, margin=0.05)

    # (组, 照片来源, 真值或None)
    cases = []
    cases.append(("姬鹟", PROJ / "data/fly_probe/5848.jpg", "mugfly"))
    cases.append(("姬鹟", PROJ / "data/fly_probe/5876.jpg", "mugfly"))
    p5837 = con.execute("SELECT path FROM photos WHERE path LIKE '%5837-%'",
                        ).fetchone()[0]
    cases.append(("姬鹟5837", p5837, "mugfly?"))        # 用户目检接近mugfly组
    for pid in range(25, 31):
        cases.append(("鸭", pid, "mallar3"))
    for tag, p, want in (("锚", PROJ / "data/frozen_060_src/普通翠鸟中文.jpg", "comkin1"),
                         ("锚", PROJ / "data/demo_src/Anas_platyrhynchos.jpg", "mallar3"),
                         ("锚", PROJ / "data/demo_src/Ardea_cinerea.jpg", "graher1"),
                         ("锚", PROJ / "data/demo_src/Passer_montanus.jpg", "eutspa"),
                         ("锚", PROJ / "data/demo_src/Cyanistes_caeruleus.jpg", "blutit")):
        cases.append((tag, p, want))
    for tag in ("2877", "2826", "5837b"):
        p = con.execute("SELECT path FROM photos WHERE path LIKE ?",
                        (f"%{tag}-%" if tag != "5837b" else "%5837-%",)).fetchone()[0]
        cases.append((f"待复核{tag}", p, None))
    # 5837已在上面; 去重(5837b与姬鹟5837同图, 只保留待复核标记)
    cases = cases[:-1]

    stat = {s: [0, 0] for s in STRATEGIES}
    print(f"{'组':10s} {'期望':9s} " +
          " ".join(f"{s[:10]:12s}" for s in STRATEGIES))
    for tag, ref, want in cases:
        path = ref
        if isinstance(ref, int):
            path = con.execute("SELECT path FROM photos WHERE id=?",
                               (ref,)).fetchone()[0]
        img = load_rgb(str(path))
        box = det.detect(img)[0]["box"]
        line = {}
        for s in STRATEGIES:
            crop = crop_for(img, box, s)
            top = clf.topk(crop, 1, strategy=s)
            code = top[0][1] if top else "?"
            conf = round(top[0][3], 2) if top else 0.0
            line[s] = f"{code} {conf:.2f}"
            if want and not want.endswith("?"):
                stat[s][1] += 1
                stat[s][0] += code == want
        want_disp = want or "待复核"
        print(f"{tag:10s} {want_disp:9s} " +
              " ".join(f"{line[s][:11]:12s}" for s in STRATEGIES), flush=True)

    print()
    n_known = stat["center448"][1]
    print(f"已确认真值组: {n_known}张")
    for s in STRATEGIES:
        hit, total = stat[s]
        print(f"  {s:12s}: {hit}/{total} = {hit/total*100:.0f}%")


if __name__ == "__main__":
    main()
