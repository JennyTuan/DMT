# Pack 04 — 先验配对 + 描述性报告草稿

## 目标

在 Pack 03（509b771 已交，验门并行）量测之上，跑通**前后检查对照**：`prior_exam_id` 关联 + 病灶级 `lesion_track_id` 配对（可改）→ 生成**可编辑的描述性报告草稿**并导出（常驻原型声明）。

**不做**：质量门总包（Pack 05）、自动缓解/疗效结论、Deauville/Lugano、恶性判定、多病种壳。

## 禁止

- 报告或 UI 出现 Deauville、Lugano、CMR/PMR/NMR/PMD、完全|部分代谢缓解、良恶性、辅助诊断声称
- 借 DMT 扩成多模态平台导航
- 联影等竞品商标 / 可混淆仿品
- 云推理、付费模型、其他产品仓 submodule
- 大改 Pack 02/03 已验主路径（只加配对与草稿）

## 依赖

- Pack 01–02 PASS；Pack 03 交付在 `509b771`（若验门尚有补洞，以 main 最新为准，本包不回滚量测口径）
- [`docs/UI_STYLE.md`](../UI_STYLE.md)：顶栏「关联上次」、右侧列表对照、视口为主
- [`docs/CODEX_BRIEF.md`](../CODEX_BRIEF.md) D9–11 刀序

## Schema 例外（仅本包允许的加法）

Pack 01 曾刻意不做 `lesion_track_id`。本包**允许且仅允许**：

1. 在 `schemas/v0/lesion.schema.json` **增加可选**字段 `lesion_track_id`：`string | null`（跨检查同一病灶的稳定 ID；新建病灶默认 `null` 或新 UUID，配对后两边同值）
2. 更新 `schemas/v0/examples/` 配对样例与 `schemas/v0/README.md` 一句说明
3. `test_contract.py` 覆盖新字段（仍无缓解类字段）

**禁止**借机加结论枚举、疗效字段或其他 breaking 改动。`exam.prior_exam_id` 已存在，只消费不改语义。

## 交付物

1. **检查级关联**
   - UI：顶栏「关联上次」——选择同 `patient_pseudo_id` 的既有 exam 写入/更新 `prior_exam_id`；可解除
   - fixtures/`--demo`：提供可切换的 baseline + followup 一对（followup.`prior_exam_id` → baseline）

2. **病灶级配对（`lesion_track_id`）**
   - 在已关联先验时，列表展示本次病灶 vs 先验候选
   - 支持：**人工指定配对**（选先验 lesion → 两侧写入同一 `lesion_track_id`）、解除配对、为新病灶生成新 track id
   - 可选弱提示（同 label / 粗位置）：仅建议，默认不自动写死；自动建议须可一键否决
   - 配对后对照展示：先验/本次 SUVmax、最长径及差值（描述用，**不**映射成缓解分级）

3. **描述性报告草稿**
   - 面板：可编辑纯文本/富文本均可，但结构至少含：
     - 文首/文末（或页眉）固定：`原型·不可用于临床诊疗决策`
     - 检查信息、是否示意数据、先验 exam 引用
     - 病灶表：部位、track id（可短显）、本次/先验 SUVmax 与最长径、差值、状态（proposed/needs_review…）
     - 自由「描述」段落（医生可改）；**不得**预置疗效结论下拉
   - 「从当前量测重新生成」：覆盖机器生成段，保留用户在标记区内的手改策略须文档说明（推荐：生成区与手写区分离，或生成前提示将覆盖）
   - **导出**：至少一种（`.md` / `.txt` / `.html`）；导出物同等带原型声明；不写注册/诊断话术

4. **持久化**
   - 草稿存本仓（如 `data/reports/<exam_id>.md` 或检查包旁路字段）；路径与版本在 README 写清
   - 配对变更留简单审计（谁、何时、哪个 track、连了哪两个 lesion_id）——可放旁路 json，不破坏状态机 `audit[]` 契约

5. **测试与 README**
   - 单测：关联 prior、写入相同 `lesion_track_id`、草稿含原型句且不含禁词、导出文件可读
   - 更新根 README：Docs / Pack status / 简短「如何关联上次与导出草稿」；For Codex 指向本包

## 技术取舍（默认）

- 续 `apps/petfollow-lymphoma` 技术栈
- 配对以人工为准；不做深度学习匹配
- 单机；无 PACS 推送

## 验收 checklist

- [ ] followup 可设/改/清 `prior_exam_id`；demo 有一对可对照
- [ ] 人工配对后两侧 `lesion_track_id` 一致；可解除；列表能看先验/本次量测与差值
- [ ] `lesion.schema` 仅加法含可选 `lesion_track_id`；examples + contract 测试更新；无疗效/Deauville 字段
- [ ] 描述性草稿可编辑、可再生成策略清楚、可导出；导出与 UI 常驻原型声明
- [ ] 无禁词结论 UI；遵守 UI_STYLE（关联上次入口、视口+列表）
- [ ] 无质量门大包、无云依赖

## 可复制提示词（整段贴进 Codex）

```text
你在仓库 JennyTuan/DMT 工作。只做 docs/packs/04-prior-pairing-report-draft.md 写明的 Pack 04。
Pack 01–02 已 PASS；Pack 03 交付在 509b771（量测口径勿回滚）。禁止开 Pack 05 质量门总包。

背景：淋巴瘤 FDG PET-CT 治疗后代谢随访院内试用原型（petfollow-lymphoma）。遵守 docs/UI_STYLE.md 与 docs/CODEX_BRIEF.md。

任务：
1. Schema 仅允许加法：lesion 增加可选 lesion_track_id (string|null)；更新 examples 与 schemas/v0/README、test_contract.py。禁止加 Deauville/Lugano/缓解/疗效/恶性字段。
2. UI 顶栏「关联上次」：为当前 exam 设置/清除 prior_exam_id（同 patient_pseudo_id）。demo 提供 baseline+followup 一对。
3. 病灶配对：人工将本次 lesion 与先验 lesion 写成同一 lesion_track_id；可解除；可选弱建议但不可强制。列表展示两侧 SUVmax/最长径及差值（只描述，不分级）。
4. 描述性报告草稿：可编辑；含原型声明、检查/先验信息、病灶对照表、自由描述段；禁止疗效结论控件。可从量测再生成（策略写清）。导出 md/txt/html 至少一种，导出带同等原型声明。
5. 续 apps/petfollow-lymphoma；配对/草稿持久化路径写进 README；补单测。更新根 README Pack status；For Codex 指向本 pack。

硬禁：缓解/Deauville/Lugano/恶性/辅助诊断话术；多病种平台壳；竞品商标；云推理；破坏 Pack01 状态机 audit 契约。

做完后列改动文件，并按 Pack 04 验收 checklist 逐条自检。
```
