# -*- coding: utf-8 -*-
"""EXIF提取(Pillow) + HEIC支持。"""
from __future__ import annotations

import pillow_heif
from PIL import Image, ImageOps

pillow_heif.register_heif_opener()

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".mpo", ".bmp", ".tif", ".tiff"}


def _ratio_to_float(v) -> float | None:
    if v is None:
        return None
    try:
        if isinstance(v, tuple):
            num, den = v
            return float(num) / float(den) if den else None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str) and "/" in v:
            num, den = v.split("/", 1)
            return float(num) / float(den) if float(den) else None
        return float(v)
    except Exception:
        return None


def _gps_to_degrees(gps_ifd: dict, key_lat: int, key_lon: int,
                    ref_lat: int, ref_lon: int) -> tuple[float | None, float | None]:
    def conv(v):
        try:
            d, m, s = v
            return float(d) + float(m) / 60 + float(s) / 3600
        except Exception:
            return None
    lat = conv(gps_ifd.get(key_lat)) if key_lat in gps_ifd else None
    lon = conv(gps_ifd.get(key_lon)) if key_lon in gps_ifd else None
    if lat is not None and gps_ifd.get(ref_lat) not in (None, "N", "E"):
        lat = -lat
    if lon is not None and gps_ifd.get(ref_lon) not in (None, "N", "E"):
        lon = -lon
    return lat, lon


def read_exif(path: str) -> dict:
    """返回规范化EXIF字段; 无EXIF返回空字段。"""
    ex: dict = {}
    try:
        with Image.open(path) as im:
            ex["width"], ex["height"] = im.size
            exif = im.getexif()
            if not exif:
                return ex
            ex["orientation"] = exif.get(274)
            ex["make"] = (exif.get(271) or "").strip() or None
            ex["model"] = (exif.get(272) or "").strip() or None
            ex["artist"] = (exif.get(315) or "").strip() or None
            exif_ifd = exif.get_ifd(0x8769)
            dt = exif_ifd.get(36867) or exif.get(306)
            if dt:
                # "YYYY:MM:DD HH:MM:SS" -> "YYYY-MM-DD HH:MM:SS"
                s = str(dt).strip()
                parts = s.split(" ", 1)
                if len(parts) == 2 and ":" in parts[0]:
                    ex["dt_original"] = parts[0].replace(":", "-") + " " + parts[1]
                else:
                    ex["dt_original"] = s
            ex["iso"] = exif_ifd.get(34855)
            exposure = _ratio_to_float(exif_ifd.get(33434))
            if exposure:
                ex["exposure"] = (f"1/{round(1/exposure)}" if exposure < 1
                                  else f"{exposure:g}")
            ex["fnum"] = _ratio_to_float(exif_ifd.get(33437))
            ex["focal_len"] = _ratio_to_float(exif_ifd.get(37386))
            lens = exif_ifd.get(42036)
            ex["lens"] = (str(lens).strip() or None) if lens else None
            gps = exif.get_ifd(0x8825)
            if gps:
                ex["gps_lat"], ex["gps_lon"] = _gps_to_degrees(
                    gps, 2, 4, 1, 3)  # GPSLatitude(2)/Ref(1), Longitude(4)/Ref(3)
    except Exception as e:
        ex["error"] = str(e)
    return ex


def month_of(dt_original: str | None, fallback_month: int = 1) -> int:
    if dt_original and len(dt_original) >= 7:
        try:
            return int(dt_original[5:7])
        except ValueError:
            pass
    return fallback_month


def load_rgb(path: str):
    from PIL import ImageOps
    import numpy as np
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        return np.asarray(im)
