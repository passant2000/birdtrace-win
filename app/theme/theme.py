# -*- coding: utf-8 -*-
"""iOS风格主题: 明/暗调色板 + 全局QSS + QPalette + 字体。

用法: theme.apply_theme(app, mode)  —— mode: "system"|"light"|"dark"
必须在构建任何窗口之前调用(main.py在import ui前完成)。
页面内联样式引用本模块的颜色常量(from ..theme import LABEL等),
切换主题需重启(常量在ui模块import时绑定)。
"""

FONT_FAMILIES = ["MiSans", "HarmonyOS Sans SC", "PingFang SC",
                 "Microsoft YaHei UI", "Segoe UI"]

LIGHT = {
    "BG": "#F2F2F7", "CARD": "#FFFFFF", "SIDEBAR": "#E9E9EE",
    "SEP": "#E3E3E8", "LABEL": "#1C1C1E", "LABEL_2": "#6D6D72",
    "LABEL_3": "#AEAEB2", "BLUE": "#007AFF", "GREEN": "#34C759",
    "RED": "#FF3B30", "ORANGE": "#FF9500", "FILL": "#EFEFF3",
    "HOVER": "#E4E4EA", "PRESSED": "#D8D8DE", "VIEWER_BG": "#E9E9EE",
    "CARD_BORDER": "rgba(0,0,0,14)", "NAV_HOVER": "rgba(0,0,0,28)",
    "SCROLL": "rgba(0,0,0,58)", "SCROLL_HOVER": "rgba(0,0,0,100)",
    "SEL_BG": "rgba(0,122,255,36)", "CHIP_BG": "#EAF3FF", "CHIP_FG": "#007AFF",
    "PROG_BG": "rgba(0,0,0,28)", "INPUT_FOCUS_BG": "#FFFFFF",
    "OLIVE": "#8A9455",
    "PRIMARY_HOVER": "#0071EB", "PRIMARY_PRESSED": "#0062CC",
    "PRIMARY_DISABLED": "#B8D6FF", "LINK_HOVER": "#0062CC",
    "DANGER_BG": "rgba(255,59,48,26)",
}

DARK = {
    "BG": "#1C1C1E", "CARD": "#2C2C2E", "SIDEBAR": "#161618",
    "SEP": "#38383A", "LABEL": "#F2F2F7", "LABEL_2": "#98989F",
    "LABEL_3": "#7C7C80", "BLUE": "#0A84FF", "GREEN": "#30D158",
    "RED": "#FF453A", "ORANGE": "#FF9F0A", "FILL": "#3A3A3C",
    "HOVER": "#48484A", "PRESSED": "#545456", "VIEWER_BG": "#111113",
    "CARD_BORDER": "rgba(255,255,255,26)", "NAV_HOVER": "rgba(255,255,255,24)",
    "OLIVE": "#A8B36E",
    "SCROLL": "rgba(255,255,255,58)", "SCROLL_HOVER": "rgba(255,255,255,100)",
    "SEL_BG": "rgba(10,132,255,52)", "CHIP_BG": "#0E2A47", "CHIP_FG": "#6FB2FF",
    "PROG_BG": "rgba(255,255,255,30)", "INPUT_FOCUS_BG": "#3A3A3C",
    "PRIMARY_HOVER": "#2A94FF", "PRIMARY_PRESSED": "#1180E8",
    "PRIMARY_DISABLED": "#274568", "LINK_HOVER": "#6FB2FF",
    "DANGER_BG": "rgba(255,69,58,44)",
}

# 兼容既有引用: 模块级常量在apply_theme时按当前模式覆盖
BG = LIGHT["BG"]
BG_SECONDARY = LIGHT["CARD"]
SIDEBAR_BG = LIGHT["SIDEBAR"]
SEPARATOR = LIGHT["SEP"]
LABEL = LIGHT["LABEL"]
OLIVE = LIGHT["OLIVE"]
LABEL_2 = LIGHT["LABEL_2"]
LABEL_3 = LIGHT["LABEL_3"]
BLUE = LIGHT["BLUE"]
GREEN = LIGHT["GREEN"]
RED = LIGHT["RED"]
ORANGE = LIGHT["ORANGE"]
FILL = LIGHT["FILL"]
CARD = LIGHT["CARD"]
HOVER = LIGHT["HOVER"]
PRESSED = LIGHT["PRESSED"]
VIEWER_BG = LIGHT["VIEWER_BG"]
CHIP_BG = LIGHT["CHIP_BG"]
CHIP_FG = LIGHT["CHIP_FG"]
CARD_BORDER = LIGHT["CARD_BORDER"]
SEP = SEPARATOR   # 短别名

_current = dict(LIGHT)
_current_mode = "light"


def current_mode() -> str:
    return _current_mode


def _build_qss(c: dict) -> str:
    return f"""
* {{
    font-family: "MiSans", "HarmonyOS Sans SC", "PingFang SC",
                 "Microsoft YaHei UI", "Segoe UI";
    outline: none;
}}
QMainWindow, QDialog {{ background: {c["BG"]}; }}
QWidget#Root {{ background: {c["BG"]}; }}

/* ---- 侧栏 ---- */
QFrame#Sidebar {{
    background: {c["SIDEBAR"]};
    border-right: 1px solid {c["SEP"]};
}}
QLabel#AppTitle {{
    color: {c["LABEL"]}; font-size: 20px; font-weight: 700;
    background: transparent; padding: 4px 0 0 0;
}}
QLabel#AppSubtitle {{ color: {c["LABEL_2"]}; font-size: 12px; background: transparent; }}
/* 分组侧栏(UI重设计c2): 组标题小字+分隔线 */
QLabel#SidebarGroup {{
    color: {c["LABEL_3"]}; font-size: 12px; font-weight: 700;
    background: transparent; padding: 2px 6px 0 6px;
}}
QFrame#SidebarSep {{ color: {c["SEP"]}; background: {c["SEP"]}; max-height: 1px; border: none; }}

QPushButton#NavItem {{
    color: {c["LABEL"]}; background: transparent; border: none;
    border-radius: 10px; padding: 10px 14px; text-align: left;
    font-size: 14px;
}}
QPushButton#NavItem:hover {{ background: {c["NAV_HOVER"]}; }}
QPushButton#NavItem:checked {{
    background: {c["BLUE"]}; color: white; font-weight: 600;
}}

/* ---- 卡片 ---- */
QFrame#Card {{
    background: {c["CARD"]};
    border-radius: 14px;
    border: 1px solid {c["CARD_BORDER"]};
}}
QLabel#CardTitle {{
    color: {c["LABEL"]}; font-size: 15px; font-weight: 700; background: transparent;
}}
QLabel#SectionHeader {{
    color: {c["LABEL_2"]}; font-size: 13px; font-weight: 600;
    background: transparent; padding: 2px 4px;
}}

/* ---- 按钮 ---- */
QPushButton {{
    background: {c["FILL"]}; color: {c["LABEL"]}; border: none;
    border-radius: 10px; padding: 9px 18px; font-size: 14px;
}}
QPushButton:hover {{ background: {c["HOVER"]}; }}
QPushButton:pressed {{ background: {c["PRESSED"]}; }}
QPushButton:disabled {{ color: {c["LABEL_3"]}; }}

QPushButton#Primary {{
    background: {c["BLUE"]}; color: white; font-weight: 600; font-size: 15px;
    padding: 11px 26px; border-radius: 12px;
}}
QPushButton#Primary:hover {{ background: {c["PRIMARY_HOVER"]}; }}
QPushButton#Primary:pressed {{ background: {c["PRIMARY_PRESSED"]}; }}
QPushButton#Primary:disabled {{ background: {c["PRIMARY_DISABLED"]}; color: white; }}

QPushButton#Danger {{ background: {c["DANGER_BG"]}; color: {c["RED"]}; }}
QPushButton#Link {{ background: transparent; color: {c["BLUE"]}; padding: 4px 8px; }}
QPushButton#Link:hover {{ background: transparent; color: {c["LINK_HOVER"]}; }}

/* ---- 输入 ---- */
QLineEdit, QComboBox {{
    background: {c["FILL"]}; border: none; border-radius: 10px;
    padding: 9px 14px; font-size: 14px; color: {c["LABEL"]};
}}
QLineEdit:focus {{ background: {c["INPUT_FOCUS_BG"]}; border: 2px solid {c["BLUE"]}; padding: 7px 12px; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{
    width: 0; height: 0; border-left: 5px solid transparent;
    border-right: 5px solid transparent; border-top: 6px solid {c["LABEL_2"]};
    margin-right: 10px;
}}
QComboBox QAbstractItemView {{
    background: {c["CARD"]}; color: {c["LABEL"]};
    border-radius: 10px; border: 1px solid {c["SEP"]};
    selection-background-color: {c["BLUE"]}; selection-color: white;
    padding: 6px; outline: none;
}}
QSpinBox, QDoubleSpinBox {{
    background: {c["FILL"]}; border: none; border-radius: 10px; padding: 8px 12px;
    color: {c["LABEL"]};
}}

/* ---- 滚动条 ---- */
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{
    background: transparent; width: 8px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {c["SCROLL"]}; border-radius: 4px; min-height: 40px;
}}
QScrollBar::handle:vertical:hover {{ background: {c["SCROLL_HOVER"]}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{
    background: transparent; height: 8px; margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {c["SCROLL"]}; border-radius: 4px; min-width: 40px;
}}

/* ---- 进度条 ---- */
QProgressBar {{
    background: {c["PROG_BG"]}; border: none; border-radius: 5px;
    height: 10px; text-align: center; color: transparent; font-size: 9px;
}}
QProgressBar::chunk {{ background: {c["BLUE"]}; border-radius: 5px; }}

/* ---- 列表/网格 ---- */
QListWidget {{
    background: transparent; border: none; color: {c["LABEL"]};
}}
QListWidget::item {{ border-radius: 12px; margin: 4px; }}
QListWidget::item:selected {{ background: {c["SEL_BG"]}; }}

/* ---- 表格(复核页) ---- */
QTableWidget {{
    background: {c["CARD"]}; border-radius: 14px; border: 1px solid {c["CARD_BORDER"]};
    gridline-color: {c["SEP"]}; color: {c["LABEL"]};
}}
QTableWidget::item {{ padding: 6px; }}
QHeaderView::section {{
    background: {c["BG"]}; border: none; border-bottom: 1px solid {c["SEP"]};
    padding: 8px; font-weight: 600; color: {c["LABEL_2"]};
}}

/* ---- 分组框行 ---- */
QLabel#RowLabel {{ color: {c["LABEL"]}; font-size: 14px; background: transparent; }}
QLabel#RowValue {{ color: {c["LABEL_2"]}; font-size: 13px; background: transparent; }}
QLabel#Hint {{ color: {c["LABEL_3"]}; font-size: 12px; background: transparent; }}
QLabel#Badge {{
    color: white; background: {c["ORANGE"]}; border-radius: 9px;
    font-size: 11px; font-weight: 700; padding: 2px 8px;
}}
QToolTip {{ background: {c["CARD"]}; color: {c["LABEL"]}; border: 1px solid {c["SEP"]}; }}
"""


def _set_module_colors(c: dict):
    g = globals()
    g["BG"], g["BG_SECONDARY"], g["SIDEBAR_BG"], g["SEPARATOR"] = \
        c["BG"], c["CARD"], c["SIDEBAR"], c["SEP"]
    g["LABEL"], g["LABEL_2"], g["LABEL_3"] = c["LABEL"], c["LABEL_2"], c["LABEL_3"]
    g["OLIVE"] = c["OLIVE"]
    g["BLUE"], g["GREEN"], g["RED"], g["ORANGE"] = \
        c["BLUE"], c["GREEN"], c["RED"], c["ORANGE"]
    g["FILL"], g["CARD"], g["HOVER"], g["PRESSED"] = \
        c["FILL"], c["CARD"], c["HOVER"], c["PRESSED"]
    g["VIEWER_BG"], g["CHIP_BG"], g["CHIP_FG"] = \
        c["VIEWER_BG"], c["CHIP_BG"], c["CHIP_FG"]
    g["CARD_BORDER"] = c["CARD_BORDER"]


def _apply_palette(app, c: dict):
    """显式QPalette: 下拉/菜单/提示等原生弹层的文字底色不再跟随系统深浅。"""
    from PySide6.QtGui import QColor, QPalette
    p = QPalette()
    bg, card, label, l2 = QColor(c["BG"]), QColor(c["CARD"]), \
        QColor(c["LABEL"]), QColor(c["LABEL_2"])
    blue = QColor(c["BLUE"])
    for role, color in (
            (QPalette.ColorRole.Window, bg),
            (QPalette.ColorRole.Base, card),
            (QPalette.ColorRole.AlternateBase, bg),
            (QPalette.ColorRole.Text, label),
            (QPalette.ColorRole.WindowText, label),
            (QPalette.ColorRole.ButtonText, label),
            (QPalette.ColorRole.Button, QColor(c["FILL"])),
            (QPalette.ColorRole.ToolTipBase, card),
            (QPalette.ColorRole.ToolTipText, label),
            (QPalette.ColorRole.Highlight, blue),
            (QPalette.ColorRole.HighlightedText, QColor("white")),
            (QPalette.ColorRole.PlaceholderText, QColor(c["LABEL_3"]))):
        p.setColor(role, color)
    for grp in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive,
                QPalette.ColorGroup.Disabled):
        p.setColor(grp, QPalette.ColorRole.Text, QColor(c["LABEL_3"]))
        p.setColor(grp, QPalette.ColorRole.WindowText, QColor(c["LABEL_3"]))
        p.setColor(grp, QPalette.ColorRole.ButtonText, QColor(c["LABEL_3"]))
    app.setPalette(p)


def resolve_mode(mode: str) -> str:
    if mode in ("light", "dark"):
        return mode
    # system
    try:
        from PySide6.QtGui import QGuiApplication
        scheme = QGuiApplication.styleHints().colorScheme()
        return "dark" if scheme.name == "Dark" else "light"
    except Exception:
        return "light"


def apply_theme(app, mode: str = "system"):
    global _current, _current_mode
    resolved = resolve_mode(mode)
    _current_mode = resolved
    _current = dict(LIGHT if resolved == "light" else DARK)
    _set_module_colors(_current)
    app.setStyleSheet(_build_qss(_current))
    _apply_palette(app, _current)
    from PySide6.QtGui import QFont
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setPointSize(10)
    app.setFont(f)
