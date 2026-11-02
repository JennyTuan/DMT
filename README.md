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
| Editable SUVmax and CT diameter estimates with a local value history | Auto Deauville / Lugano / malignancy / response conclusions |

The name **DMT** must **not** be used to claim a multi-modality platform is already productized. Later modalities get their own modules and briefs.

## Docs

| Doc | Purpose |
| --- | --- |
| [`docs/LOCK.md`](docs/LOCK.md) | Product lock: build / don’t build / bans |
| [`docs/CODEX_BRIEF.md`](docs/CODEX_BRIEF.md) | Codex 总 BRIEF（命名 / 刀序 / 禁区） |
| [`docs/UI_STYLE.md`](docs/UI_STYLE.md) | 国产工作站信息密度 LOCK（界面包强制） |
| [Pack 01 数据契约](docs/packs/01-data-contract.md) | Exam / Lesion / Measurement / proposed |
| [Pack 02 导入、阅片与半自动 ROI](docs/packs/02-import-viewer-roi.md) | [本机启动与导入](#pack-02-本机启动与导入) · [桌面应用](apps/petfollow-lymphoma/) |
| [Pack 03 SUVmax、CT 最长径与留痕](docs/packs/03-suvmax-diameter-audit.md) | [试算、改数与复核](#pack-03-量测与数值留痕) |
| [Pack 04 先验配对 + 描述性报告草稿](docs/packs/04-prior-pairing-report-draft.md) | [关联、配对与导出步骤](#pack-04-关联上次与导出草稿) |
| [Pack 05 质量门与全流程验收](docs/packs/05-quality-gate-acceptance.md) | [人工验收清单](docs/ACCEPTANCE_MVP.md) · [残留风险条件](docs/RESIDUAL_RISK.md) |
| [`docs/CODEX_BRIEF_PACK1.md`](docs/CODEX_BRIEF_PACK1.md) | Supplementary Pack 01 notes |
| [`docs/UI_DIRECTION.md`](docs/UI_DIRECTION.md) | UI direction notes（以 UI_STYLE 为准） |

## Pack status

| 包 | 交付 | 状态 |
| --- | --- | --- |
| Pack 01 | [检查、病灶、量测、状态机及配对示例](schemas/v0/README.md) | PASS（f5a13ab） |
| Pack 02 | [本地导入、双视口、可编辑 ROI](apps/petfollow-lymphoma/) | PASS（77881ed） |
| Pack 03 | [SUVmax、CT 最长径估计、人工改数与数值留痕](docs/packs/03-suvmax-diameter-audit.md) | 已提交待人工验（509b771） |
| Pack 04 | [先验配对与描述性报告草稿](docs/packs/04-prior-pairing-report-draft.md) | 已提交待人工验（2eed4a7） |
| Pack 05 | [本地质量门与示意全流程验收](docs/packs/05-quality-gate-acceptance.md) | 已提交待人工验 |

## Pack 02 本机启动与导入

**原型·不可用于临床诊疗决策**

在可写的仓库根目录打开 PowerShell。以下命令已在 Windows、Python 3.13 上验证。首次安装需要联网，之后可离线阅片和保存。

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r apps/petfollow-lymphoma/requirements.txt
.\.venv\Scripts\python.exe apps/petfollow-lymphoma/main.py --demo
```

1. **打开检查。** `--demo` 会在本机生成并导入一对合成 DICOM（PET 21 层、CT 31 层），顶栏显示「示意数据」。平时可省略该参数，在窗口点「导入 DICOM 目录」，选择同一患者、同次淋巴瘤 FDG PET-CT 检查的 PET 和 CT 序列共同所在的目录。
2. **查看图像。** 两个视口独立切层，在图像上滚动鼠标或拖动下方滑块。上方可选显示预设，也可输入窗宽、窗位。两幅图的层号各自计数。
3. **生成并编辑 ROI。** 示意 PET 默认打开第 11 层。保持 65% 阈值，点击图像中央稍偏右的亮灶（原图像素 `x=104, y=90`）。青色线为轮廓。程序在当前层从种子向上、下、左、右生长，纳入与种子相连且像素值达到「种子值 × 阈值」的像素。窗宽窗位只影响显示。调阈值会重新生长；点「涂入」或「擦除」后可按住左键修改轮廓。
4. **保存与重开。** 填部位，点「保存 ROI」。点「＋ 新病灶」可另建条目。重新导入同一检查后，点右侧病灶行可恢复对应 PET 层和已保存的轮廓。界面下方显示最近保存时间。

**本地文件。** 检查包保存在 `data/exams/<exam_id>.json`，其中 `exam` 是检查对象。`pet_series_ref` 和 `ct_series_ref` 是稳定的序列标识。再次阅片需保留原始 DICOM。每次保存都用本仓 Pack 01 Schema 校验检查包，`measurement.roi_ref` 指向仓库内的 `data/rois/<exam_id>/<lesion_id>/<版本>.json`。初次保存记录 `draft → proposed`；每次修订另存掩膜、种子、阈值、操作者、时间和上一版引用。SUVmax 和最长径在 Pack 02 固定为 `null`（Pack 03 起填数）。`data/` 已排除在 Git 提交之外。

**导入范围。** 支持经典单帧、灰阶 DICOM，每次选择一套 PET 和一套 CT。遇到多个候选序列，请将所需的两套序列放入一个单独目录。增强多帧影像或当前环境无法解码的压缩影像，请从源端导出为未压缩的经典单帧序列。缺检查日期或时间会提示重新导出；仅缺时区时采用工作站本地时区。衰减校正标记缺失或矛盾时显示「未知」，明确未校正时显示「未校正」。这两种情况均按 v0 布尔契约写 `false`，并提示后续量测需复核。

## Pack 03 量测与数值留痕

1. **试算。** 按上节启动 `--demo`。在 PET 第 11 层用 65% 阈值点 `(104, 90)` 并保存 ROI。右侧应显示 SUVmax 约 **9.35**、CT 最长径估计约 **12.90 mm**。把阈值改为 80% 再保存，最长径应约为 **10.61 mm**。这些是 v2 合成数据的验收数值。
2. **改数和查历史。** 双击列表中的 SUVmax 或最长径，填写新值与修改依据，点「保存修改」。选中病灶后点「数值留痕」，可查前后值、操作方、时间、说明和 ROI 版本。重开同一检查会保留人工值。保存新轮廓会重算两项，旧值仍可追溯。
3. **复核。** 每项量测独立计算。衰减校正未确认、SUV 换算资料不足或 CT 无法对齐时，对应自动值留空，量测进入 `needs_review`。选中条目可见原因，人工改数仍保留复核状态。既有 Pack 02 ROI 重开后会补算；旧示例的 PET 单位是原始计数，只能补算 CT 最长径。

**量测口径。** SUVmax 取单层 ROI 内的最大体重标准化 SUV。支持有标定依据的直接 SUVbw（GML）或 BQML 体重法。BQML 的 START 路径要求能确定注射时刻、半衰期及共同采集起点；ADMIN 使用注射时的剂量。CT 最长径是 PET 轮廓投影到同参考系、覆盖该层面的 CT 后，投影内最远两个 CT 像素中心的距离。计算记录注明 CT 层号，可据 CT 复核。[DICOM PET 模块](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.8.9.html) · [DICOM 图像平面](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.7.6.2.html)

**留痕位置。** 每次自动填数、ROI 修订重算和人工改数，都写入 `data/measurements/<exam_id>.history.json`，按 `measurement_id` 分组。人工改数设置 `edited=true`。检查包内的 `measurement.audit[]` 仅记录状态转换。

## Pack 04 关联上次与导出草稿

1. **打开一对检查。** 沿用上面的 `--demo` 命令。首次载入会生成同一示意患者的基线与随访，各有一项可编辑的纵隔 ROI，默认显示随访并关联基线。「切至示意基线」和「切至示意随访」可切换影像。已手动清除的先验不会在下次载入示意数据时恢复。
2. **关联上次。** 对自有数据，先分别导入两次检查，再打开本次检查。点顶栏「关联上次」，选择同一患者较早的检查并保存。可重选，也可选「不关联上次检查」清除。更换先验会解除与原先验的病灶配对。
3. **配对病灶。** 在右侧「前后对照」选中本次病灶，在候选框选上次病灶，点「指定配对」。两侧获得同一跟踪号，列表显示本次、上次、差值和量测状态。没有对应项或数值时显示 `—`。示意病灶配对后的 SUVmax 差值约为 **−2.94**，最长径差值约为 **−5.89 mm**。「解除配对」断开当前关系，「新建跟踪号」给独立病灶分配标识。若调整会影响后续检查的既有配对，先在该随访中解除相关配对。
4. **编辑与导出。** 点顶栏「报告草稿」。上半部列出检查与病灶对照，下半部「描述」可编辑。「从当前量测重新生成」只替换上半部，保留手写段落。点「保存草稿」可供下次打开；「导出 Markdown…」将当前草稿另存为新的 UTF-8 `.md` 文件，首行固定为「原型·不可用于临床诊疗决策」。若量测或配对在保存快照后有变更，先重新生成。

**本地存储。** 两次检查仍保存在各自的 `data/exams/<exam_id>.json`。本次检查用 `prior_exam_id` 引用先验，人工配对的两条病灶共享 `lesion_track_id`。配对审计单独写入 `data/pairings/<本次exam_id>.json`（版本 1），记录时间、操作者、两次检查及病灶标识和跟踪号变更。草稿保存在 `data/reports/<exam_id>.json`（版本 1），分别保存生成区快照和手写描述。示意 DICOM 目录为 `data/fixtures/petfollow-demo-v2-baseline/` 和 `data/fixtures/petfollow-demo-v2/`。

## Pack 05 质量门与验收

用 `--demo` 载入示意检查，点顶栏「质量门」。列表按目标显示门控编号、级别、原因及动作。保存量测时核对衰减校正、SUV 换算依据、CT 对齐和 ROI 来源；失败的自动量测留空，待确认量测进入 `needs_review`。人工改数保留操作依据，程序不授予审核终态。

选择先验时核对检查归属。先验失效会阻断导出，可通过「关联上次」重选或清除。未配对病灶默认在导出前提醒；操作者可在「前后对照」对该条点「跳过本次配对」，也可撤销跳过。缺原型声明或命中禁词时，草稿窗口以红色列出阻断原因，修正后再导出。所有规则只在本机运行。

最新结构化快照在 `data/gates/<exam_id>.json`（版本 1）。`stage`、`checked_at` 和 `text_checked` 说明检查环节、时间及是否包含报告正文。顶栏查看的是已保存数据，报告窗口同时核对正在编辑的文字。导出时重新检查实际要写入的全文。门控快照不代替数值变更史或人工验收签字。

对已经由人工接受或拒绝的历史记录，质量门重新核对当前来源。若核对失败，导出会被阻断，原数值与终态审计保留。

**复验。** 在仓库根目录运行以下命令。第一条验示意全流程、未校正量测及先验失效后的阻断与修复。人工验收按[点击清单](docs/ACCEPTANCE_MVP.md)执行，逐项核对[六条残留风险条件](docs/RESIDUAL_RISK.md)。

```powershell
.\.venv\Scripts\python.exe tests/test_acceptance_mvp.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe schemas/v0/test_contract.py -v
```

## For Codex

当前范围和人工验收条件见 [Pack 05 质量门与全流程验收](docs/packs/05-quality-gate-acceptance.md)。
