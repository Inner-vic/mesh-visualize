# 使用与排错

已有点云 / LiDAR / Gaussian 导出请先看[点云一次出图](POINTCLOUD_USAGE.md)，含可重新渲染的三组真实输入。下文保留固定十场景 Mesh 流程。

[返回首页](../README.md) · [完整使用指南](project-guide.md) · [公开示例范围](examples/README.md)

## 环境和入口

Windows x64 推荐 Python 3.12；已在 Windows Python 3.12 实测。包内离线 wheel 只覆盖这一组合。Python 3.10—3.13 可通过联网 setup 安装固定依赖；Linux/macOS 路径支持由代码提供，尚未在这些系统实测。

Windows 双击 setup.cmd，或 `py -3.12 setup.py --offline`。联网安装保留系统/企业已有 pip 镜像配置。Linux/macOS 执行 `python3 setup.py`，后续以 `.venv/bin/python mesh_eval.py ...` 替代 `mesh.cmd ...`。安装只写本包 `.venv`。

`mesh.cmd doctor` 检查当前环境。所有输出目录必须新建或为空，避免覆盖原证据。路径中有空格时加引号。首次打开浏览器报告可用 `--open`，之后直接双击 index.html。

## 插件安装

插件 VSIX 无需 npm 或编译。源码用户先按[使用指南](project-guide.md)构建并解压分发包；分发包用户可直接安装。先运行 setup，再安装插件并打开本包 `.code-workspace`。插件从打开的工具包工作区寻找 `.venv`；如果只打开了原模型代码目录，请在设置 `gaussianVis.pythonPath` 中填本包 `.venv/Scripts/python.exe` 的实际绝对路径。Linux 对应 `.venv/bin/python`。

VS Code Remote SSH 中，插件与 Python 必须安装在同一个远端扩展宿主；远端安装依赖、路径使用远端路径。Windows 离线 wheel 不能给 Linux 宿主安装。需要另一平台的离线包可在联网机器按相同 requirements 下载对应 wheel。

命令行不可用时，在扩展面板 `…` → `从 VSIX 安装`。已有同 ID 1.0.21 会更新成项目副本 1.0.26；卸载/重装原 VSIX 可回退。无需安装插件也可通过 CLI 和浏览器完成 M3。

## 浏览器复核与 JSON

默认十个样本，逐张实际查看五视图中的GT、Prediction、Camera、LiDAR、Gaussian；view=scene时查看原照片、GT/PRED三维点和相机投影。辅助BEV按需展开。旧 diagnostic 模式仍查看每对俯视对照图和差异图；填四项具体分析，选结论，勾选实际检查。补齐姓名和整组总结后导出 JSON。草稿保存在本机浏览器，不能代替正式导出；刷新或换电脑前建议导出。

`finalize` 将报告、图像和评价身份绑定并生成 result.json，同时更新 index.html。最终结果不允许原地二次 finalize；修订需保留原目录并创建新的一轮输出。`check` 会重验图像、协议、报告和结果之间的绑定。目录搬到另一台机器后仍可运行 check，不依赖原输入绝对路径。

## 给 AI 使用

把本包作为工作区，并指向本轮输出；让 AI 遵循 AGENTS.md。AI 必须用可读图片的工具逐张检查10张 primary_images 场景卡；旧 diagnostic 模式检查20张 comparison/diff，填写 review-template.json，设置 reviewer_type=agent，并在 read_evidence 为每张主图记录 image_path、image_sha256 与实际工具/调用 receipt_ref。先读图再写判断，不能用网格数字或旧结论代替。

本包不附 API Key、不自动调用外部模型。读取回执引用用于追溯；软件核验其字段与图像哈希覆盖，不能仅凭一个字符串验证外部平台回执真实性。审议方仍需保留并核实原读取证据。人工页面导出使用 reviewer_type=human。

## 返回码和常见问题

| 情况 | 处理 |
|---|---|
| 退出 0 | 当前命令成功；render 成功仅表示等待复核，check 成功才表示本轮材料结项 |
| check 退出 3 | 已出图但复核尚未 finalize；继续实际读图 |
| 退出 2 | 输入、依赖、身份或证据核验失败，按 ERROR 修正，不强行跳过 |
| NumPy / PIL 缺失 | 在包目录重跑 setup.cmd，用 mesh.cmd 而非另一份系统 Python |
| 源 GT 哈希不同 | 核对数据版本和场景；不要改清单伪装相同协议 |
| 缺少 paths 或 mesh_gt | 从原评价任务补齐相应产物，本工具不会自动重跑任务 |
| 输出目录非空 | 选择新目录，保留此前记录 |
| JSON 下载到了别处 | finalize 的 --review 指向浏览器实际下载文件 |
| 图被改过，check 报错 | 从原输出恢复，或使用原输入创建新一轮报告 |
| 插件 Python 无法启动 | 打开工具包工作区或在设置里指定其虚拟环境 Python |
| 观察到 M3 fail | 保留失败证据；由项目规则决定改进方案，不等于工具运行失败 |

分享时发送整个输出目录；静态 HTML 引用 images 相对路径，不能只发 index.html。MANIFEST.sha256.json 校验发布包文件；它用于完整性核对，不是数字签名。

viewer / scene 模式需要系统中文字体：Windows 使用微软雅黑，macOS 苹方，Linux 可安装 Noto Sans CJK；不随包再分发商业字体。旧 BEV 测试的通过只证明输入/出图链路，并不证明实车可解释性；本版另保留实际场景卡的人工图片检查记录。

读图回执的 image_path 使用相对本轮目录的路径，例如 scene-views/0_scene.png；capability 返回的绝对路径用于实际打开图片。receipt_ref 保留真实读取工具或模型调用的原始引用。

1.3.0：默认主图改为参考插件布局的五视图；一次调用不需要打开插件。LiDAR是原产物保存的道路ROI；Gaussian基于实际中心、尺度、旋转、语义argmax和opacity绘制线框，不含RGB新视角重建。view=scene可切回此前相机投影卡。

## 1.4.0 等比例斜俯视

静态主图固定XYZ倍率为1:1:1，不提供高度夸张开关。默认elevation_deg=30、azimuth_deg=8；俯角相对水平面向下看（0°侧视，90°纯俯视），方位0°沿车辆+X方向看。CLI使用--elevation-deg/--azimuth-deg，Python同名下划线参数。两参数适用于viewer和scene的三维视图，原相机照片及标定投影保持原数据。

GT/PRED始终共用相机、拟合范围和统一像素比例。LiDAR/Gaussian较小面板独立适配画幅，但每个面板内部XYZ始终等比例。参数和axis_scale_xyz=[1,1,1]写入来源记录并参与复用判断；改角度应使用新输出目录。交互插件原有的高度放大选项不参与静态输出。
