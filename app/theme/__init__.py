# -*- coding: utf-8 -*-
"""theme包: 子模块theme.py持真实值, 这里动态代理(apply_theme切换后引用即时生效)。"""
from . import theme as _t
from .theme import apply_theme  # noqa: F401  (常用入口)


def __getattr__(name: str):
    return getattr(_t, name)


def __dir__():
    return dir(_t)
