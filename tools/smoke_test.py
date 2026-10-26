# -*- coding: utf-8 -*-
"""M0 冒烟测试: 用已知鸟种照片验证 检测->识别->先验重排 全链路,
并对比三种384预处理策略确定默认值。

用法:
  python tools/smoke_test.py            # 已有测试图则直接跑
  python tools/smoke_test.py --download # 先从iNaturalist下载测试图(CC授权)
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

ASSETS = PROJ / "assets"
TEST_DIR = PROJ / "data" / "test_images"

UA = {"User-Agent": "birdtrace-win-smoke/0.1 (asset smoke test)"}
# (学名, 中文期待名) — 均为极常见鸟种, 必在10480类内
CASES = [
    ("Alcedo atthis", "普通翠鸟"),
    ("Cyanistes caeruleus", "蓝山雀"),
    ("Passer montanus", "树麻雀"),
    ("Anas platyrhynchos", "绿头鸭"),
    ("Ardea cinerea", "苍鹭"),
    ("Upupa epops", "戴胜"),
]
STRATEGIES = ["squash", "center384", "center448"]


def _get_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _download(url: str, dest: Path):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        f.write(r.read())


def download_tests():
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    for sci, _ in CASES:
        slug = sci.replace(" ", "_")
        dest = TEST_DIR / f"{slug}.jpg"
        if dest.exists() and dest.stat().st_size > 10_000:
            print(f"  skip {sci}")
            continue
        q = urllib.parse.quote(sci)
        meta = _get_json(f"https://api.inaturalist.org/v1/taxa?q={q}&rank=species")
        results = meta.get("results", [])
        exact = [t for t in results if t.get("name", "").lower() == sci.lower()] or results
        if not exact:
            print(f"  !! no taxon found for {sci}")
            continue
        photo = (exact[0].get("default_photo") or {})
        url = photo.get("medium_url") or photo.get("url") or ""
        # 优先 open-data S3 图床(可达且CC授权); 并取大图
        url = url.replace("/square.", "/large.").replace("/small.", "/large.").replace("/medium.", "/large.")
        if not url:
            print(f"  !! no photo for {sci}")
            continue
        print(f"  {sci}: {url}")
        try:
            _download(url, dest)
        except Exception as e:  # 换一张
            print(f"    failed ({e}), trying next taxon photo...")
            continue
        print(f"    saved {dest.stat().st_size:,} bytes -> {dest.name}")


def find_code(labels: list[dict], sci: str) -> str | None:
    for lab in labels:
        if lab["sci"].lower() == sci.lower():
            return lab["code"]
    return None


def main():
    if "--download" in sys.argv:
        print("[download test images from iNaturalist]")
        download_tests()

    from app.ai.pipeline import RecognitionPipeline, load_rgb

    labels = json.loads((ASSETS / "data" / "labels.json").read_text(encoding="utf-8"))
    truth = {}
    for sci, cn in CASES:
        code = find_code(labels, sci)
        truth[slug_of(sci)] = (sci, cn, code)
        print(f"  ground truth: {sci} -> {code} ({cn})")

    print("\n[load pipeline]")
    t0 = time.time()
    pipe = RecognitionPipeline(
        detector_path=str(ASSETS / "models" / "BirdTraceBirdDetector_FP32.onnx"),
        classifier_path=str(ASSETS / "models" / "BirdTraceRecognitionModel.onnx"),
        labels_path=str(ASSETS / "data" / "labels.json"),
        geo_prior_path=str(ASSETS / "data" / "geo_prior.sqlite"),
        use_gpu=True,
    )
    print(f"  loaded in {time.time()-t0:.1f}s")
    print("  providers:", pipe.detector.session.get_providers())

    images = sorted(p for p in TEST_DIR.glob("*.jpg") if p.stat().st_size > 10_000)
    if not images:
        sys.exit("no test images; run with --download first")

    summary = {}
    for strat in STRATEGIES:
        print(f"\n===== strategy: {strat} =====")
        pipe.strategy = strat
        hits = []
        for img_path in images:
            slug = img_path.stem
            sci, cn, exp_code = truth[slug]
            img = load_rgb(str(img_path))
            t0 = time.time()
            recs = pipe.recognize(img, region_id="CN", month=5)
            dt = time.time() - t0
            top1 = recs[0]["top5"][0] if recs else None
            hit = next((t["rank"] for t in recs[0]["top5"] if t["code"] == exp_code),
                       None) if recs else None
            hits.append(hit or 99)
            print(f"  {slug}: dets={len(recs)} {dt*1000:.0f}ms | top1={top1['code']} "
                  f"{top1['prob']:.3f} | 期待({exp_code})top5位次={hit}")
            for t in recs[0]["top5"][:3]:
                print(f"      {t['rank']}. {t['code']:10s} {t['en'][:38]:38s} {t['prob']:.3f}")
        summary[strat] = hits

    print("\n===== 汇总(位次越小越好) =====")
    for strat, hits in summary.items():
        print(f"  {strat:10s}: {hits}")
    pipe.close()
    print("SMOKE TEST DONE.")


def slug_of(sci: str) -> str:
    return sci.replace(" ", "_")


if __name__ == "__main__":
    main()
