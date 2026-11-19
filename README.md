# Mesh Visualize · 评测结果可视化

[实习项目总览](https://github.com/Inner-vic/internship-projects) · [使用与验证](docs/project-guide.md)

把已有 Mesh 或点云评测产物转换为等比例五视图，返回可追溯的图像与元数据。

## 解决的问题

单张渲染图难以解释预测差异：场景、帧、视角、尺度和输入身份可能各不相同；图片生成完成，也不等于有人真正看过并完成评价。

项目将固定场景出图、同尺度对照、逐图判断和结果绑定组织为一份可离线查看与复核的视觉证据包。

## 实现了什么

- 固定十场景 Mesh 保留既有出图与复核协议。
- 新增点云与 Gaussian 一次出图入口，接收已有时序导出，按编号选择 GT / Prediction / Camera / LiDAR / Gaussian 五视图。
- 静态视图保持 X:Y:Z=1:1:1，GT/PRED 共用范围和视角；采样、语义过滤与来源摘要随结果保留。
- 命令行和 Python 接口可独立调用，由上层功能提供输入和消费返回的图像、manifest 与复用状态。

## 实现架构

![Mesh Visualize的主要模块、执行顺序和关键边界](https://raw.githubusercontent.com/Inner-vic/internship-projects/main/assets/architecture/mesh-visualize.svg)

## 关键工程设计

### 1. 固定输入和共同视角

静态视图保持 X:Y:Z=1:1:1，GT/Prediction 使用共同范围、尺度和视角。相机角度可以调整，但不通过夸张高度或补造网面改善视觉印象；必要同帧输入缺失时显式报错。

### 2. 把出图与评价分开

Python/CLI 负责生成图像与元数据，人工或 Agent 负责实际读图与判断。最终结果允许“资料完整但质量不通过”，避免把可视化成功当作模型达标。

### 3. 让一轮判断绑定到一轮产物

复核记录包含图像路径、内容摘要、样本身份和具体判断；Agent 还需保留原始读图回执。程序能检查覆盖和绑定关系，不能仅凭哈希或一个字符串证明实际看图行为。

## 产物与支持范围

点云入口使用 `pointcloud.cmd` 或 `pointcloud_visualize.generate`，支持编号、数量与视角选择；固定十场景 Mesh 仍按原协议生成场景卡和复核文件。接口说明见[接入与扩展](docs/INTEGRATION.md)、[点云调用](docs/POINTCLOUD_USAGE.md)及[原子出图](docs/ATOMIC_CAPABILITY.md)。

本工具处理已经生成的评测产物，不启动训练或模型推理。公开仓库保留代码、输入规范和合成测试；源项目的实车图片、点云、Gaussian 输入与场景 ZIP 未随源码发布。使用自己的合法 `vis/` 输入；`demo.cmd` 仅展示合成诊断流程，不代表真实五视图或模型质量。

## 源码导读

| 源码 | 关注的实现 |
| --- | --- |
| [mesh_visualize.py](mesh_visualize.py) | 原子出图入口 |
| [pointcloud_visualize.py](pointcloud_visualize.py) | 时序点云输入、采样溯源与一次出图 |
| [five_view.py](five_view.py) | 五视图和 Gaussian 绘制 |
| [mesh_eval.py](mesh_eval.py) | 协议、复核、finalize 与 check |
| [fixed10-scenes.json](fixed10-scenes.json) | 固定场景协议 |

## 项目资料

使用步骤、依赖和本地验证见[使用与验证](docs/project-guide.md)；源码来源与验证范围见[发布说明](https://github.com/Inner-vic/mesh-visualize/blob/main/PUBLICATION.md)。本页用于介绍实习阶段的实现与设计，具体结论以所链接的代码和证据为准。

[RoadModel 评测](https://github.com/Inner-vic/roadmodel-evaluation)展示模型/编译评测编排；本工具作为独立后处理能力保留，数据接入须先满足固定协议。
