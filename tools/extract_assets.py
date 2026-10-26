# -*- coding: utf-8 -*-
"""从 birdtrace.apk 一次性提取并转换模型/数据资产。

产物:
  assets/models/BirdTraceRecognitionModel.onnx   识别模型 (直接拷贝, 校验SHA256)
  assets/models/BirdTraceBirdDetector_FP32.onnx  检测模型 (直接拷贝)
  assets/data/labels.json           10480类 {i, en, code, sci}
  assets/data/species_catalog.json  11171种图鉴 {code, cn, en, sci, order_cn, family_cn, ...}
  assets/data/geo_prior.sqlite      地理先验库 (直接拷贝)
  assets/data/regions.json          区域表 (直接拷贝)
  assets/data/model_manifest.properties (留档)

用法: python tools/extract_assets.py [apk路径] [输出目录]
"""
import hashlib
import json
import struct
import sys
import zipfile
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
APK = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJ.parent / "birdtrace.apk"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else PROJ / "assets"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------- class_mapping_v1.bin (BTRCLS01) ----------
def parse_class_mapping(raw: bytes):
    if raw[:8] != b"BTRCLS01":
        raise ValueError("bad magic for class mapping")
    # 头部: magic8 + u32BE version + u32BE class_count + u32BE catalog_count
    #     + 日期串 + 两个sha256 —— 具体长度以实际解析为准, 先按固定探查
    ver, n_class, n_cat = struct.unpack_from(">III", raw, 8)
    print(f"  class_mapping: version={ver} classes={n_class} catalog={n_cat}")
    # 日期串: u32BE长度 + 内容; 之后两个 sha256hex(64字符) 各带 u32BE长度前缀
    off = 20
    ls = struct.unpack_from(">I", raw, off)[0]
    off += 4
    date_str = raw[off:off + ls].decode("utf-8")
    off += ls
    print(f"  build date: {date_str}")
    for _ in range(2):
        ls = struct.unpack_from(">I", raw, off)[0]
        off += 4
        print(f"  sha: {raw[off:off+ls].decode('ascii')[:16]}...")
        off += ls
    items = []
    for i in range(n_class):
        idx = struct.unpack_from(">I", raw, off)[0]
        assert idx == i, f"index mismatch at {i}: {idx}"
        off += 4
        fields = []
        for _ in range(3):
            ls = struct.unpack_from(">I", raw, off)[0]
            off += 4
            fields.append(raw[off:off + ls].decode("utf-8"))
            off += ls
        items.append({"i": i, "en": fields[0], "code": fields[1], "sci": fields[2]})
    if off != len(raw):
        raise ValueError(f"trailing bytes: consumed {off}/{len(raw)}")
    return items


# ---------- catalog_v2.bin (BTRCAT02) ----------
def parse_catalog(raw: bytes):
    if raw[:8] != b"BTRCAT02":
        raise ValueError("bad magic for catalog")
    ver, count, slen = struct.unpack_from(">III", raw, 8)
    off = 20
    content_ver = raw[off:off + slen].decode("utf-8")
    off += slen
    print(f"  catalog: version={ver} records={count} content={content_ver}")
    recs = []
    for i in range(count):
        sort_key = struct.unpack_from(">d", raw, off)[0]      # BE double 分类序
        flag = struct.unpack_from(">I", raw, off + 8)[0]      # u32 BE 标志
        country_count = raw[off + 12]                          # u8 国家数
        countries_len = struct.unpack_from(">I", raw, off + 13)[0]  # u32 BE 国家串长度
        off += 17
        fields = []
        for _ in range(21):
            ls = struct.unpack_from(">I", raw, off)[0]
            off += 4
            fields.append(raw[off:off + ls].decode("utf-8"))
            off += ls
        countries = [c for c in fields[6].split("|") if c]
        assert len(countries) == country_count, f"country count mismatch at rec {i}"
        recs.append({
            "tax_order": sort_key,
            "flag": flag,
            "code": fields[1],
            "sci": fields[2],
            "cn": fields[3],
            "en": fields[4],
            "habitat": fields[5],
            "countries": countries,
            "kingdom": [fields[8], fields[9]],
            "phylum": [fields[10], fields[11]],
            "class": [fields[12], fields[13]],
            "order": [fields[14], fields[15]],
            "family": [fields[16], fields[17]],
            "genus": [fields[18], fields[19]],
        })
    if off != len(raw):
        raise ValueError(f"trailing bytes: consumed {off}/{len(raw)}")
    return recs


def main():
    if not APK.exists():
        sys.exit(f"APK not found: {APK}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "models").mkdir(exist_ok=True)
    (OUT / "data").mkdir(exist_ok=True)

    z = zipfile.ZipFile(APK)

    def read(name: str) -> bytes:
        return z.read(name)

    def dump(name: str, dest: Path):
        dest.write_bytes(read(name))
        print(f"  {name} -> {dest.name} ({dest.stat().st_size:,} bytes)")

    # 1. 模型直接拷贝
    print("[1/5] models")
    dump("assets/recognition/BirdTraceRecognitionModel.onnx",
         OUT / "models" / "BirdTraceRecognitionModel.onnx")
    dump("assets/detection/BirdTraceBirdDetector_FP32.onnx",
         OUT / "models" / "BirdTraceBirdDetector_FP32.onnx")

    # 2. manifest 留档 (含SHA256与预处理说明)
    print("[2/5] manifests")
    manifest_text = read("assets/recognition/model_manifest.properties").decode("utf-8")
    (OUT / "data" / "model_manifest.properties").write_text(manifest_text, encoding="utf-8")
    print(manifest_text)
    # 校验识别模型SHA256
    for line in manifest_text.splitlines():
        if "sha256" in line.lower() and "=" in line:
            k, v = line.split("=", 1)
            if "artifact" in k or "model" in k or "weights" in k:
                actual = sha256(read("assets/recognition/BirdTraceRecognitionModel.onnx"))
                status = "OK" if actual.strip().lower() == v.strip().lower() else "MISMATCH!"
                print(f"  verify {k.strip()}={v.strip()[:16]}... [{status}]")

    # 3. 标签
    print("[3/5] class mapping -> labels.json")
    labels = parse_class_mapping(read("assets/recognition/class_mapping_v1.bin"))
    (OUT / "data" / "labels.json").write_text(
        json.dumps(labels, ensure_ascii=False, indent=None), encoding="utf-8")
    print(f"  {len(labels)} classes; first={labels[0]}; last={labels[-1]}")

    # 4. 图鉴
    print("[4/5] catalog -> species_catalog.json")
    catalog = parse_catalog(read("assets/birddex/catalog_v2.bin"))
    (OUT / "data" / "species_catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=None), encoding="utf-8")
    print(f"  {len(catalog)} species; e.g. {catalog[0]['code']} {catalog[0]['cn']} {catalog[0]['en']}")

    # 5. 地理先验 + 区域表 + IUCN保护等级 + 图鉴详情 + 文化库
    print("[5/7] geo prior + regions + iucn")
    dump("assets/geoprior/birdtrace_geo_prior_v1/BirdGeoPrior.sqlite",
         OUT / "data" / "geo_prior.sqlite")
    dump("assets/geoprior/birdtrace_geo_prior_v1/RecognitionRegions.json",
         OUT / "data" / "regions.json")
    iucn_raw = json.loads(read("assets/conservation/species_conservation_iucn_v1.json"))
    iucn_map = {e["speciesCode"]: e.get("iucnStatus", "")
                for e in iucn_raw.get("entries", [])}
    (OUT / "data" / "iucn_status.json").write_text(
        json.dumps(iucn_map, ensure_ascii=False), encoding="utf-8")
    print(f"  iucn_status.json: {len(iucn_map)} entries")

    # 6. 图鉴详情 (BTRDET02 + BTRIDX02, 解析器在 app/core/birddex.py)
    print("[6/7] birddex details")
    dump("assets/birddex/details_v2.btd", OUT / "data" / "details_v2.btd")
    dump("assets/birddex/details_index_v2.bin", OUT / "data" / "details_index_v2.bin")

    # 7. 文化知识库 (sqlite, 查询层在 app/core/culture.py)
    print("[7/7] bird culture")
    dump("assets/culture/BirdCulture.sqlite", OUT / "data" / "bird_culture.sqlite")

    print("DONE.")


if __name__ == "__main__":
    main()
