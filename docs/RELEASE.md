# 公开源码的检查与构建

[返回首页](../README.md)

GitHub Actions 只运行轻量源码与完整性检查，不自动生成分发包。公开仓库没有附带源项目的实车样例或预编译 Release 资产。

维护者可在自己的环境运行 `python -m unittest discover -s tests -v`；完整渲染测试需要 NumPy、Pillow 和系统中文字体。插件使用 `node --check` 检查。普通使用无需运行这些维护检查。

`python build_release.py --out dist` 可构建源码分发包；Windows 离线分发需自行准备匹配的固定依赖 wheel。源项目的 `local_release.py` 还要求其真实样例输入进行解压后出图验证，这些数据未随公开源码提供，因此本副本不宣称可直接完成原环境的一键发布验收。

运行工具不表示完成正式逐图复核，也不能作为模型质量结论。公开同步范围与来源见[公开说明](../PUBLICATION.md)。
