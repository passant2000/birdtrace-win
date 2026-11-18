# -*- coding: utf-8 -*-
"""连拍组级操作(0.8.6用户: "连拍有时候一组都识别错" P1+P2):

- change_group_species: 弹一次选鸟器, 整组写人工确认(set_species_batch,
  现成API; 人工结果后续自动统一绝不改写)
- reidentify_group: 整组重识别＝多取景全局最优(GroupRescueWorker)——
  连拍各帧近乎同画面, 模型错误相关, 组内投票救不回; 但各帧姿态不同,
  换取景常有一帧认对。识别管线只读(用户红线), 只调现成子进程协议。

时间线连拍封面右键菜单与查看器组内浏览按钮共用本模块。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from ..i18n import t


def group_photo_ids(lib, photo_id: int) -> list[int]:
    """连拍组全部photo_id(按拍摄时间升序); 无组返回[photo_id]。"""
    row = lib.conn.execute(
        "SELECT group_id FROM photos WHERE id=?", (photo_id,)).fetchone()
    gid = row["group_id"] if row else None
    if not gid:
        return [photo_id]
    rows = lib.conn.execute(
        "SELECT p.id FROM photos p LEFT JOIN exif e ON e.photo_id=p.id "
        "WHERE p.group_id=? "
        "ORDER BY COALESCE(e.dt_original, p.added_at), p.id", (gid,)).fetchall()
    return [r["id"] for r in rows] or [photo_id]


def _after_change(lib, win):
    """改判/救回后刷新各页(时间线数据签名不含confirmed→必须force)。"""
    if win is None:
        return
    if hasattr(win, "library_changed"):
        try:
            win.library_changed.emit()
        except RuntimeError:
            pass
    pages = getattr(win, "pages", {}) or {}
    tl = pages.get("timeline")
    if tl is not None and hasattr(tl, "refresh"):
        tl.refresh(force=True)


def change_group_species(lib, win, parent, photo_id: int,
                         code: str | None = None):
    """P1: 整组一键改判——弹一次选鸟器, 全组写人工确认并复核标记。"""
    ids = group_photo_ids(lib, photo_id)
    if code is None:
        from .species_pick import SpeciesPickDialog
        dlg = SpeciesPickDialog(
            lib, t(f"整组改鸟种 · {len(ids)} 张",
                   f"Change species for {len(ids)} photos"), parent)
        if not dlg.exec():
            return
        code = dlg.selected_code
    if not code:
        return
    n = lib.set_species_batch(ids, code)
    _after_change(lib, win)
    if parent is not None:
        QMessageBox.information(
            parent, t("整组改鸟种", "Change group species"),
            t(f"已把这 {len(ids)} 张连拍整组改判，共更新 {n} 条记录。\n"
              "人工改判后续自动识别/连拍统一不会再改动。",
              f"Re-assigned the whole {len(ids)}-photo burst; {n} records "
              "updated.\nManual verdicts are never overwritten by automatic "
              "re-identification or burst unification."))


def reidentify_group(lib, win, parent, photo_id: int,
                     assets=None, on_done=None):
    """P2: 整组重识别(多取景全局最优), 带进度窗; on_done(summary)回调。"""
    ids = group_photo_ids(lib, photo_id)
    assets = assets or getattr(win, "assets", None)
    if assets is None:
        if parent is not None:
            QMessageBox.warning(parent, t("整组重新识别", "Re-identify burst"),
                                t("无法定位模型资产目录", "Assets directory not found"))
        return
    r = QMessageBox.question(
        parent, t("整组重新识别", "Re-identify burst"),
        t(f"对这 {len(ids)} 张连拍整组重新识别？\n\n"
          "每帧会尝试多种取景、取全局最优结果应用到整组（连拍各帧姿态"
          "不同，常有一帧换个取景就认对）。现有的识别结果（包括人工"
          "确认过的）会被覆盖。",
          f"Re-identify this {len(ids)}-photo burst?\n\n"
          "Each frame is tried with several crops and the globally best "
          "result is applied to the whole group (different frames often "
          "catch a clearer pose). Existing results — including manual "
          "confirmations — will be overwritten."),
        QMessageBox.Yes | QMessageBox.No)
    if r != QMessageBox.Yes:
        return
    from ..core.worker import GroupRescueWorker
    worker = GroupRescueWorker(lib, assets, ids)
    dlg = QProgressDialog(
        t("整组重新识别（多取景取全局最优）…",
          "Re-identifying burst (best of crops)…"),
        t("取消", "Cancel"), 0, max(1, len(ids)), parent)
    dlg.setWindowTitle(t("整组重新识别", "Re-identify burst"))
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.show()

    def _prog(done: int, total: int, name: str):
        dlg.setMaximum(max(1, total))
        dlg.setValue(min(done, total))
        if name:
            dlg.setLabelText(name)

    def _fin(summary: dict):
        dlg.close()
        worker.wait()
        _after_change(lib, win)
        if summary.get("ok"):
            info = lib.species_info(summary.get("species")) or {}
            QMessageBox.information(
                parent, t("整组重新识别完成", "Burst re-identified"),
                t(f"整组 {summary['changed']} 张已统一为："
                  f"{info.get('cn') or summary.get('species')}"
                  f"（置信 {summary.get('confidence', 0):.0%}）。",
                  f"The whole burst ({summary['changed']} photos) is now: "
                  f"{info.get('en') or summary.get('species')} "
                  f"({summary.get('confidence', 0):.0%})."))
        elif summary.get("error") == "cancelled":
            pass
        else:
            QMessageBox.warning(
                parent, t("整组重新识别", "Re-identify burst"),
                t("这组各帧各种取景都没能认出鸟（无检测或非鸟门拦下），"
                  "记录已清空归入未识别。",
                  "No bird could be named in any frame with any crop "
                  "(nothing detected or filtered as non-bird); records were "
                  "cleared back to unidentified."))
        if on_done:
            on_done(summary)

    worker.progress.connect(_prog)
    worker.finished_group.connect(_fin)
    dlg.canceled.connect(worker.stop)
    worker.start()


def make_group_menu(lib, win, photo_id: int, parent_widget, global_pos):
    """连拍封面/组内右键菜单: 整组改鸟种 / 整组重新识别。无组不弹。"""
    ids = group_photo_ids(lib, photo_id)
    if len(ids) < 2:
        return False
    from PySide6.QtWidgets import QMenu
    menu = QMenu(parent_widget)
    a1 = menu.addAction(t("整组改鸟种…", "Change species for whole burst…"))
    a2 = menu.addAction(t("整组重新识别（多取景）…",
                          "Re-identify burst (multi-crop)…"))
    act = menu.exec(global_pos)
    if act == a1:
        change_group_species(lib, win, parent_widget, photo_id)
    elif act == a2:
        reidentify_group(lib, win, parent_widget, photo_id)
    return True
