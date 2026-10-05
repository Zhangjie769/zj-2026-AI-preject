# PROGRESS —— 视频剪辑应用开发进度笔记

> 本文件是**中断恢复的锚点**：任何会话接手时先读本文，再读 `editor/` 下各模块开头注释。
> 上次更新：2026-10-03

## 项目目标（用户需求原文要点）

1. 应用内能播放视频（预览）
2. 能把不同视频剪辑在一起（拼接时间轴）
3. 有时间轴，可放大缩小（时间轴缩放），加速，音量变大变小
4. 多画面布局（PiP）：视频1在左上、视频2在右上、视频3前10分钟在右下、
   右下角一直有一张图片（支持 png 等图片格式）
5. **不要把接口堵死**：架构留扩展点（新特效、新轨类型、转场、字幕等后续可加）
6. 随时可能中断 → 做好记录（本文件 + 项目自动保存）

## 已确定的技术决策（不要推翻，除非有充分理由）

- 技术栈：Python 3.12 + tkinter + Pillow；打包 PyInstaller onedir，**ffmpeg/ffprobe 已捆绑**
- ffmpeg 位置：`tools/ffmpeg/bin/{ffmpeg,ffprobe}.exe`，打包后复制进 `dist/video_cut_app/`
- **渲染引擎 v2（重要！）**：分轨中间文件两段式
  1) 每轨独立渲染成无损中间文件（matroska：主轨 ffv1/yuv420p、overlay ffv1/rgba 透明）
  2) 小图合成（overlay 逐轨叠加 + amix 音频 + atrim 总长 → x264/aac）
  原因：新版 ffmpeg（n9.0）**已移除 -filter_complex_script**，且巨型单图有命令行长度风险
- **ffmpeg 语法坑（务必记住）**：新版不允许 `[标签],过滤器名` 中间有逗号，
  必须 `[标签]过滤器名`。之前"Filter not found ''"就因此引起
- 预览播放：ffmpeg 输出 rawvideo → Pillow → PhotoImage，后台读帧线程 + 队列（不卡 UI）
- 时间轴播放头：tkinter Canvas 自绘；缩放 = 修改"像素/秒"
- 项目文件：JSON（`.vcp`），含 canvas 尺寸、各轨片段；每次变更自动保存到 `autosave.vcp`
- 编码/目录约定：输出 mp4 h264+aac+mov_text；片段输出 `_cut<秒>s.mp4`
- PiP 设计：**每个叠加层一条独立 overlay 轨**（主轨满屏；重叠层互不干扰），
  同轨内重叠由引擎防御性顺延（正常 UI 阻止重叠）

## 文件模块清单（完成情况见末尾命令清单）

| 文件 | 职责 | 状态 |
|------|------|------|
| `PROGRESS.md` | 本文 | ✅ 持续维护 |
| `editor/model.py` | 数据模型 + JSON 序列化 + 轨道/片段/特效链 | 见下方 |
| `editor/project_store.py` | .vcp 读写 + autosave | 见下方 |
| `editor/engine.py` | filter_complex 构建 + ffmpeg 渲染 + 进度 | 见下方 |
| `editor/preview.py` | Pillow 播放器（播放/暂停/seek/变速） | 见下方 |
| `editor/timeline_widget.py` | 时间轴控件 | 见下方 |
| `editor/editor_app.py` | 主窗口组装 | 见下方 |
| `video_cut_app.py` | 入口（兼容打包脚本） | 见下方 |
| `test_engine.py` | 引擎冒烟测试（生成样例媒体→渲染→验证时长） | 见下方 |

## 模型设计（model.py 摘要）

- `Project(canvas_w=1920, canvas_h=1080, fps=30, tracks=[...])`
- `Track(kind='main'|'overlay'|'audio', clips=[...])`；overlay 轨的片段带 x/y/w/h（画布坐标）
- `Clip` 基类：`id, track_id, src, ts(时间轴起点秒), duration(时间轴时长秒), speed, volume, effects[]`
- `VideoClip` 额外：`in_point, out_point`（源裁剪），`x,y,w,h`（PiP 位置，满屏用 -1 表示）
- `ImageClip`：`duration` + 位置/尺寸/透明度（无 in/out/speed 音频）
- `effects` 列表为扩展点：将来 `{"type":"transition","name":"fade"...}`、滤镜等
- 时间轴时长 = (out-in)/speed；片段总时长 = max(ts+duration)

## 渲染管线（engine.py 摘要）

1. 按轨分组，按 ts 排序；相邻片段间空隙用 `color=black` + `anullsrc` 填空
2. 每轨：各片段 trim(源裁剪) + setpts(PTS/speed) + 音频 atempo(链式)/volume → concat 成一轨
3. overlay 轨：片段先 scale 到 w/h 再 overlay 到透明画布 (x,y)，多段 concat（空隙透明）
4. 最终：`[main][ov1][ov2]overlay` + `amix(normalize=0)` 音频 + `atrim=0:总时长` + `format=yuv420p,fps=30`
5. 图片片段：`-loop 1 -framerate 30 -t <duration> -i img.png`（会放大输入数）
6. 输出：h264 + aac + mov_text（字幕尚在 TODO）

## 下一步 / 待办（按优先级）

- [x] 极简模式：属性面板随选中自动显隐；深色主题 theme.py（第七轮）
- [x] ⚡快速成片向导：多选素材→自动拼接+转场→渲染（第七轮）
- [x] 预览 seek 优化：代次帧 + 双管线预热切换（第七轮）
- [x] 体积瘦身：去掉 ffprobe/ffplay，发布包 488→234MB（第七轮）
- [ ] 关键帧动画、多选批量、轨道增量缓存 → 后续轮次

- [x] 文字字幕轨：TextClip + drawtext 渲染 + 添加/编辑 UI（本轮）
- [x] 基础功能审查：中间产物暂存 / 素材不被破坏 / 自动命名 / 画质损耗（docs/AUDIT.md + 测试断言）
- [ ] 关键帧动画、多选批量、轨道级增量渲染缓存 → 后续轮次

### 2026-10-03 第七轮（清爽化：极简/美化/瘦身/向导/seek）
- ✅ 深色主题 theme.py（ttk clam 定制，零依赖）
- ✅ 极简：属性面板选中才显示；导出行去掉重复按钮
- ✅ ⚡快速成片：文件→多选→转场→分辨率→导出（复用渲染队列）
- ✅ ffprobe/ffplay 移除：时长/音频/fps 用 `ffmpeg -i` 解析
- ✅ seek 提速：帧带代次，新管线预热、旧管线延迟收尾
- ⚠️ 体积注：BtbN ffmpeg 157MB 是大头；换 gyan essentials(~80MB) 可再减 ~110MB（服务器本轮不可达）

### 2026-10-03 第六轮（文字字幕 / 基础功能审查）
- ✅ 文字轨：TextClip（内容/对齐/字号/颜色/淡入淡出）+ 工具栏「✎ 文字」+ 属性面板编辑 + 时间轴显示文案
- ✅ 渲染：drawtext（textfile 相对路径 + 字体复制进中间目录 + 子进程 cwd）像素级验证通过
- ✅ 审查报告：docs/AUDIT.md（中间产物可暂存/源只读有断言/三级自动命名/画质链路透明可控）
- ✅ 导出对话框：自动命名(项目名_分辨率_时间戳)、无损档(CRF0)、保留中间产物勾选
- ⚠️ 坑：新版 ffmpeg filtergraph 单引号内盘符冒号解析失败 → 一律相对路径 + cwd 技巧

### 2026-10-03 第五轮（缩略图/波形/滤镜/导出预设）
- ✅ 素材缩略图：Listbox→Treeview（图片列），后台线程 ffmpeg 抓帧，磁盘缓存(路径+大小+mtime 哈希)
- ✅ 音频波形：ffmpeg 解 f32le 8000Hz → 0.05s 窗口 RMS，JSON 磁盘缓存 + 时间轴逐像素绘制
- ✅ 滤镜：eq(brightness/contrast/saturation) + hue=s=0 黑白；存在 Clip.effects[type=filter]；
      属性面板"滤镜:"行 + 黑白勾选
- ✅ 导出预设：导出对话框（格式 mp4/mov/webm + 画质 CRF16/20/26/30 + 路径）
- ⚠️ 注意：Treeview 的 selection_set 用字符串 iid；图片列用 ImageTk.PhotoImage 需防回收

### 2026-10-03 第四轮（UX 打磨 / 复制粘贴 / 工具栏 / 素材刷新）
- ✅ 控件可用性：没加载素材时 播放/回零/进度条/试听 全部禁用；
      未选中片段时 应用/删除/分割/波纹/速度/预设/变速到时长 禁用；
      空时间轴时 渲染按钮 禁用 —— 杜绝"空手能按按钮"
- ✅ 素材自动刷新：每 2 秒检测文件夹变化自动刷新列表；手动 ⟳ 按钮；切目录自动刷新
- ✅ 工具栏：菜单下方新工具栏，复杂功能分组收纳（文件/编辑/时间轴/渲染），全部带悬停提示气泡
- ✅ 复制/粘贴片段：Ctrl+C/Ctrl+V + 工具栏按钮；粘贴到播放头，同轨自动找空位防重叠
- GAP 勾销：复制/粘贴 完成

### 2026-10-03 第三轮（吸附/转场/变速/接缝）
- ✅ 磁吸：拖动/裁剪左边缘/右边缘时吸附到 各轨片段边缘/播放头/0，可开关（工具栏☑磁吸）
- ✅ 转场：16 种 xfade（fade/fadeblack/dissolve/wipe/slide/circle…）+ 音频 acrossfade；
      所在片段→下一相邻片段；总时长自动扣除重叠；时间轴显示 ◤转场标记
- ✅ 变速：常用速度按钮(0.5~4x)、变速到目标时长、视频渐变速度（起速/末速，setpts 二次公式，
      音频按平均速度 atempo——已知限制）
- ✅ 接缝：『闭合全部空隙』『闭合本轨空隙』『波纹删除』；吸附对齐后转场无缝
- ⚠ 测试注意：自动化测试禁止用带确认框的入口（如 _new_project），会阻塞挂起
- ffmpeg 语法坑补充：链输出重命名用 null/anull 滤镜，不能把两个标签直接拼在一起（会报空过滤器）

## 测试命令（改动后必跑）

```
python test_engine.py    # 引擎回归（生成样例→渲染→验证时长/分辨率/像素）
python test_ui_smoke.py  # UI 冒烟（实例化→加素材→选片段→自动保存）
```

## 已知限制 / 待扩展（用户明确说"不要堵死接口"）

- 预览音频与画面为"墙钟对齐"（±100ms 级），正式成片以渲染为准
- 同轨重叠：UI 不阻止（引擎会防御性顺延），后续可加吸附/冲突提示
- Clip.effects 已预留，但渲染器还没按 type 分发（转场/滤镜/字幕 TODO）
- 图片换帧动画、关键帧动画（位置随时间变化）未做
- 音频波形、素材缩略图、吸附、转场、文字轨等 → 见 docs/GAP_ANALYSIS.md

## 交付物清单（2026-10-03 长任务收尾）

- `dist\video_cut_app\` —— 完整绿色版（exe + ffmpeg/ffprobe/ffplay），启动验证通过
- `editor\` —— 模块：model/engine/preview/timeline_widget/project_store/editor_app/
  undo/settings_store/logger
- 测试：`test_engine.py`（含音频轨/淡入淡出）、`test_ui_smoke.py`（含撤销/音频轨/分辨率）全绿
- 样例素材：`samples\`（ffmpeg 生成，可反复测试用）
- 差距分析：`docs/GAP_ANALYSIS.md`（vs 剪映，含 10 项优先级路线）

## 阶段性更新记录

### 2026-10-05 第三轮（后台任务/画中画锯齿/拖拽图/时间轴刻度/属性侧栏）
- ✅ 后台任务系统：重活线程化 + 中央忙碌遮罩吞点击 + 线程安全 UI 队列（`_start_task`/`_post_ui`）
- ✅ 画中画锯齿根因修复：叠加层按源比例精确尺寸 + 2× 超采样 + LANCZOS（预览与渲染一致）
- ✅ 拖拽体验：拖素材有缩略图幽灵跟随 + 时间轴"放这里"落点蓝线；拖动片段不再丢缩略图
- ✅ 时间轴刻度等比例自适应：nice_step 选 1s/5s/…/10 分/30 分/1 时；MIN_PPS=0.01，
  40 分钟项目适配后一屏（约 840px）
- ✅ **属性改为右侧常驻侧栏**（可滚动，工具栏「▦ 侧栏」开关）：
  导出成片区（按钮/最近导出路径/打开文件夹）置顶；片段属性（源范围/速度/音量/淡入出/
  不透明度/渐变速度）、画中画（X/Y/宽/高 + 位置预设 + 原始/3/4/1/2/1/3/1/4 大小预设，
  保持源比例且不越界）、滤镜、转场、文字/字幕、操作按钮
- ✅ 导出流程更清晰：默认输出到素材文件夹并记住上次目录；扩展名随格式联动；
  完成后弹窗显示完整路径，可"打开所在文件夹/复制路径/在预览中播放"
- 新增回归：S25（拖拽幽灵/落点）、S26（刻度自适应/长视频等比缩放）、
  S27（侧栏/画中画大小预设/导出位置记忆）；S11/S22 随语义与缩放更新
- 坑记录：tkinter 的 PanedWindow 侧栏需把 Canvas 内窗宽度绑定 `<Configure>`
  才不会被内容撑宽裁掉；事件绑定 `<MouseWheel>` 用 `bind_all(add="+")` + 指针归属判断，
  避免影响时间轴缩放

### 2026-10-03 第二轮（音频/分辨率/日志/人性化）
- ✅ 音频轨：AudioClip + 独立音频轨 + 引擎混音（淡入淡出/音量/atempo）
- ✅ 应用内播放声音：sounddevice+soundfile 流式播放，墙钟同步
- ✅ 日志系统：editor/logger.py，滚动文件 logs/app.log + 日志面板 + 打开日志文件
- ✅ 撤销/重做：editor/undo.py（快照式 50 步）Ctrl+Z/Y + 菜单
- ✅ 界面状态记忆：editor/settings_store.py（窗口/目录/时间轴/最近项目）
- ✅ 目标分辨率：项目设置对话框（横屏/竖屏/4K/自定义 + fps）
- ✅ 文档：docs/GAP_ANALYSIS.md 差距分析 + 10 项升级路线
- 坑记录：新版 ffmpeg 无 -filter_complex_script；`[标签],过滤器` 逗号是语法错误；
  测试里 messagebox 会阻塞自动化（自动化测试绕过确认框）；
  logging.basicConfig 会把同一批 handler 挂到根 logger 造成日志重复（不用 basicConfig）；
  PyInstaller onedir 时 sys._MEIPASS 指向 _internal —— 数据目录一律用 exe 同目录

## 中断恢复三步曲

1. `git status` 或看目录文件 → 确认代码现状
2. 读本 PROGRESS.md 与各模块头部注释
3. 跑 `python test_engine.py` 确认引擎仍可用，接着做未完成的 TODO