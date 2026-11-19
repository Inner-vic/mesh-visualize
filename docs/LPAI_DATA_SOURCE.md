# 已有评测产物的来源

[返回首页](../README.md) · [点云调用](POINTCLOUD_USAGE.md)

可视化工具消费已经生成的评测输出，不申请 GPU、不提交平台任务。使用者负责从自己的获准数据卷或结果目录取得同版 GT、Prediction、Camera、LiDAR、Gaussian 与元数据，保持原身份和摘要。

公开副本不提供源项目的账号、数据卷标识、实车样例或下载授权；示例路径为 `/data/eval/vis`。不同模型或导出格式需满足[输入契约](INPUT_FORMAT.md)与[扩展边界](INTEGRATION.md)，不能通过构造假的 Mesh 数组替代缺失的实际输出。
