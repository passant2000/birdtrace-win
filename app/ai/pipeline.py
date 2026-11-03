# -*- coding: utf-8 -*-
"""识别管线: 检测(含分割掩码框) -> 裁剪 -> 分类 -> 地理先验重排 -> top-k 记录。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from .classifier import BirdClassifier
from .detector import BirdDetector
from .detector_seg import BirdSegDetector, SEG_DETECTOR_MODEL
from .geo_prior import GeoPrior

CROP_MARGIN = 0.05   # 旧宽框策略(squash/letterbox/ensemble)的裁剪框外扩比例
SQUARE_MARGIN = 0.08  # 已废弃(test6旧方形裁剪外扩); 仅旧评测工具仍引用
AUTHOR_PADDING = 0.15  # 方形裁剪总外扩(SuperPicky smart_square_crop同参,
                       # 2026-10-31作者路线24例验证19/24胜出现状15: l-seg
                       # 掩码框+1.15外扩+黑填充; 越界补黑不squash)
WHOLE_FALLBACK_CONF_CAP = 0.0  # 整图兜底记录的标记权重(存库时用 source 区分)
REJECT_GPROB = 0.05  # 全类别softmax全局概率低于此判定"非鸟"(如牛/人误检), 丢弃


def load_rgb(path: str) -> np.ndarray:
    from PIL import ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        return np.asarray(im)


def crop_with_margin(img: np.ndarray, box: list[float], margin: float = CROP_MARGIN) -> np.ndarray:
    h, w = img.shape[:2]
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    x1, y1 = max(0, x1 - bw * margin), max(0, y1 - bh * margin)
    x2, y2 = min(w, x2 + bw * margin), min(h, y2 + bh * margin)
    return img[int(y1):int(y2), int(x1):int(x2)]


def square_crop(img: np.ndarray, box: list[float], margin: float = 0.0) -> np.ndarray:
    """检测框方形化(框中心不动, 短边扩到长边成方形, 越界裁到图内)。
    test6旧裁法——越界裁边会得到非方形被resize压扁; test7起识别主路
    改author_crop(黑填充保方形), 本函数保留供旧评测工具对照。"""
    h, w = img.shape[:2]
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    s = max(bw, bh) * (1 + 2 * margin)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    nx1, ny1 = max(0, int(cx - s / 2)), max(0, int(cy - s / 2))
    nx2, ny2 = min(w, int(cx + s / 2)), min(h, int(cy + s / 2))
    return img[ny1:ny2, nx1:nx2]


def _square_at(img: np.ndarray, cx: float, cy: float, side: int) -> np.ndarray:
    """以(cx,cy)为中心裁side×side方形, 越界补黑(SuperPicky smart_square_crop同法)。"""
    h, w = img.shape[:2]
    if side < 1:
        side = 1
    ix1, iy1 = max(0, int(cx - side / 2)), max(0, int(cy - side / 2))
    ix2, iy2 = min(w, int(cx + side / 2)), min(h, int(cy + side / 2))
    cropped = img[iy1:iy2, ix1:ix2]
    ah, aw = cropped.shape[:2]
    if ah == side and aw == side:
        return cropped
    square = np.zeros((side, side, 3), np.uint8)
    square[iy1 - int(cy - side / 2):iy1 - int(cy - side / 2) + ah,
           ix1 - int(cx - side / 2):ix1 - int(cx - side / 2) + aw] = cropped
    return square


def author_crop(img: np.ndarray, box: list[float],
                padding: float = AUTHOR_PADDING) -> np.ndarray:
    """SuperPicky smart_square_crop 复刻(见tools对照实验data/_diag_lseg):
    框中心不动, 最长边×(1+padding)成正方形, 越界部分补黑保方形,
    随后classifier"square"策略BICUBIC直缩384。掩码外接框+此裁法
    =作者路线; 黑填充比裁边squash稳(不变形)。"""
    x1, y1, x2, y2 = box
    side = int(round(max(x2 - x1, y2 - y1) * (1.0 + padding)))
    return _square_at(img, (x1 + x2) / 2, (y1 + y2) / 2, side)


BIG_BIRD_FRAC = 0.45  # 鸟最长边≥图短边此比例=大鸟(苇丛/枝头中距构图)


def frame_crop(img: np.ndarray, box: list[float]) -> np.ndarray:
    """两档取景(test8): 大鸟→图中心整图方形; 小鸟→author_crop紧裁剪。

    模型对"鸟占画面比例"极度敏感: 紧裁剪(鸟≈87%)系统性偏向锈胸蓝姬鹟/
    澳洲鸥嘴噪鸥, 自然尺度+生境上下文(鸟40-70%)才是正确输入——
    2026-10-31整图矩阵实验(36例基准): 整图27 > 掩码p50 25 > 紧裁19,
    且紧裁命中的19例全被整图覆盖; 但纯整图对"小鸟大天空"(鹞/鸢/云雀)
    翻车20%, 故小鸟维持紧裁。两档=27/36+已对记录回归40/40。
    鸟贴图边不在中心方形内时以鸟为中心黑填充, 不丢主体。"""
    h, w = img.shape[:2]
    x1, y1, x2, y2 = box
    md = max(x2 - x1, y2 - y1)
    side = min(h, w)
    if md >= BIG_BIRD_FRAC * side:
        ox1, oy1 = (w - side) / 2, (h - side) / 2
        if x1 >= ox1 and y1 >= oy1 and x2 <= ox1 + side and y2 <= oy1 + side:
            cx, cy = w / 2, h / 2          # 鸟完整在中心方形内→图中心整图
        else:
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2   # 贴边→鸟中心同边长黑填充
        return _square_at(img, cx, cy, side)
    return author_crop(img, box)


class RecognitionPipeline:
    """prior_strength=1.0(2026-10-31两档取景下78例重标定: 0.8=83%→1.0=86%,
    2877/4663翻正鸥嘴噪鸥且1.0~2.0平台零回归, 取最温和达标值保真迷鸟余量;
    注意6033/6036红尾鸲对先验完全同权2.00, 地理无法区分属模型抛硬币)。"""
    def __init__(self, detector_path: str, classifier_path: str, labels_path: str,
                 geo_prior_path: str, prior_strength: float = 1.0,
                 preprocess_strategy: str = "square", use_gpu: bool = True,
                 conf_thr: float = 0.25, reject_gprob: float = REJECT_GPROB):
        # l-seg掩码框驱动(文件缺则回退m/nano检测框, 兼容旧包与裁包)
        p = Path(detector_path)
        if p.name == SEG_DETECTOR_MODEL and not p.exists():
            for fb in ("BirdTraceBirdDetector_YOLO11m.onnx",
                       "BirdTraceBirdDetector_FP32.onnx"):
                if p.with_name(fb).exists():
                    p = p.with_name(fb)
                    break
        if p.name == SEG_DETECTOR_MODEL:
            self.detector = BirdSegDetector(str(p), conf_thr=conf_thr, use_gpu=use_gpu)
        else:
            self.detector = BirdDetector(str(p), conf_thr=conf_thr, use_gpu=use_gpu)
        self.classifier = BirdClassifier(classifier_path, labels_path, use_gpu=use_gpu)
        self.prior = GeoPrior(geo_prior_path, strength=prior_strength)
        self.strategy = preprocess_strategy
        self.reject_gprob = reject_gprob

    def _classify_box(self, img_rgb: np.ndarray, box: list[float],
                      region_id: str | None, month: int | None,
                      topk: int) -> dict | None:
        """对单个框裁剪分类+重排, 返回单条记录(全局概率过低判非鸟→None)。
        2026-10-31起无涂灰遮蔽: 掩码框已贴鸟身, 下部栖枝/腿不再被框进来,
        涂灰反而毁鸻鹬腿特征(431白腰草鹬实测涂灰→美洲种, 去灰→0.97)。"""
        if self.strategy == "square":
            crop = frame_crop(img_rgb, box)
            logits_in = self.classifier.logits(crop, self.strategy)
        else:
            crop = crop_with_margin(img_rgb, box)
            if self.strategy == "ensemble":
                # 滑窗集成: 多视图平均概率转回logits域给先验重排
                # (softmax(log p)=p, 先验加法对常数平移不变)
                from .classifier import ensemble_views
                logits_in = np.log(self.classifier.probs_views(
                    ensemble_views(crop)) + 1e-12)
            else:
                logits_in = self.classifier.logits(crop, self.strategy)
        log_probs, scores = self.prior.rerank(
            logits_in, region_id, month)
        lse = float(np.logaddexp.reduce(scores))
        gprob = float(np.exp(scores.max() - lse))
        if gprob < self.reject_gprob:
            return None
        order = np.argsort(-scores)[:topk]
        probs = np.exp(scores[order] - scores[order].max())
        probs = probs / probs.sum()
        top5 = []
        for rank, (ci, p) in enumerate(zip(order, probs), 1):
            lab = self.classifier.labels[int(ci)]
            top5.append({"code": lab["code"], "en": lab["en"],
                         "sci": lab["sci"], "prob": float(p), "rank": rank})
        return {
            "species_code": top5[0]["code"],
            "confidence": float(top5[0]["prob"]),
            "source": "detect",
            "box": box,
            "top5": top5,
        }

    def recognize(self, img_rgb: np.ndarray, region_id: str | None, month: int,
                  topk: int = 5) -> list[dict]:
        """返回主鸟记录列表(0或1条):
        [{species_code, confidence, source, box, top5:[(code,en,prob)...]}]
        confidence为重排后top1概率(top5内相对)。

        主鸟=最高检测置信且通过两道门的候选(SuperPicky同法):
        · 尘埃门: 掩码框边长<max(48px, 图短边1%)的碎屑框丢弃——
          4663实测43×38px尘埃框放大后高置信认成白眼潜鸭0.54,
          把真鹞(检测0.96, 分类仅0.43)挤成主鸟(按分类置信选主的教训)。
        · 非鸟门: 全局概率<reject_gprob判非鸟丢弃, 顺延下一候选。
        无检测框(画面无鸟, 如牛/风景)返回[]——不做整图兜底:
        标定实测整图牛会被硬分成某鸟种(全局概率0.51)且与难认真鸟
        无法区分, 兜底记录只会污染鸟种统计, 不如留给人工「标注鸟种」。
        次级候选留top5"次选"(查看器可见); 确认的第二只鸟用画框识别补。
        """
        dets = self.detector.detect(img_rgb)
        h, w = img_rgb.shape[:2]
        min_side = max(48, int(0.01 * min(h, w)))
        for d in dets[:5]:   # 按检测置信降序, 第一个过两道门者为主鸟
            box = d.get("maskbox") or d["box"]
            if max(box[2] - box[0], box[3] - box[1]) < min_side:
                continue
            rec = self._classify_box(img_rgb, box, region_id, month, topk)
            if rec:
                return [rec]
        return []

    def recognize_box(self, img_rgb: np.ndarray, box: list[float],
                      region_id: str | None, month: int | None,
                      topk: int = 5) -> dict | None:
        """跳过检测, 对用户指定/调整过的框直接分类(查看器"用此框重新识别")。
        返回单条记录或None(该框判非鸟)。"""
        box = [float(v) for v in box]
        rec = self._classify_box(img_rgb, box, region_id, month, topk)
        if rec:
            rec["source"] = "rebox"
        return rec

    def close(self):
        self.prior.close()
