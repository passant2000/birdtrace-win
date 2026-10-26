# -*- coding: utf-8 -*-
"""图鉴详情库解析 (assets/data/details_v2.btd + details_index_v2.bin)。

格式 (大端, 已逆向验证):
  index  BTRIDX02: [8B magic][u32 ver][u32 count][u32 dateLen][date][u64 btd总长]
                   + count × { [u32 nameLen][学名][u64 offset][u32 length][32B sha256] }
  btd    BTRDET02: 30B头(magic+u32 ver+u32 count+u32 dateLen+date)
                   记录 = { [u32 nameLen][学名] + 内容item×14 + [u32 0 终止] }
                   item = { [u32 len][UTF-8] }
  内容item (中英成对): 0/1概述 2/3识别要点 4/5分布区系 6/7栖息地海拔
                       8/9行为生态 10/11食性 12/13每窝卵数
  index 与 catalog_v2.bin 同为分类学顺序且逐行对齐; 这里按学名建字典直接定位。
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from ..paths import assets_dir

FIELD_NAMES = ["summary", "id_points", "range", "habitat",
               "behavior", "diet", "clutch"]


class BirdDex:
    def __init__(self, data_dir: Path | None = None):
        data_dir = Path(data_dir) if data_dir else assets_dir() / "data"
        self.btd_path = data_dir / "details_v2.btd"
        self.index_path = data_dir / "details_index_v2.bin"
        self._by_sci: dict[str, tuple[int, int, bytes]] = {}
        self._fh = None
        self._load_index()

    def _load_index(self):
        raw = self.index_path.read_bytes()
        if raw[:8] != b"BTRIDX02":
            raise ValueError("bad magic in details index")
        ver, count, date_len = struct.unpack_from(">III", raw, 8)
        off = 20 + date_len
        _btd_len, = struct.unpack_from(">Q", raw, off)
        off += 8
        _flags, self._record_base = struct.unpack_from(">II", raw, off)  # 0, 30
        off += 8
        entries = []
        for _ in range(count):
            nl, = struct.unpack_from(">I", raw, off)
            off += 4
            sci = raw[off:off + nl].decode("utf-8")
            off += nl
            offset, length = struct.unpack_from(">QI", raw, off)
            off += 12
            sha = raw[off:off + 32]
            off += 32
            entries.append((sci, offset, length, sha))
        if off != len(raw):
            raise ValueError(f"index trailing bytes: {off}/{len(raw)}")
        self.count = count
        self._by_sci = {sci.lower(): (offset, length, sha)
                        for sci, offset, length, sha in entries}

    # ---------- 记录读取 ----------
    def _read_record(self, offset: int, length: int, sha: bytes | None = None,
                     verify: bool = False) -> tuple[str, list[str]]:
        if self._fh is None:
            self._fh = open(self.btd_path, "rb")
        self._fh.seek(offset)
        raw = self._fh.read(length)
        if verify and sha and hashlib.sha256(raw).digest() != sha:
            raise ValueError("record sha256 mismatch")
        nl, = struct.unpack_from(">I", raw, 0)
        sci = raw[4:4 + nl].decode("utf-8")
        pos = 4 + nl
        items: list[str] = []
        # 固定15字段(14内容+1终止), 内容字段可合法为空(len=0), 必须消费到记录末尾
        while pos + 4 <= len(raw):
            ln, = struct.unpack_from(">I", raw, pos)
            pos += 4
            items.append(raw[pos:pos + ln].decode("utf-8"))
            pos += ln
        return sci, items

    def detail(self, sci: str, verify: bool = False) -> dict | None:
        """学名 → 中文图鉴详情; 无条目返回 None。"""
        entry = self._by_sci.get((sci or "").lower())
        if entry is None:
            return None
        offset, length, sha = entry
        _sci, items = self._read_record(offset, length, sha, verify)
        if len(items) < 14:
            return None
        out = {}
        for i, name in enumerate(FIELD_NAMES):
            zh, en = items[i * 2], items[i * 2 + 1]
            out[name] = {"zh": zh, "en": en}
        return out

    def has(self, sci: str) -> bool:
        return (sci or "").lower() in self._by_sci

    def close(self):
        if self._fh:
            self._fh.close()
            self._fh = None


_dex: BirdDex | None = None


def get_dex() -> BirdDex:
    global _dex
    if _dex is None:
        _dex = BirdDex()
    return _dex
