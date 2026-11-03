# -*- coding: utf-8 -*-
"""iOS分类模型DML适配: Reshape allowzero置0(与tools/dml_fix_model.py同法)。

用法: .venv/Scripts/python.exe tools/fix_ios_classifier.py
输入: data/model_experiments/BirdClassifier_iOS.onnx (作者发的iOS导出原样拷贝)
输出: 同路径覆盖(已手术版, DML可加载)
"""
from pathlib import Path

import onnx

P = Path(__file__).resolve().parent.parent / "data" / "model_experiments" / "BirdClassifier_iOS.onnx"
m = onnx.load(str(P))
n = 0
for node in m.graph.node:
    if node.op_type == "Reshape":
        for attr in node.attribute:
            if attr.name == "allowzero" and attr.i == 1:
                attr.i = 0
                n += 1
onnx.checker.check_model(m, full_check=False)
onnx.save(m, str(P))
print(f"allowzero置0: {n}处, 已保存 {P}")
