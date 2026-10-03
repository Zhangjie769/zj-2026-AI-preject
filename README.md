# my_AI_practice

个人 AI / 算法练习项目合集，包含三个独立子项目：

## 📐 shape_search — 图形搜索与求解器

类似「谁是猎头」的棋盘推理游戏辅助工具，包含策略求解、蒙特卡洛搜索、GUI 界面等。

- `engine_new.py` / `solver.py` — 推理引擎与求解器
- `hunt_gui.py` / `solver_gui.py` — 图形界面
- `REPORT.md` — 项目报告

## 🎬 video_cut — 视频剪辑工具

基于 Python 的桌面视频剪辑应用（Tkinter 界面）。

- `video_cut_app.py` — 主程序入口
- `editor/` — 编辑器核心模块（时间轴、预览、撤销等）
- `README.md` / `docs/` — 说明与文档
- 打包需要 ffmpeg（见 `tools/ffmpeg`）

## 🎙️ voice — 语音合成与变声实验

语音合成、变声效果（8bit / 可爱 / 太妹 等风格）的实验项目。

- `voice_lab.py` / `voice_studio.py` / `voice_workshop.py` — 主实验脚本
- `vary_speech.py` / `synth_demo.py` — 变声与合成演示
- `demo_wavs/` — 内置音效素材
- 中文文档见 `语音合成与播放全攻略.md`

---

> 注意：构建产物（`build/`、`dist/`）、`__pycache__`、大型数据文件（`.npy`、`.npz`、`configs.txt`）等已通过 `.gitignore` 排除，不参与版本控制。