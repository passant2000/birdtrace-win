# -*- coding: utf-8 -*-
"""机/镜显示别名(1.0冲刺⑫②, 调研 Z's Gallery camera_aliases 思路):
裸型号 → 友好显示名(分享卡参数行/装备榜)。内置种子=常见型号补品牌
或官方名; 用户可扩展 assets/data/camera_aliases.json(键=原始型号串,
值=显示名; 文件不存在时只用内置)。无命中=原样返回(零风险)。
映射大小写不敏感(机型串在EXIF里大小写不一)。"""
from __future__ import annotations

import json
from pathlib import Path

_SEED: dict[str, str] = {
    # 索尼: 裸型号补系列名
    "ilce-7cm2": "SONY α7C II",
    "ilce-7m4": "SONY α7 IV",
    "ilce-7rm5": "SONY α7R V",
    "ilce-9m2": "SONY α9 II",
    "ilce-9m3": "SONY α9 III",
    "ilce-6700": "SONY α6700",
    # 手机: 工程代号 → 市场名
    "2203121c": "小米12S Ultra",  # i18n:ok 数据码(设备市场名)
    "2311drk47c": "小米14 Ultra",  # i18n:ok 同上
    # 大疆
    "fc3582": "DJI Mavic 3",
}

_cache: dict[str, str] | None = None


def _load() -> dict[str, str]:
    global _cache
    if _cache is not None:
        return _cache
    m = {k.lower(): v for k, v in _SEED.items()}
    try:
        from ..paths import assets_dir
        f = Path(assets_dir()) / "data" / "camera_aliases.json"
        if f.is_file():
            obj = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                m.update({str(k).lower(): str(v) for k, v in obj.items()})
    except Exception:
        pass
    _cache = m
    return m


def alias_of(raw: str | None) -> str:
    """原始机/镜串 → 显示名; 无命中原样返回。"""
    s = (raw or "").strip()
    if not s:
        return s
    return _load().get(s.lower(), s)
