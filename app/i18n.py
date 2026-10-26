# -*- coding: utf-8 -*-
"""极简双语支持: t(中,英)内联翻译 + 语言设置。

约定:
· 用户可见文案一律 t("中文", "English") 内联写在调用处——无key表,
  不会错位, 评审时中英对照一目了然;
· 语言存库设置 lang = zh|en, 默认zh; 切换后整窗重建(同主题切换);
· 物种名用 sname(cn, en): 中文模式显示中文名, 英文模式显示英文名;
· 纯数据内容(图鉴正文/文化故事/分类术语)不翻译, 保持原样。
"""
from __future__ import annotations

_LANG = "zh"


def set_lang(lang: str):
    global _LANG
    _LANG = lang if lang in ("zh", "en") else "zh"


def lang() -> str:
    return _LANG


def t(zh: str, en: str) -> str:
    return zh if _LANG == "zh" else en


def sname(cn: str | None, en: str | None) -> str:
    """物种显示名: 英文模式优先英文名(缺则中文), 中文模式相反。"""
    if _LANG == "en":
        return (en or cn or "")
    return (cn or en or "")
