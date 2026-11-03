# -*- coding: utf-8 -*-
"""鸟类眼点关键点检测(SuperPicky作者cub200模型, ONNX移植)。

模型: cub200_keypoint_resnet50_slim.pth → cub200_keypoint.onnx(+.data外部权重)
输入: RGB裁剪图, resize 416×416(BILINEAR), ImageNet归一化
输出: coords[1,3,2] sigmoid归一化(左眼/右眼/喙), vis[1,3]可见性
与SuperPicky core/keypoint_detector.py语义一致(VISIBILITY_THRESHOLD=0.3);
识别路径仅用"最佳眼睛"坐标做贴茎场景的眼锚定取景(见sp_engine)。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

VISIBILITY_THRESHOLD = 0.3
KEYPOINT_INPUT = 416
KEYPOINT_MODEL = "cub200_keypoint.onnx"
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)


class KeyPointDetector:
    """懒加载单例风格的检测器; 缺模型文件时available()=False, 调用方降级。

    固定CPU推理: 2026-10-31冻结实测该模型在DML上session.run抛
    UnicodeDecodeError(错误消息解码崩溃), 6033类不触发锚定一切正常、
    5837类触发即整次识别失败——识别链路上的模型绝不允许带病运行;
    416输入的ResNet50在CPU上~百毫秒, 只对贴茎候选跑一次, 可接受。
    """

    def __init__(self, model_path: str | Path, use_gpu: bool = True):
        self.model_path = str(model_path)
        self.session = None

    def available(self) -> bool:
        return Path(self.model_path).exists()

    def _load(self):
        if self.session is not None:
            return
        import onnxruntime as ort

        self.session = ort.InferenceSession(
            self.model_path, providers=["CPUExecutionProvider"])

    def detect(self, crop_rgb: np.ndarray) -> tuple | None:
        """crop_rgb: 框内裁剪(HxWx3 RGB)。返回(eye=(x,y)归一化, vis, beak|None)
        眼不可见(双vis<0.3)或任何异常返回None(调用方回退bbox裁剪)。"""
        if not self.available() or crop_rgb is None or crop_rgb.size == 0:
            return None
        try:
            self._load()
            pil = Image.fromarray(crop_rgb).resize(
                (KEYPOINT_INPUT, KEYPOINT_INPUT), Image.BILINEAR)
            x = np.asarray(pil, dtype=np.float32).transpose(2, 0, 1) / 255.0
            x = (x - _MEAN) / _STD
            coords, vis = self.session.run(None, {"input": x[None]})
            coords, vis = coords[0], vis[0]          # (3,2) (3,)
            lv, rv, bv = (float(v) for v in vis)
            if lv < VISIBILITY_THRESHOLD and rv < VISIBILITY_THRESHOLD:
                return None
            eye = coords[0] if lv >= rv else coords[1]
            beak = coords[2] if bv >= VISIBILITY_THRESHOLD else None
            return (float(eye[0]), float(eye[1])), max(lv, rv), \
                ((float(beak[0]), float(beak[1])) if beak is not None else None)
        except Exception:
            return None      # 推理任何异常=无眼点, 走纯SP裁剪
