# -*- coding: utf-8 -*-
"""家燕迁徙地图52周录屏: 迁徙对话框程序化自渲染逐周抓帧 → PNG序列。

只抓对话框自身(dlg.grab()), 绝不抓全屏/用户桌面。数据用
data/migration_probe的真实barswa包种子进测试库缓存, 离线渲染。

用法: .venv/Scripts/python.exe tools/capture_migration_video.py
输出: data/mig_capture/frames/frame_XX.png (1100x740)
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB_DIR = PROJ / "data/mig_capture_lib"
OUT_DIR = PROJ / "data/mig_capture/frames"


def seed_cache():
    """probe真实数据 → 测试库迁徙缓存(免96MB下载, SHA与线上目录一致)。"""
    mig = LIB_DIR / "migration"
    mig.mkdir(parents=True, exist_ok=True)
    shutil.copy(PROJ / "data/mig_catalog.json", mig / "catalog.json")
    shutil.copy(PROJ / "data/migration_probe/barswa_surface_tiles.sqlite",
                mig / "barswa.sqlite")
    shutil.copy(PROJ / "data/mig_barswa_manifest.json",
                mig / "barswa.manifest.json")


def wait_until(pred, timeout_s: float, step_ms: int = 200,
               app=None) -> bool:
    from PySide6.QtCore import QEventLoop, QTimer
    deadline_remaining = timeout_s * 1000
    while deadline_remaining > 0:
        if pred():
            return True
        loop = QEventLoop()
        QTimer.singleShot(step_ms, loop.quit)
        loop.exec()
        if app:
            app.processEvents()
        deadline_remaining -= step_ms
    return pred()


def main():
    for d in (LIB_DIR,):
        if d.exists():
            shutil.rmtree(d)
    seed_cache()

    # 注意: 必须用windows平台真窗口渲染——offscreen下①WebEngine内容不会被
    # 合成进grab()(地图区全白)②无字体(文字全豆腐块)。抓帧约1分钟, 窗口
    # 会在桌面短暂显示(用户已知情并要求录制)。
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme
    theme.apply_theme(app, "light")
    from pathlib import Path as _P
    from app.db import Library
    from app.ui.migration_view import MigrationMapDialog

    lib = Library(LIB_DIR)
    lib.fill_species()
    win = QWidget()

    dlg = MigrationMapDialog(lib, win, "barswa")
    dlg.resize(1100, 740)
    dlg.show()
    app.processEvents()

    ok = wait_until(lambda: dlg._data_ready and dlg._ready, 180, app=app)
    if not ok:
        print(f"FAILED: 数据/地图未就绪 data_ready={dlg._data_ready} "
              f"ready={dlg._ready} status={dlg._status.text()[:60]}")
        sys.exit(1)
    # 底图瓦片加载余量 + 首帧渲染
    wait_until(lambda: False, 8, step_ms=500, app=app)
    # 数据就绪时对话框自动开始播放(_on_decoded里_timer.start(), 900ms/周)。
    # 抓帧循环周期≈0.9s与播放定时器同频, 会系统性错位一周——必须停掉。
    dlg._timer.stop()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    weeks = dlg._timeline.weeks()
    print(f"数据就绪, 共{weeks}周, 开始逐周抓帧…", flush=True)
    for w in range(1, weeks + 1):
        dlg._on_week(w)
        # 等WebEngine把该周渲染完(setPaintProperty生效)
        wait_until(lambda: False, 0.7, step_ms=100, app=app)
        pm = dlg.grab()
        pm.save(str(OUT_DIR / f"frame_{w:02d}.png"), "PNG")
        if w % 10 == 0:
            print(f"  第{w}周…", flush=True)
    # 英雄帧(第26周, 北半球盛夏/繁殖季)单存全分辨率
    dlg._on_week(26)
    wait_until(lambda: False, 1.0, step_ms=100, app=app)
    dlg.grab().save(str(PROJ / "data/mig_capture/hero_week26.png"), "PNG")
    print(f"完成: {weeks}帧 + hero_week26.png → {OUT_DIR}")
    dlg.close()


if __name__ == "__main__":
    main()
