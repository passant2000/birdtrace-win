# -*- coding: utf-8 -*-
"""南汇批次预处理策略对照: center448(现行) vs squash(旧默认) vs letterbox(新)。

对真实库指定批次的每张照片: m检测→逐框三种策略分类→输出top1对照表。
只读真实库(URI ro), 结果打印+存CSV, 不写任何库。

用法: .venv/Scripts/python.exe tools/strategy_eval.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB = Path(r"C:/Users/zhaohp2116/Documents/BirdTraceWin/catalog.db")
STRATEGIES = ("center448", "squash", "letterbox")


def main():
    args = [a for a in sys.argv[1:] if a.isdigit()]
    lo, hi = (int(args[0]), int(args[1])) if len(args) == 2 else (1, 10 ** 9)
    con = sqlite3.connect(f"file:{LIB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    photos = con.execute(
        "SELECT id, path FROM photos WHERE id BETWEEN ? AND ? ORDER BY id",
        (lo, hi)).fetchall()
    print(f"批次照片: {len(photos)} 张")
    from app.ai.detector import BirdDetector
    from app.ai.classifier import BirdClassifier
    from app.ai.pipeline import load_rgb, crop_with_margin

    det = BirdDetector(str(PROJ / "assets/models/BirdTraceBirdDetector_YOLO11m.onnx"))
    clf = BirdClassifier(str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
                         str(PROJ / "assets/data/labels.json"))
    codes = {l["code"]: l for l in clf.labels}

    rows_out = []
    for p in photos:
        path = p["path"]
        try:
            img = load_rgb(path)
        except Exception as e:
            print(f"#{p['id']} 读取失败: {e}")
            continue
        boxes = det.detect(img)
        line = {"id": p["id"], "name": Path(path).name[:26],
                "n_boxes": len(boxes)}
        for s in STRATEGIES:
            best = ("", 0.0)
            for b in boxes:
                crop = crop_with_margin(img, b["box"])
                top = clf.topk(crop, 1, strategy=s)
                if top and top[0][3] > best[1]:
                    code, prob = top[0][1], top[0][3]
                    best = (f"{code}({codes[code]['en'][:16]})", prob)
            line[s] = f"{best[0]} {best[1]:.2f}"
        rows_out.append(line)
        print(f"#{line['id']:3d} 框{line['n_boxes']} | "
              f"448:{line['center448']} | sq:{line['squash']} | "
              f"lb:{line['letterbox']}", flush=True)

    import csv
    out = PROJ / "data/duck_probe/strategy_eval.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["id", "name", "n_boxes"] + list(STRATEGIES))
        w.writeheader()
        w.writerows(rows_out)
    print(f"\n对照表已存 {out}")


if __name__ == "__main__":
    main()
