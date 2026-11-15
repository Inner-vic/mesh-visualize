# Mesh Visualize · 评测结果可视化

[实习项目总览](https://github.com/Inner-vic/internship-projects) · [使用与验证](docs/project-guide.md)

把固定场景评测产物转换为可对照、可逐图复核、可离线交付的视觉证据。

## 解决的问题

单张渲染图难以解释预测差异：场景、帧、视角、尺度和输入身份可能各不相同；图片生成完成，也不等于有人真正看过并完成评价。

项目将固定场景出图、同尺度对照、逐图判断和结果绑定组织为一份可离线查看与复核的视觉证据包。

## 实现了什么

| 能力 | 实现结果 |
| --- | --- |
| 固定协议输入 | 检查十场景、第 7 帧及同帧传感器元数据 |
| 多视图输出 | GT、Prediction、Camera、LiDAR、Gaussian 五视图及辅助诊断图 |
| 交互复核页 | 逐图填写分类、边界、形状、匹配和结论，导出本轮判断 |
| 结果绑定 | `finalize` 关联图像、身份、协议与复核记录，`check` 重新核验 |

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

默认输出十张主要评价卡、二十张辅助俯视图、HTML 复核页和元数据。CLI、Python 原子接口与 VS Code/Cursor 插件入口共享相应实现。

该工具处理已完成的评测产物，不运行训练或推理。当前协议和数据要求保持项目特定范围；合成 DEMO 只展示工具流程，不表示真实模型效果。接口见[原子出图文档](docs/ATOMIC_CAPABILITY.md)，输入及验证范围见[格式规范](docs/INPUT_FORMAT.md)和[公开说明](https://github.com/Inner-vic/mesh-visualize/blob/main/PUBLICATION.md)。

## 源码导读

| 源码 | 关注的实现 |
| --- | --- |
| [mesh_visualize.py](mesh_visualize.py) | 原子出图入口 |
| [five_view.py](five_view.py) | 五视图和 Gaussian 绘制 |
| [mesh_eval.py](mesh_eval.py) | 协议、复核、finalize 与 check |
| [fixed10-scenes.json](fixed10-scenes.json) | 固定场景协议 |

## 项目资料

使用步骤、依赖和本地验证见[使用与验证](docs/project-guide.md)；源码来源与验证范围见[发布说明](https://github.com/Inner-vic/mesh-visualize/blob/main/PUBLICATION.md)。本页用于介绍实习阶段的实现与设计，具体结论以所链接的代码和证据为准。

[RoadModel 评测](https://github.com/Inner-vic/roadmodel-evaluation)展示模型/编译评测编排；本工具作为独立后处理能力保留，数据接入须先满足固定协议。
