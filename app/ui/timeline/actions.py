# -*- coding: utf-8 -*-
"""时间线动作(c8): 批量分享卡/导出向导/查重/记录中心/静态站/「工具▾」菜单。"""
from __future__ import annotations

from PySide6.QtWidgets import QMenu, QPushButton

from ...i18n import t, sname
from ... import theme
from ...media import ensure_thumbnail
from ...theme.widgets import PhotoGridItem, grid_tile_of, ThemedDateEdit


class ActionsMixin:
    """ActionsMixin(c8自timeline_page纯搬家, 方法体零改动)。"""

    def _batch_share(self):
        """批量分享卡导出(0.8-⑥): 日期范围+可选鸟种 → 每鸟种一张最美。
        0.8.6: 默认日期=时间线当前选中节点(年/月/日), 没点过=今天。"""
        from ..batch_share_dialog import BatchShareDialog
        BatchShareDialog(self.lib, self.win,
                         preset=self._sel_date_range()).exec()

    def _export_wizard(self):
        """导出向导(0.8-④): 复制到新位置 / 原地重命名。"""
        from ..export_dialog import ExportDialog
        ExportDialog(self.lib, self.win).exec()

    def _open_dups(self):
        """视觉查重(1.0冲刺③): 两层候选+人工确认移除。"""
        from ..dup_dialog import DupDialog
        dlg = DupDialog(self.lib, self.win)
        dlg.exec()
        if dlg.result():
            self.refresh(force=True)

    def _open_birdreport(self):
        """观鸟记录中心导出(1.0冲刺④): CSV上报行+最美照归集。"""
        from ..birdreport_dialog import BirdReportDialog
        BirdReportDialog(self.lib, self.win).exec()

    def _open_site(self):
        """静态图库站(1.0冲刺⑩): 一键生成纯静态站。"""
        from PySide6.QtWidgets import QFileDialog, QProgressDialog
        dest = QFileDialog.getExistingDirectory(
            self, t("选择站点输出文件夹（建议空目录）",
                    "Choose output folder (empty recommended)"),
            str(Path.home() / "Pictures"))
        if not dest:
            return
        from ...core.static_site import build_site
        pd = QProgressDialog(t("正在生成站点…", "Building site…"),
                             t("取消", "Cancel"), 0, 0, self)
        pd.setWindowModality(Qt.WindowModal)
        pd.setMinimumDuration(300)
        try:
            res = build_site(self.lib, Path(dest))
        except Exception as e:
            pd.cancel()
            QMessageBox.warning(self, t("生成失败", "Build failed"), str(e))
            return
        pd.cancel()
        QMessageBox.information(
            self, t("静态站已生成", "Site built"),
            t(f"已生成 {res['species']} 个鸟种 / {res['thumb']} 张缩略图 到\n"
              f"{res['dest']}\n\n把该文件夹拖到 Cloudflare Pages（免费）"
              "即可上线；index.html 双击本地也能看。",
              f"Built {res['species']} species / {res['thumb']} thumbs at\n"
              f"{res['dest']}\n\nDrag the folder to Cloudflare Pages to "
              "publish; index.html also opens locally."))

    # ---------- 标签/作品集(1.0冲刺⑭⑮) ----------

    def _build_tools_button(self):
        """「工具 ▾」(UI重设计c8): 低频工具降级收纳——导出/查重/
        记录中心/静态站收进菜单, 头部只留高频(选择/批量分享/连拍折叠/档位)。"""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QToolButton
        btn = QToolButton()
        btn.setText(t("工具 ▾", "Tools ▾"))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(btn)
        a_exp = m.addAction(t("导出…", "Export…"))
        a_exp.setToolTip(t("按范围/方式批量导出或原地重命名",
                           "Batch export or rename in place by range/mode"))
        a_dup = m.addAction(t("查重…", "Find duplicates…"))
        a_dup.setToolTip(t(
            "找重复/相似照片候选：完全相同文件（跨月）+画面相似（同月）；"
            "是否移除由你逐组确认",
            "Find duplicate/similar photo candidates (identical files "
            "across months + visually similar within a month); you confirm "
            "each group before removing"))
        a_rep = m.addAction(t("记录中心…", "Bird report…"))
        a_rep.setToolTip(t(
            "按观鸟记录中心(birdreport.cn)导入思路导出上报行 CSV，"
            "并归集每鸟种最美照配合上传",
            "Export report rows as CSV for birdreport.cn-style upload, "
            "plus one best photo per species"))
        a_site = m.addAction(t("静态站…", "Static site…"))
        a_site.setToolTip(t(
            "一键生成纯静态图库站（手机优先/深浅跟随系统/鸟种·时间·地区"
            "三视图）——鸟点名与坐标绝不进站点数据，原图绝不出库",
            "Generate a static gallery site (mobile-first, three views); "
            "spot names/coordinates never included, originals never "
            "exported"))
        a_exp.triggered.connect(self._export_wizard)
        a_dup.triggered.connect(self._open_dups)
        a_rep.triggered.connect(self._open_birdreport)
        a_site.triggered.connect(self._open_site)
        btn.setMenu(m)
        return btn
