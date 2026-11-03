# -*- coding: utf-8 -*-
"""GPU/DirectML 诊断探针: 多配置尝试创建会话并实测推理耗时。

背景: 中文Windows上onnxruntime-directml的DML初始化报错会被
utf-8解码bug吞掉真实原因(GBK错误串被当UTF-8解), 且make_session
静默回退CPU——设置页/日志里都看不到为什么。本探针:
  1) 记录环境(ORT版本/系统编码/显卡列表)
  2) 对检测器与分类器分别尝试: DML默认/指定device_id/关图优化/CPU基线
  3) 会话创建成功后立刻查get_providers()——创建成功≠DML真生效
  4) 随机张量实测3次推理耗时(GPU是否真在算, 一目了然)
  5) log_severity_level=0让ORT原生详细日志进结果文件(真实错误就在里面)
结果增量写入 exe旁 gpu_probe_result.txt (崩溃也不丢已完成部分)。

入口: 鸟迹BirdTrace.exe --gpu-probe  (或 python -m app.main --gpu-probe)
"""
from __future__ import annotations

import ctypes
import json
import platform
import subprocess
import time
from pathlib import Path

from ..paths import proj_root


def _gpu_names() -> list[str]:
    try:
        out = subprocess.run(
            ["wmic", "path", "win32_VideoController", "get", "name"],
            capture_output=True, timeout=15).stdout.decode("gbk", "replace")
        return [l.strip() for l in out.splitlines()
                if l.strip() and "Name" not in l]
    except Exception as e:
        return [f"<查询失败: {e}>"]


def _acp() -> int:
    try:
        return ctypes.windll.kernel32.GetACP()
    except Exception:
        return -1


def _dummy_feed(sess) -> dict:
    """按模型输入元数据构造随机张量(动态维取64/384)。"""
    import numpy as np
    feed = {}
    for inp in sess.get_inputs():
        dims = []
        for d in inp.shape:
            if isinstance(d, int) and d > 0:
                dims.append(d)
            else:                       # 动态维: 字符串/None/负数
                dims.append(384 if len(dims) >= 2 else 1)
        feed[inp.name] = np.random.rand(*dims).astype(np.float32)
    return feed


def _try_config(out, tag: str, model_path: Path, providers: list,
                so_kwargs: dict) -> str:
    """创建会话+实测推理, 结果写入out(已打开的文件)。返回ok/partial/fail。"""
    import onnxruntime as ort
    want_dml = any("DmlExecutionProvider" in p for p in providers
                   if isinstance(p, (str, tuple)))
    out.write(f"\n--- {tag} ---\n")
    out.write(f"providers请求: {providers}  opts: {so_kwargs}\n")
    so = ort.SessionOptions()
    so.log_severity_level = so_kwargs.get("log_severity", 3)
    if so_kwargs.get("opt") == "disable":
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    prov = providers
    if so_kwargs.get("device_id") is not None:
        # ORT要求 (provider名, 选项字典) 元组格式; 字典格式会被静默拒绝
        prov = [("DmlExecutionProvider", {"device_id": so_kwargs["device_id"]})
                if p == "DmlExecutionProvider" else p for p in providers]
    t0 = time.perf_counter()
    try:
        sess = ort.InferenceSession(str(model_path), providers=prov,
                                    sess_options=so)
    except Exception as e:
        out.write(f"创建失败({time.perf_counter()-t0:.1f}s): {type(e).__name__}: "
                  f"{str(e)[:300]}\n")
        out.flush()
        return "fail"
    dt_create = time.perf_counter() - t0
    actual = sess.get_providers()[0]
    out.write(f"创建成功 {dt_create:.1f}s, 实际生效provider: {actual}\n")
    if want_dml and actual != "DmlExecutionProvider":
        out.write("!! 请求了DML但实际在用CPU(内部静默回退)\n")
        out.flush()
        return "partial"
    try:
        feed = _dummy_feed(sess)
        names = [o.name for o in sess.get_outputs()]
        # 预热1次+实测3次
        sess.run(names, feed)
        times = []
        for _ in range(3):
            t1 = time.perf_counter()
            sess.run(names, feed)
            times.append((time.perf_counter() - t1) * 1000)
        out.write(f"推理耗时: {', '.join(f'{t:.0f}ms' for t in times)} "
                  f"(输入{ {k: list(v.shape) for k, v in feed.items()} })\n")
        out.flush()
        return "ok"
    except Exception as e:
        out.write(f"会话创建成功但推理失败: {type(e).__name__}: "
                  f"{str(e)[:300]}\n")
        out.flush()
        return "partial"
    finally:
        del sess


def run_probe(assets: Path) -> None:
    import onnxruntime as ort
    result = proj_root() / "gpu_probe_result.txt"
    # newline="\n": 不做CRLF翻译(翻译会让按行grep/比对工具失配)
    out = open(result, "w", encoding="utf-8", buffering=1,
               newline="\n")  # 行缓冲=增量落盘
    import sys
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = out        # Python层print(EP告警banner)进文件
    sys.stderr = out
    import os
    try:
        # ORT原生日志走系统fd不走sys.stderr——dup2把fd级输出也收进文件
        # (双击bat运行时无控制台, 不收就永远看不到真实错误)
        os.dup2(out.fileno(), 1)
        os.dup2(out.fileno(), 2)
    except OSError:
        pass  # 无控制台的windowed进程fd 1/2可能不存在
    try:
        out.write("鸟迹 GPU/DirectML 诊断\n")
        out.write(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        out.write(f"onnxruntime: {ort.__version__}\n")
        out.write(f"python: {platform.python_version()}  "
                  f"系统编码ACP: {_acp()} (936=GBK中文)\n")
        out.write(f"可用providers: {ort.get_available_providers()}\n")
        out.write(f"显卡: {json.dumps(_gpu_names(), ensure_ascii=False)}\n")
        out.write("=" * 50)

        from .detector import (DETECTOR_MODEL, DETECTOR_MODEL_CPU,
                               default_detector_model)
        det = assets / "models" / default_detector_model(True)
        det_nano = assets / "models" / DETECTOR_MODEL_CPU
        cls = assets / "models" / "BirdTraceRecognitionModel.onnx"
        if not cls.exists():
            out.write(f"\n!! 找不到模型: {cls}\n")
            return

        dml = ["DmlExecutionProvider", "CPUExecutionProvider"]
        cpu = ["CPUExecutionProvider"]
        summary = []
        for name, path in ((f"检测{det.name[:24]}(GPU默认)", det),
                           ("检测nano(CPU回退)", det_nano),
                           ("分类器214MB", cls)):
            out.write(f"\n\n========== 模型: {name} ==========")
            cfgs = [
                ("DML默认", dml, {}),
                ("DML默认+详细日志", dml, {"log_severity": 0}),
                ("DML+关图优化", dml, {"opt": "disable"}),
                ("DML device_id=0", dml, {"device_id": 0}),
                ("DML device_id=1", dml, {"device_id": 1}),
                ("DML device_id=2", dml, {"device_id": 2}),
                ("CPU基线", cpu, {}),
            ]
            for tag, prov, kw in cfgs:
                r = _try_config(out, f"{name}/{tag}", path, prov, kw)
                summary.append(f"{name}/{tag}: {r}")
        out.write("\n\n========== 汇总 ==========\n")
        out.write("\n".join(summary) + "\n")
        out.write("说明: ok=DML创建且推理成功; partial=请求DML但实际回退CPU"
                  "或推理失败; fail=创建失败。把本文件发回给开发者。\n")
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        out.close()
        print(f"GPU probe done -> {result}")
