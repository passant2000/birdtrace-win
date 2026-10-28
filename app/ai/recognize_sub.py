# -*- coding: utf-8 -*-
"""识别worker: stdin 逐行接收任务, stdout 逐行回 JSON 结果。

协议: stdin行 = photo_id \\t path \\t region \\t month
      stdout行 = {"ok": true, "pid": N, "records": [...]}
               | {"ok": false, "pid": N, "error": "..."}

独立进程 = 与UI线程GIL完全隔离, 识别再重界面也不卡。
入口: 源码态 `python -m app.ai.recognize_sub --assets ...`;
      冻结态 复用主exe `--recognize-worker`(app/main.py分发到run_worker)。

⚠️ stdio编码: 源码态worker.py带-X utf8启动, 但冻结exe无法传该参数——
默认stdin/stdout=cp936, 中文路径照片会解码成乱码路径("No such file",
症状与换电脑文件丢失一模一样)。故run_worker入口强制重绑UTF-8,
不依赖启动参数与环境变量。
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path


def _force_utf8_stdio():
    """把stdin/stdout重绑为UTF-8(已是UTF-8时无副作用)。"""
    for name in ("stdin", "stdout"):
        stream = getattr(sys, name, None)
        buf = getattr(stream, "buffer", None)
        if buf is None:
            continue
        try:
            setattr(sys, name, io.TextIOWrapper(
                buf, encoding="utf-8", errors="surrogateescape",
                line_buffering=True))
        except Exception:
            pass


def build_worker_cmd(assets: str, conf: str,
                     use_gpu: bool = True) -> tuple[list[str], str | None]:
    """构造识别worker子进程命令(源码态python -m / 冻结态exe自我复用)。

    ⚠️冻结态绝不能用-m: sys.executable是exe, 会把主程序再开一遍
    (用户撞过的"无限开窗死循环")。返回(cmd, cwd)。
    use_gpu=False: 查看器单张重识别用CPU(够快, 且避免与批量识别的
    GPU子进程同机并存时个别环境DML初始化不稳)。
    """
    import sys
    tail = ["--conf", conf] + ([] if use_gpu else ["--cpu"])
    if getattr(sys, "frozen", False):
        return [sys.executable, "--recognize-worker",
                "--assets", assets] + tail, None
    return [sys.executable, "-u", "-X", "utf8", "-m",
            "app.ai.recognize_sub", "--assets", assets] + tail, \
        str(_proj_root())


def _proj_root():
    from pathlib import Path
    return Path(__file__).resolve().parent.parent.parent


def run_worker(assets, conf: str = "0.25", use_gpu: bool = True):
    """识别worker主循环(main.py --recognize-worker 与 -m 入口共用)。

    顺序一问一答(经验证稳定; 曾试过reader线程+解码线程池的流水线并行,
    个别环境下子进程在import管线时死锁, 已回退——批量提速靠GPU推理本身)。
    """
    _force_utf8_stdio()
    pipe = None

    def out(obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            parts = line.split("\t")
            pid = int(parts[0])
            month = int(parts[3]) if parts[3] else None
            # 可选第5列: 指定/重画的检测框"x1,y1,x2,y2"(查看器重画识别用)
            box = None
            if len(parts) >= 5 and parts[4]:
                box = [float(v) for v in parts[4].split(",")]
                if len(box) != 4:
                    box = None
            path = parts[1]
            region = parts[2]
        except (ValueError, TypeError, IndexError):
            out({"ok": False, "pid": -1, "error": f"bad line: {line[:40]}"})
            continue
        try:
            if pipe is None:
                from app.ai.pipeline import RecognitionPipeline
                pipe = RecognitionPipeline(
                    detector_path=str(Path(assets) / "models" / "BirdTraceBirdDetector_FP32.onnx"),
                    classifier_path=str(Path(assets) / "models" / "BirdTraceRecognitionModel.onnx"),
                    labels_path=str(Path(assets) / "data" / "labels.json"),
                    geo_prior_path=str(Path(assets) / "data" / "geo_prior.sqlite"),
                    use_gpu=use_gpu,
                    conf_thr=float(conf),
                )
            from app.ai.pipeline import load_rgb
            img = load_rgb(path)
            if box is not None:
                rec = pipe.recognize_box(img, box, region or None, month, topk=5)
                out({"ok": True, "pid": pid, "records": [rec] if rec else []})
            else:
                records = pipe.recognize(img, region or None, month, topk=5)
                out({"ok": True, "pid": pid, "records": records})
        except Exception as e:
            out({"ok": False, "pid": pid, "error": str(e)[:200]})


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", required=True)
    ap.add_argument("--conf", default="0.25")
    ap.add_argument("--cpu", action="store_true", help="CPU推理(单张重识别)")  # i18n:ok
    args, _ = ap.parse_known_args()
    run_worker(args.assets, args.conf, use_gpu=not args.cpu)


if __name__ == "__main__":
    main()
