# 架构说明（ARCHITECTURE）

> 本文件是软件的"地图"：模块职责、数据流、线程模型、渲染管线、扩展点、短板。
> 修改任何核心代码前先读这里。配套：PROGRESS.md（进度与踩坑）、docs/AUDIT.md（基础功能审查）、
> docs/GAP_ANALYSIS.md（vs 剪映差距与路线）。

## 1. 总览

```
┌──────────────────────────────────────────────────────────┐
│ video_cut_app.py    入口（PyInstaller 打包入口）          │
├──────────────────────────────────────────────────────────┤
│ editor/                                                    │
│   editor_app.py      主窗口：媒体栏/预览/时间轴/属性侧栏/图层│
│      │               面板/导出/快速成片；交互路由全部在这   │
│      ├── model.py    数据模型（Project/Track/Clip系列）    │
│      │              + JSON 序列化 + 滤镜/转场元数据        │
│      ├── engine.py   渲染引擎（分轨中间件两段式）           │
│      ├── preview.py  应用内播放器（画面帧流+音频+PiP叠加）  │
│      ├── timeline_widget.py  时间轴画布控件                 │
│      ├── project_store.py    .vcp 读写 + autosave         │
│      ├── settings_store.py   界面状态记忆（窗口/目录/…）   │
│      ├── undo.py     撤销/重做（快照式）                   │
│      ├── thumbs.py   素材缩略图生成+磁盘缓存（异步）       │
│      ├── wave.py     音频波形峰值+磁盘缓存（异步）         │
│      ├── theme.py    深色主题（ttk clam）                 │
│      └── logger.py   日志（滚动文件 logs/app.log）         │
└──────────────────────────────────────────────────────────┘
外部依赖：ffmpeg.exe（唯一二进制依赖；时长/音频探测用它 -i 解析）、
         sounddevice+soundfile（预览音频，可选降级）
```

## 2. 数据模型（model.py）——"唯一事实来源"

- `Project`：画布尺寸、fps、轨道列表；`total_duration()=可见轨道末端 − 转场重叠`
- `Track`：kind（main/overlay/audio/subtitle）+ `visible`（图层开关）+ clips；`move()` 调 z 序
- `Clip` 基类：src/ts/duration/speed/volume/effects
  - `VideoClip`：in/out 源裁剪、x/y/w/h PiP、opacity、transition(到下一段)、ramp 渐变速度
  - `ImageClip`　`AudioClip`（淡入淡出）　`TextClip`（文字/字幕，drawtext）
- 序列化：`to_dict/from_dict` 全链路，`Project.to_json/.from_json` 即 .vcp
- 扩展点：`Clip.effects`（type=filter 已实现；transition/字幕等按 type 分发）、Track.kind 可加"音轨组"等

## 3. 交互路由（editor_app.py）

```
素材列表(双击/拖拽/右键) ─→ _media_add_auto / _drop_media / 右键菜单
时间轴(单击=跳转/拖=移动裁剪/右键) ─→ seek/移动/裁剪/变速菜单
属性侧栏(右侧常驻，▦ 开关)  图层窗(🗂)  画布(◧)  ⚡快速成片  🎬导出视频  ↩撤销 ↪重做 ← 顶栏
```
- 所有编辑动作：`_push_undo()`（变更前快照）→ 改模型 → `_after_model_change()`
  （autosave 去抖 + 时间轴刷新 + 视图策略(_reveal_clip) + 控件状态 + 波形预取）
- 控件可用性：`_refresh_controls()` 按状态禁用（无素材禁播放、无线索禁渲染…）

## 4. 预览与线程模型（preview.py）

- 主线程：tk 事件循环（33ms tick：取帧显示 + 叠加层同步）
- 后台线程：主画面 ffmpeg rawvideo 读帧（帧带 generation，seek 换代不串帧）；
  每个活跃画中画一个解码线程（2×超采样→LANCZOS 合成）；音频 WAV 用 sounddevice 流回调
- 墙钟同步：播放位置按单调时钟推进（音频为准），画面尽力跟上
- 关键：**任何阻塞操作不允许在主线程**——缩略图/波形都在子线程队列，
  回主线程用 after/回调；弹窗（messagebox）在自动化里会"隐形卡死"，必须打桩

## 5. 渲染管线（engine.py）——无损中间件两段式

```
第一阶段(每轨独立)：源 ─trim/变速/缩放(flags=lanczos)─▶ ffv1 中间件(无损)
                    音频：pcm_s16le；overlay 轨：rgba 透明
第二阶段(合成)：  各轨中间件 → overlay 叠加 + drawtext(字幕) + amix
                  → 最终编码（mp4/mov: h264+crf；webm: vp9+opus；crf0=无损）
轨道链：concat/xfade(转场)/acrossfade(音频转场)；隐藏轨不参与
```
- 中间件放在临时目录（可勾选"保留中间产物"）；字体/字幕文本用相对路径+cwd 技巧
- 无增量缓存：改一轨全量重渲（已列为 TODO）

## 6. 已知短板（诚实清单）

- 预览连续播放 = 主轨顺序拼接播（PiP 画面实时叠加；音画墙钟级同步，非帧级）
- 无轨道级增量渲染缓存；超长项目渲染耗时线性增长
- 唯一二进制 ffmpeg 157MB（精简构建可缩到 ~80MB，见 AUDIT）
- 快照式撤销（50 步）；无多级嵌套撤销分组
- tkinter 高 DPI 未做 PerMonitorV2（高分屏字体稍虚）

## 7. 测试体系（改代码必跑）

```
python test_engine.py        # 渲染管线 + 素材完整性 + 隐藏图层像素断言
python test_ui_smoke.py      # UI 冒烟（按钮状态/自动入轨/mp3全链路/日志/状态记忆）
python test_interactions.py  # 交互巡检 S1-S17（保存打开/撤销重做/导出E2E/坏路径/快速成片…）
python -m PyInstaller ...    # 打包（build_exe.bat）
```
新增任何修复：先在 test_interactions 补一条 "S#：描述"，再改代码。