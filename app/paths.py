# -*- coding: utf-8 -*-
"""路径解析: 开发态=项目目录; 打包态=exe旁。"""
from __future__ import annotations

import sys
from pathlib import Path


def proj_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def assets_dir() -> Path:
    return proj_root() / "assets"
