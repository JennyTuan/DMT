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
| [Pack 01 数据契约](docs/packs/01-data-contract.md) | 当前执行范围与验收清单 |
| [`docs/CODEX_BRIEF_PACK1.md`](docs/CODEX_BRIEF_PACK1.md) | Supplementary Pack 01 notes |
| [`docs/UI_DIRECTION.md`](docs/UI_DIRECTION.md) | UI direction for later packs (domestic clinical workstation density; no vendor clone) |

## Pack status

| 包 | 交付 | 状态 |
| --- | --- | --- |
| Pack 01 | [检查、病灶、量测、状态机及配对示例](schemas/v0/README.md) | 已提交待人工验 |

Later: ROI → SUVmax / longest diameter → prior linking → descriptive report draft → quality gates

## For Codex

Use the prompt and acceptance checklist in [Pack 01](docs/packs/01-data-contract.md).
