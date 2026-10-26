# -*- coding: utf-8 -*-
"""fixA(allowzero=0)等价性与性能验证: 原模型 vs 手术模型(CPU/DML)。

断言: ①CPU下两模型logits完全一致(逐元素) ②DML下top1与CPU一致且
概率差<1e-3(float32正常抖动) ③给出DML vs CPU耗时对比。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

from app.ai.classifier import BirdClassifier
from app.ai.pipeline import load_rgb

ORIG = PROJ / "assets/models/BirdTraceRecognitionModel.onnx"
FIXA = PROJ / "data/model_experiments/BirdTraceRecognitionModel_fixA.onnx"
LABELS = str(PROJ / "assets/data/labels.json")
IMGS = sorted((PROJ / "data/test_images").glob("*.jpg"))

FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def main() -> int:
    print("[1] CPU等价性: 原模型 vs fixA (逐元素logits)")
    c_orig = BirdClassifier(str(ORIG), LABELS, use_gpu=False)
    c_fix = BirdClassifier(str(FIXA), LABELS, use_gpu=False)
    max_diff_all = 0.0
    agree = 0
    for img_path in IMGS:
        img = load_rgb(str(img_path))
        a = c_orig.logits(img, "squash")
        b = c_fix.logits(img, "squash")
        d = float(abs(a - b).max())
        max_diff_all = max(max_diff_all, d)
        agree += int(a.argmax() == b.argmax())
    check(max_diff_all == 0.0,
          f"{len(IMGS)}张图logits逐元素最大差 = {max_diff_all}")
    check(agree == len(IMGS), f"top1全一致 {agree}/{len(IMGS)}")

    print("[2] fixA在DML上: top1与CPU一致, 概率差<1e-3")
    c_dml = BirdClassifier(str(FIXA), LABELS, use_gpu=True)
    prov = c_dml.session.get_providers()[0]
    check(prov == "DmlExecutionProvider", f"fixA DML会话实际生效 ({prov})")
    import numpy as np
    max_pdiff = 0.0
    agree_dml = 0
    for img_path in IMGS:
        img = load_rgb(str(img_path))
        b = c_fix.logits(img, "squash")            # CPU
        d_ = c_dml.logits(img, "squash")           # DML
        pb = np.exp(b - b.max()); pb /= pb.sum()
        pd = np.exp(d_ - d_.max()); pd /= pd.sum()
        max_pdiff = max(max_pdiff, float(abs(pb - pd).max()))
        agree_dml += int(b.argmax() == d_.argmax())
    check(agree_dml == len(IMGS), f"DML top1与CPU全一致 {agree_dml}/{len(IMGS)}")
    check(max_pdiff < 1e-3, f"概率最大差 {max_pdiff:.2e} (<1e-3)")

    print("[3] 耗时对比(单张, 预热后3次均值)")
    img = load_rgb(str(IMGS[0]))
    for tag, clf in (("CPU", c_fix), ("DML", c_dml)):
        clf.logits(img, "squash")                  # 预热
        t0 = time.perf_counter()
        for _ in range(3):
            clf.logits(img, "squash")
        dt = (time.perf_counter() - t0) / 3 * 1000
        print(f"  {tag}: {dt:.0f}ms/张")

    print()
    print("FAILED" if FAILED["v"] else "ALL PASS")
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
