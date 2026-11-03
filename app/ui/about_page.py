# -*- coding: utf-8 -*-
"""关于页: 软件介绍(开发者原文案) / 开发者 / 开源生态致谢。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QFrame, QLabel, QScrollArea, QVBoxLayout,
                               QWidget)

from .. import theme
from ..i18n import t
from ..version import VERSION


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("Card")
    v = QVBoxLayout(card)
    v.setContentsMargins(20, 16, 20, 18)
    v.setSpacing(10)
    t = QLabel(title)
    t.setObjectName("CardTitle")
    v.addWidget(t)
    return card, v


def _body(text: str) -> QLabel:
    lb = QLabel(text.replace("\n", "<br>"))
    lb.setWordWrap(True)
    lb.setStyleSheet(f"font-size:14px;color:{theme.LABEL_2};background:transparent;")
    lb.setTextFormat(Qt.RichText)
    return lb


class AboutPage(QWidget):
    def __init__(self, lib, win, assets_dir: Path):
        super().__init__()
        self.lib = lib
        self.win = win
        self.assets = assets_dir
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)
        title = QLabel(t("关于", "About"))
        title.setStyleSheet(f"font-size:26px;font-weight:800;color:{theme.LABEL};"
                            "background:transparent;")
        lay.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(0, 0, 16, 24)
        cv.setSpacing(14)
        scroll.setWidget(content)
        lay.addWidget(scroll, 1)

        # ---- 头卡: logo + 名称 + 版本 ----
        head = QFrame()
        head.setObjectName("Card")
        hv = QVBoxLayout(head)
        hv.setContentsMargins(24, 20, 24, 20)
        hv.setSpacing(6)
        logo = QLabel()
        logo.setAlignment(Qt.AlignHCenter)
        pm = QIcon(str(self.assets / "brand" / "logo.png")).pixmap(110, 110)
        if not pm.isNull():
            logo.setPixmap(pm)
        hv.addWidget(logo)
        name = QLabel(t("BirdTrace Windows 版", "BirdTrace for Windows"))
        name.setAlignment(Qt.AlignHCenter)
        name.setStyleSheet(f"font-size:24px;font-weight:800;color:{theme.LABEL};"
                           "background:transparent;padding-top:6px;")
        hv.addWidget(name)
        ver = QLabel(t(f"版本 {VERSION} · 便携版 · Windows 鸟图收容所",
                       f"Version {VERSION} · Portable · "
                       "A Windows shelter for your bird photos"))
        ver.setAlignment(Qt.AlignHCenter)
        ver.setStyleSheet(f"font-size:13px;color:{theme.BLUE};font-weight:600;"
                          "background:transparent;")
        hv.addWidget(ver)
        cv.addWidget(head)

        # ---- 关于（原文案精简排版）----
        c1, v1 = _card(t("这是什么", "What this is"))
        v1.addWidget(_body(
            t("一个 Windows 鸟友的鸟图管理自救项目。\n"
              "选片有师兄的 <b>SuperPicky</b>，手机端有师兄的 <b>慧眼观鸟</b>和"
              " WarDen 的 <b>BirdTrace</b>——都很优秀，优秀到我一度觉得"
              "“只要负责拍糊就行”。但成片在 Windows 上往哪儿放、怎么管、怎么认，"
              "一直是痛点，总不能靠文件夹命名“最终版_真的最终版_这只肯定是某鸟”续命。"
              "于是借鉴师兄们的思路，<b>给 Windows 补个作业</b>。",
              "A Windows birder's do-it-yourself rescue project for bird "
              "photo management.\n"
              "For culling there is a senior birder's <b>SuperPicky</b>, "
              "and on the phone a senior birder's <b>Huiyan Birding</b> and "
              "WarDen's <b>BirdTrace</b> — all excellent, so excellent that "
              "for a while I figured my only job was to “be in charge of "
              "the blurry shots”. But where keepers should live on Windows, "
              "how to organize them, how to identify them — that has always "
              "been the pain point; you can't keep a library alive on folder "
              "names like “final_really-final_this-one-is-definitely-some-"
              "bird”. So, borrowing the seniors' ideas, <b>I'm turning in "
              "the missing homework for Windows</b>.")))
        cv.addWidget(c1)

        c2, v2 = _card(t("使用须知", "Good to know"))
        v2.addWidget(_body(
            t("<b>无偿使用</b>：不收费、不订阅、不弹窗问你要不要“升级专业版”。\n"
              "<b>识别模型</b>：WarDen 个人训练的 BirdTrace 模型。"
              "加了地区筛选，识别率很能打；不加？偶尔“鸟界脸盲但很自信”"
              "——别故意拿非洲鸟考它。\n"
              "<b>持续完善</b>：有空就干，干完再说。发现问题欢迎反馈；"
              "没发现问题？说明今天运气不错。",
              "<b>Free of charge</b>: no fees, no subscriptions, and no "
              "pop-ups asking whether you'd like to “upgrade to Pro”.\n"
              "<b>Recognition model</b>: the BirdTrace model, trained "
              "personally by WarDen. With regional filtering on, its "
              "accuracy really holds its own; without it? Occasionally "
              "“face-blind about birds but very confident” — please don't "
              "quiz it on African birds on purpose.\n"
              "<b>Always improving</b>: I work on it when I find the time, "
              "and we'll see from there. Spotted a problem? Feedback is "
              "welcome. Spotted nothing? Then today must be your lucky day.")))
        cv.addWidget(c2)

        # ---- 开发者 ----
        c3, v3 = _card(t("开发者", "Developer"))
        who = self.lib.get_setting("photographer_name", "")
        dev_txt = (t(f"设计与开发：{who}<br>",
                     f"Design &amp; development: {who}<br>") if who
                   else t("设计与开发：一位 Windows 鸟友<br>",
                          "Design &amp; development: a Windows birder<br>"))
        v3.addWidget(_body(
            dev_txt +
            t("全球征集<b>同济校友观鸟爱好者</b>——是校友且观鸟，"
              "属于“双重稀有刷新”，欢迎来聊；不是也没关系，软件照样免费用。"
              "微信：<b>tubage989525</b>",
              "Calling worldwide for <b>Tongji alumni who love birding</b> "
              "— being both an alumnus and a birder counts as a “double "
              "rare sighting”, so come say hi; if you're neither, no "
              "worries — the app is still free. "
              "WeChat: <b>tubage989525</b>")))
        cv.addWidget(c3)

        # ---- 致谢 ----
        c4, v4 = _card(t("致谢 · 开源与数据", "Acknowledgments · Open source & data"))
        v4.addWidget(_body(
            t("· 鸟类识别模型 BirdTrace FastViT-MA36（10480类）· 鸟体检测模型"
              " —— <b>BirdTrace（by WarDen）</b><br>"
              "· 分类体系 eBird/Clements v2025 · 地理先验 eBird Status &amp; Trends"
              " · 保护等级 IUCN Red List<br>"
              "· 地图引擎 MapLibre GL JS（开源）· 底图 高德<br>"
              "· 界面 PySide6/Qt · 推理 ONNX Runtime<br><br>"
              "灵感与生态伙伴：BirdTrace（Android）· 慧眼观鸟（iOS）· "
              "SuperPicky 慧眼选鸟 · SuperBirdTools<br>"
              "同一个模型，同一群人，让拍鸟人各取所需。",
              "· Bird recognition model BirdTrace FastViT-MA36 (10,480 "
              "classes) · bird detection model — <b>BirdTrace (by "
              "WarDen)</b><br>"
              "· Taxonomy eBird/Clements v2025 · geographic prior eBird "
              "Status &amp; Trends · conservation status IUCN Red List<br>"
              "· Map engine MapLibre GL JS (open source) · basemap Amap<br>"
              "· UI PySide6/Qt · inference ONNX Runtime<br><br>"
              "Inspiration and fellow apps: BirdTrace (Android) · Huiyan "
              "Birding (iOS) · SuperPicky · SuperBirdTools<br>"
              "One model, one community, letting every birder take what "
              "they need.")))
        cv.addWidget(c4)

        tail = QLabel(t("© 2026 BirdTrace Windows版 · 无偿使用 · 放心用，别客气",
                        "© 2026 BirdTrace for Windows · Free to use · "
                        "Make yourself at home"))
        tail.setAlignment(Qt.AlignHCenter)
        tail.setStyleSheet(f"font-size:12px;color:{theme.LABEL_3};background:transparent;"
                           "padding:6px;")
        cv.addWidget(tail)
        cv.addStretch(1)

    def refresh(self):
        pass
