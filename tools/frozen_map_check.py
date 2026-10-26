# -*- coding: utf-8 -*-
"""冻结版地图验证: 启动exe(--open-page map), 实拍窗口, 检查地图像素, 读日志。

用法: .venv/Scripts/python -u tools/frozen_map_check.py
前置: packaging/dist/birdtrace 已构建; data/frozen_lib 测试库已就绪。
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from pathlib import Path

from PIL import ImageGrab

PROJ = Path(__file__).resolve().parent.parent
EXE = PROJ / "packaging" / "dist" / "birdtrace" / "鸟迹BirdTrace.exe"
LIB = PROJ / "data" / "frozen_lib"
TITLE = "鸟迹 · 鸟类照片管理"

user32 = ctypes.windll.user32


def find_window():
    hwnd = user32.FindWindowW(None, TITLE)
    return hwnd or None


def window_rect(hwnd):
    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def main():
    log = LIB / "birdtrace.log"
    if log.exists():
        log.unlink()
    proc = subprocess.Popen([str(EXE), "--library", str(LIB), "--open-page", "map"])
    print("launched pid", proc.pid, flush=True)
    try:
        hwnd = None
        for _ in range(40):
            time.sleep(1)
            hwnd = find_window()
            if hwnd:
                break
        if not hwnd:
            print("FAIL: window not found in 40s")
            return 1
        print("window found:", hwnd, flush=True)
        time.sleep(15)   # 等WebEngine+AMap JS加载
        bbox = window_rect(hwnd)
        img = ImageGrab.grab(bbox=bbox, all_screens=True)
        out = PROJ / "data" / "ui_shots" / "frozen_map.png"
        img.save(out)
        w, h = img.size
        crop = img.crop((int(w * 0.30), int(h * 0.20), int(w * 0.90), int(h * 0.70)))
        colors = crop.convert("RGB").getcolors(maxcolors=400000)
        nc = len(colors) if colors else -1
        print(f"截图 {out.name} size={img.size} 地图区色数={nc}", flush=True)
        print("VERDICT:", "PASS" if nc > 3000 else "FAIL(地图区疑似空白)", flush=True)
    finally:
        # /T 杀整棵进程树(exe+其QtWebEngineProcess子进程), 防止占用dist目录
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True)
    time.sleep(2)
    if log.exists():
        text = log.read_text(encoding="utf-8", errors="replace")
        print("=== birdtrace.log (last 30 lines) ===")
        print("\n".join(text.splitlines()[-30:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
