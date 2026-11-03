# -*- coding: utf-8 -*-
"""迁徙地图: 世界级52周迁徙动画(与安卓同源——接作者迁徙服务)。

数据=app/core/migration.py 按需下载缓存(目录+物种包, SHA256校验),
活跃cell按周着色叠加在免Key高德底图上。对齐安卓交互:
- Annual week timeline: 52格季段时间线(manifest frames[].phase, APK
  Seasonal phase同源四段), 可点击/拖拽选周; 当前周高亮;
- 播放/上一周/下一周(安卓 Play/Previous week/Next week 同款);
- LOD随缩放自动升级(world→continental→regional→local, 数据本就在
  同一包内, 按视口bbox解码, 350ms防抖, 安卓按viewport选tile同思路);
- 本周该视野无模拟数据时地图中央提示(安卓 noPixels 同款);
- 图例/周标签含季段(繁殖期/非繁殖期/北迁期/南迁期)。

配色=一套色系(2026-11-02方案A, 取代与季段撞色的彩虹密度渐变):
色相=当前周季段(与时间线同义), 深浅=该周相对密度(单色4档),
全年常驻区(≥RESIDENT_MIN_WEEKS周活跃)加深色描边。

注意: WebEngine相关import全部在使用处(懒加载)——引用方也必须在按钮
回调里局部import本模块。JS侧零文案, 所有提示文字由Python注入。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from PySide6.QtCore import QRectF, QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                               QProgressBar, QToolTip, QVBoxLayout, QWidget)

from ..core.migration import (MigrationClient, MigrationError, decode_view,
                              decode_world, frame_phases, lod_for_zoom,
                              week_counts, world_geojson)
from ..i18n import t, sname
from ..paths import assets_dir
from .. import theme

# 周标签英文月名(数据格式, 不翻译)
_MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# 季段: key -> (色, (中, EN)) —— APK Seasonal phase 同源四段
_PHASES = {
    "breeding": ("#D9454B", ("繁殖期", "Breeding")),
    "nonBreeding": ("#3B66B3", ("非繁殖期", "Non-breeding")),
    "preBreedingMigration": ("#3E9BB8", ("北迁期", "Northbound migration")),
    "postBreedingMigration": ("#E08A2E", ("南迁期", "Southbound migration")),
}

# 常驻判定: 52周里活跃(值>0)周数≥此值 = 全年常驻区(深色描边)。2026-11-02
RESIDENT_MIN_WEEKS = 46


def phase_ramp(phase: str) -> list[str]:
    """密度=单色相深浅(2026-11-02方案A, 取代与季段撞色的彩虹渐变)。

    色相=当前周季段(与时间线同义: 时间线红周里地图即红色系),
    密度=该色相内浅→深4档; 未知季段回退中性灰。
    """
    base = QColor(_PHASES.get(phase, ("#8A8A8A", None))[0])
    out = []
    for mix, alpha in ((0.30, 0.45), (0.55, 0.58), (0.78, 0.70),
                       (1.0, 0.85)):
        r = int(base.red() * mix + 255 * (1 - mix))
        g = int(base.green() * mix + 255 * (1 - mix))
        b = int(base.blue() * mix + 255 * (1 - mix))
        out.append(f"rgba({r},{g},{b},{alpha})")
    return out

# 高德栅格瓦片style(同amap_view, 但minzoom放宽到1——世界视图需要z1~2)
_MIG_TILES_STYLE = (  # i18n:ok
    '{version:8,'
    ' sources:{amap:{type:"raster",tileSize:256,minzoom:1,maxzoom:18,'
    '  tiles:["https://webst01.is.autonavi.com/appmaptile?style=7&x={x}&y={y}&z={z}",'
    '         "https://webst02.is.autonavi.com/appmaptile?style=7&x={x}&y={y}&z={z}",'
    '         "https://webst03.is.autonavi.com/appmaptile?style=7&x={x}&y={y}&z={z}",'
    '         "https://webst04.is.autonavi.com/appmaptile?style=7&x={x}&y={y}&z={z}"],'
    '  attribution:"Amap"}},'  # i18n:ok
    ' layers:[{id:"amap",type:"raster",source:"amap"}]}'
)

# 强度配色: 单色相深浅(phase_ramp按周注入JS), 常驻区mig-res描边层
_HTML = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="maplibre-gl.css">
<style>
  html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;
    font-family:"Microsoft YaHei UI","PingFang SC",system-ui,sans-serif;}
  #container{width:100%;height:100%;}
  #nodata{position:absolute;top:42%;left:50%;transform:translate(-50%,-50%);
    display:none;z-index:9;background:rgba(28,28,30,.85);color:#fff;
    font-size:13px;padding:8px 16px;border-radius:10px;white-space:nowrap;}
</style>
<script src="maplibre-gl.js"></script>
<script>__QWEBCHANNEL__</script>
</head>
<body><div id="container"></div><div id="nodata"></div>
<script>
var map=null, bridge=null, READY=false, PENDING_DATA=null;
new QWebChannel(qt.webChannelTransport, function(ch){
  bridge=ch.objects.mmap;
  map=new maplibregl.Map({container:'container', center:[80,25], zoom:1.1,
    minZoom:1, maxZoom:12, style: __STYLE__, attributionControl:false});
  // report ready at once (do NOT wait 'load': it waits all initial tiles)
  bridge.mapReady();
  map.on('load', function(){
    READY=true;
    if(PENDING_DATA){ apiSetData.apply(null,PENDING_DATA); PENDING_DATA=null; }
    map.on('zoomend moveend', function(){
      if(!window.__MIG) return;
      var b=map.getBounds();
      bridge.viewport(map.getZoom(), b.getWest(), b.getSouth(),
                      b.getEast(), b.getNorth());
    });
  });
});
var RAMPS=[];   // per-week 4-step monochrome ramp (phase hue, from Python)
function rampExpr(w){
  var r=RAMPS[w]||RAMPS[RAMPS.length-1]||['rgba(138,138,138,0.45)',
    'rgba(160,160,160,0.58)','rgba(120,120,120,0.7)','rgba(90,90,90,0.85)'];
  return ['interpolate',['linear'],['at',w,['get','w']],
    1,r[0],85,r[1],170,r[2],255,r[3]];
}
function markResident(gj,rm){   // resident = active in >=rm weeks
  (gj.features||[]).forEach(function(f){
    var w=(f.properties&&f.properties.w)||[], n=0;
    for(var i=0;i<w.length;i++) if(w[i]>0) n++;
    f.properties.res=(n>=rm);
  });
}
function resFilter(i0){
  return ['all',['==',['get','res'],true],['>',['at',i0,['get','w']],0]];
}
function apiSetData(gj, counts, ramps, resMin){
  if(!READY){ PENDING_DATA=[gj,counts,ramps,resMin]; return; }
  RAMPS=ramps||[];
  markResident(gj, resMin||46);
  map.addSource('mig',{type:'geojson',data:gj});
  map.addLayer({id:'mig-fill',type:'fill',source:'mig',
    paint:{'fill-color':rampExpr(0),'fill-opacity':1}});
  map.addLayer({id:'mig-res',type:'line',source:'mig',filter:resFilter(0),
    paint:{'line-color':'rgba(38,50,56,0.9)','line-width':1.1}});
  window.__MIG={weeks:(gj.features.length?gj.features[0].properties.w.length:0),
    counts:counts, week:0, resMin:(resMin||46)};
  apiSetWeek(0);
}
function apiSetViewData(gj, counts){
  if(!READY || !map.getSource('mig')) return;
  markResident(gj, window.__MIG?window.__MIG.resMin:46);
  map.getSource('mig').setData(gj);
  window.__MIG.counts=counts;
  apiSetWeek(window.__MIG.week);
}
function apiSetWeek(i0){
  if(!window.__MIG || !map.getSource('mig')) return;
  window.__MIG.week=i0;
  map.setFilter('mig-fill',['all',['>',['at',i0,['get','w']],0]]);
  map.setFilter('mig-res',resFilter(i0));
  map.setPaintProperty('mig-fill','fill-color',rampExpr(i0));
  var nd=document.getElementById('nodata');
  if(nd) nd.style.display =
    (window.__MIG.counts && window.__MIG.counts[i0]>0)?'none':'block';
}
function apiSetHint(s){ document.getElementById('nodata').textContent=s; }
</script></body></html>
"""


def _qwebchannel_js() -> str:
    from PySide6.QtCore import QIODevice, QFile
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if f.open(QIODevice.ReadOnly):
        s = bytes(f.readAll()).decode("utf-8")
        f.close()
        return s
    return "console.error('qwebchannel.js missing');"


class _Bridge(QObject):
    """JS→Python: 地图就绪 + 视口变化(缩放联动LOD)。"""
    ready = Signal()
    viewChanged = Signal(float, float, float, float, float)

    @Slot()
    def mapReady(self):
        self.ready.emit()

    @Slot(float, float, float, float, float)
    def viewport(self, zoom: float, west: float, south: float,
                 east: float, north: float):
        self.viewChanged.emit(float(zoom), float(west), float(south),
                              float(east), float(north))


class _DownloadWorker(QThread):
    """目录+物种包下载(带进度/取消) → world LOD解码。"""
    progress = Signal(str, int, int)
    decoded = Signal(dict, dict, str)   # decoded, manifest, sqlite路径
    failed = Signal(object)             # MigrationError

    def __init__(self, lib_root: Path, code: str, parent=None):
        super().__init__(parent)
        self.lib_root = lib_root
        self.code = code
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            client = MigrationClient(self.lib_root)

            def cb(phase, cur, total):
                self.progress.emit(phase, cur, total)

            paths = client.fetch_species(
                self.code, cb, lambda: self._cancel)
            if self._cancel:
                return
            decoded = decode_world(paths["sqlite"])
            manifest = json.loads(
                Path(paths["manifest"]).read_text(encoding="utf-8"))
            self.decoded.emit(decoded, manifest, str(paths["sqlite"]))
        except MigrationError as e:
            if e.reason != "cancelled":
                self.failed.emit(e)
        except Exception as e:  # sqlite/json等异常统一按损坏处理
            self.failed.emit(MigrationError("corrupt", str(e)))


class _ViewWorker(QThread):
    """缩放联动: 视口bbox按LOD解码(数据已在本地包内, 无下载)。"""
    ready = Signal(int, dict, str)   # seq, decoded, lod

    def __init__(self, sqlite_path: Path, lod: str,
                 bbox: tuple | None, seq: int, parent=None):
        super().__init__(parent)
        self.sqlite_path = sqlite_path
        self.lod = lod
        self.bbox = bbox
        self.seq = seq

    def run(self):
        try:
            d = decode_view(self.sqlite_path, self.lod, self.bbox)
            self.ready.emit(self.seq, d, self.lod)
        except Exception:
            # 视口解码失败保持当前图层, 下次缩放再试; 留痕便于排查
            import traceback
            traceback.print_exc()


class _TimelineWidget(QWidget):
    """52格季段时间线(安卓 Annual week timeline): phase着色, 点击/拖拽选周。"""

    weekChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._week = 1
        self._weeks = 52
        self._phases: list[str] = []
        self._dates: list[str] = []
        self._pressing = False
        self.setMinimumHeight(40)
        self.setMouseTracking(True)

    def set_data(self, phases: list[str], dates: list[str]):
        self._phases = phases
        self._dates = dates
        self._weeks = max(1, len(dates))
        self.update()

    def weeks(self) -> int:
        return self._weeks

    def set_week(self, week: int):
        """程序设置(不回发信号, 供对话框同步)。"""
        self._week = max(1, min(self._weeks, int(week)))
        self.update()

    def week(self) -> int:
        return self._week

    def _pick(self, x: float) -> int:
        cw = self.width() / max(1, self._weeks)
        return max(1, min(self._weeks, int(x / cw) + 1))

    def mousePressEvent(self, ev):
        self._pressing = True
        self._set_user_week(self._pick(ev.position().x()))

    def mouseMoveEvent(self, ev):
        if self._pressing:
            self._set_user_week(self._pick(ev.position().x()))

    def mouseReleaseEvent(self, ev):
        self._pressing = False

    def _set_user_week(self, w: int):
        if w != self._week:
            self._week = w
            self.update()
            self.weekChanged.emit(w)

    def event(self, ev):
        from PySide6.QtCore import QEvent
        if ev.type() == QEvent.ToolTip and self._dates:
            w = self._pick(ev.pos().x())
            ph = self._phase_name(w)
            QToolTip.showText(ev.globalPos(), self._label(w, ph), self)
            return True
        return super().event(ev)

    def _phase_name(self, week: int) -> str:
        if 1 <= week <= len(self._phases):
            pair = _PHASES.get(self._phases[week - 1], (None, None))[1]
            if pair:
                return t(*pair)
        return t("—", "—")

    def _label(self, week: int, phase: str) -> str:
        date = self._dates[week - 1] if week <= len(self._dates) else ""
        return t(f"第{week}周 · {date} · {phase}",
                 f"Week {week} · {date} · {phase}")

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        w = self.width()
        h = self.height()
        n = self._weeks
        cw = w / n
        top = 12.0
        bh = h - top - 8.0
        # 月分隔刻度+月名(每月首格)
        f = p.font()
        f.setPixelSize(9)
        p.setFont(f)
        last_month = None
        for i, d in enumerate(self._dates[:n]):
            mm = d[5:7] if len(d) >= 7 else None
            if mm and mm != last_month:
                last_month = mm
                x = i * cw
                p.setPen(QColor(theme.LABEL_3))
                p.drawLine(int(x), int(top), int(x), int(top + bh))
                p.drawText(QRectF(x, 0, 34, 11), Qt.AlignLeft | Qt.AlignVCenter,
                           t(f"{int(mm)}月", _MONTHS_EN[int(mm) - 1]))
        # 52格phase色块
        for i in range(n):
            ph = self._phases[i] if i < len(self._phases) else ""
            color = _PHASES.get(ph, ("#A8A8A8", None))[0]
            c = QColor(color)
            c.setAlpha(150 if i + 1 != self._week else 255)
            p.fillRect(QRectF(i * cw + 0.5, top, cw - 1.0, bh), c)
        # 当前周框
        p.setPen(QPen(QColor(theme.LABEL), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF((self._week - 1) * cw + 1, top - 1, cw - 2, bh + 2))
        p.end()


class _Legend(QWidget):
    """密度深浅色带图例(动态: 随当前周季段换色相, 与地图ramp同源)。"""
    _POS = (0.0, 1 / 3, 2 / 3, 1.0)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._colors = self._parse(phase_ramp(""))   # 初始中性灰
        self.setFixedSize(140, 12)

    @staticmethod
    def _parse(ramp: list[str]) -> list[QColor]:
        out = []
        for s in ramp:
            m = re.match(r"rgba\((\d+),(\d+),(\d+),([\d.]+)\)", s)
            c = QColor(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            c.setAlphaF(float(m.group(4)))
            out.append(c)
        return out

    def set_phase(self, phase: str):
        colors = self._parse(phase_ramp(phase))
        if colors != self._colors:
            self._colors = colors
            self.update()

    def paintEvent(self, ev):
        grad = QLinearGradient(0, 0, self.width(), 0)
        for pos, c in zip(self._POS, self._colors):
            grad.setColorAt(pos, c)
        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        painter.setBrush(grad)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawRoundedRect(0, 1, self.width(), self.height() - 2, 5, 5)


class MigrationMapDialog(QDialog):
    """52周迁徙动画对话框(模态)。入口: 图鉴页「迁徙地图…」。"""

    def __init__(self, lib, win, code: str, parent=None):
        super().__init__(parent or win)
        self.lib = lib
        self.code = code
        self._labels: list[str] = []   # 先于时间线(其信号会触发_on_week)
        self._phases: list[str] = []
        self._js: list[str] = []
        self._ready = False
        self._data_ready = False
        self._timer = QTimer(self)
        self._timer.setInterval(900)
        self._timer.timeout.connect(self._advance)
        self._worker: _DownloadWorker | None = None
        self._view_worker: _ViewWorker | None = None
        self._lod = "world"
        self._view_seq = 0
        self._world_cache: tuple[dict, list] | None = None  # (gj, counts)
        self._view_timer = QTimer(self)
        self._view_timer.setSingleShot(True)
        self._view_timer.setInterval(350)
        self._view_timer.timeout.connect(self._do_view_decode)
        self._sqlite_path: Path | None = None

        sp = lib.species_info(code)
        name = sname(sp["cn"], sp["en"])
        self.setWindowTitle(t(f"{name} · 迁徙地图", f"{name} · Migration map"))
        self.resize(1100, 740)

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 10)
        v.setSpacing(6)

        # 状态条(下载进度/错误, 就绪后隐藏)
        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setStyleSheet("background:transparent;")
        self._bar = QProgressBar()
        self._bar.setFixedHeight(6)
        self._bar.setTextVisible(False)
        self._retry_btn = QPushButton(t("重试", "Retry"))
        self._retry_btn.clicked.connect(self._start_download)
        self._retry_btn.hide()
        srow = QHBoxLayout()
        srow.setSpacing(8)
        srow.addWidget(self._status, 1)
        srow.addWidget(self._bar, 2)
        srow.addWidget(self._retry_btn)
        v.addLayout(srow)

        # WebEngine懒import: 只在用户点击后构造本对话框
        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtWebEngineCore import QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView
        missing = assets_dir() / "map" / "maplibre-gl.js"
        if not missing.exists():
            raise FileNotFoundError(t(
                "缺少地图组件 assets/map/maplibre-gl.js —— "
                "请重新安装或按 README 获取 assets 资产",
                "Missing assets/map/maplibre-gl.js — reinstall or fetch "
                "assets per README"))
        self._bridge = _Bridge(self)
        self._bridge.ready.connect(self._on_map_ready)
        self._bridge.viewChanged.connect(self._on_viewport)
        self.web = QWebEngineView(self)
        st = self.web.settings()
        st.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        st.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        self._channel = QWebChannel(self)
        self._channel.registerObject("mmap", self._bridge)
        self.web.page().setWebChannel(self._channel)
        v.addWidget(self.web, 1)

        # 控制条: 上一周/播放/下一周 + 季段时间线 + 周标签(含季段胶囊)
        crow = QHBoxLayout()
        crow.setSpacing(8)
        self._prev_btn = QPushButton(t("‹ 上周", "‹ Prev"))
        self._next_btn = QPushButton(t("下周 ›", "Next ›"))
        self._play_btn = QPushButton("▶")
        for btn in (self._prev_btn, self._play_btn, self._next_btn):
            btn.setEnabled(False)
            btn.setCursor(Qt.PointingHandCursor)
        self._play_btn.setFixedWidth(44)
        self._prev_btn.setFixedWidth(64)
        self._next_btn.setFixedWidth(64)
        self._prev_btn.setToolTip(t("上一周", "Previous week"))
        self._next_btn.setToolTip(t("下一周", "Next week"))
        self._play_btn.setToolTip(t("播放 / 暂停", "Play / Pause"))
        self._prev_btn.clicked.connect(lambda: self._step(-1))
        self._next_btn.clicked.connect(lambda: self._step(1))
        self._play_btn.clicked.connect(self._toggle_play)
        crow.addWidget(self._prev_btn)
        crow.addWidget(self._play_btn)
        crow.addWidget(self._next_btn)
        self._timeline = _TimelineWidget()
        self._timeline.weekChanged.connect(self._on_week)
        crow.addWidget(self._timeline, 1)
        self._week_lbl = QLabel("")
        self._week_lbl.setStyleSheet(
            f"color:{theme.LABEL};background:transparent;min-width:170px;")
        crow.addWidget(self._week_lbl)
        v.addLayout(crow)

        # 图例行: 季段色块(=地图色相同义) + 密度深浅带(随当前周季段换色)
        # + 全年常驻描边项 —— 2026-11-02方案A: 一套色系, 深浅=密度
        lrow = QHBoxLayout()
        lrow.setSpacing(10)
        self._phase_tags: dict[str, tuple[QWidget, QWidget]] = {}
        for key in ("breeding", "preBreedingMigration", "nonBreeding",
                    "postBreedingMigration"):
            color, pair = _PHASES[key]
            dot = QWidget()
            dot.setFixedSize(10, 10)
            dot.setStyleSheet(f"background:{color};border-radius:3px;")
            lb = QLabel(t(*pair))
            lb.setStyleSheet(f"color:{theme.LABEL_2};font-size:11px;"
                             "background:transparent;")
            lb.setObjectName(f"phaselegend_{key}")
            lrow.addWidget(dot)
            lrow.addWidget(lb)
            self._phase_tags[key] = (dot, lb)
        lrow.addStretch(1)
        few = QLabel(t("少", "Few"))
        many = QLabel(t("多", "Many"))
        for lb in (few, many):
            lb.setStyleSheet(f"color:{theme.LABEL_3};background:transparent;")
        self._legend = _Legend()
        lrow.addWidget(few)
        lrow.addWidget(self._legend)
        lrow.addWidget(many)
        res_dot = QWidget()
        res_dot.setFixedSize(12, 12)
        res_dot.setStyleSheet(
            "background:rgba(38,50,56,0.12);"
            "border:2px solid rgba(38,50,56,0.9);border-radius:2px;")
        res_lb = QLabel(t("全年常驻", "Year-round resident"))
        res_lb.setStyleSheet(f"color:{theme.LABEL_2};font-size:11px;"
                             "background:transparent;")
        lrow.addWidget(res_dot)
        lrow.addWidget(res_lb)
        v.addLayout(lrow)

        hint = QLabel(t("色相=季段 · 深浅=该周相对数量 · 深色描边=全年常驻区 · "
                        "模拟的季节种群分布 · 数据源 eBird Status and Trends",
                        "Hue = season · Depth = relative abundance that week · "
                        "Dark outline = year-round range · Modeled seasonal "
                        "population distribution · Data: eBird Status and Trends"))
        hint.setStyleSheet(f"color:{theme.LABEL_3};font-size:12px;"
                           "background:transparent;")
        hint.setAlignment(Qt.AlignCenter)
        v.addWidget(hint)

        self._write_html_and_load()
        self._start_download()

    # ---- 页面装载 ----
    def _write_html_and_load(self):
        from PySide6.QtCore import QUrl
        map_js = (assets_dir() / "map" / "maplibre-gl.js").as_uri()
        map_css = (assets_dir() / "map" / "maplibre-gl.css").as_uri()
        html = (_HTML.replace("__STYLE__", _MIG_TILES_STYLE)
                .replace("__QWEBCHANNEL__", _qwebchannel_js())
                .replace('href="maplibre-gl.css"', f'href="{map_css}"')
                .replace('src="maplibre-gl.js"', f'src="{map_js}"'))
        html_path = self.lib.root / "migration_map.html"
        html_path.write_text(html, encoding="utf-8")
        self.web.load(QUrl.fromLocalFile(str(html_path)))

    def js(self, expr: str):
        if self._ready:
            self.web.page().runJavaScript(expr)
        else:
            self._js.append(expr)

    def _on_map_ready(self):
        self._ready = True
        for e in self._js:
            self.web.page().runJavaScript(e)
        self._js = []

    # ---- 下载 ----
    def _start_download(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self._retry_btn.hide()
        self._status.setText(t("正在获取迁徙目录…", "Fetching migration catalog…"))
        self._bar.setRange(0, 0)
        self._worker = _DownloadWorker(self.lib.root, self.code, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.decoded.connect(self._on_decoded)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, phase: str, cur: int, total: int):
        labels = {
            "catalog": t("正在获取迁徙目录…", "Fetching migration catalog…"),
            "sqlite": t("正在下载迁徙数据…", "Downloading migration data…"),
            "manifest": t("正在下载周历…", "Downloading week calendar…"),
        }
        self._status.setText(labels.get(phase, ""))
        if total > 0:
            self._bar.setRange(0, total)
            self._bar.setValue(cur)
        else:
            self._bar.setRange(0, 0)

    def _on_failed(self, err):
        self._bar.hide()
        texts = {
            "offline": t("无法连接迁徙服务(离线或网络不可用)",
                         "Cannot reach the migration service (offline)"),
            "http": t("迁徙服务连接失败", "Failed to reach the migration service"),
            "sha": t("下载校验失败, 请重试", "Checksum failed, please retry"),
            "corrupt": t("迁徙数据损坏, 请重试", "Migration data corrupted, please retry"),
            "not_in_catalog": t(
                "该鸟种暂无迁徙数据(迁徙图层覆盖约 3000 个常见物种)",
                "No migration data for this species "
                "(the migration layer covers ~3,000 common species)"),
        }
        self._status.setText(f"⚠ {texts.get(err.reason, str(err))}")
        self._retry_btn.setVisible(err.reason not in ("not_in_catalog",))

    def _on_decoded(self, decoded: dict, manifest: dict, sqlite_path: str):
        self._bar.hide()
        self._status.setText("")
        self._sqlite_path = Path(sqlite_path)
        weeks = decoded["weeks"]
        dates = [(f.get("date") or "") for f in (manifest.get("frames") or [])]
        phases = frame_phases(manifest)
        self._phases = phases
        self._labels = self._week_labels(dates, weeks)
        self._timeline.set_data(phases, dates[:weeks])
        self._timeline.set_week(1)
        self._timeline.setEnabled(True)
        for btn in (self._prev_btn, self._play_btn, self._next_btn):
            btn.setEnabled(True)
        self._data_ready = True
        gj = world_geojson(decoded)
        counts = week_counts(decoded)
        self._world_cache = (gj, counts)
        self._lod = "world"
        # 密度色带: 每周4档单色深浅(色相=该周季段), 注入JS
        ramps = [phase_ramp(phases[i] if i < len(phases) else "")
                 for i in range(weeks)]
        self.js(f"apiSetData({json.dumps(gj, ensure_ascii=False)}, "
                f"{json.dumps(counts)}, {json.dumps(ramps)}, "
                f"{RESIDENT_MIN_WEEKS})")
        self.js("apiSetHint(" + json.dumps(
            t("本周该视野无模拟数据", "No modeled pixels in this view for this week"),
            ensure_ascii=False) + ")")
        self._on_week(1)
        self._timer.start()

    @staticmethod
    def _week_labels(dates: list[str], weeks: int) -> list[str]:
        out = []
        for w in range(1, weeks + 1):
            date = dates[w - 1][:10] if w <= len(dates) else ""
            if date:
                yy, mm, dd = date.split("-")
                day = t(f"{int(mm)}月{int(dd)}日",
                        f"{_MONTHS_EN[int(mm) - 1]} {int(dd)}")
                out.append(t(f"第{w}周 · {day}", f"Week {w} · {day}"))
            else:
                out.append(t(f"第{w}周", f"Week {w}"))
        return out

    # ---- 周/播放 ----
    def _step(self, delta: int):
        w = self._timeline.week() + delta
        if w > 52:
            w = 1
        if w < 1:
            w = 52
        self._on_week(w)

    def _toggle_play(self):
        if self._timer.isActive():
            self._timer.stop()
            self._play_btn.setText("▶")
        else:
            self._timer.start()
            self._play_btn.setText("⏸")

    def _advance(self):
        w = self._timeline.week() + 1
        if w > self._timeline.weeks():
            w = 1
        self._on_week(w)

    def _on_week(self, week: int):
        self._timeline.set_week(week)
        self._week_lbl.setText(self._labels[week - 1] if
                               0 < week <= len(self._labels) else "")
        ph = self._phases[week - 1] if 0 < week <= len(
            getattr(self, "_phases", [])) else ""
        self._legend.set_phase(ph)   # 图例色带与地图同色相
        if self._data_ready:
            self.js(f"apiSetWeek({week - 1})")

    # ---- 缩放联动LOD ----
    def _on_viewport(self, zoom: float, west: float, south: float,
                     east: float, north: float):
        if not self._data_ready or self._sqlite_path is None:
            return
        lod = lod_for_zoom(zoom)
        if lod == "world":
            self._view_timer.stop()
            if self._lod != "world" and self._world_cache is not None:
                self._lod = "world"
                gj, counts = self._world_cache
                self.js(f"apiSetViewData({json.dumps(gj, ensure_ascii=False)}, "
                        f"{json.dumps(counts)})")
            return
        # world以外: bbox也可能变化, 统一走防抖重解码(解码<200ms, 350ms防抖)
        self._lod = lod
        self._pending = (lod, (west, south, east, north))
        self._view_timer.start()

    def _do_view_decode(self):
        if not self._data_ready or self._sqlite_path is None:
            return
        lod, bbox = self._pending
        self._view_seq += 1
        self._view_worker = _ViewWorker(self._sqlite_path, lod, bbox,
                                        self._view_seq, self)
        self._view_worker.ready.connect(self._on_view_decoded)
        self._view_worker.start()

    def _on_view_decoded(self, seq: int, decoded: dict, lod: str):
        if seq != self._view_seq or not self._data_ready:
            return  # 过期结果(视口又变了)
        gj = world_geojson({"weeks": decoded["weeks"],
                            "cells": [c[3:] for c in decoded["cells"]],
                            "values": decoded["values"]})
        counts = week_counts(decoded)
        self.js(f"apiSetViewData({json.dumps(gj, ensure_ascii=False)}, "
                f"{json.dumps(counts)})")

    def reject(self):
        self._shutdown()
        super().reject()

    def closeEvent(self, ev):
        self._shutdown()
        super().closeEvent(ev)

    def _shutdown(self):
        self._timer.stop()
        self._view_timer.stop()
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
        if self._view_worker is not None and self._view_worker.isRunning():
            self._view_worker.wait(2000)
