# -*- coding: utf-8 -*-
"""双语静态检查: 扫描源码里 t()/sname() 之外的裸中文字符串。

比 verify_i18n.py(运行时界面扫描)更早抓漏——不启动界面、逐文件AST检查。
规则:
· 字符串(f-string含)含中文且不在 t()/sname() 调用内 → 报告
· docstring/注释(注释本就不进AST)豁免
· 合法的数据中文字符串: 行尾加 `# i18n:ok` 标记豁免(自文档化,
  例如 db.py 的目名比对值、IUCN_CN 中文表、RARITY 键——它们是
  喂给 t() 的中文半边或库内数据的比对码)

用法: .venv/Scripts/python.exe tools/check_i18n_static.py
退出码: 0=干净, 1=有未豁免的裸中文
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
CJK = re.compile(r"[\u4e00-\u9fff]")
ALLOWED_CALLERS = {"t", "sname"}
MARKER = "# i18n:ok"
# 整文件豁免(有意保持中文的模块):
#  gpu_probe: 隐藏诊断工具, 报告刻意中文; theme.py: QSS样式串内注释
SKIP_FILES = {"app/ai/gpu_probe.py", "app/theme/theme.py"}


def docstring_ids(tree: ast.AST) -> set[int]:
    ids = set()

    def mark_body(body):
        if body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            ids.add(id(body[0].value))

    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            mark_body(node.body)
    return ids


def scan_file(path: Path) -> list[tuple[int, str]]:
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [(e.lineno or 0, f"<语法错误> {e.msg}")]

    docs = docstring_ids(tree)
    # 双语元组规则: 常量的直接父节点是Tuple且兄弟里存在纯英文串常量
    # (即 ("中文","English") 对, 显示期t(*pair)解包) → 豁免
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node

    def in_bilingual_tuple(node: ast.Constant) -> bool:
        par = parents.get(id(node))
        if not isinstance(par, (ast.Tuple, ast.List)):
            return False
        has_en = any(
            isinstance(el, ast.Constant) and isinstance(el.value, str)
            and el.value and not CJK.search(el.value)
            and re.search(r"[A-Za-z]", el.value)
            for el in par.elts)
        return has_en

    hits: list[tuple[int, str]] = []

    class V(ast.NodeVisitor):
        def __init__(self):
            self.depth = 0   # >0 = 在t()/sname()实参子树内

        def visit_Call(self, node: ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in ALLOWED_CALLERS:
                self.depth += 1
                self.generic_visit(node)
                self.depth -= 1
            else:
                self.generic_visit(node)

        def _const(self, node: ast.Constant):
            if self.depth > 0 or id(node) in docs or in_bilingual_tuple(node):
                return
            v = node.value
            if isinstance(v, str) and CJK.search(v):
                line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                if MARKER in line:
                    return
                hits.append((node.lineno, v.strip()[:40]))

        def visit_Constant(self, node: ast.Constant):
            self._const(node)

        def visit_JoinedStr(self, node: ast.JoinedStr):
            if self.depth == 0:
                for part in node.values:
                    if isinstance(part, ast.Constant):
                        self._const(part)
            self.generic_visit(node)

    V().visit(tree)
    return hits


def main() -> int:
    bad = 0
    for path in sorted((PROJ / "app").rglob("*.py")):
        rel = path.relative_to(PROJ).as_posix()
        if "__pycache__" in path.parts or rel in SKIP_FILES:
            continue
        for lineno, text in scan_file(path):
            print(f"{path.relative_to(PROJ).as_posix()}:{lineno}: 裸中文«{text}»  "
                  f"(入 t()/sname() 或行尾加 {MARKER})")
            bad += 1
    print("I18N_STATIC", "CLEAN" if bad == 0 else f"{bad} 处待处理")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
