# Pack 01 — 数据契约（Exam / Lesion / Measurement / proposed）

## 目标

在本仓落地**最小** JSON 数据契约与样例，支撑后续 ROI / SUVmax / 最长径 / 先验配对。不写 UI，不做分割模型。

## 禁止

- 诊断结论、Deauville、Lugano、缓解字段
- 多病种枚举扩成平台（`disease` 固定 `lymphoma` 或可空但默认 lymphoma）
- 引用或 submodule 其他产品仓

## 交付物

1. `schemas/v0/exam.schema.json`
2. `schemas/v0/lesion.schema.json`
3. `schemas/v0/measurement.schema.json`
4. `schemas/v0/finding_state.schema.json`（proposed 状态机）
5. `schemas/v0/examples/` 下至少 2 份配对样例（baseline + followup）
6. `schemas/v0/README.md` 字段说明（中文短句）

## 状态机（必须）

`draft → proposed → needs_review → accepted | rejected`

- 机器输出默认 `proposed`
- 质量门失败 → `needs_review`
- 仅人工可 `accepted` / `rejected`
- 每次状态变更写 `audit[]`：`{ at, actor, from, to, note }`

## 核心字段（最小集）

**Exam**：`exam_id`, `patient_pseudo_id`, `study_datetime`, `modality`=`PET-CT`, `pet_series_ref`, `ct_series_ref`, `attenuation_corrected` (bool), `prior_exam_id` (nullable), `prototype_banner` 恒为原型声明字符串

**Lesion**：`lesion_id`, `exam_id`, `label` (自由文本部位), `status` (上列状态机)

**Measurement**：`measurement_id`, `lesion_id`, `suv_max` (number|null), `longest_diameter_mm` (number|null), `roi_ref` (nullable), `edited` (bool), `state`, `audit[]`

前后对照不在本包做算法，但 Exam 必须能挂 `prior_exam_id`。

## 验收 checklist

- [ ] 四个 schema 可通过 JSON Schema 校验器校验 examples
- [ ] examples 含一对 baseline/followup，且 followup.prior_exam_id 指向 baseline
- [ ] 无 Deauville/Lugano/diagnosis/response 字段
- [ ] README 写明「原型·不可用于临床诊疗决策」
- [ ] 无对外部产品仓的依赖

## 可复制提示词（整段贴进 Codex）

```text
你在仓库 JennyTuan/DMT 工作。只做 docs/packs/01-data-contract.md 写明的 Pack 01。

背景：独立新仓；第一刀是淋巴瘤 FDG PET-CT 治疗后代谢随访的院内试用原型。不是多模态诊断平台，不继承 longitudinal-imaging。

任务：
1. 创建 schemas/v0/ 下 exam / lesion / measurement / finding_state 的 JSON Schema（draft 2020-12 或 draft-07 均可，全仓统一）。
2. finding_state 状态机仅允许：draft → proposed → needs_review → accepted | rejected；默认机器输出 proposed；并定义 audit 条目结构。
3. 提供 examples：至少 2 个 exam（baseline + followup 配对），各含 ≥1 lesion 与 measurement（suv_max + longest_diameter_mm 可先填示意数）；followup.prior_exam_id 指向 baseline。
4. schemas/v0/README.md 用中文短句说明字段；文首写「原型·不可用于临床诊疗决策」。
5. 更新根 README 状态表：Pack 01 标为已提交待人工验。

硬禁：Deauville、Lugano、缓解/疗效结论字段、恶性判定、多癌种平台结构、submodule 其他仓、UI、分割权重下载。

做完后列出改动文件清单，并按 Pack 01 验收 checklist 逐条自检。
```
