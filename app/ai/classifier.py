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
      "letterbox"   长边缩放到384保比例, 四周灰色补边到384x384——
                    整鸟完整无变形; 游禽/鸥类侧视角产生2.5:1以上宽条
                    裁剪, center448中心裁剪会切掉头尾(实测鸭子0.97误认
                    非洲海雕), squash则横向压扁2.8倍, letterbox两者兼免
      "square"      直接resize到384x384+BICUBIC——配合方形化裁剪使用
                    (SuperPicky对同款模型的裁剪法: YOLO框方形化+直接
                    resize+BICUBIC, iNaturalist测97.1%, 见STUDY_NOTES§5)
    M0冒烟测试对比确定默认值; v0.6.0实测新增letterbox/square。"""
    h, w = img_rgb.shape[:2]
    pil = Image.fromarray(img_rgb)
    if strategy == "squash":
        r = pil.resize((INPUT_SIZE, INPUT_SIZE), Image.BILINEAR)
    elif strategy == "square":
        r = pil.resize((INPUT_SIZE, INPUT_SIZE), Image.BICUBIC)
    elif strategy == "letterbox":
        scale = INPUT_SIZE / max(h, w)
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        resized = pil.resize((nw, nh), Image.BILINEAR)
        r = Image.new("RGB", (INPUT_SIZE, INPUT_SIZE), (114, 114, 114))
        r.paste(resized, ((INPUT_SIZE - nw) // 2, (INPUT_SIZE - nh) // 2))
    else:
        short = INPUT_SIZE if strategy == "center384" else 448
        scale = short / min(h, w)
        nw, nh = round(w * scale), round(h * scale)
        r = pil.resize((nw, nh), Image.BILINEAR)
        left, top = (nw - INPUT_SIZE) // 2, (nh - INPUT_SIZE) // 2
        r = r.crop((left, top, left + INPUT_SIZE, top + INPUT_SIZE))
    arr = np.asarray(r, dtype=np.float32) / 255.0
    return np.ascontiguousarray(arr.transpose(2, 0, 1)[None])


def letterbox_pil(pil: Image.Image, size: int = INPUT_SIZE) -> Image.Image:
    """长边缩放到size保比例, 114灰补边(与检测letterbox同色)。"""
    w, h = pil.size
    scale = size / max(h, w)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    out = Image.new("RGB", (size, size), (114, 114, 114))
    out.paste(pil.resize((nw, nh), Image.BILINEAR),
              ((size - nw) // 2, (size - nh) // 2))
    return out


def ensemble_views(img_rgb: np.ndarray, size: int = INPUT_SIZE) -> list:
    """滑窗集成视图集: 全局letterbox + (宽裁剪时)短边拉满后的滑窗。

    游禽/鸥/猛禽侧视角产生2.5:1以上宽条裁剪, letterbox整图视图里鸟只占
    画布高度1/3~1/2, 细节缩没了; 滑窗把短边拉满到size(鸟=原生高度),
    以半窗步进覆盖全宽, 头/躯干/尾各有特写窗口。给桌端用——慢几十毫秒
    无所谓, 准确率优先(用户拍板: nano/小输入的手机式妥协全部抛弃)。
    返回PIL视图列表(1个全局 + 宽裁剪最多4个滑窗)。"""
    h, w = img_rgb.shape[:2]
    pil = Image.fromarray(img_rgb)
    views = [letterbox_pil(pil, size)]
    ar = w / max(1, h)
    if ar > 1.3:
        scale = size / min(h, w)
        nw, nh = round(w * scale), round(h * scale)
        if nh >= 40 and nw > size:
            big = pil.resize((nw, nh), Image.BILINEAR)
            stride = size // 2
            x = 0
            while x < nw and len(views) < 5:
                left = min(x, max(0, nw - size))
                views.append(big.crop((left, 0, left + size, min(nh, size))))
                if left + size >= nw:
                    break
                x += stride
    return views


def softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max())
    return e / e.sum()


class BirdClassifier:
    def __init__(self, model_path: str, labels_path: str, use_gpu: bool = True):
        self.session = make_session(model_path, use_gpu)
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        self.labels = load_labels(labels_path)

    def probs_views(self, views: list) -> np.ndarray:
        """多视图平均softmax概率(滑窗集成)。"""
        acc = None
        for v in views:
            tensor = preprocess(np.asarray(v), strategy="squash")
            p = softmax(self.session.run([self.output_name],
                                         {self.input_name: tensor})[0][0])
            acc = p if acc is None else acc + p
        return acc / len(views)

    def logits(self, img_rgb: np.ndarray, strategy: str = "squash") -> np.ndarray:
        tensor = preprocess(img_rgb, strategy)
        return self.session.run([self.output_name], {self.input_name: tensor})[0][0]

    def probs(self, img_rgb: np.ndarray, strategy: str = "squash") -> np.ndarray:
        """softmax概率; "ensemble"=滑窗集成(全局+原生细节滑窗平均)。"""
        if strategy == "ensemble":
            return self.probs_views(ensemble_views(img_rgb))
        tensor = preprocess(img_rgb, strategy)
        return softmax(self.session.run([self.output_name],
                                        {self.input_name: tensor})[0][0])

    def topk(self, img_rgb: np.ndarray, k: int = 5, strategy: str = "squash"):
        """返回 [(class_index, code, en_name, prob), ...] prob为softmax后。"""
        probs = self.probs(img_rgb, strategy)
        idx = np.argsort(-probs)[:k]
        return [(int(i), self.labels[i]["code"], self.labels[i]["en"], float(probs[i]))
                for i in idx]
