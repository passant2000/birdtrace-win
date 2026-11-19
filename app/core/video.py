# -*- coding: utf-8 -*-
"""⑬视频归档(实测反馈10d, 2026-11-19用户拍板开发; 范围=归档/识别/播放,
不做剪辑): 全部走 Qt 自带 QtMultimedia(内含 ffmpeg 后端)——零新增打包
依赖、无 LGPL 捆绑顾虑。能力: 探时长/抽帧(缩略图与识别用)/判定。
QMediaPlayer 必须在 GUI 线程使用; 所有函数供 GUI 上下文调用。"""
from __future__ import annotations

from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv"}


def is_video(path: str | Path) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTS


def probe_duration(path: str | Path, timeout_ms: int = 10000) -> float | None:
    """视频时长(秒)。QMediaPlayer 加载→durationChanged/超时。"""
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtMultimedia import QMediaPlayer
    player = QMediaPlayer()
    loop = QEventLoop()
    got: list[float] = []

    def _on_dur(d):
        if d > 0:
            got.append(d / 1000.0)
            loop.quit()
    player.durationChanged.connect(_on_dur)
    player.mediaStatusChanged.connect(
        lambda st: loop.quit() if st in (
            QMediaPlayer.MediaStatus.InvalidMedia,
            QMediaPlayer.MediaStatus.EndOfMedia) else None)
    player.setSource(QUrl.fromLocalFile(str(path)))
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    player.stop()
    player.setSource(QUrl())
    return round(got[0], 2) if got else None


def extract_frame(path: str | Path, at_ms: int = 0,
                  timeout_ms: int = 12000):
    """抽指定时间点一帧 → QImage(None=失败)。供缩略图/抽帧识别。"""
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtGui import QImage
    from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
    player = QMediaPlayer()
    sink = QVideoSink()
    player.setVideoSink(sink)
    loop = QEventLoop()
    got: list[QImage] = []
    target = {"ms": at_ms}

    def _on_frame(frame):
        f = frame.toImage()
        if not f.isNull() and (target["ms"] <= 0 or
                               player.position() >= target["ms"] - 400):
            got.append(f)
            loop.quit()
    sink.videoFrameChanged.connect(_on_frame)
    player.mediaStatusChanged.connect(
        lambda st: loop.quit() if st == QMediaPlayer.MediaStatus.InvalidMedia
        else None)
    player.setSource(QUrl.fromLocalFile(str(path)))
    if target["ms"] > 0:
        player.play()
        QTimer.singleShot(700, lambda: player.setPosition(target["ms"]))
    else:
        player.play()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    player.stop()
    player.setSource(QUrl())
    return got[0] if got else None


def extract_frames(path: str | Path, duration_s: float | None,
                   picks=(0.02, 0.5, 0.9), timeout_ms: int = 12000):
    """抽帧识别用: 首/中/尾三个比例点各抽一帧(有时长才走中尾)。"""
    frames = []
    if duration_s and duration_s > 1.0:
        for frac in picks:
            img = extract_frame(path, int(duration_s * 1000 * frac),
                                timeout_ms)
            if img is not None:
                frames.append(img)
    else:
        img = extract_frame(path, 0, timeout_ms)
        if img is not None:
            frames.append(img)
    return frames
