# 输入规范

本工具消费远端 `eval.py --vis-occ` 已生成的目录。它不提交远端任务，也不下载 checkpoint。先将评价产物解压到本地，不要把 ZIP 路径当 vis 目录传入。

每个数字编号 `{i}` 必须包含：

| 文件 | 要求 |
|---|---|
| `{i}_gt.pcd.bin.npy` | 有限数值 `[N,4]`，列为 x,y,z,label |
| `{i}_pred.pcd.bin.npy` | 有限数值 `[N,4]`，与 GT 位于相同物理坐标系；点数和采样坐标可以不同 |
| `{i}_mesh_gt.npy` | 原始 GT `[N,5]`，与固定清单该场景的源 GT SHA256 相同 |
| `{i}_paths.json` | 包含 `scene_name`、`datalink_frame.frame_index=7` |

必须恰好十组、十个不同固定场景，整组 GT 覆盖八个关注类。编号与固定清单顺序可以不同；程序按元数据匹配，并统一按清单顺序输出。额外未配对的点云不忽略。

`fixed10-scenes.json` 保存协议、数据版本、场景集合及源 GT 哈希。它属于项目版本控制材料；替换数据、帧或样本需正式创建新协议和验证适配，不能为了通过检查直接修改哈希。

三维插件可另外显示 `{i}_lidar.pcd.bin.npy`、`{i}_image.jpg` 或 cam0/cam1 图像、`{i}_gaussian.pkl`。缺少这些扩展数据时，固定十图渲染仍可运行。Gaussian pickle 应来自可信的本项目评价产物。

identity.json 必须提供本轮真实 `task_uid`、`checkpoint_sha256`、`code_commit`、`dataset_version=1.0.10`。程序检查必填、哈希格式和协议版本，不会访问平台核实 UID 或执行 checkpoint。身份真实性应来自原评价 manifest/任务回执；不要填写示例占位值。

单位是米、label 为 0..26 的整数；BEV 分辨率固定 0.1m。只有八个关注类使用专用颜色，其余有效标签灰色，空网格黑色。差异图按标签比较，避免两个灰色的不同类别被误判相同。

实测历史连续 mesh 产物中 GT 与 PRED 点数/坐标可不同；工具不会要求逐点对应。manifest 记录两边点数和 query_coordinates_aligned。共用物理视野用于视觉比较，BEV 差异不是严格逐点精度；不得从此图推导真实高度误差。

1.2.0 默认主视图还必须有 `{i}_image.jpg`、`{i}_mesh_pred.npy` 和 `{i}_sensor_param.json`。图像须与标定原始分辨率相同，标定 scene_name 须与 paths 元数据相同；支持原插件的 pinhole + equidistant 模型。缺少任何上下文不会自动退回辅助网格；显式 --view diagnostic 才采用旧辅助输出。投影的相机外参及去畸变约定沿用插件，未经独立重标定验证。

1.3.0 默认 viewer 模式还使用 `{i}_lidar.pcd.bin.npy` 和 `{i}_gaussian.pkl`。Gaussian为可信来源导出的NumPy参数字典（means/scales/rots/opas/semantics），opacity须已激活为[0,1]、旋转约定wxyz。此模式不投影到相机，不要求sensor_param；场景图像按paths的同一编号绑定。scene模式才需要原标定。
