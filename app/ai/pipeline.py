# -*- coding: utf-8 -*-
"""识别管线: 检测 -> 裁剪 -> 分类 -> 地理先验重排 -> top-k 记录。"""
from __future__ import annotations

import numpy as np
from PIL import Image

from .classifier import BirdClassifier
from .detector import BirdDetector
from .geo_prior import GeoPrior

CROP_MARGIN = 0.10   # 裁剪框外扩比例, 保留上下文
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


class RecognitionPipeline:
    def __init__(self, detector_path: str, classifier_path: str, labels_path: str,
                 geo_prior_path: str, prior_strength: float = 0.6,
                 preprocess_strategy: str = "squash", use_gpu: bool = True,
                 conf_thr: float = 0.25, reject_gprob: float = REJECT_GPROB):
        self.detector = BirdDetector(detector_path, conf_thr=conf_thr, use_gpu=use_gpu)
        self.classifier = BirdClassifier(classifier_path, labels_path, use_gpu=use_gpu)
        self.prior = GeoPrior(geo_prior_path, strength=prior_strength)
        self.strategy = preprocess_strategy
        self.reject_gprob = reject_gprob

    def _classify_box(self, img_rgb: np.ndarray, box: list[float],
                      region_id: str | None, month: int | None,
                      topk: int) -> dict | None:
        """对单个框裁剪分类+重排, 返回单条记录(全局概率过低判非鸟→None)。"""
        crop = crop_with_margin(img_rgb, box)
        log_probs, scores = self.prior.rerank(
            self.classifier.logits(crop, self.strategy), region_id, month)
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
        """返回记录列表(可能多条=多鸟):
        [{species_code, confidence, source, box, top5:[(code,en,prob)...]}]
        confidence为重排后top1概率(top5内相对)。

        无检测框(画面无鸟, 如牛/风景)返回[]——不再做整图兜底:
        标定实测整图牛会被硬分成某鸟种(全局概率0.51)且与难认真鸟无法区分,
        兜底记录只会污染鸟种统计, 不如留给人工「标注鸟种」。
        检测框的全局概率(万类softmax)低于reject_gprob判非鸟丢弃。
        """
        records: list[dict] = []
        dets = self.detector.detect(img_rgb)
        for d in dets[:5]:  # 最多取5个检测框, 防极端误检拖慢
            rec = self._classify_box(img_rgb, d["box"], region_id, month, topk)
            if rec:
                records.append(rec)
        records.sort(key=lambda r: -r["confidence"])
        return records

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
