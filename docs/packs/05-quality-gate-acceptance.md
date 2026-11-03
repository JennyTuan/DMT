# Pack 05 — 质量门 + 样例全流程验收

## 目标

收束两周 MVP：把已分散的复核规则收成**可运行质量门**；失败条目进 `needs_review`（不硬出终值、不自动 `accepted`）；用示意样例跑通**全流程验收**；写清**院内试用残留风险可接受条件**。

**不做**：NMPA/FDA 注册材料、疗效/Deauville/Lugano 字段、第二病种、云端部署、PACS 集成。

## 禁止

- 任何疗效结论、缓解分级、Deauville、Lugano、良恶性、辅助诊断声称（UI / 草稿 / 导出 / schema）
- 质量门「通过」被解释成临床可用或注册就绪
- 自动 `accepted` / `rejected`（仅人工）
- 借机扩多模态平台壳、竞品商标、改已验量测口径（除非门控暴露的明确 bug）

## 依赖

- Pack 01–02 PASS；Pack 03 交付 `509b771`；Pack 04 交付 `2eed4a7`（验门并行，以 main 为准）
- [`docs/UI_STYLE.md`](../UI_STYLE.md)、[`docs/CODEX_BRIEF.md`](../CODEX_BRIEF.md) §4 验收总门与 D12–14

## 交付物

### 1. 质量门（可运行）

集中实现（如 `apps/petfollow-lymphoma/quality_gate.py` 或等价），对当前 exam bundle **逐条**检查，输出结构化结果：`{ gate_id, level, target_id, message, action }`。

**至少覆盖（失败 → 相关 measurement/lesion `needs_review`，note/旁路记录原因）：**

| gate_id | 条件 | 动作 |
| --- | --- | --- |
| `AC_MISSING` | `attenuation_corrected == false` | SUV 相关量测 → `needs_review`；不把 SUV 当终值 |
| `SUV_META_MISSING` | 无法完成 SUV 换算（缺 tag/单位） | `suv_max` 保持/置 `null` → `needs_review` |
| `CT_ALIGN_FAIL` | 最长径无法可靠估计 | `longest_diameter_mm` 为 `null` → `needs_review` |
| `ROI_EMPTY` | `roi_ref` 空或掩膜空 | 量测 → `needs_review` |
| `PRIOR_BROKEN` | `prior_exam_id` 指向缺失/患者不一致 | 检查级告警；已配对 track 标复核或阻断导出终稿提示 |
| `TRACK_INCOMPLETE` | 已设 prior 但关键病灶无 `lesion_track_id` 且用户未显式跳过 | 告警（可配置为 warn 或 needs_review，默认 warn + 导出提醒） |
| `PROTOTYPE_BANNER` | 缺原型声明 | **阻断导出**直至补齐 |
| `BANNED_TERMS` | 草稿/导出含禁词表（Deauville/Lugano/缓解分级等） | **阻断导出**；UI 标红 |

门控在：保存量测、关联先验、生成/导出报告前各跑一次；UI 可查看「质量门」列表（只读原因）。

### 2. 样例全流程验收

1. **自动化**：`tests/` 增加（或扩展）一条端到端用例——示意 baseline+followup：导入/载入 → ROI → SUVmax/最长径 → 关联+配对 → 草稿生成 → 导出；断言原型句存在、无禁词、关键路径文件落盘；至少一条路径故意触发 `AC_MISSING` 或 `SUV_META_MISSING` 并断言 `needs_review`
2. **人工清单**：`docs/ACCEPTANCE_MVP.md`（本包创建）——逐步点击验收（对齐 CODEX_BRIEF §4），含期望截图位说明（文字即可，不强制截图入库）
3. README 增加「Pack 05 质量门与验收」短节：如何跑门控与 e2e

### 3. 残留风险可接受条件（写死进 `docs/RESIDUAL_RISK.md`）

供 @合规质量 对照。须明确**仅当下列全部成立**时，院内试用残留风险视为可接受：

1. 每屏与导出常驻 `原型·不可用于临床诊疗决策`；话术限定科研/院内试用，不写注册申报
2. 量测与 ROI 均可人工修改；数值史 + 状态机 audit 可回看；不确定不硬出终值
3. 缺衰减校正 / 定量不全 / 对齐失败 → `needs_review`，不得自动 `accepted`
4. 无自动疗效/Deauville/Lugano/恶性字段；禁词门阻断导出
5. 范围仅淋巴瘤 FDG PET-CT 随访对照；示意数据有徽标
6. 单机运行、无云推理依赖；操作者知悉合成/示意数据局限

任一条件被产品改动削弱 → 本包验收失败，须重开合规门。

### 4. Schema / 范围

- **默认不改** `schemas/v0`；若门控只需旁路字段（gate report json），放 `data/gates/<exam_id>.json`
- 禁止加疗效枚举

## 技术取舍

- 续 `apps/petfollow-lymphoma`；门控纯本地规则引擎
- 禁词表维护在本仓（如 `apps/petfollow-lymphoma/banned_terms.txt`），中英常见疗效词

## 验收 checklist

- [ ] 质量门可对 demo exam 跑出结构化结果；AC/SUV/ROI 失败进 `needs_review`
- [ ] 导出前跑 `PROTOTYPE_BANNER` + `BANNED_TERMS`；失败则不能导出
- [ ] e2e 测试覆盖全流程 + 至少一条失败→`needs_review`
- [ ] `docs/ACCEPTANCE_MVP.md` 与 `docs/RESIDUAL_RISK.md` 已写且与上文一致
- [ ] 无疗效结论字段；未自动 accepted；README / Pack status 已更新

## 可复制提示词（整段贴进 Codex）

```text
你在仓库 JennyTuan/DMT 工作。只做 docs/packs/05-quality-gate-acceptance.md 写明的 Pack 05。
Pack 01–02 PASS；Pack 03≈509b771；Pack 04≈2eed4a7。不要开新病种，不要写注册材料。

背景：淋巴瘤 FDG PET-CT 治疗后代谢随访院内试用原型。遵守 docs/UI_STYLE.md 与 docs/CODEX_BRIEF.md。

任务：
1. 实现本地质量门：结构化 gate 结果；AC_MISSING / SUV_META_MISSING / CT_ALIGN_FAIL / ROI_EMPTY / PRIOR_BROKEN / TRACK_INCOMPLETE / PROTOTYPE_BANNER / BANNED_TERMS 按 BRIEF 表执行；失败量测进 needs_review；禁止自动 accepted。
2. 保存量测、关联先验、导出报告前调用门控；UI 可查看原因；缺原型或命中禁词则阻断导出。
3. 增加 e2e：示意全流程（载入→ROI→量测→配对→草稿→导出）断言原型句与无禁词；另测一条门控失败→needs_review。
4. 新建 docs/ACCEPTANCE_MVP.md（人工清单）与 docs/RESIDUAL_RISK.md（残留风险可接受条件，按 BRIEF 六条）。更新根 README Pack status 与短使用说明。
5. 默认不改 schemas/v0；门控报告可旁路 json。

硬禁：Deauville/Lugano/缓解/恶性/辅助诊断；注册话术；云推理；多病种壳。

做完后列改动文件，并按 Pack 05 验收 checklist 逐条自检。
```
