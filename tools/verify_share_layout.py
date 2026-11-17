# -*- coding: utf-8 -*-
"""分享卡版式验证(小红书3:5/3:4 + 框对准保头 + 原图档):
尺寸/自动择优/框对准/越界/bleed/标题区不压缩(drawText截字形回归)/原图档。
红块鸟+灰底合成图, width=1600(k=1)几何可精确预测。share/字体类须真实
窗口平台跑(0.8.2教训)。"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, ".")
from PySide6.QtWidgets import QApplication

app = QApplication([])
from app import theme, i18n
theme.apply_theme(app, "light")
i18n.set_lang("zh")
from app.core.sharecard import render_card
from PIL import Image

ok = fail = 0


def check(name, cond, note=""):
    global ok, fail
    ok += bool(cond)
    fail += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {note}")


D = Path("data/_share_layout_check")
if D.exists():
    shutil.rmtree(D)
D.mkdir(parents=True)

RED = (200, 30, 30)
BLUE = (30, 30, 200)
GRAY = (128, 128, 128)


def make_photo(name, w, h, blobs=()):
    im = Image.new("RGB", (w, h), GRAY)
    for x1, y1, x2, y2, c in blobs:
        for y in range(y1, y2):
            for x in range(x1, x2):
                im.putpixel((x, y), c)
    p = D / name
    im.save(p, "JPEG", quality=95)
    return str(p)


INFO = {"cn": "测试鸟", "pinyin": [], "en": "Eagle ggjpq Owl",
        "sci": "", "lifer_no": None, "photographer": "",
        "date": "2026-11-16", "place": "", "exif": {}}


def px(img, x, y):
    if hasattr(img, "toImage"):
        img = img.toImage()
    c = img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())


def is_red(c):
    return c[0] > 150 and c[1] < 90 and c[2] < 90


def is_cream(c):
    return abs(c[0] - 240) < 14 and abs(c[1] - 239) < 14 and abs(c[2] - 228) < 16


def ink_rows(img, x0, x1, y0, y1, thr=450):
    out = []
    for yy in range(y0, y1):
        dark = sum(1 for xx in range(x0, x1, 2)
                   if sum(img.pixelColor(xx, yy).getRgb()[:3]) < thr)
        if dark:
            out.append(yy)
    return out


landscape = make_photo("l.jpg", 1200, 800)
portrait = make_photo("p.jpg", 800, 1200)
boundary = make_photo("b.jpg", 1000, 930)          # h/w=0.93 交点(0.91)上→3:5
boundary2 = make_photo("b2.jpg", 1000, 860)        # h/w=0.86 交点下侧→3:4
square_blob_l = make_photo("sl.jpg", 2000, 2000,
                           [(0, 940, 120, 1060, RED)])
square_blob_r = make_photo("sr.jpg", 2000, 2000,
                           [(1880, 940, 2000, 1060, RED)])
pano_blob = make_photo("pano.jpg", 2400, 1000,
                       [(0, 400, 100, 600, RED)])
portrait_up = make_photo("pu.jpg", 1000, 1500,
                         [(700, 100, 900, 300, RED)])
wide_bird = make_photo("wb.jpg", 3000, 2800,
                       [(200, 900, 2800, 1900, BLUE),   # 鸟体(超窗宽)
                        (2700, 1370, 2800, 1430, RED)])  # 眼在框右端

# ---- 1) 尺寸 / auto择优 / classic不变 / 原图档 ----
pm = render_card(landscape, INFO, "light", width=2000, layout="auto")
check("auto横图→3:4 (2000x2666)", pm.width() == 2000
      and abs(pm.height() - 2666) <= 2, f"{pm.width()}x{pm.height()}")
pm = render_card(portrait, INFO, "light", width=2000, layout="auto")
check("auto竖图→3:5 (2000x3334)", pm.width() == 2000
      and abs(pm.height() - 3334) <= 2, f"{pm.width()}x{pm.height()}")
pm = render_card(boundary, INFO, "light", width=2000, layout="auto")
check("auto临界(h/w=0.93>交点0.91)→3:5(裁切取小者)", pm.width() == 2000
      and abs(pm.height() - 3334) <= 2, f"{pm.width()}x{pm.height()}")
pm = render_card(boundary2, INFO, "light", width=2000, layout="auto")
check("auto临界(h/w=0.86<交点0.91)→3:4", pm.width() == 2000
      and abs(pm.height() - 2666) <= 2, f"{pm.width()}x{pm.height()}")
pm = render_card(portrait, INFO, "light", width=2000, layout="3:5")
check("强制3:5尺寸", pm.width() == 2000
      and abs(pm.height() / pm.width() - 5 / 3) < 0.01)
pm = render_card(landscape, INFO, "light", width=2000, layout="3:4")
check("强制3:4尺寸", pm.width() == 2000
      and abs(pm.height() / pm.width() - 4 / 3) < 0.01)
pm = render_card(landscape, INFO, "light", width=2000)
pm2 = render_card(landscape, INFO, "light", width=2000, layout="classic")
check("classic默认=显式, 尺寸不变(2000x2650)",
      (pm.width(), pm.height()) == (pm2.width(), pm2.height()) == (2000, 2650),
      f"{pm.width()}x{pm.height()}")
pm = render_card(landscape, INFO, "light", width=1200)
check("原图档横图 (1200x1590)", (pm.width(), pm.height()) == (1200, 1590),
      f"{pm.width()}x{pm.height()}")
pm = render_card(portrait, INFO, "light", width=800, layout="3:5")
check("原图档竖图3:5 (800x1334)", (pm.width(), pm.height()) == (800, 1334),
      f"{pm.width()}x{pm.height()}")
tiny = make_photo("tiny.jpg", 600, 400)
pm = render_card(tiny, INFO, "light", width=1200)
check("原图档小图钳1200 (1200x1590)", (pm.width(), pm.height()) == (1200, 1590),
      f"{pm.width()}x{pm.height()}")

# ---- 2) 框对准(3:5, 两侧裁): 左缘/右缘/无框对照 ----
# (ph=1877: 方图缩0.9385→1877×1877, 红块y带882~995→探针取y=940)
pm = render_card(square_blob_l, {**INFO, "focus": (0.03, 0.5)},
                 "light", width=1600, layout="3:5")
check("框对准:左缘红块入窗", is_red(px(pm, 30, 940)), str(px(pm, 30, 940)))
pm = render_card(square_blob_l, INFO, "light", width=1600, layout="3:5")
check("无框居中:左缘红块被裁", not is_red(px(pm, 30, 940)),
      str(px(pm, 30, 940)))
pm = render_card(square_blob_r, {**INFO, "focus": (0.97, 0.5)},
                 "light", width=1600, layout="3:5")
check("框对准:右缘夹紧入窗", is_red(px(pm, 1550, 940)),
      str(px(pm, 1550, 940)))

# ---- 3) 框对准窗口上移: 文字区不沾照片(0.8.3截断bug回归) ----
pm = render_card(portrait_up, {**INFO, "focus": (0.5, 0.133)},
                 "light", width=1600, layout="3:5")
check("框对准上移:鸟仍在照片区", is_red(px(pm, 1280, 200)),
      str(px(pm, 1280, 200)))
check("框对准上移:文字区不沾照片", is_cream(px(pm, 800, 2200)),
      str(px(pm, 800, 2200)))
check("框对准上移:更深文字区同为底色", is_cream(px(pm, 800, 2600)),
      str(px(pm, 800, 2600)))

# ---- 4) bleed: 全景(损失>30%)→模糊垫底整图可见 ----
pm = render_card(pano_blob, {**INFO, "focus": (0.02, 0.5)},
                 "light", width=1600, layout="3:4")
check("bleed:整图可见(最左红块入卡)", is_red(px(pm, 20, 560)),
      str(px(pm, 20, 560)))
check("bleed:垫底为模糊照片(非主题米色)",
      not is_cream(px(pm, 20, 60)), str(px(pm, 20, 60)))

# ---- 5) classic不受新逻辑影响 ----
pm = render_card(pano_blob, INFO, "light", width=1600)
check("classic全景居中重裁(红块不可见)", not is_red(px(pm, 5, 560)),
      str(px(pm, 5, 560)))

# ---- 6) 0.8.4: 标题区不压缩(descender回归) + meta行压缩 + 品牌行不越界 ----
pm = render_card(portrait, INFO, "light", width=1600, layout="3:5")
PH = 1877
c = px(pm, 800, PH + 428)
near_line = abs(c[0] - 220) < 30 and abs(c[1] - 219) < 30 and abs(c[2] - 204) < 30
check("3:5标题区不压缩:分隔线仍在428", near_line, str(c))
img = pm.toImage()
d_rows = ink_rows(img, 112, 400, PH + 326, PH + 402, thr=560)
check("3:5英文名descender不截断(整行墨量完整)",
      len(d_rows) >= 30, f"墨行数={len(d_rows)}(裁剪时约腰斩)")
pm = render_card(portrait, {**INFO, "photographer": "Tester"},
                 "light", width=1600, layout="3:5")
img = pm.toImage()
p_rows = ink_rows(img, 112, 400, PH + 600, PH + 674)
ok_band = bool(p_rows) and p_rows[0] >= PH + 600 and p_rows[-1] <= PH + 674
check("3:5 meta压缩:拍摄者墨在606行带(非旧676)",
      len(p_rows) >= 6 and ok_band,
      f"墨行={p_rows[:2]}..{p_rows[-2:] if p_rows else []}")
check("3:5品牌行不越界(logo下方已是底色)",
      all(is_cream(px(pm, x, PH + 766)) for x in (120, 800, 1480)),
      str(px(pm, 800, PH + 766)))
pm = render_card(landscape, INFO, "light", width=1600, layout="3:4")
c = px(pm, 800, 1133 + 428)
check("3:4行距不变:分隔线仍在428",
      abs(c[0] - 220) < 30 and abs(c[1] - 219) < 30 and abs(c[2] - 204) < 30,
      str(c))

# ---- 7) 眼点保头: 横图鸟体超窗, 眼在框右端——眼锚定入窗/框心裁头 ----
# (ph=1877: 缩0.6704→2011×1877, sy=0; 窗sx=411, 眼x带1399~1466 y带918~959)
pm = render_card(wide_bird, {**INFO, "focus": (0.9, 0.5)},
                 "light", width=1600, layout="3:5")
check("保头:眼锚定窗口眼睛入卡", is_red(px(pm, 1430, 938)),
      str(px(pm, 1430, 938)))
pm = render_card(wide_bird, {**INFO, "focus": (0.5, 0.5)},
                 "light", width=1600, layout="3:5")
check("保头对照:框心窗口眼睛被裁", not is_red(px(pm, 1430, 938)),
      str(px(pm, 1430, 938)))

# ---- 8) 0.8.5 手动裁切adjust: 数学单源/夹紧/缩放平移/全景bleed起点 ----
from app.core.sharecard import photo_placement, ADJUST_ZOOM_MAX

pl = photo_placement(2000, 2000, 1600, 1877)             # 方图→3:5窗口
check("placement数学: cover基准无焦点居中", pl["w"] == 1877 and pl["rx"] == 277
      and abs(pl["sx"] - 138.5) < 1 and pl["ry"] == 0, str(pl))
pl = photo_placement(2000, 2000, 1600, 1877,
                     adjust={"zoom": 99, "ox": -5, "oy": 9})
check("夹紧: zoom钳上限/ox·oy钳[0,1]", pl["zoom"] == ADJUST_ZOOM_MAX
      and pl["sx"] == 0 and pl["sy"] == pl["ry"], str(pl))
pm = render_card(square_blob_l, INFO, "light", width=1600, layout="3:5",
                 adjust={"zoom": 2.0, "ox": 0.0})
check("手动: zoom2贴左缘红块仍入卡", is_red(px(pm, 30, 940)),
      str(px(pm, 30, 940)))
pm = render_card(square_blob_l, INFO, "light", width=1600, layout="3:5",
                 adjust={"zoom": 2.0, "ox": 1.0})
check("手动: zoom2推到右端红块被裁", not is_red(px(pm, 30, 940)),
      str(px(pm, 30, 940)))
pm = render_card(pano_blob, INFO, "light", width=1600, layout="3:4",
                 adjust={"zoom": 1.0})
check("手动全景zoom1=自动bleed: 整图可见", is_red(px(pm, 20, 560)),
      str(px(pm, 20, 560)))
pm = render_card(pano_blob, INFO, "light", width=1600, layout="3:4",
                 adjust={"zoom": 1.5, "ox": 1.0})
check("手动全景zoom1.5推右: 红块出窗+上下模糊垫底仍在",
      not is_red(px(pm, 20, 560)) and not is_cream(px(pm, 800, 20)),
      f"{px(pm, 20, 560)} {px(pm, 800, 20)}")
pm = render_card(landscape, INFO, "light", width=1600, layout="classic",
                 adjust={"zoom": 3.0, "ox": 1.0, "oy": 1.0})
pm2 = render_card(landscape, INFO, "light", width=1600, layout="classic")
check("classic不吃adjust(历史行为不动)", pm.size() == pm2.size())

print(f"\n===== SHARE_LAYOUT: PASS={ok} FAIL={fail} =====")
sys.exit(1 if fail else 0)
