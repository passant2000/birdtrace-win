# -*- coding: utf-8 -*-
"""连拍分组(0.8-③): 时间≤2s + 同鸟种 + 感知哈希相近 → 成组; 封面=组内美学最高。

规则(用户定): 连续按快门的一串同主体照片折成一张封面(角标 ×N), 展开看全组。
  · 链式比较: 候选帧与当前组**最后一帧**比 (Δt≤BURST_GAP_S, 同 rank=1 鸟种,
    dHash 汉距≤BURST_SAME_MAX); 长连拍逐帧漂移也能连成一组。
  · 没有拍摄时间/未识别的照片不参与; 任一帧没有哈希(缩略图都没有)时
    只按时间+鸟种(同鸟种2秒内几乎必是连拍, 不因缺哈希拆散)。
  · group_id = "g<组内最小photo_id>", 全量重算稳定; 单张不写(NULL)。
不改库结构, 只用 photos.group_id / photos.phash 两列。
"""
from __future__ import annotations

from typing import Callable, Iterable

from .phash import BURST_SAME_MAX, hamming

BURST_GAP_S = 2.0
# 分组规则版本: 规则/阈值变化时递增, 启动时版本不同→全量重算一次
BURST_VERSION = "2026-11-03a"


def parse_ts(s: str | None) -> float | None:
    """'YYYY-MM-DD HH:MM:SS' / 'YYYY:MM:DD HH:MM:SS' / ISO 'T' → 秒; 解析失败None。"""
    if not s or len(s) < 19:
        return None
    try:
        y, mo, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
        h, mi, se = int(s[11:13]), int(s[14:16]), int(s[17:19])
        import datetime as _dt
        return _dt.datetime(y, mo, d, h, mi, se).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def group_bursts(rows: Iterable[dict],
                 phash_of: Callable[[int], str | None],
                 gap_s: float = BURST_GAP_S,
                 same_max: int = BURST_SAME_MAX) -> dict[int, str]:
    """rows: {id, taken_at, code} (任意顺序) → {photo_id: group_id}, 仅含≥2张的组。

    先按鸟种分流、各自按时间链式成组——交错拍到的别的鸟种不会拆散连拍
    (两只鸟轮流拍/双机位同秒都有)。phash_of 懒调用: 只对时间过门的相邻帧比哈希。"""
    by_code: dict[str, list[tuple[float, int]]] = {}
    for r in rows:
        ts = parse_ts(r.get("taken_at"))
        if ts is None or not r.get("code"):
            continue
        by_code.setdefault(r["code"], []).append((ts, int(r["id"])))
    out: dict[int, str] = {}
    for code, items in by_code.items():
        items.sort()
        cur: list[int] = []
        cur_last_ts = None
        cur_last_hash: str | None = None
        cur_last_hash_done = False

        def flush():
            if len(cur) >= 2:
                gid = f"g{min(cur)}"
                for pid in cur:
                    out[pid] = gid

        for ts, pid in items:
            if cur and ts - cur_last_ts <= gap_s:
                if not cur_last_hash_done:
                    cur_last_hash = phash_of(cur[-1])
                    cur_last_hash_done = True
                h = phash_of(pid)
                d = hamming(cur_last_hash, h)
                if d is None or d <= same_max:
                    cur.append(pid)
                    cur_last_ts = ts
                    cur_last_hash, cur_last_hash_done = h, True
                    continue
            flush()
            cur = [pid]
            cur_last_ts = ts
            cur_last_hash, cur_last_hash_done = None, False
        flush()
    return out


def collapse_bursts(rows: list[dict], id_key: str = "id") -> list[dict]:
    """把同组照片折成封面一张(组内美学最高, 平手取最早), 保持原顺序位置
    (封面放在该组首次出现的位置)。封面行新增 group_n / group_ids(按时间升序)。
    行需含 group_id; aesthetic/taken_at 可缺。"""
    groups: dict[str, list[dict]] = {}
    for r in rows:
        gid = r.get("group_id")
        if gid:
            groups.setdefault(gid, []).append(r)
    out: list[dict] = []
    emitted: set[str] = set()
    for r in rows:
        gid = r.get("group_id")
        if not gid or len(groups.get(gid, ())) < 2:
            out.append(r)
            continue
        if gid in emitted:
            continue
        emitted.add(gid)
        members = groups[gid]
        cover = max(members, key=lambda m: (
            m.get("aesthetic") if m.get("aesthetic") is not None else -1.0,
            -(parse_ts(m.get("taken_at")) or 0.0)))
        c = dict(cover)
        c["group_n"] = len(members)
        c["group_ids"] = [m[id_key] for m in sorted(
            members, key=lambda m: (parse_ts(m.get("taken_at")) or 0.0, m[id_key]))]
        out.append(c)
    return out
