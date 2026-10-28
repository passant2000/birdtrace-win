# 鸟迹 Win · 进度记录

> 进展以本文件为准；规格与踩坑清单见 PLAN.md；后续路线见 后续开发方案.md。新会话从这里接手即可开工。

## 2026-10-28 · 双语静态检查工具 + i18n补漏 + 后续开发方案

- **`tools/check_i18n_static.py`**：AST扫描 t()/sname() 外的裸中文（f-string含），docstring/双语元组(`("中","En")`)自动豁免，gpu_probe(诊断报告刻意中文)/theme.py(QSS注释)整文件跳过，数据/日志行尾 `# i18n:ok` 豁免——**当前CLEAN**，列入每版必跑。
- **静态扫描抓到真漏网并已修**：①`species_pick.py`选鸟种对话框整体漏翻（当初运行时扫描没覆盖）→全量双语（列表保留中英双名同显，验证器skip_lists）；②prior_hint层级码（常见/偶见/稀有…）在图鉴chips里EN模式显中文→加TIER_EN+tier_display()；③importer"检查"进度、spots"无坐标"、main资产缺失提示→t()；④amap_view `_t`别名归一。verify_i18n扩到32项全过。
- **`docs/后续开发方案.md`**：现状基线/双语规范/版本路线(0.5.5正式版→0.6.0图鉴迁徙A/B/C)/GitHub待办/每版固定流程——切换模型后的新会话交接书。
- 注：以上补漏未打包（源码领先test2包），下次构建自动包含。

## 2026-10-26 · v0.5.4网站专版介绍素材（用户朋友网站要做介绍页）

生成器 `tools/make_intro_poster.py`（QPainter，米色系与年报同源）→ `releases/网站介绍素材包/`：**intro_v0.5.4.png** 介绍长图（1080×4029，手机友好：logo头部/4亮点/6张界面卡/功能清单/怎么用/页脚致谢）+8张精选截图+`releases/网站介绍文案.txt`（编辑可直接复制的标题/简介/正文/致谢与"非商业勿捆绑付费"注意事项）。自检抓到页脚与"怎么用"重叠已修（画布预算+120，页脚固定底部绘制）。分享卡图share.png为竖图按横框裁剪后保留中段属预期。**给用户的交付方式：素材包文件夹整体转发（微信传文件夹或网盘链接），长图单发手机可直接看**。

## 2026-10-26 · v0.5.5-test2：全模块中英双语 + 移除个人高德Key + GitHub准备（待用户实测）

用户指令：0.5.4稳定版基础上做中英文（设置里选语言、确保每模块双语）、去掉自己的高德apikey（模型作者的MapTiler团队Key保留，中转安全）、可以上GitHub。
- **i18n方案**：`app/i18n.py` 极简内联 `t("中","En")`（无key表不错位）+`sname(cn,en)`物种名（EN模式显示英文名）；语言存库`lang=zh|en`；切换=整窗重建（复用主题切换机制，`_rebuild_window`共用，含worker/aes_worker停机）；启动时main.py读库set_lang。regions.build_tree按语言缓存（en用sourceName英文国名）。
- **落地方式**：8个并行子代理按文件分工替换（~350条t()），关键坑=**模块级常量在import期求值t()会冻结语言**——NAV改`_nav()`工厂、徽章名改(中,En)元组显示时t(*)、SpotPickDialog默认参数移进__init__；**局部变量遮蔽`t`**——5处`for t in`/`t=QLabel`改名（py_compile查不出，运行才炸，verify_i18n抓到map_page._show_popup一处）。stats的24徽章/分享卡罕见度/年报月份/文化页IUCN/图鉴字段全部双语。
- **不翻译（按设计）**：图鉴正文、文化故事、物种中文名（EN显示英文名）、鸟点名/备注（用户数据）。
- **Key移除**：amap_view三个DEFAULT(Js/Secret/Web)置空；POI搜索无Key时提示配置；高德官方引擎无Key不加载（占位提示）；设置页文案改"填自己的Key"。**MapTiler团队Key保留**。make_logo.py里的个人路径已清理。
- **验证**：`tools/verify_i18n.py` 30项全过——ZH+EN双语言各扫7页面+鸟种详情+地图弹卡+5对话框，EN模式中文残留=0（库内数据字符串鸟点名/科名/文化故事按设计排除+白名单"中文"语言选项）；双语言截图存data/ui_shots/i18n_*.png；回归美学/弹卡/multibird/rebox/viewer/concurrent全过；冻结冒烟：worker中文路径2/2+GUI中文启动(美学回填2/2)+GUI英文启动存活。**教训：视觉目检子代理对UI截图产出幻觉（虚构不存在的控件），排版结论必须程序化测量复核——最长EN提示631px vs 可用1144px无溢出**。
- releases/鸟迹BirdTrace-v0.5.5-test2-便携版/（933MB，与0.5.4正式版并存）。**用户确认后→0.5.5正式版**；GitHub：.gitignore已备（assets/data/releases/dist全排除，源码-only仓库），本地git init+首提交完成，推送等用户建仓确认。

## 2026-10-26 · v0.5.5-test1：「最美鸟照」TOPIQ美学评分（待用户实测）

v0.5.4发布后开工的趣味功能（用户确认test1后直接推进，见上一条）。**全链路已打通**：
- **模型**：TOPIQ cfanet_iaa_ava_res50（pyiqa名`topiq_iaa_res50`≠`topiq_iaa`——后者是swin骨干会去github拉timm权重被墙挂死，第一坑）；pth从hf-mirror下载放`~/.cache/torch/hub/pyiqa/`免下载；torch导出（temp py312: `data/py312x/`，**torch 2.14 dynamo导出器默认把权重存外部.data需内联回单文件**、fp16转换必须keep_io_types=True否则输入变fp16）；forward默认输出MOS（score_linear末尾Softmax+dist_to_mos，应用侧零解码）。**等价验证：fp32 Δ=0.0000逐位一致、fp16 Δ≤0.005、排序一致、模糊图最低分**。`assets/models/AestheticTOPIQ_fp16.onnx` 133MB（799→932MB）。
- **应用**（无torch依赖，走现有onnxruntime CPU）：`photos.aesthetic REAL`迁移；`app/ai/aesthetic.py`评分器（PIL LANCZOS 384直拉+0~1输入，归一化在图内）；`AestheticWorker` QThread回填（只评有records的，分批commit）；main_window钩子=启动8s后拉起+识别完成拉起+导入/识别中让路+aboutToQuit停线程；状态栏"美学评分中x/y"。
- **UI**：鸟种详情墙按评分降序+首项★最美徽章（PhotoGridItem.corner）；species_overview封面=该种最美；年度报告加「年度十八图」卡片+长图6列区块（best_of_year：rank=1记录、每 种≤2张）；查看器信息面板显示分数。
- **验证**：`tools/verify_aesthetic.py` 20/20（评分语义/迁移/回填线程/排序封面徽章/十八图cap/长图渲染）；回归species_map_fix/multibird/rebox/viewer全过。**坑：JPEG改1像素若差值太小会被量化吞掉→hash重复去重，测试副本要大差值**。
- releases/鸟迹BirdTrace-v0.5.5-test1-便携版/。**用户实测确认后→打0.5.5正式版并清理临时工具链（data/py312x≈3GB、pth、fp32 onnx）**。

## 2026-10-26 · **v0.5.4 正式版发布**（releases/鸟迹BirdTrace-v0.5.4-便携版/，799MB唯一保留版本）

用户确认test1没问题后定稿（0.5.4 = test1内容 + 版本号，冻结冒烟：worker中文路径识别2/2+落库、GUI存活20s）。旧release（0.5.3/0.5.3.zip/test1）已删。启动慢预期已写进使用说明（排除项设置后下一次仍慢一次→之后秒开；重启后第一次慢几秒=冷读）。

## 2026-10-26 · v0.5.5「最美鸟照」开工：TOPIQ美学评分（进行中）

用户需求：每种鸟最美照片排前+封面；年度报告加"年度18图/12图"。调研结论（SuperPicky，GPL代码不抄）：只用一个美学模型即可——**TOPIQ cfanet_iaa_ava_res50**（AVA数据集，1-10分，IQA-PyTorch出品，权重复制在 data/model_experiments/cfanet_iaa_ava_res50-3cd62bb3.pth，经hf-mirror下载；权重无明确许可=个人自用口径，我们免费自用OK，不引入SuperPicky任何代码）。SuperFlier飞行姿态（"运动检测"）不需要，暂缓。
技术路径：.pth→ONNX导出用临时Python3.12工具链（本机3.14无torch win轮子——只有cp314t free-threaded；安装包python-3.12.10-amd64.exe已下到data/model_experiments/，装到data/py312，导完即删）；导出fp16 ONNX后做pyiqa对照等价验证（老规矩：分数排序一致性）；应用侧零torch依赖，走现有onnxruntime（CPU约0.1-0.2s/张，后台线程打分）。

## 2026-10-26 · v0.5.4-test1：鸟种库首开提速 + 地图弹卡切换修复（待用户实测）

用户v0.5.3实测反馈两项bug：
- **鸟种库首开慢（图多的鸟种第一次打开卡）**：根因=导入时已给每张照片生成512px缩略图缓存，但鸟种详情页要256px——尺寸不同缓存不命中，首开同步解码该种全部高像素原图（每张~0.3-0.6s × N张整页卡死，第二次打开有缓存才快）。三层修复：①`media.ensure_thumbnail`缺尺寸时先找已有的**更大尺寸缓存**降采样，不再解码原图（实测单张58ms→6.5ms约9×；原图丢失/引用盘拔掉时也能出缩略图）；②鸟种详情网格只查缓存即时渲染（新增`cached_thumbnail`不生成），缺的后台QThreadPool逐张补齐点亮（代际号+原地中断标记防串台，返回列表任务即作废）；③删掉`_show_detail`里每次全表GROUP BY却从不使用的`species_overview()`调用。时间线/待复核/地图/弹卡等所有页面的缩略图自动受益于①。
- **鸟点地图弹卡切换后空白遮挡**：根因=`_show_popup`清理旧布局写成`while self.popup.layout():`——布局清空后条件永真，`takeAt(0)`返回None→AttributeError中断重建（PySide6槽内异常被吞只打印），旧控件已删新内容没建→左下角只剩空白卡片。第一个点正常是因为popup当时还没布局、循环体不执行。修复=复用布局+`while lay.count():`清空，旧控件`setParent(None)`立即摘除（不等延迟删除，无残影）。
- **验证**：`tools/verify_species_map_fix.py` 13/13——60张图种首开22ms网格全渲染、后台补齐60/60点亮、二次打开全缓存28ms、返回列表任务作废、弹卡甲→乙切换内容正确无残留、marker路径连切7次稳、×关闭正常；回归multibird/rebox/viewer/concurrent全过（concurrent结尾QThread警告是测试脚本自身worker替换回收，与本次改动无关）；冻结冒烟：`--recognize-worker`中文路径2/2识别+父进程落库2/2、GUI启动存活25s。
- releases/鸟迹BirdTrace-v0.5.4-test1-便携版/（799MB，与v0.5.3正式版并存）。**用户实测确认后→打0.5.4正式版**（发布规则：test*给用户测，确认才升号）。
- 启动慢用户反馈（2026-10-26）：设Defender排除项后"下一次启动仍慢一次，之后秒开"——排除项已生效（扫描成本归零），残余首开=800MB首次冷读入内存+安全软件收尾，一次性属预期；开机后第一次仍会慢几秒（冷读非扫描）。使用说明.txt已按此口径改写预期。根治仍只有代码签名（无公司主体不现实）。

## 2026-10-25 · **v0.5.3 正式版发布**（releases/鸟迹BirdTrace-v0.5.3-便携版/，799MB，唯一保留版本）

用户确认test11全部功能后定稿。0.5.3 = test11最终内容 + 版本号（同代码，冻结验证3/3中文路径识别过；U盘47张终验因U盘不在跳过——同代码路径已有冻结3/3+并发6/6覆盖）。
**0.5.2→0.5.3 变化**：GPU识别（模型Reshape allowzero手术）；导入识别并行（波次循环+双计数状态栏）；画框识别独立工具（三处同步回传）；查看器2×2按钮网格+开始导入置顶+图片自适应+最大化+路径点击定位；中文路径识别修复（_force_utf8_stdio）；文化库防崩；导入免等预览；WebEngine懒加载（启动~3s，其余为Defender扫描）；计数口径定稿；显卡诊断--gpu-probe隐藏保留。
**遗留/后续**：①启动首扫慢=Defender无签名扫描，正解=排除项（readme有步骤）；要分发再考虑Azure Trusted Signing(需公司主体)。②检测模型=YOLO11n nano档（APK同款），鸟站牛背类遮挡场景弱——U盘回插后tools/det_sweep.py扫成片+用户看标注图；根治需向APK作者要更大检测权重。③解码并行化（reader线程死锁）已回退，吞吐优化待重做。④打包坑全记录见birdtrace-windows-project备忘。

## 2026-10-25 · test11迭代4（导入识别并行+状态栏双计数）

用户需求：导入和识别都要时间，导入的同时就开始识别。
- **worker波次循环**：run()改为`while not stop: 查pending→处理一批→再查`——识别中新增的照片（导入并行入库）在下一波自动拾取；子进程跨波次复用。**测试抓到关键bug：预发窗口(INFLIGHT)只在"新建进程"分支执行，第二波起复用活进程时窗口永远为空→死循环空转**（症状：识别完首批就卡住不退出也不拾取）——预发必须移到通用路径。
- **并行拉起**：ImportPage._import_progress每张入库都调win.start_recognition（已在跑则跳过，退出则重启）；导入完成_import_done再兜底拉一次→"识别不全"双保险。**重复识别机制上不可能**：pending=无识别记录的照片，处理完即出队；全局同时仅一个worker（start_recognition的isRunning守卫）。
- **状态栏双计数**（用户要求区分"导入几张/识别几张"）：_import_progress_tick上报导入进度；_update_status在importing时显示"导入中 x/y · 已识别 N 张"（N=COUNT DISTINCT photo_id，累计值，消除波次归零闪烁）；_recognition_progress不再按done/total改chip（波次会闪）。并行期间_recognition_done静默收尾（不抢状态、丢失弹窗推迟到导入结束后那波）。
- **验证**：tools/verify_concurrent_recog.py——识别中追加2张被自动拾取(5/5)、worker退出后重启拾取(6/6)、pending清零；verify_rebox 19/19回归；冻结3张中文路径3/3识别。

## 2026-10-25 · test11迭代3（启动慢定位+开始导入挪顶部+WebEngine懒加载）

用户反馈：①双击启动慢 ②开始导入按钮在底部不方便。
- **启动慢定位（数据定案）**：源码模式全程1.5s；冻结版分段计时（main.py加`_startup_mark`，BT_TIMING=1写exe旁startup_timing.log）显示**应用代码仅3.2s**（MainWindow构建3.0s=Qt DLL冷加载）；窗口出现11~41s——期间进程CPU仅0.5~1.5s，**其余全是IO等待=Windows Defender对未签名800MB程序的每次启动逐文件扫描**（重建/重新拷贝后首次启动全量扫描可达40s，之后有缓存约11s）。缓解=用户侧加Defender排除项（readme已写步骤）；根治=代码签名（无证书不现实）。**教训：测启动要区分代码耗时与AV扫描，MainWindowHandle轮询+分段计时是有效手段。**
- **WebEngine懒加载**：main.py去掉QtWebEngineWidgets顶层import（AA_ShareOpenGLContexts属性保留仍在QApplication前设置）；map_page的`from .amap_view import ...`全部下沉到使用处（模块级import会被main_window顶层import连带拉起194MB DLL）——`main_window导入后WebEngine模块: 未加载`已验证；冻结版--open-page map实测正常。Qt6允许QApplication后再import QtWebEngineWidgets。
- **开始导入挪顶部**：从底部动作条挪进"来源"卡（选文件/选文件夹旁边），底部只留进度+状态。
- 重建后冻结：窗口出现21s(map页)/11s(普通)与AV理论一致；导入页offscreen冒烟过。使用说明重写（含启动慢说明+Defender排除步骤）。

## 2026-10-25 · test11迭代2（回传三处+按钮排布+去bat，同版本号原地重建）

用户实测反馈：①画框好用精度高，但确认后"结果没回传"（_accept只写库未刷新身后查看器）；②典型路径=待复核/鸟种库→查看器→画框，要求三处同步；③查看器按钮排布随意；④显卡检测.bat不要了。
- **回传三处**：_accept里 parent(PhotoViewer)记录列表刷新 + win.pages[species/review].refresh() + win._refresh_pages()（状态栏/待复核角标）。verify_rebox加StubPage刷新计数断言 **19/19全过**，viewer/multibird回归全过。
- **按钮排布**：查看器右侧底部改2×2等宽网格——上行[✚画框识别…][生成分享卡]常用，下行[设为鸟点][从鸟迹移除…红字]管理。
- **显卡检测.bat移除**（--gpu-probe代码保留为隐藏调试入口）。重建后冻结识别2/2✓，使用说明已更新。

## 2026-10-25 · test11原地重建（文化库防崩）+ 清理旧版本

用户报打包版启动崩溃：`culture.stories_for -> sqlite3.DatabaseError: database disk image is malformed`。排查：D盘源/发布两份bird_culture.sqlite sha一致+integrity ok——**坏的是用户U盘拷贝**（拷贝损坏13MB文化库）。但可选资产损坏不该让主程序起不来：culture.py加`_rows()`容错（连接失败置None+查询失败返回空，故障时文化功能静默降级），坏库验证stories_for/daily_pool/display_associations均返回空不炸、好库962故事正常。test11同版本号原地重建（用户反对版本号膨胀），冻结识别2/2。**旧release目录已全部删除只留test11**（用户指示；释放~6GB）。
- U盘拷贝损坏的教训给用户：拷完先启动一次验证再带走；以后考虑加启动自检+损坏文件提示。

## 2026-10-25 · v0.5.2-test11：画框识别改独立工具窗口（用户test10反馈）

用户反馈：rebox不起作用/不知道哪触发（test10打包版里"点重新识别没反应"）+ 查看器框影响观感。改为用户提议方案：
- **查看器净化**：删检测框叠加(BoxItem/悬停高亮/eventFilter)、行内重画按钮、_rebox_with等整套内嵌管线——回归纯看图。
- **`app/ui/rebox_dialog.py` ReboxDialog独立窗口**：入口=查看器右面板醒目按钮「✚ 画框识别…」（分享卡下一行）；打开即框选模式（复用ZoomableView.begin_draw），框鸟松手→CPU子进程识别→结果卡（画框徽章+top5下拉可换）→「加入结果」(add_records入库,鸟种库同步)→可连续框多只；「重画」重试；关窗杀子进程。
- 修坑：①species_info返回sqlite3.Row无.get()（结果展示崩溃,数据已入库只是UI崩——测试为何仍ALL PASS的原因）②_esc方法在块删除中被误删(启动即崩,立即暴露)。
- 验证：verify_rebox改写为对话框流17/17全过零Traceback（含画框模拟/矩形落库/加入计数/杀进程）；multibird更新断言（不再有框叠加）+viewer回归全过；冻结中文路径2/2。test11=799MB。
- test10的"点了没反应"根因未在打包版复现（test10按钮在记录行内,可能用户点的是别处或版本混淆）,新入口独立按钮规避了歧义。

## 2026-10-25 · 检测质量排查（用户问：为何安卓/iOS能框住鸟我们框不住，rebox是否白做）

用户质疑（合理）：牛背鹭站牛背场景安卓/iOS一枪命中，我们的框有时没框住鸟——若检测准就不需要重画框。排查结论（进行中）：
- **实现层无bug**：detector.py的letterbox(640/RGB 0-1/pad114)/cxcywh解码/pad减除/scale还原/NMS(0.45)与Ultralytics标准逐项对齐；APK内检测模型metadata证实=YOLO11n/640/nms=False，我们的契约完全正确。
- **关键事实**：①我们的检测模型=APK同款YOLO11**n**（nano，最小档，作者为手机速度选的）；②iOS慧眼是另一个App用**自己的检测器**（很可能是更大的模型）——"iOS更准"大概率是模型能力差异而非我们的代码bug。③APK dex里有`BirdDetectionSelection`类（安卓也有检测选择交互），阈值藏字节码。
- **实证工具**：`tools/det_sweep.py`（可换SRC目录）扫conf阈值+输出标注图到 data/ui_shots/det_check/。本地6张test_images全部0.25检出（绿头鸭2框正确）。**待用户插回U盘后对47张成片复扫+用户看标注图判断几何**；用户还应提供一张"鸟站牛背"实拍复现。
- 可行动项（等实证）：设置页已有灵敏度(0.35/0.25/0.15)，若成片实测0.25漏检多→默认改0.15或加"极高"档；检测模型想升级需向APK作者要更大的检测权重（我们只有nano）。
- rebox定位=兜底工具（butt crop再准的检测器也救不了分类器），保留但非主路径。

## 2026-10-25 · v0.5.2-test10：重画识别（用户方案）+ 导入免等预览 + 流水线回退

用户test9实测（5080）：①GPU工作了但"只快一丢丢"（GPU 3%→10%、CPU不再100%）②调框难用（难抓/不能改大小/识别后弹回）③导入选文件夹后等预览很久。5080探针：检测DML 2ms/张、分类DML 8-29ms/张（快10-20倍）——瓶颈实为高像素照片解码，GPU在等解码。
- **调框→重画（用户提议，正确解）**：删掉整套BoxItem拖拽+角点（难抓根因=fit缩放下4px画笔≈1屏幕像素；弹回根因=拖拽未写库时重识别读回旧框）。改为「重画识别」按钮→`ZoomableView.begin_draw`（RubberBandDrag框选，mousePress/Release映射场景坐标；**PySide6坑：mapToScene单点只收QPoint不收QPointF需.toPoint()**；Esc取消且不关查看器）→松手自动`_rebox_with`（QProcess单张重识别，**--cpu**）。verify_rebox 17项全过（含框选模拟/Esc/新框落库/关窗杀进程）。
- **导入免等预览**：`_set_sources`扫描完立即`go_btn.setEnabled`，预览后台继续（hash/缩略图只服务可视化，导入流程不依赖）。
- **解码流水线并行化尝试→回退**：子进程reader线程+3线程解码池+父进程滑动窗口(INFLIGHT=3)。本机复现**子进程死锁**（0% CPU干等，faulthandler都不触发→卡在import管线阶段；invalid行秒答、valid行必挂；与DML无关，--cpu同样挂）——根因未明（疑似stdin reader线程与import的交互），**已回退顺序一问一答循环**（保留--cpu开关、box第5列、父进程窗口与顺序子进程天然兼容）。GPU批量识别收益保留；吞吐优化后续在安静环境重做。
- worker死锁排查方法沉淀：faulthandler.dump_traceback_later、py-spy（本环境装不上）、按CPU占用判忙等/干等。
- 冻结验证：中文路径3张批量识别4条/0失败/3种 ✓。test10=799MB。

## 2026-10-25早 · v0.5.2-test9：GPU模型+拖框重识别（已打包）

- test9 = test8全部 + 拖框重识别 + DML手术版分类器。构建后验证：①包内模型确认手术版（Reshape allowzero≠0 的=0）②**冻结探针：分类器DML默认ok，110ms/张 vs CPU 329ms（包内3×提速实测）** ③冻结识别中文路径2/2。使用说明含5080验证指引（任务管理器GPU占用应明显上升）。
- 用户5080实测验证点：GPU占用、识别速度、拖框重识别手感。确认后出v0.5.3。

## 2026-10-24晚 · GPU打通：分类器Reshape allowzero手术（等价验证全过，已换入正式位）

5080探针结果与AMD本机**逐字节同型**（EP Error同为position 286；检测器DML全ok、分类器全静默回退）→ 排除显卡/驱动/双显卡路由，**问题在模型结构**。用户条件：GPU能用+识别逻辑与精度不变（确认我们调用逻辑=作者逻辑：检测→裁剪→分类→先验重排，问题出在DML加载期算子注册，与调用无关）。
- **确诊**：FastViT分类器(opset18, torch导出)里26个Reshape带`allowzero=1`属性——opset18新特性DML EP未实现，注册期E_INVALIDARG整模型被拒。shape均无0维（allowzero语义=shape中的0沿用输入维），置0完全等价。CastLike(36个)无需动。
- **手术**（tools/dml_fix_model.py，最小改动只动allowzero）：①CPU等价性=6张图logits**逐元素最大差0.0**（位级一致）②DML生效（get_providers()=DML）top1全一致、概率差1.5e-06 ③性能：分类器CPU 442ms→DML 117ms/张（本机AMD卡**3.8×**，5080应更高；检测器原本就走DML 20ms）。
- **换入**：assets/models/BirdTraceRecognitionModel.onnx ← 手术版；**原模型原样备份** data/model_experiments/BirdTraceRecognitionModel_原始备份.onnx（旧_dml/_sim实验品已删）。应用代码零改动（文件名不变自动生效）。
- **全链路回归**：U盘成片47张两轮 47/47、鸟种2种（红尾歌鸲8+白颊噪鹛39）与原模型结果**完全一致**、lifer顺序一致 ALL PASS。
- **待办**：下一包（含拖框重识别+GPU模型）出后，5080实测：任务管理器GPU占用应明显上升、识别明显变快。tools/verify_dml_fix.py 可随时复验等价性。

## 2026-10-24 · 拖框重识别（用户需求，未打包——等5080测试报告一起出包）

用户反馈(test8实测后)：检测框已在查看器上，希望 ①框可移动 ②查看器内"用调整好的框重新识别"。参照物：安卓版birdtrace能及时识别牛背鹭站牛背（检测模型同源，能力等价，框可视化后用户可自行验证）。
- **管线**：`RecognitionPipeline.recognize_box(img, box, region, month)` 跳过检测直接对指定框分类（重构出公共`_classify_box`），source='rebox'。
- **子进程协议扩展**：任务行可选第5列 `x1,y1,x2,y2` → worker走recognize_box；无该列=原检测路径（向后兼容）。`build_worker_cmd()`抽到recognize_sub公用（worker.py同步改用，冻结态exe自我复用逻辑单点维护）。
- **查看器**：①检测框改为`BoxItem`（ItemIsMovable）可整体拖动——**交互路由**：按在框上=拖框（临时关ScrollHandDrag），按空白=平移画面；**几何归一坑**：松手必须用`rect().translated(pos())`而非sceneBoundingRect（后者含画笔半宽外扩，框会悄悄放大2px）。②拖动松手`update_record_box`写回+缩略图刷新。③每条带框记录新增「重新识别」按钮→**QProcess常驻识别子进程**（首次点击拉起加载模型~7s，之后单张~1s；readyReadStandardOutput事件驱动解析；done()时kill+waitForFinished防QProcess析构告警）；结果`replace_record`原位替换（record_id/rank不变，reviewed重置）。④'rebox'来源显示橙色「改框」徽章。⑤后台批量识别进行中时按钮弹提示暂禁（防双进程双份模型内存）。
- **验证（verify_rebox.py 13项全过）**：同框重认结果一致/协议box列+兼容/db写回/E2E拖框(平移120,80精确落库170,140)+归一/重新识别异步完成source=rebox/关窗杀进程。verify_multibird+verify_viewer回归全过。截图 data/ui_shots/rebox_viewer.png。
- **未打包**（用户指示：先试可行再做、不打包，等其5080测试报告回来分析GPU后一起出包）。

## 2026-10-24 · v0.5.2-test8：多鸟选择/单条删除 + 查看器路径显示（用户反馈三项）

**bat闪退事故（当晚修复）**：用户双机实测「显卡检测.bat」闪退无txt——根因是bat文件被Write工具写成UTF-8，而cmd只认ANSI(GBK)，中文行全成乱码命令直接崩。已用GBK+CRLF重写`packaging/显卡检测.bat`并同步到test7/test8目录；本机以用户路径（cmd执行bat）完整验证：中文正常显示→探针跑完→gpu_probe_result.txt生成（本机结果同test7：检测器DML全ok含device_id=0/1，分类器全partial回退CPU）。**教训：bat/中文文件名相关产物绝不能用UTF-8写，必须GBK编码+CRLF（Python open(encoding='gbk', newline='\r\n')）；验证必须走用户真实路径（双击/cmd执行bat）而非只测exe本身。**

用户反馈：①一图两鸟（同种，其中一只只拍到屁股）被识别成两个不同鸟种进鸟种库；②查看器要显示路径/文件名且路径可点击；③（去5080测显卡，探针已在test7）。
- **多鸟选择（弃弹窗取行内交互）**：查看器识别记录行新增 ①该记录检测框的**裁剪缩略图**（box_json是原图xyxy坐标，QPixmap.copy直接裁）②**悬停行→大图高亮该鸟红框**（QGraphicsRectItem覆盖在场景上，其余框黄色细线）③**单条「删除」按钮**——`db.remove_record()`: 删单条+其余rank顺位重排（rank必须连续因rank=1=主鸟）；**全部删光时置rec_fail=3**（否则下次启动pending又把它识别回来，"删了又复活"）；鸟种库自动同步（该种无照片即消失）。
- **查看器信息面板**：顶部加文件名（粗体）+完整路径（`<a href='open-path'>`，linkActivated→`explorer /select,路径` 打开文件夹并选中）。
- 顺手修存量bug：viewer文件丢失提示分支用了未定义的`LABEL_2`（打开丢失文件照片必NameError，从未被测到）。
- **验证（verify_multibird.py 全过）**：删除后rank重排[1,2]/误识种从库消失(4→3种)/删光→rec_fail=3且不在pending/手工标注仍可用/缩略图+框+路径链接UI断言+截图。冻结回归：中文路径2张识别2/2✓。test8=test7全部+以上三项。
- 用户确认后 → v0.5.3（GPU结论出来一起定最终内容）。

## 2026-10-24 · v0.5.2-test7：显卡诊断工具（5080用户实测CPU 100%/GPU 3%后）

用户在拯救者Y9000P(5080)实测test6：识别时GPU 3%、CPU 100%→DML在NVIDIA上也未生效。用户另要求：25MB裁剪撤掉不做。充电器(245W氮化镓)与provider选择无关。
- **新增 `--gpu-probe` 显卡诊断模式**（app/ai/gpu_probe.py + exe旁「显卡检测.bat」）：环境信息+两模型×{DML默认/详细日志/关图优化/device_id 0/1/2/CPU基线}矩阵，逐项记录"请求vs实际生效provider"+随机张量实测3次耗时，结果增量写入exe旁 gpu_probe_result.txt（os.dup2收原生fd日志——中文Windows的EP报错GBK/UTF-16混杂，Python层redirect收不到；探针发现ORT原生日志以类UTF-16写入文件，grep匹配不上但人可读，分析时注意）。
- **本机(AMD)探针结果**：检测器DML全配置ok(20ms/张,GPU真在算！device_id=0/1都通)——**现状=识别已是"GPU检测+CPU分类"混合**；分类器DML全配置partial(创建不抛异常但get_providers()=CPU,静默回退)。原生错误定位到：**`Reshape node 'node_view_18'` + MLOperatorAuthorImpl.cpp(2853) E_INVALIDARG**——分类器模型里某个view/reshape导出的算子被DML拒。
- **修复方向（等5080探针结果分流）**：5080 DML能通→固化device_id等配置进make_session；同样被拒→用onnx工具改写分类器Reshape为DML兼容的等价表达（不动精度，模型文件本身重导出）。
- 冻结回归：中文路径2张识别2/2 ✓ 探针exe模式写文件 ✓。test7=test6+探针，无功能差异。
- 用户确认后 → v0.5.3（等GPU结论一起定内容）。

## 2026-10-24 · v0.5.2-test6：瘦身回799MB（用户test5本机通过后反馈）

用户实测test5通过（中文路径修复确认✓），另提两点：体积膨胀（0.5.1=799MB→test5=1226MB）+ GPU能否用。
- **膨胀根因**：不是打包膨胀（_internal两版完全一致459MB），是 `assets/models/` 里DML排查时代的两个实验模型（`_dml`=CastLike替换版 214MB、`_sim`=简化版 212MB）被make_release的 `*.onnx` glob全量拷入。已移到 `data/model_experiments/` 保留（5080的DML排查可能复用），make_release改白名单只拷两个运行时模型。**test6=799MB，与0.5.1持平，功能与test5零差异（仅version.py+打包脚本变化）**。
- 冻结实测：中文路径6张库 exe启动识别 7条记录/0失败/6种 ✓。
- **二次瘦身审计（test6之后）**：799MB构成=模型224（不动）+WebEngineCore 194（地图Chromium内核,动不了）+onnxruntime 64+图鉴数据109（geo_prior 74+details 15+culture 14,内容核心）+Qt基础库~50+libx265 22（HEIC硬依赖）+python/numpy/PIL ~46+其他。可安全再砍的只有零引用模块：**Qt6Pdf.dll 4.4MB + opengl32sw.dll 19.7MB（Mesa软GL回退,仅无硬件GL机器才加载）+ QtPositioning/QtQuickWidgets pyd**≈25MB，已加入prune_dist（含"地图黑屏则恢复opengl32sw"的注释），**0.5.3构建时生效并需冻结实测地图页**。地板≈774MB，再往下只能砍功能（地图/HEIC/图鉴数据），不建议。
- **GPU现状结论（答复用户）**：本机(AMD RX 640+UHD750) DML初始化214MB分类模型必失败（E_INVALIDARG，环境性，_dml/_sim两版实验模型都不能解决→与模型结构无关），自动回退CPU，单张0.3~0.7s够用。**5080从未真正测过GPU**——之前所有版本在5080上全部毁于中文路径编码bug（秒失败没跑到推理）；test5/test6是首批能在5080真正识别的版本，待用户实测速度：明显快于本机=DML生效；与本机相当=也在回退CPU（则需针对性查NVIDIA DML）。
- 用户确认test6后 → 出 **v0.5.3** 正式版（内容=test5修复+瘦身+二次prune, 构建后冻结全链路+地图页验证）。

## 2026-10-24 · v0.5.2-test5：中文路径不识别（test4用户实测抓到的核心bug）

用户在打包版test4实测：G盘成片47张（全中文文件名）导入后全部不识别（rec_fail=2/张），清空重导一样。**确诊：冻结exe识别子进程的stdio编码=系统GBK**——worker.py源码态spawn带`-X utf8`，冻结分支无法传该参数，父进程UTF-8发的中文路径被子进程按GBK解坏（实测错误消息里出现孤立代理`\udcad`），症状与"换电脑文件丢失"完全相同。此前冻结测试一直用英文文件名（Alcedo_atthis.jpg）所以从未暴露；test3时代用户5080机器"ok=0/47全No such file"很可能同根因（当时归因于文件在另一台电脑）。

- **修复**：`recognize_sub.run_worker()`入口`_force_utf8_stdio()`把stdin/stdout重绑为UTF-8（io.TextIOWrapper, errors=surrogateescape），不依赖启动参数/环境变量，源码冻结两态通吃。
- **验证**（全部通过）：①不带-X utf8的源码worker+中文路径→红尾歌鸲98.7%✓；②冻结worker探针单进程三路径（本地中文/本地ASCII/G盘中文）全OK✓；③**冻结GUI完整用户流**：47张G盘成片→exe启动自动识别47/47、0失败、2种（红尾歌鸲8+白颊噪鹛39）→时间线同款入口清空全归零→重导入从#1→再启动再识别47/47结果一致✓。
- **教训（测试方法论）**：冻结验证的测试图**必须含中文文件名/中文目录**，纯ASCII文件名的测试会漏掉整类编码bug；shell里若设了PYTHONUTF8=1会给子进程兜底掩盖问题，验证编码时必须清掉。

## 2026-10-24 · v0.5.2-test4：去打点 + 查看器自适应 + 计数口径定稿（含importer绝对路径防御）

用户报告：时间线有照片但鸟种库空、查看器打开"尚未识别"、图片四周大片空白。排查结论：**数据管线本身没问题**（testlib/relink_verify 均有完整记录；坏库 frozen_lib/reg_lib 是测试脚本中途被杀留下的残库，非产品bug），用户看到的"尚未识别"即照片还没识别完/或残库数据。本轮交付：

1. **GPU打点监测全部移除**（用户："去除Gpu打点监测，让软件先能用起来"）：worker.py 批次/每张打点、recognize_sub.py stderr打点、main.py 的 diagnostics.log 重定向与轮换——三处全删。exe旁不再生成日志文件。
2. **查看器图片自适应修复**（根因）：`ZoomableView._fit_if_ready` 原来只在 `_need_fit` 时执行，首次fit发生在对话框还不可见/视口还是占位尺寸时 → 图片按错误尺寸渲染，打开后四周一圈空白。现在：set_image 后等 `isVisible()` 且视口>10px 才fit；未手动缩放时 **resizeEvent 始终跟随适配**（拉伸/最大化/还原都贴合）；滚轮/±手动缩放后不再抢视角；双击复位。程序化验证：首次打开/900x700/1500x950 三种尺寸短边覆盖率均>0.95，手动2x后resize视角不变 ✓
3. **查看器加最小化/最大化按钮**：`Qt.WindowMinMaxButtonsHint`（原来只有关闭）。
4. **计数口径定稿并写进 db.py docstring**（用户："照片计数和人生第几种鸟的计数逻辑你一定设计清楚"）：
   - photo_count：photos 表现存行数，全库唯一口径（时间线/状态栏/成就/全选都调它）；移除立即减、重导入立即加；引用模式文件丢失仍计数（missing_files 另行提示）
   - lifer编号：按「当前在库照片的最早拍摄时间」(EXIF优先, 无EXIF退导入时间)升序排 1..N，**完全由现存数据推导无隐藏状态**——移除某鸟种全部照片→该种退出、编号自动前移无空洞；同EXIF重导入→编号不变；全清空→归零重来（配合v0.5.2-test3的sqlite_sequence重置）
5. **新增回归工具**（一次性投入，长期防退化）：
   - `tools/verify_count_logic.py`：ref导入→识别→移除→重导入→全清空 全链路计数断言（含"无EXIF图按导入时间排位、一照多鸟按种各计"的口径边界）
   - `tools/verify_viewer.py`：查看器视口填充率/窗口按钮/手动缩放断言（程序化，不靠目测）
   - `tools/verify_usb_scenario.py`：**用户场景实测**——U盘成片47张 空库ref导入→真实RecognizeWorker(子进程协议)识别→鸟种库核查→时间线清空→重导入→重识别，两轮结果逐项比对
6. **U盘场景实测结果（全部PASS）**：47/47识别成功、鸟种库2种（红尾歌鸲/白颊噪鹛）n值与底层直查一致、lifer编号连续无空洞、清空后photo_count/鸟种库/lifer/batches/id全归零、重导入从#1开始、两轮识别鸟种集合与lifer顺序完全一致。UI截图（timeline/species/viewer两种尺寸）用户本人目测正常。

- 用户实测确认（5.3模型会话）：截图目测正常。
- ~~v0.5.2-test4 已打包~~ → 被用户实测推翻（中文路径不识别，见test5节）；test4目录保留但勿再用。
- 打包时抓到自己一个测试方法论坑：**给测试库喂数据必须用绝对路径**——相对路径存的库会让识别子进程在exe目录下找不到文件、ok=0全失败（症状与"换电脑文件丢失"相同）；importer已在入口统一resolve()防御（UI的QFileDialog天然绝对路径，真实用户不受影响）。
- 用户确认无问题后，同内容打包升 **v0.5.3** 正式版（版本规则：迭代期打0.5.2-test*，确认后才升号）。

## 2026-10-26 · v0.5.2-test3：清空归零 + 崩溃修复（用户需求）

1. **移除清空后编号归零**（用户明确需求："每次移除清空时编号也归零"）：`remove_photo` 里当 photos 表清空时——DELETE batches + 重置 sqlite_sequence(photos/records/exif/batches)。重导从#1开始。鸟点/鸟种表保留。
2. **timeline空状态QLabel崩溃修复**（用户5080日志抓到）：`self.empty` 持久QLabel被refresh的deleteLater删除后再次复用 → libshiboken RuntimeError。改为每次refresh新建。该bug在"清空→导入→清空"循环下必崩。
- 验证：导入#1-3→移除清空(batches=0)→空状态三次refresh不崩→重导ids=[1,2,3] PASS；e2e✓；冻结启动✓。
- 测试脚本注意：move模式后源文件已移走，第二轮导入要从新位置取源，否则"导入0张"是测试问题非产品问题。

## 2026-10-26 · v0.5.2-test2：换电脑场景修复（用户日志确诊）

用户5080机器测试后回收 diagnostics.log，**确诊**：
- 库里已有2000+照片记录（id至2151，引用模式导入自那台电脑的 D:\照片\...）
- 47张成片的3次识别批次全部 ok=0/47，每次2-5秒结束——**全部 No such file**（原文件路径在另一台电脑上不存在）
- 附带抓到：libshiboken QLabel already deleted（timeline._toggle_select→refresh 里每日一鸟横幅的QLabel僵尸引用，识别完成后library_changed时序触发）——待修
- 修复：①worker统计失败原因分布（[DIAG] 失败原因分布+No such file示例）+ finished_all 增加 missing_files 字段；②大量文件丢失(≥半数且≥3张)时弹说明框（原因+三种处理办法）；③时间线缩略图缺失且原文件不存在 → 「文件丢失」角标；④使用说明写明清空重测的正确姿势（删整个BirdTraceWin目录）
- 冻结验证：启动✓ 日志在exe旁✓ move+识别6/6✓ missing_files字段=0✓

## 2026-10-26 · v0.5.2-test 诊断版（用户5080机器排查用）

用户5080显卡却"几秒一张"+鸟种库0。本版为诊断包：
- **日志移到exe旁** `diagnostics.log`（用户要求方便找），2MB自动轮换保留3份
- **识别全程打点**：批次开始(ort版本/可用providers/显卡列表)、每张(耗时/鸟种码/置信度)、批次结束(ok/总耗时)；worker子进程侧stderr打点(模型加载耗时/provider/纯识别耗时)——worker的stderr写入diagnostics.log(主进程stderr已重定向)
- **成片实测(G盘47张DxO图, 全新库)**：预览→导入→识别 全链路通过，鸟种库2种(红尾歌鸲8+白颊噪鹛39)、置信度全部~100%、待复核0。鸟种库截图视觉确认（旧截图里空提示与卡片并存是一帧残留，复拍已消失）
- CPU吞吐提升：识别子进程化后CPU线程上限从核数/2提到核数-2（无需给UI留核）——本机实测单张分类283ms(14线程, 原~2s的1/7)
- DML深挖结论：检测模型(10MB)DML初始化成功，分类模型(214MB)失败= MLOperatorAuthorImpl.cpp(2853) E_INVALIDARG，与CastLike/simplify/locale均无关（CastLike替换后仍失败），是**该模型+AMD/驱动组合的环境性问题**；用户5080需test版日志确认是否同样失败
- **打点键名坑**：records键是species_code不是code——DIAG曾显示"无鸟100%"误导排查（已修）
- 用户要求后撤销：「开始导入」按钮保持底部位置（预览完成才可用，逻辑合理）
- 冻结验证：启动✓ 日志在exe旁✓ 识别6/6✓ 鸟种6✓

## 2026-10-26 · v0.5.1 发布：新库首导场景修复（用户连报三问题）

用户（每次清空当全新软件测试）报三问题，全部源于**回归没覆盖"全新库首导"场景**：
1. **"识别完成但鸟种库0/成就鸟种0"**——复合根因：①挂点对话框模态阻塞在 start_recognition 之前，对话框开着识别就不启动；② BatchSpotDialog 关闭路径的时序。修复：**start_recognition 提前到对话框之前**（识别与挂点互不影响）+ `start_recognition` 内加 `species_filled()` 防御填充。
2. **移动模式没有目标文件夹**——v0.4.5加三段控件时 `_mode_changed` 仍写 `idx==1`（移动=2漏掉）。修复：`idx>=1` 显示 + 未选目标拦截提示。
3. **拍摄地区置顶**（用户：对识别最重要）——导入页地区卡移到最顶。
- 复现链路价值：本轮先在源码态完整复现"新库首导鸟种0"（fill_species缺失变体），修复后复跑 PASS（鸟种库6种/成就6）。
- **回归方法论补课**：全量回归必须包含"全新库首导"场景（用户真实用法=每次清空重测）；`SegmentedControl.setCurrent` 不触发changed信号（程序化切换≠用户点击），UI测试必须走 _on_click。
- 冻结终验：启动/0错/move导入6张/子进程识别6of6/鸟种6种 全PASS。

## 2026-10-26 · v0.5.0 稳定版发布（全量回归通过）

用户对连续小版本不满，按新规矩做了一轮**全量回归**再出大版本：

### 回归范围与结果
| 项 | 结果 |
|---|---|
| 识别冒烟（6图全链路） | ✓ |
| e2e（导入→识别→lifer→复核） | ✓ |
| DAO全家桶（鸟点/批量/改种/手工/主鸟/eBird/报告/成就/移除/备份） | ✓ |
| 双主题全页切换（light/dark×8页含懒加载map） | ✓ |
| UI截图套件（11页，0样式告警） | ✓ |
| 多选五场景（计数/重识别/移除/切页重置/回队列） | ✓ |
| 导入三模式+状态条摘要 | ✓ |
| 地图免Key引擎（JS加载+marker） | ✓（发现真bug，见下） |
| 查看器/分享卡 | ✓ |
| 冻结版（启动/备份/move导入/子进程识别） | ✓ |

### 回归抓到的真bug（已修）
**库目录相对路径**：`Library(Path('data/reg_lib'))` 相对路径 → `QUrl.fromLocalFile` 生成无盘符URL → 地图页加载空白页。修复：`Library.__init__` 强制 `root.resolve()`。触发条件：`--library` 传相对路径（默认库是绝对路径所以用户没撞过，但属真实隐患）。排查中另有3个测试脚本自身bug（`amap.web.page`漏括号、批量挂载断言错、viewer用未重跑识别的库）——产品零缺陷，测试需修。

### 版本策略（响应用户）
- 严重bug（起不来/丢数据/死循环）→ 立即修立即发
- 一般问题 → 攒批，用户确认后打包，一天最多一个版本
- 打包前先问上一轮测试结果（已固化为规则）
- 本轮回归后出 v0.5.0 作为稳定版，用户可安心长期使用

## 2026-10-26 · v0.4.6 发布：选择状态重置 + 识别状态透明化

（体验修复三件+状态条持久化，用户报"识别完成还是0"后追加）
- **"识别完成 0"排查**：复现确认导入入库/WAL可见性/识别启动都正常（30/30成功）；
  真正问题=识别完成的状态条文本几秒内被 `_update_status` 的"库内N张照片"覆盖，
  用户后来看状态条只见"库内30张"没有识别结果——误以为识别了0张。
  修复：`_update_status` 优先显示60s内的识别摘要（"识别完成 X/Y + 待复核N张"）。
  （另确认用户可能把"待复核 ● 0"误读为识别0张——现在摘要直接写明"全部高置信度，无需复核"）
- 其余同上一节（选择模式重置/识别中跳过重型refresh/鸟种库识别提示）。
- 验证：A/B测试PASS + 状态条持久化直测PASS（识别完成30/30保持不被覆盖）+ e2e✓ + 冻结版启动/识别PASS。

## 2026-10-26 · 体验修复（未打包，攒着等用户反馈）

1. **时间线选择状态跨切页残留**（用户报：默认应浏览态）：`switch_to`离开timeline时自动退出多选模式。
2. **导入挂点后切页卡**（用户报）：根因=_import_done里BatchSpotDialog模态阻塞期间library_changed未发，挂完点关对话框才发→6页refresh+识别worker启动同时进行。修复：①library_changed提前到弹窗前；②_refresh_pages分级跳过——识别worker运行中也跳过timeline/review（识别写records表）。
3. **"时间线有照片但鸟种库里没有"**（用户困惑）：设计如此——导入=登记(时间线立即可见)，识别=独立第二步后台跑，鸟种库只统计已识别的。已加提示：识别进行中鸟种库顶部显示"后台识别进行中…稍后再回来看"。
- 验证：A选择模式重置PASS；B识别中切页心跳65ms+鸟种库提示PASS；e2e✓。

## 2026-10-26 · v0.4.5 严重bug修复：双击exe无限开窗（用户两台电脑复现）

- **根因**：v0.4.2引入的识别子进程用 `[sys.executable, "-m", "app.ai.recognize_sub"]`——**冻结态 sys.executable = 鸟迹exe本身**，`-m` 对exe无效→被当作正常启动再开一个完整GUI→它也自动恢复识别→再spawn……指数级开窗。源码态（sys.executable=python.exe）一切正常，所以我的测试全绿、用户两台机器全炸。
- **修复**：冻结态识别worker**复用主exe本体**——`--recognize-worker`参数走main.py分发到`run_worker()`（无GUI、stdout是JSON协议通道**绝不重定向日志**、conf经`--conf`透传）；源码态维持`-m`。
- 决定性验证：冻结库预导6张→启动exe→自动恢复识别→**窗口峰值1**、records=7、0 Traceback（旧版此场景必无限开窗）。
- **教训（重大）**：冻结态下 `sys.executable` 是你的exe而不是python解释器——**任何"spawn自己再跑个模块"的方案在打包后都会变成"再开一个自己"**；凡Popen引用sys.executable必须先判 `sys.frozen` 并让exe支持无GUI子命令模式。我的测试盲区：全部用源码态验证，冻结态只测了启动没测识别——**冻结验证必须覆盖"会用子进程的路径"**。

## 2026-10-26 · v0.4.4 紧急修复：导入预览卡死 + 导入中无响应/多窗口死循环（用户报严重bug）

用户v0.4.3实测两大严重问题：①选文件夹后卡很久才能点开始导入；②导入中点其他页出现无响应+不断开新birdtrace窗口死循环，最后只能关机。
- **bug1根因**：`_populate_grid` 在主线程同步做每张file_hash(读512KB)+查库+整图解码生成缩略图——大文件夹=主线程冻结几十秒。修复：**预览后台化**（新`PreviewThread`：批量hash→一次查库→缩略图，每张`item_ready`信号回填网格占位；主线程只铺空位86ms完成）。
- **bug2根因（链路还原）**：导入线程持SQLite写事务时用户切页→`library_changed`→6页同时refresh查库撞锁，主线程卡死弹"无响应"；用户关窗/等待后**识别完成弹的QMessageBox模态框在消息堆积下层层出现**（`finished_all`信号+各处refresh触发重入），表现为"不断开新窗口死循环"。修复：①导入线程运行中`_refresh_pages`跳过重型页（timeline/species/stats/review）；②**识别完成不弹模态框**，改状态条提示（信息不丢：待复核徽章+状态条都有）。
- 实测（180张）：选文件夹同步耗时86ms、预览后台跑时切5页无卡死、导入中切4页+识别中切4页全程心跳最大369ms、可见主窗口恒为1、识别178/178成功（91秒）records=208；e2e✓；冻结版启动+move导入+识别PASS。
- **教训**：①"识别完成弹窗提醒"这种看似贴心的模态框，在批量场景+消息堆积下会变成死循环——模态框只适合用户主动触发的单次操作确认；②导入/识别等后台任务运行期间，主线程的任何"顺手刷新"都要掂量SQLite锁与重负载页（时间线178张缩略图）的成本。

## 2026-10-26 · v0.4.3 发布：多选修复 + 识别不卡UI + 移动导入（用户确认后出包）

- 按用户流程规则：修完多选/识别卡顿/移动导入三件后**先问测试结果**，用户确认"打包吧"才出包。
- **打包抓到启动级bug**：上一轮轻量化清空spec datas时删掉的 `_internal/assets` 其实是**活依赖**——`db.py` 自定义 `PROJ=__file__$.parent.parent` 在冻结态解析到 `_internal`，找不到exe旁的assets（此前没炸纯因旧包残留死副本）。修复：db.py 改用 `paths.assets_dir()`（冻结态解析exe旁）。教训：**删"死重"前必须grep全部引用含跨模块常量；重打包后必须冻结版实测启动**（本轮如果不是按流程先验证就发出去，用户会拿到一个起不来的包）。
  - **隐患全面清除（用户要求"先帮我消除掉"）**：grep全app只剩 `__file__` 推导三处——db.py(已修) + worker.py的cwd + recognize_sub.py的sys.path注入，后两处冻结态同样解析_internal。统一改走 `paths.proj_root()`/`assets_dir()`，app内现仅paths.py一处路径推导（冻结分支正确）。重打+冻结全链路复验：启动/0错误/备份/move导入6张源清零/子进程识别6of6（9秒）全PASS。
- 冻结验证：启动PASS（默认关于页/0错误/备份✓）；move导入6张源清零+子进程识别6/6（11秒）PASS；使用说明重写（bash heredoc的\B转义坑→改用python r-string）。
- 版本号0.4.3在打包前bump（流程正确）。

## 2026-10-26 · 识别不卡UI（子进程化）+ 移动导入模式（未打包，与多选修复一起等反馈）

用户报：照片多了识别时点软件弹"无响应"（实际在识别）。
- **根因确诊**：onnxruntime-directml 在**中文环境下 DML(GPU) 初始化必失败**（EP Error: 'utf-8' codec can't decode byte 0xb2，DML内部用系统locale编码日志），**静默回退CPU**；回退后ORT默认 intra_op=16 线程吃满全部核，识别线程的Python层前处理密集抢GIL，UI线程被饿死——Windows 5秒收不到消息就弹"无响应"。
- **修复（三道保险）**：
  1. **识别搬独立子进程**（`app/ai/recognize_sub.py`，stdin/stdout行协议：`pid	path	region	month` → JSON行）——GIL完全隔离，识别再重UI也不卡；worker.py 重写为子进程管理器（启动一次复用、崩溃自动重启下一张、**stdout只认`{`开头的JSON行**——onnxruntime的EP告警横幅会打到stdout）。
  2. `make_session` 无论是否请求GPU都限 `intra_op=核数/2` 留核给系统。
  3. 识别完成**弹窗提醒**（成功/共几张+待复核提示）；侧栏状态芯片实时进度"识别中… N/M 可正常使用其他功能"。
- **实测**：UI心跳最大延迟 1681ms→**98ms**（PASS），识别6/6成功11秒；e2e✓。
- **导入新增「移动到新位置」模式**（用户需求，LR式）：importer mode=move（shutil.move到 拍摄年月/ 归档目录，源文件不保留）；导入页三段选择（引用/复制/移动）+提示文案。move端到端实测：6张源→0剩余→dest 6张→库内路径指向dest ✓。
- **踩坑**：①改Python文件的heredoc脚本里 `
` 会被bash先解释成真换行写进文件（f-string断行语法错）——改用Edit工具或先写临时.py再执行；②assert断言式的"全有或全无"批量替换：part2失败时part1也不会写入（文件在内存里改的），要分开写或用Edit；③测试库被多轮bump_rec_fail污染后pending=0，测识别前要确认pending>0。

## 2026-10-26 · 多选点击bug修复（未打包，等用户反馈一起出）

用户v0.4.1实测：多选模式点缩略图弹查看器而不是选中。排查（复现脚本tools/repro_multiselect.py已删,可按PROGRESS重建）发现三层问题：
1. **lambda签名错**：`mousePressEvent = lambda e, pid=..., it=item: _on_item_click(pid, it)` ——Qt调用时shiboken把item对象作为第2个位置参数塞进来, `_on_item_click`收3参 TypeError **被Qt静默吞掉**，点击零反应（这是"点了没反应"的直接原因）。
2. **refresh重建竞态**：选中后refresh重建网格，快速连点第二次落在已deleteLater的僵尸控件上（RuntimeError: Internal C++ object already deleted）。
3. 修复：①lambda改为显式def _click(_e,_pid,_it)闭包+try/except RuntimeError防僵尸；②选中翻转**就地set_selected不重建网格**（只有全选/进出选择模式才refresh）；③`_on_item_click(pid, item=None)`。
验证：repro脚本 PASS（点击选中{2}→0查看器→二次点击取消）。**教训：Qt槽/事件lambda签名错会静默失败，必须用模拟事件真点一次**。

## 2026-10-26 · v0.4.2：eBird 导出 + 年度报告（B6 生态完成）

- **eBird CSV 导出**：`ebird_export_rows()` 按(鸟种,鸟点,日期)聚合——Common/Sci Name用物种表英文名/学名、Count=照片数、Location=鸟点名(无鸟点回落地区名)、Protocol=Incidental、Observers=1；UTF-8-BOM（utf-8-sig，Excel直开不乱码）。入口=成就页右上「导出eBird记录」。
- **年度报告**：`yearly_report(year)`（年度新种=生涯首见在该年、年鸟回归、照片数、拍摄天数、月度柱状、九宫格=年度新种首见照前9）；`YearlyReportDialog`（年份下拉+汇总卡+月度柱状+九宫格）+「导出报告长图」QPainter渲染1600px宽海报（年份大字/汇总行/九宫格圆角裁剪/月度柱/页脚署名）。入口=成就页右上「年度报告…」。
- **踩坑**：长图y0原来按固定3行九宫格算——demo库1行时中部大片空白+柱状图溢出压页脚（视觉验收抓住）；改画布高度随grid_rows动态。**打包顺序坑：版本号bump必须在make_release之前**（本轮bump晚了导致包内关于页显示旧版本，重打一次）。
- 验证：eBird行数据+CSV样例✓；报告数据（2025:新种2/月度正确）✓；对话框+长图渲染✓；视觉验收（对话框PASS/长图修后PASS）✓；e2e✓；冻结版成就页PASS✓。
- **B6 生态至此全部完成**（eBird导出/年度报告/自动备份）。PLAN主线收官，剩余=按用户反馈迭代+远期想法积压（§8.5）。

## 2026-10-26 · v0.4.1：主题即时生效 + 拼音对齐 + 导航重排 + 首页=关于 + 窗口可缩

- **主题即时生效（用户要求不重启）**：架构改造——全部UI文件的`from ..theme import X`改为`from .. import theme`+引用`theme.X`（运行时查模块属性，~11文件批量脚本改+1处误伤修复：spot_dialog的`SEP="__sep__"`旧常量被误改成theme.SEP赋值会污染主题模块，已改回）；设置页切主题→`apply_theme`+**整窗重建**（停旧worker→new MainWindow→show→switch settings→旧窗deleteLater），实测深色秒切✓。
- **分享卡拼音逐字对齐（用户报：拼音与汉字位置不对应）**：`pinyin_spaced`改返回逐字音节列表；render_card拼音/中文两行改为**每字竖排单元**（音节画在对应汉字正上方，单元宽=max(两宽)，长名自动缩字号3轮迭代），4字/9字名验收PASS（不与Life胶囊重叠）。
- **导航重排（用户定序）**：设置→导入→时间线→鸟种库→鸟点地图→待复核→成就→关于；**关于=首页**（构造后switch_to("about")），侧栏logo可点回首页（tooltip"回到首页"）。
- **窗口高度可缩（用户报：只能调宽度）**：根因=导入页/设置页固定高卡片堆叠撑大整窗最小高度——两页整页套QScrollArea（嵌套滚动OK）+MainWindow显式`setMinimumSize(860,540)`；实测900x560全页切换正常✓。
- 验证：e2e✓；全页截图0 stylesheet告警✓；4项视觉验收PASS（拼音对齐x2/主题即时/成就页回归）；冻结版PASS（默认页=关于,logo区0.96白,0错误）✓。

## 2026-10-26 · v0.4.0（上线版）：统计页→个人成就 + 关于页

- **个人成就（参考birdtrace安卓指标体系，dex逆向所得）**：安卓版成就指标=`distinctCanonicalSpecies/distinctLocations/distinctRaptors/distinctWaterbirds/streak.days.3/7/30`+achievement_unlocks表。我们实现（纯本地计算，无unlock表）：`Library.achievements_summary()`——里程碑解锁日=第N种首见日期/第N张照片日期/第N个鸟点created_at（可精确回溯）；streak按记录distinct日期算当前连续+最长连续；猛禽=鹰/隼/鸮形目、水鸟=鸻/雁/鹈/鹤/鸊鷉/鲣鸟目（order_cn匹配）。
  - stats_page.py 重构：6数字卡（+拍摄天数/鸟点数）+ 6组徽章（生涯鸟种7枚/照片4/鸟点4/连续3/猛禽3/水鸟3，共24枚）——解锁=橙描边+日期，未解锁=灰+进度条；保留BarChart年度增长图。导航"统计"→"成就"。
- **关于页 about_page.py**：用户提供了完整自白文案（Windows鸟图收容所/师兄生态/无偿/识别率梗/同济校友征集微信tubage989525）——按用户要求**精简排版**保留神韵（这是什么/使用须知/开发者/致谢开源）；开发者读photographer_name。RichText里\n不换行→_body统一转<br>。
- **分享卡罕见度徽章（用户需求，参考birdtrace/慧眼观鸟）**：`share_dialog._card_info`经`prior_hint.rarity_tier(code, photo批次region)`取5档；render_card日期行右侧画胶囊——稀有/罕见=红橙醒目、不常见=橙、常见系=灰（保持卡片干净）。
- 验证：成就数据层✓；关于页/分享卡截图验收双PASS✓；e2e✓；冻结版PASS（关于页17112色/0错）✓。
- **refresh踩坑**：清空布局时`it.widget()`连续调用中间会变None——缓存局部变量；图表等动态控件refresh里重建而非复用引用。
- **打包踩坑**：rm -rf整个release目录再cp会把使用说明.txt一起删掉——重打包后必须重写使用说明（本轮踩中一次）。

## 2026-10-26 · v0.3.4：免Key地图（默认引擎）+ 设置页省份修复 + 时间线批量操作

- **免Key引擎（用户追问"没有免Key的吗"后补做）**：高德**栅格瓦片本身免Key**（webst01-04/appmaptile，B4实测23ms），喂给开源MapLibre引擎（raster source inline style JSON）——引擎开源+底图零Key+中文标注+国内最快。坐标GCJ-02，纠偏经 `_is_gcj` 属性统一（amap/maplibre_free都转换）。三引擎枚举：maplibre_free(默认)/maptiler/amap，旧值maplibre兼容映射maptiler。设置页三选项「免Key高德底图/全球矢量/高德官方」。
- **设置页省份修复（用户报bug：只有国家没有省）**：设置页"默认拍摄地区"改两级级联（国家+省份，同导入页），省级选择优先存储（default_region存CN-BJ式）。
- **时间线批量操作（用户需求）**：「选择」按钮进多选模式（PhotoGridItem蓝色选中框B1就有，现在启用）→工具条（已选N/全选/重新识别…/从鸟迹移除…/完成）。`Library.reset_recognition(ids)` 清records+rec_fail复位→start_recognition重跑；批量移除=循环remove_photo。确认框都注明后果（重识别覆盖人工确认；移除不动原文件）。
- **连拍折叠：用户拍板不做**（从候选清单去除）。
- 验证：三引擎探针（free:15512色/2marker/fit北京✓；maptiler:10902✓；amap:4438✓）+free引擎视觉验收PASS（pin贴道路=纠偏正确）；功能测试（省份级联存取CN-BJ/CN-SH、多选移除6→4、重识别记录清零回队列）✓；截图验收（设置页两级地区/时间线多选）双PASS；e2e✓；**冻结版PASS（15834色/0错误/备份✓）**。
- **冻结验证踩坑**：taskkill强杀后FindWindowW会匹配到**僵尸窗口**（IsWindow仍True但rect=0,0,0,0）——必须循环等rect有效的真窗口。

## 2026-10-26 · v0.3.3：免高德依赖的地图双引擎（默认MapLibre）

- **侦察结论（用户点名参考birdtrace安卓版）**：解包 birdtrace.apk → libmaplibre.so，安卓版地图 = **MapLibre（开源引擎）+ MapTiler 矢量底图**（dex 里抠出作者内置Key `QMZGF8IiSPfyUQeVTOEQ`，MapTilerConfiguration 类名佐证）。MapTiler 国内直连实测可达（style.json 0.8s，矢量瓦片1-2s/块）。
- **实现（`amap_view.py` 双引擎）**：
  - 新增 `_HTML_MAPLIBRE` 模板：本地打包 maplibre-gl.js/css（assets/map/，共1MB）+ MapTiler streets-v2 style（`?language=zh`），**WGS84坐标直传无GCJ纠偏**；HTML marker + 屏幕距离56px聚合（moveend重算）；桥接口与高德版完全同构（mapReady/mapMoved/picked/markerClicked + apiSetSpots/apiFit/apiFocus/apiSetPick）→ Python侧MapPage零改动。
  - `_effective_conf()` 返回 (engine, key, secret)；`load_map()` 按引擎选模板；纠偏收口到 `_to_map()/_from_map()`（仅amap引擎转换）。
  - 设置页地图卡加「地图引擎」（开源地图/高德官方，默认开源）+ MapTiler Key 输入（内置缺省=安卓同款团队Key）。settings键：map_engine/maptiler_key。
- **踩坑**：①file://页面加载本地js需显式 `LocalContentCanAccessFileUrls=True`（Qt6部分默认关）；②MapLibre 'load' 事件等全部初始瓦片（MapTiler国内慢，16s都没到）——和高德'complete'同款教训，**创建即上报mapReady**，styledata再补layoutMarkers；③shell cwd漂移导致素材下错目录（已核对迁移）。
- 验证：双引擎源码探针（maplibre: fit北京/2marker/11093色；amap: 4463色）✓；e2e✓；冻结版双引擎实拍 PASS（11093/4479色，日志零Traceback）✓；体积799MB（仅+1MB）。
- 剩余：视觉子代理验收进行中（engine_maplibre/engine_amap截图）。

## 2026-10-26 · v0.3.2：内置全部高德Key + 轻量化（970→798MB）

- **Key补全（用户报：新电脑搜索不可用）**：`DEFAULT_WEB_KEY`（Web服务，POI搜索）加入 amap_view.py，`PoiSearcher._do_search` 未配置时用内置——全新库开箱即可搜地名（实测新库搜"奥林匹克"8结果✓）。至此两类Key（JS API渲染+Web服务搜索）均有内置缺省+设置页可换。
- **轻量化（用户原则：一定要轻量；模型不动）**：
  - babel 31MB → 预生成 `assets/data/country_zh.json`（294国名，6KB），regions.py 改读本地表，spec 去 babel hiddenimports
  - make_release 加 `prune_dist()`：WebEngine devtools资源87MB+debug snapshot、Qt翻译只留中英~50MB、spec datas 重复资产5.8MB（_internal/assets 死重，assets_dir本就指向exe旁）
  - **踩坑：libx265不能删**——pillow-heif Windows二进制硬链接它，删了`_pillow_heif.pyd`整体加载失败（ImportError DLL load failed，冻结版起不来）；解码链=libheif+libde265，x265虽是编码器但是硬依赖
  - 模型 FP32 214MB 保持原样（用户拍板不瘦身）
- 验证：e2e✓（regions改造后中国/美国/巴西显示正常）、新库内置Key搜索✓、冻结版地图渲染+备份+日志无错✓、体积798MB
- 用户定调：与SuperPicky/SuperBirdTools是**一个团队**（详见STUDY_NOTES.md），代码借鉴无许可顾虑；XMP回写不做。

## 2026-10-26 · v0.3.1：用户异地实测反馈5连修（模型GLM-5.3）

用户在另一台电脑试用 v0.3.0 便携版后反馈5个问题，全部修复：

1. **地区下拉白底白字**：根因=QSS弹层只写background没写color，文字色继承系统调色板——用户那台电脑开了Windows深色模式，文字变白。修复：theme显式设置QPalette（Window/Base/Text等全套角色）+ QSS弹层 `color:{LABEL}`。
2. **非鸟动物干扰（牛）**：标定实验发现两条路径——牛图根本不触发检测器（0框），干扰全部来自"无检测框时的整图兜底"：整图牛会被硬分成某鸟种（全局概率0.51，与难认真鸟戴胜0.52不可区分）。修复：**砍掉整图兜底**——无检测框返回[]，worker 走 `mark_no_bird`（rec_fail=3，不再重试，照片保留可手工标注）；检测框路径加全局概率(万类softmax)拒识线 REJECT_GPROB=0.05（实测真鸟≥0.5，安全边际大）。
3. **多鸟选主鸟**：查看器每条识别记录显示 rank=1 的「主鸟」蓝徽章，其余可「设为主鸟」（`set_main_record` 重排 rank）。鸟点照片流的"代表种"取 rank=1 自动跟随。
4. **改鸟种无列表**：species_pick 重写——默认展示全库11171种（in_classifier优先,按拼音排序），打开0.77s、过滤毫秒级；搜索维度：中文/拼音全拼/**拼音首字母(ysq)**/学名/英文；>300结果截断提示。载入即预拼匹配key，过滤不查库。
5. **主题选择**：theme.py 重构——LIGHT/DARK双调色板+`apply_theme(app, mode)`(system用QGuiApplication.styleHints().colorScheme())；设置页「外观」卡（跟随系统/浅色/深色，重启生效）；main.py 先建库读设置再apply_theme（顺序关键）。
   - **踩坑**：`theme/__init__.py` 的 `from .theme import X` 是值拷贝，apply_theme改子模块全局不跟随——改PEP 562 `__getattr__` 动态代理。全UI文件42处内联写死颜色已批量替换为主题常量（QFrame花括号在f-string里要双写`{{`）。

远期想法已记 PLAN §8.5：logo点按回首页、地图免Key通用方案（先问安卓作者）、关于页。

### 验证

- 视觉验收：12页面×明暗双主题全过（map_dark首拍被无关窗口遮挡，重拍过）；下拉框展开态明暗双验证过（报障画面确认修复）；species_pick默认列表+ysq过滤过
- 功能：牛图识别0条✓ mark_no_bird不进pending✓ 设为主鸟rank交换✓ 选择器11171条性能✓
- 回归：smoke✓ e2e✓；**v0.3.1发布版冻结验证：明暗两主题地图渲染+侧栏亮度(227/48)+备份落盘 全PASS**
- 截图采集加固：screen_grab抓前强制raise+activate（避免被其他窗口遮挡）

## 2026-10-23 · v0.3.0 发布：便携版打包 + 自动备份

- **版本号单一来源** `app/version.py` VERSION="0.3.0"（设置页关于/UA引用）。
- **自动备份**（B6.3提前完成）：`Library.maybe_backup()`——启动时检查，距上次>24h即用SQLite backup API备catalog.db到 `<库>/backups/catalog-YYYYMMDD-HHMM.db`，保留最近7份；设置页显示状态+「立即备份」；main.py启动调用。
  - **踩坑**：WAL模式下主库mtime不随写入更新（写入在-wal），"按mtime跳过无变化"判定失效——放弃变化检测，固定24h节流（库文件小，成本可忽略）。
- **便携版发布**：`releases/鸟迹BirdTrace-v0.3.0-便携版/`（完整程序+使用说明.txt）。便携式定位：数据全在文档\BirdTraceWin，升级=换文件夹。
  - **踩坑**：frozen_map_check旧进程没杀干净（/PID不带/T，Chromium子进程存活）占用dist导致PyInstaller清理失败（PermissionError）——已改 /F /T 杀进程树。
- 验证：备份测试（首次/节流/超期/强制/可读/轮换7份）全过✓；发布版冻结验证：地图渲染PASS+首启自动备份落盘✓。

## 下一周（用户定）

B6 剩余：eBird CSV导出、年度报告；B5 性能优化（库变大后再说）。可选：照片按鸟种着色marker层、深色模式。

## 2026-10-23 · B4.3 挂点搜索体验修复（用户反馈：搜索一点就跳地图）

- **Bug根因**：QDialog里QPushButton默认autoDefault——搜索框按回车触发了布局里第一个按钮「在地图上选点新建…」。所有挂点对话框按钮已显式 `setAutoDefault(False)`；回车=应用当前选中项（SpotSearchList.returnPressed→trigger_current）。
- **二合一搜索**（用户定位思路：搜索多搜POI粗略位置，鸟点是精确位置）：`SpotSearchList`（spot_dialog.py）结果列表分两段——📍已有鸟点 / ──高德地点──🔎POI条目；选中POI按其位置直接建鸟点（**同名复用不重复建**，`find_or_create_spot_by_poi`）。`PoiSearcher`（map_page.py）共享POI搜索（350ms防抖），MapPage搜索、MapPickDialog、挂点对话框三处共用。
- **MapPickDialog 加搜索框**：先搜地名跳大致位置→点精确角落→确定；"地图选点界面没有搜索框"的不便一并解决。
- 交互约定：单击列表=只选中；回车/双击=应用。选POI=建粗略鸟点；要精确位置走「地图选点新建」。
- 验证：POI搜索→建点→批量挂载→同名复用 全链路实测✓（"奥林匹克"8结果）；batch_spot截图验收PASS；打包+冻结验证PASS。

## 2026-10-23 · B4.2 用户反馈轮2：品牌logo + 批量挂鸟点 + 单张挂点升级

### 1. 品牌logo（用户提供Gemini生成图，伪透明棋盘格JPG）

- `tools/make_logo.py`：抠图管线——①边界BFS清棋盘灰（黑轮廓挡住填充）②轮廓外光晕放宽阈清除 ③封闭空隙逐块判定：块内"严格深灰格(≈195)占比≥5%"才整块清（棋盘空隙特征），否则保留（鸟身阴影）。
- **v1教训**：全局严格清灰把鸟身浅灰阴影打穿（1.6万px孔洞，验收FAIL）——鸟身白(249蓝调白)与棋盘浅灰(236)色谱重叠，全局色彩键控必穿孔；且"残留计数"指标有盲区（清掉的像素变透明就不计了）。
- 产物 `assets/brand/logo.png` + `logo.ico`；验收PASS（0穿孔、缝隙干净、轮廓完整）。
- 接入：侧栏72px、窗口图标、exe图标（spec icon=logo.ico）、分享卡右下角150px（替换原矢量小鸟，缺失时回退）。make_release COPY_FILES加logo.png（copy2不建父目录的坑已修）。

### 2. 导入后批量挂鸟点

- `BatchSpotDialog`（spot_dialog.py）：导入完成后，若选择"不挂鸟点"或"自动但无任何GPS可归组"，弹出"为这 N 张照片设置同一个鸟点？"——搜索已有点/地图选点新建/仅名称新建/跳过。`Library.set_photos_spot` 单事务批量挂载。
- 单张照片「挂到鸟点」对话框加「在地图上选点新建…」（MapPickDialog→命名→建点挂载），无GPS照片的主路径。

### 3. 顺带修复

- 分享卡预览改为整卡适配视口高度（原来按宽缩放，长卡底部logo看不到）。

### 验证

- logo：视觉验收PASS；批量DAO测试✓；batch_spot/share/timeline（侧栏logo）/sharecard_light+dark 渲染验证✓
- 冻结版：地图PASS（12264色）+ 侧栏logo像素确认✓
- share.png首验FAIL复盘：logo其实已渲染，是预览框折叠在下方——顺带修复。

## 下一轮

B5 性能优化 / B6 生态（eBird 导出、年度报告、**自动备份——真实使用前建议优先**）。

---

## 2026-10-23 · B4.1 用户实测反馈轮：地图改高德JS API + 鸟点地图合并 + 改鸟种 + 移除照片

用户首次真实使用（启动鸟迹.bat，源码方式）后反馈4个问题，本轮全部处理：

### 1. 地图不显示 → 弃自绘瓦片，改高德 JS API（用户选定方案，供了 JS API Key+安全密钥）

- **诊断结论**（留存备查）：用户库瓦片缓存1398个文件显示——初始视野(z4中国)瓦片**下载缓存正常**（北京z4瓦片6.7KB/253色真实影像），但之后所有请求全跑到北纬85°/东经-180°钳制边界（z8+全是103字节空瓦片），即视野被某次交互带进极区钳制后，wheelEvent缩放中心取自光标经纬度，永远出不来。第一触发源未定位（QGraphicsView真实屏幕渲染环节，grab截图复现不了；用户搜索后可能拖图找图加速了跑偏）。
- **新方案**（用户拍板"嵌入浏览器控件+JS API"）：`app/ui/amap_view.py`，QWebEngineView+QWebChannel，AMap JS API 2.0 + 官方MarkerCluster。Key/安全密钥存settings(map_js_key/map_js_secret)+内置缺省；HTML写`<库>/amap.html`；设置页可改Key，`ensure_keys()`检测变更重载。
- 搜索/选点/纠偏逻辑沿用：POI搜索仍走Web服务Key的REST（下拉改侧栏列表）；选点模式JS `map.on('click')`；WGS84↔GCJ-02换算在Python侧。

### 2. 鸟点+地图合并为一个模块

- 导航去掉「鸟点」页，「鸟点地图」页 = 左侧栏（地名搜索+结果列表+鸟点卡片+新建按钮）+ 右侧地图 + 弹卡（详情/编辑/关闭）。
- 鸟点详情改 `SpotDetailDialog`（统计头+物种清单胶囊+照片流+编辑/删除），spots_page.py 删除。
- 选点后可直接「在此建鸟点」（弹卡预填坐标）。

### 3. 鸟种随处可改

- 查看器每条识别记录加「改鸟种…」→ `species_pick.py`（全库11171种，中文名/学名/英文/拼音/拼音缩写搜索）→ `set_confirmed`。
- 无识别记录的照片可「＋标注鸟种」→ `add_manual_record`（source='manual'，计入lifer/统计）。

### 4. 移除照片（不动原文件）

- 查看器「从鸟迹移除…」+确认框；`Library.remove_photo`：显式删 records/exif/photos 行（FK级联依赖连接级PRAGMA不可依赖）+ 清缩略图缓存；原文件绝不动。

### 验证

- 视觉子代理：map（真实北京影像+双pin位置正确）/ spots_detail / settings / timeline 全过；viewer「改鸟种…」按钮裁切修复后 PASS。
- DAO 测试：改种生效(eff_code)、手工标注(source=manual)、移除级联(photos/records/exif清零+缩略图清理)✓。
- 回归：smoke ✓ e2e ✓。
- JS↔Python桥接探针：mapReady/center_moved/marker点击/选点全通。

### 本轮踩坑（详见 PLAN.md §7）

- **QWebChannel方向**：signal在JS侧是{connect,disconnect}对象**不可调用**，JS→Python必须走@Slot方法（typeof检查一眼识破：'object' vs 'function'）。
- runJavaScript结果回调只可靠回传原始类型；AMap在0×0容器上setBounds算错缩放（showEvent首显重fit解决）；mapReady别等'complete'（>15s），建图即报；QWebEngineView内容截图必须PIL ImageGrab真实屏幕。

## 下一轮

B5 性能优化 / B6 生态（eBird 导出、年度报告、**自动备份——真实使用前建议优先**）。另：用户库的 `<库>/tiles/` 已无用可删；旧 exe 需重新打包（本轮 B4.1 后）。

### 交付内容

- **瓦片底图**：高德栅格瓦片（OSM 国内不可达，实测高德 23ms vs OSM 超时），按需加载 + `<库>/tiles/` 本地缓存 + 合规 UA。自绘 slippy map（`TileMap`）：滚轮整数级缩放（锚点跟随鼠标）、拖拽平移、缩放 3–17。
- **坐标体系**：鸟点库存 WGS84（照片 GPS 真实值），高德瓦片/POI 是 GCJ-02，`app/core/gcj02.py` 双向纠偏（往返误差 ~1m）。地图选点自动反算回 WGS84 入库。
- **鸟点图钉**：每点一枚圆形缩略图图钉（白描边+三角），低级别下 56px 内聚合成数字气泡（点击放大一级）；点击图钉弹卡：统计+3 张缩略图+「查看鸟点详情」+「在系统地图打开」（uri.amap.com/marker）。
- **POI 搜索**：高德 place/text API（Key 在设置页"地图"卡填写，已存入演示库与正式库）。实测"野鸭湖湿地"返回 96 个结果（含观景平台/停车场等细粒度 POI），选中即跳转。无 Key 时可粘贴"纬度,经度"直跳（按 WGS84 解释）。
- **选点模式**：地图页工具条开关（点按取坐标、拖动平移不触发）；`MapPickDialog` 接入鸟点编辑对话框「在地图上选点…」，确认后回填经纬度。
- **导航**：新增「地图」页（鸟点之后）；离线时显示已缓存瓦片+橙色提示。

### 验证

- 坐标数学：GCJ 往返误差 0、墨卡托换算精确往返 ✓
- 离屏渲染：15+ 块瓦片加载、std 26.5 ✓
- 搜索：坐标粘贴 ✓、高德地名搜索 8/页+跳转（GCJ↔WGS 往返一致）✓
- 视觉验收 4 张全过（map/settings/spots/spots_detail）：真实路网纹理+两枚图钉位置正确（野鸭湖/奥森）✓
- 回归：smoke ✓ e2e ✓ 打包 exe 冻结库迁移 ✓

### 本轮踩坑（详见 PLAN.md §7）

PySide6 四连坑：reply 不回传 request attribute（改从 URL 解析）；`bool(NetworkError.NoError) == True`（必须显式枚举比较）；`QUrl.queryItemValue` 已移除（用 QUrlQuery）；TILE 子域名拼接笔误（webst001 不存在）。QGraphicsView 在祖先级 grab() 时复用空 backing store → 截图纯背景（grab 前强制 `viewport().repaint()` 解决；TileMap 加 showEvent 重 assert 中心，切页回来也受益）。`scrollContentsBy` 在 centerOn 中间态重算中心会写歪（`_internal_move` 标志屏蔽）。

## 下一轮

B5 性能优化 / B6 生态（eBird 导出、年度报告、**自动备份——真实使用前建议优先**）。照片按鸟种着色 marker 层推迟。

---

## 2026-10-23 · B3 鸟点数据层 + 鸟点页完成

### 交付内容

- **数据层**：`spots` 表（名称/经纬度/备注）+ `photos.spot_id` 外键；`Library._migrate` 对旧库自动 `ALTER TABLE` 补列，冻结环境验证通过。`photo_detail` 现返回 `spot_name`。
- **自动归组**（`app/core/spots.py`）：导入未指定鸟点时按 EXIF GPS 聚类——300 米内并入最近鸟点，否则自动新建"鸟点 N"（可在鸟点页重命名）。haversine 距离。
- **导入页**：新增「挂到鸟点（可省）」卡片：自动按GPS归组（默认）/ 不挂 / 选已有鸟点 / ＋新建（输入名称）。导入完成提示自动新建的点数。
- **照片查看器**：信息面板新增"位置"行；「设为鸟点」按钮打开对话框（`spot_dialog.py`）：搜索已有点挂载 / 从这张照片GPS新建 / 解除挂载。无GPS照片自动禁用建点。
- **鸟点页**（新导航项，插在"鸟种库"后）：列表卡片（封面缩略图/照片数/鸟种数/最近记录/坐标/备注）+ 详情页（统计头卡、物种清单胶囊可点击跳鸟种、照片流缩略图可开查看器、编辑/删除鸟点）。删点不删照片。

### 验证

- 单元：旧库迁移✓、95m 同点归组/远距新建✓、haversine✓、删除解挂✓
- 端到端：seed_demo 注入 GPS 重建演示库 → 奥森两张（相距95m）并入"鸟点 1"，野鸭湖两张（250m）并入"鸟点 2"，无GPS两张未挂✓
- 对话框流程：挂载→解挂 状态正确，无GPS照片建点按钮禁用✓
- 回归：smoke_test（补全6物种真值表——上轮加图后遗留失配）✓、e2e_test 全过✓
- 截图：spots / spots_detail / import / viewer / timeline 共5张视觉验收全过（经历3轮修复：截图脚本没切导航栈、_clear旧控件同tick残留、grab早于QScrollArea重排版——修复均已固化，见 PLAN.md §7 踩坑）
- 打包：make_release 重建 exe，冻结库迁移验证✓

### 顺带修复

- seed_demo 写 GPS：此版 Pillow 的 RATIONAL 字段必须传**浮点度分秒标量元组**（如 `(40.0, 0.0, 12.6)`），不能传嵌套分数元组；旧代码 ExposureTime 的 `(1,1600)` 能读回纯属巧合。

## 下一轮

B4 交互地图（依赖 B3 的 spots 数据，方案 §4.2 自绘 slippy map）→ B5 性能 → B6 生态。

---

## 2026-10-22 · B1+B2 完成，并意外修复了一个 v1 核心bug

按 PLAN.md 执行完毕：B1 全部、B2 全部、B7 回归打包，均已验证。

### 本轮最大成果：抓到并修复了地理先验的符号bug

为做"当月出现提示"功能去读先验库时，发现数据对不上——按原解码，**麻雀在北京成了"罕见"，而美洲的大尾拟八哥在中国成了"常见"**。经过多地区交叉实证（纽约1月=灯草鹀/主红雀✓、加州=安娜蜂鸟✓、北京=麻雀+2.0顶格✓、家麻雀-1.5✓（它确实不到北京）），确定：

1. **解码应该取反**：`(128-字节值)×0.03125`，字节0为哨兵=硬-4
2. **v1的识别重排方向一直是反的**——视觉logits太强掩盖了问题，但模糊照片会被误导。修复后e2e实测：**苍鹭置信度0.59→0.995**，树麻雀0.957→1.0
3. CN区域行存在超出官方clamp[-4,+2]的噪声值（会把戴胜照片推出错误结果），已按文档在读取时强制截断修复

### 已交付的B2功能（全部截图验证）

- **物种详情页v2**：概览/图鉴/文化三个标签页。图鉴页展示7个字段（概述/识别要点/分布区系/栖息地海拔/行为/食性/卵数）+ **当月出现提示**（"本月·中国：常见"）+ **罕见度5档**；文化页展示双语长文故事（普通翠鸟的"纽伦堡画家"故事完整呈现）带分类标签和来源
- **每日一鸟横幅**：时间线顶部，每天从962个有故事的物种确定性轮换，点击直达详情（库外物种也正常显示）
- **年鸟桂冠徽章**：时间线"年鸟"角标（今年首见且往年有过）、鸟种卡👑#N+🌿年鸟、统计页新增"今年新种/今年回归"数字卡
- **检测灵敏度设置**：设置页低/中/高三档（conf 0.35/0.25/0.15）

### 验证

- 图鉴库11171条记录**全量sha256校验**通过（修复了空字段截断bug——内容字段可合法为空）
- e2e回归：6张图识别正确，斑嘴鸭vs绿头鸭这类真实近缘混淆正确落入待复核
- 打包exe冻结环境验证通过（顺带修了make_release漏拷新资产的缺陷）
- 9张UI截图+详情页3张截图全部正常（存于 `data/ui_shots/`）

### 遗留备忘

- PLAN.md §7 已记录：**CN各省的先验向量有超出clamp上限的噪声值**（比如仙鹤在三行数据里顶格），已截断处理不影响使用。如方便可问安卓作者："中国省级行的geoprior数据构建时是不是没做clamp？"

## 下一轮（PLAN.md 顺序）

B3 鸟点数据层 → B4 交互地图 → B5 性能优化 → B6 eBird导出/年度报告/自动备份
