# -*- coding: utf-8 -*-
"""美学评分后台线程: 给"有识别记录但未评分"的照片补1~10美学分。

只评有records的照片(无鸟/识别失败的不参与最美排序);
模型缺失(旧包/资产不全)时静默跳过, 不影响任何现有功能。
CPU推理在本线程执行(onnxruntime释放GIL), 界面不受拖累。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..db import Library


class AestheticWorker(QThread):
    progress = Signal(int, int)        # done, total
    finished_all = Signal(dict)        # {"done": n, "ok": n, "missing_model": bool}

    def __init__(self, lib: Library, assets_dir: Path, parent=None):
        super().__init__(parent)
        self.lib = lib
        self.assets = Path(assets_dir)
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        from ..ai.aesthetic import MODEL_FILENAME, AestheticScorer
        model = self.assets / "models" / MODEL_FILENAME
        if not model.exists():
            self.finished_all.emit({"done": 0, "ok": 0, "missing_model": True})
            return
        rows = self.lib.pending_aesthetic()
        total = len(rows)
        if not total:
            self.finished_all.emit({"done": 0, "ok": 0})
            return
        scorer = AestheticScorer(model)
        done = ok = 0
        for r in rows:
            if self._stop:
                break
            s = scorer.score_file(r["path"])
            if s is not None:
                self.lib.set_aesthetic(r["id"], s)
                ok += 1
                if ok % 20 == 0:      # 分批提交, 中断也保住已算的
                    self.lib.conn.commit()
            done += 1
            if done % 5 == 0 or done == total:
                self.progress.emit(done, total)
        self.lib.conn.commit()
        self.finished_all.emit({"done": done, "ok": ok})


class BurstWorker(QThread):
    """连拍分组重算(0.8-③): 识别/美学回填完成后或规则版本变化时后台跑。

    只读照片表+缩略图算哈希(首次对老库会逐张算 dHash, 之后落库缓存);
    结果直接写 photos.group_id, 完成后主窗口刷新时间线/鸟种页。"""
    finished_all = Signal(dict)        # {"groups": n, "photos": n, "changed": n}

    def __init__(self, lib: Library, parent=None):
        super().__init__(parent)
        self.lib = lib

    def run(self):
        try:
            res = self.lib.regroup_bursts()
        except Exception as e:          # 分组失败不影响任何现有功能
            res = {"groups": 0, "photos": 0, "changed": 0, "error": str(e)}
        self.finished_all.emit(res)
