# -*- coding: utf-8 -*-
"""照片库: SQLite编目数据库 + DAO。

库位置默认在 文档/BirdTraceWin/, 内含 catalog.db 与 thumbnails/ 缓存。
设计原则: photos 表只引用文件路径, 绝不移动/修改原文件。

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
SPECIES_DATA_VERSION = "2026-11-03a"

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
  reviewed INTEGER DEFAULT 0, confirmed_code TEXT
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
  lat REAL, lon REAL,
  note TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);

CREATE VIEW IF NOT EXISTS v_records AS
SELECT r.id AS record_id, r.photo_id, p.path,
       COALESCE(r.confirmed_code, r.species_code) AS eff_code,
       r.species_code, r.rank, r.confidence, r.source, r.reviewed,
       r.confirmed_code, r.box_json,
       COALESCE(e.dt_original, p.added_at) AS taken_at,
       substr(COALESCE(e.dt_original, p.added_at), 1, 7) AS ym,
       substr(COALESCE(e.dt_original, p.added_at), 1, 4) AS yr
FROM records r
JOIN photos p ON p.id = r.photo_id
LEFT JOIN exif e ON e.photo_id = p.id;
"""


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
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(photos)")}
        if "spot_id" not in cols:
            self.conn.execute(
                "ALTER TABLE photos ADD COLUMN spot_id INTEGER REFERENCES spots(id)")
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
    def add_records(self, photo_id: int, recs: list[dict]):
        for i, r in enumerate(recs, 1):
            top5 = [{"code": t["code"], "prob": t["prob"]} for t in r.get("top5", [])]
            self.conn.execute(
                "INSERT INTO records(photo_id,species_code,rank,confidence,source,"
                "box_json,top5_json) VALUES(?,?,?,?,?,?,?)",
                (photo_id, r["species_code"], i, r.get("confidence", 0),
                 r.get("source", "detect"), json.dumps(r.get("box")),
                 json.dumps(top5, ensure_ascii=False)))
        if recs:
            self.conn.execute("UPDATE photos SET cand_json=NULL WHERE id=?",
                              (photo_id,))
        self.conn.commit()

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

    def mark_not_bird(self, photo_id: int):
        """待复核「不是鸟」: 撤回该照片的识别记录并标为无鸟(未识别)。
        用于检测器把蛇/其他动物误检成鸟的情况(2026-11-02用户语义:
        没鸟的进未识别)。照片仍在时间线, 可随时重新识别/手工标注。"""
        self.conn.execute("DELETE FROM records WHERE photo_id=?", (photo_id,))
        self.conn.execute(
            "UPDATE photos SET rec_fail=3, cand_json=NULL WHERE id=?",
            (photo_id,))
        self.conn.commit()

    def reset_recognition(self, photo_ids: list[int]):
        """批量重新识别: 清空识别记录并复位失败计数(人工确认一并清除)。"""
        for pid in photo_ids:
            self.conn.execute("DELETE FROM records WHERE photo_id=?", (pid,))
            self.conn.execute(
                "UPDATE photos SET rec_fail=0, cand_json=NULL WHERE id=?",
                (pid,))
        self.conn.commit()

    def set_confirmed(self, record_id: int, code: str | None):
        """人工确认/纠正: 写confirmed_code并标记已复核。"""
        self.conn.execute(
            "UPDATE records SET confirmed_code=?, reviewed=1 WHERE id=?",
            (code, record_id))
        self.conn.commit()

    def set_main_record(self, photo_id: int, record_id: int):
        """把某条识别记录设为该照片的rank=1(主鸟), 其余顺延。"""
        rows = self.conn.execute(
            "SELECT id FROM records WHERE photo_id=? ORDER BY rank", (photo_id,)).fetchall()
        ids = [r["id"] for r in rows if r["id"] != record_id]
        for i, rid in enumerate([record_id] + ids, 1):
            self.conn.execute("UPDATE records SET rank=? WHERE id=?", (i, rid))
        self.conn.commit()

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

    def update_record_box(self, record_id: int, box: list[float]) -> None:
        """用户在查看器里拖动检测框后写回(仅几何, 不动识别结果)。"""
        self.conn.execute(
            "UPDATE records SET box_json=? WHERE id=?",
            (json.dumps([round(float(v), 1) for v in box]), record_id))
        self.conn.commit()

    def replace_record(self, record_id: int, rec: dict) -> None:
        """"用此框重新识别"落库: 原位替换鸟种/置信度/top5/框, 保持record_id
        与rank不变(UI刷新简单); 人工确认状态一并重置(等新结果复核)。"""
        top5 = [{"code": t["code"], "prob": t["prob"]}
                for t in (rec.get("top5") or [])]
        self.conn.execute(
            "UPDATE records SET species_code=?, confidence=?, source=?, "
            "box_json=?, top5_json=?, reviewed=0, confirmed_code=NULL "
            "WHERE id=?",
            (rec["species_code"], rec.get("confidence", 0),
             rec.get("source", "rebox"),
             json.dumps(rec.get("box")), json.dumps(top5, ensure_ascii=False),
             record_id))
        self.conn.commit()

    def add_manual_record(self, photo_id: int, code: str) -> int:
        """无识别记录的照片手工标注鸟种(计入全部统计)。"""
        cur = self.conn.execute(
            "INSERT INTO records(photo_id,species_code,rank,confidence,source,"
            "reviewed,confirmed_code) VALUES(?,?,1,1.0,'manual',1,?)",
            (photo_id, code, code))
        self.conn.execute("UPDATE photos SET cand_json=NULL WHERE id=?",
                          (photo_id,))
        self.conn.commit()
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
            "b.region_id AS region_id, sp.name AS spot_name "
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
        """时间线: 全部照片按拍摄年月分组(未识别照片也显示)。"""
        rows = self.conn.execute(
            "SELECT p.id, p.path, COALESCE(e.dt_original, p.added_at) AS taken_at "
            "FROM photos p LEFT JOIN exif e ON e.photo_id=p.id "
            "ORDER BY taken_at DESC").fetchall()
        out: dict[str, list] = {}
        for r in rows:
            ym = (r["taken_at"] or "")[:7] or t("未知时间", "Unknown date")
            out.setdefault(ym, []).append(
                {"id": r["id"], "path": r["path"], "taken_at": r["taken_at"]})
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
            "p.aesthetic FROM photos p "
            "WHERE p.rec_fail>=3 AND NOT EXISTS"
            "(SELECT 1 FROM records r WHERE r.photo_id=p.id) "
            "ORDER BY p.aesthetic DESC, p.added_at DESC").fetchall()
        return [dict(r) for r in rows]

    def photos_of_species(self, code: str) -> list[dict]:
        """该鸟种照片, 最美优先(美学评分降序, 无评分排后按拍摄时间)。"""
        rows = self.conn.execute(
            "SELECT v.photo_id, v.path, v.taken_at, p.aesthetic, "
            "  MAX(confidence) AS confidence, "
            "  MAX(reviewed) AS reviewed, MAX(confirmed_code) AS confirmed_code "
            "FROM v_records v JOIN photos p ON p.id=v.photo_id "
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
                    lon: float | None = None):
        cur = self.spot_info(spot_id)
        if not cur:
            return
        self.conn.execute(
            "UPDATE spots SET name=?, note=?, lat=?, lon=? WHERE id=?",
            (name if name is not None else cur["name"],
             note if note is not None else cur["note"],
             lat if lat is not None else cur["lat"],
             lon if lon is not None else cur["lon"],
             spot_id))
        self.conn.commit()

    def delete_spot(self, spot_id: int):
        """删点不删照片, 挂载自动解除。"""
        self.conn.execute("UPDATE photos SET spot_id=NULL WHERE spot_id=?",
                          (spot_id,))
        self.conn.execute("DELETE FROM spots WHERE id=?", (spot_id,))
        self.conn.commit()

    def set_photo_spot(self, photo_id: int, spot_id: int | None):
        self.conn.execute("UPDATE photos SET spot_id=? WHERE id=?",
                          (spot_id, photo_id))
        self.conn.commit()

    def set_photos_spot(self, photo_ids: list[int], spot_id: int | None):
        """批量挂载(单事务)。"""
        self.conn.executemany(
            "UPDATE photos SET spot_id=? WHERE id=?",
            [(spot_id, pid) for pid in photo_ids])
        self.conn.commit()

    def spot_photos(self, spot_id: int) -> list[dict]:
        """鸟点内照片(含已识别种数与代表种名), 按拍摄时间倒序。"""
        rows = self.conn.execute(
            "SELECT p.id, p.path, COALESCE(e.dt_original, p.added_at) AS taken_at, "
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
        """待复核: 低置信度或整图兜底的未确认主记录。"""
        rows = self.conn.execute(
            "SELECT v.record_id, v.photo_id, v.path, v.confidence, v.source, "
            "  s.code, s.cn, s.en, v.taken_at "
            "FROM v_records v JOIN species s ON s.code=v.eff_code "
            "WHERE v.rank=1 AND v.reviewed=0 AND v.confirmed_code IS NULL "
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

    # ---------- 重新链接(换电脑/文件移动后) ----------
    def missing_photo_ids(self) -> list[int]:
        out = []
        for r in self.conn.execute("SELECT id, path FROM photos"):
            if not Path(r["path"]).exists():
                out.append(r["id"])
        return out

    def relink_photos(self, new_dir: Path) -> int:
        """原文件移动/换电脑后: 在新目录(含子目录)按文件名重新匹配。
        只处理当前路径已失效的照片; 返回重新链接成功数。"""
        import os
        new_dir = Path(new_dir)
        # 新目录文件名索引(同名多份时取最早修改的)
        index: dict[str, Path] = {}
        for f in new_dir.rglob("*"):
            if f.is_file() and f.suffix.lower() in (
                    ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif",
                    ".bmp", ".tif", ".tiff"):
                index.setdefault(f.name.lower(), f)
        relinked = 0
        for r in self.conn.execute("SELECT id, path FROM photos").fetchall():
            if Path(r["path"]).exists():
                continue
            name = os.path.basename(r["path"]).lower()
            target = index.get(name)
            if target:
                self.conn.execute("UPDATE photos SET path=? WHERE id=?",
                                  (str(target), r["id"]))
                relinked += 1
        self.conn.commit()
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

    def best_share_cards(self, date_from: str, date_to: str,
                         code: str | None = None) -> list[dict]:
        """批量分享卡候选(0.8-⑥): 日期区间内每鸟种一张"最美"。

        "最美" = 美学分 × 置信度 取最高; 只取 已确认(confirmed_code非空,
        含手工标注, 其confidence=1.0) 或 原始置信≥0.5 的rank=1记录——
        待复核里的低置信错名不印进卡。未评分照片不参与。
        """
        sql = (
            "SELECT v.photo_id, v.eff_code, v.path, p.file_hash AS hash, "
            "  p.aesthetic, v.confidence, "
            "  COALESCE(s.cn, s.en, v.eff_code) AS cn, s.en AS en_name, "
            "  s.sci, v.taken_at, b.region_id AS region_id, "
            "  e.dt_original, e.make, e.model, e.lens, e.iso, e.exposure, "
            "  e.fnum, e.focal_len, e.artist "
            "FROM v_records v JOIN photos p ON p.id=v.photo_id "
            "LEFT JOIN species s ON s.code=v.eff_code "
            "LEFT JOIN batches b ON b.id=p.batch_id "
            "LEFT JOIN exif e ON e.photo_id=p.id "
            "WHERE v.rank=1 AND p.aesthetic IS NOT NULL "
            "  AND (v.confirmed_code IS NOT NULL OR v.confidence >= 0.5) "
            "  AND substr(v.taken_at,1,10) BETWEEN ? AND ? ")
        args: list = [date_from, date_to]
        if code:
            sql += "AND v.eff_code=? "
            args.append(code)
        sql += "ORDER BY p.aesthetic * v.confidence DESC, v.confidence DESC"
        out: list[dict] = []
        seen: set[str] = set()
        for r in self.conn.execute(sql, args).fetchall():
            if r["eff_code"] in seen:
                continue
            seen.add(r["eff_code"])
            out.append(dict(r))
        return out

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
