# -*- coding: utf-8 -*-
"""高德 JS API 交互地图: QWebEngineView + QWebChannel 桥。

- 地图渲染交给高德官方JS(内置浏览器控件, GCJ-02坐标系), 不再自绘瓦片;
- 鸟点/GPS坐标为WGS84真值: 传给地图前正向纠偏, 地图取点/取中心逆变换;
- JS API Key与安全密钥: 设置页 map_js_key / map_js_secret, 留空用内置值;
- 页面HTML写到 <库>/amap.html, Key变更后由 ensure_keys() 重新生成加载。
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from PySide6.QtCore import (QFile, QIODevice, QObject, Qt, QUrl, Signal, Slot)
from PySide6.QtCore import QTimer
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QLabel, QStackedWidget, QVBoxLayout, QWidget

from ..core.gcj02 import gcj02_to_wgs84, wgs84_to_gcj02

# 2026-10-31用户指示: 内置其三个高德Key(Web服务/JS API/安全密钥)但全部
# 混淆存放(异或+base64, 防对exe明文grep; 非对抗逆向的安全加密), 设置页
# 不回显。0.5.4包曾误带明文三Key已于2026-10-29移除, 本轮以混淆形式内置。
# 无Web服务Key时POI回退MapTiler, 其中文POI库缺世纪公园/滨江森林公园
# (2026-10-31实测, 5080机POI搜不到的根因)。


def _dec(s: str) -> str:
    import base64
    obf = base64.b64decode(s)
    mask = b"BirdTraceWin-POI-2026"
    return bytes(a ^ mask[i % len(mask)]
                 for i, a in enumerate(obf)).decode("ascii")


DEFAULT_WEB_KEY = _dec("JwhHAGVLUQdcb1AKGzJ3ehlUVVQAdw1HAWBLAlYHb10=")
DEFAULT_JS_KEY = _dec("J18UUGIWUQFWZFhYT2h9cUlTB1cEdF9EAmBFWQBVNgs=")
DEFAULT_JS_SECRET = _dec("ew9AVGZGWFEDM1FYFGJ5KkhRBgUFdAxAVmEQAwBVYFg=")

# 地名搜索(POI)默认走 MapTiler Geocoding, 用原作者团队Key——与安卓
# 同源(安卓dex里就是这个Key); 用量计在作者账户, 提示用户克制使用。
# 用户在设置页自填高德「Web服务」Key时优先走高德(中国POI更全)。
# 注意: MapTiler底图引擎因政治合规已移除, 此Key只用于地名搜索。
DEFAULT_MAPTILER_KEY = "QMZGF8IiSPfyUQeVTOEQ"

# MapLibre版页面(本地maplibre-gl.js + MapTiler style, 桥接口与高德版同构)
_HTML_MAPLIBRE = """<!--# i18n:ok: 页面内嵌中文占位文案, 浏览器渲染按数据豁免-->
<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="maplibre-gl.css">
<style>
  html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;
    font-family:"Microsoft YaHei UI","PingFang SC",system-ui,sans-serif;}
  #container{width:100%;height:100%;}
  .pin{text-align:center;line-height:1;cursor:pointer;}
  .pin img,.pin .noimg{width:42px;height:42px;border-radius:21px;
    border:3px solid #fff;box-shadow:0 1px 5px rgba(0,0,0,.35);object-fit:cover;}
  .pin .noimg{display:inline-block;background:#007AFF;color:#fff;
    font-size:22px;line-height:42px;}
  .pin .nm{display:inline-block;margin-top:3px;padding:1px 7px;border-radius:8px;
    background:rgba(255,255,255,.93);color:#1C1C1E;font-size:11px;font-weight:600;
    max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
    box-shadow:0 1px 3px rgba(0,0,0,.25);}
  .clu{width:44px;height:44px;border-radius:22px;background:rgba(255,149,0,.93);
    border:3px solid #fff;color:#fff;font-weight:700;font-size:14px;
    line-height:44px;text-align:center;box-shadow:0 1px 5px rgba(0,0,0,.35);
    cursor:pointer;}
</style>
<script src="maplibre-gl.js"></script>
<script>__QWEBCHANNEL__</script>
</head>
<body><div id="container"></div>
<script>
var map=null, bridge=null, pickMode=false, markerObjs=[], allSpots=[];
new QWebChannel(qt.webChannelTransport, function(ch){
  bridge=ch.objects.bmap;
  map=new maplibregl.Map({container:'container', center:[105,35], zoom:3,
    style: __STYLE__,
    attributionControl:false});
  function report(){
    var c=map.getCenter();
    bridge.mapMoved(c.lat, c.lng, map.getZoom());
  }
  map.on('moveend',report);
  map.on('click',function(e){
    if(pickMode) bridge.picked(e.lngLat.lat, e.lngLat.lng);
  });
  // 创建即上报(不等'load'——它要等全部初始瓦片, MapTiler国内较慢会拖死ready)
  report();
  bridge.mapReady();
  layoutMarkers();
  map.on('moveend',layoutMarkers);
  map.on('styledata',function(){ if(map.isStyleLoaded()){ layoutMarkers(); } });
});
function pinDiv(d){
  var div=document.createElement('div'); div.className='pin';
  var ph=d.thumb? "<img src='"+d.thumb+"'>" : "<span class='noimg'>\\ud83d\\udc26</span>";
  div.innerHTML=ph+"<div class='nm'>"+d.name+"</div>";
  div.addEventListener('click',function(ev){
    ev.stopPropagation();
    bridge.markerClicked(JSON.stringify(d));
  });
  return div;
}
function layoutMarkers(){
  if(!map||!map.isStyleLoaded()&&!map.loaded()){ setTimeout(layoutMarkers,300); return; }
  markerObjs.forEach(function(m){ m.remove(); });
  markerObjs=[];
  var groups=[];
  allSpots.forEach(function(d){
    var p=map.project([d.glng,d.glat]);
    var g=null;
    for(var i=0;i<groups.length;i++){
      var q=map.project([groups[i].spots[0].glng,groups[i].spots[0].glat]);
      if(Math.hypot(p.x-q.x,p.y-q.y)<56){ g=groups[i]; break; }
    }
    if(g){ g.spots.push(d); }
    else{ groups.push({spots:[d], x:p.x, y:p.y}); }
  });
  groups.forEach(function(g){
    if(g.spots.length===1){
      var m=new maplibregl.Marker({element:pinDiv(g.spots[0]), anchor:'bottom'})
        .setLngLat([g.spots[0].glng,g.spots[0].glat]).addTo(map);
      markerObjs.push(m);
    }else{
      var div=document.createElement('div'); div.className='clu';
      div.textContent=g.spots.length;
      var lat=0,lng=0;
      g.spots.forEach(function(s){ lat+=s.glat; lng+=s.glng; });
      lat/=g.spots.length; lng/=g.spots.length;
      div.addEventListener('click',function(ev){
        ev.stopPropagation();
        map.flyTo({center:[lng,lat], zoom:Math.min(19,map.getZoom()+2)});
      });
      var m=new maplibregl.Marker({element:div, anchor:'center'})
        .setLngLat([lng,lat]).addTo(map);
      markerObjs.push(m);
    }
  });
}
function apiSetSpots(spots, fit){
  allSpots=spots||[];
  if(map&&map.loaded()){ layoutMarkers(); }
  if(fit){ apiFit(spots); }
}
function apiFit(spots){
  if(!spots||!spots.length||!map){ return; }
  if(spots.length===1){
    map.jumpTo({center:[spots[0].glng,spots[0].glat], zoom:14}); return;
  }
  var b=new maplibregl.LngLatBounds();
  spots.forEach(function(s){ b.extend([s.glng,s.glat]); });
  map.fitBounds(b,{padding:70,maxZoom:16});
}
function apiFocus(lat,lng,z){ if(map){ map.flyTo({center:[lng,lat],zoom:z}); } }
function apiSetPick(on){ pickMode=on;
  var c=map.getContainer(); c.style.cursor=on?'crosshair':'';
}
</script></body></html>
"""


_HTML = """<!--# i18n:ok: 页面内嵌中文占位文案, 浏览器渲染按数据豁免-->
<!doctype html>
<html><head><meta charset="utf-8">
<style>
  html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;
    font-family:"Microsoft YaHei UI","PingFang SC",system-ui,sans-serif;}
  #container{width:100%;height:100%;}
  .pin{text-align:center;line-height:1;}
  .pin img,.pin .noimg{width:42px;height:42px;border-radius:21px;
    border:3px solid #fff;box-shadow:0 1px 5px rgba(0,0,0,.35);object-fit:cover;}
  .pin .noimg{display:inline-block;background:#007AFF;color:#fff;
    font-size:22px;line-height:42px;}
  .pin .nm{display:inline-block;margin-top:3px;padding:1px 7px;border-radius:8px;
    background:rgba(255,255,255,.93);color:#1C1C1E;font-size:11px;font-weight:600;
    max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
    box-shadow:0 1px 3px rgba(0,0,0,.25);}
  .clu{width:44px;height:44px;border-radius:22px;background:rgba(255,149,0,.93);
    border:3px solid #fff;color:#fff;font-weight:700;font-size:14px;
    line-height:44px;text-align:center;box-shadow:0 1px 5px rgba(0,0,0,.35);}
</style>
<script>window._AMapSecurityConfig={securityJsCode:"__SECRET__"};</script>
<script src="https://webapi.amap.com/maps?v=2.0&key=__KEY__&plugin=AMap.MarkerCluster"></script>
<script>__QWEBCHANNEL__</script>
</head>
<body><div id="container"></div>
<script>
var map=null, cluster=null, bridge=null, pickMode=false;
new QWebChannel(qt.webChannelTransport, function(ch){
  bridge=ch.objects.bmap;
  map=new AMap.Map('container',{zoom:4,center:[105,35],viewMode:'2D',zooms:[3,19]});
  function report(){
    var c=map.getCenter();
    bridge.mapMoved(c.getLat(), c.getLng(), map.getZoom());
  }
  map.on('moveend',report);
  map.on('zoomend',report);
  map.on('complete',report);
  map.on('click',function(e){
    if(pickMode) bridge.picked(e.lnglat.getLat(), e.lnglat.getLng());
  });
  // JS世界就绪即通知Python(瓦片后台渐进加载, 不等complete)
  bridge.mapReady();
  report();
});
function pinDiv(d){
  var div=document.createElement('div'); div.className='pin';
  var ph=d.thumb? "<img src='"+d.thumb+"'>" : "<span class='noimg'>\\ud83d\\udc26</span>";
  div.innerHTML=ph+"<div class='nm'>"+d.name+"</div>";
  return div;
}
function apiSetSpots(spots, fit){
  if(cluster){ cluster.setMap(null); cluster=null; }
  var pts=spots.map(function(d){
    return {lnglat:[d.glng,d.glat], id:d.id, name:d.name, thumb:d.thumb};
  });
  cluster=new AMap.MarkerCluster(map,pts,{
    gridsize:70,
    renderMarker:function(ctx){
      var d=Array.isArray(ctx.data)?ctx.data[0]:ctx.data;
      ctx.marker.setContent(pinDiv(d));
      ctx.marker.setAnchor('bottom-center');
      ctx.marker.on('click',function(){
        bridge.markerClicked(JSON.stringify(d));
      });
    },
    renderClusterMarker:function(ctx){
      var div=document.createElement('div'); div.className='clu';
      div.textContent=ctx.count;
      ctx.marker.setContent(div); ctx.marker.setAnchor('center');
      ctx.marker.on('click',function(){
        if(ctx.bounds){ map.setBounds(ctx.bounds); } else { map.zoomIn(); }
      });
    }
  });
  if(fit){ apiFit(spots); }
}
function apiFit(spots){
  if(!spots||!spots.length){ return; }
  if(spots.length===1){
    map.setZoomAndCenter(14,[spots[0].glng,spots[0].glat]); return;
  }
  var a=Infinity,b=-Infinity,c=Infinity,d=-Infinity;
  spots.forEach(function(s){
    a=Math.min(a,s.glng); b=Math.max(b,s.glng);
    c=Math.min(c,s.glat); d=Math.max(d,s.glat);
  });
  map.setBounds(new AMap.Bounds([a,c],[b,d]));
  if(map.getZoom()>16){ map.setZoom(16); }
}
function apiFocus(lat,lng,z){ map.setZoomAndCenter(z,[lng,lat]); }
function apiSetPick(on){ pickMode=on;
  map.getContainer().style.cursor=on?'crosshair':'';
}
</script></body></html>
"""


def _qwebchannel_js() -> str:
    """Qt资源里的qwebchannel.js原样内联, 避免file页外链qrc的不确定性。"""
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if f.open(QIODevice.ReadOnly):
        s = bytes(f.readAll()).decode("utf-8")
        f.close()
        return s
    return "console.error('qwebchannel.js missing');"


class _Bridge(QObject):
    """JS→Python 通道。

    QWebChannel里signal在JS侧是connect()对象(只能订阅不能调用),
    JS回调Python必须走@Slot方法; 这里收到后转成Qt信号给AmapView。
    坐标均为GCJ-02, 由AmapView转成WGS84再对外发信号。
    """
    ready = Signal()
    moved = Signal(float, float, float)   # lat, lon, zoom (GCJ)
    pickedAt = Signal(float, float)       # lat, lon (GCJ)
    markerHit = Signal(str)               # spot JSON

    @Slot()
    def mapReady(self):
        self.ready.emit()

    @Slot(float, float, float)
    def mapMoved(self, lat: float, lon: float, z: float):
        self.moved.emit(lat, lon, z)

    @Slot(float, float)
    def picked(self, lat: float, lon: float):
        self.pickedAt.emit(lat, lon)

    @Slot(str)
    def markerClicked(self, s: str):
        self.markerHit.emit(s)


class AmapView(QWidget):
    """高德交互地图控件。对外信号/接口一律使用WGS84。"""
    mapReady = Signal()
    center_moved = Signal(float, float, float)   # WGS84 lat, lon, zoom
    picked_wgs84 = Signal(float, float)
    spot_clicked = Signal(dict)

    def __init__(self, lib, parent=None):
        super().__init__(parent)
        self.lib = lib
        self._ready = False
        self._pending_js: list[str] = []
        self._last_payload: tuple[str, bool] | None = None
        self._key = ""
        self._secret = ""
        self._engine = "maplibre_free"
        self._center_state = (35.0, 105.0, 4.0)   # WGS84 lat, lon, zoom

        self._bridge = _Bridge(self)
        self._bridge.ready.connect(self._on_ready)
        self._bridge.moved.connect(self._on_moved)
        self._bridge.pickedAt.connect(self._on_picked)
        self._bridge.markerHit.connect(self._on_marker)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget(self)
        lay.addWidget(self.stack)

        from ..i18n import t
        self.placeholder = QLabel(t("地图加载中…（需要联网访问高德服务）",
                                    "Loading map… (requires access to Amap services)"))
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setStyleSheet(
            "color:#5B6B7A;font-size:15px;background:#DCE3EA;")
        self.web = QWebEngineView(self)
        st = self.web.settings()
        st.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        # file://页面引用本地maplibre-gl.js需要显式允许(Qt6部分版本默认关)
        st.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        self._channel = QWebChannel(self)
        self._channel.registerObject("bmap", self._bridge)
        self.web.page().setWebChannel(self._channel)
        self.web.loadFinished.connect(self._on_load_finished)
        self.stack.addWidget(self.placeholder)
        self.stack.addWidget(self.web)

        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.timeout.connect(self._load_timeout)
        self._fitted_visible = False
        self.load_map()

    def showEvent(self, e):
        super().showEvent(e)
        # 首次真正可见时容器才有尺寸; 此前fit会在0x0容器上算出错误缩放,
        # 重发一次带fit的点位把视野校正回来(仅一次)
        if not self._fitted_visible and self._last_payload:
            self._fitted_visible = True
            payload, _ = self._last_payload
            self.js(f"apiSetSpots({payload},true)")

    # ---- 页面装载 ----
    # 引擎枚举: maplibre_free(默认, 高德栅格瓦片零Key) / amap(高德官方JS,
    # 用户Key)。旧值 maplibre/maptiler(已移除的MapTiler引擎, 政治合规)
    # 兼容映射为 maplibre_free
    def _effective_conf(self) -> tuple[str, str, str]:
        """(engine, key, secret) —— 引擎与Key的生效配置(含内置缺省)。"""
        engine = self.lib.get_setting("map_engine", "maplibre_free")
        if engine not in ("maplibre_free", "amap"):
            engine = "maplibre_free"
        if engine == "maplibre_free":
            return engine, "", ""      # 高德瓦片不需要Key
        # 自填优先, 缺省=内置Key(2026-10-31用户提供JS Key+安全密钥内置)
        key = self.lib.get_setting("map_js_key", "") or DEFAULT_JS_KEY
        secret = self.lib.get_setting("map_js_secret", "") or DEFAULT_JS_SECRET
        return engine, key, secret

    # MapLibre style: 高德栅格瓦片(免Key, GCJ-02坐标系, 中文标注, 国内快)
    _AMAP_TILES_STYLE = (  # i18n:ok
        '{version:8,'  # i18n:ok
        ' sources:{amap:{type:"raster",tileSize:256,minzoom:3,maxzoom:18,'
        '  tiles:["https://webst01.is.autonavi.com/appmaptile?style=7&x={x}&y={y}&z={z}",'
        '         "https://webst02.is.autonavi.com/appmaptile?style=7&x={x}&y={y}&z={z}",'
        '         "https://webst03.is.autonavi.com/appmaptile?style=7&x={x}&y={y}&z={z}",'
        '         "https://webst04.is.autonavi.com/appmaptile?style=7&x={x}&y={y}&z={z}"],'
        '  attribution:"高德地图"}},'  # i18n:ok
        ' layers:[{id:"amap",type:"raster",source:"amap"}]}'
    )

    def load_map(self):
        from ..i18n import t
        self._engine, self._key, self._secret = self._effective_conf()
        if self._engine == "amap" and not self._key:
            # 高德官方引擎不再内置Key: 未配置时不加载, 给出指引
            self._ready = False
            self._load_timer.stop()
            self.placeholder.setText(
                t("未配置高德JS Key：请在设置页填写自己的Key后重开地图页\n"
                  "（默认的「免Key高德底图」引擎无需任何Key）",
                  "Amap JS key not configured: set your own key in Settings, "
                  "then reopen this page.\n(The default keyless engine needs no key.)"))
            self.stack.setCurrentWidget(self.placeholder)
            return
        qc = _qwebchannel_js()
        if self._engine == "maplibre_free":
            from ..paths import assets_dir
            map_js = (assets_dir() / "map" / "maplibre-gl.js").as_uri()
            map_css = (assets_dir() / "map" / "maplibre-gl.css").as_uri()
            style_js = self._AMAP_TILES_STYLE  # i18n:ok
            html = (_HTML_MAPLIBRE.replace("__STYLE__", style_js)
                     .replace("__QWEBCHANNEL__", qc)
                     .replace("href=\"maplibre-gl.css\"", f"href=\"{map_css}\"")
                     .replace("src=\"maplibre-gl.js\"", f"src=\"{map_js}\""))
            html_path = self.lib.root / "maplibre.html"
            label = t("开源地图（免Key高德底图）", "Open map (keyless Amap tiles)")
            self.placeholder.setText(
                t(f"地图加载中…（{label}，需联网）",
                  f"Loading map… ({label}, internet required)"))
        else:
            html = (_HTML.replace("__SECRET__", self._secret)
                     .replace("__KEY__", self._key)
                     .replace("__QWEBCHANNEL__", qc))
            html_path = self.lib.root / "amap.html"
            self.placeholder.setText(
                t("地图加载中…（需要联网访问高德服务）",
                  "Loading map… (requires access to Amap services)"))
        html_path.write_text(html, encoding="utf-8")
        self._ready = False
        self._pending_js = []
        self.stack.setCurrentWidget(self.placeholder)
        self._load_timer.start(15000)
        self.web.load(QUrl.fromLocalFile(str(html_path)))

    def ensure_keys(self) -> bool:
        """设置里的引擎/Key变更后重载页面; 返回是否发生了重载。"""
        if self._effective_conf() != (self._engine, self._key, self._secret):
            self.load_map()
            return True
        return False

    def _on_load_finished(self, ok: bool):
        if not ok:
            from ..i18n import t
            self._load_timer.stop()
            self.placeholder.setText(
                t("地图页面加载失败：请检查网络后重进地图页",
                  "Map page failed to load: check your network and reopen"))

    def _load_timeout(self):
        if not self._ready:
            from ..i18n import t
            self.placeholder.setText(
                t("地图加载超时：请检查网络（高德JS/瓦片需直连）。\n"
                  "搜索、鸟点列表等功能不受影响。",
                  "Map loading timed out: check your network (Amap JS/tiles "
                  "need direct access).\nSearch and the spot list still work."))

    def _on_ready(self):
        self._ready = True
        self._load_timer.stop()
        self.stack.setCurrentWidget(self.web)
        pending, self._pending_js = self._pending_js, []
        for code in pending:
            self.web.page().runJavaScript(code)
        self.mapReady.emit()

    def js(self, code: str):
        if self._ready:
            self.web.page().runJavaScript(code)
        else:
            self._pending_js.append(code)

    # ---- 对外接口(WGS84) ----
    @property
    def _is_gcj(self) -> bool:
        """当前引擎底图是否GCJ-02坐标系(高德瓦片/高德JS)。"""
        return self._engine in ("amap", "maplibre_free")

    def _to_map(self, lat: float, lon: float) -> tuple[float, float]:
        """WGS84 → 引擎世界坐标(两个引擎都是高德系=GCJ02纠偏)。"""
        return wgs84_to_gcj02(lat, lon)

    def _from_map(self, lat: float, lon: float) -> tuple[float, float]:
        return gcj02_to_wgs84(lat, lon)

    def set_spots(self, spots: list[dict], fit: bool = False):
        """spots: [{id,name,lat,lon,thumb(dataURL|None)}], 坐标WGS84。"""
        pts = []
        for d in spots:
            g_lat, g_lon = self._to_map(d["lat"], d["lon"])
            pts.append({"id": d["id"], "name": d["name"],
                        "glng": round(g_lon, 7), "glat": round(g_lat, 7),
                        "thumb": d.get("thumb")})
        payload = json.dumps(pts, ensure_ascii=False)
        self._last_payload = (payload, fit)
        self.js(f"apiSetSpots({payload},{str(fit).lower()})")

    def focus_wgs84(self, lat: float, lon: float, z: int):
        g_lat, g_lon = self._to_map(lat, lon)
        self.js(f"apiFocus({g_lat:.7f},{g_lon:.7f},{z})")

    def fit_wgs84(self, pts: list[tuple[float, float]]):
        if not pts:
            return
        if len(pts) == 1:
            self.focus_wgs84(pts[0][0], pts[0][1], 14)
            return
        marks = [{"glng": self._to_map(a, b)[1], "glat": self._to_map(a, b)[0]}
                 for a, b in pts]
        self.js("apiFit(" + json.dumps(marks) + ")")

    def set_pick(self, on: bool):
        self.js(f"apiSetPick({str(bool(on)).lower()})")

    # ---- JS回调 ----
    def _on_moved(self, lat: float, lon: float, z: float):
        w_lat, w_lon = self._from_map(lat, lon)
        self._center_state = (w_lat, w_lon, z)
        self.center_moved.emit(w_lat, w_lon, z)

    def _on_picked(self, lat: float, lon: float):
        w_lat, w_lon = self._from_map(lat, lon)
        self.picked_wgs84.emit(w_lat, w_lon)

    def _on_marker(self, s: str):
        try:
            self.spot_clicked.emit(json.loads(s))
        except (ValueError, TypeError):
            pass


def thumb_data_url(lib, cover_photo_id: int | None) -> str | None:
    """鸟点封面照 → webp dataURL(给JS marker用), 失败返回None。"""
    if not cover_photo_id:
        return None
    row = lib.conn.execute(
        "SELECT path, file_hash FROM photos WHERE id=?",
        (cover_photo_id,)).fetchone()
    if not row:
        return None
    from ..media import ensure_thumbnail
    tp = ensure_thumbnail(lib.root, row["path"], row["file_hash"], 96)
    if not tp:
        return None
    b64 = base64.b64encode(Path(tp).read_bytes()).decode()
    return f"data:image/webp;base64,{b64}"
