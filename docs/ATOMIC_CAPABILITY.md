# mesh-visualize：项目原子出图能力

组合到其他业务流程、返回值消费及后续扩展见[接入与扩展](INTEGRATION.md)。

已有点云与Gaussian一次出图使用 `pointcloud_visualize.generate` / `pointcloud.cmd`，完整参数、返回值和内置真实输入试跑见[点云入口](POINTCLOUD_USAGE.md)。下文描述原固定十场景Mesh评价能力。

一次调用接收已完成评价的 vis/，默认输出10张黑底五视图（GT、Prediction、Camera、LiDAR、Gaussian），附20张语义俯视辅助诊断图、HTML预览、逐图元数据和SHA256。无需插件或浏览器参与执行。

## 一次调用

环境安装一次后，Windows：

```powershell
.\generate.cmd --vis "D:\eval\vis" --out "D:\eval\visuals"
```

Python 调用（调用进程使用本包依赖环境，并从本包导入）：

```python
from mesh_visualize import generate
result = generate(vis_dir="/data/eval/vis", output_dir="/data/eval/visuals")
images = result["artifacts"]["samples"]
```

跨进程调用使用 `.venv` 的 Python 执行 `mesh_visualize.py --vis ... --out ...`。stdout 只有一个 JSON 对象，成功退出 0，失败退出 2；Python API 失败抛出具体异常。

## 视图选择

默认 view="viewer"：参考原插件的固定视角五视图。CLI 无需新增参数；GT/PRED 共用视角和尺度，Gaussian 用导出的中心、尺度、旋转及 opacity。需要相机、Mesh GT/PRED、LiDAR、Gaussian 和路径元数据，输入缺失时明确失败。Gaussian pickle 必须来自可信评价产物。

view="scene"：相机原图、GT/PRED三维点和投影场景卡，需要原相机标定。

view="diagnostic"：旧版20张语义俯视辅助图。

CLI 对应 --view viewer|scene|diagnostic。返回 artifacts.primary_images 是十张主图；five_view_count=10 标识默认五视图。实际输入仍固定十场景，所有额外模态文件均绑定请求指纹和来源哈希。

## 输入

vis_dir：本项目数据 1.0.10 固定十场景、第 7 帧的目录；每组含语义 GT/PRED、源 mesh GT、paths.json、原相机 _image.jpg、_mesh_pred.npy、_sensor_param.json。使用包内 fixed10-scenes.json 核验，不在调用中重新选样本。

output_dir：新目录、空目录或此能力相同输入的既有输出。

identity：可选，实际 task_uid/checkpoint_sha256/code_commit/dataset_version 对象；CLI 对应 --identity JSON文件。未提供时正常出图，identity_bound=false，不能 finalize 为正式评价。已提供则核验字段并绑定，可供后续真实视觉复核使用。

## 返回

schema=mesh-visualize.result/v1，status=generated，包含 artifacts.report、manifest、review_template 以及十条 samples。每条 sample 有 index、scene_name、frame_index 和 comparison/diff 的绝对路径与 SHA256。调用者可以把这些图片直接交给视觉分析步骤。

artifacts.primary_images 是10张默认场景卡，每条含路径、SHA256和场景名；artifacts.samples 中 comparison/diff 是20张辅助图。view="diagnostic" 可显式仅生成旧版辅助图。

request_fingerprint 绑定工具版本、视图模式、协议、任务身份、相机/标定/真实Mesh和语义输入文件哈希。相同请求再次调用核验既有图片并返回 reused=true；不同输入不会覆盖旧输出。所有图及 manifest 在临时目录通过后才整体发布，失败不发布一份看似完成的产物。

CLI 失败返回 status=failed/error。输入缺失、错帧、源 GT 不符或输出冲突时，由调用方修正对应材料。所有结果均 review_performed_by_this_call=false、model_quality_verdict=null；该能力生成视觉证据，质量判断由后续真实读图步骤执行。

## 与原工具包的关系

mesh_visualize.generate 是流程集成的唯一推荐原子入口，底层复用原固定十图渲染。已有浏览器复核、finalize/check 和三维插件仍可选用。包根 SKILL.md 提供 Agent 发现入口；保持整个目录完整即可使用，不需要安装 BMAD-ML 核心或连接平台。

## 1.4.0 等比例斜俯视

静态主图固定XYZ倍率为1:1:1，不提供高度夸张开关。默认elevation_deg=30、azimuth_deg=8；俯角相对水平面向下看（0°侧视，90°纯俯视），方位0°沿车辆+X方向看。CLI使用--elevation-deg/--azimuth-deg，Python同名下划线参数。两参数适用于viewer和scene的三维视图，原相机照片及标定投影保持原数据。

GT/PRED始终共用相机、拟合范围和统一像素比例。LiDAR/Gaussian较小面板独立适配画幅，但每个面板内部XYZ始终等比例。参数和axis_scale_xyz=[1,1,1]写入来源记录并参与复用判断；改角度应使用新输出目录。交互插件原有的高度放大选项不参与静态输出。
