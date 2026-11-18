# -*- coding: utf-8 -*-
"""照片库: SQLite编目数据库 + DAO。

库位置默认在 文档/BirdTraceWin/, 内含 catalog.db 与 thumbnails/ 缓存。
设计原则: photos 表只引用文件路径, 绝不擅自移动/修改原文件——唯一
例外=用户显式授权的操作(导出向导"原地重命名"、选片"隔离区", 均
预览确认+同步更新库path+绝不覆盖同名)。

核心视图 v_records: 每条识别记录 + 生效鸟种(纠正优先) + 拍摄时间。
一照多鸟 = 多条记录; 同种多鸟在鸟种统计中按照片数去重。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .i18n import t
from .paths import assets_dir

ASSETS = assets_dir()

# 鸟种资产版本: species_catalog/overrides/labels/iucn 变更时递增,
# 启动时发现不一致就重刷 species 表(旧库也能吃到中文名等修正)。
SPECIES_DATA_VERSION = "2026-11-04a"

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS photos(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  path TEXT NOT NULL UNIQUE,
  file_hash TEXT NOT NULL,
  size INTEGER, mtime REAL,
  width INTEGER, height INTEGER,
  added_at TEXT DEFAULT (datetime('now','localtime')),
  batch_id INTEGER, rating INTEGER DEFAULT 0, rec_fail INTEGER DEFAULT 0,
  aesthetic REAL
);
CREATE INDEX IF NOT EXISTS idx_photos_hash ON photos(file_hash);
CREATE INDEX IF NOT EXISTS idx_photos_batch ON photos(batch_id);

CREATE TABLE IF NOT EXISTS exif(
  photo_id INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
  dt_original TEXT, make TEXT, model TEXT, lens TEXT,
  iso INTEGER, exposure TEXT, fnum REAL, focal_len REAL,
  gps_lat REAL, gps_lon REAL, orientation INTEGER, artist TEXT
);

CREATE TABLE IF NOT EXISTS species(
  code TEXT PRIMARY KEY, cn TEXT, en TEXT, sci TEXT,
  order_cn TEXT, family_cn TEXT, genus TEXT,
  iucn TEXT, in_classifier INTEGER DEFAULT 0,
  cn_pinyin TEXT, cn_initials TEXT
);
CREATE INDEX IF NOT EXISTS idx_species_pinyin ON species(cn_pinyin);
CREATE INDEX IF NOT EXISTS idx_species_initials ON species(cn_initials);

CREATE TABLE IF NOT EXISTS records(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
  species_code TEXT NOT NULL REFERENCES species(code),
  rank INTEGER, confidence REAL, source TEXT, box_json TEXT, top5_json TEXT,
  reviewed INTEGER DEFAULT 0, confirmed_code TEXT,
  eye_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_photo ON records(photo_id);
CREATE INDEX IF NOT EXISTS idx_records_species ON records(species_code);

CREATE TABLE IF NOT EXISTS batches(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mode TEXT, dest TEXT, region_id TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')), count INTEGER
);

CREATE TABLE IF NOT EXISTS spots(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  short_name TEXT DEFAULT '',
  lat REAL, lon REAL,
  note TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
"""

# v_records视图DDL单列: _migrate检测旧库视图缺列时DROP重建用
# (2026-11-05 test3反馈: 视图缺top5_json→查看器top5候选永远为空)
_V_RECORDS_DDL = """CREATE VIEW IF NOT EXISTS v_records AS
SELECT r.id AS record_id, r.photo_id, p.path,
       COALESCE(r.confirmed_code, r.species_code) AS eff_code,
       r.species_code, r.rank, r.confidence, r.source, r.reviewed,
       r.confirmed_code, r.box_json, r.top5_json, r.eye_json,
       COALESCE(e.dt_original, p.added_at) AS taken_at,
       substr(COALESCE(e.dt_original, p.added_at), 1, 7) AS ym,
       substr(COALESCE(e.dt_original, p.added_at), 1, 4) AS yr
FROM records r
JOIN photos p ON p.id = r.photo_id
LEFT JOIN exif e ON e.photo_id = p.id;
"""
SCHEMA += _V_RECORDS_DDL


def default_library_dir() -> Path:
    doc = Path.home() / "Documents"
    return doc / "BirdTraceWin"


class Library:
    """一个照片库实例。

    conn 为线程本地连接: UI线程/导入线程/识别线程各自持有,
    SQLite对象不允许跨线程复用; WAL模式保证并发读写安全。
    """

    def __init__(self, root: Path | None = None):
        import threading
        self._local = threading.local()
        # 强制绝对路径: 相对路径会让QUrl.fromLocalFile生成无盘符URL,
        # 地图页加载失败(file://data/... 而非 file:///D:/...)
        self.root = (Path(root) if root else default_library_dir()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "thumbnails").mkdir(exist_ok=True)
        self.db_path = self.root / "catalog.db"
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        """旧库升级: photos.spot_id (鸟点挂载, B3); photos.aesthetic (美学评分);
        photos.cand_json (未识别候选Top3, 2026-11-02一键采纳);
        photos.phash (感知哈希dHash64缓存, 0.8连拍分组/十八图去重);
        photos.group_id (连拍分组, 0.8-③); photos.missing INTEGER (原图离线标记)。"""
        # v_records视图缺top5_json(0.8.0-test3用户反馈: 查看器top5候选
        # 菜单永远为空的根因) → 重建视图。CREATE VIEW IF NOT EXISTS对
        # 已建视图无效, 必须显式检测列集后DROP重建
        vcols = {r["name"] for r in self.conn.execute(
            "PRAGMA table_info(v_records)")}
        if vcols and ("top5_json" not in vcols or "eye_json" not in vcols):
            self.conn.executescript(
                "DROP VIEW IF EXISTS v_records;\n" + _V_RECORDS_DDL)
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(photos)")}
        if "spot_id" not in cols:
            self.conn.execute(
                "ALTER TABLE photos ADD COLUMN spot_id INTEGER REFERENCES spots(id)")
        # 鸟点简称(0.8.3): 分享卡地点行显示用, 旧库自动补列
        scols = {r["name"] for r in self.conn.execute("PRAGMA table_info(spots)")}
        if "short_name" not in scols:
            self.conn.execute("ALTER TABLE spots ADD COLUMN short_name TEXT DEFAULT ''")
        # 眼睛点(0.8.4): 分享卡框对准保头用, 识别路径零改动——首次出卡
        # 时惰性计算并落库缓存(旧库自动补列, 旧记录NULL=未算过)
        rcols = {r["name"] for r in self.conn.execute("PRAGMA table_info(records)")}
        if "eye_json" not in rcols:
            self.conn.execute("ALTER TABLE records ADD COLUMN eye_json TEXT")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_photos_spot ON photos(spot_id)")
        if "aesthetic" not in cols:
            self.conn.execute("ALTER TABLE photos ADD COLUMN aesthetic REAL")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_photos_aesthetic ON photos(aesthetic)")
        if "cand_json" not in cols:
            self.conn.execute("ALTER TABLE photos ADD COLUMN cand_json TEXT")
        if "phash" not in cols:
            self.conn.execute("ALTER TABLE photos ADD COLUMN phash TEXT")
        if "group_id" not in cols:
            self.conn.execute("ALTER TABLE photos ADD COLUMN group_id TEXT")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_photos_group ON photos(group_id)")
        if "missing" not in cols:
            self.conn.execute(
                "ALTER TABLE photos ADD COLUMN missing INTEGER DEFAULT 0")
        # 选片三态/备注/组锁定(1.0冲刺①+⑨culling): pick=''未标/'keep'
        # 保留/'pending'待定/'reject'拒绝; group_lock=1人工拆合组,
        # regroup_bursts跳过锁定照片(人工标记不因重跑丢失)
        if "pick" not in cols:
            self.conn.execute(
                "ALTER TABLE photos ADD COLUMN pick TEXT DEFAULT ''")
        if "pick_note" not in cols:
            self.conn.execute(
                "ALTER TABLE photos ADD COLUMN pick_note TEXT DEFAULT ''")
        if "group_lock" not in cols:
            self.conn.execute(
                "ALTER TABLE photos ADD COLUMN group_lock INTEGER DEFAULT 0")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_photos_pick ON photos(pick)")
        # 拒绝片隔离区(1.0冲刺⑨③): 文件移入<库>/隔离区/<操作编号>/,
        # 照片记录不删只改path(缩略图/识别/评分全保留), 可恢复原路径
        # (原路径被占则拒绝, 绝不覆盖); 不提供永久删除
        if not self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='quarantine'").fetchone():
            self.conn.execute(
                "CREATE TABLE quarantine("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "photo_id INTEGER NOT NULL REFERENCES photos(id),"
                "op_no TEXT NOT NULL,"
                "quar_path TEXT NOT NULL,"
                "orig_path TEXT NOT NULL,"
                "file_hash TEXT NOT NULL,"
                "moved_at TEXT DEFAULT (datetime('now','localtime')),"
                "restored_at TEXT)")
        self._dedupe_records()

    def _dedupe_records(self):
        """自愈: 同一照片同一rank多条记录(0.8.0-test3识别与sidecar回填
        并发写入的历史脏数据)——每条照片每rank只留一条, 优先级:
        人工(确认/复核/手工/改框) > 带候选(top5) > 最新。多鸟照片的
        rank1/rank2不同rank, 不受影响。"""
        dup = self.conn.execute(
            "SELECT photo_id, rank, COUNT(*) n FROM records "
            "GROUP BY photo_id, rank HAVING n>1").fetchall()
        if not dup:
            return
        removed = 0
        for d in dup:
            rows = self.conn.execute(
                "SELECT id, confirmed_code, reviewed, source, top5_json "
                "FROM records WHERE photo_id=? AND rank=? ORDER BY id",
                (d["photo_id"], d["rank"])).fetchall()

            def score(r):
                if r["confirmed_code"] or r["reviewed"] or \
                        r["source"] in ("manual", "rebox"):
                    return 3
                if r["top5_json"] and r["top5_json"] not in ("", "[]"):
                    return 1
                return 0

            # 人工多条都保留(用户可能真的标了两只); 无人工时只留最优一条
            humans = [r for r in rows if score(r) == 3]
            if humans:
                keep_ids = {r["id"] for r in humans}
            else:
                best = max(rows, key=lambda r: (score(r), r["id"]))
                keep_ids = {best["id"]}
            for r in rows:
                if r["id"] not in keep_ids:
                    self.conn.execute("DELETE FROM records WHERE id=?",
                                      (r["id"],))
                    removed += 1
        if removed:
            self.conn.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
        return conn

    # ---------- settings ----------
    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        self.conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.conn.commit()

    # ---------- species 目录 ----------
    def species_filled(self) -> bool:
        n = self.conn.execute("SELECT COUNT(*) FROM species").fetchone()[0]
        return n > 0
    def fill_species(self):
        """从资产填充图鉴(11171种) + 拼音搜索字段 + IUCN。
        cn_name_overrides.json(可选)覆盖个别中文名——默认名取自APK
        catalog_v2.bin, 与国内标准名录不一致的在此修正(2026-11-02:
        brrmin1 褐背山椒鸟→小灰山椒鸟, 与SuperPicky/IOC一致)。"""
        from pypinyin import Style, lazy_pinyin
        catalog = json.loads((ASSETS / "data" / "species_catalog.json").read_text(encoding="utf-8"))
        labels = json.loads((ASSETS / "data" / "labels.json").read_text(encoding="utf-8"))
        classifier_codes = {l["code"] for l in labels}
        iucn = json.loads((ASSETS / "data" / "iucn_status.json").read_text(encoding="utf-8"))
        overrides_path = ASSETS / "data" / "cn_name_overrides.json"
        overrides = {}
        if overrides_path.exists():
            try:
                overrides = {k: v for k, v in json.loads(
                    overrides_path.read_text(encoding="utf-8")).items()
                    if not k.startswith("_")}
            except ValueError:
                overrides = {}
        rows = []
        for s in catalog:
            cn = overrides.get(s["code"]) or s["cn"] or s["en"]
            py = lazy_pinyin(cn, style=Style.NORMAL)
            initials = lazy_pinyin(cn, style=Style.FIRST_LETTER)
            rows.append((
                s["code"], cn, s["en"], s["sci"],
                s["order"][1] or "", s["family"][1] or "", s["genus"][0] or "",
                iucn.get(s["code"], ""), 1 if s["code"] in classifier_codes else 0,
                "".join(py).lower(), "".join(initials).lower(),
            ))
        self.conn.executemany(
            "INSERT OR REPLACE INTO species(code,cn,en,sci,order_cn,family_cn,genus,"
            "iucn,in_classifier,cn_pinyin,cn_initials) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
        self.conn.commit()
        print(f"species filled: {len(rows)}")

    def species_info(self, code: str):
        return self.conn.execute("SELECT * FROM species WHERE code=?", (code,)).fetchone()

    # ---------- photos ----------
    def photo_by_path(self, path: str):
        return self.conn.execute("SELECT * FROM photos WHERE path=?", (path,)).fetchone()

    def existing_hashes(self, hashes: list[str]) -> set[str]:
        if not hashes:
            return set()
        q = ("SELECT file_hash FROM photos WHERE file_hash IN (%s)"
             % ",".join("?" * len(hashes)))
        return {r["file_hash"] for r in self.conn.execute(q, hashes)}

    def add_photo(self, path: str, file_hash: str, size: int, mtime: float,
                  width: int, height: int, batch_id: int) -> int:
        cur = self.conn.execute(
            "INSERT INTO photos(path,file_hash,size,mtime,width,height,batch_id) "
            "VALUES(?,?,?,?,?,?,?)", (path, file_hash, size, mtime, width, height, batch_id))
        self.conn.commit()
        return cur.lastrowid

    def photo_count(self) -> int:
        """库内当前照片总数。

        计数规则(引用模式同样适用, 全库唯一口径):
        · 只数 photos 表现存行 —— 「从鸟迹移除」立即减1, 重新导入立即加1;
          原文件丢失(引用模式换电脑)仍计数, 由missing_files另行提示。
        · 时间线总数/状态栏"库内N张"/成就页照片里程碑/时间线全选
          全部取本函数, 不存在第二套口径。
        """
        return self.conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]

    def region_for_photo(self, photo_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT b.region_id FROM photos p JOIN batches b ON b.id=p.batch_id "
            "WHERE p.id=?", (photo_id,)).fetchone()
        return row["region_id"] if row else None

    def all_photos(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT p.id, p.path, e.dt_original FROM photos p "
            "LEFT JOIN exif e ON e.photo_id=p.id ORDER BY p.id").fetchall()
        return [dict(r) for r in rows]

    # ---------- exif ----------
    def add_exif(self, photo_id: int, ex: dict):
        self.conn.execute(
            "INSERT OR REPLACE INTO exif(photo_id,dt_original,make,model,lens,iso,"
            "exposure,fnum,focal_len,gps_lat,gps_lon,orientation,artist) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (photo_id, ex.get("dt_original"), ex.get("make"), ex.get("model"),
             ex.get("lens"), ex.get("iso"), ex.get("exposure"), ex.get("fnum"),
             ex.get("focal_len"), ex.get("gps_lat"), ex.get("gps_lon"),
             ex.get("orientation"), ex.get("artist")))
        self.conn.commit()

    # ---------- records ----------
    def has_human_record(self, photo_id: int) -> bool:
        """该照片是否有人工痕迹(确认/复核/手工标注/改框)。

        自动识别结果一律不得覆盖人工结果(2026-11-05: sidecar回填与
        识别并发时, 两套rank=1同时存在→查看器显示两个"主鸟")。"""
        row = self.conn.execute(
            "SELECT 1 FROM records WHERE photo_id=? AND "
            "(confirmed_code IS NOT NULL OR reviewed=1 "
            " OR source IN ('manual','rebox')) LIMIT 1",
            (photo_id,)).fetchone()
        return row is not None

    def add_records(self, photo_id: int, recs: list[dict]):
        # 幂等: 同一照片的自动识别结果整体替换(此前直接INSERT, 识别与
        # sidecar回填并发时产生重复rank——查看器两个"主鸟", 0.8.0-test3)
        if recs and self.has_human_record(photo_id):
            return                      # 人工结果优先, 自动结果不落库
        self.conn.execute("DELETE FROM records WHERE photo_id=?", (photo_id,))
        for i, r in enumerate(recs, 1):
            top5 = [{"code": t["code"], "prob": t["prob"]} for t in r.get("top5", [])]
            self.conn.execute(
                "INSERT INTO records(photo_id,species_code,rank,confidence,source,"
                "box_json,top5_json,eye_json) VALUES(?,?,?,?,?,?,?,?)",
                (photo_id, r["species_code"], i, r.get("confidence", 0),
                 r.get("source", "detect"), json.dumps(r.get("box")),
                 json.dumps(top5, ensure_ascii=False),
                 json.dumps(r.get("eye")) if r.get("eye") else None))
        if recs:
            self.conn.execute("UPDATE photos SET cand_json=NULL WHERE id=?",
                              (photo_id,))
        self.conn.commit()
        self._sidecar_touch(photo_ids=[photo_id])

    def pending_photo_ids(self) -> list[int]:
        rows = self.conn.execute(
            "SELECT p.id FROM photos p "
            "LEFT JOIN records r ON r.photo_id=p.id "
            "WHERE r.id IS NULL AND p.rec_fail < 3 ORDER BY p.id").fetchall()
        return [r["id"] for r in rows]

    def bump_rec_fail(self, photo_id: int):
        self.conn.execute("UPDATE photos SET rec_fail=rec_fail+1 WHERE id=?",
                          (photo_id,))
        self.conn.commit()

    def mark_no_bird(self, photo_id: int):
        """识别完成但没写出鸟种(raw<写名下限/名录落空/无检测/非鸟):
        不再自动重试, 照片保留在时间线, 可在查看器手工标注。
        cand_json清空(0.2~0.5的低置信已改为写名进待复核, 2026-11-02傍晚,
        旧库残留的候选不再展示)。"""
        self.conn.execute(
            "UPDATE photos SET rec_fail=3, cand_json=NULL WHERE id=?",
            (photo_id,))
        self.conn.commit()
        self._sidecar_touch(photo_ids=[photo_id])

    def mark_not_bird(self, photo_id: int):
        """待复核「不是鸟」: 撤回该照片的识别记录并标为无鸟(未识别)。
        用于检测器把蛇/其他动物误检成鸟的情况(2026-11-02用户语义:
        没鸟的进未识别)。照片仍在时间线, 可随时重新识别/手工标注。"""
        self.conn.execute("DELETE FROM records WHERE photo_id=?", (photo_id,))
        self.conn.execute(
            "UPDATE photos SET rec_fail=3, cand_json=NULL WHERE id=?",
            (photo_id,))
        self.conn.commit()
        self._sidecar_touch(photo_ids=[photo_id])

    def reset_recognition(self, photo_ids: list[int]):
        """批量重新识别: 清空识别记录并复位失败计数(人工确认一并清除)。"""
        for pid in photo_ids:
            self.conn.execute("DELETE FROM records WHERE photo_id=?", (pid,))
            self.conn.execute(
                "UPDATE photos SET rec_fail=0, cand_json=NULL WHERE id=?",
                (pid,))
        self.conn.commit()
        self._sidecar_touch(photo_ids=list(photo_ids))

    def set_confirmed(self, record_id: int, code: str | None):
        """人工确认/纠正: 写confirmed_code并标记已复核。"""
        self.conn.execute(
            "UPDATE records SET confirmed_code=?, reviewed=1 WHERE id=?",
            (code, record_id))
        self.conn.commit()
        self._sidecar_touch(record_id=record_id)

    def set_species_batch(self, photo_ids: list[int], to_code: str,
                          from_code: str | None = None) -> int:
        """批量改判鸟种(鸟种库多选): 所选照片里生效鸟种=from_code的记录
        写confirmed_code=to_code并标已复核; from_code=None时不限来源种。
        只动人工确认值, AI原值(species_code)与top5不动, 统计走eff_code
        自动跟上。多鸟照片里其他种的记录不受影响。返回改动记录数。"""
        n = 0
        for pid in photo_ids:
            rows = self.conn.execute(
                "SELECT id, species_code, confirmed_code FROM records "
                "WHERE photo_id=?", (pid,)).fetchall()
            for r in rows:
                eff = r["confirmed_code"] or r["species_code"]
                if eff == to_code:
                    continue
                if from_code is not None and eff != from_code:
                    continue
                self.conn.execute(
                    "UPDATE records SET confirmed_code=?, reviewed=1 "
                    "WHERE id=?", (to_code, r["id"]))
                n += 1
        self.conn.commit()
        self._sidecar_touch(photo_ids=list(photo_ids))
        return n

    # ---------- 选片工作流(1.0冲刺①+⑨culling, 2026-11-18) ----------

    def set_rating(self, photo_ids, rating: int) -> int:
        """人工星级(0=清星, 1~5)。与AI美学分(aesthetic列)互不干扰:
        重识别/美学重算永不覆盖人工评分。sidecar随标注走(已有编辑优先)。"""
        rating = max(0, min(5, int(rating)))
        ids = list(photo_ids)
        if not ids:
            return 0
        q = ",".join("?" * len(ids))
        cur = self.conn.execute(
            f"UPDATE photos SET rating=? WHERE id IN ({q})", [rating] + ids)
        self.conn.commit()
        self._sidecar_touch(photo_ids=ids)
        return cur.rowcount

    def set_pick(self, photo_ids, pick: str, note: str | None = None) -> int:
        """选片三态: 'keep'保留/'pending'待定/'reject'拒绝/''清除;
        note=备注(只记库不碰文件)。pick!=''时note才落库(清态即弃注)。"""
        if pick not in ("", "keep", "pending", "reject"):
            raise ValueError(f"bad pick: {pick!r}")
        ids = list(photo_ids)
        if not ids:
            return 0
        q = ",".join("?" * len(ids))
        if pick:
            cur = self.conn.execute(
                f"UPDATE photos SET pick=?, pick_note=? WHERE id IN ({q})",
                [pick, note or ""] + ids)
        else:
            cur = self.conn.execute(
                f"UPDATE photos SET pick='', pick_note='' WHERE id IN ({q})",
                ids)
        self.conn.commit()
        self._sidecar_touch(photo_ids=ids)
        return cur.rowcount

    def quarantine_move(self, photo_ids: list[int]) -> dict:
        """拒绝片隔离(⑨③): 文件移入 <库>/隔离区/<操作编号>/, 库path
        同步更新, 照片记录/识别/评分全保留(sidecar按file_hash键不受
        影响)。仅处理文件存在且未隔离的照片; 单文件失败不中断整批
        (计入failed)。绝不覆盖: 隔离目录为新建空目录, 同批同名冲突
        加序号(文件名无害变化, 实际位置记入quar_path)。"""
        import shutil
        import time
        import uuid
        ids = list(photo_ids)
        op = "Q" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        # 隔离区目录名=用户可见路径, 中文目录名(方案⑨③原文); 不入
        # 翻译(文件系统路径, 与"鸟迹导出"同类)
        dest_dir = self.root / t("隔离区", "Quarantine") / op
        dest_dir.mkdir(parents=True, exist_ok=True)
        moved, failed = [], []
        used = set()
        for pid in ids:
            r = self.conn.execute(
                "SELECT path, file_hash FROM photos WHERE id=?", (pid,)).fetchone()
            if not r:
                failed.append((pid, t("无记录", "No record")))
                continue
            src = Path(r["path"])
            if not src.is_file():
                failed.append((pid, t("源文件不存在", "Source file missing")))
                continue
            qrows = self.conn.execute(
                "SELECT 1 FROM quarantine WHERE photo_id=? AND restored_at "
                "IS NULL", (pid,)).fetchall()
            if qrows:
                failed.append((pid, t("已在隔离区", "Already quarantined")))
                continue
            dest = dest_dir / src.name
            k = 1
            while str(dest) in used or dest.exists():
                dest = dest_dir / f"{src.stem}_{k}{src.suffix}"
                k += 1
            try:
                shutil.move(str(src), str(dest))
            except OSError as e:
                failed.append((pid, t(f"移动失败: {e}", f"Move failed: {e}")))
                continue
            used.add(str(dest))
            self.conn.execute(
                "UPDATE photos SET path=? WHERE id=?", (str(dest), pid))
            self.conn.execute(
                "INSERT INTO quarantine(photo_id, op_no, quar_path, "
                "orig_path, file_hash) VALUES (?,?,?,?,?)",
                (pid, op, str(dest), r["path"], r["file_hash"]))
            moved.append(pid)
        self.conn.commit()
        return {"op_no": op, "dest": str(dest_dir), "moved": moved,
                "failed": failed}

    def quarantine_restore(self, qids: list[int]) -> dict:
        """从隔离区恢复到原路径。原路径已存在文件时拒绝(绝不覆盖同名),
        由用户处理后再试; 原目录已不存在则重建目录。"""
        import shutil
        restored, failed = [], []
        for qid in list(qids):
            q = self.conn.execute(
                "SELECT q.photo_id, q.quar_path, q.orig_path FROM quarantine q "
                "WHERE q.id=? AND q.restored_at IS NULL", (qid,)).fetchone()
            if not q:
                failed.append((qid, t("无此隔离记录或已恢复",
                                      "No such quarantine record or restored")))
                continue
            orig = Path(q["orig_path"])
            if orig.exists():
                failed.append((qid, t(f"原路径已被占用: {orig}",
                                      f"Original path occupied: {orig}")))
                continue
            quar = Path(q["quar_path"])
            if not quar.is_file():
                failed.append((qid, t(f"隔离文件缺失: {quar}",
                                      f"Quarantined file missing: {quar}")))
                continue
            try:
                orig.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(quar), str(orig))
            except OSError as e:
                failed.append((qid, t(f"恢复失败: {e}", f"Restore failed: {e}")))
                continue
            self.conn.execute(
                "UPDATE photos SET path=? WHERE id=?",
                (q["orig_path"], q["photo_id"]))
            self.conn.execute(
                "UPDATE quarantine SET restored_at=datetime('now','localtime') "
                "WHERE id=?", (qid,))
            restored.append(qid)
        self.conn.commit()
        return {"restored": restored, "failed": failed}

    def quarantine_list(self) -> list[dict]:
        """隔离区未恢复条目(管理对话框: 缩略图/原路径/哈希/时间)。"""
        rows = self.conn.execute(
            "SELECT q.id, q.photo_id, q.op_no, q.quar_path, q.orig_path, "
            "q.file_hash, q.moved_at FROM quarantine q "
            "WHERE q.restored_at IS NULL ORDER BY q.id").fetchall()
        return [dict(r) for r in rows]

    def split_from_group(self, photo_ids: list[int]) -> int:
        """人工拆组(⑨④): 所选照片脱离连拍组(group_id=NULL)并锁定;
        regroup_bursts跳过锁定照片, 组内其余成员照常自动分组。"""
        ids = [i for i in photo_ids if i]
        if not ids:
            return 0
        q = ",".join("?" * len(ids))
        cur = self.conn.execute(
            f"UPDATE photos SET group_id=NULL, group_lock=1 WHERE id IN ({q})",
            ids)
        self.conn.commit()
        return cur.rowcount

    def merge_into_group(self, photo_ids: list[int]) -> int:
        """人工合组(⑨④): 所选照片(可跨组/含单张)并成一组, 组号沿用
        'g<组内最小photo_id>'惯例, 整组锁定防重算打散。"""
        ids = [i for i in photo_ids if i]
        if len(ids) < 2:
            return 0
        gid = f"g{min(ids)}"
        q = ",".join("?" * len(ids))
        cur = self.conn.execute(
            f"UPDATE photos SET group_id=?, group_lock=1 WHERE id IN ({q})",
            [gid] + ids)
        self.conn.commit()
        return cur.rowcount

    def unlock_group(self, photo_ids: list[int]) -> int:
        """解除人工锁定, 回到自动分组(下次regroup_bursts自然归位)。"""
        ids = [i for i in photo_ids if i]
        if not ids:
            return 0
        q = ",".join("?" * len(ids))
        cur = self.conn.execute(
            f"UPDATE photos SET group_lock=0 WHERE id IN ({q})", ids)
        self.conn.commit()
        return cur.rowcount

    def set_main_record(self, photo_id: int, record_id: int):
        """把某条识别记录设为该照片的rank=1(主鸟), 其余顺延。"""
        rows = self.conn.execute(
            "SELECT id FROM records WHERE photo_id=? ORDER BY rank", (photo_id,)).fetchall()
        ids = [r["id"] for r in rows if r["id"] != record_id]
        for i, rid in enumerate([record_id] + ids, 1):
            self.conn.execute("UPDATE records SET rank=? WHERE id=?", (i, rid))
        self.conn.commit()
        self._sidecar_touch(photo_ids=[photo_id])

    def append_record(self, photo_id: int, rec: dict):
        """追加一条人工记录(0.8.6修: 画框识别确认走这里)。

        旧_accept走add_records: 整组替换语义被"人工优先"挡住——同一照片
        第二只起确认被静默丢弃(与"可连续框多只"矛盾, v0.8.5起verify_rebox
        即挂)。现追加rank=末尾一行, 既有记录(含人工)一律不动;
        主鸟判定/统计走eff_code自动跟上, 想换主鸟用set_main_record。
        rec字段同add_records(species_code/confidence/source/box/top5/eye)。"""
        nxt = self.conn.execute(
            "SELECT IFNULL(MAX(rank),0)+1 FROM records WHERE photo_id=?",
            (photo_id,)).fetchone()[0]
        top5 = [{"code": c["code"], "prob": c["prob"]}
                for c in rec.get("top5", [])]
        self.conn.execute(
            "INSERT INTO records(photo_id,species_code,rank,confidence,source,"
            "box_json,top5_json,eye_json) VALUES(?,?,?,?,?,?,?,?)",
            (photo_id, rec["species_code"], nxt, rec.get("confidence", 0),
             rec.get("source", "rebox"), json.dumps(rec.get("box")),
             json.dumps(top5, ensure_ascii=False),
             json.dumps(rec.get("eye")) if rec.get("eye") else None))
        self.conn.execute(
            "UPDATE photos SET cand_json=NULL WHERE id=?", (photo_id,))
        self.conn.commit()
        self._sidecar_touch(photo_ids=[photo_id])

    def remove_record(self, record_id: int) -> None:
        """删除单条识别记录(多鸟照片清掉误识的次要鸟, 如同种鸟只拍到屁股
        被认成别的种), 其余记录顺位重排保持rank连续。
        全部删光时置rec_fail=3: 视同无鸟, 不再被自动重识别
        (否则下次启动pending又把它识别回来), 仍可手工标注。"""
        row = self.conn.execute(
            "SELECT photo_id FROM records WHERE id=?", (record_id,)).fetchone()
        if not row:
            return
        pid = row["photo_id"]
        self.conn.execute("DELETE FROM records WHERE id=?", (record_id,))
        rest = self.conn.execute(
            "SELECT id FROM records WHERE photo_id=? ORDER BY rank",
            (pid,)).fetchall()
        if rest:
            for i, r in enumerate(rest, 1):
                self.conn.execute("UPDATE records SET rank=? WHERE id=?",
                                  (i, r["id"]))
        else:
            self.conn.execute("UPDATE photos SET rec_fail=3 WHERE id=?", (pid,))
        self.conn.commit()
        self._sidecar_touch(photo_ids=[pid])

    def update_record_box(self, record_id: int, box: list[float]) -> None:
        """用户在查看器里拖动检测框后写回(仅几何, 不动识别结果)。
        框变了眼点缓存即失效, 置空待下次出卡重算(0.8.4保头)。"""
        self.conn.execute(
            "UPDATE records SET box_json=?, eye_json=NULL WHERE id=?",
            (json.dumps([round(float(v), 1) for v in box]), record_id))
        self.conn.commit()
        self._sidecar_touch(record_id=record_id)

    def replace_record(self, record_id: int, rec: dict) -> None:
        """"用此框重新识别"落库: 原位替换鸟种/置信度/top5/框, 保持record_id
        与rank不变(UI刷新简单); 人工确认状态一并重置(等新结果复核)。"""
        top5 = [{"code": t["code"], "prob": t["prob"]}
                for t in (rec.get("top5") or [])]
        self.conn.execute(
            "UPDATE records SET species_code=?, confidence=?, source=?, "
            "box_json=?, top5_json=?, reviewed=0, confirmed_code=NULL, "
            "eye_json=NULL WHERE id=?",
            (rec["species_code"], rec.get("confidence", 0),
             rec.get("source", "rebox"),
             json.dumps(rec.get("box")), json.dumps(top5, ensure_ascii=False),
             record_id))
        self.conn.commit()
        self._sidecar_touch(record_id=record_id)

    def add_manual_record(self, photo_id: int, code: str) -> int:
        """无识别记录的照片手工标注鸟种(计入全部统计)。"""
        cur = self.conn.execute(
            "INSERT INTO records(photo_id,species_code,rank,confidence,source,"
            "reviewed,confirmed_code) VALUES(?,?,1,1.0,'manual',1,?)",
            (photo_id, code, code))
        self.conn.execute("UPDATE photos SET cand_json=NULL WHERE id=?",
                          (photo_id,))
        self.conn.commit()
        self._sidecar_touch(photo_ids=[photo_id])
        return cur.lastrowid

    def remove_photo(self, photo_id: int):
        """从鸟迹移除照片: 删数据库行与缩略图缓存, 原始文件绝不动。"""
        row = self.conn.execute(
            "SELECT file_hash FROM photos WHERE id=?", (photo_id,)).fetchone()
        if not row:
            return
        fhash = row["file_hash"]
        # 外键级联依赖PRAGMA(连接级), 显式删干净
        self.conn.execute("DELETE FROM records WHERE photo_id=?", (photo_id,))
        self.conn.execute("DELETE FROM exif WHERE photo_id=?", (photo_id,))
        self.conn.execute("DELETE FROM photos WHERE id=?", (photo_id,))
        self.conn.commit()
        d = self.root / "thumbnails" / fhash[:2]
        if d.exists():
            for tp in d.glob(f"{fhash}_*.webp"):
                try:
                    tp.unlink()
                except OSError:
                    pass
        # 用户清空重测习惯: 全部移除后把编号归零(photos/records/exif/batches),
        # 让下一次导入从#1开始, 并清掉批次历史(鸟点/物种表保留)
        if self.conn.execute("SELECT COUNT(*) c FROM photos").fetchone()["c"] == 0:
            self.conn.execute("DELETE FROM batches")
            self.conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN "
                "('photos','records','exif','batches')")
            self.conn.commit()

    def photo_detail(self, photo_id: int):
        """照片 + exif + 地区 + 鸟点 + 识别记录(带鸟种名)。"""
        photo = self.conn.execute(
            "SELECT p.*, e.dt_original, e.make, e.model, e.lens, e.iso, e.exposure, "
            "e.fnum, e.focal_len, e.gps_lat, e.gps_lon, e.artist, "
            "b.region_id AS region_id, sp.name AS spot_name, "
            "sp.short_name AS spot_short "
            "FROM photos p LEFT JOIN exif e ON e.photo_id=p.id "
            "LEFT JOIN batches b ON b.id=p.batch_id "
            "LEFT JOIN spots sp ON sp.id=p.spot_id WHERE p.id=?",
            (photo_id,)).fetchone()
        if not photo:
            return None, []
        recs = self.conn.execute(
            "SELECT v.*, s.cn, s.en, s.sci, s.iucn, s.family_cn FROM v_records v "
            "JOIN species s ON s.code=v.eff_code "
            "WHERE v.photo_id=? ORDER BY v.rank", (photo_id,)).fetchall()
        return dict(photo), [dict(r) for r in recs]

    def timeline(self) -> dict[str, list[dict]]:
        """时间线: 全部照片按拍摄年月分组(未识别照片也显示)。
        带 group_id/aesthetic 供连拍折叠(core.burst.collapse_bursts);
        0.8.6带 main_code/sp_cn/sp_en(缩略图鸟种说明+鸟种胶囊)与
        spot_name/spot_short(缩略图鸟点说明)。"""
        rows = self.conn.execute(
            "SELECT p.id, p.path, p.group_id, p.aesthetic, "
            "  COALESCE(e.dt_original, p.added_at) AS taken_at, "
            "  v0.eff_code AS main_code, sc.cn AS sp_cn, sc.en AS sp_en, "
            "  st.name AS spot_name, st.short_name AS spot_short, "
            "  p.rating, p.pick "
            "FROM photos p LEFT JOIN exif e ON e.photo_id=p.id "
            "  LEFT JOIN (SELECT photo_id, eff_code FROM v_records "
            "             WHERE rank=1 GROUP BY photo_id) v0 "
            "    ON v0.photo_id=p.id "
            "  LEFT JOIN species sc ON sc.code=v0.eff_code "
            "  LEFT JOIN spots st ON st.id=p.spot_id "
            "ORDER BY taken_at DESC").fetchall()
        out: dict[str, list] = {}
        for r in rows:
            ym = (r["taken_at"] or "")[:7] or t("未知时间", "Unknown date")
            out.setdefault(ym, []).append(
                {"id": r["id"], "path": r["path"], "taken_at": r["taken_at"],
                 "group_id": r["group_id"], "aesthetic": r["aesthetic"],
                 "main_code": r["main_code"], "sp_cn": r["sp_cn"],
                 "sp_en": r["sp_en"], "spot_name": r["spot_name"],
                 "spot_short": r["spot_short"],
                 "rating": int(r["rating"] or 0),
                 "pick": r["pick"] or ""})
        return out

    # ---------- 鸟种库 / 成就 ----------
    def species_overview(self, search: str = "") -> list[dict]:
        like = f"%{search.lower()}%"
        where = ("WHERE (s.cn LIKE ? OR s.en LIKE ? OR s.sci LIKE ? "
                 "OR s.cn_pinyin LIKE ? OR s.cn_initials LIKE ?)") if search else ""
        args = [like] * 5 if search else []
        rows = self.conn.execute(
            f"SELECT s.code, s.cn, s.en, s.sci, s.family_cn, s.iucn, s.in_classifier, "
            f"  COUNT(DISTINCT v.photo_id) AS n, "
            f"  MIN(v.taken_at) AS first_at, "
            f"  (SELECT v2.photo_id FROM v_records v2 "
            f"   JOIN photos p2 ON p2.id=v2.photo_id "
            f"   WHERE v2.eff_code=s.code "
            f"   ORDER BY p2.aesthetic DESC, v2.taken_at ASC LIMIT 1) AS cover_photo_id "
            f"FROM v_records v JOIN species s ON s.code=v.eff_code "
            f"{where} GROUP BY s.code ORDER BY first_at ASC", args).fetchall()
        return [dict(r) for r in rows]

    UNIDENTIFIED_CODE = "__unid__"   # 鸟种库「未识别」伪种code(不进species表)

    def unidentified_overview(self) -> dict:
        """未识别桶概览(2026-10-31 bug4): 识别完成但没写出鸟种的照片
        (无records且rec_fail>=3, 区别于待识别)。鸟种库展示、不计入鸟种数。"""
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM photos p WHERE p.rec_fail>=3 AND NOT EXISTS"
            "(SELECT 1 FROM records r WHERE r.photo_id=p.id)").fetchone()
        cover = self.conn.execute(
            "SELECT p.id AS cover_photo_id FROM photos p WHERE p.rec_fail>=3 "
            "AND NOT EXISTS(SELECT 1 FROM records r WHERE r.photo_id=p.id) "
            "ORDER BY p.aesthetic DESC, p.added_at ASC LIMIT 1").fetchone()
        return {"n": row["n"] if row else 0,
                "cover_photo_id": cover["cover_photo_id"] if cover else None}

    def unidentified_photos(self) -> list[dict]:
        """未识别桶照片流(最美优先), 供「未识别」伪种详情页。
        语义(2026-11-02傍晚): 只装没写出鸟种的照片——raw<写名下限/
        名录落空/无检测/非鸟; 低置信(0.2~0.5)已改为写名进待复核。"""
        rows = self.conn.execute(
            "SELECT p.id AS photo_id, p.path, p.added_at AS taken_at, "
            "p.aesthetic, st.name AS spot_name, st.short_name AS spot_short "
            "FROM photos p LEFT JOIN spots st ON st.id=p.spot_id "
            "WHERE p.rec_fail>=3 AND NOT EXISTS"
            "(SELECT 1 FROM records r WHERE r.photo_id=p.id) "
            "ORDER BY p.aesthetic DESC, p.added_at DESC").fetchall()
        return [dict(r) for r in rows]

    def photos_of_species(self, code: str) -> list[dict]:
        """该鸟种照片, 最美优先(美学评分降序, 无评分排后按拍摄时间)。
        0.8.6带 spot_name/spot_short(鸟种库缩略图鸟点说明)。"""
        rows = self.conn.execute(
            "SELECT v.photo_id, v.path, v.taken_at, p.aesthetic, p.group_id, "
            "  MAX(confidence) AS confidence, "
            "  MAX(reviewed) AS reviewed, MAX(confirmed_code) AS confirmed_code, "
            "  st.name AS spot_name, st.short_name AS spot_short, "
            "  p.rating AS rating, p.pick AS pick "
            "FROM v_records v JOIN photos p ON p.id=v.photo_id "
            "  LEFT JOIN spots st ON st.id=p.spot_id "
            "WHERE v.eff_code=? GROUP BY v.photo_id "
            "ORDER BY p.aesthetic DESC, v.taken_at DESC", (code,)).fetchall()
        return [dict(r) for r in rows]

    def lifers(self) -> list[dict]:
        """个人首见清单(按首见时间排序, 带lifer_no)与代表照片。

        lifer编号规则(引用模式移除/重导入均成立):
        · 第几种鸟 = 把鸟种按「当前在库照片的最早拍摄时间」升序排, 序号即
          1,2,3…; 拍摄时间取EXIF原始时间, 没有EXIF退回导入时间。
        · 完全由库内现存记录推导, 无隐藏状态 —— 移除某鸟种全部照片,
          该种退出清单、后面的编号自动前移(始终连续无空洞); 重新导入
          同一鸟种, 按其(新)最早拍摄时间重新排位, 同EXIF重导入编号不变。
        · 全部清空 = 归零重来(remove_photo清空时同步清batches与自增id),
          与用户"清空当全新软件"的习惯一致; 不存在删了照片还占号的幽灵lifer。
        """
        rows = self.conn.execute(
            "SELECT s.code, s.cn, s.en, s.sci, MIN(v.taken_at) AS first_at, "
            "  (SELECT v2.photo_id FROM v_records v2 WHERE v2.eff_code=s.code "
            "   ORDER BY v2.taken_at ASC LIMIT 1) AS photo_id "
            "FROM v_records v JOIN species s ON s.code=v.eff_code "
            "GROUP BY s.code ORDER BY first_at ASC").fetchall()
        return [{**dict(r), "lifer_no": i + 1} for i, r in enumerate(rows)]

    def lifer_no_for_species(self, code: str) -> int | None:
        for item in self.lifers():
            if item["code"] == code:
                return item["lifer_no"]
        return None

    def lifer_photo_ids(self) -> set[int]:
        return {li["photo_id"] for li in self.lifers() if li["photo_id"]}

    # ---------- 年鸟（今年首见且生涯首见不在今年） ----------
    def year_summary(self, year: str) -> dict:
        """{new: 生涯新种数(首见在今年), yearbird: 年鸟回归数}"""
        rows = self.conn.execute(
            """SELECT eff_code,
                      MIN(CASE WHEN substr(taken_at,1,4)=? THEN taken_at END)
                        AS first_this_year,
                      MIN(taken_at) AS career_first
               FROM v_records GROUP BY eff_code""",
            (year,)).fetchall()
        new = yearbird = 0
        for r in rows:
            if not r["first_this_year"]:
                continue
            if (r["career_first"] or "")[:4] == year:
                new += 1
            else:
                yearbird += 1
        return {"new": new, "yearbird": yearbird}

    def year_bird_codes(self, year: str) -> list[str]:
        """年鸟物种代码列表。"""
        rows = self.conn.execute(
            """SELECT eff_code,
                      MIN(taken_at) AS first_this_year,
                      (SELECT MIN(v2.taken_at) FROM v_records v2
                        WHERE v2.eff_code = v.eff_code) AS career_first
               FROM v_records v WHERE substr(v.taken_at,1,4)=?
               GROUP BY eff_code""",
            (year,)).fetchall()
        return [r["eff_code"] for r in rows
                if r["first_this_year"] and (r["career_first"] or "")[:4] != year]

    def year_bird_photo_ids(self, year: str) -> set[int]:
        """年鸟对应的"今年首张"照片id集合(时间线角标用)。"""
        codes = set(self.year_bird_codes(year))
        if not codes:
            return set()
        best: dict[str, tuple[int, str]] = {}
        for r in self.conn.execute(
                "SELECT photo_id, eff_code, taken_at FROM v_records "
                "WHERE substr(taken_at,1,4)=?", (year,)):
            if r["eff_code"] in codes:
                cur = best.get(r["eff_code"])
                if cur is None or r["taken_at"] < cur[1]:
                    best[r["eff_code"]] = (r["photo_id"], r["taken_at"])
        return {v[0] for v in best.values()}

    # ---------- 鸟点 ----------
    def spots_overview(self) -> list[dict]:
        """鸟点列表: 照片数/鸟种数/最近记录/封面照。"""
        rows = self.conn.execute(
            "SELECT sp.*, COUNT(DISTINCT p.id) AS n_photos, "
            "  COUNT(DISTINCT v.eff_code) AS n_species, "
            "  MAX(v.taken_at) AS last_at, "
            "  (SELECT p2.id FROM photos p2 WHERE p2.spot_id=sp.id "
            "   ORDER BY p2.id LIMIT 1) AS cover_photo_id "
            "FROM spots sp "
            "LEFT JOIN photos p ON p.spot_id=sp.id "
            "LEFT JOIN v_records v ON v.photo_id=p.id "
            "GROUP BY sp.id ORDER BY last_at DESC NULLS LAST, sp.id DESC").fetchall()
        return [dict(r) for r in rows]

    def spot_info(self, spot_id: int):
        r = self.conn.execute("SELECT * FROM spots WHERE id=?", (spot_id,)).fetchone()
        return dict(r) if r else None

    def create_spot(self, name: str, lat: float | None = None,
                    lon: float | None = None, note: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO spots(name,lat,lon,note) VALUES(?,?,?,?)",
            (name, lat, lon, note))
        self.conn.commit()
        return cur.lastrowid

    def update_spot(self, spot_id: int, name: str | None = None,
                    note: str | None = None, lat: float | None = None,
                    lon: float | None = None, short_name: str | None = None):
        cur = self.spot_info(spot_id)
        if not cur:
            return
        self.conn.execute(
            "UPDATE spots SET name=?, note=?, lat=?, lon=?, short_name=? "
            "WHERE id=?",
            (name if name is not None else cur["name"],
             note if note is not None else cur["note"],
             lat if lat is not None else cur["lat"],
             lon if lon is not None else cur["lon"],
             (short_name if short_name is not None
              else (cur["short_name"] if "short_name" in cur.keys() else "")),
             spot_id))
        self.conn.commit()
        # 0.8.7修(外审采纳): 鸟点名称/坐标/备注写进每张照片的sidecar,
        # 改点后必须让相关目录变脏, 否则换电脑导入会回填旧信息
        self._sidecar_touch(spot_id=spot_id)

    def delete_spot(self, spot_id: int):
        """删点不删照片, 挂载自动解除。"""
        self._sidecar_touch(spot_id=spot_id)
        self.conn.execute("UPDATE photos SET spot_id=NULL WHERE spot_id=?",
                          (spot_id,))
        self.conn.execute("DELETE FROM spots WHERE id=?", (spot_id,))
        self.conn.commit()

    def set_photo_spot(self, photo_id: int, spot_id: int | None):
        self.conn.execute("UPDATE photos SET spot_id=? WHERE id=?",
                          (spot_id, photo_id))
        self.conn.commit()
        self._sidecar_touch(photo_ids=[photo_id])

    def set_photos_spot(self, photo_ids: list[int], spot_id: int | None):
        """批量挂载(单事务)。"""
        self.conn.executemany(
            "UPDATE photos SET spot_id=? WHERE id=?",
            [(spot_id, pid) for pid in photo_ids])
        self.conn.commit()
        self._sidecar_touch(photo_ids=list(photo_ids))

    def spot_photos(self, spot_id: int) -> list[dict]:
        """鸟点内照片(含已识别种数与代表种名), 按拍摄时间倒序。"""
        rows = self.conn.execute(
            "SELECT p.id, p.path, p.file_hash, "
            "  COALESCE(e.dt_original, p.added_at) AS taken_at, "
            "  (SELECT v.eff_code FROM v_records v WHERE v.photo_id=p.id AND v.rank=1 "
            "   ORDER BY v.confidence DESC LIMIT 1) AS main_code, "
            "  (SELECT COUNT(DISTINCT v2.eff_code) FROM v_records v2 "
            "   WHERE v2.photo_id=p.id) AS n_species "
            "FROM photos p LEFT JOIN exif e ON e.photo_id=p.id "
            "WHERE p.spot_id=? ORDER BY taken_at DESC", (spot_id,)).fetchall()
        return [dict(r) for r in rows]

    def spot_species(self, spot_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT v.eff_code AS code, s.cn, s.en, s.sci, "
            "  COUNT(DISTINCT v.photo_id) AS n, MAX(v.taken_at) AS last_at "
            "FROM v_records v JOIN photos p ON p.id=v.photo_id "
            "JOIN species s ON s.code=v.eff_code "
            "WHERE p.spot_id=? GROUP BY v.eff_code "
            "ORDER BY n DESC, last_at DESC", (spot_id,)).fetchall()
        return [dict(r) for r in rows]

    def nearest_spot(self, lat: float, lon: float, max_m: float = 300.0):
        """300m内最近的鸟点, 返回(鸟点dict或None, 距离m)。"""
        from .core.spots import haversine_m
        best, best_d = None, max_m
        for r in self.conn.execute(
                "SELECT * FROM spots WHERE lat IS NOT NULL AND lon IS NOT NULL"):
            d = haversine_m(lat, lon, r["lat"], r["lon"])
            if d <= best_d:
                best, best_d = dict(r), d
        return best, (best_d if best else None)

    def review_queue(self) -> list[dict]:
        """待复核: 低置信或整图兜底的未确认记录(全部rank, 2026-11-04用户:
        多鸟照片的第二只低置信鸟此前直接进鸟种库绕过待复核)。"""
        rows = self.conn.execute(
            "SELECT v.record_id, v.photo_id, v.path, v.confidence, v.source, "
            "  s.code, s.cn, s.en, v.taken_at "
            "FROM v_records v JOIN species s ON s.code=v.eff_code "
            "WHERE v.reviewed=0 AND v.confirmed_code IS NULL "
            "  AND (v.confidence < 0.5 OR v.source='whole') "
            "ORDER BY v.confidence ASC").fetchall()
        return [dict(r) for r in rows]

    def stats_summary(self) -> dict:
        lifer_list = self.lifers()
        yearly: dict[str, int] = {}
        cumulative = 0
        by_year_new: dict[str, int] = {}
        for li in lifer_list:
            y = (li["first_at"] or "")[:4]
            by_year_new[y] = by_year_new.get(y, 0) + 1
        series = []
        for y in sorted(by_year_new):
            cumulative += by_year_new[y]
            series.append({"year": y, "new": by_year_new[y], "total": cumulative})
        return {"photos": self.photo_count(), "species": len(lifer_list),
                "series": series}

    # ---------- 个人成就 ----------
    RAPTOR_ORDERS = ("鹰形目", "隼形目", "鸮形目")  # i18n:ok
    WATERBIRD_ORDERS = ("鸻形目", "雁形目", "鹈形目", "鹤形目", "鸊鷉目", "鲣鸟目")  # i18n:ok

    def shooting_days(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(DISTINCT substr(taken_at,1,10)) FROM v_records"
        ).fetchone()[0]

    def streak_days(self) -> tuple[int, int]:
        """(当前连续, 最长连续) 观鸟天数(按记录日期)。"""
        rows = [r[0] for r in self.conn.execute(
            "SELECT DISTINCT substr(taken_at,1,10) d FROM v_records "
            "WHERE taken_at IS NOT NULL ORDER BY d")]
        if not rows:
            return 0, 0
        from datetime import date, timedelta
        # 防御: 非ISO日期(EXIF冒号未规范化/脏数据)跳过, 不让统计页崩
        days = []
        for d in rows:
            try:
                days.append(date.fromisoformat(d))
            except ValueError:
                continue
        if not days:
            return 0, 0
        longest = cur = 1
        for a, b in zip(days, days[1:]):
            cur = cur + 1 if (b - a).days == 1 else 1
            longest = max(longest, cur)
        today = date.today()
        current = 0
        for d in reversed(days):
            if (today - d).days <= 1:
                current += 1
                today = d
            else:
                break
        return current, longest

    def group_species_count(self, orders: tuple[str, ...]) -> int:
        """目(order_cn)属于给定集合的已收录鸟种数。"""
        q = (f"SELECT COUNT(DISTINCT v.eff_code) FROM v_records v "
             f"JOIN species s ON s.code=v.eff_code "
             f"WHERE s.order_cn IN ({','.join('?' * len(orders))})")
        return self.conn.execute(q, orders).fetchone()[0]

    def achievements_summary(self) -> dict:
        """成就页数据: 各里程碑的当前值/解锁日期(达成时的首见日期)。"""
        lifers = self.lifers()
        n_species = len(lifers)
        n_photos = self.photo_count()
        n_spots = self.conn.execute(
            "SELECT COUNT(*) FROM spots WHERE lat IS NOT NULL").fetchone()[0]
        cur_streak, max_streak = self.streak_days()

        def species_unlock(n: int) -> str | None:
            # 第n种的解锁日 = lifer列表(按首见升序)第n项的first_at
            return (lifers[n - 1]["first_at"] or "")[:10] if n_species >= n else None

        def photos_unlock(n: int) -> str | None:
            if n_photos < n:
                return None
            r = self.conn.execute(
                "SELECT COALESCE((SELECT dt_original FROM exif e "
                " WHERE e.photo_id=p.id), p.added_at) t FROM photos p "
                "ORDER BY t LIMIT 1 OFFSET ?", (n - 1,)).fetchone()
            return (r[0] or "")[:10] if r else None

        def spots_unlock(n: int) -> str | None:
            if n_spots < n:
                return None
            r = self.conn.execute(
                "SELECT substr(created_at,1,10) FROM spots "
                "WHERE lat IS NOT NULL ORDER BY id LIMIT 1 OFFSET ?",
                (n - 1,)).fetchone()
            return r[0] if r else None

        return {
            "photos": n_photos, "species": n_species,
            "spots": n_spots, "shooting_days": self.shooting_days(),
            "cur_streak": cur_streak, "max_streak": max_streak,
            "raptors": self.group_species_count(self.RAPTOR_ORDERS),  # i18n:ok
            "waterbirds": self.group_species_count(self.WATERBIRD_ORDERS),  # i18n:ok
            "species_unlock": species_unlock,
            "photos_unlock": photos_unlock,
            "spots_unlock": spots_unlock,
        }

    # ---------- 原图可用性 / 重新链接(换电脑/文件移动后) ----------
    def file_status(self, max_age: float = 3.0) -> dict:
        """全库原图可用性一次扫描(0.8-②):
        {"ok": n, "offline": {卷根: [ids]}, "missing": [ids], "n_offline": n}。

        同一刷新周期多页共享(缓存max_age秒); 结果写回 photos.missing
        (0可用/1离线卷/2不在原位置)供轻量查询。离线卷按卷只stat一次。"""
        import time
        cached = getattr(self, "_fs_cache", None)
        if cached and time.monotonic() - cached[0] < max_age:
            return cached[1]
        from .core.offline import classify_paths
        rows = self.conn.execute("SELECT id, path FROM photos").fetchall()
        cls = classify_paths((r["id"], r["path"]) for r in rows)
        n_off = sum(len(v) for v in cls["offline"].values())
        res = {"ok": len(cls["ok"]), "offline": cls["offline"],
               "missing": cls["missing"], "n_offline": n_off}
        try:
            self.conn.execute("UPDATE photos SET missing=0 WHERE missing<>0")
            for ids in cls["offline"].values():
                self.conn.executemany(
                    "UPDATE photos SET missing=1 WHERE id=?",
                    [(i,) for i in ids])
            self.conn.executemany("UPDATE photos SET missing=2 WHERE id=?",
                                  [(i,) for i in cls["missing"]])
            self.conn.commit()
        except sqlite3.Error:
            pass
        self._fs_cache = (time.monotonic(), res)
        return res

    def invalidate_file_status(self):
        self._fs_cache = None

    # ---------- 标注随文件夹走(0.8-①): 脏目录标记 + flush ----------
    def _sidecar_touch(self, photo_ids=None, record_id=None, spot_id=None,
                       paths=None):
        """标记相关照片所在文件夹需要重写 .birdtrace.json(主窗口定时/退出 flush)。
        线程安全(识别worker线程也会调)。"""
        import os
        import threading
        lock = getattr(self, "_sc_lock", None)
        if lock is None:
            lock = self._sc_lock = threading.Lock()
            self._sc_dirty = set()
        ps = list(paths or [])
        ids = list(photo_ids or [])
        if record_id is not None:
            r = self.conn.execute("SELECT photo_id FROM records WHERE id=?",
                                  (record_id,)).fetchone()
            if r:
                ids.append(r["photo_id"])
        if spot_id is not None:
            ids += [r["id"] for r in self.conn.execute(
                "SELECT id FROM photos WHERE spot_id=?", (spot_id,))]
        if ids:
            q = ",".join("?" * len(ids))
            ps += [r["path"] for r in self.conn.execute(
                f"SELECT path FROM photos WHERE id IN ({q})", ids)]
        with lock:
            for pth in ps:
                self._sc_dirty.add(os.path.dirname(pth))

    def flush_sidecars(self) -> int:
        """把脏目录的 sidecar 写出; 返回写成功的目录数。
        目录不可达(盘离线)或写入失败(只读盘/权限/杀软拦截)一律保留脏标记,
        挂回/恢复后再写(0.8.7修: 旧逻辑只在目录不存在时保留, 其余失败
        会被静默丢标记)。"""
        lock = getattr(self, "_sc_lock", None)
        if lock is None:
            return 0
        with lock:
            dirs = list(self._sc_dirty)
            self._sc_dirty.clear()
        if not dirs:
            return 0
        from .core.sidecar import export_folder
        n = 0
        for d in dirs:
            try:
                ok = export_folder(self, d) is not None
            except Exception:
                ok = False
            if ok:
                n += 1
            else:
                with lock:
                    self._sc_dirty.add(d)
        return n

    def sidecar_dirty_count(self) -> int:
        return len(self._sc_dirty) if getattr(self, "_sc_lock", None) else 0

    def missing_photo_ids(self) -> list[int]:
        """当前不可读的照片id(离线卷+不在原位置)。"""
        st = self.file_status(max_age=0)
        out = list(st["missing"])
        for ids in st["offline"].values():
            out.extend(ids)
        return sorted(out)

    def relink_photos(self, new_dir: Path) -> int:
        """原文件移动/换电脑后: 在新目录(含子目录)重新匹配。

        匹配顺序(0.8-②按hash自动化): ①同名候选里 file_hash 相同者;
        ②按 size 预筛再比 hash(改过名的文件也能找回, 内容优先于名字);
        ③仍未匹配且同名唯一→按名(旧行为, 兼容重存过/内容变了的文件)。
        只处理当前路径不可读的照片; 返回重新链接成功数。"""
        import os
        from .media import file_hash as _fh
        new_dir = Path(new_dir)
        exts = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif",
                ".bmp", ".tif", ".tiff")
        by_name: dict[str, list[Path]] = {}
        by_size: dict[int, list[Path]] = {}
        for f in new_dir.rglob("*"):
            if f.is_file() and f.suffix.lower() in exts:
                by_name.setdefault(f.name.lower(), []).append(f)
                try:
                    by_size.setdefault(f.stat().st_size, []).append(f)
                except OSError:
                    pass
        hash_cache: dict[Path, str] = {}

        def h(p: Path) -> str:
            v = hash_cache.get(p)
            if v is None:
                try:
                    v = _fh(p)
                except OSError:
                    v = ""
                hash_cache[p] = v
            return v

        relinked = 0
        taken: set[Path] = set()
        for r in self.conn.execute(
                "SELECT id, path, file_hash, size FROM photos").fetchall():
            if os.path.exists(r["path"]):
                continue
            name = os.path.basename(r["path"]).lower()
            cands = [c for c in by_name.get(name, []) if c not in taken]
            target = next((c for c in cands if h(c) == r["file_hash"]), None)
            if target is None and r["size"]:
                target = next((c for c in by_size.get(r["size"], [])
                               if c not in taken and h(c) == r["file_hash"]),
                              None)
            if target is None and len(cands) == 1:
                target = cands[0]
            if target:
                taken.add(target)
                self.conn.execute("UPDATE photos SET path=?, missing=0 WHERE id=?",
                                  (str(target), r["id"]))
                self._sidecar_touch(paths=[str(target)])
                relinked += 1
        self.conn.commit()
        self.invalidate_file_status()
        return relinked

    # ---------- eBird 导出 ----------
    def ebird_export_rows(self) -> list[dict]:
        """按 (鸟点, 日期) 聚合每鸟种一行, eBird CSV 兼容。

        Common/Scientific Name 用物种表英文名/学名; Count=照片数;
        Location=鸟点名(无鸟点用拍摄地区名); Date/Time 取EXIF;
        Protocol=Incidental(照片库逐条记录最贴切)。
        """
        from .core.regions import region_display
        rows = self.conn.execute(
            """SELECT v.eff_code, s.en, s.sci,
                      sp.name AS spot_name,
                      substr(v.taken_at,1,10) AS date,
                      substr(v.taken_at,12,5) AS time,
                      b.region_id AS region_id,
                      COUNT(DISTINCT v.photo_id) AS n
               FROM v_records v
               JOIN species s ON s.code=v.eff_code
               JOIN photos p ON p.id=v.photo_id
               LEFT JOIN spots sp ON sp.id=p.spot_id
               LEFT JOIN batches b ON b.id=p.batch_id
               WHERE v.taken_at IS NOT NULL AND v.taken_at != ''
               GROUP BY v.eff_code, p.spot_id, date, region_id
               ORDER BY date, spot_name, s.en""").fetchall()
        out = []
        for r in rows:
            loc = r["spot_name"]
            if not loc:
                loc = region_display(r["region_id"]) if r["region_id"] else ""
            out.append({
                "Common Name": r["en"] or r["sci"] or "",
                "Scientific Name": r["sci"] or "",
                "Count": r["n"],
                "Location": loc,
                "Date": r["date"],
                "Time": r["time"] or "",
                "Protocol": "Incidental",
                "Number of Observers": 1,
            })
        return out

    # ---------- 年度报告 ----------
    def available_years(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT substr(taken_at,1,4) y FROM v_records "
            "WHERE taken_at IS NOT NULL AND taken_at != '' ORDER BY y DESC"
        ).fetchall()
        ys = [r["y"] for r in rows if r["y"]]
        if not ys:
            import datetime
            ys = [datetime.date.today().strftime("%Y")]
        return ys

    def yearly_report(self, year: str) -> dict:
        """年度报告数据: 汇总/月度照片数/年度新种九宫格。"""
        lifers = self.lifers()
        year_first: list[dict] = []       # 生涯首见在该年的物种
        for li in lifers:
            if (li["first_at"] or "")[:4] == year:
                year_first.append(li)
        ys = self.year_summary(year)
        monthly = [0] * 12
        for r in self.conn.execute(
                "SELECT substr(taken_at,6,2) m, COUNT(DISTINCT photo_id) n "
                "FROM v_records WHERE substr(taken_at,1,4)=? GROUP BY m",
                (year,)):
            try:
                monthly[int(r["m"]) - 1] = r["n"]
            except (ValueError, IndexError):
                pass
        photos_year = self.conn.execute(
            "SELECT COUNT(DISTINCT photo_id) FROM v_records "
            "WHERE substr(taken_at,1,4)=?", (year,)).fetchone()[0]
        days = self.conn.execute(
            "SELECT COUNT(DISTINCT substr(taken_at,1,10)) FROM v_records "
            "WHERE substr(taken_at,1,4)=?", (year,)).fetchone()[0]
        busiest = max(range(12), key=lambda i: monthly[i]) + 1 if any(monthly) else None
        # 年度新种九宫格(首见照)
        grid = []
        for li in year_first[:9]:
            row = self.conn.execute(
                "SELECT path, file_hash FROM photos WHERE id=?",
                (li["photo_id"],)).fetchone() if li.get("photo_id") else None
            grid.append({"cn": li["cn"], "en": li["en"],
                         "path": row["path"] if row else None,
                         "hash": row["file_hash"] if row else "",
                         "date": (li["first_at"] or "")[:10]})
        return {"new": len(year_first), "yearbird": ys["yearbird"],
                "photos": photos_year, "days": days,
                "monthly": monthly, "busiest": busiest, "grid": grid,
                "total_species": len(lifers),
                "best18": self.best_of_year(year)}

    # ---------- 美学评分 ----------
    def set_aesthetic(self, photo_id: int, score: float):
        self.conn.execute("UPDATE photos SET aesthetic=? WHERE id=?",
                          (score, photo_id))
        # 0.8.7修(外审采纳): 连接是延迟事务模式, 此前不commit=美学worker
        # 线程(独立连接)上挂未提交事务, 无后续提交则退出时回滚丢分
        self.conn.commit()
        self._sidecar_touch(photo_ids=[photo_id])

    def pending_aesthetic(self) -> list[dict]:
        """有识别记录但还没打美学分的照片(按id升序, 后台逐张补)。"""
        rows = self.conn.execute(
            "SELECT p.id, p.path FROM photos p "
            "WHERE p.aesthetic IS NULL "
            "  AND p.id IN (SELECT DISTINCT photo_id FROM records) "
            "ORDER BY p.id").fetchall()
        return [dict(r) for r in rows]

    def phash_of(self, photo_id: int) -> str | None:
        """照片感知哈希(dHash 64bit, 16位hex); 缩略图计算+落库缓存。

        连拍分组/年度十八图去重共用。优先用已缓存缩略图, 原图离线
        也能算(0.8-②); 连缩略图都没有(原图离线且从未打开过)返回None。
        """
        row = self.conn.execute(
            "SELECT path, file_hash AS fh, phash FROM photos WHERE id=?",
            (photo_id,)).fetchone()
        if row is None:
            return None
        if row["phash"]:
            return row["phash"]
        from .media import ensure_thumbnail
        from .core.phash import dhash_file
        tp = ensure_thumbnail(self.root, row["path"], row["fh"], 96)
        if tp is None:
            return None
        val = dhash_file(tp)
        if val:
            self.conn.execute("UPDATE photos SET phash=? WHERE id=?",
                              (val, photo_id))
            self.conn.commit()
        return val

    def best_of_year(self, year: str, want: int = 18) -> list[dict]:
        """年度最佳(美学评分Top-N), 0.8-⑦去重版(用户定):

        先按美学分**每鸟种一张**取满18; 凑不够(鸟种少)再从各鸟种第2张补,
        第2张放宽条件 = 与该种第1张感知哈希距离≥BEST18_DIFF_MIN(不同构图/
        姿态, 原图离线算不出哈希则不补) 且美学分高于已选图的中位数。
        只取rank=1(主鸟)记录; 未评分照片不参与。
        """
        rows = self.conn.execute(
            "SELECT v.photo_id, v.eff_code, v.path, p.file_hash AS hash, "
            "  p.aesthetic, COALESCE(s.cn, s.en, v.eff_code) AS name, "
            "  v.taken_at "
            "FROM v_records v JOIN photos p ON p.id=v.photo_id "
            "LEFT JOIN species s ON s.code=v.eff_code "
            "WHERE v.yr=? AND v.rank=1 AND p.aesthetic IS NOT NULL "
            "ORDER BY p.aesthetic DESC", (year,)).fetchall()
        # 第一遍: 每种最高分1张
        picked: list[dict] = []
        first: dict[str, dict] = {}
        rest: list[dict] = []
        for r in rows:
            c = r["eff_code"]
            if c in first:
                rest.append(dict(r))
                continue
            first[c] = dict(r)
            picked.append(first[c])
            if len(picked) >= want:
                return picked
        # 第二遍: 各鸟种第2张补位(构图不同+高于已选中位数)
        import statistics
        from .core.phash import BEST18_DIFF_MIN, hamming
        n_per: dict[str, int] = {c: 1 for c in first}
        while len(picked) < want and rest:
            med = statistics.median(p["aesthetic"] for p in picked)
            chosen = None
            for r in rest:
                if r["aesthetic"] <= med:
                    break            # rest按分降序, 后面更不可能过中位数
                if n_per.get(r["eff_code"], 0) >= 2:
                    continue
                d = hamming(self.phash_of(r["photo_id"]),
                            self.phash_of(first[r["eff_code"]]["photo_id"]))
                if d is not None and d >= BEST18_DIFF_MIN:
                    chosen = r
                    break
            if chosen is None:
                break
            n_per[chosen["eff_code"]] = n_per.get(chosen["eff_code"], 0) + 1
            picked.append(chosen)
            rest.remove(chosen)
        picked.sort(key=lambda p: p["aesthetic"], reverse=True)
        return picked

    # ---------- 连拍分组(0.8-③) ----------
    def regroup_bursts(self) -> dict:
        """全量重算连拍分组(规则见 core/burst), 只写有变化的行。

        返回 {"groups": 组数, "photos": 入组照片数, "changed": 改写行数}。
        可在后台线程调用(线程本地连接)。"""
        from .core.burst import BURST_VERSION, group_bursts
        rows = self.conn.execute(
            "SELECT p.id, COALESCE(e.dt_original, p.added_at) AS taken_at, "
            "  (SELECT COALESCE(r.confirmed_code, r.species_code) FROM records r "
            "   WHERE r.photo_id=p.id AND r.rank=1 LIMIT 1) AS code, "
            "  p.group_id "
            "FROM photos p LEFT JOIN exif e ON e.photo_id=p.id "
            "WHERE p.group_lock=0").fetchall()
        mapping = group_bursts(({"id": r["id"], "taken_at": r["taken_at"],
                                 "code": r["code"]} for r in rows),
                               self.phash_of)
        changed = 0
        for r in rows:
            new = mapping.get(r["id"])
            if new != r["group_id"]:
                self.conn.execute("UPDATE photos SET group_id=? WHERE id=?",
                                  (new, r["id"]))
                changed += 1
        self.conn.commit()
        self.set_setting("burst_version", BURST_VERSION)
        return {"groups": len(set(mapping.values())), "photos": len(mapping),
                "changed": changed}

    def bursts_stale(self) -> bool:
        """分组规则版本变了(或从未分过)→需要重算一次。"""
        from .core.burst import BURST_VERSION
        return self.get_setting("burst_version", "") != BURST_VERSION

    def unify_burst_species(self, gap_s: float = 2.0,
                            threshold: float = 0.5) -> dict:
        """连拍组鸟种统一(0.8-②学习SuperPicky burst_species, 用户2026-11-04):
        按**纯拍摄时间链**(≤gap_s, 不管鸟种——组先形成再统一)成组,
        组内置信最高且≥threshold的rank=1帧为胜出帧, 其余有鸟帧统一为
        胜出帧的鸟种与置信度; 组内无帧达标则整组不动。
        人工确认过的记录(reviewed=1/confirmed_code)绝不改写。
        在识别完成后由主窗口后台调用(与UI折叠分组是两套组: 本函数
        按时间, 折叠按时间+鸟种+哈希——统一后两者自然一致)。

        返回 {"groups": 检查组数, "changed": 改写帧数}。"""
        from .core.burst import parse_ts
        # 只认EXIF拍摄时间: 无EXIF照片(截图/扫描/微信收图)的added_at是
        # 导入时刻, 整批导入全在同一两秒内→纯时间链会把不相干照片并成
        # 一组改写鸟种(数据破坏)。UI折叠分组另有dHash护栏, 这里是写库侧。
        rows = self.conn.execute(
            "SELECT p.id, e.dt_original AS ts, p.group_id FROM photos p "
            "JOIN exif e ON e.photo_id=p.id "
            "WHERE e.dt_original IS NOT NULL").fetchall()
        items = []
        for r in rows:
            ts = parse_ts(r["ts"])
            if ts is not None:
                items.append((ts, r["id"]))
        items.sort()
        groups: list[list[int]] = []
        cur: list[int] = []
        last_ts = None
        for ts, pid in items:
            if cur and ts - last_ts <= gap_s:
                cur.append(pid)
            else:
                if len(cur) >= 2:
                    groups.append(cur)
                cur = [pid]
            last_ts = ts
        if len(cur) >= 2:
            groups.append(cur)
        changed = 0
        for members in groups:
            best = None   # (conf, pid, code, rec_id, top5)
            for pid in members:
                rec = self.conn.execute(
                    "SELECT id, species_code, confidence, top5_json, reviewed, "
                    "  confirmed_code FROM records "
                    "WHERE photo_id=? AND rank=1 "
                    "ORDER BY confidence DESC LIMIT 1", (pid,)).fetchone()
                if rec is None:
                    continue
                if rec["reviewed"] or rec["confirmed_code"]:
                    continue   # 人工确认帧: 优先级高于自动胜出, 不参与也不被改
                if rec["confidence"] is None or rec["confidence"] < threshold:
                    continue
                if best is None or rec["confidence"] > best[0]:
                    best = (rec["confidence"], pid, rec["species_code"],
                            rec["id"], rec["top5_json"])
            if best is None:
                continue
            w_conf, w_pid, w_code, _w_rid, w_top5 = best
            for pid in members:
                if pid == w_pid:
                    continue
                rec = self.conn.execute(
                    "SELECT id, species_code, confidence, reviewed, "
                    "  confirmed_code FROM records "
                    "WHERE photo_id=? AND rank=1 "
                    "ORDER BY confidence DESC LIMIT 1", (pid,)).fetchone()
                if rec is None or rec["reviewed"] or rec["confirmed_code"]:
                    continue   # 无鸟帧/人工帧不动
                if rec["species_code"] == w_code and                         (rec["confidence"] or 0) >= threshold:
                    continue
                self.conn.execute(
                    "UPDATE records SET species_code=?, confidence=?, "
                    "  top5_json=?, source='burst', reviewed=0 "
                    "WHERE id=?",
                    (w_code, w_conf, w_top5, rec["id"]))
                self.conn.execute(
                    "UPDATE photos SET cand_json=NULL WHERE id=?", (pid,))
                changed += 1
        if changed:
            self.conn.commit()
        return {"groups": len(groups), "changed": changed}

    def group_members(self, group_id: str) -> list[int]:
        """组内照片id, 按拍摄时间升序。"""
        rows = self.conn.execute(
            "SELECT p.id FROM photos p LEFT JOIN exif e ON e.photo_id=p.id "
            "WHERE p.group_id=? ORDER BY COALESCE(e.dt_original, p.added_at), p.id",
            (group_id,)).fetchall()
        return [r["id"] for r in rows]

    # 分享卡候选行(单卡信息/批量导出共用): rank1记录 + 出卡所需全部字段
    _CARD_SELECT = (
        "SELECT v.record_id, v.photo_id, v.eff_code, v.path, "
        "  p.file_hash AS hash, "
        "  p.aesthetic, v.confidence, v.box_json, v.eye_json, "
        "  p.width, p.height, "
        "  COALESCE(s.cn, s.en, v.eff_code) AS cn, s.en AS en_name, "
        "  s.sci, v.taken_at, b.region_id AS region_id, "
        "  sp.name AS spot_name, sp.short_name AS spot_short, "
        "  e.dt_original, e.make, e.model, e.lens, e.iso, e.exposure, "
        "  e.fnum, e.focal_len, e.artist "
        "FROM v_records v JOIN photos p ON p.id=v.photo_id "
        "LEFT JOIN species s ON s.code=v.eff_code "
        "LEFT JOIN batches b ON b.id=p.batch_id "
        "LEFT JOIN spots sp ON sp.id=p.spot_id "
        "LEFT JOIN exif e ON e.photo_id=p.id ")

    def best_share_cards(self, date_from: str, date_to: str,
                         code: str | None = None,
                         per_species: int = 1) -> list[dict]:
        """批量分享卡候选(0.8-⑥): 日期区间内每鸟种 per_species 张"最美"
        (2026-11-04用户: 张数可选, 不足几张出几张)。

        "最美" = 美学分 × 置信度 取最高; 只取 已确认(confirmed_code非空,
        含手工标注, 其confidence=1.0) 或 原始置信≥0.5 的rank=1记录——
        待复核里的低置信错名不印进卡。未评分照片不参与。
        """
        sql = self._CARD_SELECT + (
            "WHERE v.rank=1 AND p.aesthetic IS NOT NULL "
            "  AND (v.confirmed_code IS NOT NULL OR v.confidence >= 0.5) "
            "  AND substr(v.taken_at,1,10) BETWEEN ? AND ? ")
        args: list = [date_from, date_to]
        if code:
            sql += "AND v.eff_code=? "
            args.append(code)
        sql += "ORDER BY p.aesthetic * v.confidence DESC, v.confidence DESC"
        out: list[dict] = []
        per: dict[str, int] = {}
        for r in self.conn.execute(sql, args).fetchall():
            n = per.get(r["eff_code"], 0)
            if n >= max(1, per_species):
                continue
            per[r["eff_code"]] = n + 1
            out.append(dict(r))
        return out

    def share_card_rows(self, photo_ids: list[int]) -> list[dict]:
        """按所选照片出卡(0.8.4鸟种库/时间线多选入口): 每张一条rank=1行,
        行结构同 best_share_cards。不做置信/美学门——用户显式选中优先。"""
        ids = list(dict.fromkeys(photo_ids))
        if not ids:
            return []
        q = ",".join("?" * len(ids))
        sql = (self._CARD_SELECT +
               f"WHERE v.rank=1 AND v.photo_id IN ({q}) "
               "ORDER BY v.taken_at DESC, v.photo_id")
        return [dict(r) for r in self.conn.execute(sql, ids).fetchall()]

    def close(self):
        self.conn.close()

    # ---------- 自动备份 ----------
    def maybe_backup(self, keep: int = 7, min_interval_h: float = 24.0,
                     force: bool = False) -> Path | None:
        """距上次备份超过24h时, 备份catalog.db到 <库>/backups/。

        用SQLite backup API(对WAL安全), 保留最近keep份; 失败静默(仅打印)。
        返回备份文件路径; 未备份返回None。
        (不做"库无变化跳过": WAL模式下主库mtime不可靠, 而库文件很小,
         每天一份的成本可忽略)
        """
        import time
        try:
            bdir = self.root / "backups"
            bdir.mkdir(exist_ok=True)
            now = time.time()
            last_at = self.get_setting("last_backup_at", "")
            if not force and last_at and now - float(last_at) < min_interval_h * 3600:
                return None
            stamp = time.strftime("%Y%m%d-%H%M")
            dst = bdir / f"catalog-{stamp}.db"
            src = self.conn  # 线程本地连接
            import sqlite3
            with sqlite3.connect(dst) as dst_conn:
                src.backup(dst_conn)
            self.set_setting("last_backup_at", str(now))
            # 只保留最近keep份
            backups = sorted(bdir.glob("catalog-*.db"))
            for old in backups[:-keep]:
                try:
                    old.unlink()
                except OSError:
                    pass
            print(f"backup: {dst.name} (保留{min(len(backups), keep)}份)")  # i18n:ok
            return dst
        except Exception as e:
            print(f"backup failed: {e}")
            return None

    def last_backup_info(self) -> str:
        """设置页展示用: 最近一次备份的说明。"""
        import time
        files = sorted((self.root / "backups").glob("catalog-*.db"))
        if not files:
            return t("从未备份", "Never backed up")
        ts = self.get_setting("last_backup_at", "")
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts))) \
            if ts.replace(".", "").isdigit() else files[-1].stem
        return t(f"{when}（{len(files)} 份，位于库目录 backups/）",
                 f"{when} ({len(files)} backups, in library backups/)")
