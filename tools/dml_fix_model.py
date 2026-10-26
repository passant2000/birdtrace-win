# -*- coding: utf-8 -*-
"""DML兼容性模型手术v2: 分阶段验证, 原权不动, 只改等价表达。

阶段独立产出, 各自测DML, 起作用的最小改动才保留:
  A) 只处理 Reshape allowzero=1 -> 0 (shape无0维, 语义完全等价)
  B) A + CastLike -> Cast (目标类型用shape inference从第二输入取)

用法:
  .venv/Scripts/python.exe tools/dml_fix_model.py A|B
  .venv/Scripts/python.exe tools/dml_fix_model.py eq   # 等价性验证(见verify)
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
SRC = PROJ / "assets" / "models" / "BirdTraceRecognitionModel.onnx"
OUT_DIR = PROJ / "data" / "model_experiments"


def do_allowzero(m):
    import onnx
    n = 0
    for node in m.graph.node:
        if node.op_type != "Reshape":
            continue
        for a in node.attribute:
            if a.name == "allowzero" and a.i != 0:
                a.i = 0
                n += 1
    return n


def do_castlike(m):
    """CastLike(x, like) -> Cast(x, to=like的类型)。
    类型不瞎猜: 先shape inference, 从value_info查第二输入的真实类型。"""
    import onnx
    from onnx import helper, TensorProto
    m2 = onnx.shape_inference.infer_shapes(m)
    types = {}          # value名 -> dtype枚举
    for vi in list(m2.graph.value_info) + list(m2.graph.input) + \
            list(m2.graph.output):
        t = vi.type.tensor_type
        if t.elem_type:
            types[vi.name] = t.elem_type
    producers = {o: node for node in m.graph.node for o in node.output}
    n = 0
    new_nodes = []
    for node in m.graph.node:
        if node.op_type != "CastLike":
            new_nodes.append(node)
            continue
        like_name = node.input[1] if len(node.input) > 1 else None
        to = types.get(like_name)
        if to is None:
            # 兜底: 第二输入的生产者是Shape/常量int64的常见情形
            src = producers.get(like_name)
            if src is not None and src.op_type in ("Shape",):
                to = TensorProto.INT64
        if to is None:
            raise RuntimeError(
                f"无法推断CastLike目标类型: {node.name} (like={like_name})——放弃B方案")
        new_nodes.append(helper.make_node(
            "Cast", inputs=[node.input[0]], outputs=node.output,
            name=node.name or None, to=to))
        n += 1
    del m.graph.node[:]
    m.graph.node.extend(new_nodes)
    return n


def main() -> int:
    import onnx
    stage = sys.argv[1] if len(sys.argv) > 1 else "A"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    m = onnx.load(str(SRC))
    if stage == "A":
        n = do_allowzero(m)
        dst = OUT_DIR / "BirdTraceRecognitionModel_fixA.onnx"
    elif stage == "B":
        n = do_allowzero(m)
        n2 = do_castlike(m)
        dst = OUT_DIR / "BirdTraceRecognitionModel_fixB.onnx"
        n = f"{n} allowzero + {n2} CastLike"
    else:
        print("用法: dml_fix_model.py A|B")
        return 2
    onnx.checker.check_model(m, full_check=False)
    onnx.save(m, str(dst))
    print(f"[{stage}] 改动: {n}")
    print("输出:", dst, f"({dst.stat().st_size // 1048576}MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
