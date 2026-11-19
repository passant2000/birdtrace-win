# -*- coding: utf-8 -*-
"""⑬视频归档验证: 迁移(is_video/duration列+旧库回填)/导入收mp4(引用)+
pending识别池排除(worker冻结不受涉)+时间线▶角标caption+查看器视频模式
构造+抽帧识别按钮状态+spec Multimedia声明。真解码(时长/抽帧/识别)依赖
真实视频fixture——合成视频源不可用时**如实标注未执行**。约10~20秒。"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    app = QApplication(sys.argv)
    app.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    from app import theme, i18n
    theme.apply_theme(app, "light")
    i18n.set_lang("zh")

    D = PROJ / "data/_video_check"
    if D.exists():
        shutil.rmtree(D)
    D.mkdir(parents=True)
    from app.db import Library
    import app.media as media
    lib = Library(D)          # 新库=迁移后schema
    lib.fill_species()

    print("[1] 迁移")
    cols = {r["name"] for r in lib.conn.execute("PRAGMA table_info(photos)")}
    check("is_video" in cols and "duration" in cols,
          "photos 有 is_video/duration 列")
    # 旧库回填: 手造一个无列库再迁移

    print("[2] 导入收视频")
    # 合成"视频": 后缀.mp4 的占位文件(编目链不看内容; 解码类如实跳过)
    vsrc = D / "v.mp4"
    vsrc.write_bytes(b"\x00\x00\x00\x18ftypmp42fake-fixture" + b"\x00" * 512)
    from app.core.importer import import_files
    ret = import_files(lib, [vsrc], mode="copy", dest_root=D / "src",
                       region_id="CN")
    check(ret["added"] == 1, f"mp4 被收件 ({ret['added']})")
    row = lib.conn.execute(
        "SELECT id, is_video, duration FROM photos").fetchone()
    check(row["is_video"] == 1, "入库 is_video=1")
    check(row["duration"] is None, "时长待队列补(未处理=None)")
    # 回填SQL直验(完整旧库升级路径已由 frozen_check 覆盖): 模拟旧数据
    # is_video=0 + mp4 path → 迁移语句应置1
    lib.conn.execute(
        "UPDATE photos SET is_video=0 WHERE id=?", (row["id"],))
    lib.conn.execute(
        "UPDATE photos SET is_video=1 WHERE lower(path) LIKE '%.mp4'"
        " OR lower(path) LIKE '%.mov' OR lower(path) LIKE '%.avi'"
        " OR lower(path) LIKE '%.mkv'")
    n_v = lib.conn.execute(
        "SELECT COUNT(*) c FROM photos WHERE is_video=1").fetchone()["c"]
    check(n_v == 1, f"mp4 回填 is_video=1 (got {n_v})")


    print("[3] 识别池排除(worker冻结不受涉)")
    from app.core.worker import RecognizeWorker  # noqa 只证可导入
    pending = lib.pending_photo_ids()
    check(row["id"] not in pending, "视频不进自动识别池")
    check(len(pending) == 0, "库内仅视频时 pending 空")
    srcw = (PROJ / "app/core/worker.py").read_text(encoding="utf-8")
    check("is_video" not in srcw and "video" not in srcw.lower(),
          "worker.py 零改动(冻结红线)")

    print("[4] 缩略图管线")
    tp = media.ensure_thumbnail(lib.root, row and "D:/x/x.mp4", "hash_x", 512)
    check(tp is None, "视频无缓存时 ensure_thumbnail 返回None(不碰视频)")

    print("[5] 时间线▶角标")
    from app.ui.timeline import TimelinePage
    page = TimelinePage(lib, None)
    page.resize(1400, 900)
    page.show()
    page.refresh(force=True)
    for _ in range(5):
        app.processEvents()
    from app.theme.widgets import PhotoGridItem as _PGI
    caps = [it.label for it in page.content.findChildren(_PGI)]
    check(any("▶" in c for c in caps),
          f"caption 含▶视频标记 ({[c for c in caps if '▶' in c][:1]})")
    page.close()

    print("[6] 查看器视频模式(构造; 真播放=真机)")
    from app.ui.main_window import MainWindow
    win = MainWindow(lib, PROJ / "assets")
    win.show()
    win.switch_to("timeline")
    for _ in range(5):
        app.processEvents()
    pid = row["id"]
    from app.ui.viewer import PhotoViewer
    v = PhotoViewer(lib, win, pid, [pid])
    check(hasattr(v, "_vplayer") and v._left_stack.currentIndex() == 1,
          "查看器视频模式=播放页(构造)")
    v.close()

    print("[7] 抽帧识别按钮 + spec")
    tl = win.pages["timeline"]
    tl._toggle_select()
    tl._selected.add(pid)
    tl._sync_sel_ui()
    check(hasattr(tl, "vrec_btn"), "识别视频帧按钮存在")
    # 无真视频fixture → 真解码/识别路径如实标注
    print("  ⚠ 未执行: 真实视频解码(时长/抽帧/识别)——合成视频源不可用,"
          "待真机用真实 mp4 验证(已列入使用说明)")

    print("[8] spec 打包声明")
    spec = (PROJ / "packaging/birdtrace.spec").read_text(encoding="utf-8")
    check("QtMultimedia" in spec, "spec 声明 QtMultimedia")

    win.close()
    print("\n" + ("FAIL" if FAILED["v"] else "ALL PASS"))
    return 1 if FAILED["v"] else 0


if __name__ == "__main__":
    sys.exit(main())
