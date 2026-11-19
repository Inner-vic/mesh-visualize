# 来源说明

GaussianFormer Visualizer 来源于用户提供的 `gaussianformer.gaussianformer-vis-1.0.21`。本包保留原作者/发布者 gaussianformer 名称以及原 README，项目修订见 CHANGELOG.md。扩展中的 Three.js 及其既有声明保持原样。提供目录未附完整独立 LICENSE；本包用于项目同事内部同步，不为原插件或其第三方组成部分新增或声称开源许可。

NumPy 与 Pillow wheel 保持上游发布文件原字节，wheel 内含各自许可和第三方声明。requirements.txt 固定版本，MANIFEST.sha256.json 登记随包文件摘要。工具包无 API Key、平台凭据或 checkpoint；历史场景PNG的范围见下文。

## 示例图片

docs/examples/images/ 中的10张PNG来自本项目历史实车评价产物，按用户要求随私有仓库展示输出效果。来源与逐图摘要见 docs/examples/samples.json；不为原采集图像或业务数据另授开源许可。仓库没有附完整原始数据集、模型权重或平台凭据。新增紧凑点云用例的范围见下文。

三图读图用例ZIP仅复用上述PNG及说明/模板，不包含原始vis、传感器数组或模型参数。

## 可重新渲染的点云用例

`docs/examples/pointcloud-inputs.zip` 及 `pointcloud-views/` 来自用户授权的LPAI共享卷点云导出，选择编号0、40、80。GT/PRED只过滤ignore label=26，其他有效行字节及顺序不变；相机、LiDAR、Gaussian和配套元数据保持原字节。逐文件摘要和过滤计数随ZIP内 `preview-provenance.json` 提供，图片来源与参数见同目录说明。这些业务输入和图片仅用于本项目私有仓库内部演示，不另授开源许可。
