# -*- coding: utf-8 -*-
"""分布地图: 选鸟种 → 中国省级choropleth按峰值丰度着色。

数据=geo_prior priors表各区域的12个月最大值(log先验[-4,+2], 与月份无关
——月度维度已按作者指示去掉, 见prior_hint模块docstring); 几何=阿里DataV
省界GeoJSON(assets/map/china_provinces.json)。坐标系: DataV省界与高德底图
同为GCJ-02系, 免纠偏(残余偏移几百米对省级着色无碍)。引擎=maplibre_free
(免Key高德栅格底图, 与鸟点地图同款); GeoJSON内联注入HTML一次。

注意: 本模块WebEngine相关import全部放在使用处(懒加载, 避免拉起194MB
WebEngineCore DLL拖慢启动) —— 引用方也必须在按钮回调里局部import本模块。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout

from ..core.prior_hint import get_hint, tier_display, value_tier
from ..i18n import t, sname
from ..paths import assets_dir
from .. import theme

# DataV省级adcode -> priors区域码 (34省级行政区, 与priors表CN-*一一对应;
# GeoJSON里的九段线feature(adcode=100000_JD)不参与着色, 仅由线层绘制)
ADCODE_TO_REGION = {
    110000: "CN-BJ", 120000: "CN-TJ", 130000: "CN-HE", 140000: "CN-SX",
    150000: "CN-NM", 210000: "CN-LN", 220000: "CN-JL", 230000: "CN-HL",
    310000: "CN-SH", 320000: "CN-JS", 330000: "CN-ZJ", 340000: "CN-AH",
    350000: "CN-FJ", 360000: "CN-JX", 370000: "CN-SD", 410000: "CN-HA",
    420000: "CN-HB", 430000: "CN-HN", 440000: "CN-GD", 450000: "CN-GX",
    460000: "CN-HI", 500000: "CN-CQ", 510000: "CN-SC", 520000: "CN-GZ",
    530000: "CN-YN", 540000: "CN-XZ", 610000: "CN-SN", 620000: "CN-GS",
    630000: "CN-QH", 640000: "CN-NX", 650000: "CN-XJ", 710000: "CN-TW",
    810000: "CN-HK", 820000: "CN-MO",
}

# 高德栅格瓦片style(与amap_view._AMAP_TILES_STYLE同源, 单独内联免互相依赖)
_AMAP_TILES_STYLE = (  # i18n:ok
    '{version:8,'
    ' sources:{amap:{type:"raster",tileSize:256,minzoom:3,maxzoom:18,'
    '  tiles:["https://webst01.is.autonavi.com/appmaptile?style=7&x={x}&y={y}&z={z}",'
    '         "https://webst02.is.autonavi.com/appmaptile?style=7&x={x}&y={y}&z={z}",'
    '         "https://webst03.is.autonavi.com/appmaptile?style=7&x={x}&y={y}&z={z}",'
    '         "https://webst04.is.autonavi.com/appmaptile?style=7&x={x}&y={y}&z={z}"],'
    '  attribution:"Amap"}},'  # i18n:ok
    ' layers:[{id:"amap",type:"raster",source:"amap"}]}'
)

# fill色阶与图鉴地区分布表同系: ≤-1.49(缺席/rescue地板)=近透明, -1.5..+2 浅→深橄榄
# 悬浮提示文案由Python按当前语言生成后经apiSetValues注入, JS侧零文案(模板无中文)
_HTML = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="maplibre-gl.css">
<style>
  html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;
    font-family:"Microsoft YaHei UI","PingFang SC",system-ui,sans-serif;}
  #container{width:100%;height:100%;}
  #tip{position:absolute;pointer-events:none;display:none;z-index:9;
    background:rgba(28,28,30,.92);color:#fff;font-size:12px;
    padding:4px 9px;border-radius:8px;white-space:nowrap;}
</style>
<script src="maplibre-gl.js"></script>
<script>__QWEBCHANNEL__</script>
</head>
<body><div id="container"></div><div id="tip"></div>
<script>
var map=null, bridge=null, TIPS={}, PENDING=null;
var tip=document.getElementById('tip');
var GJ=__GEOJSON__;
new QWebChannel(qt.webChannelTransport, function(ch){
  bridge=ch.objects.dmap;
  map=new maplibregl.Map({container:'container', center:[105,35], zoom:3.4,
    style: __STYLE__,
    attributionControl:false});
  // report ready at once (do NOT wait 'load': it waits all initial tiles)
  bridge.mapReady();
  map.on('load', function(){
    var fillExpr=['case',
      ['<=',['coalesce',['feature-state','v'],-4],-1.49],'rgba(120,120,120,0.10)',
      ['interpolate',['linear'],['feature-state','v'],-1.5,'#EDF2DF',0,'#A8B36B',2,'#55631F']];
    map.addSource('prov',{type:'geojson',data:GJ});
    map.addLayer({id:'prov-fill',type:'fill',source:'prov',
      paint:{'fill-color':fillExpr,'fill-opacity':0.88}});
    map.addLayer({id:'prov-line',type:'line',source:'prov',
      paint:{'line-color':'rgba(60,60,60,0.55)','line-width':0.7}});
    map.on('mousemove','prov-fill',function(e){
      var info=TIPS[e.features[0].id];
      if(info){
        tip.textContent=info.tip;
        tip.style.display='block';
        // Pin beside the cursor, flip at right/bottom edges. Before
        // 2026-11-04 the tip had no positioning at all: it sat in the
        // document flow after the 100%-height container, so it rendered
        // off-window and hover looked dead (0.6.0..0.8.0-test1).
        var w=tip.offsetWidth, h=tip.offsetHeight;
        var x=e.point.x+14, y=e.point.y+14;
        if(x+w>map.getCanvas().clientWidth-4) x=e.point.x-w-14;
        if(y+h>map.getCanvas().clientHeight-4) y=e.point.y-h-14;
        tip.style.left=Math.max(4,x)+'px';
        tip.style.top=Math.max(4,y)+'px';
      }
    });
    map.on('mouseleave','prov-fill',function(){ tip.style.display='none'; });
    if(PENDING){ apiSetValues(PENDING); PENDING=null; }
  });
});
function apiSetValues(tips){
  if(!map || !map.getSource('prov')){ PENDING=tips; return; }
  TIPS=tips||{};
  for(var id in TIPS){
    map.setFeatureState({source:'prov', id:id}, {v:TIPS[id].v});
  }
}
</script></body></html>
"""


def _qwebchannel_js() -> str:
    """Qt资源里的qwebchannel.js原样内联(同amap_view做法)。"""
    from PySide6.QtCore import QIODevice, QFile
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if f.open(QIODevice.ReadOnly):
        s = bytes(f.readAll()).decode("utf-8")
        f.close()
        return s
    return "console.error('qwebchannel.js missing');"


def region_tooltip_map(code: str) -> dict[str, dict]:
    """34省的 {feature_id(str adcode): {v: 峰值先验, tip: 悬浮文案}}。

    物种无先验数据的省 → v=-4(近透明"无记录"); 文案随当前语言。
    """
    peaks = get_hint().region_peaks(code)
    from ..core import regions
    out: dict[str, dict] = {}
    for adcode, rid in ADCODE_TO_REGION.items():
        v = peaks.get(rid, -4.0)
        reg = regions.region_display(rid)
        if v <= -1.49:
            tip = t(f"{reg}：无记录", f"{reg}: no records")
        else:
            tier = tier_display(value_tier(v))
            tip = t(f"{reg}：{tier} ({v:+.1f})", f"{reg}: {tier} ({v:+.1f})")
        # 不round: 先验值是0.03125步长, 丢精度会破坏与region_peaks的对照验证
        out[str(adcode)] = {"v": float(v), "tip": tip}
    return out


class _Bridge(QObject):
    """JS→Python: 地图就绪信号。"""
    ready = Signal()

    @Slot()
    def mapReady(self):
        self.ready.emit()


class DistributionMapDialog(QDialog):
    """省级分布choropleth对话框(模态)。入口: 图鉴页地区分布卡片。
    UI重设计c5扩展: title/payload_fn 可选参数供生涯页足迹图复用同一
    渲染管线(数据源换成调用方注入的 {adcode:{v,tip}}), 缺省行为不变。"""

    def __init__(self, lib, win, code: str, parent=None,
                 title: str | None = None,
                 payload_fn=None):
        super().__init__(parent or win)
        self.lib = lib
        self.code = code
        self._payload_fn = payload_fn
        if title:
            self.setWindowTitle(title)
        else:
            sp = lib.species_info(code)
            name = sname(sp["cn"], sp["en"])
            self.setWindowTitle(t(f"{name} · 分布地图", f"{name} · Distribution map"))
        self.resize(1060, 720)

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 10)
        v.setSpacing(8)

        # WebEngine懒import: 本对话框只在用户点击后才构造
        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtWebEngineCore import QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView
        self._bridge = _Bridge(self)
        self._bridge.ready.connect(self._on_map_ready)
        self.web = QWebEngineView(self)
        st = self.web.settings()
        st.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        # file://页面引用本地maplibre-gl.js/css需要显式允许(Qt6部分版本默认关)
        st.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        self._channel = QWebChannel(self)
        self._channel.registerObject("dmap", self._bridge)
        self.web.page().setWebChannel(self._channel)
        v.addWidget(self.web, 1)

        # 说明条
        hint = QLabel(t("颜色越深=越常见 · 悬浮省份看详情",
                        "Darker = more common · hover a province for details"))
        hint.setStyleSheet(f"color:{theme.LABEL_2};font-size:12px;"
                           "background:transparent;")
        hint.setAlignment(Qt.AlignCenter)
        v.addWidget(hint)

        self._js: list[str] = []          # map就绪前积压的js调用
        self._ready = False
        self._write_html_and_load()

    # ---- 页面装载 ----
    def _write_html_and_load(self):
        from PySide6.QtCore import QUrl
        import json
        map_js = (assets_dir() / "map" / "maplibre-gl.js").as_uri()
        map_css = (assets_dir() / "map" / "maplibre-gl.css").as_uri()
        gj = json.dumps(_load_geojson(), ensure_ascii=False)
        html = (_HTML.replace("__STYLE__", _AMAP_TILES_STYLE)
                .replace("__GEOJSON__", gj)
                .replace("__QWEBCHANNEL__", _qwebchannel_js())
                .replace('href="maplibre-gl.css"', f'href="{map_css}"')
                .replace('src="maplibre-gl.js"', f'src="{map_js}"'))
        html_path = self.lib.root / "distribution_map.html"
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
        import json
        payload = self._payload_fn() if self._payload_fn else \
            region_tooltip_map(self.code)
        self.js(f"apiSetValues({json.dumps(payload, ensure_ascii=False)})")


def _load_geojson() -> dict:
    """省界GeoJSON, 给每个feature补MapLibre setFeatureState需要的id。

    来源: 阿里DataV开放数据 https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json
    (git源码仓库不含assets, 需按上述地址下载放到 assets/map/; 发布包已内置)。
    """
    import json
    p = assets_dir() / "map" / "china_provinces.json"
    if not p.exists():
        raise FileNotFoundError(t(
            "缺少省界数据 assets/map/china_provinces.json —— "
            "请从 https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json "
            "下载后放到该位置",
            "Missing assets/map/china_provinces.json — download it from "
            "https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json "
            "and place it there"))
    gj = json.loads(p.read_text(encoding="utf-8"))
    for f in gj.get("features", []):
        f["id"] = str(f.get("properties", {}).get("adcode", ""))
    return gj
