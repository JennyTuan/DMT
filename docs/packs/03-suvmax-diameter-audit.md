# Pack 03 — SUVmax + CT 最长径 + 可改留痕

## 目标

在 Pack 02（77881ed PASS）阅片壳与 ROI 之上，对每个已有 `roi_ref` 的病灶算出 **SUVmax** 与 **CT 最长径 (mm)**，列表可改，**数值变更可追溯**；缺衰减校正等质量问题时进入 `needs_review`。

**不做**：先验配对 / `lesion_track_id`、描述性报告草稿、质量门总包、Deauville/Lugano/缓解字段（Pack 04+）。

## 禁止

- 改 Pack 01 `schemas/v0`（契约已锁；数值留痕走旁路，见下）
- 回改 Pack 02 导入/视口主路径（只加量测与留痕）
- 诊断 / 缓解 / Deauville / Lugano / 恶性 UI 或字段
- 多病种壳、竞品商标、云推理、付费权重、其他产品仓 submodule

## 依赖

- Pack 01 PASS（f5a13ab）；Pack 02 PASS（77881ed）
- [`docs/UI_STYLE.md`](../UI_STYLE.md)、[`docs/CODEX_BRIEF.md`](../CODEX_BRIEF.md)
- 产品验 Pack02 软备注：ROI 再存时 **measurement 状态机 `audit[]` 条数不增是契约限制**；本包必须把**数值留痕咬严**（见交付物 3）

## 交付物

1. **SUVmax（自动 + 可改）**
   - 基于当前 `roi_ref` 对应 PET ROI：在衰减校正 PET 上计算 ROI 内最大 SUV，写入 `measurement.suv_max`
   - 公式/单位：优先 DICOM 已是 SUV；否则用标准体重法（需体重/注射剂量/时间等 tag）。缺关键 tag → 不硬填终值：`suv_max` 可暂 `null`，状态进 `needs_review`，列表提示原因
   - `exam.attenuation_corrected == false`（含 Pack02「未知」按 false 写入的情形）→ 即便算出数，**必须** `proposed → needs_review`，note 写明「缺/未衰减校正，SUV 仅供复核」
   - 右侧列表显示 SUVmax，支持人工改数；改后 `edited=true`

2. **CT 最长径 mm（自动 + 可改）**
   - 在同检 CT 上，按 ROI 对齐层（或用户当前 CT 层）估计病灶最长径（实现自选：ROI 投影/外接径/两点测径半自动），写入 `longest_diameter_mm`
   - 列表可改；改后 `edited=true`
   - 无法可靠估计时保持 `null` 并提示，不编造

3. **量测留痕（咬严）**
   - Pack 01 `measurement.audit[]` **只记录状态机**（`draft→proposed→needs_review→…`），`proposed` 时契约限制最多 1 条——**禁止为了留痕去改 schema 或塞非法多条状态 audit**
   - 本包必须另建 **数值变更史**（推荐：`data/exams/<exam_id>.json` 内 `measurement_value_history[]`，或 `data/measurements/<exam_id>/<measurement_id>.history.json`），每条至少：`{ at, actor, field, from, to, note, roi_ref? }`
   - 触发必写 history 的事件：自动首次填数、ROI 变更后重算、用户改 SUVmax、用户改最长径
   - ROI 版本链（Pack02）保留；重算后更新 `suv_max`/`longest_diameter_mm` 并挂当前 `roi_ref`
   - UI：病灶/量测区可查看「数值留痕」或最近 N 条（只读）

4. **状态机行为**
   - 机器自动填数默认保持/进入 `proposed`（已有 Pack02 病灶）
   - 缺衰减校正 / 缺 SUV 关键 tag / 重算失败 → `needs_review`（补齐状态 audit 第二条）
   - 仅人工可 `accepted` / `rejected`（本包可不做接受按钮，但不得自动 accepted）

5. **测试与 README**
   - 单测：给定示意 ROI，SUVmax 与最长径有稳定可断言结果（或快照容差）；改数 → `edited` + history 增条；模拟未校正 → `needs_review`
   - 更新根 README Pack status；启动说明补一句如何看到量测与留痕

## 技术取舍（默认）

- 续 Pack02 已选技术栈（`apps/petfollow-lymphoma`），不要平行再起一套壳
- SUV：`pydicom` 读 tag；不引入商业定量库
- 最长径：几何/测径即可，不上分割新模型
- 单机 RTX 3060；无云

## 验收 checklist

- [ ] 有 ROI 的病灶能自动写出非 null 的 `suv_max` 与/或 `longest_diameter_mm`（示意数据上可复现）；列表可见
- [ ] 两值均可人工修改；修改后 `edited=true`，且 **value history 条数增加**（不只靠 ROI 版本链）
- [ ] ROI 修改并重算后，数值更新并再写 history
- [ ] `attenuation_corrected == false` → `needs_review` + 状态 audit 合法；UI 有复核提示
- [ ] 未改 `schemas/v0`；未出现 Deauville/Lugano/缓解/诊断；无先验配对/报告草稿
- [ ] 顶栏原型条仍在；单测覆盖计算/改数/未校正路径

## 可复制提示词（整段贴进 Codex）

```text
你在仓库 JennyTuan/DMT 工作。只做 docs/packs/03-suvmax-diameter-audit.md 写明的 Pack 03。
Pack 01（f5a13ab）与 Pack 02（77881ed）已 PASS。禁止修改 schemas/v0；禁止重做导入/视口主路径；禁止开 Pack 04（先验配对/报告）。

背景：淋巴瘤 FDG PET-CT 治疗后代谢随访院内试用原型（petfollow-lymphoma）。遵守 docs/UI_STYLE.md 与 docs/CODEX_BRIEF.md。

任务：
1. 在 apps/petfollow-lymphoma 上，对已有 roi_ref 的病灶计算 SUVmax（PET ROI）与 CT 最长径 mm，写入 measurement.suv_max / longest_diameter_mm；右侧列表展示且可改。
2. exam.attenuation_corrected == false（含未知按 false）或缺 SUV 关键 DICOM tag：不得当终值糊弄——进入 needs_review，状态机 audit 合法，UI 提示复核。
3. 量测数值留痕咬严：Pack 01 的 measurement.audit[] 只用于状态机（proposed 最多 1 条），不要为留痕破坏契约。另建 measurement value history（每次自动填数、ROI 重算、用户改 SUVmax、用户改最长径都追加 {at,actor,field,from,to,note}）；用户改数必须 edited=true。UI 可查看留痕。
4. 续现有 Python/桌面栈与 fixtures；补单测（计算稳定、改数增 history、未校正→needs_review）。更新根 README Pack status 与简短使用说明。

硬禁：改 schema；Deauville/Lugano/缓解/恶性；先验配对与报告草稿；竞品商标；云推理。

做完后列改动文件，并按 Pack 03 验收 checklist 逐条自检。
```
