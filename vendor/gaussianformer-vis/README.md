# GaussianFormer Visualizer · Mesh 项目副本 1.0.26

基于用户提供的 1.0.21 插件保留三维交互，并接入本项目一次调用生成固定十场景图片的能力。上游说明保留在 [README.upstream.md](README.upstream.md)。

## 使用

从源码执行根目录 `python build_release.py --out dist`，解压生成的 ZIP 后即可获得 `plugins/gaussianformer-vis-1.0.26.vsix`；分发包用户直接安装 VSIX，无需 npm。先运行工具包 `setup.cmd`，再安装插件并打开 `mesh-evaluation.code-workspace`。插件使用该工具包的 `.venv`，也可在 `gaussianVis.pythonPath` 指定 Python。

- `GaussianFormer: Open Visualizer`：原三维交互入口。
- `Mesh: Generate Fixed Ten-Scene Review`：选择 vis、identity.json 和输出父目录，生成十图复核页。

静态导出默认GT/Prediction/Camera/LiDAR/Gaussian五视图，XYZ固定1:1:1，俯角/方位角可调。交互浏览器原有的高度放大选项不影响静态输出。

项目副本沿用扩展 ID `gaussianformer.gaussianformer-vis`，安装会更新原插件。保留 Three.js 与原辅助程序；构建包中的 PROJECT_CHANGES.md 来自仓库 CHANGELOG.md。完整使用步骤见根目录文档。
