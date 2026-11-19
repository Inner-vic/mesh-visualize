# 输出数据接口

`run-manifest.json`（mesh-m3-run/v1）记录版本、是否 demo、任务/模型/代码身份、协议摘要、十个样本映射、输入文件 SHA256、每对 bounds_xy、20 张图片的相对路径与 SHA256、八类 GT 支持。BEV 诊断单独标为非正式 M1。

`review-template.json` / `visual-review.json`（mesh-m3-review/v1）绑定 run manifest SHA256；包含复核者、human/agent、完成时间、总结、20 图读取证据以及十行分类、边界、形状、匹配、结论和 inspected。human 由浏览器导出；agent 需实际读取回执引用。任何 sample 身份或图片哈希与 manifest 不一致均拒绝。

`result.json`（mesh-m3-result/v1）只在 finalize 核验后生成。evaluation_status=complete 与 m3_verdict 独立；任一样本 fail 则整组 fail，否则任一样本 inconclusive 则整组 inconclusive，全部 pass 才整组 pass。这是材料中的 M3 聚合规则，不是整个研究的晋升/停止规则。

render 后无 result.json，check 返回 incomplete/visual_review_pending。原始输入错误直接失败，不生成一个伪成功 result。finalize 后 check 重验所有图片、协议、判断与结果绑定。demo 字段始终传播，禁止以模拟结果宣称真实模型效果。

`index.html` 是离线交互复核页；finalize 后显示最终只读分析。输入原始数组未复制到输出目录；run manifest 保留输入 SHA256，原任务 ZIP/数据应由原评价证据存储保留。本包 check 检查随报告交付的派生产物，不宣称重新跑过原始模型。

1.2.0 主输出为10张 scene-views/{i}_scene.png，每张包含真实相机图、共同视角和尺度的连续表面采样点、相机投影与类别图例。run manifest 每行 scene_card 绑定此图的哈希、原照片/标定/Mesh来源摘要、显示变换和点数。primary_view=scene 时 AI 读图回执核验这10张主卡；原 comparison/diff 保持为20张辅助图。每张主卡也纳入 check 哈希核验。
