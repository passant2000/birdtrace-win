# -*- coding: utf-8 -*-
"""识别后台线程: 拉取未识别照片 -> 检测/分类/先验重排 -> 落库。"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..db import Library
from ..paths import proj_root
from ..exif import month_of, read_exif
from ..media import file_hash


class RecognizeWorker(QThread):
    progress = Signal(int, int, str)     # done, total, 当前文件名
    photo_done = Signal(int)             # photo_id
    finished_all = Signal(dict)          # 汇总

    def __init__(self, lib: Library, assets_dir: Path, use_gpu: bool = True,
                 parent=None):
        super().__init__(parent)
        self.lib = lib
        self.assets = Path(assets_dir)
        self.use_gpu = use_gpu
        self._stop = False
        self.pipe = None

    def stop(self):
        self._stop = True

    def _ensure_pipeline(self):
        if self.pipe is not None:
            return
        from ..ai.pipeline import RecognitionPipeline
        conf = float(self.lib.get_setting("detect_conf", "0.25"))
        self.pipe = RecognitionPipeline(
            detector_path=str(self.assets / "models" / "BirdTraceBirdDetector_FP32.onnx"),
            classifier_path=str(self.assets / "models" / "BirdTraceRecognitionModel.onnx"),
            labels_path=str(self.assets / "data" / "labels.json"),
            geo_prior_path=str(self.assets / "data" / "geo_prior.sqlite"),
            use_gpu=self.use_gpu,
            conf_thr=conf,
        )

    def run(self):
        """识别在独立子进程中逐张执行(multiprocessing), 与UI线程GIL完全隔离——
        识别再重也不拖累界面(根治"无响应"假死)。

        子进程协议: stdin行 = photo_id 	 path 	 region 	 month
                    stdout行 = JSON {pid, ok, records|error}
        库写入在主线程(本QThread)完成, 避免跨进程写SQLite。

        波次循环: 每批pending处理完再看一眼队列——导入与识别并行时
        (导入线程边入库边由start_recognition反复拉起), 新导入的照片
        在下一波被自动拾取, 无需等全部导入完成。
        """
        import json as _json
        import subprocess
        import sys as _sys

        from ..ai.recognize_sub import build_worker_cmd

        assets = str(self.assets)
        conf = self.lib.get_setting("detect_conf", "0.25")
        self._fail_missing = 0
        grand_done = grand_ok = 0
        proc = None
        # 滑动窗口: 预发INFLIGHT张任务, 子进程并行解码(解码才是大头,
        # GPU推理~10ms/张), 按发送顺序收结果——吞吐≈解码并行度
        INFLIGHT = 3

        def send_next() -> bool:
            pid = next(tasks, None)
            if pid is None:
                return False
            if self._stop:
                return False
            path, region, month = meta[pid]
            self.progress.emit(wave_done["n"], total, Path(path).name)
            proc.stdin.write(f"{pid}\t{path}\t{region}\t{month}\n")
            proc.stdin.flush()
            window.append(pid)
            return True

        def read_result():
            """读一条JSON结果; 子进程死亡返回None。"""
            while True:
                line = proc.stdout.readline()
                if not line:
                    return None
                line = line.strip()
                # onnxruntime的EP告警会打到stdout, 只认JSON结果行
                if line.startswith("{"):
                    try:
                        return _json.loads(line)
                    except ValueError:
                        continue

        try:
            while not self._stop:
                ids = self.lib.pending_photo_ids()
                if not ids:
                    break
                meta = {}
                for pid in ids:
                    photo, _recs = self.lib.photo_detail(pid)
                    region = self.lib.region_for_photo(pid) or ""
                    ex = self.lib.conn.execute(
                        "SELECT dt_original FROM exif WHERE photo_id=?",
                        (pid,)).fetchone()
                    meta[pid] = (photo["path"], region,
                                 str(month_of(ex["dt_original"] if ex else None)
                                     or ""))
                total = len(ids)
                wave_done = {"n": 0}
                wave_ok = 0
                window: list[int] = []     # 已发送待应答的pid(有序)
                tasks = iter(ids)
                while True:
                    if proc is None:
                        # 冻结态=复用主exe自身, 源码态=python -m
                        # (cmd构造细节与"冻结态不能用-m"的原因见build_worker_cmd)
                        cmd, cwd = build_worker_cmd(assets, conf)
                        proc = subprocess.Popen(
                            cmd, cwd=cwd,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True,
                            encoding="utf-8")
                    if not window:
                        # 预发窗口(每波开始都要填——proc复用的后续波次
                        # 也走这里, 不能只在新建进程时预发)
                        for _ in range(INFLIGHT):
                            if not send_next():
                                break
                    if not window:
                        break
                    res = read_result()
                    if res is None:
                        # 子进程崩溃: 在飞的全部记失败, 重启后从下一张继续
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        proc = None
                        for pid in list(window):
                            self.lib.bump_rec_fail(pid)
                            wave_done["n"] += 1
                        window.clear()
                        continue
                    pid = res.get("pid")
                    if pid not in window:
                        pid = window[0]
                    window.remove(pid)
                    path = meta[pid][0]
                    if res.get("ok"):
                        recs = res.get("records") or []
                        if recs:
                            self.lib.add_records(pid, recs)
                        else:
                            self.lib.mark_no_bird(pid)
                        wave_ok += 1
                    else:
                        self.lib.bump_rec_fail(pid)
                        msg = str(res.get('error'))
                        print(f"recognize failed #{pid} {Path(path).name}: {msg}")
                        if "No such file" in msg:
                            self._fail_missing += 1
                    wave_done["n"] += 1
                    self.photo_done.emit(pid)
                    send_next()
                grand_done += wave_done["n"]
                grand_ok += wave_ok
                # 循环回顶部: 再查pending(导入并行中新增的照片在此拾取)
        finally:
            if proc:
                try:
                    proc.stdin.close()
                    proc.wait(timeout=10)
                except Exception:
                    proc.kill()
        self.progress.emit(grand_done, grand_done, "")
        self.finished_all.emit({"done": grand_done, "total": grand_done,
                                "ok": grand_ok,
                                "missing_files": self._fail_missing})
