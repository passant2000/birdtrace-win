# -*- coding: utf-8 -*-
"""鸟点: GPS距离计算 + 导入时自动归组(300m内并入最近点, 否则新建)。"""
from __future__ import annotations

import math

from ..i18n import t

AUTO_GROUP_M = 300.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两经纬度间的地表距离(米)。"""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def format_coord(lat: float | None, lon: float | None) -> str:
    if lat is None or lon is None:
        return t("无坐标", "No coordinates")
    return f"{lat:.4f}, {lon:.4f}"


def auto_assign_spot(lib, photo_id: int, lat: float, lon: float) -> tuple[int, bool]:
    """把照片归组到300m内的鸟点; 没有则自动新建"鸟点 N"。

    返回 (spot_id, 是否新建)。逐张导入顺序调用即可完成批量聚类:
    同一批同地照片会并入同一个先建出来的点。
    """
    spot, _d = lib.nearest_spot(lat, lon, AUTO_GROUP_M)
    if spot is not None:
        lib.set_photo_spot(photo_id, spot["id"])
        return spot["id"], False
    n = lib.conn.execute("SELECT COUNT(*) FROM spots").fetchone()[0] + 1
    name = f"鸟点 {n}"  # i18n:ok
    while lib.conn.execute("SELECT 1 FROM spots WHERE name=?", (name,)).fetchone():
        n += 1
        name = f"鸟点 {n}"  # i18n:ok
    sid = lib.create_spot(name, lat, lon, note="按GPS自动创建")  # i18n:ok
    lib.set_photo_spot(photo_id, sid)
    return sid, True
