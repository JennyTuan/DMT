# DMT

独立新仓。第一刀交付：**淋巴瘤 PET-CT 治疗后代谢随访**院内试用原型（非注册、非多模态诊断平台）。

- 口头名：淋巴瘤 PET 随访原型
- 模块代号：`petfollow-lymphoma`（本仓内目录/命名空间；不继承其他仓库）
- 约束：本机 RTX 3060；开源优先；每屏常驻「原型·不可用于临床诊疗决策」

## 给 Codex

1. 读 [`docs/CODEX_BRIEF.md`](docs/CODEX_BRIEF.md)
2. 按刀序只做当前包：从 [`docs/packs/01-data-contract.md`](docs/packs/01-data-contract.md) 开始
3. 不要扩多癌种 / Deauville·Lugano / 恶性判定 / 真实注册材料

## 状态

| 包 | 内容 | 状态 |
| --- | --- | --- |
| 01 | 数据契约（Exam / Lesion / Measurement / proposed 状态机） | 待 Codex |
| 02 | 导入 + PET/CT 阅片壳 + 半自动 ROI | 未开 |
| 03 | SUVmax + CT 最长径 + 可改留痕 | 未开 |
| 04 | 先验配对 + 描述性报告草稿 + 质量门 | 未开 |
