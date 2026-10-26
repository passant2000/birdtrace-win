# 鸟迹 BirdTrace for Windows

本地鸟类照片管理软件：Lightroom 式非破坏导入 → AI 鸟种识别（地区×月份先验增强）→ 时间线 / 鸟种库 / 个人成就 / 分享卡。

模型与数据来自 birdtrace.apk（FastViT-MA36 识别模型 10480 类 + YOLO11n 鸟体检测 + eBird 分类体系 + 503 区域地理先验 + IUCN 保护等级）。

## 功能

- **导入**（不动原文件）：选择单个/多个图片文件，或文件夹（可开关"包含子文件夹"）；两种模式——**引用原位置** / **复制到新位置**（按拍摄年月归档）；导入时选择拍摄地区（全球/国家/中国省级）提高识别准确率
- **识别**：后台队列自动跑 检测→裁剪→分类→地理先验重排；一张照片多只鸟会生成多条鸟种记录；低置信度自动进"待复核"
- **时间线**：按拍摄年月分组浏览，个人首见(lifer)角标
- **鸟种库**：11171 种图鉴（中文名/学名/科属/IUCN），按首见排序，支持 中文名/拼音/学名/英文 搜索
- **统计**：照片总数、鸟种数、年度新增/累计柱状图
- **分享卡**：照片 + 「个人第 N 种鸟」+ 中文名(拼音)/英文名 + 拍摄者署名，浅色/深色主题，一键复制到剪贴板或保存 PNG
- **待复核**：对没把握的记录从 Top5 候选（+最近确认过的物种）中确认或纠正，纠正结果计入成就

## 运行

### 方式一：开发运行

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
python tools\extract_assets.py          :: 首次: 从 birdtrace.apk 提取模型与数据
.venv\Scripts\python -m app.main
```

可选参数：`--library <目录>` 指定照片库位置；`--no-gpu` 用CPU推理。

### 方式二：打包 exe

```bat
.venv\Scripts\pip install pyinstaller
.venv\Scripts\python packaging\make_release.py
:: 产物在 packaging\dist\birdtrace\, 双击 鸟迹BirdTrace.exe
```

模型与地理先验库(约530MB)外置于exe旁的 `assets\` 目录。打包版日志在 照片库目录的 `birdtrace.log`。

照片库默认在 `文档\BirdTraceWin\`（catalog.db + thumbnails/），可在设置页查看。原始照片文件永远不会被移动、修改或删除。

## 目录结构

```
birdtrace-win/
├── tools/            # extract_assets.py(资产提取) smoke_test.py e2e_test.py seed_demo.py ui_shots.py
├── assets/           # models/(2个onnx) data/(labels/catalog/geo_prior/regions/iucn)  ← 由提取工具生成
├── packaging/        # PyInstaller spec
├── app/
│   ├── ai/           # detector(YOLO解码+NMS) classifier(FastViT) geo_prior(先验重排) pipeline
│   ├── core/         # importer(引用/复制导入) worker(后台识别) regions sharecard
│   ├── ui/           # 主窗口 + 六个页面 + 查看器 + 分享对话框 (iOS风格QSS)
│   ├── db.py         # SQLite编目库(photos/exif/species/records/batches/v_records视图)
│   ├── exif.py       # EXIF提取(含HEIC)
│   └── media.py      # 内容指纹 + 缩略图缓存
└── data/             # 测试图/演示库/截图 (可删)
```

## 技术要点

- 识别模型输入 `1,3,384,384` RGB[0,1]（归一化内嵌），预处理用直接缩放（squash），冒烟测试中与中心裁剪并列最优
- 先验重排：`final = log_softmax(visual_logits) + 0.6 × prior[区域][拍摄月份]`，未选区域=全球（中性）
- 检测输出 `[1,5,8400]` 无内嵌NMS，应用层解码 + NMS(conf 0.25 / IoU 0.45)
- 待复核阈值：置信度 <0.5 或整图兜底
