# 已有点云与 Gaussian 一次出图

[返回首页](../README.md) · [接入其他功能与扩展](INTEGRATION.md) · [公开示例范围](examples/README.md) · [LPAI目录](LPAI_DATA_SOURCE.md)

`pointcloud.cmd` / `pointcloud_visualize.generate` 消费已经生成的点云评测产物，一次输出 GT、Prediction、Camera、LiDAR、Gaussian 五视图。无需 checkpoint、GPU 或启动模型；默认等间隔选择三组，可以指定编号或数量。

## 准备自己的输入

公开副本不附带源项目实车输入。先按[输入格式](INPUT_FORMAT.md)准备自己已有的 `vis/`，安装依赖后使用下面的命令或 Python 接口；不需要模型权重，也不需要为出图重新训练。

## 用同事自己的评测结果

同事要看自己模型的效果，需要提供**自己评测后导出的 vis**，不需要向渲染工具提供模型权重。已有符合格式的导出可以直接使用，不必重跑评价；只有原始点云或相机图片、没有 Prediction 时，无法展示该模型预测。

```powershell
.\pointcloud.cmd --vis "D:\eval\vis" --out "D:\eval\pointcloud-preview" --indices 0,40,80 --elevation-deg 30 --azimuth-deg 8
```

Linux/macOS 安装依赖后使用同一 Python 入口：

```bash
python3.12 setup.py
.venv/bin/python pointcloud_visualize.py --vis /data/eval/vis --out /data/preview --indices 0,40,80
```

Python 集成：

```python
from pointcloud_visualize import generate

result = generate(
    vis_dir="/data/eval/vis",
    output_dir="/data/preview",
    indices=[0, 40, 80],
    elevation_deg=30,
    azimuth_deg=8,
)
images = result["artifacts"]["primary_images"]
```

调用只负责生成图片与来源记录，实际读图分析需由人或可读图的 Agent 完成。返回值不宣称模型质量通过。

## 输入约定

同一编号的文件必须来自同一组评价导出、位于同一坐标系，保留原始配对关系。每组需要：

| 文件 | 约定 |
| --- | --- |
| `{i}_gt.pcd.bin.npy` | 有限数值 `[N,4]`：x、y、z（米）、整数语义标签 0..26 |
| `{i}_pred.pcd.bin.npy` | 同上；不要求与 GT 的点数或坐标逐点一致 |
| `{i}_image.jpg` | 同组实车相机照片 |
| `{i}_lidar.pcd.bin.npy` | 有限数值 `[N,4]`：x、y、z、强度 |
| `{i}_gaussian.pkl` | 本项目可信导出，NumPy 参数字典 means/scales/rots/opas/semantics，wxyz 旋转、正尺度、已激活 opacity [0,1] |
| `{i}_paths.json` | `scene_name`、`datalink_frame.frame_index`；帧索引允许整数或非空整数列表 |
| `{i}_sensor_param.json` | 可选，保留来源；此入口不做相机投影 |

数字前缀不要求连续。默认从全部 `*_paths.json` 按编号等间隔选择至多三组，`--limit 10` 选择至多十组，`--indices` 明确指定编号。被选组缺少模态会报错，不静默省略面板。pickle 仅接受可信项目导出。

## 视角与显示数量

- 默认俯角 30°、方位角 8°；通过上述两个角度参数调整。X:Y:Z 始终 1:1:1，不提供高度夸大选项。
- GT/PRED 共用未抽样有效点的物理范围、相机与比例；不补造连续 Mesh。LiDAR/Gaussian 各自适配面板，不能直接跨面板按像素长度比较。
- GT/PRED 过滤 ignore label=26。LiDAR 第四列为强度，强度值 26 不被语义过滤。
- 默认每组每类点云最多显示 200,000 点。超过时按输入有效行原顺序等步长抽样，图片和 manifest 写明实际显示数与步长；细小结构可能遗漏。`--max-points 1000000` 可提高上限，但会增加绘图时间。
- 所有输入只读；GT/PRED 不做平滑或拟合。相机保持完整画幅，Gaussian 展示导出参数的椭球线框，不生成照片级新视角。

## 输出与正式评价的区别

输出 `index.html`、`pointcloud-views/*.png`、`pointcloud-manifest.json`，记录每组源文件和图片 SHA256、视角、过滤、抽样和 Gaussian 显示统计。请求参数或输入改变时应使用新目录，工具拒绝用新结果覆盖旧结果。

这是任意已配对点云导出的预览入口，`formal_evaluation=false`。本项目原有 `generate.cmd` / `mesh_visualize.generate` 仍按固定十场景、第7帧和连续 Mesh 协议工作，并沿用原逐图复核流程。点云预览不替代该正式 M3 口径，也不输出 M1/M2 结论。

## 准备可分享的小型用例

工具包提供仅使用标准库的准备脚本，在能读取原始 vis 的宿主执行：

```bash
python prepare_pointcloud_demo.py --vis /data/eval/vis --out /data/pointcloud-demo-inputs --indices 0,40,80
```

目标必须不存在。输出目录与同名 ZIP 包含配套输入和 `preview-provenance.json`。该脚本仅处理 C-order 小端 float32 的 GT/PRED；只过滤 ignore 行，不做抽样。请按项目内部数据权限分享，不把整份业务数据集或凭据提交到仓库。
