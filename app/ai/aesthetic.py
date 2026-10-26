# -*- coding: utf-8 -*-
"""TOPIQ美学评分器(cfanet_iaa_ava_res50 → ONNX fp16): 整图1~10分。

模型出自IQA-PyTorch(AVA美学数据集训练, 权重仅个人非商业使用),
导出脚本 tools/export_aesthetic_onnx.py(临时Python3.12工具链,
不在应用依赖里)。输入384×384(RGB直接拉伸, 0~1, ImageNet归一化已
包含在图内), 输出即MOS美学分(概率·1..10, 已含Softmax, 无需解码)。
CPU单张约0.1~0.2s, 只在后台线程调用。
"""
from __future__ import annotations

from pathlib import Path

MODEL_FILENAME = "AestheticTOPIQ_fp16.onnx"
INPUT_SIZE = 384

_SCORE_WORKER = None   # 进程内单例(线程本地由调用方管理)


class AestheticScorer:
    """onnxruntime CPU会话; 实例可在创建它的线程内复用。"""

    def __init__(self, model_path: str | Path):
        import numpy as np
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.inter_op_num_threads = 1
        so.intra_op_num_threads = max(2, (self._cpu_count() or 4) // 2)
        self._np = np
        self.sess = ort.InferenceSession(
            str(model_path), so, providers=["CPUExecutionProvider"])
        self.input_name = self.sess.get_inputs()[0].name

    @staticmethod
    def _cpu_count() -> int | None:
        import os
        return os.cpu_count()

    def score_file(self, path: str | Path) -> float | None:
        """整图评分, 1~10分; 解码失败/文件缺失返回None。"""
        from PIL import Image
        try:
            with Image.open(path) as im:
                im = im.convert("RGB").resize(
                    (INPUT_SIZE, INPUT_SIZE), Image.LANCZOS)
                x = self._np.asarray(im, dtype=self._np.float32) / 255.0
        except Exception:
            return None
        return self.score_chw(x.transpose(2, 0, 1)[None])

    def score_chw(self, batch: "ndarray") -> float | None:
        """输入NCHW float32(0~1, 未归一化), 图内含归一化, 输出即MOS。"""
        try:
            mos = self.sess.run(None, {self.input_name: batch})[0].flatten()[0]
        except Exception:
            return None
        return min(10.0, max(1.0, float(mos)))
