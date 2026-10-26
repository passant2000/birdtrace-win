# -*- coding: utf-8 -*-
"""构造演示库: 给测试图注入不同拍摄日期的EXIF, 走完整导入+识别, 供UI体验。"""
from __future__ import annotations

import io
import shutil
import sys
from pathlib import Path

from PIL import Image

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB = PROJ / "data" / "demo_lib"
SRC = PROJ / "data" / "test_images"

# 每张图分配的拍摄时间(错开月份, 制造时间线层次)
DATES = {
    "Alcedo_atthis.jpg": "2024:05:12 08:31:00",
    "Cyanistes_caeruleus.jpg": "2024:05:12 09:02:00",
    "Passer_montanus.jpg": "2024:06:03 07:15:00",
    "Ardea_cinerea.jpg": "2024:11:20 15:40:00",
    "Upupa_epops.jpg": "2025:04:18 10:05:00",
    "Anas_platyrhynchos.jpg": "2025:12:06 14:22:00",
}
REGION = "CN"

# GPS: 奥森南园两图(相距~110m, 验证300m自动归组同一鸟点)、
# 野鸭湖两图(相距~250m)、两图无GPS
GPS = {
    "Alcedo_atthis.jpg": (40.0035, 116.3950),
    "Passer_montanus.jpg": (40.0041, 116.3958),
    "Ardea_cinerea.jpg": (40.4600, 115.7100),
    "Anas_platyrhynchos.jpg": (40.4615, 115.7115),
}


def _dms(v: float) -> tuple[float, float, float]:
    """十进制度 -> (度, 分, 秒) 浮点三元组(Pillow会自动转RATIONAL)。"""
    d = int(v)
    m_float = (v - d) * 60
    m = int(m_float)
    s = (m_float - m) * 60
    return (float(d), float(m), round(s, 4))


def inject_exif(src: Path, dt: str) -> Path:
    out = PROJ / "data" / "demo_src" / src.name
    out.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(src).convert("RGB")
    exif = Image.Exif()
    exif[306] = dt                       # DateTime
    ifd = exif.get_ifd(0x8769)
    ifd[36867] = dt                      # DateTimeOriginal
    ifd[36868] = dt                      # DateTimeDigitized
    ifd[34855] = 800                     # ISO
    ifd[33434] = (1, 1600)               # ExposureTime 1/1600
    ifd[33437] = (56, 10)                # FNumber 5.6
    ifd[37386] = (400, 1)                # FocalLength 400mm
    exif[271] = "Canon"
    exif[272] = "Canon EOS R7"
    if src.name in GPS:
        lat, lon = GPS[src.name]
        gps = exif.get_ifd(0x8825)
        gps[1] = "N"
        gps[2] = _dms(abs(lat))
        gps[3] = "E"
        gps[4] = _dms(abs(lon))
    im.save(out, "JPEG", quality=90, exif=exif)
    return out


def main():
    if LIB.exists():
        shutil.rmtree(LIB)
    from app.db import Library
    from app.core.importer import import_files, scan_sources

    files = [inject_exif(f, DATES[f.name]) for f in sorted(SRC.glob("*.jpg"))]
    lib = Library(LIB)
    lib.fill_species()
    stats = import_files(lib, files, mode="ref", dest_root=None, region_id=REGION)
    print("import:", stats)

    from app.ai.pipeline import RecognitionPipeline, load_rgb
    from app.exif import month_of
    pipe = RecognitionPipeline(
        detector_path=str(PROJ / "assets/models/BirdTraceBirdDetector_FP32.onnx"),
        classifier_path=str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
        labels_path=str(PROJ / "assets/data/labels.json"),
        geo_prior_path=str(PROJ / "assets/data/geo_prior.sqlite"),
    )
    t0 = __import__("time").time()
    for pid in lib.pending_photo_ids():
        photo, _ = lib.photo_detail(pid)
        recs = pipe.recognize(load_rgb(photo["path"]),
                              lib.region_for_photo(pid),
                              month_of(photo.get("dt_original"), 5))
        lib.add_records(pid, recs)
        print(f"  {Path(photo['path']).name}: "
              f"{[(r['species_code'], round(r['confidence'], 2)) for r in recs]}")
    print(f"recognized in {__import__('time').time()-t0:.1f}s")
    pipe.close()
    print("lifers:", [(li["lifer_no"], li["cn"]) for li in lib.lifers()])
    print("spots:", [(s["id"], s["name"], s["n_photos"], s["n_species"])
                     for s in lib.spots_overview()])
    lib.close()
    print("DEMO LIB READY:", LIB)


if __name__ == "__main__":
    main()
