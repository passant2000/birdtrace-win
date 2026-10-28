# -*- coding: utf-8 -*-
"""鸟迹 BirdTrace for Windows 入口。

用法: python -m app.main
可选参数: --library <照片库目录>  --no-gpu
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .i18n import t
from .paths import assets_dir


def default_library_dir_hidden():
    from .db import default_library_dir
    return default_library_dir()


def _startup_mark(name: str):
    """启动分段计时(BT_TIMING=1时写exe旁startup_timing.log, 排查启动慢用)。"""
    import os
    import time
    if os.environ.get("BT_TIMING") != "1":
        return
    global _T0
    if "_T0" not in globals():
        _T0 = time.time()
    try:
        from .paths import proj_root
        with open(proj_root() / "startup_timing.log", "a", encoding="utf-8") as f:
            f.write(f"{time.time() - _T0:6.2f}s  {name}\n")
    except OSError:
        pass


def main():
    _startup_mark("main入口")  # i18n:ok
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", default=None, help="照片库目录")  # i18n:ok
    ap.add_argument("--no-gpu", action="store_true", help="禁用DirectML, 用CPU推理")  # i18n:ok
    ap.add_argument("--open-page", default=None,
                    help="启动后直接切到某页(如 map)，测试用")  # i18n:ok
    ap.add_argument("--recognize-worker", action="store_true",
                    help="内部: 以识别worker模式运行(不建GUI, 冻结态识别子进程复用本exe)")  # i18n:ok
    ap.add_argument("--gpu-probe", action="store_true",
                    help="显卡诊断: 测试DirectML各配置并写gpu_probe_result.txt")  # i18n:ok
    ap.add_argument("--cpu", action="store_true",
                    help=argparse.SUPPRESS)  # 冻结态worker自我复用时的CPU开关
    ap.add_argument("--conf", default="0.25", help=argparse.SUPPRESS)
    args, _ = ap.parse_known_args()

    if args.recognize_worker:
        # 识别worker模式: 读stdin行任务, 写stdout JSON行; 不初始化任何GUI
        from .ai.recognize_sub import run_worker
        run_worker(assets_dir(), conf=args.conf,
                   use_gpu=not getattr(args, "cpu", False))
        return

    if args.gpu_probe:
        # 显卡诊断模式: 不建GUI, 结果写在exe旁
        from .ai.gpu_probe import run_probe
        run_probe(assets_dir())
        return

    assets = assets_dir()
    if not (assets / "models" / "BirdTraceRecognitionModel.onnx").exists():
        sys.exit(t("缺少模型资产: 请将 assets/ 目录放在程序旁, 或运行 tools/extract_assets.py",
          "Missing model assets: place the assets/ folder next to the app, or run tools/extract_assets.py"))

    # WebEngine(地图页)要求: AA_ShareOpenGLContexts属性在QApplication创建前设置。
    # QtWebEngineWidgets本身懒加载(地图页首开时import), 不在启动期拉起194MB DLL
    _startup_mark("资产检查完")  # i18n:ok
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

    from . import theme
    from .db import Library, default_library_dir

    app = QApplication(sys.argv)
    app.setApplicationName("鸟迹 BirdTrace")  # i18n:ok
    _startup_mark("QApplication创建")  # i18n:ok

    lib = Library(Path(args.library) if args.library else default_library_dir())
    # 主题须在创建任何窗口前应用(库先行以读取设置)
    theme.apply_theme(app, lib.get_setting("theme", "system"))
    from . import i18n
    i18n.set_lang(lib.get_setting("lang", "zh"))
    if not lib.species_filled():
        lib.fill_species()
    lib.maybe_backup()   # 自动备份(24h节流)
    _startup_mark("库打开+species+备份")  # i18n:ok

    from .ui.main_window import MainWindow
    win = MainWindow(lib, assets)
    _startup_mark("MainWindow构建")  # i18n:ok
    win.show()
    _startup_mark("show")  # i18n:ok
    if args.open_page:
        win.switch_to(args.open_page)
    win.start_recognition()  # 恢复上次未完成的识别
    _startup_mark("启动完成")  # i18n:ok
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
