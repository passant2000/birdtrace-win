# -*- coding: utf-8 -*-
"""时间线筛选(c8): 六维下拉(评分/选片/标签/作品集/鸟点/置信)+鸟种胶囊+
组合过滤逻辑(自refresh切出)。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from ...i18n import t, sname
from ... import theme
from ...media import ensure_thumbnail
from ...theme.widgets import PhotoGridItem, grid_tile_of, ThemedDateEdit


class FiltersMixin:
    """FiltersMixin(c8自timeline_page纯搬家, 方法体零改动)。"""

    def _refresh_tag_filter(self):
        """标签下拉重填(保留当前选中; refresh 前调用)。"""
        cur = self.tag_filter.currentData()
        self.tag_filter.blockSignals(True)
        self.tag_filter.clear()
        self.tag_filter.addItem(t("标签: 全部", "Tags: all"), None)
        for tg in self.lib.tags_list():
            self.tag_filter.addItem(f"{tg['name']} ({tg['n']})", tg["id"])
        idx = self.tag_filter.findData(cur)
        self.tag_filter.setCurrentIndex(idx if idx >= 0 else 0)
        self.tag_filter.blockSignals(False)

    def _refresh_col_filter(self):
        """作品集下拉重填(UI重设计c3; 保留当前选中; refresh 前调用)。"""
        cur = self.col_filter.currentData()
        self.col_filter.blockSignals(True)
        self.col_filter.clear()
        self.col_filter.addItem(t("作品集: 全部", "Collections: all"), None)
        for c in self.lib.collections_list():
            self.col_filter.addItem(f"{c['name']} ({c['n']})", c["id"])
        idx = self.col_filter.findData(cur)
        self.col_filter.setCurrentIndex(idx if idx >= 0 else 0)
        self.col_filter.blockSignals(False)

    def apply_collection_filter(self, cid: int):
        """作品集页联动: 选中指定作品集并刷新(公开接口)。"""
        idx = self.col_filter.findData(cid)
        if idx < 0:
            self.refresh(force=True)   # 重填一次让新集出现在下拉里
            idx = self.col_filter.findData(cid)
        if idx >= 0:
            self.col_filter.setCurrentIndex(idx)
        self.refresh(force=True)

    def _refresh_spot_filter(self):
        """鸟点下拉重填(保留当前选中; refresh 前调用)。"""
        cur = self.spot_filter.currentText()
        self.spot_filter.blockSignals(True)
        self.spot_filter.clear()
        self.spot_filter.addItem(t("鸟点: 全部", "Spot: all"), None)
        for sp in self.lib.spots_overview():
            self.spot_filter.addItem(f"{sp['name']} ({sp.get('n', '?')})"
                                     if sp.get("n") else sp["name"])
        idx = self.spot_filter.findText(cur)
        self.spot_filter.setCurrentIndex(idx if idx >= 0 else 0)
        self.spot_filter.blockSignals(False)

    def _rebuild_chips(self):
        """重建胶囊行: 范围内鸟种(数量降序)+全部; 无范围且未筛选=隐藏。"""
        rows = self._scope_rows()
        if not rows and not self._tl_sp:
            self.chips_card.setVisible(False)
            return
        while self.chips_lay.count():
            it = self.chips_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

        def _chip(text, code):
            sel = (self._tl_sp == code)
            c = QLabel(text)
            c.setStyleSheet(
                "font-size:13px;padding:4px 14px;border-radius:14px;"
                + (f"background:{theme.BLUE};color:white;" if sel else
                   f"background:{theme.FILL};color:{theme.LABEL};"))
            c.setCursor(Qt.PointingHandCursor)
            c.mousePressEvent = lambda e, cd=code: self._pick_species(cd)
            self.chips_lay.addWidget(c)

        names: dict[str, str] = {}
        for v in self._raw.values():
            for p in v:
                mc = p.get("main_code")
                if mc and mc not in names:
                    names[mc] = sname(p.get("sp_cn") or "", p.get("sp_en") or "")
        agg: dict[str, int] = {}
        for p in rows:
            mc = p.get("main_code")
            if mc:
                agg[mc] = agg.get(mc, 0) + 1
        _chip(t(f"全部 {len(rows)}", f"All {len(rows)}"), None)
        for code, n in sorted(agg.items(), key=lambda kv: (-kv[1], kv[0])):
            _chip(f"{names.get(code, code)} ×{n}", code)
        self.chips_lay.addStretch(1)
        tip = QLabel(t("点鸟种只看该种；再点一次恢复全部",
                       "Click a species to filter; click again for all"))
        tip.setStyleSheet(f"font-size:12px;color:{theme.LABEL_3};"
                          "background:transparent;")
        tip.setWordWrap(True)
        self.chips_lay.addWidget(tip)
        self.chips_card.setVisible(True)

    def _pick_species(self, code):
        """胶囊点击: 筛选/取消该鸟种(整库范围, 与连拍折叠叠加)。"""
        self._tl_sp = None if self._tl_sp == code else code
        self.refresh(force=True)

    def _caption(self, ph: dict) -> str:
        """缩略图说明=鸟种+鸟点(0.8.6用户, 鸟点详情是时间+鸟种的对偶)。"""
        parts = []
        if ph.get("main_code"):
            sp = sname(ph.get("sp_cn") or "", ph.get("sp_en") or "")
            if sp:
                parts.append(sp)
        spot = ph.get("spot_short") or ph.get("spot_name") or ""
        if spot:
            parts.append(spot)
        return " · ".join(parts)

    def _apply_view_filters(self, raw: dict) -> dict:
        """评分/选片/标签/作品集/鸟点/置信 六维叠加过滤
        (c8自refresh切出; 只动视图, 全部选'全部'即还原)。"""
        # 评分/选片筛选(1.0冲刺①+⑨): 只动视图, 与鸟种胶囊叠加
        ri = self.rating_filter.currentIndex() if hasattr(self, "rating_filter") else 0
        pi = self.pick_filter.currentIndex() if hasattr(self, "pick_filter") else 0
        if ri:
            if ri == 6:        # 未评星
                raw = {ym: [p for p in v if not (p.get("rating") or 0)]
                       for ym, v in raw.items()}
            else:              # ★ri+
                raw = {ym: [p for p in v if (p.get("rating") or 0) >= ri]
                       for ym, v in raw.items()}
            raw = {ym: v for ym, v in raw.items() if v}
        if pi:
            want = ("", "keep", "pending", "reject", "")[pi]
            if pi == 4:        # 未标
                raw = {ym: [p for p in v if not (p.get("pick") or "")]
                       for ym, v in raw.items()}
            else:
                raw = {ym: [p for p in v if (p.get("pick") or "") == want]
                       for ym, v in raw.items()}
            raw = {ym: v for ym, v in raw.items() if v}
        # 标签筛选(1.0冲刺⑭): 批量map避免逐张查询
        ti = self.tag_filter.currentIndex() if hasattr(self, "tag_filter") else 0
        if ti:
            tag_id = self.tag_filter.itemData(ti)
            tagged = {r["photo_id"] for r in self.lib.conn.execute(
                "SELECT photo_id FROM photo_tags WHERE tag_id=?", (tag_id,))}
            raw = {ym: [p for p in v if p["id"] in tagged]
                   for ym, v in raw.items()}
            raw = {ym: v for ym, v in raw.items() if v}
        # 作品集筛选(UI重设计c3): 同标签套路, 批量map避免逐张查询
        ci_col = (self.col_filter.currentIndex()
                  if hasattr(self, "col_filter") else 0)
        if ci_col:
            cid = self.col_filter.itemData(ci_col)
            in_col = {r["photo_id"] for r in self.lib.conn.execute(
                "SELECT photo_id FROM collection_photos WHERE collection_id=?",
                (cid,))}
            raw = {ym: [p for p in v if p["id"] in in_col]
                   for ym, v in raw.items()}
            raw = {ym: v for ym, v in raw.items() if v}
        # 鸟点筛选(1.0冲刺⑤)
        si = self.spot_filter.currentIndex() if hasattr(self, "spot_filter") else 0
        if si:
            spot_name = self.spot_filter.currentText()
            spot_name = spot_name.split(" (")[0] if " (" in spot_name else spot_name
            raw = {ym: [p for p in v
                        if (p.get("spot_name") or "") == spot_name]
                   for ym, v in raw.items()}
            raw = {ym: v for ym, v in raw.items() if v}
        # 置信度筛选(1.0冲刺⑤): 待复核<0.5即既有语义
        ci = self.conf_filter.currentIndex() if hasattr(self, "conf_filter") else 0
        if ci:
            if ci == 1:
                raw = {ym: [p for p in v if p.get("main_conf") is not None
                            and p["main_conf"] < 0.5]
                       for ym, v in raw.items()}
            elif ci == 2:
                raw = {ym: [p for p in v if (p.get("main_conf") or 0) >= 0.5]
                       for ym, v in raw.items()}
            elif ci == 3:
                raw = {ym: [p for p in v if (p.get("main_conf") or 0) >= 0.8]
                       for ym, v in raw.items()}
            else:            # 无识别
                raw = {ym: [p for p in v if p.get("main_conf") is None]
                       for ym, v in raw.items()}
            raw = {ym: v for ym, v in raw.items() if v}
        return raw

    def _build_fbar(self):
        """筛选条(c8自_build_ui切出): 六个下拉横排。"""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QComboBox, QHBoxLayout
        fbar = QHBoxLayout()
        self.rating_filter = QComboBox()
        self.rating_filter.addItems([
            t("评分: 全部", "Rating: all"), t("★1+", "★1+"), t("★2+", "★2+"),
            t("★3+", "★3+"), t("★4+", "★4+"), t("★5", "★5"),
            t("未评星", "Unrated")])
        self.rating_filter.setCursor(Qt.PointingHandCursor)
        self.rating_filter.currentIndexChanged.connect(
            lambda _: self.refresh(force=True))
        fbar.addWidget(self.rating_filter)
        self.pick_filter = QComboBox()
        self.pick_filter.addItems([
            t("选片: 全部", "Pick: all"), t("保留", "Keep"), t("待定", "Pending"),
            t("拒绝", "Reject"), t("未标", "Unmarked")])
        self.pick_filter.setCursor(Qt.PointingHandCursor)
        self.pick_filter.currentIndexChanged.connect(
            lambda _: self.refresh(force=True))
        fbar.addWidget(self.pick_filter)
        self.tag_filter = QComboBox()
        self.tag_filter.addItem(t("标签: 全部", "Tags: all"), None)
        self.tag_filter.setCursor(Qt.PointingHandCursor)
        self.tag_filter.currentIndexChanged.connect(
            lambda _: self.refresh(force=True))
        fbar.addWidget(self.tag_filter)
        # 作品集筛选(UI重设计c3, 补⑮"只能加不能看"缺口):
        # 与其余筛选叠加; 作品集页「在时间线查看」经 apply_collection_filter 联动
        self.col_filter = QComboBox()
        self.col_filter.addItem(t("作品集: 全部", "Collections: all"), None)
        self.col_filter.setCursor(Qt.PointingHandCursor)
        self.col_filter.currentIndexChanged.connect(
            lambda _: self.refresh(force=True))
        fbar.addWidget(self.col_filter)
        # 鸟点/置信度(1.0冲刺⑤组合筛选: 多维下拉叠加, 全部只动视图)
        self.spot_filter = QComboBox()
        self.spot_filter.addItem(t("鸟点: 全部", "Spot: all"), None)
        self.spot_filter.setCursor(Qt.PointingHandCursor)
        self.spot_filter.currentIndexChanged.connect(
            lambda _: self.refresh(force=True))
        fbar.addWidget(self.spot_filter)
        self.conf_filter = QComboBox()
        self.conf_filter.addItems([
            t("置信: 全部", "Conf: all"), t("待复核(<50%)", "Pending (<50%)"),
            t("≥50%", "≥50%"), t("≥80%", "≥80%"),
            t("无识别", "Unidentified")])
        self.conf_filter.setCursor(Qt.PointingHandCursor)
        self.conf_filter.currentIndexChanged.connect(
            lambda _: self.refresh(force=True))
        fbar.addWidget(self.conf_filter)
        fbar.addStretch(1)
        return fbar
