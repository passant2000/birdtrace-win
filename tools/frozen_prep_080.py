# -*- coding: utf-8 -*-
"""冻结实测准备: 中文路径库+导入(不识别), 供exe启动自动识别。"""
import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB = PROJ / "data" / "冻结测试-0.8test1" / "照片库"
SRC = PROJ / "data" / "冻结测试-0.8test1" / "原图"
if LIB.parent.exists():
    shutil.rmtree(LIB.parent)
SRC.mkdir(parents=True)
for f in (PROJ / "data" / "test_images").glob("*.jpg"):
    shutil.copy2(f, SRC / f.name)

from app.db import Library
from app.core.importer import import_files

lib = Library(LIB)
lib.fill_species()
st = import_files(lib, sorted(SRC.glob("*.jpg")), mode="ref", region_id="CN")
print("imported:", st["added"], "skipped:", st["skipped_dup"],
      "sidecar:", st.get("sidecar"))
print("待识别:", len(lib.pending_photo_ids()))
print("LIB:", LIB)
