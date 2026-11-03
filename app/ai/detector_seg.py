# -*- coding: utf-8 -*-
"""YOLO11l-seg 鸟体检测+分割: 检测框与掩码外接框一起返回, 驱动分类裁剪。

模型契约 (BirdTraceBirdDetector_YOLO11lSeg.onnx, ultralytics yolo11l-seg导出):
  输入 images float32 [1,3,1024,1024] NCHW RGB 0-1
  输出 output0 [1,116,21504] = 4框(cx,cy,w,h, 1024 letterbox系, 已解码)
       + 80类分数(已sigmoid, 鸟=COCO类14→通道18) + 32掩码系数
       output1 [1,32,256,256] 掩码proto(1024/4)

掩码外接框 = 系数×proto → sigmoid → 框内裁剪 → >0.5 像素的外接矩形,
映射回原图坐标; 掩码空时回退检测框。SuperPicky birdid 同参
(BGR输入/conf 0.25/imgsz 1024/类别14), 见 STUDY_NOTES 与 tools实验
data/_diag_lseg_detect.py(2026-10-31作者路线验证: 24例19/24)。
"""
from __future__ import annotations

import numpy as np

from .detector import make_session, nms, letterbox

INPUT_SIZE = 1024
SEG_DETECTOR_MODEL = "BirdTraceBirdDetector_YOLO11lSeg.onnx"
BIRD_SCORE_CH = 4 + 14          # COCO类14=bird
MASK_COEFF_OFF = 84             # 4框+80类后是32个掩码系数
PROTO_SIZE = 256                # 1024/4
FALLBACK_MODEL = "BirdTraceBirdDetector_YOLO11m.onnx"   # 旧包缺l-seg时回退


class BirdSegDetector:
    """与 BirdDetector 同接口的分割检测器, 额外返回 maskbox。"""

    TILE_GATE = 2048   # 与BirdDetector一致: 全图0检出的大图追加3×3分块召回

    def __init__(self, model_path: str, conf_thr: float = 0.25,
                 iou_thr: float = 0.45, use_gpu: bool = True):
        self.session = make_session(model_path, use_gpu)
        self.input_name = self.session.get_inputs()[0].name
        self.conf_thr = conf_thr
        self.iou_thr = iou_thr

    def detect(self, img_rgb: np.ndarray) -> list[dict]:
        """返回 [{'box','conf','maskbox'}, ...] 按分数降序。
        box=检测框, maskbox=掩码外接框(空掩码时=box)。"""
        boxes = self._detect_pass(img_rgb)
        if not boxes:
            boxes = self._detect_tiled(img_rgb)
        return boxes

    def _run(self, img_rgb: np.ndarray):
        tensor, scale, px, py = letterbox(img_rgb, size=INPUT_SIZE)
        return self.session.run(None, {self.input_name: tensor}), scale, px, py

    def _decode(self, img_rgb: np.ndarray, outputs, scale: float,
                px: int, py: int) -> list[dict]:
        orig_h, orig_w = img_rgb.shape[:2]
        out0, proto = outputs[0][0], outputs[1][0]     # [116,N], [32,256,256]
        pred = out0.T                                   # [N,116]
        scores = pred[:, BIRD_SCORE_CH]
        mask = scores >= self.conf_thr
        if not mask.any():
            return []
        pred = pred[mask]
        scores = scores[mask]
        cx, cy, w, h = pred[:, 0], pred[:, 1], pred[:, 2], pred[:, 3]
        xyxy = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
        keep = nms(xyxy, scores, self.iou_thr)

        coeffs = pred[:, MASK_COEFF_OFF:]               # [n,32]
        p2, p1 = proto.shape[1] * proto.shape[2], proto.shape[0]
        masks = 1.0 / (1.0 + np.exp(-(coeffs @ proto.reshape(p1, p2))
                                    .reshape(-1, proto.shape[1], proto.shape[2])))

        results = []
        for i in keep:
            box = xyxy[i]
            # 框映射回原图
            ob = (box - [px, py, px, py]) / scale
            x1 = max(0.0, min(float(orig_w), ob[0]))
            y1 = max(0.0, min(float(orig_h), ob[1]))
            x2 = max(0.0, min(float(orig_w), ob[2]))
            y2 = max(0.0, min(float(orig_h), ob[3]))
            if x2 - x1 < 4 or y2 - y1 < 4:
                continue
            # 掩码框内裁剪(proto系) → 上采样到1024再阈值(与ultralytics
            # scale_masks对齐: 256直接阈值在数千px大图上外接框会抖动
            # ±160px, 上采样后与torch逐例对齐<20px) → >0.5外接矩形 → 原图坐标
            pb = box / (INPUT_SIZE / PROTO_SIZE)
            m = masks[i]
            m[:int(max(0, pb[1])), :] = 0
            if pb[3] < PROTO_SIZE:
                m[int(pb[3]):, :] = 0
            m[:, :int(max(0, pb[0]))] = 0
            if pb[2] < PROTO_SIZE:
                m[:, int(pb[2]):] = 0
            from PIL import Image as _PILImage
            m1k = np.asarray(
                _PILImage.fromarray(m, mode="F").resize(
                    (INPUT_SIZE, INPUT_SIZE), _PILImage.BILINEAR))
            rows = np.flatnonzero(m1k.max(axis=1) > 0.5)
            cols = np.flatnonzero(m1k.max(axis=0) > 0.5)
            maskbox = None
            if rows.size and cols.size:
                mb = np.array([cols[0], rows[0], cols[-1] + 1, rows[-1] + 1],
                              dtype=np.float64)
                mb = (mb - [px, py, px, py]) / scale
                mb = [max(0.0, min(float(orig_w), mb[0])),
                      max(0.0, min(float(orig_h), mb[1])),
                      max(0.0, min(float(orig_w), mb[2])),
                      max(0.0, min(float(orig_h), mb[3]))]
                if mb[2] - mb[0] >= 4 and mb[3] - mb[1] >= 4:
                    maskbox = mb
            results.append({"box": [x1, y1, x2, y2], "conf": float(scores[i]),
                            "maskbox": maskbox or [x1, y1, x2, y2]})
        results.sort(key=lambda r: -r["conf"])
        return results

    def _detect_pass(self, img_rgb: np.ndarray) -> list[dict]:
        outputs, scale, px, py = self._run(img_rgb)
        return self._decode(img_rgb, outputs, scale, px, py)

    def _detect_tiled(self, img_rgb: np.ndarray) -> list[dict]:
        """分块召回(全图0检出且图大时兜底, 与BirdDetector同窗格)。"""
        h, w = img_rgb.shape[:2]
        if max(h, w) < self.TILE_GATE:
            return []
        allbox, allsc = [], []
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
        # 分块只回收"有没有鸟"——掩码在块边缘不可靠, 直接用检测框
        return [{"box": [float(v) for v in allbox[i]], "conf": float(allsc[i]),
                 "maskbox": [float(v) for v in allbox[i]]} for i in keep]
