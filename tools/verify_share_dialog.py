# -*- coding: utf-8 -*-
"""0.8.5 分享卡对话框重做·功能级验证(真窗口平台跑, 勿设offscreen——
share字体类测试0.8.2教训): 左预览右选项/默认最大化/视图缩放/
手动构图(拖动平移+滚轮缩放锚点+滑杆+自动复位+classic禁用+换版式保持)。
红块鸟合成图, BIRDTRACE_CARD_WIDTH=1600钉死k=1几何可精确预测。"""
import os
import shutil
import sys
from pathlib import Path

os.environ["BIRDTRACE_CARD_WIDTH"] = "1600"   # 测试钩子: k=1(先于import设)

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

FAILED = {"v": False}


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}", flush=True)
    if not cond:
        FAILED["v"] = True


def main():
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from app import theme, i18n
    theme.apply_theme(app, "light")
    i18n.set_lang("zh")

    D = PROJ / "data/share_dialog_check"
    if D.exists():
        shutil.rmtree(D)
    D.mkdir(parents=True)
    from PIL import Image
    # 方图+左缘红块(2000×2000, 块x0-120/y940-1060): 3:5窗口cover基准
    # 0.9385→1877×1877, 可平移rx=277; 块x带0~112.6
    p = D / "sq.jpg"
    im = Image.new("RGB", (2000, 2000), (128, 128, 128))
    for y in range(940, 1060):
        for x in range(0, 120):
            im.putpixel((x, y), (200, 30, 30))
    im.save(p, "JPEG", quality=95)

    from app.db import Library
    from app import media
    lib = Library(D)
    lib.fill_species()
    code = lib.conn.execute("SELECT code FROM species LIMIT 1").fetchone()["code"]
    pid = lib.add_photo(str(p), media.file_hash(p), p.stat().st_size,
                        p.stat().st_mtime, 2000, 2000, 0)
    lib.add_records(pid, [{"species_code": code, "confidence": 0.9}])

    def px(pm, x, y):
        c = pm.toImage().pixelColor(x, y)
        return (c.red(), c.green(), c.blue())

    def is_red(c):
        return c[0] > 150 and c[1] < 90 and c[2] < 90

    print("\n[1] 结构: 左预览右选项+默认最大化")
    from app.ui.share_dialog import ShareDialog
    dlg = ShareDialog(lib, None, pid)
    dlg.show()
    app.processEvents()
    scr = QGuiApplication.primaryScreen().availableGeometry()
    check(not dlg.isMaximized()
          and dlg.height() >= scr.height() - 140
          and dlg.width() <= round((scr.height() - 48) * 0.78) + 470,
          f"默认窗口=竖向满屏横向紧凑, 不最大化 "
          f"({dlg.width()}×{dlg.height()}, 屏 {scr.width()}×{scr.height()})")
    dlg.showNormal()
    app.processEvents()
    check(all(hasattr(dlg, w) for w in
              ("scroll", "preview_host", "zoom_slider", "auto_btn",
               "vz_in", "vz_out", "vz_fit", "vz_100", "vz_pct",
               "crop_hint", "crop_hint2")),
          "左工具条/预览+右选项/构图卡控件齐全")
    check(dlg.zoom_slider.maximum() == 300 and dlg.zoom_slider.minimum() == 100,
          "滑杆范围100~300%")
    check(int(dlg.preview_host.alignment() & Qt.AlignCenter) != 0,
          "预览居中对齐(0.8.5实测修: 左对齐=卡贴左+拖动命中偏移)")

    print("\n[2] 自动渲染基线(k=1; 分界线钉1.0保ph=1877几何, 无裁切默认另测[11])")
    dlg._ts_touched = True               # 钉住1.0: [2]~[6]几何按ph=1877设计
    dlg._tscale = 1.0
    dlg._update()
    check(dlg.pm.width() == 1600, f"卡宽=1600(env钩子) 实际{dlg.pm.width()}")
    check(dlg._lay_key == "3:5", f"方图auto→3:5 实际{dlg._lay_key}")
    check(dlg._zh == 1877, f"照片区高1877 实际{dlg._zh}")
    base_c = px(dlg.pm, 30, 940)
    check(not is_red(base_c),
          f"自动居中(ox=0.5,sx=138.5)左缘红块被裁 {base_c}")
    check(dlg._adjust is None and not dlg.auto_btn.isEnabled()
          and dlg.zoom_slider.isEnabled(),
          "初始=自动(复位钮灰), 手动可用")

    print("\n[3] 手动平移(直接调_pan_by, env钉1600; 0.8.5修=抓取式跟手)")
    dlg._ensure_adjust()
    check(dlg._adjust["zoom"] == 1.0
          and abs(dlg._adjust["ox"] - 0.5) < 1e-6,
          f"进入手动=自动起点(zoom1/ox0.5) {dlg._adjust}")
    dlg._pan_by(138.5, 0)                  # 手往右→窗口左移 sx 138.5→0
    check(abs(dlg._adjust["ox"]) < 0.01,
          f"右拖→窗口左移到ox=0 {dlg._adjust['ox']:.3f}")
    check(is_red(px(dlg.pm, 30, 940)),
          f"跟手方向: 右拖后左缘红块入卡 {px(dlg.pm, 30, 940)}")
    dlg._pan_by(-400, 0)                   # 手往左越界→夹紧ox=1
    check(abs(dlg._adjust["ox"] - 1.0) < 0.01, "左拖越界夹紧ox=1")
    dlg._pan_by(5000, 0)                   # 手往右越界→夹紧ox=0
    check(abs(dlg._adjust["ox"]) < 0.01, "右拖越界夹紧ox=0")
    check(dlg.auto_btn.isEnabled(), "手动后复位钮亮")

    print("\n[4] 滚轮缩放(锚=光标: 该点画面不动)")
    dlg._reset_adjust()
    dlg._ensure_adjust()
    dlg._pan_by(138.5, 0)                  # 右拖→ox=0 红块贴左(0.8.5跟手方向)
    dlg._crop_zoom(0, 940, 1.5)             # 锚在左缘: 缩放后左缘仍是照片左缘
    check(abs(dlg._adjust["zoom"] - 1.5) < 1e-6,
          f"zoom=1.5 {dlg._adjust['zoom']}")
    check(dlg.zoom_slider.value() == 150
          and dlg.zoom_label.text() == "150%",
          "滑杆/标签同步150")
    check(is_red(px(dlg.pm, 30, 940)),
          f"锚左缘: 红块仍在左缘 {px(dlg.pm, 30, 940)}")
    dlg._reset_adjust()
    dlg._ensure_adjust()
    dlg._pan_by(-138.5, 0)
    dlg._crop_zoom(1600, 940, 1.5)          # 锚在右缘: 窗口右移吃掉左块
    check(not is_red(px(dlg.pm, 30, 940)),
          f"锚右缘: 左缘红块出窗 {px(dlg.pm, 30, 940)}")
    for _ in range(12):                     # 连打上限
        dlg._crop_zoom(0, 940, 2.0)
    check(dlg._adjust["zoom"] == 3.0, "zoom钳上限3.0")

    print("\n[5] 事件链路(_PreviewLabel转发+press/move/release)")
    dlg._reset_adjust()
    app.processEvents()
    pvpm = dlg.preview_host.pixmap()
    check(pvpm is not None and not pvpm.isNull(),
          f"预览pixmap已设 {pvpm.width() if pvpm else 0}px")
    from PySide6.QtGui import QMouseEvent

    def mev(tp, lx, ly, gx, gy, btn=Qt.NoButton, mod=Qt.NoModifier):
        return QMouseEvent(tp, QPointF(lx, ly), QPointF(gx, gy),
                           Qt.LeftButton, btn, mod)

    cx = dlg.preview_host.width() / 2        # pixmap居中→中心即卡中心
    cy = dlg.preview_host.height() / 2
    dlg.preview_host.mousePressEvent(
        mev(QEvent.MouseButtonPress, cx, cy, 500, 500, Qt.LeftButton))
    check(dlg._drag is not None, "照片区内按下=进入拖动")
    dlg.preview_host.mouseMoveEvent(
        mev(QEvent.MouseMove, cx, cy, 500, 500))
    dlg._pv_move(mev(QEvent.MouseMove, cx, cy,
                     500 + dlg._view_s * 300, 500))   # 右拖300物理px(跟手)
    check(dlg._adjust is not None and abs(dlg._adjust["ox"]) < 0.05,
          f"右拖→照片跟手右移, ox趋向0 {dlg._adjust['ox']:.3f}")
    dlg.preview_host.mouseReleaseEvent(
        mev(QEvent.MouseButtonRelease, cx, cy, 500, 500, Qt.LeftButton))
    check(dlg._drag is None and dlg.pm.width() == 1600,
          "松手结束拖动并回全分辨率(env钉1600)")

    print("\n[6] 滑杆缩放(锚=窗口中心)+复位")
    dlg._reset_adjust()
    dlg.zoom_slider.setValue(200)           # 真信号→_on_slider全链路
    check(abs(dlg._adjust["zoom"] - 2.0) < 1e-6 and dlg.zoom_label.text() == "200%",
          f"滑杆200%→zoom2.0 {dlg._adjust['zoom']}")
    dlg._reset_adjust()
    check(dlg._adjust is None and dlg.zoom_slider.value() == 100
          and not dlg.auto_btn.isEnabled(),
          "复位=自动/滑杆回100/复位钮灰")
    check(not is_red(px(dlg.pm, 30, 940)), "复位后回自动居中(红块又裁)")

    print("\n[7] classic: 手动构图禁用(历史行为不动)")
    dlg.lay_seg.setCurrent(3)               # setCurrent不发changed(坑): 手动_update
    dlg._update()
    check(dlg._lay_key is None and not dlg.zoom_slider.isEnabled()
          and not dlg.auto_btn.isEnabled() and not dlg.crop_hint2.isEnabled(),
          "classic→构图卡整体禁用")
    check(dlg.pm.width() == 1600, "classic正常渲染")

    print("\n[8] 视图缩放(看图辅助, 不动出片)")
    dlg.lay_seg.setCurrent(0)
    dlg._update()
    dlg._view_set(1.0)
    app.processEvents()
    check(dlg.preview_host.pixmap().width() == dlg.pm.width()
          and "100" in dlg.vz_pct.text(),
          f"100%=原尺寸像素 {dlg.preview_host.pixmap().width()}")
    dlg._view_zoom(1.25)
    app.processEvents()
    check(abs(dlg._view_s - 1.25) < 0.02, f"＋一档125% 实际{dlg._view_s:.2f}")
    dlg._view_fit()
    app.processEvents()
    check(dlg._view["mode"] == "fit" and dlg.vz_pct.text() == "适应",
          "适应窗口回fit")

    print("\n[9] 换版式保持手动构图")
    dlg._reset_adjust()
    dlg._ensure_adjust()
    dlg._pan_by(-138.5, 0)
    z, ox = dlg._adjust["zoom"], dlg._adjust["ox"]
    dlg.lay_seg.setCurrent(2)               # 3:4
    dlg._update()
    check(dlg._lay_key == "3:4" and dlg._adjust is not None
          and dlg._adjust["zoom"] == z and abs(dlg._adjust["ox"] - ox) < 1e-6,
          f"3:5→3:4手动参数保持 {dlg._adjust}")

    print("\n[10] 交界线拖动: 文字区缩放/磁吸/夹紧/复位/参考线(0.8.6)")
    from app.core.sharecard import TEXT_SCALE_MAX, TEXT_SCALE_MIN
    p2 = D / "t2.jpg"
    im2 = Image.new("RGB", (1000, 1100), (110, 130, 150))   # r=1.1竖
    im2.save(p2)
    pid2 = lib.add_photo(str(p2), media.file_hash(p2), p2.stat().st_size,
                         p2.stat().st_mtime, 1000, 1100, 0)
    lib.add_records(pid2, [{"species_code": code, "confidence": 0.9}])
    dlg2 = ShareDialog(lib, None, pid2)
    dlg2.showNormal()
    app.processEvents()
    gy, note = dlg2._no_crop_guide()
    check(gy == 1760 and note is None,
          f"参考线可达: r=1.1照片→ph_nc=1760无注释 ({gy} {note})")
    check(abs(dlg2._tscale * 790 - 907) < 0.6,
          f"0.8.6自动默认分界线=无裁切线: r=1.1打开即th=907 "
          f"(ts={dlg2._tscale:.4f})")
    z0 = dlg2._zh
    dlg2._bdrag_th(100)   # 0.8.6实测修方向: 下拖=分界线跟手下移=照片区变大
    check(abs(dlg2._tscale * 790 - 807) < 0.6
          and dlg2._zh > z0 and dlg2.pm.height() == 2667,
          f"跟手: 从无裁切默认907下拖100→th=807/照片区变大/卡高不变 "
          f"(ts={dlg2._tscale:.3f} zh {z0}→{dlg2._zh} h={dlg2.pm.height()})")
    dlg2._bdrag_th(6000)                 # 继续下拖越界→文字区下限0.75
    check(dlg2._tscale == TEXT_SCALE_MIN,
          f"下拖越界夹紧下限0.75 (ts={dlg2._tscale})")
    dlg2._bdrag_th(-6000)                # 上拖越界→文字区上限1.35
    check(dlg2._tscale == TEXT_SCALE_MAX,
          f"上拖越界夹紧上限1.35 (ts={dlg2._tscale})")
    dlg2._tscale = 1.0
    dlg2._update()
    dlg2._bdrag_th(-120)                 # 上拖: th=910, 距无裁切907<24→磁吸
    check(abs(dlg2._tscale * 790 - 907) < 0.6,
          f"磁吸无裁切点(910→907) th={dlg2._tscale * 790:.1f}")
    gy2, note2 = dlg._no_crop_guide()    # 主dlg=2000x2000方图已切3:4(见[9])
    check(gy2 is not None and abs(gy2 - 1118) < 1.5 and note2 is None,
          f"参考线bleed边界分支: 方图3:4→lo=0.7·ph_nc≈1120可达 "
          f"({gy2} {note2})")
    # 双击交界线复位 + 交界带按下优先于照片拖动
    dlg2._tscale = TEXT_SCALE_MAX
    dlg2._update()
    lbl = dlg2.preview_host
    dpm = lbl.pixmap()
    oy = (lbl.height() - dpm.height()) / 2
    yb = oy + dlg2._zh * dlg2._view_s
    dlg2._pv_press(mev(QEvent.MouseButtonPress, lbl.width() / 2, yb,
                       500, 500, Qt.LeftButton))
    check(dlg2._bdrag is not None and dlg2._drag is None,
          "交界带按下=交界拖动(非照片拖动)")
    dlg2._pv_release(mev(QEvent.MouseButtonRelease, 0, 0, 0, 0))
    check(dlg2._bdrag is None, "松手交界拖动结束")
    dlg2._pv_dbl(mev(QEvent.MouseButtonDblClick, lbl.width() / 2, yb,
                     0, 0))
    check(abs(dlg2._tscale * 790 - 907) < 0.6,
          f"双击交界线=复位到自动(0.8.6: 自动默认=无裁切线907, 非死1.0) "
          f"(ts={dlg2._tscale:.4f})")

    print("\n[11] 0.8.6修: 无裁切线按原图双边界 + letterbox负偏移居中")
    from app.core.sharecard import (auto_text_scale, nocrop_line,
                                    photo_placement)
    # 3:5可拖范围pmin=1601/pmax=2075(设计): 按原图比例分类逐档验证
    for w, h, want_kind, want_ph in (
            (1892, 3363, "lo", 0.7 * 1600 * 3363 / 1892),   # 9:16竖(用户卡)
            (800, 1200, "lo", 1680.0),                       # 2:3竖
            (1000, 1100, "exact", 1760.0),                   # 精确整图可达
            (2000, 2000, "off_wide", 1601),                  # 方图(差1px不可达)
            (1200, 1600, "off_tall", 2075),                  # 3:4竖全cover带
            (1200, 800, "all", None),                        # 3:2横全程bleed
            (1360, 1200, "hi", 1600 * (1200 / 1360) / 0.7)):  # 横图bleed上界
        ph, kind = nocrop_line(w, h, "3:5")
        check(kind == want_kind
              and (want_ph is None and ph is None
                   or (want_ph is not None and ph is not None
                       and abs(ph - want_ph) < 1.5)),
              f"nocrop_line({w}x{h})→{want_kind}"
              f"@{round(want_ph, 1) if want_ph else None} 实际{kind}@{ph}")
    for w, h, want_ts in ((1892, 3363, (2667 - (0.7 * 1600 * 3363 / 1892 - 2)) / 790),
                          (1000, 1100, 907 / 790),
                          (2000, 2000, 1066 / 790),
                          (1200, 1600, 0.75),
                          (1200, 800, 1.0)):
        ts = auto_text_scale(w, h, "3:5")
        check(abs(ts - want_ts) < 0.005,
              f"auto_text_scale({w}x{h})={want_ts:.4f} 实际{ts:.4f}")
    # letterbox符号回归(用户9:16卡根因): 负偏移=居中留边
    pl = photo_placement(1892, 3363, 2000, 2346)
    check(pl["w"] == 1320 and pl["rx"] == 0
          and abs(pl["sx"] + 340) < 1 and pl["sy"] == 0 and pl["ry"] == 0,
          f"自动bleed letterbox: sx负值-340居中(旧=+340画在-sx推出左边) {pl}")
    pl2 = photo_placement(1892, 3363, 2000, 2346,
                          adjust={"zoom": 1.0, "ox": 0.0, "oy": 0.0})
    check(abs(pl2["sx"] + 340) < 1,
          f"手动zoom1 letterbox: sx同负值居中(ox无效) {pl2}")
    pl3 = photo_placement(1892, 3363, 2000, 2346,
                          adjust={"zoom": 1.6, "ox": 0.5, "oy": 0.5})
    check(pl3["rx"] == 112 and abs(pl3["sx"] - 56) < 1,
          f"zoom1.6跨letterbox→cover: ox=0.5居中(锚点数学修复后) {pl3}")

    print("\n[12] 右栏宽自适应(0.8.6英文实测: 段名/动作钮两端裁切→sizeHint驱动)")
    from app import i18n as _i18n
    from PySide6.QtWidgets import QPushButton as _QP
    from app.ui.viewer import PhotoViewer
    for lg in ("en", "zh"):
        _i18n.set_lang(lg)
        d = ShareDialog(lib, None, pid)
        d.showNormal()
        app.processEvents()
        allb = [b for b in d.findChildren(_QP)
                if b.text() and len(b.text()) > 1]   # −/＋=刻意固定34px单字符钮
        bad = [b.text() for b in allb if b.width() < b.sizeHint().width() - 2]
        check(not bad, f"[{lg}] 分享卡全部按钮文字完整(宽≥sizeHint) 裁切:{bad}")
        check(340 <= d._panel_w <= 520,
              f"[{lg}] 面板宽在宽松界[340,520]: {d._panel_w}")
        if lg == "en":
            check([b.text() for b in d.res_seg.buttons]
                  == ["2000", "3000", "Original"],
                  f"分辨率英文段名缩短: {[b.text() for b in d.res_seg.buttons]}")
        d.close()
        pv = PhotoViewer(lib, None, pid, [pid])
        pv.show()
        app.processEvents()
        vbad = [b.text() for b in (pv.rebox_btn, pv.share_btn, pv.spot_btn,
                                   pv.remove_btn)
                if b.width() < b.sizeHint().width() - 2]
        check(not vbad, f"[{lg}] 查看器动作钮文字完整 裁切:{vbad}")
        pv.close()
    _i18n.set_lang("zh")

    lib.close()
    print()
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
