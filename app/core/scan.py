# -*- coding: utf-8 -*-
"""常用目录增量扫描(1.0冲刺⑯, 简化版"文件夹监控"): 手动触发, 分层
识别(路径→大小→mtime→必要时SHA-256), 复用 file_hash 免重复哈希。

四情形矩阵(六专题专题3, 全部只出候选清单绝不自动写库/移动/删除):
· new     = 路径不在库 → 算hash: hash已存在=疑似移动/改名(relink候选);
            hash全新=新文件(导入候选, 走既有importer)
· changed = 路径在库但size/mtime变了 → 重算hash: 不同=内容变化候选
            (提示不覆盖); 相同=仅元数据变化(忽略, 不误判新照片)
· gone    = 不在本模块职责内(由 file_status 的 missing/离线机制管;
            扫描根不可访问时不误标missing)
· moved   = new里hash命中库内missing照片 → relink候选(复用现有relink)
误报护栏: 盘符变化按路径比对待新(产生relink候选正是预期); 根不可
访问/枚举出错→整个根跳过并记error, 绝不据此判missing。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def scan_roots_get(lib) -> list[str]:
    try:
        obj = json.loads(lib.get_setting("scan_roots", "[]") or "[]")
        return [str(s) for s in obj if isinstance(s, str)] \
            if isinstance(obj, list) else []
    except ValueError:
        return []


def scan_roots_set(lib, roots: list[str]):
    lib.set_setting("scan_roots", json.dumps(list(roots), ensure_ascii=False))


def scan_increment(lib, root: str | Path) -> dict:
    """扫描一个目录 → 候选清单(不写库)。分层判定省SHA-256:
    同路径+同size+同mtime=跳过(连hash都不算)。"""
    rootp = Path(root)
    res = {"root": str(rootp), "ok": False, "error": "",
           "new": [], "moved": [], "changed": [], "meta_only": 0,
           "unchanged": 0, "skipped_hash": 0}
    if not rootp.is_dir():
        res["error"] = "目录不存在"
        return res
    from ..exif import SUPPORTED_EXTS
    # 库内现状: path→(id,size,mtime) 与 hash→[ids](含missing)
    by_path = {}
    by_hash: dict[str, list] = {}
    for r in lib.conn.execute(
            "SELECT id, path, size, mtime, file_hash, missing FROM photos"):
        by_path[os.path.normcase(os.path.normpath(
            os.path.abspath(r["path"])))] = r
        by_hash.setdefault(r["file_hash"], []).append(r)
    try:
        it = list(rootp.rglob("*"))
    except OSError as e:
        res["error"] = f"枚举失败: {e}"
        return res
    res["ok"] = True
    for f in it:
        if not f.is_file() or f.suffix.lower() not in SUPPORTED_EXTS:
            continue
        key = os.path.normcase(os.path.normpath(os.path.abspath(str(f))))
        try:
            st = f.stat()
        except OSError:
            res["error"] = res["error"] or "部分文件不可读(已跳过)"
            continue
        r = by_path.get(key)
        if r is None:
            # new: 算hash定性质(移动改名 vs 全新)
            h = _content_hash(f)
            res["skipped_hash"] += 0
            mates = by_hash.get(h) or []
            gone_mates = [m for m in mates if m["missing"]]
            entry = {"path": str(f), "size": st.st_size,
                     "mtime": st.st_mtime, "hash": h}
            if gone_mates:
                entry["relink_photo_ids"] = [m["id"] for m in gone_mates]
                res["moved"].append(entry)
            elif mates:
                entry["dup_of_ids"] = [m["id"] for m in mates]
                res["moved"].append(entry)   # 同hash副本=路径变化语义
            else:
                res["new"].append(entry)
        else:
            same_meta = (r["size"] == st.st_size and
                         abs((r["mtime"] or 0) - st.st_mtime) < 1.0)
            if same_meta:
                res["unchanged"] += 1
                continue
            h = _content_hash(f)
            if h == r["file_hash"]:
                res["meta_only"] += 1   # 仅元数据变化: 不误判新照片
            else:
                res["changed"].append({"path": str(f), "size": st.st_size,
                                       "mtime": st.st_mtime, "hash": h,
                                       "photo_id": r["id"]})
    return res


def _content_hash(p: Path) -> str:
    """与库内 file_hash 同源(media.file_hash), 命中判定才可能成立。"""
    from ..media import file_hash
    return file_hash(p)
