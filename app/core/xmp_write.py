# -*- coding: utf-8 -*-
"""⑪ XMP 鸟种写回(可选, 默认关; 2026-11-19 用户拍板开发):
把人工确认的鸟种关键词+拍摄日期+版权块写入 JPEG 的 APP1/XMP 段
(dc:subject / photoshop:DateCreated / dc:rights), 供 Lightroom 等
外部软件读取。纯 stdlib 实现——不引第三方依赖(⑪红线)。

安全纪律(原图绝不动原则的⑪调和):
· 设置 xmp_writeback="1" 才写; 设置页首次启用弹"请先在副本上验证"提示
· 只处理 JPEG(SOI+APP1 结构); PNG/HEIC/RAW/视频一律跳过
· 原子写: 全量读→内存改段→<临时文件>→os.replace; 任一步失败原件不动
· 已有 XMP 段=整段替换; 没有=插在 APP0/EXIF 之后
· XMP 段上限 64KB, 超长截断(关键词列表极少超)
"""
from __future__ import annotations

import os
from pathlib import Path

XMP_NS_HDR = b"http://ns.adobe.com/xap/1.0/\x00"


def build_xmp(keywords: list[str], date_created: str,
              rights: str | None = None) -> bytes:
    """构造最小可读的 XMP RDF(Adobe 常规字段, Lightroom 兼容)。"""
    def _esc(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;") \
            .replace(">", "&gt;")
    kws = "".join(
        f"<rdf:li>{_esc(k)}</rdf:li>" for k in (keywords or []) if k)
    parts = [
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>',
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">',
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">',
        '<rdf:Description rdf:about=""',
        ' xmlns:dc="http://purl.org/dc/elements/1.1/"',
        ' xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/">',
        f'<dc:subject><rdf:Bag>{kws}</rdf:Bag></dc:subject>',
    ]
    if date_created:
        parts.append(f'<photoshop:DateCreated>{_esc(date_created)}'
                     '</photoshop:DateCreated>')
    if rights:
        parts.append(f'<dc:rights><rdf:Alt><rdf:li xml:lang="x-default">'
                     f'{_esc(rights)}</rdf:li></rdf:Alt></dc:rights>')
    parts.append('</rdf:Description></rdf:RDF></x:xmpmeta>')
    parts.append('<?xpacket end="w"?>')
    return "".join(parts).encode("utf-8")


def _segments(data: bytes):
    """解析 JPEG 段: yield (marker, start, end含长度)。SOS 后是熵数据。"""
    if data[:2] != b"\xff\xd8":
        return
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            return
        marker = data[i + 1]
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if marker == 0xDA:   # SOS: 后面是压缩数据, 停
            yield (marker, i, len(data))
            return
        seg_len = (data[i + 2] << 8) | data[i + 3]
        yield (marker, i, i + 2 + seg_len)
        i += 2 + seg_len


def read_xmp(path: str | Path) -> str | None:
    """读 JPEG 内现有 XMP 文本(无=None)。非 JPEG 返回 None。"""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    if data[:2] != b"\xff\xd8":
        return None
    for marker, _s, e in _segments(data):
        if marker != 0xE1:   # APP1
            continue
        seg = data[_s + 4:e]
        if seg.startswith(XMP_NS_HDR):
            return seg[len(XMP_NS_HDR):].decode("utf-8", "replace")
    return None


def write_xmp(path: str | Path, xmp_bytes: bytes) -> bool:
    """把 XMP 写进 JPEG APP1 段(替换已有/新建)。失败返回 False, 原件不动。"""
    fp = Path(path)
    try:
        data = fp.read_bytes()
    except OSError:
        return False
    if data[:2] != b"\xff\xd8" or len(xmp_bytes) > 65500:
        return False
    new_seg = b"\xff\xe1" + ((len(xmp_bytes) + len(XMP_NS_HDR) + 2)
                             .to_bytes(2, "big")) + XMP_NS_HDR + xmp_bytes
    out = bytearray(data[:2])
    inserted = False
    for marker, s, e in _segments(data):
        seg_len = e - s
        if marker == 0xDA:
            if not inserted:
                out += new_seg
                inserted = True
            out += data[s:]
            break
        if marker == 0xE1 and data[s + 4:s + 4 + len(XMP_NS_HDR)] == XMP_NS_HDR:
            out += new_seg          # 替换已有 XMP 段
            inserted = True
            continue
        out += data[s:e]
        # 插入位置: APP0(JFIF) 与 EXIF(APP1) 之后、其余段之前
        if marker in (0xE0, 0xE1) and not inserted:
            nxt = out[-1]
            # 只有当下一段不再是同优先级头段时, 立即插入
            if marker == 0xE0 and data[e:e + 2] == b"\xff\xe1":
                continue            # 后面还有 EXIF, 等它写完再插
            out += new_seg
            inserted = True
    if not inserted:
        # 全是无头段(罕见): 插在 SOI 之后
        return False
    tmp = fp.with_name(fp.name + ".birdtrace-xmp-tmp")
    try:
        tmp.write_bytes(bytes(out))
        os.replace(tmp, fp)         # 同卷原子替换
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def maybe_write_for_photo(lib, photo_id: int) -> bool:
    """按设置执行的照片级写回入口(人工确认/改判钩子调用):
    xmp_writeback 关闭→False; 非JPEG/无生效鸟种→False;
    写关键词=[中文名,英文名,学名], 日期, 版权声明(⑰单源)。"""
    if lib.get_setting("xmp_writeback", "0") != "1":
        return False
    r = lib.conn.execute(
        "SELECT p.path, v.eff_code, COALESCE(e.dt_original, p.added_at) ts "
        "FROM photos p LEFT JOIN v_records v ON v.photo_id=p.id AND v.rank=1 "
        "LEFT JOIN exif e ON e.photo_id=p.id WHERE p.id=?",
        (photo_id,)).fetchone()
    if not r or not r["path"] or not r["eff_code"]:
        return False
    path = Path(r["path"])
    if not path.is_file() or path.suffix.lower() not in (".jpg", ".jpeg"):
        return False
    sp = lib.species_info(r["eff_code"])
    kws = []
    if sp:   # species_info 返回 sqlite3.Row
        sp = dict(sp)
        kws = [x for x in (sp.get("cn"), sp.get("en"), sp.get("sci")) if x]
    cp = lib.effective_copyright(photo_id)
    rights = cp.get("copyright_notice") or None
    return write_xmp(path, build_xmp(kws, (r["ts"] or "")[:19].replace(
        " ", "T")[:10], rights))
