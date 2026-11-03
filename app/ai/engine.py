# -*- coding: utf-8 -*-
"""识别引擎工厂(2026-10-31定版: SuperPicky彻底移植为唯一引擎)。

不设用户切换(用户指示"只用这一个引擎"); 0.6引擎代码保留在
app/ai/pipeline.py 仅作开发对照。sp_regions.json缺失(旧裁包)时
自动回退0.6引擎保证可运行。
"""
from __future__ import annotations

from pathlib import Path


def engine_setting(get_setting=None) -> str:
    """唯一引擎=sp; 仅当名录资产缺失时回退v06(兼容旧裁包)。"""
    return "sp"


def build_recognizer(assets_dir: str | Path, engine: str,
                     use_gpu: bool = True, conf: float = 0.25):
    """构造识别器。engine="sp"且名录资产在→SpRecognitionEngine, 否则0.6。"""
    assets = Path(assets_dir)
    from .detector import DETECTOR_MODEL
    if engine == "sp" and (assets / "data" / "sp_regions.json").exists():
        from .sp_engine import SpRecognitionEngine
        return SpRecognitionEngine(
            detector_path=str(assets / "models" / DETECTOR_MODEL),
            classifier_path=str(assets / "models" / "BirdTraceRecognitionModel.onnx"),
            labels_path=str(assets / "data" / "labels.json"),
            regions_path=str(assets / "data" / "sp_regions.json"),
            keypoint_path=str(assets / "models" / "cub200_keypoint.onnx"),
            use_gpu=use_gpu, conf_thr=conf)
    from .pipeline import RecognitionPipeline
    return RecognitionPipeline(
        detector_path=str(assets / "models" / DETECTOR_MODEL),
        classifier_path=str(assets / "models" / "BirdTraceRecognitionModel.onnx"),
        labels_path=str(assets / "data" / "labels.json"),
        geo_prior_path=str(assets / "data" / "geo_prior.sqlite"),
        use_gpu=use_gpu, conf_thr=conf)
