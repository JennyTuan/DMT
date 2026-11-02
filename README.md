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
| [`docs/CODEX_BRIEF_PACK1.md`](docs/CODEX_BRIEF_PACK1.md) | **Pack1** Codex brief — data contracts + state machine |
| [`docs/UI_DIRECTION.md`](docs/UI_DIRECTION.md) | UI direction for later packs (domestic clinical workstation density; no vendor clone) |

## Pack status

- **Pack1 (current):** JSON data contracts, `ProposedState` machine, fixtures, unit tests — **no UI**
- Later: ROI → SUVmax / longest diameter → prior linking → descriptive report draft → quality gates

## For Codex

Paste the prompt block at the bottom of `docs/CODEX_BRIEF_PACK1.md` into Codex on a machine with this repo cloned. Do not expand scope past Pack1.
