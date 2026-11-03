# -*- coding: utf-8 -*-
"""迁徙服务: 接作者迁徙服务器(eBird Status & Trends 2023 按周数据)。

与安卓同源同逻辑——安卓就是客户端按需从作者服务器现拉, Win版做同样的
瘦客户端, 数据不进发布包、不发生再分发。链路(全部无鉴权):
    latest.json -> catalog.json(2980物种, 每条带 sqlite/manifest 的
    key+SHA256+字节数) -> species/<code>/surface_tiles.sqlite + manifest.json

缓存布局: <库>/migration/catalog.json(目录) + <code>.sqlite / <code>.manifest.json
(物种包)。SHA256 与 catalog 条目不符则删掉重下(release 更新自动跟进)。

数据格式(BTRR payload, 整体xz压缩):
    头16B('BTRR' + <HHHH: ver,weeks,rows,cols> + 8B保留)
    + weeks×16B 每周参数(含季节量化参数, 本端不用——u8相对强度足够画热力)
    + weeks×rows×cols u8 强度, 周主序。
tile_coverage 给每tile经纬度边界(跨日界线tile拆两段coverage_part);
cell经纬度 = 在tile边界内线性插值(数据是Equal Earth瓦片, 世界级视图下
线性近似足够; 只画任一周强度>0的活跃cell)。
"""
from __future__ import annotations

import hashlib
import json
import lzma
import sqlite3
import struct
import urllib.request
from pathlib import Path

BASE_URL = "https://migration.birdtrace.org/"
LATEST_KEY = "migration/status-2023/latest.json"

CHUNK = 256 * 1024


class MigrationError(Exception):
    """reason: offline / http / sha / not_in_catalog / corrupt / bad_manifest"""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fetch(url: str, timeout: float, progress=None, phase: str = "",
           cancel=None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "BirdTrace-Win"})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except Exception as e:  # URLError/timeout/...
        raise MigrationError("http", f"{url}: {e}") from e
    with resp:
        total = int(resp.headers.get("Content-Length") or 0)
        chunks = []
        cur = 0
        while True:
            if cancel is not None and cancel():
                raise MigrationError("cancelled")
            b = resp.read(CHUNK)
            if not b:
                break
            chunks.append(b)
            cur += len(b)
            if progress is not None:
                progress(phase, cur, total)
    return b"".join(chunks)


class MigrationClient:
    """目录与物种包的拉取/缓存。base_url 可注入(验证用本地HTTP服务器)。"""

    def __init__(self, lib_root: Path, base_url: str = BASE_URL,
                 timeout: float = 30.0):
        self.dir = Path(lib_root) / "migration"
        self.base_url = base_url
        self.timeout = timeout

    # ---- 目录 ----
    def catalog(self, progress=None, cancel=None) -> dict:
        """latest.json → catalog.json, 校验SHA256后缓存; 断网回退缓存目录。"""
        cache = self.dir / "catalog.json"
        try:
            latest = json.loads(_fetch(
                self.base_url + LATEST_KEY, self.timeout, progress,
                "catalog", cancel))
            raw = _fetch(self.base_url + latest["catalogKey"], self.timeout,
                         progress, "catalog", cancel)
            if latest.get("catalogSHA256") and sha256_hex(raw) != latest["catalogSHA256"]:
                raise MigrationError("sha", "catalog")
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".part")
            tmp.write_bytes(raw)
            tmp.replace(cache)
            return json.loads(raw)
        except MigrationError as e:
            if e.reason == "sha":
                raise
            # 断网/超时: 有缓存就用缓存(可能是旧release, 物种包SHA会兜底校验)
            if cache.exists():
                try:
                    return json.loads(cache.read_text(encoding="utf-8"))
                except Exception:
                    pass
            raise MigrationError("offline", str(e)) from e

    def entry(self, code: str, catalog: dict | None = None) -> dict | None:
        cat = catalog or self.catalog()
        for sp in cat.get("species", []):
            if sp.get("speciesCode") == code:
                return sp
        return None

    # ---- 物种包 ----
    def ensure_species(self, code: str, progress=None, cancel=None,
                       catalog: dict | None = None) -> dict:
        """确保 <库>/migration/<code>.sqlite + .manifest.json 存在且SHA256匹配。

        返回 {"sqlite": Path, "manifest": Path, "from_cache": bool}。
        progress(phase, cur, total), phase ∈ catalog/sqlite/manifest。
        """
        ent = self.entry(code, catalog)
        if ent is None:
            raise MigrationError("not_in_catalog", code)
        self.dir.mkdir(parents=True, exist_ok=True)
        out = {"from_cache": True}
        for kind in ("sqlite", "manifest"):
            suffix = ".sqlite" if kind == "sqlite" else ".manifest.json"
            path = self.dir / f"{code}{suffix}"
            want = ent.get(f"{kind}SHA256")
            if path.exists() and want:
                if sha256_hex(path.read_bytes()) == want:
                    out[kind] = path
                    continue
            raw = _fetch(self.base_url + ent[f"{kind}Key"], self.timeout,
                         progress, kind, cancel)
            if want and sha256_hex(raw) != want:
                raise MigrationError("sha", f"{code} {kind}")
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_bytes(raw)
            tmp.replace(path)
            out[kind] = path
            out["from_cache"] = False
        if "sqlite" not in out or "manifest" not in out:
            raise MigrationError("corrupt", code)
        return out

    def fetch_species(self, code: str, progress=None, cancel=None) -> dict:
        """目录(带缓存回退) + 物种包, 一次到位。"""
        cat = self.catalog(progress, cancel)
        return self.ensure_species(code, progress, cancel, cat)


# ---- 解码 ----

LOD_ORDER = ("world", "continental", "regional", "local")


def lod_for_zoom(zoom: float) -> str:
    """MapLibre缩放→LOD档位(安卓按viewport选tile的同思路; 阈值经验值)。"""
    if zoom < 2.6:
        return "world"
    if zoom < 4.2:
        return "continental"
    if zoom < 5.8:
        return "regional"
    return "local"


def _norm_bbox(west: float, south: float, east: float,
               north: float) -> list[tuple[float, float, float, float]]:
    """视口经度wrap到[-180,180], 跨日界线拆两段 → [(w,s,e,n)]。"""
    def wrap(l):
        return (l + 180.0) % 360.0 - 180.0

    w2, e2 = wrap(west), wrap(east)
    if w2 <= e2:
        return [(w2, south, e2, north)]
    return [(w2, south, 180.0, north), (-180.0, south, e2, north)]


def decode_view(sqlite_path: Path, lod: str = "world",
                bbox: tuple[float, float, float, float] | None = None) -> dict:
    """任意LOD(可按视口bbox过滤)解码 → {"weeks", "cells", "values"}。

    结构与decode_world同构(每cell几何+52周u8值), 但cells是[lod, ty, tx,
    lon0,lat0,lon1,lat1]前带tile键(供增量替换时比较)。bbox=(w,s,e,n)为
    视口(unwrapped经度), None=全部; 已解压tile用active_week_mask跳过
    全零行(安卓同款SQL思路)。放大后的LOD数据本就在同一包内, 无额外下载。
    """
    try:
        con = sqlite3.connect(f"file:{Path(sqlite_path).as_posix()}?mode=ro",
                              uri=True)
        con.execute("SELECT 1")
    except sqlite3.Error:
        con = sqlite3.connect(str(sqlite_path))
    try:
        boxes = _norm_bbox(*bbox) if bbox else None
        cov: dict[tuple[int, int], list[tuple]] = {}
        q = ("SELECT c.tile_y,c.tile_x,c.coverage_part,c.min_longitude,"
             "c.max_longitude,c.min_latitude,c.max_latitude "
             "FROM tile_coverage c JOIN surface_tile s ON s.lod=c.lod "
             "AND s.tile_y=c.tile_y AND s.tile_x=c.tile_x "
             "WHERE c.lod=? AND s.active_week_mask!=0")
        args: list = [lod]
        if boxes:
            ors = []
            for b in boxes:
                ors.append("(c.min_longitude<=? AND c.max_longitude>=?"
                           " AND c.min_latitude<=? AND c.max_latitude>=?)")
                args += [b[2], b[0], b[3], b[1]]
            q += " AND (" + " OR ".join(ors) + ")"
        q += " ORDER BY c.tile_y,c.tile_x,c.coverage_part LIMIT 8192"
        for ty, tx, part, mnlon, mxlon, mnlat, mxlat in con.execute(q, args):
            cov.setdefault((ty, tx), []).append((mnlon, mxlon, mnlat, mxlat))
        cells: list[list] = []
        cols_per_week: list[bytes] = []
        weeks_total = None
        for (ty, tx), parts in sorted(cov.items()):
            row = con.execute(
                "SELECT payload FROM surface_tile WHERE lod=? AND tile_y=? "
                "AND tile_x=?", (lod, ty, tx)).fetchone()
            if row is None:
                continue
            raw = lzma.decompress(row[0])
            magic, ver, weeks, rows, cols = struct.unpack("<4sHHHH", raw[:12])
            if magic != b"BTRS" or ver != 2:
                raise MigrationError("corrupt", f"bad header {magic!r} ver={ver}")
            base = 16 + weeks * 16  # 跳过每周16B参数
            need = base + weeks * rows * cols
            if len(raw) < need:
                raise MigrationError("corrupt", "truncated payload")
            weeks_total = weeks
            # coverage_part只是区间在±180处的裁切记录: 真实经度区间=
            # [首段.min, 末段.max], 末段max<首段min时+360展开(跨日界线)。
            lo = parts[0][0]
            top = parts[0][3]
            bot = parts[0][2]
            hi = parts[-1][1]
            if hi < lo:
                hi += 360.0
            vals = raw[base:need]
            dlon = (hi - lo) / cols
            dlat = (top - bot) / rows
            cellmax = [0] * (rows * cols)
            for w in range(weeks):
                off = w * rows * cols
                for rc in range(rows * cols):
                    v = vals[off + rc]
                    if v > cellmax[rc]:
                        cellmax[rc] = v
            for rc, mx in enumerate(cellmax):
                if mx <= 0:
                    continue
                r, c = divmod(rc, cols)
                x0 = lo + c * dlon
                x1 = x0 + dlon
                y1 = top - r * dlat
                y0 = y1 - dlat
                idxs = []
                if x0 >= 180.0:  # 整格在展开经度≥180: 平移回西半球
                    idxs.append([x0 - 360.0, y0, x1 - 360.0, y1])
                elif x1 > 180.0:  # 跨日界线: 拆东西两半
                    idxs.append([x0, y0, 180.0, y1])
                    idxs.append([-180.0, y0, x1 - 360.0, y1])
                else:
                    idxs.append([x0, y0, x1, y1])
                for box in idxs:
                    if boxes and not any(
                            box[0] < b[2] and box[2] > b[0]
                            and box[1] < b[3] and box[3] > b[1]
                            for b in boxes):
                        continue
                    cells.append([lod, ty, tx] + box)
                    cols_per_week.append(bytes(
                        vals[w * rows * cols + rc] for w in range(weeks)))
        return {"weeks": weeks_total or 0,
                "cells": cells,
                "values": b"".join(cols_per_week)}
    finally:
        con.close()


def decode_world(sqlite_path: Path) -> dict:
    """world LOD全量解码(格式同decode_view, cells不含tile键前缀)。"""
    d = decode_view(sqlite_path, "world")
    return {"weeks": d["weeks"],
            "cells": [c[3:] for c in d["cells"]],
            "values": d["values"]}


def world_geojson(decoded: dict) -> dict:
    """解码结果 → MapLibre GeoJSON(每活跃cell一个Polygon, properties.w=52周值)。"""
    weeks = decoded["weeks"]
    values = decoded["values"]
    features = []
    for i, (x0, y0, x1, y1) in enumerate(decoded["cells"]):
        w = list(values[i * weeks:(i + 1) * weeks])
        if not any(w):
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[
                [x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]},
            "properties": {"i": i, "w": w},
        })
    return {"type": "FeatureCollection", "features": features}


def week_dates(manifest: dict) -> list[str]:
    """manifest.frames → 52周ISO日期(帧序即周序)。"""
    frames = manifest.get("frames") or []
    out = []
    for f in frames:
        d = f.get("date") or ""
        out.append(d)
    return out


def frame_phases(manifest: dict) -> list[str]:
    """manifest.frames → 每周物候季段(breeding/nonBreeding/
    preBreedingMigration/postBreedingMigration, 安卓Seasonal phase同源)。"""
    frames = manifest.get("frames") or []
    return [(f.get("phase") or "") for f in frames]


def week_counts(decoded: dict) -> list[int]:
    """52周各自的非零活跃cell数(供JS"本周该视野无数据"提示)。"""
    vals = decoded["values"]
    n = len(decoded["cells"])
    w_total = decoded["weeks"]
    return [sum(1 for i in range(n) if vals[i * w_total + w])
            for w in range(w_total)]
