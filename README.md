# mesh-visualize · 2.5D Mesh 原子可视化能力 1.4.0

独立仓库：https://github.com/Inner-vic/mesh-visualize。运行依赖为 Python、NumPy、Pillow 和系统中文字体；本仓库包含自身的渲染实现、固定十场景协议、插件源码、测试与构建脚本。

## 从 Git 源码开始

```powershell
git clone https://github.com/Inner-vic/mesh-visualize.git
cd mesh-visualize
py -3.12 setup.py
.\generate.cmd --vis "D:\eval\vis" --out "D:\eval\visuals" --elevation-deg 30 --azimuth-deg 8
```

Git 源码不包含 `.venv`、wheel 缓存、模型或真实场景产物。第一次 setup 使用已有 pip 配置安装固定依赖；后续本地出图可离线运行。Linux/macOS 使用 `python3 setup.py` 和 `.venv/bin/python mesh_visualize.py ...`；中文字体及实测范围见 docs/USAGE.md。

输入须是本项目固定十场景的实际评价产物；输出十张 GT/Prediction/Camera/LiDAR/Gaussian 五视图。接口说明见 [原子调用文档](docs/ATOMIC_CAPABILITY.md)。X:Y:Z 固定 1:1:1，俯角和方位角可调。

### 从源码构建插件和分发包

```powershell
python build_release.py --out dist
```

解压生成的 `dist/mesh-evaluation-1.4.0.zip`，即可找到 `plugins/gaussianformer-vis-1.0.25.vsix`；在 VS Code/Cursor 中选择“从 VSIX 安装”。原子出图可直接使用 Python/CLI。

GitLab CI 配置执行数值/证据检查及 JavaScript 语法检查，并构建分发 ZIP。CI 分发包会下载匹配 Windows Python 3.12 x64 的固定 wheel；源码仓库不跟踪这些二进制依赖。也可自行在 `wheels/` 准备对应 wheel 后构建离线包。


给使用本项目评价结果的同事：本包将固定十场景出图、浏览器逐图复核、结果核验以及 GaussianFormer 三维插件整合到一起。输入是**已完成的远端评价产物 `vis/`**。Python 只执行本地后处理，不执行模型推理或训练。

## 推荐入口：一次调用出图

初次执行 setup.cmd，之后直接调用：

```powershell
.\generate.cmd --vis "D:\eval\vis" --out "D:\eval\visuals"
```

或在 Python 中调用 `mesh_visualize.generate(vis_dir, output_dir, identity=None)`。默认返回10张黑底五视图（GT、Prediction、Camera、LiDAR、Gaussian），以及20张辅助俯视诊断图的路径和哈希；不要求打开插件或人工逐步操作。只有 vis 也能出图，正式评价身份可随调用传入。[原子能力接口](docs/ATOMIC_CAPABILITY.md)

## 先看效果：Windows 三步

1. 解压整个 ZIP 到一个可写目录；不要直接在压缩包内运行。安装 Python **3.12 64 位**并勾选 Python Launcher（已有则跳过）。
2. 双击 `setup.cmd`。预置 wheels/ 的 Windows Python 3.12 x64 分发包默认使用离线依赖；源码克隆默认联网。离线包可明确运行 `setup.cmd --offline`。
3. 双击 `demo.cmd`，浏览器打开十图复核页。页面明确标为 **模拟 DEMO**，不用数据集或 GPU；填写并导出 JSON，体验完整流程。

DEMO 只验证工具使用，不代表任何真实模型效果。真实评价见下文。完成后可以离线出图和查看报告。

## 用自己的真实结果

1. 准备固定协议下的完整 `vis/`；文件要求见 [输入规范](docs/INPUT_FORMAT.md)。当前随包协议固定为旧项目数据 `1.0.10` 的十场景、第 7 帧，不会自动替换成另一批场景。
2. 复制 `identity.example.json` 为本轮 `identity.json`，填入实际任务 UID、checkpoint SHA256、代码 commit 与数据版本。
3. 在包目录打开终端，执行：

```powershell
.\mesh.cmd inspect --vis "D:\evaluation-output\vis"
.\generate.cmd --vis "D:\evaluation-output\vis" --identity ".\identity.json" --out ".\outputs\candidate-001"
```

4. 打开输出目录 index.html，逐张查看全部10张场景评价卡，按需展开辅助俯视诊断；填写分类、边界、形状、匹配、结论和总结，导出 `visual-review.json`。
5. 指向下载的 JSON 完成绑定和核验：

```powershell
.\mesh.cmd finalize --run ".\outputs\candidate-001" --review "C:\Users\你的用户名\Downloads\visual-review.json"
.\mesh.cmd check --run ".\outputs\candidate-001"
```

将该轮整个 `candidate-001/` 目录发给同事，打开 `index.html` 即可看结果；已生成报告不需要安装 Python或插件。JSON 供后续自动流程读取。

## 用 VS Code / Cursor 插件

运行 `install-plugin.cmd --editor code`（Cursor 改为 `cursor`）；也可在扩展面板选择“从 VSIX 安装”，选 `plugins/gaussianformer-vis-1.0.25.vsix`。

打开包里的 `mesh-evaluation.code-workspace`，让插件自动使用本包 `.venv`。在命令面板选择：

- `GaussianFormer: Open Visualizer`：交互浏览原始三维 GT、预测、LiDAR、相机及 Gaussian 数据。
- `Mesh: Generate Fixed Ten-Scene Review`：依次选择 `vis/`、本轮 `identity.json`、输出父目录，自动出图并打开浏览器复核页。

详细安装、远程 SSH 和故障处理见 [使用说明](docs/USAGE.md)。本包插件是所提供 1.0.21 的项目交付副本 1.0.25；沿用相同扩展 ID，安装会更新该扩展。原扩展配置保留，Z 缩放标注改为与实际一致的 ×5。

## 当前视角：斜俯视，XYZ等比例

1.4.0 按项目要求固定 X:Y:Z=1:1:1，取消高度放大。默认俯角30°、方位角8°；俯角0°为水平看，90°为纯俯视。调整角度只旋转相机，自动缩放对XYZ统一应用，GT/PRED继续共用视角和尺度。

```powershell
.\generate.cmd --vis "D:\eval\vis" --out "D:\eval\oblique" --elevation-deg 30 --azimuth-deg 8
```

Python 可传 elevation_deg=30, azimuth_deg=8。相机参数及[1,1,1]倍率写入返回值和manifest，参与请求指纹。改变角度时使用新的输出目录。旧1.3.0图片保留当时的Z×5标注，不与本版等比例图混用。

## 当前默认：参考插件布局的五视图

1.3.0 默认 view=viewer：左起 GT、Prediction，中列上方 Camera／下方 LiDAR，右侧 Gaussian。GT/PRED 使用相同固定视角和尺度、原插件语义配色；XYZ保持等比例。Gaussian 按实际导出的 scales、wxyz rotations 和 opacity 画椭球线框，不是照片级 RGB 渲染。

默认模式需要同帧相机、Mesh GT/PRED、LiDAR、Gaussian 和 paths 元数据。当前保存的 LiDAR 仅为前方道路裁剪区域，不能生成完整360°场景。`--view scene` 保留相机投影评价卡；`--view diagnostic` 仅生成旧语义辅助图。

## 1.2.0 的相机投影视图（--view scene）

此前 0.1m 语义 BEV 网格只能看粗略类别分布，不能代替实车场景与表面重建效果。选择 --view scene 时生成10张场景评价卡：保留原照片、同视角和同尺度的真实 Mesh GT/PRED 表面采样点、类别图例及沿用原插件标定的相机投影。XYZ不作非等比拉伸；不平滑或补造网面。

scene 模式输入还须有同帧 `_image.jpg`、`_mesh_pred.npy` 与 `_sensor_param.json`。缺失时默认出图明确失败，不静默退回低信息图；只有辅助需求时显式加 `--view diagnostic`。相机投影沿用原插件标定约定，未独立复验时空配准，不用叠图替代正式精度指标。

## 交付边界

- 评价材料完整与模型质量分开：`complete + fail` 是有效的失败结果，不会自动停止研究或晋升模型。
- 未实际读图、漏图、漏判断或哈希不符，不能结项。程序核验身份、数量、字段和记录绑定；认真读图的事实仍由复核者及原始读取记录负责。
- M3 只检查这批图。正式 pillar M1 与真实高度 M2 不在本工具内计算，整体目标保持未判定。
- 版本化固定面板用于回归；全留出集广筛及动态失败集另见 [项目要求](docs/PROJECT_REQUIREMENTS.md)。
- 当前已可独立使用；BMAD-ML 活动研究没有被修改或恢复。后续接入时读取本包 `result.json` 和原证据，不另起训练控制器。

包内附输入格式、JSON 字段、AI 实际读图流程、故障说明、变更记录和校验清单。新输出采用稳定场景顺序、按 GT/PRED 联合范围、标签众数平局取最小类别 ID；属于新渲染协议，不能假设与旧脚本 PNG 哈希相同。

公开副本的来源、示例配置与验证范围见 [发布说明](PUBLICATION.md)。
