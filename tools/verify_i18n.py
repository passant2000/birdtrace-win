# -*- coding: utf-8 -*-
"""双语完整性验证: EN模式下逐页/逐对话框扫描全部可见文案, 不允许残留中文。

覆盖: 主窗口全部页面(含地图页stub) + 5个对话框; 每模块EN截图存
data/ui_shots/i18n_en_*.png 供人工复核。数据内容(图鉴正文/文化故事/
物种中文名)不在扫描范围——按设计保持原样。

用法: .venv/Scripts/python.exe tools/verify_i18n.py
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

LIB_DIR = PROJ / "data/i18n_check"
FAILED = {"v": False}
ZH = re.compile(r"[\u4e00-\u9fff]")
# 有意保留中文的白名单(双语标签/语言选项/数据样本)
WHITELIST = ("语言 Language", "Language 语言", "中文")


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def data_strings(lib) -> list[str]:
    """库内数据字符串(鸟点名/科中文名/文化故事开头)——EN模式按设计保留原样。"""
    out = []
    for s in lib.spots_overview():
        if s["name"]:
            out.append(s["name"])
    for r in lib.conn.execute(
            "SELECT DISTINCT family_cn FROM species "
            "WHERE family_cn IS NOT NULL AND family_cn != ''"):
        out.append(r["family_cn"])
    try:
        # 全量文化故事(每日一鸟横幅的鸟种不限本库)
        import sqlite3
        db = __import__("sqlite3").connect(
            __import__("pathlib").Path(__file__).resolve().parent.parent
            / "assets" / "data" / "bird_culture.sqlite")
        for r in db.execute(
                "SELECT title, body, summary, short_summary FROM localized_text WHERE language='zh-Hans'"):
            if r[0]:
                out.append(r[0][:10])
        db.close()
    except Exception:
        pass
    return out


def collect_texts(root, skip_lists: bool = False) -> list[str]:
    """递归收集一个widget树里所有用户可见文案。"""
    from PySide6.QtWidgets import (QComboBox, QDialog, QGroupBox, QLabel,
                                   QLineEdit, QListWidget, QPushButton,
                                   QTabWidget, QWidget)
    texts: list[str] = []

    def add(s: str):
        if s and s.strip():
            texts.append(s.strip())

    widgets = [root] + root.findChildren(QWidget)
    for w in widgets:
        try:
            if isinstance(w, (QDialog, QWidget)) and w is not root:
                add(w.windowTitle())
            if isinstance(w, QLabel):
                add(w.text())
            elif isinstance(w, QPushButton):
                add(w.text())
                add(w.toolTip() or "")
            elif isinstance(w, QLineEdit):
                add(w.placeholderText() or "")
            elif isinstance(w, QComboBox):
                for i in range(w.count()):
                    add(w.itemText(i))
            elif isinstance(w, QListWidget) and not skip_lists:
                for i in range(w.count()):
                    add(w.item(i).text())
            elif isinstance(w, QGroupBox):
                add(w.title())
            elif isinstance(w, QTabWidget):
                for i in range(w.count()):
                    add(w.tabText(i))
        except RuntimeError:
            continue
    return texts


def zh_residue(texts: list[str], data: list[str] | None = None) -> list[str]:
    data = data or []
    out = []
    for s in texts:
        if not ZH.search(s) or s in WHITELIST:
            continue
        if any(d in s for d in data):   # 库内数据(鸟点名/科名/文化故事)按设计保留
            continue
        out.append(s)
    return out


def main():
    if LIB_DIR.exists():
        shutil.rmtree(LIB_DIR)

    from PIL import Image
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    from app import theme
    theme.apply_theme(app, "light")
    from app import i18n
    from app.db import Library
    from app.core.importer import import_files
    from app.ai.pipeline import RecognitionPipeline, load_rgb
    from app.exif import month_of

    # ---- 测试库: 10张(3种) + 识别 + 美学分 + 鸟点 ----
    src = PROJ / "data/i18n_src"
    if src.exists():
        shutil.rmtree(src)
    src.mkdir()
    base = Image.open(PROJ / "data/test_images/Anas_platyrhynchos.jpg").copy()
    px = base.load()
    for i in range(8):
        px[0, 0] = ((i * 37) % 256, (i * 91) % 256, (i * 151) % 256)
        base.save(src / f"鸭{i}.jpg", quality=92)
    shutil.copy2(PROJ / "data/test_images/Alcedo_atthis.jpg", src / "翠鸟.jpg")
    shutil.copy2(PROJ / "data/test_images/Upupa_epops.jpg", src / "戴胜.jpg")
    lib = Library(LIB_DIR)
    lib.fill_species()
    import_files(lib, sorted(src.glob("*.jpg")), mode="ref", dest_root=None,
                 region_id="CN")
    pipe = RecognitionPipeline(
        detector_path=str(PROJ / "assets/models/BirdTraceBirdDetector_FP32.onnx"),
        classifier_path=str(PROJ / "assets/models/BirdTraceRecognitionModel.onnx"),
        labels_path=str(PROJ / "assets/data/labels.json"),
        geo_prior_path=str(PROJ / "assets/data/geo_prior.sqlite"))
    for pid in lib.pending_photo_ids():
        photo, _ = lib.photo_detail(pid)
        lib.add_records(pid, pipe.recognize(
            load_rgb(photo["path"]), lib.region_for_photo(pid),
            month_of(photo.get("dt_original"), 5)))
    pipe.close()
    for i, pid in enumerate([r["id"] for r in lib.conn.execute(
            "SELECT id FROM photos ORDER BY id")]):
        lib.set_aesthetic(pid, 5.0 + i * 0.3)
    lib.conn.commit()
    sid = lib.create_spot("奥林匹克森林公园", 40.002, 116.39, "测试")
    lib.set_photo_spot(1, sid)
    lib.set_setting("default_region", "CN-BJ")   # 图鉴页当月/罕见度徽章+热力表pin行需要
    print(f"测试库就绪: 10张/3种/1鸟点")

    lib_data = data_strings(lib)
    shots = PROJ / "data/ui_shots"
    shots.mkdir(exist_ok=True)
    residues: dict[str, list[str]] = {}

    for lang in ("zh", "en"):
        print(f"\n===== 语言: {lang} =====")
        i18n.set_lang(lang)
        # 主窗口(真实构造, 含全部页面)
        from app.ui.main_window import MainWindow
        win = MainWindow(lib, PROJ / "assets")
        win.resize(1280, 840)
        win.show()
        app.processEvents()
        page_keys = [k for k in ("timeline", "import", "species", "review",
                                 "stats", "settings", "about")
                     if win.pages.get(k) is not None]
        for k in page_keys:
            page = win.pages[k]
            texts = collect_texts(page)
            bad = zh_residue(texts, lib_data) if lang == "en" else []
            residues[f"{lang}:{k}"] = bad
            check(not bad, f"页面[{k}] " + ("无中文残留" if not bad
                                            else f"残留: {bad[:4]}"))
            page.grab().save(str(shots / f"i18n_{lang}_{k}.png"))
        # 鸟种详情(概览页; 图鉴/文化是中文数据, 不扫)
        code = max(lib.species_overview(), key=lambda s: s["n"])["code"]
        win.pages["species"]._open_detail(code)
        app.processEvents()
        texts = collect_texts(win.pages["species"])
        bad = zh_residue(texts, lib_data) if lang == "en" else []
        residues[f"{lang}:species_detail"] = bad
        check(not bad, "页面[species详情] " + ("无中文残留" if not bad
                                              else f"残留: {bad[:4]}"))
        win.pages["species"].grab().save(str(shots / f"i18n_{lang}_species_detail.png"))

        # 图鉴标签页(全年分布热力表/最美照片/徽章): 正文属数据内容不翻译,
        # 把该种图鉴字段按渲染变换(- → •, \n → <br>)计入豁免后整页扫
        from app.core.birddex import get_dex
        from app.ui.species_page import DEX_FIELDS
        d = get_dex().detail(lib.species_info(code)["sci"])
        dex_data = []
        if d:
            for key, _zl, _el in DEX_FIELDS:
                zh = d[key]["zh"]
                if not zh:
                    continue
                text = zh.replace("\n- ", "\n• ").replace("- ", "• ", 1) \
                    if zh.startswith("- ") else zh.replace("\n- ", "\n• ")
                dex_data.append(text.replace("\n", "<br>"))
        win.pages["species"]._tab_changed(1)
        app.processEvents()
        texts = collect_texts(win.pages["species"])
        bad = zh_residue(texts, lib_data + dex_data) if lang == "en" else []
        residues[f"{lang}:species_dex"] = bad
        check(not bad, "页面[species图鉴] " + ("无中文残留" if not bad
                                              else f"残留: {bad[:4]}"))
        win.pages["species"].grab().save(str(shots / f"i18n_{lang}_species_dex.png"))
        win.pages["species"]._tab_changed(0)   # 还原概览, 不影响后续流程
        app.processEvents()

        # 地图页(WebEngine stub, 避免拉起真实引擎)
        import app.ui.amap_view as amv

        class _StubAmap(QWidget):
            from PySide6.QtCore import Signal as _S
            spot_clicked = _S(dict)
            center_moved = _S(float, float, float)
            picked_wgs84 = _S(float, float)
            _center_state = (35.0, 105.0, 4.0)

            def __init__(self, lib_, parent=None):
                super().__init__(parent)

            def ensure_keys(self):
                return False

            def set_spots(self, *a, **k):
                pass

            def focus_wgs84(self, *a, **k):
                pass

            def fit_wgs84(self, *a, **k):
                pass

            def set_pick(self, on):
                pass

        real_amap = amv.AmapView
        amv.AmapView = _StubAmap
        try:
            from app.ui.map_page import MapPage
            mp = MapPage(lib, win)
            mp.resize(1280, 840)
            mp.show()
            app.processEvents()
            mp._show_popup(sid)
            app.processEvents()
            texts = collect_texts(mp)
            bad = zh_residue(texts, lib_data) if lang == "en" else []
            residues[f"{lang}:map"] = bad
            check(not bad, "页面[map+弹卡] " + ("无中文残留" if not bad
                                               else f"残留: {bad[:4]}"))
            mp.grab().save(str(shots / f"i18n_{lang}_map.png"))

            # 对话框们
            from app.ui.report_dialog import YearlyReportDialog
            from app.ui.share_dialog import ShareDialog
            from app.ui.rebox_dialog import ReboxDialog
            from app.ui.spot_dialog import SpotPickDialog, BatchSpotDialog
            dlgs = []
            try:
                dlgs.append(("report", YearlyReportDialog(lib, win)))
            except Exception as e:
                check(False, f"年度报告可构造 ({e})")
            try:
                dlgs.append(("share", ShareDialog(lib, win, 1)))
            except Exception as e:
                check(False, f"分享卡可构造 ({e})")
            try:
                dlgs.append(("rebox", ReboxDialog(lib, win, 1)))
            except Exception as e:
                check(False, f"画框识别可构造 ({e})")
            try:
                photo0, _ = lib.photo_detail(1)
                dlgs.append(("spotpick", SpotPickDialog(lib, photo0)))
            except Exception as e:
                check(False, f"挂点对话框可构造 ({e})")
            try:
                dlgs.append(("batchspot",
                             BatchSpotDialog(lib, win, [1, 2])))
            except Exception as e:
                check(False, f"批量挂点可构造 ({e})")
            try:
                from app.ui.species_pick import SpeciesPickDialog
                dlgs.append(("speciespick", SpeciesPickDialog(lib)))
            except Exception as e:
                check(False, f"选鸟种对话框可构造 ({e})")
            try:
                from app.ui.distribution_map import DistributionMapDialog
                # 只构造+扫Qt侧文案(标题/说明), WebEngine内容不参与扫描
                dlgs.append(("distributionmap",
                             DistributionMapDialog(lib, win, code)))
            except Exception as e:
                check(False, f"分布地图对话框可构造 ({e})")
            try:
                from PySide6.QtCore import QThread, Signal
                from app.ui import migration_view as mv
                # 惰性worker桩: 构造即下载(目录2.7MB+包96MB)且离线会误报,
                # i18n只扫Qt侧文案, 用不启动的桩替换
                class _StubWorker(QThread):
                    progress = Signal(str, int, int)
                    decoded = Signal(dict, dict)
                    failed = Signal(object)

                    def __init__(self, *a, **kw):
                        super().__init__()

                    def start(self, *a):
                        pass
                real_worker = mv._DownloadWorker
                mv._DownloadWorker = _StubWorker
                try:
                    dlgs.append(("migrationmap",
                                 mv.MigrationMapDialog(lib, win, code)))
                finally:
                    mv._DownloadWorker = real_worker
            except Exception as e:
                check(False, f"迁徙地图对话框可构造 ({e})")
            try:
                # 临时识别: 构造不拉起worker(懒加载), 直接构造
                from app.ui.temp_id_dialog import TempIdDialog

                class _W:            # win桩(只取assets, 非QWidget不传父)
                    assets = __import__("pathlib").Path(
                        __import__("app.paths", fromlist=["assets_dir"])
                        .assets_dir())
                dlgs.append(("tempid", TempIdDialog(lib, _W())))
            except Exception as e:
                check(False, f"临时识别对话框可构造 ({e})")
            for name, d in dlgs:
                d.resize(900, 640)
                d.show()
                app.processEvents()
                texts = collect_texts(d, skip_lists=(name == "speciespick"))
                bad = zh_residue(texts, lib_data) if lang == "en" else []
                residues[f"{lang}:{name}"] = bad
                check(not bad, f"对话框[{name}] " + ("无中文残留" if not bad
                                                     else f"残留: {bad[:4]}"))
                d.grab().save(str(shots / f"i18n_{lang}_{name}.png"))
                d.close()
                d.deleteLater()
            mp.close()
            mp.deleteLater()
        finally:
            amv.AmapView = real_amap

        win.close()
        win.deleteLater()
        app.processEvents()

    # 报告长图两种语言都能渲染
    i18n.set_lang("en")
    from app.ui.report_dialog import YearlyReportDialog
    d = YearlyReportDialog(lib, None)
    pm = d._render_poster()
    check(not pm.isNull(), "EN长图渲染成功")
    pm.save(str(shots / "i18n_en_report_poster.png"))
    i18n.set_lang("zh")

    print()
    shutil.rmtree(src, ignore_errors=True)
    if FAILED["v"]:
        for k, v in residues.items():
            if v:
                print(f"残留 {k}: {v}")
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
