# 开源生态学习笔记（2026-10-26）

> 对象：SuperPicky（师兄弟）、SuperBirdTools（朋友）、BirdTrace-FastViT-MA36-10K（HF开源模型）
> 源码克隆在 `D:\tmp2\study\`。许可证注意：SuperPicky=GPL-3.0，SuperViewer=AGPL-3.0，
> HF模型=CC BY-NC 4.0。**借鉴思路自己实现，不要直接抄代码**（否则传染许可证，将来无法自由分发鸟迹）。

## 三个项目的定位差异

| 项目 | 一句话 | 与鸟迹的关系 |
|---|---|---|
| SuperPicky 慧眼选鸟 | AI**选片**（culling）：拍5000张挑出好的 | 上游：拍完先过它选片 |
| SuperBirdTools | **看图/修图**（SuperViewer：降噪/RAW调色/清晰度检测）+ 视频打点（Stamp） | 下游：选出的成片精修 |
| 鸟迹（我们） | **成片管理**：识别→编目→鸟点→lifer→分享 | 中游：管住"值得留下的照片"的一生 |
| HF模型 | 与APK同款 FastViT-MA36-10K 官方开源版 | 我们已在用（APK提取=同权重）；SuperPicky也用它做唯一识别模型 |

三者用的是**同一个识别模型**，生态天然互通——SuperPicky官网明确致谢 BirdTrace (Warden)。

## 高价值可借鉴（按对成片管理的价值排序）

### 1. 连拍分组 + 组内鸟种统一（SuperPicky core/burst_species.py + burst_ranking.py）⭐⭐⭐
- 连拍判定：相邻照片 EXIF 时间间隔 ≤ 1000/FPS 毫秒为一组
- **鸟种统一**：组内"置信度最高且达阈值"的那帧的鸟种=整组鸟种（用户1372组实测分歧仅4组）；消除"3张阔嘴鹬+1张尖尾滨鹬"拆组问题
- **组内最佳**：分层排序键（对焦档，0.7×眼清+0.3×头锐）
- 对我们的意义：成片管理核心痛点——同一只鸟20张连拍在时间线/统计里全是重复。借鉴：时间线按连拍折叠、组内选代表图、鸟种判定整组统一。眼清/头锐可先用简单的拉普拉斯方差替代（不依赖SuperPicky的鸟眼模型）。
- **纯算法，可无版权自实现**

### 2. GPS→地区自动定位（SuperPicky region_locator.py）⭐⭐⭐
- Natural Earth admin-0/admin-1多边形做点在多边形，离海370km内就近归属；五步兜底顺序讲究（包含优先于就近）
- 对我们的意义：现在导入要**手选拍摄地区**（先验重排用）；带GPS照片可自动定到省，识别更准且零操作。GPS→region→geoprior自动链路。
- 实现：Natural Earth数据公有领域，思路可自实现（或用 reverse_geocode 简化版）

### 3. XMP/EXIF 元数据回写 + Lightroom互通（SuperPicky）⭐⭐
- 评分/锐度/鸟种写入照片元数据（锐度用 XMP-photoshop:City 字段，0-1000刻度，与SuperViewer约定互通）
- LR插件（Lua）经本地HTTP server（birdid_server.py）识别当前照片
- 对我们的意义：**用户是Lightroom用户**——鸟迹的鸟种名/评分/鸟点写进XMP边车后，LR里可直接过滤"普通翠鸟"；反之LR星级可读进鸟迹。打通两个软件的工作流。
- 实现：pyexiv2/XMP边车自写，字段自定义（不占City，用我们自己的namespace更干净）

### 4. 地区候选集过滤（SuperPicky geo_filter.py）⭐⭐
- ebird_regions.db 存每个国家/省的物种类别集合，识别时三级放宽（省→国家→不过滤）**硬过滤候选**
- 与我们的geoprior（软重排，月度感知）互补：他们挡"该地区绝对没有的种"，我们调"该月常见的种"。可叠加：先硬过滤+再软重排。他们的DB派生自eBird清单。
- 注意：他们没有月份维度（迁徙鸟会误杀），叠加时保留我们的月度先验为主

### 5. SuperPicky对同款模型的预处理结论 ⭐
- 他们的验证（2026-10-21五组手工核对）：YOLO方形裁剪**直接resize**（不加边距）；整图先中心方形裁再resize；BICUBIC
- 与我们不同：我们=检测框外扩10%再squash。我们的e2e基准上squash策略胜出。**不盲从**，将来可做一次两种策略的A/B（同图对比top1）

### 6. SuperViewer工程实践 ⭐
- Qt offscreen测试conftest、exiftool打包诊断（--check-exiftool自检）、单实例、模型多级查找链（环境变量→用户目录→自带→同级安装的SuperPicky）
- NAFNet降噪/yolo11l-seg+SAM2.1分割/RAW调色（Rust扩展）——重修图能力，与成片管理定位不同，暂不引入

## 不建议碰

- SuperBirdStamp（视频打点）：与照片管理无关
- TOPIQ美学/鸟眼关键点模型（cub200_keypoint）：选片域，成片已人工挑过；除非将来做"连拍最佳"要精细眼清度
- 直接复制任何GPL/AGPL代码或数据文件

## 已确认事实

- HF模型=我们APK提取的同一份（10480类/384输入/logits直出）；SuperPicky改进裁剪后测得97.1%（iNaturalist测试集）
- SuperPicky V4.0.5起也迁SQLite（提速1.9x），验证了我们SQLite路线
- SuperViewer清晰度字段与SuperPicky互通（XMP-photoshop:City）——若我们做锐度，建议**不跟随这个hack**（City字段装数字是历史约定），用XMP自定义namespace

## 建议落地顺序（成片管理主线）

1. **连拍折叠+组内统一**（纯算法，无新依赖，时间线体验质变）
2. **GPS自动地区**（带GPS照片零操作更准）
3. **XMP回写鸟种/评分→LR互通**（用户LR工作流闭环）
4. 硬过滤+软重排叠加（需要自制eBird区域物种集合，工作量中等）
