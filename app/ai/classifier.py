# -*- coding: utf-8 -*-
"""FastViT-MA36 鸟种分类: 加载 BirdTraceRecognitionModel.onnx。

模型契约 (assets/data/model_manifest.properties):
  输入 image float32 [1,3,384,384] NCHW RGB 0-1 (ImageNet归一化已内嵌)
  输出 visual_logits float32 [1,10480] 原始logits, 无softmax
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from .detector import make_session

INPUT_SIZE = 384


def load_labels(labels_path: str | Path) -> list[dict]:
    return json.loads(Path(labels_path).read_text(encoding="utf-8"))


def preprocess(img_rgb: np.ndarray, strategy: str = "squash") -> np.ndarray:
    """384x384 预处理。

    strategy:
      "squash"      直接拉伸到 384x384 (移动端一键识别常用)
      "center384"   短边缩放到384后中心裁剪 384x384
      "center448"   短边缩放到448后中心裁剪 384x384 (ImageNet评测风格)
    M0冒烟测试对比三种策略后确定默认值。
    """
    h, w = img_rgb.shape[:2]
    pil = Image.fromarray(img_rgb)
    if strategy == "squash":
        r = pil.resize((INPUT_SIZE, INPUT_SIZE), Image.BILINEAR)
    else:
        short = INPUT_SIZE if strategy == "center384" else 448
        scale = short / min(h, w)
        nw, nh = round(w * scale), round(h * scale)
        r = pil.resize((nw, nh), Image.BILINEAR)
        left, top = (nw - INPUT_SIZE) // 2, (nh - INPUT_SIZE) // 2
        r = r.crop((left, top, left + INPUT_SIZE, top + INPUT_SIZE))
    arr = np.asarray(r, dtype=np.float32) / 255.0
    return np.ascontiguousarray(arr.transpose(2, 0, 1)[None])


def softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max())
    return e / e.sum()


class BirdClassifier:
    def __init__(self, model_path: str, labels_path: str, use_gpu: bool = True):
        self.session = make_session(model_path, use_gpu)
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        self.labels = load_labels(labels_path)

    def logits(self, img_rgb: np.ndarray, strategy: str = "squash") -> np.ndarray:
        tensor = preprocess(img_rgb, strategy)
        return self.session.run([self.output_name], {self.input_name: tensor})[0][0]

    def topk(self, img_rgb: np.ndarray, k: int = 5, strategy: str = "squash"):
        """返回 [(class_index, code, en_name, prob), ...] prob为softmax后。"""
        logits = self.logits(img_rgb, strategy)
        probs = softmax(logits)
        idx = np.argsort(-probs)[:k]
        return [(int(i), self.labels[i]["code"], self.labels[i]["en"], float(probs[i]))
                for i in idx]
