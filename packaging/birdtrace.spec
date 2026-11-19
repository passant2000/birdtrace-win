# -*- mode: python ; coding: utf-8 -*-
# 鸟迹 BirdTrace 打包配置: onedir, 模型资产外置(exe旁assets/)
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

def _data(rel):
    return (os.path.join(ROOT, rel), os.path.dirname(rel))

# assets全部外置(exe旁assets/), 不再打包进_internal——避免双份且永不读取的死重
datas = []
binaries = collect_dynamic_libs("pillow_heif")
hiddenimports = collect_submodules("pypinyin")
hiddenimports += ["rawpy"]  # RAW解码(函数内懒import, 显式声明防漏收)
hiddenimports += ["PySide6.QtMultimedia",
                  "PySide6.QtMultimediaWidgets"]  # ⑬视频(播放+抽帧)

a = Analysis(
    [os.path.join(ROOT, "app_main.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "numpy.tests",
        "PySide6.QtPdf", "PySide6.QtQml",
        "PySide6.QtQuick", "PySide6.QtCharts", "PySide6.QtTest",
        "pytest", "setuptools", "pip",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="鸟迹BirdTrace",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(ROOT, "assets", "brand", "logo.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="birdtrace",
)
