# -*- coding: utf-8 -*-
"""TOPIQ美学模型导出ONNX fp16 + 等价验证(一次性工具, 临时环境运行)。

运行: data/py312x/python.exe tools/export_aesthetic_onnx.py
前置: data/model_experiments/cfanet_iaa_ava_res50-3cd62bb3.pth
      (hf-mirror下载, 与pyiqa官方发布字节一致)
产出: assets/models/AestheticTOPIQ_fp16.onnx

模型事实(读pyiqa源码确认):
  · pyiqa名=topiq_iaa_res50(CFANet, res50骨干, AVA 10档);
  · score_linear末尾Softmax → forward默认输出MOS(概率·1..10), 1~10分;
  · ImageNet归一化在net内部(preprocess), 输入只需0~1、384×384;
  · res50分支无内部resize, 尺寸由外部保证。

等价标准(同GPU模型手术纪律): 同输入下 fp32 |Δ|<0.02 / fp16 |Δ|<0.05,
全图排序一致; 另对照pyiqa完整管线(含其自身变换, 宽容0.15仅供参考)。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")   # timm骨干经镜像

PROJ = Path(__file__).resolve().parent.parent
PTH = PROJ / "data/model_experiments/cfanet_iaa_ava_res50-3cd62bb3.pth"
OUT_FP32 = PROJ / "data/model_experiments/aesthetic_topiq_fp32.onnx"
OUT_FP16 = PROJ / "assets/models/AestheticTOPIQ_fp16.onnx"


def place_weight_in_cache():
    """把pth放到pyiqa的缓存目录(hub/pyiqa/, 文件名含校验hash直接命中,
    避免pyiqa从github release重新下载——本环境不可达)。"""
    import torch.hub as hub
    d = Path(hub.get_dir()) / "pyiqa"
    d.mkdir(parents=True, exist_ok=True)
    dst = d / PTH.name
    if not dst.exists():
        shutil.copy2(PTH, dst)
    return dst


def main():
    import numpy as np
    import torch

    place_weight_in_cache()
    metric = pyiqa_create()
    net = metric.net.eval()

    dummy = torch.rand(1, 3, 384, 384)
    with torch.no_grad():
        ref = net(dummy)
    print("forward输出(MOS):", float(ref.flatten()[0]), "shape", tuple(ref.shape))

    torch.onnx.export(
        net, dummy, str(OUT_FP32),
        input_names=["input"], output_names=["mos"],
        opset_version=17, do_constant_folding=True,
        dynamic_axes={"input": {0: "batch"}, "mos": {0: "batch"}})
    # torch 2.14会把大权重存成外部.data文件: 内联回单文件便于校验
    import onnx
    m32 = onnx.load(str(OUT_FP32), load_external_data=True)
    onnx.save_model(m32, str(OUT_FP32))
    print("fp32导出:", OUT_FP32.stat().st_size // 1048576, "MB")

    from onnxconverter_common import float16
    m16 = float16.convert_float_to_float16(
        onnx.load(str(OUT_FP32), load_external_data=True),
        keep_io_types=True)   # 输入输出保持fp32, 应用侧无需喂fp16
    onnx.save(m16, str(OUT_FP16))
    print("fp16导出:", OUT_FP16.stat().st_size // 1048576, "MB")

    # ---------- 等价验证 ----------
    import onnxruntime as ort
    from PIL import Image, ImageFilter

    s32 = ort.InferenceSession(str(OUT_FP32), providers=["CPUExecutionProvider"])
    s16 = ort.InferenceSession(str(OUT_FP16), providers=["CPUExecutionProvider"])

    imgs = sorted((PROJ / "data/test_images").glob("*.jpg"))
    blur = PROJ / "data/model_experiments/_blur_probe.jpg"
    Image.open(imgs[0]).convert("RGB").filter(
        ImageFilter.GaussianBlur(8)).save(blur, quality=90)
    cases = list(imgs) + [blur]

    def tensor_of(path):
        im = Image.open(path).convert("RGB").resize((384, 384), Image.LANCZOS)
        return np.asarray(im, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0

    def run_onnx(sess, x):
        return float(sess.run(None, {"input": x})[0].flatten()[0])

    rows = []
    for f in cases:
        x = tensor_of(f)
        with torch.no_grad():
            t = float(net(torch.from_numpy(x)).flatten()[0])
        full = float(metric(Image.open(f).convert("RGB")))   # pyiqa完整管线
        r32, r16 = run_onnx(s32, x), run_onnx(s16, x)
        rows.append({"img": f.name, "net": t, "fp32": r32, "fp16": r16,
                     "pyiqa_full": full})
        print(f"  {f.name[:26]:28s} net={t:.4f} fp32={r32:.4f} "
              f"Δ={abs(t-r32):.4f} fp16={r16:.4f} Δ={abs(t-r16):.4f} "
              f"管线={full:.4f}")

    order_ref = sorted(range(len(rows)), key=lambda i: -rows[i]["net"])
    order16 = sorted(range(len(rows)), key=lambda i: -rows[i]["fp16"])
    ok32 = all(abs(r["net"] - r["fp32"]) < 0.02 for r in rows)
    ok16 = all(abs(r["net"] - r["fp16"]) < 0.05 for r in rows)
    print("fp32同输入Δ<0.02:", ok32)
    print("fp16同输入Δ<0.05:", ok16)
    print("fp16排序一致:", order16 == order_ref)
    print("模糊图最低分:", order16[-1] == len(rows) - 1)
    if not (ok32 and ok16 and order16 == order_ref):
        print("EQUIVALENCE FAILED")
        sys.exit(1)
    (PROJ / "data/model_experiments/aesthetic_export_report.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("EQUIVALENCE OK ->", OUT_FP16.name)


def pyiqa_create():
    import pyiqa
    return pyiqa.create_metric("topiq_iaa_res50", device="cpu")


if __name__ == "__main__":
    main()
