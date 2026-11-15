# Mesh Visualize

将已完成评测的 `vis/` 数据转换为可离线查看的 2.5D Mesh 评价图和 HTML 复核报告，支持 GT/Prediction 对照、同帧相机与 LiDAR 展示，以及 Gaussian 可视化。

这是评测结果的本地后处理工具，不执行模型训练或推理。当前固定协议为指定十场景的第 7 帧，场景清单见 [fixed10-scenes.json](fixed10-scenes.json)；其他数据需先适配输入协议。

## 输入与输出

| 项目 | 内容 |
| --- | --- |
| 输入 | 完整 `vis/`，包含同帧 Mesh GT/Prediction、相机、LiDAR、Gaussian 和元数据 |
| 可选身份 | 实际任务、检查点哈希、代码提交和数据版本；正式复核应提供 |
| 主要输出 | 10 张 GT/Prediction/Camera/LiDAR/Gaussian 五视图评价卡 |
| 辅助输出 | 20 张俯视诊断图、HTML 复核页、图像元数据和 SHA-256 |
| 复核结果 | `finalize` 后生成绑定本轮图像与判断的 `result.json` |

静态评价图固定 X:Y:Z 为 1:1:1，GT/Prediction 共用尺度和视角。默认俯角 30°、方位角 8°。Gaussian 展示为依据导出参数绘制的椭球线框。

## 快速体验

已实测的环境为 Windows x64、Python 3.12；依赖固定在 [requirements.txt](requirements.txt)，另需系统中文字体。

```powershell
git clone https://github.com/Inner-vic/mesh-visualize.git
cd mesh-visualize
py -3.12 setup.py
.\demo.cmd
```

安装器在项目内创建 `.venv` 并安装 NumPy、Pillow。源码克隆首次安装需访问包源；仓库不附 wheel 缓存。演示使用模拟数据，无需 GPU 或真实评测数据，结果不代表模型效果。

Linux/macOS 提供 `python3 setup.py` 和 `.venv/bin/python mesh_eval.py ...` 路径，但尚未在这些系统实测。

## 处理真实评测结果

先按[输入格式](docs/INPUT_FORMAT.md)准备数据。复制 [identity.example.json](identity.example.json) 为本轮 `identity.json`，填写实际身份；以下路径替换为自己的输入和全新输出目录：

```powershell
.\mesh.cmd inspect --vis "D:\eval\vis"
.\generate.cmd --vis "D:\eval\vis" --identity ".\identity.json" --out "D:\eval\review-001"
```

打开输出目录的 `index.html`，逐张查看全部十张主要评价卡，填写分类、边界、形状、匹配、结论及总结，导出 `visual-review.json`。然后绑定并复核：

```powershell
.\mesh.cmd finalize --run "D:\eval\review-001" --review "D:\reviews\visual-review.json"
.\mesh.cmd check --run "D:\eval\review-001"
```

每轮使用独立输出目录，保留原始图片和判断。资料完整与模型质量分别判断：复核完成且质量不通过，也是有效结果。AI 复核还需逐图读取证据，规则见 [AGENTS.md](AGENTS.md)。

## Python 与插件入口

使用本项目的依赖环境可直接调用：

```python
from mesh_visualize import generate

result = generate(vis_dir="D:/eval/vis", output_dir="D:/eval/review-002")
```

调用参数和返回字段见[原子接口](docs/ATOMIC_CAPABILITY.md)。该调用负责出图，正式身份绑定与逐图复核仍按上面的流程完成。

仓库也包含 VS Code/Cursor 插件源码。需要插件时先构建分发包：

```powershell
python build_release.py --out dist
```

解压生成的 ZIP 后，从编辑器的“从 VSIX 安装”选择包内插件。CLI 和浏览器复核不依赖插件；安装及显示选项见[使用说明](docs/USAGE.md)。

## 验证与限制

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
```

GitHub 的 [Source checks](.github/workflows/source-checks.yml) 执行源码检查，不自动构建分发包。源码同步时的测试范围见[发布说明](PUBLICATION.md)。

本工具只评价这批可视化结果；不计算完整模型精度或真实高度验收指标。当前 LiDAR 产物为前方道路裁剪区域，相机投影也不能替代独立标定和正式精度评测。第三方来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
