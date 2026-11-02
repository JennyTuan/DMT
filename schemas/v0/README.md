原型·不可用于临床诊疗决策

# 淋巴瘤 FDG PET-CT 随访数据契约

每份示例含一次检查（`exam`）、所属病灶（`lesions[]`）和量测（`measurements[]`）。两次检查来自同一合成患者。数值仅作示意，序列路径为占位引用。

## 检查

| 字段 | 含义 |
| --- | --- |
| `exam_id` / `patient_pseudo_id` | 本次检查的标识 / 患者脱敏代号。前后检查共用患者代号。 |
| `study_datetime` | 带时区的检查时间。 |
| `modality` / `disease` | 模态固定为 `PET-CT`。病种可省略，默认且仅允许 `lymphoma`。 |
| `pet_series_ref` / `ct_series_ref` | 同次检查的 PET、CT 序列引用。 |
| `attenuation_corrected` | PET 是否经过衰减校正。 |
| `prior_exam_id` | 基线填 `null`。随访填上次检查的 `exam_id`。 |
| `prototype_banner` | 固定为文首的原型声明。 |
| `is_synthetic` | 是否为示意数据。本目录两个示例均为 `true`。 |

## 病灶和量测

| 对象 | 字段 | 含义 |
| --- | --- | --- |
| 病灶 | `lesion_id` / `exam_id` | 病灶标识 / 所属检查标识。 |
| 病灶 | `label` | 用短文字记录部位，如“纵隔淋巴结”。 |
| 病灶 | `status` / `audit` | 病灶的当前状态 / 状态变更记录。 |
| 量测 | `measurement_id` / `lesion_id` | 量测标识 / 所属病灶标识。 |
| 量测 | `suv_max` / `longest_diameter_mm` | ROI 内的 SUV 最大值 / CT 最长径（毫米）。取非负数，未测填 `null`。 |
| 量测 | `roi_ref` / `edited` | ROI 引用，无引用填 `null`。`edited` 记录量测是否经过编辑。 |
| 量测 | `state` / `audit` | 量测的当前状态 / 状态变更记录。 |

## 状态与审计

| 从 | 到 | 记录人 |
| --- | --- | --- |
| `draft` | `proposed` | 系统或人工 |
| `proposed` | `needs_review` | 系统或人工 |
| `needs_review` | `accepted` 或 `rejected` | 仅人工 |

草稿的 `audit` 为空数组。机器首次输出时须显式写入 `proposed`，追加第一条记录。Schema 的 `default` 只声明默认值。质量门失败时，写入方须转入 `needs_review`，并记录原因。人工接受或拒绝后即为终态。

每次变更追加一项。`at` 是带时区的操作时间，`actor` 取 `system` 或 `user`，`from` 和 `to` 是变更前后的状态，`note` 记录变更说明。五个字段均必填。历史必须从草稿开始，逐步衔接，最后一项的 `to` 必须与当前状态一致。

## 复验

四份 Schema 统一使用 JSON Schema Draft 2020-12。`exam.schema.json` 的根校验单条检查，`#/$defs/bundle` 校验完整示例。`finding_state.schema.json` 的根可单独校验 `{state, audit}`。跨文件的患者、检查和病灶标识由配对测试核对。

在仓库根目录运行以下命令。测试从本目录加载全部 Schema，并启用日期时间格式检查。

```sh
python -m pip install "jsonschema[format-nongpl]>=4.18,<5"
python schemas/v0/test_contract.py -v
```
