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
    check(dlg.isMaximized(), "默认最大化打开(0.8.4鸟点详情同款)")
    dlg.showNormal()
    app.processEvents()
    check(all(hasattr(dlg, w) for w in
              ("scroll", "preview_host", "zoom_slider", "auto_btn",
               "vz_in", "vz_out", "vz_fit", "vz_100", "vz_pct",
               "crop_hint", "crop_hint2")),
          "左工具条/预览+右选项/构图卡控件齐全")
    check(dlg.zoom_slider.maximum() == 300 and dlg.zoom_slider.minimum() == 100,
          "滑杆范围100~300%")

    print("\n[2] 自动渲染基线(k=1)")
    check(dlg.pm.width() == 1600, f"卡宽=1600(env钩子) 实际{dlg.pm.width()}")
    check(dlg._lay_key == "3:5", f"方图auto→3:5 实际{dlg._lay_key}")
    check(dlg._zh == 1877, f"照片区高1877 实际{dlg._zh}")
    base_c = px(dlg.pm, 30, 940)
    check(not is_red(base_c),
          f"自动居中(ox=0.5,sx=138.5)左缘红块被裁 {base_c}")
    check(dlg._adjust is None and not dlg.auto_btn.isEnabled()
          and dlg.zoom_slider.isEnabled(),
          "初始=自动(复位钮灰), 手动可用")

    print("\n[3] 手动平移(直接调_pan_by, env钉1600)")
    dlg._ensure_adjust()
    check(dlg._adjust["zoom"] == 1.0
          and abs(dlg._adjust["ox"] - 0.5) < 1e-6,
          f"进入手动=自动起点(zoom1/ox0.5) {dlg._adjust}")
    dlg._pan_by(-138.5, 0)                  # sx 138.5→0 = 贴左缘
    check(abs(dlg._adjust["ox"]) < 0.01, f"平移到左缘ox=0 {dlg._adjust['ox']:.3f}")
    check(is_red(px(dlg.pm, 30, 940)),
          f"左缘红块入卡 {px(dlg.pm, 30, 940)}")
    dlg._pan_by(400, 0)                     # 越界→夹紧ox=1
    check(abs(dlg._adjust["ox"] - 1.0) < 0.01, "继续右推夹紧ox=1")
    dlg._pan_by(-5000, 0)                   # 越界→夹紧ox=0
    check(abs(dlg._adjust["ox"]) < 0.01, "反向越界夹紧ox=0")
    check(dlg.auto_btn.isEnabled(), "手动后复位钮亮")

    print("\n[4] 滚轮缩放(锚=光标: 该点画面不动)")
    dlg._reset_adjust()
    dlg._ensure_adjust()
    dlg._pan_by(-138.5, 0)                  # ox=0 红块贴左
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
                     500 - dlg._view_s * 300, 500))   # 左拖300物理px
    check(dlg._adjust is not None and abs(dlg._adjust["ox"]) < 0.05,
          f"左拖→ox趋向0 {dlg._adjust['ox']:.3f}")
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

    lib.close()
    print()
    if FAILED["v"]:
        print("FAILED")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
