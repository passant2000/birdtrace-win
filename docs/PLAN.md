# 鸟迹 Windows 版 · 优化方案 v2（执行文档）

> **本文档是自包含的执行规格书**：包含背景、已破解的数据格式规格、每个功能的详细设计（数据结构/文件指引/验收标准）、里程碑顺序与踩坑清单。执行者无需其他上下文即可开工。
> 项目根：`D:\tmp2\birdtrace-win\`，虚拟环境 `.venv\`（Python 3.14），启动 `启动鸟迹.bat` 或 `.venv\Scripts\python -X utf8 -m app.main`。

## 0. 背景与定位

- 鸟迹Win是基于好友的 BirdTrace 安卓版 APK（作者提供）内开源模型与数据资产开发的本地优先 Windows 鸟类照片管理软件，v1 已完成并打包（`packaging\dist\birdtrace\`）。
- 对标产品：好友的慧眼观鸟 iOS 版（OSEA模型/年鸟桂冠/年度报告/地图标注/罕见度）与 BirdTrace 安卓版（图鉴详情/文化库/成就系统/MapLibre离线地图）。
- **电脑版差异化定位**：本地优先（全部离线）、照片管理（Lightroom式非破坏导入，两家App都不做）、大屏浏览与批量操作、eBird导出。不做：社区/在线识别/好友服务器依赖。
- 用户可向两位作者直接取材（开放问题见 §8）。

## 1. 当前代码结构速览（v1已完成）

```
app/
├── paths.py            # assets解析: 开发态=项目assets/, 打包态=exe旁assets/
├── db.py               # Library类: SQLite编目库(线程本地连接), 表 photos/exif/species/
│                       #   records(含top5_json,box_json)/batches/settings + 视图v_records
├── exif.py             # EXIF提取(含HEIC), month_of()
├── media.py            # file_hash(首尾256KB+size SHA1), ensure_thumbnail(webp缓存)
├── ai/
│   ├── detector.py     # YOLO11n解码+NMS(conf 0.25/iou 0.45), letterbox 640
│   ├── classifier.py   # FastViT 384×384, 策略squash(已对比选定)
│   ├── geo_prior.py    # 先验sqlite读取+rerank(log_softmax + 0.6×prior)
│   └── pipeline.py     # detect→crop(外扩10%)→classify→rerank→top5, 按confidence排序
├── core/
│   ├── importer.py     # scan_sources(绝对路径!) / import_files(ref|copy模式,按年月归档)
│   ├── worker.py       # RecognizeWorker(QThread), 失败3次不再重试(rec_fail列)
│   ├── regions.py      # 区域树(babel zh_CN中文名+JSON zh-Hans), region_display()
│   └── sharecard.py    # 分享卡v2渲染(参考慧眼风格: 拼音/加字距中文名/Life#N/小鸟logo)
├── theme/              # iOS风格QSS + ToggleSwitch/SegmentedControl/PhotoGridItem/make_card
└── ui/                 # main_window(六页导航+start_recognition) / import_page /
                        # timeline_page / species_page / review_page / stats_page /
                        # settings_page / viewer(ZoomableView滚轮缩放) / share_dialog
tools/                  # extract_assets.py / smoke_test.py / e2e_test.py / seed_demo.py / ui_shots.py
packaging/              # birdtrace.spec + make_release.py(构建+复制模型资产)
assets/                 # models/*.onnx + data/{labels,species_catalog,regions,iucn,geo_prior}
```

## 2. 新增资产利用 · 数据格式规格书（已逆向验证，直接照抄实现）

### 2.1 图鉴详情 `details_v2.btd` + `details_index_v2.bin`（APK内各15MB/750KB）

**提取**：`tools/extract_assets.py` 增加从 `birdtrace.apk` 提取这两个文件到 `assets/data/`。

**index格式（BTRIDX02，全部大端）**：
```
[8B magic][u32 ver=2][u32 count=11171][u32 dateLen][date字符串][u64 btd文件总长]
然后 count × { [u32 nameLen][学名UTF-8][u64 offset][u32 length][32B sha256] }
```
offset/length 指向 .btd 文件内的记录字节区间；sha256 为该记录的校验。

**btd记录格式（BTRDET02）**：30字节头（magic+u32 ver+u32 count+u32 dateLen+date），之后：
```
记录 = { [u32 nameLen][学名] + 15个item + [u32 0 终止] }
item = { [u32 len][UTF-8字节] }   # 每物种恒定15个item
```
item 语义（中英成对）：
| # | 内容 | # | 内容 |
|---|---|---|---|
| 0/1 | 中/英概述（分类+生境+食性一句话）| 8/9 | 中/英行为生态 |
| 2/3 | 中/英识别要点（3条短句）| 10/11 | 中/英食性 |
| 4/5 | 中/英分布区系 | 12/13 | 中/英每窝卵数 |
| 6/7 | 中/英栖息地+海拔 | 14 | 空 |

**关联方式**：catalog_v2.bin（已解析为 `species_catalog.json`，顺序即分类学顺序）与 index 条目**逐行对齐（已验证 11171/11171）**。即 `species_catalog.json[i]` ↔ `index第i条`。启动时构建 `学名→(offset,length)` 或按行号映射。

**实现**：新建 `app/core/birddex.py`：
- `BirdDex(index_path, btd_path)`，懒加载按需读文件区间（`seek+read`，不要全量载入内存）；
- `detail(sci_name_or_code) -> dict{summary, id_points, range, habitat, behavior, diet, clutch}`（中文字段）；
- 首次构建时把 `code→学名` 映射缓存进 `assets/data/details_map.json` 或直接用 species 表的 sci 字段查。

### 2.2 文化知识库 `BirdCulture.sqlite`（14MB）

**提取**：同样加入 extract_assets.py → `assets/data/bird_culture.sqlite`。只读打开（`file:...?mode=ro`）。

**核心表**（已验证）：
- `taxa(11171)`：`species_code`(eBird code，唯一)、学名、英文名、中文名 —— 与 species 表直连
- `stories(1378)`：id、`evidence_confidence`(veryHigh/high)、`disputed`
- `localized_text(2756 = en+zh-Hans 各1378)`：story关联、`title/subtitle/short_summary/summary/body长文/scientific_note/taxonomy_note/cultural_context_note/source_note`、语言列
- `story_categories(2520)`：15类——名称由来580/博物史383/历史故事263/保护文化253/国家象征178/文学128/象征125/民俗125/艺术91/原住民传统89/词源52/诗歌50/神话50/传统知识22/音乐18
- `story_taxa(1378)`：story↔物种，`scope`（exactSpecies 1228 / vernacularGroup 145 等）→ **965个不同物种有故事**
- `story_display_associations(147)`：直接挂 species_code、带中文标签与 caveat
- `claims/claim_sources/production_sources/source_attributions`：证据引用链（详情页可展示"来源"一行）

**实现**：`app/core/culture.py`：`Culture(db_path)`，`stories_for(code) -> list[{title, body, category, caveat, sources}]`（zh-Hans，body 可能很长，UI里分段展示），`random_pool() -> list[code]`（exactSpecies 的 965 种）。

### 2.3 地理先验库的月份维度（已持有 `assets/data/geo_prior.sqlite`，无需提取）

`priors(region_id, month 1..12, checklist_count, vector BLOB 10480字节int8)`，解码 `int8×0.03125`（log空间[-4,+2]）。v1 只用了识别时单月重排，本方案扩展两个用途（当月活性提示 §3.4、罕见度 §3.5）。

## 3. P0 · 快赢功能（数据现成，纯本地）

### 3.1 物种详情页 v2（预估1.5天）
- **UI**：`species_page.py` 详情视图改造为标签页式（QSS分段控件）：「概览 / 图鉴 / 文化」。
  - 概览（现有）：中英名/学名/IUCN/科属/首见/照片网格
  - **图鉴（新）**：识别要点、栖息地与海拔、食性、每窝卵数、行为生态、分布区系——分组卡片排版（make_card），中文展示
  - **文化（新）**：§3.2
- **验收**：任一物种打开详情，图鉴标签展示 ≥4 个字段；无详情的物种优雅降级（"暂无图鉴条目"）。

### 3.2 文化板块 + 每日一鸟（预估1天）
- 物种详情页「文化」标签：`culture.stories_for(code)` 列表，每篇一张卡片（标题/分类标签/正文/来源行；`disputed=true` 或有 caveat 的显示灰色提示条）。
- **每日一鸟**：主窗口顶部或时间线页顶部横幅卡片。选种逻辑：`pool = culture.random_pool()`（965种），`index = dayofyear % len(pool)`，确定性（同一天打开看到同一只）。若库内已有该物种照片用照片做卡头图，否则纯排版；点击跳转物种详情。
- **验收**：横幅每日变化、点击可达详情；有故事的物种详情页能看到完整中文长文。

### 3.3 年鸟（桂冠）徽章（预估0.5天）
- **定义**：某物种在**今年**的首次记录，且其生涯首见不在今年（即"今年回归/新发现但非今年才第一次拍"——严格年鸟=生涯首见发生在今年则同时显示皇冠）。简化实现：
  ```sql
  -- 每物种每年首见（v_records 已有 yr/taken_at/eff_code）
  SELECT eff_code, yr, MIN(taken_at) FROM v_records GROUP BY eff_code, yr
  ```
  年鸟集合 = 当前年份的 `(eff_code, min(taken_at))` 中，该 code 的生涯首见年份 < 当前年份的。
- **UI**：时间线/鸟种库角标：生涯首见=皇冠色（现"首见"角标升级为👑语义，但保留纯文字"首见"+金色），年鸟=桂冠绿角标"年鸟"；统计页年度卡显示"今年新种 N / 其中年鸟 M"。
- **验收**：demo 库里 2025 年拍的鸟在 2025 视角下显示年鸟角标；跨年测试用 seed_demo 造数。

### 3.4 当月出现提示（预估0.5天）
- 详情页「图鉴」标签顶部一行胶囊：基于用户默认地区（settings.default_region）+ 当前月份：取 `prior.vector[code_idx]`，按值分档：`≥1 常见 / ≥0 可见 / ≥-1 偶见 / <-1 罕见`（log空间直觉档位，执行时可微调）；显示如「本月·你所在地区：常见」。
- 需要类目索引：`labels.json` 里该 code 的 `i`（classifier 索引）。注意：691 种 manualOnly 不在 classifier 内，提示"不在AI识别范围"。
- **验收**：绿头鸭在北京 1月 vs 6月 档位不同（先验库真实差异）。

### 3.5 罕见度指数 5 档（预估0.5天）
- **算法**：对用户地区，取每物种 12 个月 vector 的最大值 `m_s`；在 10480 种里算 `m_s` 的分位数 → 5 档（常见/较常见/不常见/稀有/罕见），类似慧眼"拍摄难度"。
- 物种卡与详情页显示档位徽章（颜色从绿到红渐变）。
- 注意先验是 log 空间且负值占绝大多数，直接分位数即可，不要线性换算。
- **验收**：麻雀=常见；某海外特有种=罕见。

## 4. P1 · 鸟点与地图（用户点名功能，预估 1 + 3 天）

### 4.1 第一步：位置数据层（先于地图，独立有价值）
- **建表**：
  ```sql
  CREATE TABLE spots(id INTEGER PRIMARY KEY, name TEXT, lat REAL, lon REAL,
                     note TEXT, created_at TEXT DEFAULT (datetime('now','localtime')));
  ALTER TABLE photos ADD COLUMN spot_id INTEGER REFERENCES spots(id);
  ```
- **入口**：
  - 导入页高级选项：「挂到鸟点」下拉（已有鸟点 + 新建）；不选则默认取EXIF GPS匹配（距离 <300m 自动归组，可关闭）。
  - 照片查看器：信息面板加"位置"行 + 「设为鸟点」按钮（从这张照片的GPS建点，或搜索已有鸟点挂载）。
- **鸟点页（新导航项"鸟点"，插在鸟种库后）**：列表卡片（名称/坐标/照片数/鸟种数/最近记录），点击进入鸟点详情（物种清单+照片流）。纯列表UI，不含地图。
- **验收**：两张同地照片自动归组同一点；手动挂点/解挂可用。

### 4.2 第二步：交互地图（⚠️2026-10-23起已改为高德JS API方案，见§7 B4.1；以下为弃用的自绘瓦片方案存档）
- ~~**选型结论（已论证）**：`QGraphicsView` 自绘 slippy map。~~ 不用 QWebEngine 的理由（+150MB、打包复杂）在"官方地图渲染保真+交互手感"面前不再成立，且自绘方案真机上出现未根治的显示缺陷（见§7 B4.1）。
- **瓦片源**：OSM 标准瓦片 `https://tile.openstreetmap.org/{z}/{x}/{y}.png`，缩放 3–17。**合规**：按需加载+本地缓存（`<库>/tiles/{z}/{x}/{y}.png`），设置 UA（如 `BirdTraceWin/0.2 personal photo map`），不做批量预下载。断网时显示已缓存瓦片+灰底提示。
- **新文件 `app/ui/map_page.py`**（约350行）：
  - `TileMap(QGraphicsView)`：滚轮缩放（整数级+平滑）、拖拽平移、瓦片异步加载（QNetworkAccessManager 或 简单QThread队列，加载完成发信号刷新）。
  - **marker**：每鸟点一个 `QGraphicsPixmapItem`——用该点最高频鸟种的代表缩略图做圆形小图钉（48px，白描边+底部小三角，参考慧眼）；缩放级别低时按屏幕距离聚合为数字气泡。
  - 点击 marker：弹出该点摘要（名称/照片数/鸟种数/最新3张缩略图），按钮「查看鸟点详情」「在系统地图中打开」（`QDesktopServices.openUrl(f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=15/{lat}/{lon}")`）。
  - 照片层开关：「按鸟种着色」每个物种一个小marker模式（同点多鸟种散开排布）。
- 地图页顶部：地区跳转（跟随默认地区中心点）、当前中心坐标显示。
- **验收**：缩放平移流畅；marker缩略图正确；离线打开显示缓存瓦片不崩溃；点击导航能唤起浏览器。

## 5. P2 · 体验与性能（库变大后按需，各0.5–1天）

1. **检测框叠加**（0.5天）：viewer 的 ZoomableView 加 `QGraphicsRectItem` 图层，按 `records.box_json` 画框（蓝色圆角描边+置信度标签），工具栏开关「显示检测框」。
2. **时间线懒加载**（1天）：改为按月分块渲染 + QScrollBar 接近底部时追加下一年；`_thumb_cache` 加 LRU 上限（2000项，QPixmap内存约≤500MB）。QListView+delegate 方案可后续再优化，先做分块。
3. **导入预览后台化**（0.5天）：`_populate_grid` 的 file_hash 计算挪到 QThread，逐个发信号回填网格与"已导入"角标（当前大文件夹会冻结UI——已知缺陷）。
4. **推理流水线并行**（1天）：检测session共享（ORT session.run 线程安全，DML走GPU）；分类开 2 个线程各持独立 CPU session（每session内存约850MB，设置页暴露"并行度"选项，默认2）。批量导入吞吐预期 0.35s/张 → ~0.15s/张。
5. **top-200 存储 + 秒级换区重排**（1天）：识别时额外存：
   ```sql
   ALTER TABLE records ADD COLUMN top200_json TEXT;  -- [ [class_idx u16, logit f32] × ≤200 ]
   ALTER TABLE records ADD COLUMN logsumexp REAL;    -- 全集 logsumexp(logits)
   ```
   重排公式：`logprob = logit − logsumexp`（精确），`final = logprob + 0.6×prior`。新UI：查看器/复核页加「用其他地区重排」下拉（列出相邻地区），对 top200 内候选即时重排展示。历史记录没有 top200 的走重新推理兜底。
6. **主界面深色模式**（0.5天）：theme.py 加 dark 调色板，设置页切换，QSS 变量化（颜色已集中在 theme.py，工作量小）。

## 6. P3 · 生态与安全

1. **eBird CSV 导出**（0.5天）：我们的 species code 即 eBird taxonomy 代码。导出列：`Common Name, Scientific Name, Count(X或照片数), Location(spot名), Date(EXIF日期), Time, Protocol(Traveling/Incidental), Number of Observers(1)`。入口：统计页「导出eBird记录(CSV)」，按日期+地点聚合每 species 一行。**这是观鸟党刚需，别家桌面工具没有**。
2. **年度报告页**（1.5天）：年度选择器；汇总卡（新种/年鸟回归/照片数/拍摄天数/最忙月份）；月度柱状（复用 stats_page.BarChart）；年度新种九宫格代表图；「导出报告长图」——QPainter 渲染 1600×2000 分享卡风格长图（复用 sharecard 的字体/配色体系），含年份大字、统计数字、九宫格、署名。
3. **catalog.db 自动备份**（0.5天）：启动时若 `data_version`（PRAGMA data_version）较上次变化且距上次备份>24h，复制库文件到 `<库>/backups/catalog-YYYYMMDD-HHMM.db`，保留最近 7 份（Wal 模式下用 `sqlite3 backup API` 或 VACUUM INTO 保证一致性）。前车之鉴：慧眼 1.5.4 丢过用户记录。

## 7. 里程碑与依赖（建议执行顺序，每批交付可运行版本）

> **进度（2026-10-22，B1+B2已完成）**：
> - ✅ B1：`extract_assets.py` 已含图鉴详情/文化库提取；解析器 `app/core/birddex.py`、`app/core/culture.py` 完成，11171条记录全量sha256校验通过（**记录=固定15字段**：14内容+1空终止，内容字段可合法为空len=0，不可提前break）。
> - ✅ **重大修复：地理先验解码符号**。正确解码 = `(128-uint8)×0.03125` 且 **字节0为哨兵=硬-4.0**，并按元数据 clamp[-4,+2] 截断。旧实现符号相反导致中国区域重排反向（麻雀在北京被压成罕见）。证据链：纽约1月=灯草鹀/主红雀✓、加州=安娜蜂鸟/金冠带鹀✓、北京=麻雀+2.0/灰喜鹊+2.0/家麻雀-1.5(确不在北京)✓。v1的识别重排符号错误已被此修复纠正（e2e: 苍鹭0.59→0.995）。
> - ✅ B2：物种详情页v2（概览/图鉴/文化标签页+当月出现提示+罕见度5档）、每日一鸟横幅、年鸟桂冠徽章（时间线/鸟种卡/统计页）、检测灵敏度设置（低/中/高=conf 0.35/0.25/0.15，存settings.detect_conf）。
> - ✅ B7（部分）：打包验证通过（含新增资产 details/culture 的发布复制——**已修 make_release.py 漏拷这三个文件的缺陷**）。
> - ✅ B3（2026-10-23）：位置数据层+鸟点页。`spots`表+`photos.spot_id`（`Library._migrate`对旧库ALTER）；`app/core/spots.py`（haversine+300m自动归组：300m内并入最近点否则新建"鸟点 N"）；导入页「挂到鸟点」下拉（自动/不挂/已有/＋新建）；查看器信息面板"位置"行+「设为鸟点」对话框（搜索挂载/从GPS新建/解挂，`spot_dialog.py`）；鸟点页（导航插鸟种库后，列表卡片+详情：统计头卡+物种清单胶囊+照片流，编辑/删除）。seed_demo已注入GPS（奥森×2@95m、野鸭湖×2@250m，PIL写GPS的RATIONAL要传浮点度分秒元组不能传嵌套分数）。验收：同地自动归组✓ 手动挂/解挂✓ 截图5张全过✓ e2e/smoke回归✓ 冻结库迁移✓。
> - ✅ B4（2026-10-23）：交互地图 `app/ui/map_page.py`。**瓦片源改高德**（OSM系国内不可达，实测超时；高德webst0{1-4}栅格23ms）：按需加载+`<库>/tiles/`缓存+UA，GCJ-02坐标系——鸟点存WGS84，`app/core/gcj02.py`双向纠偏（往返误差~1m）。自绘slippy map：滚轮整数级缩放（锚点跟随鼠标）、拖拽平移、缩略图圆钉marker+56px屏幕距离聚合气泡（点击放大一级）、点marker弹卡（照片数/鸟种数/3缩略图+「查看鸟点详情」+「在系统地图打开」uri.amap.com/marker）。**POI搜索走高德place/text API**（Key存settings.amap_key，设置页"地图"卡填；实测搜"野鸭湖湿地"96结果含观景平台/停车场），无Key可粘贴"纬度,经度"直跳（按WGS84解释）。**选点模式**：点按地图取WGS84坐标（拖动不触发），`MapPickDialog`接入鸟点编辑「在地图上选点…」。导航新增「地图」（鸟点之后）。照片按鸟种着色marker层→**推迟**（本轮聚焦搜索+选点，B5再议）。
> - ✅ **B4.1（2026-10-23，用户实测反馈后重构）：地图改高德JS API + 鸟点/地图合并 + 改鸟种 + 移除照片**。
>   - **地图重写** `app/ui/amap_view.py`：QWebEngineView+QWebChannel桥，高德JS API 2.0官方交互地图（MarkerCluster官方聚合）。**弃用自绘瓦片的原因**：用户真机实测"搜索正常但地图不显示"——排查发现初始视野(z4中国)瓦片下载正常，但交互后视野被带往北纬85°钳制边界且缩放永远钉死在那（用户所有后续请求全是日期变更线附近的空瓦片），根因未完全定位（QGraphicsView真实屏幕渲染环节，控件grab截图复现不了）。JS API彻底绕开。Key/安全密钥存settings(map_js_key/map_js_secret)+内置用户Key缺省，设置页可改，改动后`ensure_keys()`重载页面。HTML写到`<库>/amap.html`。页面懒加载：MapPage首次切入才创建（WebEngine重，不拖慢启动），main.py在QApplication前设AA_ShareOpenGLContexts+预导入QtWebEngineWidgets。
>   - **鸟点+地图合并**：NAV去掉「鸟点」页，「鸟点地图」=左侧栏（地名搜索+结果列表+鸟点卡片列表+新建按钮）+右侧高德地图+弹卡（详情/编辑）。`SpotDetailDialog`（原鸟点详情改对话框：统计头+物种清单+照片流+编辑/删除）。`spots_page.py`删除。
>   - **改鸟种随处可用**：查看器每条识别记录加「改鸟种…」按钮（`species_pick.py`全库11171种搜索：中文名/学名/英文/拼音/缩写，走`set_confirmed`）；无记录照片可「＋标注鸟种」（`add_manual_record`，source='manual'，计入全部统计）。识别记录徽章加"手工"。
>   - **移除照片**：查看器「从鸟迹移除…」+确认框；`Library.remove_photo`显式删records/exif/photos行（FK级联依赖PRAGMA连接级设置，不可依赖）+清thumbnails缓存；原始文件绝不动。
>   - 验收：视觉子代理全过（map=真实北京影像+pin正确；viewer按钮修复后PASS）；DAO测试（改种/手工标注/移除级联+缩略图清理）✓；smoke/e2e回归✓。
> - 未开始：B5性能、B6生态。注意：详情页对"库内无照片的物种"（如每日一鸟跳转）已支持（概览显示提示，图鉴/文化正常）。
> - ⚠️ **UI重建同一tick截图的坑**：页面内容重建（takeAt+deleteLater）后立即`grab()`会拍到旧控件残留或空布局——deleteLater要等事件循环、QScrollArea重排版也要一拍。`spots_page._clear`已用hide+setParent(None)立即消隐；ui_shots对详情页grab前延时300ms。交互使用不受影响。
> - ⚠️ **QGraphicsView截图的坑（B4实测）**：合成截图（win.grab/祖先render）时QGraphicsView视口可能复用空backing store——整块纯背景色，与场景内容无关。解法：grab前`viewport().repaint()`强制同步重绘，用`viewport().grab()`贴回窗口位置；TileMap加了showEvent重assert中心（QStackedWidget切回同样受益）。PySide6四连坑：reply不回传request attribute（改从URL QUrlQuery解析）、`bool(NetworkError.NoError)==True`（必须显式`!= NoError`比较）、QUrl.queryItemValue已移除、QUrlQuery在QtCore。
> - ⚠️ **QWebChannel桥的方向坑（B4.1实测，排查半天）**：JS侧拿到的QObject里，**signal在JS是`{connect,disconnect}`对象，不是函数**——`bridge.someSignal()`静默无效（typeof='object'）。JS回调Python必须暴露**@Slot方法**，方法内部再emit Qt信号。另：`runJavaScript`的result回调只可靠回传原始类型（对象/数组返回空串），探测脚本要用`String(...)`包一层。地图容器0×0时（页面未显示）AMap的setBounds会算出错误缩放——AmapView.showEvent首次可见时重发一次带fit的setSpots。QWebEngineView内容widget.grab()拍不到（独立进程合成），截图必须PIL ImageGrab真实屏幕（物理像素=逻辑×devicePixelRatioF）。`mapReady`别等AMap 'complete'（要等全部瓦片，>15s），QWebChannel回调建图后立即上报。
> - ⚠️ **待向安卓作者求证**：CN 各省级行的先验向量存在超出 clamp[-4,+2] 的噪声值（字节<64，如 Demoiselle Crane 在 CN 全国行=+3.97），我们已按文档 clamp 截断处理；若安卓/iOS版本同样存在该现象，建议他们检查构建管线对 CN 数据源的处理。

| 批次 | 内容 | 前置 | 预估 |
|---|---|---|---|
| B1 | 资产提取扩展（§2.1/2.2）+ BirdDex/Culture 解析器 + 单元自检 | 无 | 0.5天 |
| B2 | P0 全部：详情页v2 / 文化+每日一鸟 / 年鸟 / 当月提示 / 罕见度 | B1 | 3.5天 |
| B3 | 鸟点数据层 + 鸟点页 | B1 | 1天 |
| B4 | 交互地图 | B3 | 3天 |
| B5 | P2 按需（建议顺序：导入后台化→时间线懒加载→检测框叠加→top200重排→流水线→深色模式） | 无 | 4.5天 |
| B6 | P3：eBird导出 → 备份 → 年度报告 | B2 | 2.5天 |
| B7 | 回归测试（§9）+ make_release 重新打包 + 冻结环境验证 | 全部 | 0.5天 |

每批完成后跑 `tools/ui_shots.py`（截图冒烟）与 `tools/e2e_test.py`，B7 用打包exe验证一次全链路。

## 8. 开放问题 → 已定默认决策（2026-10-22定稿）

用户暂不向作者朋友取材，执行遇阻时整理具体问题清单交用户转问。当前默认决策：

| 原开放问题 | 默认决策 | 若有问题的升级路径 |
|---|---|---|
| 安卓版检测阈值官方值 | 保持 conf=0.25 / iou=0.45（YOLO 官方默认，社区通用），**并把两值暴露到设置页**（"识别灵敏度"：低/中/高三档 = conf 0.35/0.25/0.15），用户自助调节 | 若发现明显漏检/误检，问安卓作者："你们检测用的置信度和NMS IoU阈值是多少？" |
| 慧眼年鸟定义 | 年鸟 = 该物种今年首见 **且生涯首见不在今年**（即"今年回归种"）；生涯首见在今年 → 只显示皇冠 | 若与慧眼行为不符，问iOS作者："'今年新种'是否包含生涯第一次拍到的那种？" |
| 罕见度算法口径 | 自研：用户地区12个月先验最大值的分位数5档（见§3.5），不依赖慧眼口径 | 无需对齐，展示上注明"基于eBird清单频率估算" |
| 迁徙数据包 | **不做**（依赖在线服务，违背本地优先定位；v3再议） | 若朋友愿意公开下载源与格式文档，v3评估 |
| OSEA 模型对比 | **不做**（双模型徒增300MB+复杂度，当前精度已满足） | 若用户反馈识别不准的案例多了再评估 |

## 8.5 用户远期想法积压（2026-10-26 记录，未排期）

- **首页**：点侧栏 logo 回首页（不单独做导航版块）；首页内容待用户想好（候选：每日一鸟、最近导入、年度进度、快速导入入口）。
- **地图免Key方案**：用户觉得依赖高德Key仍不便，想要通用地图（高德或OSM），"参考birdtrace安卓版的地图"——下步先向安卓作者问清他们地图实现（用的什么源/是否免Key）；OSM国内可达性是已知障碍。
- **关于页**：软件介绍 + 开发者信息（用户本人+模型来源致谢等，内容待用户提供）。

## 9. 验收清单（B7 全量回归）

- [ ] `tools/smoke_test.py`：3 测试图 top1 全中（squash 策略）
- [ ] `tools/e2e_test.py`：导入→识别→时间线→lifer→复核→分享卡 全通过
- [ ] `tools/ui_shots.py`：全部页面截图无样式告警（"Could not parse stylesheet"为0）
- [ ] 物种详情：图鉴字段≥4、文化长文可读、当月提示档位随月份变化
- [ ] 每日一鸟：同日确定性、点击跳转
- [ ] 年鸟角标：跨年数据显示正确
- [ ] 鸟点：自动归组、手动挂载、地图marker缩略图、导航唤起
- [ ] 地图：离线打开不崩溃（断网测试）
- [ ] 打包exe：冻结环境识别+详情页+地图全通，日志写入 `<库>/birdtrace.log`
- [ ] 大库压力：seed_demo 扩到 ≥500 张（复制改名+随机日期EXIF），时间线滚动不卡、导入预览不冻结UI

## 10. 踩坑清单（v1 实测，执行必读）

1. **PySide6 6.12 枚举必须带作用域**：`QGraphicsView.DragMode.ScrollHandDrag`、`QFont.Weight(800)`、`QGraphicsView.ViewportAnchor.AnchorUnderMouse`（不是 `AnchorUnderMouse`）。
2. **SQLite 线程本地连接**：`Library.conn` 是 `threading.local` property——任何 QThread 里使用 lib 都自动拿本线程连接，**不要**把 conn 存成实例属性传线程。
3. **引用路径必须绝对**：`scan_sources` 已 `resolve()`；新代码涉及文件路径一律绝对。
4. **f-string 拼 QSS**：非 f-string 续行里的 `}}` 不会折叠——所有 QSS 字符串要么整段 f-string，要么用 `+` 拼接变量后置。
5. **pip 源**：清华镜像对该环境 403，一律 `-i https://pypi.org/simple`。
6. **测试图下载**：Wikipedia 不可达，用 iNaturalist API（`api.inaturalist.org/v1/taxa?q=学名` → default_photo → open-data S3 large 图）。
7. **onnxruntime DML**：分类模型 DirectML 初始化必失败自动回退 CPU（334ms/张，可接受）；检测模型 DML 正常。启动日志里的 "EP Error" 是良性噪音。
8. **frozen 模式**：`sys.frozen` 时 assets 在 exe 旁（`app/paths.py`）；stdout/stderr 已重定向到 `<库>/birdtrace.log`；打包必须用 `packaging/make_release.py`（会复制外置模型），PyInstaller 的 COLLECT 每次清空 dist。
9. **控制台乱码**： subprocess 输出是 UTF-16LE 交织，调试时统一 `-X utf8` 并用 `python -c` 读文件转码查看。
10. **QSS 全局样式与局部 setStyleSheet 共存**：分段控件等动态样式没问题，但避免在全局 QSS 写 `QPushButton:checked` 泛化规则（会打架）。
11. **packaging 体积**：spec 已排除 QtWebEngine/Pdf/Qml/Quick 等；新增功能如需网络（瓦片），用 QNetworkAccessManager，别引 WebEngine。
12. **demo 库重建**：`tools/seed_demo.py`（注入不同年月EXIF+识别）；改 schema 后旧 demo 库要删掉重建。

---
*文档版本：2026-10-22 · 基于v1代码库与APK资产完整逆向。执行时如与实际代码冲突，以代码为准并在本文档标注。*
