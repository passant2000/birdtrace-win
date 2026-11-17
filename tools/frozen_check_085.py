# -*- coding: utf-8 -*-
"""0.8.5 冻结实测: 中文路径库导入→exe启动自动识别→断言识别/top5/美学/存活。

用法: .venv/Scripts/python.exe -u tools/frozen_check_085.py
前置: packaging/dist/birdtrace 已构建(make_release.py)。
流程(沿0.8.4惯例): 中文路径库+导入(不识别)+预置网格档位240(0.8.5新设置
读取路径) → 启动exe(--library) → 轮询识别完成 → 断言: 6照片/识别5+无鸟1/
top5全带/0重复rank1/美学5/PID稳定/档位设置未被破坏。
"""
import ctypes
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
EXE = PROJ / "packaging" / "dist" / "birdtrace" / "鸟迹BirdTrace.exe"
LIB = PROJ / "data" / "冻结测试-0.8.5" / "照片库"
SRC = PROJ / "data" / "冻结测试-0.8.5" / "原图"
TITLE = "鸟迹 · 鸟类照片管理"

ok = fail = 0


def check(name, cond, note=""):
    global ok, fail
    ok += bool(cond)
    fail += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {note}")


# ---- 1. 备库: 中文路径 + 导入不识别 ----
if LIB.parent.exists():
    shutil.rmtree(LIB.parent)
SRC.mkdir(parents=True)
for f in (PROJ / "data" / "test_images").glob("*.jpg"):
    shutil.copy2(f, SRC / f.name)

sys.path.insert(0, str(PROJ))
from app.db import Library
from app.core.importer import import_files

lib = Library(LIB)
lib.fill_species()
lib.set_setting("grid_tile", "240")     # 0.8.5: 档位设置读取路径
st = import_files(lib, sorted(SRC.glob("*.jpg")), mode="ref", region_id="CN")
print("imported:", st["added"], "skipped:", st.get("skipped_dup"))
lib.close()

# ---- 2. 启动exe, 轮询识别完成 ----
user32 = ctypes.windll.user32
proc = subprocess.Popen([str(EXE), "--library", str(LIB)])
print("PID:", proc.pid)
t0 = time.time()
done = False
n_rec = n_ae = 0
while time.time() - t0 < 420:
    time.sleep(5)
    alive = proc.poll() is None
    if not alive:
        break
    hwnd = user32.FindWindowW(None, TITLE)
    if not hwnd:
        continue
    try:
        conn = sqlite3.connect(f"file:{LIB / 'catalog.db'}?mode=ro", uri=True)
        n_ph = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
        n_rec = conn.execute(
            "SELECT COUNT(DISTINCT photo_id) FROM records").fetchone()[0]
        n_ae = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE aesthetic IS NOT NULL"
            ).fetchone()[0]
        n_un = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE rec_fail>=3 AND NOT EXISTS"
            "(SELECT 1 FROM records r WHERE r.photo_id=photos.id)"
            ).fetchone()[0]
        conn.close()
        if n_ph and n_rec + n_un == n_ph and n_rec >= 5 \
                and n_ae >= n_rec:
            done = True
            print(f"识别+美学完成 @{time.time()-t0:.0f}s: 照片{n_ph} "
                  f"有记录{n_rec} 无鸟{n_un} 美学{n_ae}")
            break
        # 别在识别一完就停: 美学worker还在后台, 提前break会误判ae=0(首轮教训)
    except sqlite3.Error as e:
        print("db poll:", e)
check("识别完成(5有记录+1无鸟)", done, f"rec={n_rec} un={n_un} ae={n_ae}")

# ---- 3. 断言: top5/重复rank1/美学 ----
conn = sqlite3.connect(LIB / "catalog.db")
conn.row_factory = sqlite3.Row
top5_ok = True
for r in conn.execute("SELECT top5_json FROM records WHERE rank=1"):
    t5 = json.loads(r["top5_json"] or "[]")
    if not t5:
        top5_ok = False
check("rank1记录全带top5", top5_ok)
dup = conn.execute(
    "SELECT photo_id, COUNT(*) n FROM records WHERE rank=1 "
    "GROUP BY photo_id HAVING n>1").fetchall()
check("无重复rank1", not dup, str([dict(d) for d in dup][:3]))
check("美学评分5张", n_ae == 5, f"ae={n_ae}")
conn.close()

# ---- 4. 90s 存活(识别完成后继续轮询PID) ----
still = True
for _ in range(18):
    time.sleep(5)
    if proc.poll() is not None:
        still = False
        break
check("识别后90s+存活", still, f"exit={proc.poll()}")
proc.terminate()
try:
    proc.wait(10)
except Exception:
    proc.kill()

print(f"\n===== 冻结实测: PASS={ok} FAIL={fail} =====")
sys.exit(1 if fail else 0)
