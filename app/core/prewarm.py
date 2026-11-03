# -*- coding: utf-8 -*-
"""启动后的后台预热(2026-10-31): 消除首次切地图页的冷加载卡顿。

真库实测: 首次switch_to('map')冷态9.2s/热态0.3s, 大头是QtWebEngine
系DLL(约194MB)的磁盘IO+渲染进程拉起。这里在启动完成数秒后用子线程
把Python模块/DLL先加载进进程——DLL加载的文件IO会释放GIL, UI线程
保持响应; 到用户真切地图时只剩视图创建(~0.2s)。
"""
from __future__ import annotations

import threading

_DONE = False
_DELAY_S = 6.0     # 启动完成后再等6s: 避开启动IO高峰与首屏渲染


def _prewarm():
    global _DONE
    try:
        import importlib
        importlib.import_module("PySide6.QtWebEngineCore")
        importlib.import_module("PySide6.QtWebEngineWidgets")
    except Exception:
        pass           # 预热失败不影响任何功能, 地图页照常懒加载
    finally:
        _DONE = True


def schedule_webengine_prewarm() -> None:
    import threading as _th

    timer = _th.Timer(_DELAY_S, _prewarm)
    timer.daemon = True
    timer.start()
    # 防止重复调度(测试里多次调用main路径)
    global _DONE
    _DONE = _DONE or False
