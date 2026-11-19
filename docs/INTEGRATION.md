# 接入其他功能与扩展约定

[返回首页](../README.md) · [点云输入与操作](POINTCLOUD_USAGE.md) · [固定十场景接口](ATOMIC_CAPABILITY.md)

本仓库由发布方维护，供同事把可视化作为一个独立步骤，接入评测流水线、Agent、结果分析或报告功能。调用方交入已有评测产物，取得图片和来源信息，再继续自己的业务流程。公开副本的合成测试用于协议自检，实际业务输入由调用方提供。

当前输入格式、语义类别和五视图实现来自2.5D Mesh项目。接入其他功能可以复用现有接口；接入不同数据格式或新模态时，需要明确增加适配实现和验证，不能仅凭可调用就声称已经支持。

## 在流程中放在哪里

上游评测产物 → 调用方的数据获取/格式适配 → 本仓库出图 → 调用方的分析、报告或展示。

| 层次 | 职责 |
| --- | --- |
| 上游业务 | 产生或取回GT/PRED、相机、LiDAR、Gaussian及配套元数据，保证同组配对、坐标系和单位正确 |
| 数据适配 | 将其他来源转换为已支持的vis格式，保存原始输入及转换记录；LPAI路径只是已有案例 |
| 可视化能力 | 校验选中输入，按参数绘制，输出PNG、HTML和带摘要的manifest |
| 下游业务 | 消费图片和manifest，执行视觉分析、报告组织、文件传输或平台展示 |

本能力无需参与上游任务调度。下游模型调用、评价策略和报告模板由调用方组织；生成图片成功与模型质量结论分别处理。

## 最小接入：一次调用后消费结果

Python调用在已安装本包依赖且可导入本包源码的环境中执行。当前仓库提供源码/分发包，不提供可直接 `pip install mesh-visualize` 的注册发行包。

```python
from pointcloud_visualize import generate

def render_for_workflow(vis_dir, output_dir, sample_ids):
    result = generate(
        vis_dir=vis_dir,
        output_dir=output_dir,
        indices=sample_ids,
        max_points=200_000,
        elevation_deg=30,
        azimuth_deg=8,
    )
    # 返回给上层已有的分析、报告或展示功能。
    return {
        "images": result["artifacts"]["primary_images"],
        "manifest": result["artifacts"]["manifest"],
        "preview": result["artifacts"]["report"],
        "reused": result["reused"],
    }
```

非Python功能可在自己的进程中执行本包Python入口，无需模拟插件界面：

```bash
.venv/bin/python pointcloud_visualize.py --vis /data/eval/vis --out /data/jobs/run-001/visuals --indices 0,40,80
```

Windows可使用 `.venv\Scripts\python.exe pointcloud_visualize.py ...` 或 `pointcloud.cmd ...`。跨进程调用建议设置 `PYTHONUTF8=1` 并按UTF-8读取输出。成功时退出码为0，stdout为结果JSON；非零退出视为失败，保留stdout/stderr供排查，不能假定所有失败都能解析为结果JSON。Python接口失败时抛出异常。

### 当前点云返回约定

| 字段 | 下游如何使用 |
| --- | --- |
| `schema` | 当前为 `mesh-visualize.pointcloud-result/v1`，按此识别返回格式 |
| `status` / `reused` | 成功为 `generated`；`reused`表示复用同输入和参数的已核验图片 |
| `selection` / `display_camera` | 实际选中编号与视角，XYZ倍率固定为1:1:1 |
| `artifacts.primary_images` | 图片列表，每项包含 `source_index`、绝对路径 `path`、`sha256` |
| `artifacts.manifest` | 来源文件摘要、过滤/抽样、各模态显示统计等详细记录 |
| `artifacts.report` | 本地HTML预览入口，可供调用方展示或打包 |
| `formal_evaluation` / `model_quality_verdict` | 此入口固定为false/null；需要质量结论时，由后续实际读图步骤产生 |

返回路径属于执行出图的宿主。远端运行时，下游需能够访问同一文件系统，或由调用方通过已有产物通道传输图片及manifest；本函数不会自动上传或返回公网URL。分析结果应绑定对应图片摘要，避免误用另一轮输出。

## 已有参数与需要开发的扩展

| 需求 | 当前接入方式或扩展位置 |
| --- | --- |
| 换评测任务、存储位置、样本 | 调用方传入 `vis_dir`、`output_dir`、`indices` 或 `limit`，无需固定LPAI路径 |
| 调整观察角度、显示数量 | 使用 `elevation_deg`、`azimuth_deg`、`max_points`；不改变真实XYZ倍率 |
| 接分析、报告、Agent或其他平台 | 在调用方消费返回图片与manifest，现有出图入口无需承担下游业务 |
| 新的数据来源，内容符合现有约定 | 在上游准备配对vis后直接调用；先做小样本验证 |
| 不同文件格式、标签或Gaussian导出约定 | 新增数据适配实现并记录映射/转换；现有标签范围、配色及Gaussian校验不会自动改变 |
| 新面板、仅显示部分模态、新布局 | 需要新增渲染实现，可参考 `pointcloud_visualize.py`、`five_view.py`、`view_camera.py`；当前入口要求完整五视图输入 |
| 新项目评价协议 | 独立声明样本选择、身份、复核与判定要求；不能直接套用现有固定十场景的正式结论 |

现有入口支持参数化调用；目前没有动态适配器注册、任意面板配置或HTTP服务接口。上述需要开发的项是维护时的扩展位置，不是已交付的配置开关。

## 扩展与兼容原则

保留现有 `generate` 调用及已发布返回字段的含义。新增来源适配与下游业务尽量放在各自模块；新视图通过明确的新入口或有版本的输出约定提供。破坏性变化需升级对应版本并说明迁移方法，调用方应固定所使用的仓库提交或发布包。

数据转换应保留原始输入和来源关系，说明标签映射、坐标变换、过滤及抽样。不要为了符合入口而补造缺失预测或Mesh。新适配需要核对输入语义、实际查看生成图，并验证旧入口继续可用；不能只验证文件存在。

点云预览与固定十场景Mesh评价使用不同入口和结果schema。仅当业务明确执行原项目正式评价时，才适用固定十场景及其复核要求，详见[原子评价接口](ATOMIC_CAPABILITY.md)。其他流程可以独立组合点云出图能力，不依赖该评价流程。

## 接入资料

- [公开示例范围](examples/README.md)：首次试跑和验证输入/输出，不作为调用方业务数据默认值。
- [点云使用说明](POINTCLOUD_USAGE.md)：输入约定、参数、过滤与抽样行为。
- [验证范围](VALIDATION.md)：已验证的环境和实际行为；其他平台或新增适配需另行验证。
