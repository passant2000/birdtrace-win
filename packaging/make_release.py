# -*- coding: utf-8 -*-
"""发布脚本: PyInstaller构建 + 复制外置模型资产到 dist。

用法: .venv/Scripts/python.exe packaging/make_release.py
产物: packaging/dist/birdtrace/ (含 鸟迹BirdTrace.exe 与 assets/)
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
DIST = PROJ / "packaging" / "dist" / "birdtrace"

COPY_FILES = [
    "assets/data/geo_prior.sqlite",
    "assets/data/labels.json",
    "assets/data/species_catalog.json",
    "assets/data/regions.json",
    "assets/data/sp_regions.json",
    "assets/data/country_zh.json",
    "assets/data/iucn_status.json",
    "assets/data/cn_name_overrides.json",
    "assets/data/model_manifest.properties",
    "assets/data/details_v2.btd",
    "assets/data/details_index_v2.bin",
    "assets/data/bird_culture.sqlite",
    "assets/brand/logo.png",
    "assets/map/maplibre-gl.js",
    "assets/map/maplibre-gl.css",
    "assets/map/china_provinces.json",
    "assets/templates/site_index.html",
]


def prune_dist(d: Path) -> int:
    """删除打包产物中的死重(不碰模型与运行必需库), 返回释放的字节数。

    - WebEngine开发者工具资源(devtools pak / debug snapshot)——地图不需要
    - Qt翻译文件只留 zh_CN / en / webengine_locales 同理
    - (libx265不能删: pillow-heif的Windows二进制硬链接了它, 删则HEIC模块整体加载失败)
    """
    import fnmatch
    freed = 0

    def kill(path: Path):
        nonlocal freed
        if not path.exists():
            return
        if path.is_dir():
            size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            shutil.rmtree(path, ignore_errors=True)
        else:
            size = path.stat().st_size
            try:
                path.unlink()
            except OSError:
                return
        freed += size
        print(f"prune {path.relative_to(d)} ({size // 1048576}MB)")

    pyside = d / "_internal" / "PySide6"
    # 1) devtools与debug资源
    for pat in ("qtwebengine_devtools_resources*.pak", "*.debug.pak",
                "v8_context_snapshot.debug.bin"):
        for f in pyside.glob(f"resources/{pat}"):
            kill(f)
    # 2) 翻译只留中英
    tr = pyside / "translations"
    if tr.is_dir():
        keep_qm = {"qt_zh_CN.qm", "qt_en.qm", "qt_zh.qm"}
        for f in tr.glob("*.qm"):
            if f.name not in keep_qm:
                kill(f)
        for sub in tr.iterdir():
            if sub.is_dir():   # qtwebengine_locales等
                keep_locales = {"zh-CN.pak", "en-US.pak", "zh-TW.pak"}
                for f in sub.glob("*.pak"):
                    if f.name not in keep_locales:
                        kill(f)
    return freed


def main():
    subprocess.check_call([
        sys.executable, "-m", "PyInstaller", "--noconfirm",
        "--distpath", str(PROJ / "packaging" / "dist"),
        "--workpath", str(PROJ / "packaging" / "build"),
        str(PROJ / "packaging" / "birdtrace.spec"),
    ], cwd=PROJ)

    (DIST / "assets" / "models").mkdir(parents=True, exist_ok=True)
    (DIST / "assets" / "data").mkdir(parents=True, exist_ok=True)
    # 白名单只拷运行时实际加载的模型: glob会把assets/models/里
    # 混入的实验模型(DML排查的_dml/_sim变体, 各~214MB)全量带上, 体积翻倍
    # 正式版0.6.0: 检测带l-seg分割(运行时)+nano(诊断/回退); m(80MB)为
    # test7-9时代回退件, 源码与旧测试包里有, 正式包不再携带
    for m in ("BirdTraceBirdDetector_YOLO11lSeg.onnx",
              "BirdTraceBirdDetector_FP32.onnx",
              "BirdTraceRecognitionModel.onnx",
              "AestheticTOPIQ_fp16.onnx",
              # 眼点模型(SuperPicky同款, 贴茎构图眼锚定取景用; .data是其
              # 外置权重, PyInstaller导出ONNX时>2GB限制外置, 两个文件必须一起)
              "cub200_keypoint.onnx",
              "cub200_keypoint.onnx.data"):
        shutil.copy2(PROJ / "assets" / "models" / m,
                     DIST / "assets" / "models" / m)
        print("copy", m)
    for rel in COPY_FILES:
        dst = DIST / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJ / rel, dst)
        print("copy", rel)
    freed = prune_dist(DIST)
    print(f"prune freed {freed // 1048576}MB")
    print("RELEASE READY:", DIST)


if __name__ == "__main__":
    main()
