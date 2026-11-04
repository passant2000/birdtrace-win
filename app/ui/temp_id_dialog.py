# -*- coding: utf-8 -*-
"""临时识别: 不导入库, 对剪贴板截图/任选图片直接识别看结果。

与库内识别同一条链路(检测→裁剪→分类→先验重排, 子进程 --recognize-worker,
CPU推理与查看器画框识别同款), 但结果只在本对话框展示, 绝不写 photos/records。
入口: 导入页来源卡「临时识别…」。
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QProcess
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from .. import theme
from ..i18n import t, sname

_PREVIEW_H = 400

# 相机RAW格式(rawpy/LibRaw解码): 索尼/佳能/尼康/富士/奥巴/松下/宾得/三星/DNG
_RAW_EXTS = (".arw", ".cr2", ".cr3", ".nef", ".raf", ".orf", ".rw2",
             ".dng", ".pef", ".srw")


class TempIdDialog(QDialog):
    """临时识别对话框(非模态打开也可)。"""

    def __init__(self, lib, win, parent=None):
        # parent可能为None(win非QWidget场景如测试); win只用于取assets
        super().__init__(parent if isinstance(parent, QWidget) else None)
        self.lib = lib
        self.win = win
        self._proc: QProcess | None = None
        self._buf = ""
        self._pid = 0
        self._pending_pix: QPixmap | None = None
        self._pending_line: bytes | None = None
        self._tmp_dir = Path(tempfile.gettempdir()) / "birdtrace_tmpid"
        self._tmp_dir.mkdir(exist_ok=True)

        self.setWindowTitle(t("临时识别", "Quick ID"))
        self.resize(860, 640)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 12)
        v.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(8)
        b_clip = QPushButton(t("📋 粘贴截图", "📋 Paste screenshot"))
        b_clip.setCursor(Qt.PointingHandCursor)
        b_clip.clicked.connect(self._paste_clipboard)
        row.addWidget(b_clip)
        b_file = QPushButton(t("🖼️ 选择图片…", "🖼️ Choose image…"))
        b_file.setCursor(Qt.PointingHandCursor)
        b_file.clicked.connect(self._pick_file)
        row.addWidget(b_file)
        self.status = QLabel(t(
            "截图后点粘贴，或选择/拖入图片——支持 JPG/PNG/WebP 和相机 RAW"
            "（ARW/CR2/CR3/NEF/RAF/ORF/RW2/DNG/PEF/SRW）——识别不保存到照片库",
            "Take a screenshot then paste, or choose / drop an image — "
            "JPG/PNG/WebP and camera RAW (ARW/CR2/CR3/NEF/RAF/ORF/RW2/DNG/"
            "PEF/SRW) supported — results are not saved to the library"))
        self.status.setStyleSheet(f"color:{theme.LABEL_3};font-size:12px;"
                                  "background:transparent;")
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        v.addLayout(row)

        self.preview = QLabel(t("（还没有图片）", "(no image yet)"))
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(_PREVIEW_H)
        self.preview.setStyleSheet(
            f"background:{theme.CHIP_BG};border-radius:10px;color:{theme.LABEL_3};")
        v.addWidget(self.preview, 1)

        self.results = QLabel("")
        self.results.setWordWrap(True)
        self.results.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.results.setStyleSheet("background:transparent;")
        v.addWidget(self.results)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        b_close = QPushButton(t("关闭", "Close"))
        b_close.setCursor(Qt.PointingHandCursor)
        b_close.clicked.connect(self.close)
        close_row.addWidget(b_close)
        v.addLayout(close_row)

        self.setAcceptDrops(True)

    # ---- 图片来源 ----
    def _paste_clipboard(self):
        img = QGuiApplication.clipboard().image()
        if img.isNull():
            self.status.setText(t(
                "剪贴板里没有图片——请先用截图工具截图（如 Win+Shift+S）",
                "No image in the clipboard — take a screenshot first "
                "(e.g. Win+Shift+S)"))
            return
        path = self._tmp_dir / "clipboard.jpg"
        img.save(str(path), "JPG", 92)
        self._recognize_file(path)

    def _pick_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, t("选择图片", "Choose image"), "",
            t("图片文件 (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff "
              "*.arw *.cr2 *.cr3 *.nef *.raf *.orf *.rw2 *.dng *.pef *.srw)",
              "Images (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff "
              "*.arw *.cr2 *.cr3 *.nef *.raf *.orf *.rw2 *.dng *.pef *.srw)"))
        if path:
            self._recognize_file(Path(path))

    def dragEnterEvent(self, ev):
        urls = ev.mimeData().urls() if ev.mimeData() else []
        if urls and urls[0].toLocalFile().lower().endswith(
                (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")
                + _RAW_EXTS):
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        p = ev.mimeData().urls()[0].toLocalFile()
        self._recognize_file(Path(p))

    def _decode_raw(self, path: Path) -> Path | None:
        """相机RAW → 临时JPG(rawpy/LibRaw解码, camera白平衡, 半尺寸省内存)。"""
        import rawpy
        try:
            with rawpy.imread(str(path)) as rw:
                rgb = rw.postprocess(use_camera_wb=True, half_size=True)
        except rawpy.LibRawFileUnsupportedError:
            # 压缩档位上游LibRaw不支持(如尼康Z8/Z9「高效RAW HE/HE*」):
            # 元数据能读、像素解不开。兜底=FastStone同款思路, 抠相机内嵌的
            # 全尺寸JPEG走识别(相机自己渲染的, 识别足够); 抠不出才报人话。
            emb = self._extract_embedded_jpeg(path)
            if emb is not None:
                return emb
            self.status.setText(t(
                "RAW 解码失败：该压缩格式内置解码器暂不支持，也未找到"
                "内嵌预览（如尼康「高效RAW HE/HE*」等新格式）。可导出JPG后"
                "识别，或用Adobe DNG Converter转成DNG再试。",
                "RAW decode failed: this compression variant isn't "
                "supported by the built-in decoder and no embedded preview "
                "was found (e.g. Nikon High-Efficiency HE/HE* NEF). Export "
                "a JPG, or convert to DNG with Adobe DNG Converter and try "
                "again."))
            return None
        except Exception as e:
            self.status.setText(t(
                f"RAW 解码失败：{str(e)[:120]}",
                f"RAW decode failed: {str(e)[:120]}"))
            return None
        from PIL import Image
        out = self._tmp_dir / (path.stem + "_raw.jpg")
        Image.fromarray(rgb).save(str(out), "JPEG", quality=92)
        return out

    def _extract_embedded_jpeg(self, path: Path) -> Path | None:
        """TIFF系RAW抠出相机内嵌的最大JPEG(FastStone同款思路)。

        NEF/ARW/CR2/RAF/ORF/RW2等都是TIFF容器, 内嵌相机自己渲染的JPEG预览
        (NEF含全尺寸约5MB)—— LibRaw追不上的新压缩档(尼康HE等)照样有预览可
        用。CR3(ISO-BMFF容器)不适用, 但LibRaw本就支持CR3, 走不到这里。
        成功返回临时JPG路径; 非TIFF/无内嵌JPEG/解析异常返回None。"""
        import struct
        try:
            data = path.read_bytes()
            if data[:2] not in (b"II", b"MM"):
                return None
            bo = "<" if data[:2] == b"II" else ">"

            def parse_ifd(off):
                n = struct.unpack_from(bo + "H", data, off)[0]
                ent = {}
                for i in range(n):
                    e = off + 2 + i * 12
                    tag, typ, cnt = struct.unpack_from(bo + "HHI", data, e)
                    nb = cnt * {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1,
                                9: 4, 10: 8, 13: 4}.get(typ, 1)
                    if nb <= 4:
                        raw = data[e + 8:e + 8 + nb]
                    else:
                        o = struct.unpack_from(bo + "I", data, e + 8)[0]
                        raw = data[o:o + nb]
                    if typ in (3, 8):
                        vals = list(struct.unpack_from(bo + str(cnt) + "H",
                                                       raw))
                    elif typ in (4, 9, 13):
                        vals = list(struct.unpack_from(bo + str(cnt) + "I",
                                                       raw))
                    else:
                        vals = raw
                    ent[tag] = (typ, cnt, vals)
                nxt = struct.unpack_from(bo + "I", data, off + 2 + n * 12)[0]
                return ent, nxt

            def embedded_blob(ent):
                jif = ent.get(513, (0, 0, [0]))[2]
                jifl = ent.get(514, (0, 0, [0]))[2]
                if jif and jifl:
                    blob = data[jif[0]:jif[0] + jifl[0]]
                    if blob[:2] == b"\xff\xd8":
                        return blob
                so = ent.get(273, (0, 0, []))[2]
                sbc = ent.get(279, (0, 0, []))[2]
                if so and sbc and len(so) == len(sbc):
                    blob = b"".join(data[a:a + b] for a, b in zip(so, sbc))
                    if blob[:2] == b"\xff\xd8":
                        return blob
                return None

            best = None
            seen = set()
            pending = [struct.unpack_from(bo + "I", data, 4)[0]]
            while pending:
                off = pending.pop(0)
                if not off or off in seen:
                    continue
                seen.add(off)
                ent, nxt = parse_ifd(off)
                blob = embedded_blob(ent)
                if blob and (best is None or len(blob) > len(best)):
                    best = blob
                pending.append(nxt)
                pending.extend(ent.get(0x14A, (0, 0, []))[2])   # SubIFDs
            if not best:
                return None
            out = self._tmp_dir / (path.stem + "_emb.jpg")
            out.write_bytes(best)
            return out
        except Exception:
            return None

    # ---- 识别(QProcess常驻worker, 协议同库内识别) ----
    def _recognize_file(self, path: Path):
        if path.suffix.lower() in _RAW_EXTS:
            from PySide6.QtWidgets import QApplication
            self.status.setText(t(
                f"RAW 解码中: {path.name}", f"Decoding RAW: {path.name}"))
            QApplication.processEvents()   # 解码1~3秒, 先把状态画出来
            converted = self._decode_raw(path)
            if converted is None:
                return
            path = converted
        if not self._ensure_proc():
            self.status.setText(t(
                "识别组件不可用(缺少模型资产)", "Recognition unavailable "
                "(model assets missing)"))
            return
        self._pid += 1
        self._pending_pix = QPixmap(str(path))
        self._show_preview([])
        self.results.setText(t("识别中…", "Recognizing…"))
        self.status.setText(t(f"识别中: {path.name}", f"Recognizing: {path.name}"))
        region = self.lib.get_setting("default_region", "GLOBAL") or ""
        if region == "GLOBAL":
            region = ""
        line = f"{self._pid}\t{path}\t{region}\t\n".encode("utf-8")
        if self._proc.state() == QProcess.Starting:
            # 刚start还没起来: 直接write可能被丢, 挂到started信号再发
            self._pending_line = line
        else:
            self._proc.write(line)

    def _flush_pending(self):
        if self._pending_line is not None and self._proc is not None:
            self._proc.write(self._pending_line)
            self._pending_line = None

    def _ensure_proc(self) -> bool:
        if self._proc is not None:
            return self._proc.state() != QProcess.NotRunning
        from ..ai.recognize_sub import build_worker_cmd
        assets = getattr(self.win, "assets", None)
        if assets is None:
            return False
        cmd, cwd = build_worker_cmd(
            str(assets), self.lib.get_setting("detect_conf", "0.25"),
            use_gpu=False)
        p = QProcess(self)
        p.setProgram(cmd[0])
        p.setArguments(cmd[1:])
        if cwd:
            p.setWorkingDirectory(cwd)
        p.readyReadStandardOutput.connect(self._on_proc_out)
        p.started.connect(self._flush_pending)
        p.start()
        self._proc = p
        return True

    def _on_proc_out(self):
        if self._proc is None:
            return
        self._buf += bytes(self._proc.readAllStandardOutput()) \
            .decode("utf-8", "replace")
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.strip()
            if not line.startswith("{"):
                continue    # EP告警等杂线
            try:
                res = json.loads(line)
            except ValueError:
                continue
            if int(res.get("pid", -1)) != self._pid:
                continue    # 过期结果
            self._apply(res)

    def _apply(self, res: dict):
        if not res.get("ok"):
            self.results.setText(t("识别失败：", "Recognition failed: ")
                                 + str(res.get("error", ""))[:160])
            return
        recs = res.get("records") or []
        if not recs:
            self.results.setText(t(
                "画面里没认出鸟（可能没有鸟，或鸟太小/被遮挡）",
                "No bird recognized (none in frame, or too small/occluded)"))
            self._show_preview([])
            return
        self._show_preview(recs)
        lines = [t(f"识别到 {len(recs)} 只鸟：", f"{len(recs)} bird(s):")]
        for i, rec in enumerate(recs, 1):
            code = rec.get("species_code", "")
            name = code
            try:
                info = self.lib.species_info(code)
                if info:
                    name = sname(info["cn"], info["en"])
            except Exception:
                pass
            # top5元素是dict(code/en/sci/prob/rank)——槽内取值失败会被
            # PySide静默吞掉, 症状=永远停在"识别中", 取值必须防御
            alts = []
            for a in (rec.get("top5") or [])[1:3]:
                if isinstance(a, dict):
                    alts.append((a.get("en") or a.get("code") or "")
                                .replace("_", " "))
                elif isinstance(a, (list, tuple)) and len(a) >= 2:
                    alts.append(str(a[1]).replace("_", " "))
            alt = " · ".join(x for x in alts if x)
            pct = int(round(rec.get("confidence", 0) * 100))
            lines.append(t(
                f"#{i} {name} — {pct}%" + (f"　(次选: {alt})" if alt else ""),
                f"#{i} {name} — {pct}%" + (f"  (next: {alt})" if alt else "")))
        self.results.setText("\n".join(lines))
        self.status.setText(t("完成（未保存到照片库）",
                              "Done (not saved to the library)"))

    # ---- 预览(带检测框) ----
    def _show_preview(self, recs: list):
        if self._pending_pix is None or self._pending_pix.isNull():
            return
        pm = self._pending_pix.copy()
        if recs:
            p = QPainter(pm)
            pen = QPen(QColor("#E5484D"), max(2, pm.width() // 400))
            p.setPen(pen)
            for rec in recs:
                box = rec.get("box")
                if box and len(box) == 4:
                    p.drawRect(int(box[0]), int(box[1]),
                               int(box[2] - box[0]), int(box[3] - box[1]))
            p.end()
        scaled = pm.scaled(self.preview.width() - 16, _PREVIEW_H - 12,
                           Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview.setPixmap(scaled)

    def closeEvent(self, ev):
        if self._proc is not None:
            self._proc.kill()
            self._proc.waitForFinished(1500)
        super().closeEvent(ev)
