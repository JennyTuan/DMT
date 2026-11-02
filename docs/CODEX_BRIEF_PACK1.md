# DMT · Codex 实施说明（Pack1 · 数据契约先行）

锁定日期：2026-11-02（Jenny + 产品 / 方案 / 合规质量 · Lumi 收口）

仓：`github.com/JennyTuan/DMT`（伞名 DMT；**第一模块** `petfollow-lymphoma`）  
相关锁定：`docs/LOCK.md` · `docs/UI_DIRECTION.md`

## 角色与协作

| 角色 | 职责 |
| --- | --- |
| **Jenny** | 本机用 Codex 改代码；把本文整段贴进 Codex |
| **Codex** | 唯一写代码方；先读本文 + LOCK + UI_DIRECTION 再动手 |
| **Lumi** | 调度 BRIEF、收口验收；不写业务代码 |
| **产品** | 打假伪需求 / 验收条目 |
| **方案** | 刀序与契约切分 |
| **合规质量** | 原型标识与禁字段 |

交互链：**Lumi BRIEF → Jenny/Codex → 产品验门 + 合规验禁字段**。一次只做本 Pack。

## Pack1 目标（仅此）

在空仓 `DMT` 内落地**最小数据契约 + 状态机 + fixture + 单测**：

1. 定义实体：`Exam`、`Series`（PET/CT）、`Finding`（病灶条目）、`Measurement`（`suv_max`、`longest_diameter_mm`）、`PriorLink`、`ReportDraft`（stub）、`ProposedState`
2. 提供 JSON Schema（或等价 Zod / TypeScript 类型 + JSON Schema 导出）与 TypeScript/Python 校验入口二选一即可，**优先 JSON Schema + 语言无关 fixture**
3. 合法 fixture ≥1、非法 fixture ≥1（含禁字段，必须校验失败）
4. 单元测试：合法通过、非法/禁字段失败
5. 目录建议：`packages/petfollow-lymphoma/schema/` 或 `modules/petfollow-lymphoma/schema/`（二选一，写进 README 一小段说明）

**不做 UI、不做 DICOM 解析、不做 ROI/SUV 计算、不做报告渲染。**

## Out of scope（本包严禁顺手做）

- 任何前端/工作站界面（即便「顺手搭壳」）
- 真实 DICOM 导入管线、配准、SUV 公式实现
- Deauville / Lugano / 缓解结论 / 恶性字段「预留」
- 多癌种枚举、第二模态模块骨架、平台导航
- 依赖或 submodule `longitudinal-imaging` / 冠脉仓
- NMPA 注册文档、临床评价材料
- 用 DMT 名称写「多模态平台已就绪」类 README 吹嘘

## 产品定位（硬）

- **是**：淋巴瘤治疗后 · PET-CT **代谢随访对照** · 院内试用原型的数据层
- **不是**：多模态诊断平台、辅助诊断软件、疗效金标准、RECIST/PERCIST 替代品
- 伞名 DMT 只表示产品线仓；**对外模块话术**仍是「淋巴瘤 PET 随访原型」

## ProposedState 状态机

```text
proposed ──► needs_review ──► accepted
    │              │              │
    │              └──► rejected  │
    └──────────────► rejected     │
                     accepted ◄───┘（仅人工确认后）
```

| 状态 | 含义 |
| --- | --- |
| `proposed` | 系统或半自动给出的建议值，**不可当终值** |
| `needs_review` | 配准差 / 无衰减校正 / 不确定，必须人工处理 |
| `accepted` | 人工确认后的可引用值 |
| `rejected` | 人工否决；保留审计，不进报告终表 |

规则：

- 新建自动/半自动测量默认 `proposed`
- 质量门失败（烂配准、缺必要序列等）→ `needs_review`，禁止静默写成 `accepted`
- 只有显式人工动作可到 `accepted` / `rejected`
- 每次状态或数值变更写 `AuditEvent`（谁/何时/字段/旧→新）

## 数据契约（字段名英文；说明可中文）

### 公共

```json
{
  "schema_version": "1.0.0",
  "module_id": "petfollow-lymphoma",
  "prototype_disclaimer": "原型·不可用于临床诊疗决策"
}
```

`module_id` 固定为 `petfollow-lymphoma`。`prototype_disclaimer` 必填常量（或枚举单值）。

### Exam

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `exam_id` | string | ✓ | 本仓内稳定 ID |
| `patient_pseudonym` | string | ✓ | 脱敏代号，禁止真实姓名字段 |
| `study_date` | string (YYYY-MM-DD) | ✓ | |
| `modality_pair` | `"PET-CT"` | ✓ | Pack1 仅允许此字面量 |
| `indication` | `"lymphoma_post_treatment_followup"` | ✓ | 单一病种枚举 |
| `series` | Series[] | ✓ | 至少 1 PET + 1 CT |
| `findings` | Finding[] | ✓ | 可为 `[]` |
| `prior_links` | PriorLink[] | | 默认可 `[]` |
| `report_draft` | ReportDraft \| null | | stub |
| `created_at` / `updated_at` | ISO-8601 string | ✓ | |

**禁止**出现：`diagnosis`、`cancer_type` 多癌种列表、`is_screening` 等。

### Series

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `series_id` | string | ✓ | |
| `modality` | `"PET"` \| `"CT"` | ✓ | |
| `frame_of_reference_uid` | string \| null | | 可空；空则后续质量门易进 `needs_review` |
| `attenuation_corrected` | boolean \| null | | PET 用；未知则 `null` → 倾向 `needs_review` |
| `tracer` | string \| null | | 如 `"FDG"`；CT 为 `null` |
| `dicom_hint_path` | string \| null | | 本地样例路径提示，可空 |

### Finding（病灶条目）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `finding_id` | string | ✓ | |
| `label` | string | ✓ | 人可读，如 `"right cervical node"`；非诊断结论 |
| `state` | ProposedState | ✓ | |
| `measurements` | Measurement[] | ✓ | |
| `notes` | string \| null | | 描述性备注，禁止疗效套话模板字段 |

### Measurement

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `measurement_id` | string | ✓ | |
| `kind` | `"suv_max"` \| `"longest_diameter_mm"` | ✓ | Pack1 只允许这两种 |
| `value` | number \| null | ✓ | `null` 表示未测 |
| `unit` | string | ✓ | `suv_max`→`"SUV"`；直径→`"mm"` |
| `state` | ProposedState | ✓ | |
| `source` | `"manual"` \| `"semi_auto"` \| `"imported"` | ✓ | |
| `audit` | AuditEvent[] | ✓ | 可先 `[]`，但字段必在 |

### PriorLink

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `link_id` | string | ✓ | |
| `current_exam_id` | string | ✓ | |
| `prior_exam_id` | string | ✓ | |
| `finding_map` | { current_finding_id, prior_finding_id, state }[] | ✓ | 配对可 `proposed` |
| `state` | ProposedState | ✓ | 链本身也可需审 |

### ReportDraft（stub）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `draft_id` | string | ✓ | |
| `exam_id` | string | ✓ | |
| `body_text` | string | ✓ | **仅描述性**草稿；可空字符串 |
| `included_finding_ids` | string[] | ✓ | |
| `state` | ProposedState | ✓ | 默认 `proposed` |
| `disclaimer` | string | ✓ | 必须含 `原型·不可用于临床诊疗决策` |

### AuditEvent

| 字段 | 类型 | 必填 |
| --- | --- | --- |
| `at` | ISO-8601 string | ✓ |
| `actor` | string | ✓ | 如 `"user:jenny"` / `"system:semi_auto"` |
| `field` | string | ✓ |
| `old_value` | any \| null | ✓ |
| `new_value` | any \| null | ✓ |

## 禁止字段清单（出现即校验失败）

在任意对象上检测到下列键名（大小写不敏感）或同义字段 → **schema / 测试必须失败**：

- `deauville` / `deauville_score`
- `lugano` / `lugano_stage` / `lugano_response`
- `metabolic_response` / `cmr` / `pmr` / `nmr` / `pmd`（缓解结论）
- `malignancy` / `malignant` / `benign_malignant`
- `diagnosis` / `diagnosis_conclusion` / `diagnostic_conclusion`
- `ai_diagnosis` / `辅助诊断`
- `recist` / `percist`（本原型不做自动标准判定）
- `screening_flag` / `bi_rads` 等筛查叙事

允许在 `notes` / `body_text` **自由文本**里出现医生手打的普通句子，但**不得**提供结构化结论字段或枚举。

## Fixture 要求

1. **`fixtures/valid/exam_lymphoma_pair_min.json`**  
   - 一次当前 Exam + 一次 prior Exam（可两个文件或一个 bundle）  
   - 含 PET + CT Series、至少 1 个 Finding、`suv_max` + `longest_diameter_mm`、一条 PriorLink、ReportDraft stub  
   - 所有自动值 `state: "proposed"`  
   - 含 `prototype_disclaimer`

2. **`fixtures/invalid/exam_with_deauville.json`**  
   - 基于合法样例但加入 `deauville_score`（或其它禁字段）  
   - 测试断言：**校验失败**

可选：`exam_wrong_indication.json`（`indication` 不是淋巴瘤随访）亦应失败。

## 验收清单（Jenny / Lumi）

- [ ] 仓内可见 schema（JSON Schema 或等价）覆盖上述实体
- [ ] `module_id === "petfollow-lymphoma"`；Exam.`indication` 枚举锁死
- [ ] ProposedState 四态齐全；规则有测试或文档化断言
- [ ] 合法 fixture 通过校验
- [ ] 含禁字段的非法 fixture **失败**
- [ ] 无 UI、无 DICOM 重依赖、无 submodule 旧仓
- [ ] README 写明 DMT=伞仓、第一模块=淋巴瘤 PET 随访原型、原型免责声明
- [ ] 未引入 Deauville/Lugano/诊断结论等「预留」字段
- [ ] 提及后续 UI 须遵守 `docs/UI_DIRECTION.md`（本包可不实现）

## 技术建议（非强制栈）

- Node：Ajv + JSON Schema；或 Zod（须能导出/并行维护 JSON Schema 供非 TS 用）
- Python：jsonschema
- 测试：任一（pytest / vitest / node:test）
- 本包不需要 CUDA / GPU

## 话术（README / 注释）

- **可写**：单机科研/院内试用、原型、代谢随访对照、`proposed`、需人工确认
- **禁写**：多模态平台已上线、NMPA 三类、辅助诊断、Deauville 自动、疗效评估金标准、对齐某厂商AI

## 完成定义（DoD）

1. 行为符合本 BRIEF，未扩大 scope  
2. 禁字段有自动化拦截  
3. 简短 `docs/PACK1_NOTES.md` 或 PR 说明：改了什么、如何本地跑测试、已知限制  
4. Jenny 本地测试绿后告知 Lumi → 通过再开 Pack2 BRIEF  

---

## 粘贴给 Codex 的提示词（整段复制）

```text
你在仓库 github.com/JennyTuan/DMT（默认分支 main）工作。

先读：
1) docs/CODEX_BRIEF_PACK1.md
2) docs/LOCK.md
3) docs/UI_DIRECTION.md

只做 Pack1：淋巴瘤 PET 随访模块（module_id=petfollow-lymphoma）的数据契约 + ProposedState 状态机 + 合法/非法 fixture + 单元测试。

要求：
- 实体：Exam, Series (PET|CT), Finding, Measurement (suv_max | longest_diameter_mm), PriorLink, ReportDraft stub, AuditEvent, ProposedState (proposed|needs_review|accepted|rejected)
- indication 锁死 lymphoma_post_treatment_followup；modality_pair 锁死 PET-CT
- 必填 prototype_disclaimer = 「原型·不可用于临床诊疗决策」
- 禁止字段（出现即校验失败）：deauville*, lugano*, metabolic_response/cmr/pmr, malignancy*, diagnosis*, ai_diagnosis, recist, percist, screening*
- 不要做 UI、DICOM 管线、ROI/SUV 算法、报告渲染
- 不要 submodule 或依赖 longitudinal-imaging / 冠脉仓
- 不要把 DMT 写成「多模态平台已就绪」；DMT 只是伞仓名
- UI 方向已锁定在 docs/UI_DIRECTION.md，本包只引用、不实现
- 目录自定但清晰；更新 README 说明如何跑校验测试

做完后列出：新增文件、如何运行测试、已知限制。不要开始 Pack2。
```
