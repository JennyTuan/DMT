# DMT

**DMT** is the umbrella repository for a multimodal *follow-up* product line.  
**First module only (this sprint):** `petfollow-lymphoma` — lymphoma post-treatment **PET-CT metabolic follow-up**, hospital in-trial / research **prototype**.

> **原型·不可用于临床诊疗决策**  
> Prototype — not for clinical diagnosis or treatment decisions.

## What this is / is not

| Is | Is not |
| --- | --- |
| Independent clean repo for the lymphoma PET follow-up prototype | A shipped multi-modality “AI platform” |
| Schema-first packs toward a runnable in-trial demo | Real NMPA Class III registration package |
| Editable SUVmax + CT longest-diameter follow-up with audit trail (later packs) | Auto Deauville / Lugano / malignancy / response conclusions |

The name **DMT** must **not** be used to claim a multi-modality platform is already productized. Later modalities get their own modules and briefs.

## Docs

| Doc | Purpose |
| --- | --- |
| [`docs/LOCK.md`](docs/LOCK.md) | Product lock: build / don’t build / bans |
| [`docs/CODEX_BRIEF.md`](docs/CODEX_BRIEF.md) | Codex 总 BRIEF（命名 / 刀序 / 禁区） |
| [`docs/UI_STYLE.md`](docs/UI_STYLE.md) | 国产工作站信息密度 LOCK（界面包强制） |
| [Pack 01 数据契约](docs/packs/01-data-contract.md) | Exam / Lesion / Measurement / proposed |
| [Pack 02 导入+阅片壳+半自动 ROI](docs/packs/02-import-viewer-roi.md) | **当前执行**：导入 → 挂片 → 半自动 ROI |
| [`docs/CODEX_BRIEF_PACK1.md`](docs/CODEX_BRIEF_PACK1.md) | Supplementary Pack 01 notes |
| [`docs/UI_DIRECTION.md`](docs/UI_DIRECTION.md) | UI direction notes（以 UI_STYLE 为准） |

## Pack status

| 包 | 交付 | 状态 |
| --- | --- | --- |
| Pack 01 | [检查、病灶、量测、状态机及配对示例](schemas/v0/README.md) | PASS（f5a13ab） |
| Pack 02 | [导入 + 阅片壳 + 半自动 ROI](docs/packs/02-import-viewer-roi.md) | BRIEF 已提交，待 Codex |

Later: SUVmax / CT 最长径 + 留痕 → 先验配对 → 描述性报告草稿 → 质量门

## For Codex

一次只做一个 pack。当前贴：[`docs/packs/02-import-viewer-roi.md`](docs/packs/02-import-viewer-roi.md) 文末「可复制提示词」。
