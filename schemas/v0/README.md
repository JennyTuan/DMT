# schemas/v0

原型·不可用于临床诊疗决策。

本目录是 DMT 第一刀（淋巴瘤 PET-CT 随访）最小数据契约。

| 文件 | 含义 |
| --- | --- |
| exam.schema.json | 一次 PET-CT 检查 |
| lesion.schema.json | 病灶条目 |
| measurement.schema.json | SUVmax + CT 最长径等可编辑测量 |
| finding_state.schema.json | proposed 状态机与 audit |
| examples/ | 示意配对样例（is_synthetic=true） |

状态机：`draft → proposed → needs_review → accepted | rejected`。机器输出默认 `proposed`。

禁止字段：Deauville、Lugano、缓解结论、恶性判定。
