# GaussianFormer Visualizer · Mesh 项目副本 1.0.25

本版本随 Mesh 十图评价工具包提供，直接安装 VSIX，无需 npm 或源码编译。

先运行工具包 setup.cmd，再打开 mesh-evaluation.code-workspace。插件自动选择其中的 .venv；也可在 gaussianVis.pythonPath 指定 Python。

- GaussianFormer: Open Visualizer：原三维交互入口。
- Mesh: Generate Fixed Ten-Scene Review：选择 vis、identity.json 和输出父目录，生成浏览器十图复核页。

Z 放大实际为 ×5，界面标注已同步修正。M3 固定评价使用离线浏览器报告中的统一 BEV 配色，与三维浏览器自身多类调色板区分。

项目副本沿用原扩展 ID gaussianformer.gaussianformer-vis，会更新原安装。源码中保留 Three.js 与原辅助程序，变更见 PROJECT_CHANGES.md。原提供版说明保留在 README.upstream.md。
