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

# 运行时检测模型(2026-10-31换YOLO11l-seg分割: 掩码外接框贴鸟身, 排除栖枝/
# 空茎——SuperPicky作者路线, 24例基准19/24 vs m检测框15/24, 见PROGRESS)。
# m保留在包内(旧包回退+对照); nano保留备用(DETECTOR_MODEL_CPU)。
DETECTOR_MODEL = "BirdTraceBirdDetector_YOLO11lSeg.onnx"
DETECTOR_MODEL_CPU = "BirdTraceBirdDetector_FP32.onnx"   # 保留包内备用(诊断/回退)


def default_detector_model(use_gpu: bool = True) -> str:
    """诊断(gpu_probe)用: 默认检测模型文件名。GPU=l-seg分割, CPU=nano轻量。"""
    return DETECTOR_MODEL if use_gpu else DETECTOR_MODEL_CPU


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
    if use_gpu:
        # DML EP官方约束: 必须SEQUENTIAL执行模式 + 关闭mem pattern,
        # 否则可能出现非稳定输出(NVIDIA DML路径实测踩到, AMD未复现)
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        so.enable_mem_pattern = False
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
    # 分块召回门槛: 长边低于此值的图分块≈全图, 白付成本
    TILE_GATE = 2048

    def __init__(self, model_path: str, conf_thr: float = 0.25, iou_thr: float = 0.45,
                 use_gpu: bool = True):
        self.session = make_session(model_path, use_gpu)
        self.input_name = self.session.get_inputs()[0].name
        self.conf_thr = conf_thr
        self.iou_thr = iou_thr

    def detect(self, img_rgb: np.ndarray) -> list[dict]:
        """返回 [{'box': [x1,y1,x2,y2]原图坐标, 'conf': float}, ...] 按分数降序。

        两阶段: 全图检测; 0检出且图够大时追加3×3分块召回(见_detect_tiled)。
        有检出的照片行为与历史版本完全一致, 结果永不减少只会从无到有。"""
        boxes = self._detect_pass(img_rgb)
        if not boxes:
            boxes = self._detect_tiled(img_rgb)
        return boxes

    def _detect_pass(self, img_rgb: np.ndarray) -> list[dict]:
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

    def _detect_tiled(self, img_rgb: np.ndarray) -> list[dict]:
        """分块召回(全图0检出时的兜底, 用户授权的Win端增强, 2026-10-29)。

        YOLO11n对"鸟只占画面小部分"的构图会整体漏检——Z8全画幅飞鸟实测
        任意尺寸/低至0.10阈值都0检出, 而鸟区裁剪同一模型0.88~0.95稳检。
        3×3重叠块(60%窗口/20%步进, 保证≤60%画幅的目标完整落在某块内),
        块内检出映射回全图坐标后跨块NMS。成本仅由无检出的大图承担
        (~1.2s/DML); 与APK的偏差已获用户授权, 结果只会从无到有。"""
        h, w = img_rgb.shape[:2]
        if max(h, w) < self.TILE_GATE:
            return []
        allbox: list[list[float]] = []
        allsc: list[float] = []
        for iy in range(3):
            for ix in range(3):
                x0, y0 = int(w * 0.2) * ix, int(h * 0.2) * iy
                x1, y1 = min(w, x0 + int(w * 0.6)), min(h, y0 + int(h * 0.6))
                if x1 - x0 < 4 or y1 - y0 < 4:
                    continue
                for b in self._detect_pass(img_rgb[y0:y1, x0:x1]):
                    allbox.append([b["box"][0] + x0, b["box"][1] + y0,
                                   b["box"][2] + x0, b["box"][3] + y0])
                    allsc.append(b["conf"])
        if not allbox:
            return []
        keep = nms(np.asarray(allbox, np.float32),
                   np.asarray(allsc, np.float32), self.iou_thr)
        return [{"box": [float(v) for v in allbox[i]],
                 "conf": float(allsc[i])} for i in keep]
