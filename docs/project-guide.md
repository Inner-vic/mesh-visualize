# 使用指南

已有点云 / LiDAR / Gaussian 导出请先看[点云一次出图](POINTCLOUD_USAGE.md)，公开副本使用调用方自己的输入。下文保留固定十场景 Mesh 流程。

[返回首页](../README.md) · [文档目录](README.md) · [公开示例范围](examples/README.md)

本工具将本项目已完成的远端评价产物转为静态图和离线复核材料。以下命令在仓库根目录执行；图中含有的真实数据不随源码提供，使用自己的 `vis/` 前先读[输入规范](INPUT_FORMAT.md)。

## 1. 安装一次

Windows x64 推荐 Python 3.12：

```powershell
git clone https://github.com/Inner-vic/mesh-visualize.git
cd mesh-visualize
py -3.12 setup.py
.\mesh.cmd doctor
```

依赖固定为 NumPy/Pillow，安装在当前目录 `.venv`。源码克隆首次使用已有 pip 配置联网安装；预备了匹配 wheel 的 Windows Python 3.12 x64 分发包可运行 `setup.cmd --offline`。源码不附 wheel 或 VSIX。

Linux/macOS 执行 `python3 setup.py`，随后使用 `.venv/bin/python mesh_visualize.py ...`、`.venv/bin/python mesh_eval.py ...`；五视图需要系统中文字体。Windows 使用微软雅黑，macOS 苹方，Linux 使用 Noto Sans CJK。当前已记录实测范围见[交付验证](VALIDATION.md)，不以路径兼容推定所有平台均已实测。

## 2. 一次调用生成真实图片

先取得符合固定协议的已完成评测vis，而非直接指向原始数据集。[数据来源说明](LPAI_DATA_SOURCE.md)列出已实际核实的LPAI共享卷目录及插件查看步骤；其中81组点云导出缺少Mesh、帧号也不同，不能直接用于本节固定十图命令。

```powershell
.\mesh.cmd inspect --vis "D:\eval\vis"
.\generate.cmd --vis "D:\eval\vis" --out "D:\eval\visuals"
```

输入协议固定为数据 `1.0.10` 的十场景、第7帧；默认模式需要每帧的语义 GT/PRED、Mesh GT/PRED、相机图像、LiDAR、Gaussian 和路径元数据，具体文件见[输入规范](INPUT_FORMAT.md)。缺少必要模态会明确失败，不会自动替换场景或重跑推理。

输出主要包括：

| 路径 | 内容 |
| --- | --- |
| `five-views/` | 10张 GT / Prediction / Camera / LiDAR / Gaussian 主图 |
| `images/` | 20张语义俯视对照与差异辅助图 |
| `index.html` | 可直接打开的离线逐图复核页 |
| `run-manifest.json` | 场景、输入摘要、图像摘要及视角等来源记录 |
| `capability-result.json` | 原子调用结构化返回 |
| `review-template.json` | 后续实际读图填写的复核模板 |

只有 `vis/` 也能出图；未绑定正式任务身份的输出不能 `finalize` 为正式评价。同一输入和参数再次调用会核验并复用；输入或参数变更时使用新目录，保留旧产物。

## 3. 调整视角，保持等比例

```powershell
.\generate.cmd --vis "D:\eval\vis" --out "D:\eval\view-45" --elevation-deg 45 --azimuth-deg 8
```

默认俯角30°、方位角8°。俯角0°为水平看，90°为纯俯视；方位角0°沿车辆+X方向看。静态 XYZ 固定1:1:1，GT/PRED共用相机、范围和尺度；LiDAR/Gaussian面板各自统一适配画幅。相机参数写入清单和请求指纹，不能用改角度的请求覆盖旧目录。

| 视图参数 | 内容 |
| --- | --- |
| `--view viewer`（默认） | 十张黑底五视图，效果见[公开示例范围](examples/README.md) |
| `--view scene` | 相机原图、GT/PRED三维点及相机投影卡；还需原相机标定 |
| `--view diagnostic` | 仅生成旧版语义俯视辅助图 |

## 4. 用 Python / Agent 集成

使用本包依赖环境，并确保能从本包导入：

```python
from mesh_visualize import generate

result = generate(
    vis_dir="/data/eval/vis",
    output_dir="/data/eval/visuals",
    elevation_deg=30,
    azimuth_deg=8,
)
primary_images = result["artifacts"]["primary_images"]
```

跨进程可用 `.venv` 中的 Python 执行 `mesh_visualize.py --vis ... --out ...`。成功 stdout 为一个 JSON 对象；详细返回、错误与复用语义见[原子接口](ATOMIC_CAPABILITY.md)。Agent 使用根目录 [SKILL.md](../SKILL.md) 与 [AGENTS.md](../AGENTS.md)，本工具不附 API Key，也不自动调用外部模型。

## 5. 正式复核与交付

准备真实的任务 UID、checkpoint SHA256、代码 commit 和数据版本，参考 [identity.example.json](../identity.example.json) 填写身份文件，然后生成一份新输出：

```powershell
.\generate.cmd --vis "D:\eval\vis" --identity ".\identity.json" --out ".\outputs\candidate-001"
```

打开 `index.html`，实际查看全部10张主图，按需参考辅助图，填写分类、边界、形状、匹配、结论及整组总结，导出 `visual-review.json`。人工与 Agent 的读取记录要求见[使用与排错](USAGE.md)。

```powershell
.\mesh.cmd finalize --run ".\outputs\candidate-001" --review "C:\Users\你的用户名\Downloads\visual-review.json"
.\mesh.cmd check --run ".\outputs\candidate-001"
```

交付整个输出目录，接收方无需安装 Python 就能查看 HTML。材料完整和模型质量分别记录，`complete + fail` 是有效失败结果；本工具不计算正式 M1/M2 或宣布研究整体目标达成。

## 6. 可选：VS Code / Cursor 插件

不安装插件也可完成原子出图和离线复核。需要原有三维交互时：

1. 源码用户先执行 `python build_release.py --out dist`，解压生成的 ZIP；分发包用户直接使用已解压目录。
2. 在解压目录先运行 `setup.cmd`，再运行 `install-plugin.cmd --editor code`，Cursor 改为 `cursor`。也可从扩展面板选择“从 VSIX 安装”，选 `plugins/gaussianformer-vis-1.0.26.vsix`。
3. 打开包内 `mesh-evaluation.code-workspace`，插件使用本包 `.venv`。沿用相同扩展 ID，安装会更新原 GaussianFormer Visualizer。

| 插件命令 | 作用 |
| --- | --- |
| `GaussianFormer: Open Visualizer` | 原有 GT/PRED、LiDAR、相机、Gaussian 三维交互 |
| `Mesh: Generate Fixed Ten-Scene Review` | 选择输入、身份和输出父目录，调用同版原子出图入口 |

交互浏览器原有的高度放大选项不参与静态导出；评价图始终XYZ等比例。Remote SSH 中插件与 Python 必须在同一扩展宿主，使用远端路径和对应平台依赖。

## 7. DEMO、验证与构建

没有真实输入时可运行 `demo.cmd`，体验合成的语义诊断图和复核流程；它不生成新的真实实车五视图，也不代表模型质量。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check vendor/gaussianformer-vis/extension.js
node --check vendor/gaussianformer-vis/media/panel.js
python build_release.py --out dist
```

GitHub Actions 仅做源码与完整性检查。完整出图和分发由维护者在自己的环境执行；原本地发布工具需要未公开的实车样例，不能直接视为公开副本的一键发布入口。详见[公开构建说明](RELEASE.md)。

进一步阅读：[输入格式](INPUT_FORMAT.md) · [输出字段](OUTPUT_FORMAT.md) · [项目特殊要求](PROJECT_REQUIREMENTS.md) · [排错](USAGE.md) · [来源与许可](../THIRD_PARTY_NOTICES.md)。

自动 CI 的单元检查覆盖输入、等比例投影和复核协议；依赖系统中文字体的完整出图测试由 `local_release.py` 在维护者环境执行。
