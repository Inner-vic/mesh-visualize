---
name: mesh-visualize
description: 从本项目已完成评价的 vis 产物一次调用生成固定十场景GT/Prediction/Camera/LiDAR/Gaussian五视图，支持三维相机投影评价卡，附辅助俯视图和图片清单。用于 2.5D Mesh 出图及为后续视觉分析提供证据。
---

# Mesh 原子出图能力

输入本项目固定十场景 `vis/` 和输出目录。找到此 SKILL.md 所在目录，使用其中 `.venv` 的 Python 调用同目录 `mesh_visualize.py --vis <vis目录> --out <输出目录>`；Python API 为 `mesh_visualize.generate(vis_dir, output_dir, identity=None)`。

初次缺少依赖时执行本目录 `setup.py`，后续复用 `.venv`。不要要求调用方安装或打开编辑器插件，不打开浏览器。Windows 的 `generate.cmd` 是同一入口的便捷包装。

调用方提供实际 task UID、checkpoint SHA256、代码 commit 和数据版本时，通过 `--identity <JSON>` 绑定；只有 vis 时也可出图，返回 identity_bound=false，不据此宣布正式评价完成。输入规范和接口见 [docs/ATOMIC_CAPABILITY.md](docs/ATOMIC_CAPABILITY.md)。

读取唯一 JSON 响应。成功时 artifacts.primary_images 返回10张场景卡的路径、哈希和场景映射；samples 内的comparison/diff是辅助诊断图，以及 report/manifest 路径；失败时返回 status=failed 和具体原因，修正输入后再调。相同输入输出可核验复用，不覆盖不同请求产物。

本能力只做本地确定性出图，不执行训练、推理或读图判断。后续结果分析须实际读取返回的图片，并按项目 M3 四项维度分析；生成成功不等于模型质量通过。

默认 view=viewer，需要同帧原相机、真实Mesh GT/PRED、LiDAR与Gaussian；按参考插件黑底五视图输出。--view scene 保留相机投影卡并需要原传感器标定。缺失时补齐原始产物；不能把旧低分辨率俯视图冒充实车场景效果。只有明确要辅助网格时显式传 --view diagnostic。后续评价应实际读取10张主场景卡，结合照片、语义分类和几何形态分析；高度显示×5不代表真实高度误差。

出图必须保持XYZ=1:1:1，不放大Z。可用--elevation-deg（默认30°）与--azimuth-deg（默认8°）调整三维相机，保持GT/PRED共用视角/尺度。复用须校验相机参数；新角度用新输出目录。
