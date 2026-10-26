# -*- coding: utf-8 -*-
"""YOLO11n 鸟体检测: 加载 BirdTraceBirdDetector_FP32.onnx, 前处理/解码/NMS。

模型契约 (来自ONNX内嵌metadata):
  输入 images float32 [1,3,640,640] NCHW RGB 0-1
  输出 output0 float32 [1,5,8400] = 4框(cx,cy,w,h, 640像素系) + 1类分数, 无内嵌NMS
"""
from __future__ import annotations

import numpy as np
import onnxruntime as ort

INPUT_SIZE = 640


def make_session(model_path: str, use_gpu: bool = True,
                 intra_op: int = 0) -> ort.InferenceSession:
    """intra_op: CPU推理线程数; 0=自动。

    自动时留一半核给UI——识别线程吃满全部核会让主线程饿死
    (Windows报"无响应", 实际是UI线程抢不到时间片)。
    """
    providers = (["DmlExecutionProvider", "CPUExecutionProvider"] if use_gpu
                 else ["CPUExecutionProvider"])
    so = ort.SessionOptions()
    so.log_severity_level = 3   # 屏蔽DML回退告警刷屏
    if intra_op > 0:
        so.intra_op_num_threads = intra_op
        so.inter_op_num_threads = 1
    else:
        # 识别已子进程化(与UI的GIL完全隔离), CPU线程可以放开吃核提吞吐;
        # 留2核给系统。中文环境DML必失败回退CPU是ORT-directml已知问题,
        # CastLike替换/simplify/locale均绕不过(MLOperatorAuthor E_INVALIDARG)。
        import os
        cores = os.cpu_count() or 4
        so.intra_op_num_threads = max(2, cores - 2)
        so.inter_op_num_threads = 1
    try:
        s = ort.InferenceSession(model_path, providers=providers, sess_options=so)
    except Exception:
        s = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"],
                                 sess_options=so)
    # GPU加速是否真正生效(供设置页/状态诊断显示)
    make_session.last_provider = s.get_providers()[0]
    return s


def letterbox(img_rgb: np.ndarray, size: int = INPUT_SIZE):
    """等比缩放+灰色填充到 size x size, 返回(输入张量, scale, pad_x, pad_y)。"""
    h, w = img_rgb.shape[:2]
    scale = min(size / h, size / w)
    nh, nw = round(h * scale), round(w * scale)
    resized = np.asarray(
        _resize(img_rgb, nw, nh), dtype=np.float32) / 255.0
    canvas = np.full((size, size, 3), 114 / 255.0, dtype=np.float32)
    px, py = (size - nw) // 2, (size - nh) // 2
    canvas[py:py + nh, px:px + nw] = resized
    tensor = canvas.transpose(2, 0, 1)[None]  # HWC -> NCHW
    return np.ascontiguousarray(tensor), scale, px, py


def _resize(img: np.ndarray, w: int, h: int) -> np.ndarray:
    # cv2 不引入(减小依赖), 用PIL做高质量缩放
    from PIL import Image
    return np.asarray(Image.fromarray(img).resize((w, h), Image.BILINEAR))


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float) -> list[int]:
    """纯numpy NMS, boxes为 xyxy。"""
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou = inter / (areas[i] + areas[rest] - inter + 1e-9)
        order = rest[iou <= iou_thr]
    return keep


class BirdDetector:
    def __init__(self, model_path: str, conf_thr: float = 0.25, iou_thr: float = 0.45,
                 use_gpu: bool = True):
        self.session = make_session(model_path, use_gpu)
        self.input_name = self.session.get_inputs()[0].name
        self.conf_thr = conf_thr
        self.iou_thr = iou_thr

    def detect(self, img_rgb: np.ndarray) -> list[dict]:
        """返回 [{'box': [x1,y1,x2,y2]原图坐标, 'conf': float}, ...] 按分数降序。"""
        orig_h, orig_w = img_rgb.shape[:2]
        tensor, scale, px, py = letterbox(img_rgb)
        out = self.session.run(None, {self.input_name: tensor})[0]  # [1,5,8400]
        pred = out[0].T  # [8400, 5]
        boxes_cxcywh = pred[:, :4]
        scores = pred[:, 4]
        mask = scores >= self.conf_thr
        if not mask.any():
            return []
        boxes_cxcywh = boxes_cxcywh[mask]
        scores = scores[mask]
        # cxcywh -> xyxy (letterbox坐标系), 再映射回原图
        xyxy = np.empty_like(boxes_cxcywh)
        xyxy[:, 0] = boxes_cxcywh[:, 0] - boxes_cxcywh[:, 2] / 2
        xyxy[:, 1] = boxes_cxcywh[:, 1] - boxes_cxcywh[:, 3] / 2
        xyxy[:, 2] = boxes_cxcywh[:, 0] + boxes_cxcywh[:, 2] / 2
        xyxy[:, 3] = boxes_cxcywh[:, 1] + boxes_cxcywh[:, 3] / 2
        xyxy[:, [0, 2]] -= px
        xyxy[:, [1, 3]] -= py
        xyxy /= scale
        keep = nms(xyxy, scores, self.iou_thr)
        results = []
        for i in keep:
            x1 = max(0, min(orig_w, xyxy[i, 0]))
            y1 = max(0, min(orig_h, xyxy[i, 1]))
            x2 = max(0, min(orig_w, xyxy[i, 2]))
            y2 = max(0, min(orig_h, xyxy[i, 3]))
            if x2 - x1 < 4 or y2 - y1 < 4:
                continue
            results.append({"box": [float(x1), float(y1), float(x2), float(y2)],
                            "conf": float(scores[i])})
        results.sort(key=lambda r: -r["conf"])
        return results
