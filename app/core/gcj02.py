# -*- coding: utf-8 -*-
"""WGS84 <-> GCJ-02 纠偏(火星坐标)。

鸟点库存WGS84(照片EXIF GPS真实值); 高德瓦片与高德POI返回值为GCJ-02,
显示时 wgs84_to_gcj02, 地图取点时 gcj02_to_wgs84 反算回库。
算法为国标偏移的通用公开实现, 城区内精度约1m, 满足观鸟点位需求。
"""
from __future__ import annotations

import math

_A = 6378245.0
_EE = 0.00669342162296594323


def out_of_china(lat: float, lon: float) -> bool:
    """大陆+港澳范围粗判, 境外坐标无偏移直接返回。"""
    return not (73.66 < lon < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(x: float, y: float) -> float:
    ret = (-100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y
           + 0.2 * math.sqrt(abs(x)))
    ret += (20.0 * math.sin(6.0 * x * math.pi)
            + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi)
            + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi)
            + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = (300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y
           + 0.1 * math.sqrt(abs(x)))
    ret += (20.0 * math.sin(6.0 * x * math.pi)
            + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi)
            + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi)
            + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    if out_of_china(lat, lon):
        return lat, lon
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = 1 - _EE * math.sin(radlat) ** 2
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * math.pi)
    dlon = (dlon * 180.0) / (_A / sqrtmagic * math.cos(radlat) * math.pi)
    return lat + dlat, lon + dlon


def gcj02_to_wgs84(lat: float, lon: float) -> tuple[float, float]:
    """近似逆变换(两次迭代, 误差~1m)。"""
    if out_of_china(lat, lon):
        return lat, lon
    g_lat, g_lon = lat, lon
    w_lat, w_lon = lat, lon
    for _ in range(2):
        g_lat, g_lon = wgs84_to_gcj02(w_lat, w_lon)
        w_lat += lat - g_lat
        w_lon += lon - g_lon
    return w_lat, w_lon
