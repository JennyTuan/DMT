# Pack 02 — 导入 + 阅片壳 + 半自动 ROI

## 目标

在 Pack 01 契约之上，落地**可跑**的最小壳：导入同检 PET+CT → 按 `docs/UI_STYLE.md` 挂片 → 半自动 ROI（可改）并写入 `lesion` / `measurement.roi_ref`（状态默认 `proposed`）。

**不做** SUVmax 数值计算、CT 最长径、先验配对算法、报告草稿（留给 Pack 03+）。

## 禁止

- 扩 Pack 01 schema（缺字段用 `null` / 占位，不改契约）
- Deauville / Lugano / 缓解 / 恶性 / 诊断结论 UI 或字段
- 多病种导航、多模态应用超市、借 DMT 做平台壳
- 联影 / uWS 等商标、Logo、启动图、可混淆仿品
- 云推理、付费分割权重、submodule 其他产品仓
- 聊天助手主路径、海外 AI demo 大留白风

## 依赖

- Pack 01 已 PASS（`schemas/v0/*` + examples）；本包只消费，不改契约
- UI 强制遵守 [`docs/UI_STYLE.md`](../UI_STYLE.md) 与 [`docs/CODEX_BRIEF.md`](../CODEX_BRIEF.md)

## 交付物

1. **导入**：本地选目录 / DICOM 系列（至少 PET + CT 各一系）；解析后生成符合 Pack 01 的 `exam` JSON（含 `pet_series_ref` / `ct_series_ref` / `attenuation_corrected`；缺衰减校正标记则后续量测包进 `needs_review`，本包至少把 bool/未知写清）
2. **阅片壳**（窗口标题含「淋巴瘤 PET 随访原型」）：
   - 顶栏常驻 `原型·不可用于临床诊疗决策`
   - 中央视口 ≥2：PET / CT（可选融合切换）；滚轮切层、窗宽窗位基础可用
   - 右侧病灶列表（可空）+ ROI 工具区；布局对齐 UI_STYLE 线框
3. **半自动 ROI**：
   - 在 PET 视口点种子 → 阈值/区域生长（实现自选，须可复现）→ 生成 ROI 轮廓
   - 支持人工改轮廓或删重建；每次写入/变更：`lesion`（`draft→proposed`）+ `measurement.roi_ref` + `audit[]`
   - ROI 持久化为本仓相对路径文件（如 `data/rois/<exam_id>/<lesion_id>.json` 或 mask）；路径写入 `roi_ref`
4. **示意数据路径**：若无真实 DICOM，提供 `fixtures/` 或文档步骤用合成/公开样例跑通；UI 标明「示意数据」
5. **README / 启动**：根 README 或 `apps/petfollow-lymphoma/README.md` 写清如何启动与导入；Pack 状态表更新本包为「已提交待人工验」

## 技术取舍（默认）

- 单机、RTX 3060 友好；Python 桌面（Qt/PySide）或本地 Web 二选一，**选一种写完**，禁止半套两套
- 影像：`pydicom` + `SimpleITK`（或等价）读 DICOM；不做 PACS
- ROI：种子 + SUV 相关阈值生长即可，不要求深度学习分割
- 数据目录与 Pack 01 examples 可并存；运行时写出的 exam/lesion/measurement 必须能过 Pack 01 schema 校验

## 验收 checklist

- [ ] 能导入一对 PET+CT（真 DICOM 或标明的示意数据）并生成合法 `exam`
- [ ] 窗口标题含「淋巴瘤 PET 随访原型」；顶栏原型条常驻
- [ ] 视口为主 + 右侧列表；深色临床壳；无竞品商标；无聊天主路径
- [ ] 半自动 ROI：点种子→出轮廓→可改→落盘；`roi_ref` 非空；`status=proposed`；有 `audit`
- [ ] 未实现 SUVmax/最长径自动填数（可留空 `null`）；无缓解/Deauville UI
- [ ] 无外部产品仓依赖；启动说明可读

## 可复制提示词（整段贴进 Codex）

```text
你在仓库 JennyTuan/DMT 工作。只做 docs/packs/02-import-viewer-roi.md 写明的 Pack 02。Pack 01（schemas/v0）已 PASS，禁止改 schema、禁止扩 Pack 01。

背景：独立新仓第一刀 = 淋巴瘤 FDG PET-CT 治疗后代谢随访院内试用原型（模块 petfollow-lymphoma）。DMT 只是伞仓名。必须遵守 docs/UI_STYLE.md 与 docs/CODEX_BRIEF.md。

任务：
1. 实现本地导入：选择含 PET+CT 的 DICOM 目录（或 fixtures 示意数据），写出符合 schemas/v0 的 exam（pet_series_ref、ct_series_ref、attenuation_corrected、prototype_banner 恒为原型声明）。
2. 实现阅片壳：窗口标题含「淋巴瘤 PET 随访原型」；顶栏常驻「原型·不可用于临床诊疗决策」；中央 ≥2 视口（PET/CT，可加融合切换）；右侧病灶列表 + ROI 工具；深色高密度临床风，禁止海外 AI demo 大留白与聊天助手主路径。
3. 半自动 ROI：PET 视口点种子 → 阈值/区域生长 → 轮廓可编辑；创建/更新 lesion + measurement（roi_ref 指向本仓 ROI 文件；suv_max 与 longest_diameter_mm 本包保持 null）；状态机 draft→proposed，audit 必写。
4. 技术栈在 Python 桌面（Qt/PySide）或本地 Web 中择一做完；单机可跑；用 pydicom/SimpleITK 或等价；不要云推理、不要付费权重、不要 submodule 其他产品仓。
5. 更新根 README：Docs 表与 Pack status 写入 Pack 02；给出启动/导入步骤。若用示意数据，UI 标明「示意数据」。

硬禁：改 Pack 01 契约；SUVmax/最长径算法（Pack 03）；先验配对与报告草稿；Deauville/Lugano/缓解/恶性；多病种平台壳；联影等商标仿品。

做完后列出改动文件清单，并按 Pack 02 验收 checklist 逐条自检。
```
