# -*- coding: utf-8 -*-
"""原图可用性判定(0.8-② 移动硬盘离线韧性)。

区分两种"找不到":
  OFFLINE  所在卷未接入(F: 拔了/网络盘断开)——缩略图/标注/统计照常,
           插回即恢复, 不该叫"丢失", 也不该让用户去"重新链接";
  MISSING  卷在但文件不在原位置(移动/改名/删除)——需要重新链接或移除。

性能: 每个卷只 stat 一次; 离线卷下的文件不再逐个 stat(万张库瞬间完成)。
"""
from __future__ import annotations

import os
from pathlib import PurePath, PureWindowsPath
from typing import Iterable

OK, OFFLINE, MISSING = 0, 1, 2


def drive_root(path: str) -> str:
    """路径所在卷根("F:\\" / "\\\\nas\\photos\\" / "/"); 相对路径返回""。"""
    try:
        p = PureWindowsPath(path) if os.name == "nt" else PurePath(path)
        return p.anchor or ""
    except (TypeError, ValueError):
        return ""


def drive_label(root: str) -> str:
    """横幅显示用: "F:" / "\\\\nas\\photos"。"""
    return root.rstrip("\\/") or root


def classify_paths(items: Iterable[tuple[int, str]]) -> dict:
    """批量判定 [(id, path)] →
    {"ok": [ids], "offline": {卷根: [ids]}, "missing": [ids]}。"""
    online_cache: dict[str, bool] = {}
    out = {"ok": [], "offline": {}, "missing": []}
    for pid, path in items:
        root = drive_root(path)
        if root:
            online = online_cache.get(root)
            if online is None:
                online = os.path.exists(root)
                online_cache[root] = online
            if not online:
                out["offline"].setdefault(root, []).append(pid)
                continue
        if os.path.exists(path):
            out["ok"].append(pid)
        else:
            out["missing"].append(pid)
    return out


def path_state(path: str) -> int:
    """单路径判定 → OK/OFFLINE/MISSING(查看器/分享卡等单张场景)。"""
    root = drive_root(path)
    if root and not os.path.exists(root):
        return OFFLINE
    return OK if os.path.exists(path) else MISSING
