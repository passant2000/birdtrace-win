# -*- coding: utf-8 -*-
"""SuperPicky识别引擎(2026-10-31彻底移植, 与0.6引擎并存可切换)。

与SuperPicky birdid/bird_identifier.py逐环节对齐(2026-10-31用其源码
在本机实跑验证过三条路径: CLI/服务端/GUI批处理preloaded_crop, 三者
最终裁剪同为smart_square_crop(bbox,0.15)):
- 检测: 同款yolo11l-seg@1024 conf0.25 COCO类14, 用**bbox**(其
  detect_and_crop_bird取box.xyxy, 不用分割掩码框), 最大置信框定主鸟
  不回退(其语义);
- 裁剪: bbox中心不动, 最长边×1.15, 越界黑填充保方形(=sp_square_crop,
  smart_square_crop同参);
- 分类: FastViT-MA36同权重(safetensors与生产ONNX实测逐位一致,
  见data/sp_engine/sp_repro_result.json), BICUBIC直缩384;
- 名录: ebird_regions.db硬过滤(sp_regions.json, 2026-10-31用户指示
  "名录也沿用superpicky"): 省州→国家两层逐层放宽, top-100内≥0.3%才
  有效; 有名录而全部落空=**不定种**(返回空, 照片进未识别), 绝不放宽
  到全世界(SuperPicky geo_filter.iter_candidates语义)。

贴茎场景眼锚定取景(2026-10-31用户批准加回, 收紧版):
- SuperPicky家族闭源版(iOS慧眼识鸟)的思路=关键点模型保头部入镜;
  眼点模型(cub200_keypoint_resnet50, 其HF仓库公开发布)与三分法构图
  (其core/crop_advisor)均为其自家组件。触发条件纯几何(眼在框顶+
  高瘦框=5837贴茎构图), 30例基准实测: 5837/5847/5853翻正mugfly,
  6033/6036/鸭组/鸥等全部原结果不变(零回归); 模型缺失时自动关闭
  回退纯SP行为(兼容旧包)。

非SP的保留项(均为用户明确指令, 非自标定):
- 写名/待复核语义(2026-11-02用户定案): 检测到鸟就写名, 置信<0.5由
  待复核页把关; 未识别只留无检测/非鸟门/名录落空。见RESCUE_BELOW注释;
- 尘埃门/非鸟门: 4663干水草43×38尘埃框教训/全局概率过低判非鸟。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .classifier import BirdClassifier, softmax
from .detector import BirdDetector
from .detector_seg import BirdSegDetector, SEG_DETECTOR_MODEL
from .keypoints import KeyPointDetector
from .pipeline import REJECT_GPROB, _square_at, load_rgb  # noqa: F401 (load_rgb复用)


def sp_square_crop(img: np.ndarray, bbox: list[int],
                   padding_ratio: float = 0.15) -> np.ndarray:
    """SuperPicky `detect_and_crop_bird` 的裁剪段逐行移植（identify_bird
    实际走这条，不是 tools/image_crop.smart_square_crop）。

    2026-11-03 修正：此前移植的是同仓库另一个函数 smart_square_crop，
    两者在**贴边裁剪**时行为不同——smart 版把不足部分补黑到
    target_side 的大方框(按偏移置入)，而 detect_and_crop_bird 只把
    裁剪结果贴到 max(crop_w,crop_h) 的方框中央、**不补到 target_side**。
    边缘鸟因此会带大片黑边，分类概率随之偏移。此外 target_side 用
    int() 截断(SP原样)，不是 round()。

    bbox=(x1,y1,x2,y2)int。返回方形 uint8 RGB 数组。"""
    x1, y1, x2, y2 = [int(v) for v in bbox]
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"invalid bbox: {bbox}")
    h, w = img.shape[:2]
    max_side = max(x2 - x1, y2 - y1)
    target_side = int(max_side * (1.0 + padding_ratio))
    if target_side < 1:
        target_side = 1
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    half = target_side // 2
    crop_x1, crop_y1 = max(0, cx - half), max(0, cy - half)
    crop_x2, crop_y2 = min(w, cx + half), min(h, cy + half)
    cropped = img[crop_y1:crop_y2, crop_x1:crop_x2]
    ch, cw = cropped.shape[:2]
    if cw == ch:
        return cropped
    sq = max(cw, ch)
    square = np.zeros((sq, sq, 3), np.uint8)
    paste_x, paste_y = (sq - cw) // 2, (sq - ch) // 2
    square[paste_y:paste_y + ch, paste_x:paste_x + cw] = cropped
    return square

# SuperPicky predict_bird语义常量(原样照搬, 无自标定)
SP_TOP_WINDOW = 100     # 只在top-100里找名录内物种
SP_MIN_PCT = 0.003      # 名录模式概率≥0.3%才算有效候选
SP_MIN_GLOBAL = 0.01    # 无名录(全球)模式门槛1.0%(其predict_bird:
                        # min_confidence = 0.3 if species_class_ids else 1.0)
SP_PADDING = 0.15       # bbox外扩(smart_square_crop同参)
# 写名/待复核语义(2026-11-02用户定案, 取代此前所有置信门方案):
#   检测到鸟(过尘埃门/非鸟门/名录) → 一律写名; 原始置信<0.5 由待复核页
#   人工把关(其筛选条件 conf<0.5)。未识别只留: 无检测框 / 非鸟门(全类
#   概率<5%) / 名录落空。
#   历史: bug4(10-31)0.50不写名 → 11-02午 0.30 → 11-02傍晚 0.20 →
#   11-02夜 用户拍板"有鸟就必须进待复核", 取消写名下限。
#   蛇例说明: 2441蛇 YOLO 检出(conf 0.67)、分类器给"鸡尾鹦鹉"raw 0.116,
#   按此语义会写名进待复核——这是检测器把蛇当鸟, 不是阈值能分开的;
#   待复核页提供「不是鸟」一键送回未识别。
RESCUE_BELOW = 0.20   # 默认取景置信低于此值时, 多取景取最佳(提高待复核质量)
# 眼锚定触发条件(收紧版, 30例基准标定data/sp_engine/sp_calib实测:
# "贴茎场景"=眼在框最上部+框明显高瘦。5837组 eye_y 0.07-0.12/aspect
# 1.84-2.09全命中翻正mugfly; 6033/6036红尾鸲 eye_y同低但aspect仅
# 1.19-1.21必须排除; 姬鹟5848/5876 aspect≥1.50命中且受益(0.91-0.99)。
# 分界eye_y<0.15且aspect≥1.45, 其余全部用SP原版bbox裁剪零扰动。
EYE_TOP_FRAC = 0.15
EYE_TALL_ASPECT = 1.45
EYE_SIDE_FACTOR = 0.80      # 重取景边长=bbox最长边×0.80。原0.68太紧——
# 紧裁系统性偏slbfly1(test7教训), 2026-11-02用户实测5859/5868锚定后仍
# slbfly1、5860/5861反被翻错; 0.80尺度扫描8张贴茎姬鹟全对(5859 m0.90/
# 5868 m0.89/5860 m0.95/5861 m0.98/5847 m0.88/5853 m0.95, 5837 m0.57
# 仍对——0.68时0.77但仅此一张降), 0.90丢5837, 定0.80。
EYE_THIRDS_OFFSET = 0.167   # 眼放上三分点: 取景中心=眼y+边长/6(其crop_advisor同法)


def sp_hard_filter(probs: np.ndarray, tiers: list[frozenset],
                   labels: list, topk: int) -> list[dict] | None:
    """SuperPicky predict_bird语义: 各层内取top-100中名录内且≥0.3%的
    物种; 某层有结果即停; 全部层落空且有名录→None(=不定种);
    无名录(tiers为空)→全球top-k。返回[(code,en,sci,prob)]。"""
    order = np.argsort(-probs)[:SP_TOP_WINDOW]
    if not tiers:
        picked = []
        for i in order[:topk]:
            if probs[int(i)] >= SP_MIN_GLOBAL:   # 全球模式1%门槛(其语义)
                lab = labels[int(i)]
                picked.append({"code": lab["code"], "en": lab["en"],
                               "sci": lab["sci"], "prob": float(probs[int(i)])})
        return picked or None
    for tier in tiers:
        picked = []
        for i in order:
            lab = labels[int(i)]
            if lab["code"] in tier and probs[int(i)] >= SP_MIN_PCT:
                picked.append({"code": lab["code"], "en": lab["en"],
                               "sci": lab["sci"],
                               "prob": float(probs[int(i)])})
                if len(picked) >= topk:
                    break
        if picked:
            return picked
    return None


def sp_extend_candidates(probs: np.ndarray, tiers: list[frozenset],
                         labels: list, picked: list[dict],
                         topk: int) -> list[dict]:
    """候选补齐(2026-11-05用户反馈: 待复核下拉没有top5, 只有"最近")。

    定种仍按SP语义(名录层内≥0.3%), 但**存库的候选列表**在不足topk时
    用同层后续物种补齐(不设0.3%下限, 概率仍为原始值)。低置信照片
    (如2.9%)的第二候选往往低于0.3%, 此前被截断→下拉只剩当前鸟种,
    用户无法点选近缘种。只影响top5_json(UI候选), 不改变species_code/
    confidence, 识别口径不变。"""
    if not picked or len(picked) >= topk or not tiers:
        return picked
    first = picked[0]["code"]
    tier = None
    for t in tiers:
        if first in t:
            tier = t
            break
    if tier is None:
        return picked
    seen = {p["code"] for p in picked}
    order = np.argsort(-probs)[:SP_TOP_WINDOW]
    for i in order:
        if len(picked) >= topk:
            break
        lab = labels[int(i)]
        if lab["code"] in tier and lab["code"] not in seen:
            picked.append({"code": lab["code"], "en": lab["en"],
                           "sci": lab["sci"], "prob": float(probs[int(i)])})
            seen.add(lab["code"])
    return picked


class SpRegionFilter:
    """sp_regions.json名录: {ebird_region: [code...]}, id_map: 我们区域id→ebird码。"""

    def __init__(self, path: str | Path):
        self.lists: dict[str, set[str]] = {}
        self.id_map: dict[str, str] = {}
        self._sets: dict[str, frozenset] = {}
        p = Path(path)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            self.lists = data.get("regions", {})
            self.id_map = data.get("id_map", {})

    def available(self) -> bool:
        return bool(self.lists)

    def _codes(self, ebird_region: str) -> frozenset:
        s = self._sets.get(ebird_region)
        if s is None:
            s = frozenset(self.lists.get(ebird_region, ()))
            self._sets[ebird_region] = s
        return s

    def tiers(self, region_id: str | None) -> list[frozenset]:
        """省州→国家候选层(无名录层跳过)。region_id是我们的id(如CN-SH)。
        完全无可用层返回[](调用方按不过滤处理)。"""
        if not region_id or region_id == "GLOBAL" or not self.lists:
            return []
        ebird = self.id_map.get(region_id)
        if not ebird:
            return []
        out = []
        if "-" in ebird:
            sub = self._codes(ebird)
            if sub:
                out.append(sub)
            country = self.id_map.get(ebird.split("-")[0]) \
                or ebird.split("-")[0]
            cset = self._codes(country)
            if cset:
                out.append(cset)
        else:
            cset = self._codes(ebird)
            if cset:
                out.append(cset)
        return out


class SpRecognitionEngine:
    def __init__(self, detector_path: str, classifier_path: str,
                 labels_path: str, regions_path: str,
                 keypoint_path: str | None = None,
                 use_gpu: bool = True, conf_thr: float = 0.25,
                 min_conf: float = 0.0):
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
        self.regions = SpRegionFilter(regions_path)
        # 眼点模型缺失(旧包)→锚定自动关闭, 纯SP行为
        self.keypoints = (KeyPointDetector(keypoint_path, use_gpu=use_gpu)
                          if keypoint_path and Path(keypoint_path).exists()
                          and keypoint_path.endswith(".onnx") else None)
        if self.keypoints is not None and not self.keypoints.available():
            self.keypoints = None
        self.min_conf = min_conf

    def _eye_anchor_crop(self, img: np.ndarray, box: list[float]) -> np.ndarray | None:
        """贴茎场景眼锚定重取景(收紧触发, 见模块docstring与常量注释)。
        不触发/无模型/眼不可见→None(用SP原版bbox裁剪)。"""
        if self.keypoints is None:
            return None
        x1, y1, x2, y2 = box
        bw, bh = x2 - x1, y2 - y1
        if bw <= 0 or bh <= 0 or bh < EYE_TALL_ASPECT * bw:
            return None
        crop = img[int(y1):int(y2), int(x1):int(x2)]
        det = self.keypoints.detect(crop)
        if det is None:
            return None
        (ex, ey), _vis, _beak = det
        if ey >= EYE_TOP_FRAC:
            return None
        side = int(round(max(bw, bh) * EYE_SIDE_FACTOR))
        cx = x1 + ex * bw
        cy = y1 + ey * bh + side * EYE_THIRDS_OFFSET
        return _square_at(img, cx, cy, side)

    # ---- 内部 ----

    def _probs(self, crop_rgb: np.ndarray) -> np.ndarray:
        logits = self.classifier.logits(crop_rgb, "square")
        return softmax(logits.astype(np.float64))

    def _hard_filter(self, probs: np.ndarray, tiers: list[frozenset],
                     topk: int) -> list[dict] | None:
        return sp_hard_filter(probs, tiers, self.classifier.labels, topk)

    def _classify_box(self, img: np.ndarray, box: list[float],
                      tiers: list[frozenset], topk: int,
                      min_conf: float | None = None) -> tuple[dict | None, str]:
        """返回(记录|None, 拒因)。拒因: none/nonbird/lowconf。
        nonbird=全局概率过低(顺延下一检测框); lowconf=名录落空。
        置信默认不设写名下限(2026-11-02用户语义): 检测到鸟就写名,
        <0.5 由待复核页把关; min_conf 保留参数仅作调试/特殊调用用。
        裁剪=SuperPicky detect_and_crop_bird(bbox, 0.15)逐像素移植;
        贴茎构图(几何触发)时改用眼锚定收紧取景——**无条件覆盖**。
        2026-11-03 试过"两种取景取置信高者", 结果5837/5847回退成
        slbfly1: 默认取景对错答案反而更自信(0.86 vs 锚定对mugfly 0.77),
        与test7"置信度在错答上更高"的结论一致。故保留无条件覆盖。
        """
        gate = self.min_conf if min_conf is None else min_conf
        crop = sp_square_crop(img, [int(v) for v in box], SP_PADDING)
        anchored = self._eye_anchor_crop(img, box)
        if anchored is not None:
            crop = anchored
        probs = self._probs(crop)
        gprob = float(probs.max())
        if gprob < REJECT_GPROB:
            return None, "nonbird"              # 非鸟门: 顺延下一检测框
        picked = self._hard_filter(probs, tiers, topk)
        if not picked:                          # 名录全落空
            return None, "lowconf"
        # 候选补齐: 低置信时第二候选常低于0.3%被截断, 待复核下拉会看不到
        # 近缘种(定种/置信不变, 只补UI候选; 2026-11-05用户反馈)
        picked = sp_extend_candidates(probs, tiers, self.classifier.labels,
                                      picked, topk)
        raw0 = float(picked[0]["prob"])
        if raw0 < gate:
            return None, "lowconf"              # 低置信: 不写鸟名(未识别)
        # 概率一律用**原始值**(名录外概率不计入)——归一化到名录内会让
        # 单一候选显示100%(用户实测"100%黑翅鸢"进未识别/待复核漏筛的
        # 根源, 2026-11-02傍晚改); 待复核页按conf<0.5筛原始值才准。
        top5 = [{"code": p["code"], "en": p["en"], "sci": p["sci"],
                 "prob": float(p["prob"]), "rank": rank}
                for rank, p in enumerate(picked, 1)]
        return {
            "species_code": top5[0]["code"],
            "confidence": raw0,
            "source": "sp",
            "box": box,
            "top5": top5,
        }, "none"

    # ---- 对外(与RecognitionPipeline同形, importer无感切换) ----

    def _variant_crops(self, img: np.ndarray, box: list[float]) -> list:
        """同框的额外取景: 紧裁/放宽/眼锚定(不受贴茎几何限制)。
        模型对鸟与背景占比敏感(作者原话"对裁切极敏感", test7亦实测
        紧裁/放宽各有胜场); 默认取景置信低时用它们取最佳。"""
        x1, y1, x2, y2 = [float(v) for v in box]
        bw, bh = x2 - x1, y2 - y1
        out = [sp_square_crop(img, [int(v) for v in box], 0.0),    # 紧裁
               sp_square_crop(img, [int(v) for v in box], 0.30)]   # 放宽
        if self.keypoints is not None and bw > 0 and bh > 0:
            det = self.keypoints.detect(
                img[int(y1):int(y2), int(x1):int(x2)])
            if det is not None:
                (ex, ey), _vis, _beak = det
                side = int(round(max(bw, bh) * EYE_SIDE_FACTOR))
                out.append(_square_at(
                    img, x1 + ex * bw,
                    y1 + ey * bh + side * EYE_THIRDS_OFFSET, side))
        return out

    def _record_from_picked(self, picked: list, raw0: float,
                            box: list, source: str = "sp") -> dict:
        top5 = [{"code": p["code"], "en": p["en"], "sci": p["sci"],
                 "prob": float(p["prob"]), "rank": rank}
                for rank, p in enumerate(picked, 1)]
        return {
            "species_code": top5[0]["code"],
            "confidence": float(raw0),
            "source": source,
            "box": [int(v) for v in box],
            "top5": top5,
        }

    def _best_variant(self, img, box, tiers, topk) -> dict | None:
        """多种取景里取原始概率最高者(画框识别/低置信救援共用)。"""
        best: tuple[float, list, "np.ndarray"] | None = None
        for crop in self._variant_crops(img, box):
            probs = self._probs(crop)
            if float(probs.max()) < REJECT_GPROB:
                continue
            picked = self._hard_filter(probs, tiers, topk)
            if not picked:
                continue
            raw0 = float(picked[0]["prob"])
            if best is None or raw0 > best[0]:
                best = (raw0, picked, probs)
        if best is None:
            return None
        picked = sp_extend_candidates(best[2], tiers,
                                      self.classifier.labels, best[1], topk)
        return self._record_from_picked(picked, best[0], box)

    def recognize(self, img_rgb: np.ndarray, region_id: str | None,
                  month: int, topk: int = 5) -> list[dict]:
        """主鸟=最高检测置信过两道门的候选(SuperPicky同法+尘埃门/非鸟门)。

        语义(2026-11-02用户定): **检测到鸟就写名**——置信低也写, 由
        待复核页(conf<0.5)人工把关; 未识别只留: 无检测框/非鸟门
        (全类概率<5%)/名录落空。默认取景置信<RESCUE_BELOW时再用
        紧裁/放宽/眼锚定取最佳(提高待复核里的答案质量, 不改变取舍口径)。
        """
        dets = self.detector.detect(img_rgb)
        h, w = img_rgb.shape[:2]
        min_side = max(48, int(0.01 * min(h, w)))
        tiers = self.regions.tiers(region_id)
        for d in dets[:5]:
            box = d["box"]                   # SuperPicky用bbox, 不用maskbox
            box = [int(v) for v in box]      # 其detect_and_crop_bird存int框, 对齐
            if max(box[2] - box[0], box[3] - box[1]) < min_side:
                continue                     # 尘埃门: 顺延
            rec, why = self._classify_box(img_rgb, box, tiers, topk,
                                          min_conf=0.0)
            if why == "nonbird":
                continue                     # 非鸟门: 顺延下一候选框
            if rec and rec["confidence"] < RESCUE_BELOW:
                better = self._best_variant(img_rgb, box, tiers, topk)
                if better and better["confidence"] > rec["confidence"]:
                    rec = better
            return [rec] if rec else []      # 名录落空→未识别

    def recognize_box(self, img_rgb: np.ndarray, box: list[float],
                      region_id: str | None, month: int | None = None,
                      topk: int = 5) -> dict | None:
        """画框识别(查看器/画框工具, 用户随时可用): 跳过检测, 直接分类+名录。
        **多种取景取原始概率最高者**——用户主动框选=要最佳猜测, 不该被
        单一取景尺度坑(2026-11-02: 同一框紧裁/放宽raw可差数倍)。
        不过置信门, 非鸟门与名录过滤仍生效。"""
        box = [float(v) for v in box]
        tiers = self.regions.tiers(region_id)
        rec = self._best_variant(img_rgb, box, tiers, topk)
        if rec:
            rec["source"] = "rebox"
        return rec
