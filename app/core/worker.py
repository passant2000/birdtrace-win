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
        from ..ai.engine import build_recognizer, engine_setting
        conf = float(self.lib.get_setting("detect_conf", "0.25"))
        self.pipe = build_recognizer(
            self.assets, engine_setting(self.lib.get_setting),
            use_gpu=self.use_gpu, conf=conf)

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
        from ..ai.engine import engine_setting

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
                        cmd, cwd = build_worker_cmd(
                            assets, conf,
                            engine=engine_setting(self.lib.get_setting))
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


class GroupRescueWorker(QThread):
    """整组重识别＝多取景全局最优(0.8.6连拍组全错, 用户拍板P1+P2)。

    连拍各帧近乎同画面→模型错误相关, 组内取最高置信救不回"整组全错";
    但各帧鸟的姿态/遮挡不同, **换取景常有一帧认对**——对组内每帧两轮:
    ①无框(标准识别, 同主管线)拿主检测框 ②带框(多取景取最佳, 与画框
    识别同一条recognize_sub协议路径), 取全局最高置信的帧×取景结果
    应用到整组(连拍=同一只鸟, 与连拍统一同源假设)。

    ⚠️识别管线只读(用户红线2026-11-18): 本类只调用现成build_worker_cmd
    子进程协议, 引擎/阈值/裁剪零改动; 与主管线的RecognizeWorker互不影响。
    人工确认会被覆盖(入口有确认弹窗, 与批量重新识别同语义)。
    """
    progress = Signal(int, int, str)      # done, total, 当前文件名
    finished_group = Signal(dict)         # {ok, changed, species|error}

    MAX_FRAMES = 8      # 识别预算: 最多8帧×(1检测+4取景分类)
    EARLY_CONF = 0.85   # 达到即收(再高接近模型上限, 省时间)

    def __init__(self, lib: Library, assets_dir: Path, photo_ids: list[int],
                 parent=None):
        super().__init__(parent)
        self.lib = lib
        self.assets = Path(assets_dir)
        self.photo_ids = list(photo_ids)
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        import json as _json
        import subprocess
        from ..ai.recognize_sub import build_worker_cmd
        from ..ai.engine import engine_setting
        from .burst import parse_ts

        # 帧序=美学分降序(封面优先, 构图好的帧常先救回), 预算截断
        def _aes(pid):
            r = self.lib.conn.execute(
                "SELECT aesthetic FROM photos WHERE id=?", (pid,)).fetchone()
            return -(r["aesthetic"] or 0) if r else 0

        frames = sorted(self.photo_ids, key=_aes)[:self.MAX_FRAMES]
        total = len(frames)
        meta = {}
        for pid in self.photo_ids:
            photo, _recs = self.lib.photo_detail(pid)
            ex = self.lib.conn.execute(
                "SELECT dt_original FROM exif WHERE photo_id=?",
                (pid,)).fetchone()
            from ..exif import month_of
            meta[pid] = (photo["path"], self.lib.region_for_photo(pid) or "",
                         str(month_of(ex["dt_original"] if ex else None) or ""))
        cmd, cwd = build_worker_cmd(
            str(self.assets), self.lib.get_setting("detect_conf", "0.25"),
            engine=engine_setting(self.lib.get_setting))
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8")

        def ask(pid: int, box: str = "") -> list | None:
            """问一帧; 返回records列表(None=进程死)。"""
            path, region, month = meta[pid]
            proc.stdin.write(f"{pid}\t{path}\t{region}\t{month}\t{box}\n")
            proc.stdin.flush()
            while True:
                line = proc.stdout.readline()
                if not line:
                    return None
                line = line.strip()
                if line.startswith("{"):        # 只认JSON行(EP告警混入stdout)
                    try:
                        r = _json.loads(line)
                        return r.get("records") if r.get("ok") else None
                    except ValueError:
                        continue

        best, best_conf, err = None, -1.0, ""
        try:
            for i, pid in enumerate(frames):
                if self._stop:
                    break
                self.progress.emit(i, total, Path(meta[pid][0]).name)
                recs = ask(pid)                     # ①标准: 拿主框+基线
                box = ""
                if recs and recs[0].get("box"):
                    b = recs[0]["box"]
                    box = ",".join(f"{float(v):.1f}" for v in b)
                recs2 = ask(pid, box) if box else None   # ②带框=多取景最佳
                for cand in (recs2, recs):
                    if cand and cand[0].get("confidence", 0) > best_conf:
                        best, best_conf = cand[0], cand[0]["confidence"]
                if best_conf >= self.EARLY_CONF:
                    break
        finally:
            try:
                proc.stdin.close()
                proc.kill()
            except OSError:
                pass
        if self._stop:
            self.finished_group.emit({"ok": False, "changed": 0,
                                      "error": "cancelled"})
            return
        if best is None:
            # 各帧各种取景都没认出鸟: 与批量重识别同语义(确认过覆盖)
            # 清空归未识别, 不留旧错误记录冒充结果
            self.lib.reset_recognition(self.photo_ids)
            self.finished_group.emit({"ok": False, "changed": 0,
                                      "error": "no-bird"})
            return
        # 应用到整组: 同一结果写全组(同鸟假设); source必须detect——
        # 子进程带框结果带source=rebox会误触"人工痕迹"保护
        rec = {"species_code": best["species_code"],
               "confidence": best.get("confidence", 0),
               "source": "detect", "box": best.get("box"),
               "top5": best.get("top5") or []}
        self.lib.reset_recognition(self.photo_ids)
        for pid in self.photo_ids:
            self.lib.add_records(pid, [rec])
        self.progress.emit(total, total, "")
        self.finished_group.emit({"ok": True, "changed": len(self.photo_ids),
                                  "species": rec["species_code"],
                                  "confidence": rec["confidence"]})
