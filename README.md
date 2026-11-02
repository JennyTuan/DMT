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
| [Pack 02 导入、阅片与半自动 ROI](docs/packs/02-import-viewer-roi.md) | [本机启动与导入](#pack-02-本机启动与导入) · [桌面应用](apps/petfollow-lymphoma/) |
| [Pack 03 SUVmax+最长径+留痕](docs/packs/03-suvmax-diameter-audit.md) | **当前执行**：量测计算与可改数值史 |
| [`docs/CODEX_BRIEF_PACK1.md`](docs/CODEX_BRIEF_PACK1.md) | Supplementary Pack 01 notes |
| [`docs/UI_DIRECTION.md`](docs/UI_DIRECTION.md) | UI direction notes（以 UI_STYLE 为准） |

## Pack status

| 包 | 交付 | 状态 |
| --- | --- | --- |
| Pack 01 | [检查、病灶、量测、状态机及配对示例](schemas/v0/README.md) | PASS（f5a13ab） |
| Pack 02 | [本地导入、双视口、可编辑 ROI](apps/petfollow-lymphoma/) | PASS（77881ed） |
| Pack 03 | [SUVmax + CT 最长径 + 数值留痕](docs/packs/03-suvmax-diameter-audit.md) | BRIEF 已提交，待 Codex |

Later: 先验配对 → 描述性报告草稿 → 质量门

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

**复验。** 在同一环境下运行应用测试和只读契约测试。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe schemas/v0/test_contract.py -v
```

## For Codex

一次只做一个 pack。当前贴：[`docs/packs/03-suvmax-diameter-audit.md`](docs/packs/03-suvmax-diameter-audit.md) 文末「可复制提示词」。
