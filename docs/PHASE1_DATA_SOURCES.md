# Phase 1 真实病例来源核查（2026-11-03）

目标来自 V2.0 修订版第 6–7 页：20 例包含基线和中期复查的真实脱敏 DLBCL/cHL PET/CT，每例 3–5 个靶病灶，两名核医学科医师盲测，主任医师复核配对金标准。单次检查或仅有报告文本不能替代该队列。

| 来源 | 已核实的内容 | 对 20 例双期验收的适用性 |
| --- | --- | --- |
| [Zenodo 国际 TMTV 基准集](https://zenodo.org/records/13255214) | 开放数据。说明文件列明 20 例 DLBCL、20 例滤泡性淋巴瘤和 20 例 Hodgkin；每例有 PET/CT DICOM、专家审定 VOI 与参考表。参考说明和表格已保存到本机 `data/public/tmtv/`。 | 可用于单期导入、VOI 和定量验证；不是同一患者的基线＋中期配对。约 2 GB 的 B20 影像包在当前网络仅约 30–40 KB/s，完整下载尚未完成。 |
| [TCIA AHOD0831](https://www.cancerimagingarchive.net/collection/ahod0831/) | 165 名高风险 Hodgkin 患者、多个检查时点、PET/CT DICOM；[TCIA 说明](https://dev.cancerimagingarchive.net/collection/ahod0831/)要求通过 NCTN Data Archive 申请原始影像访问。 | 与 cHL 双期目标较接近，但影像受控访问；需有获批账户及项目用途。不能绕过访问流程。 |
| [TCIA CALGB50303](https://www.cancerimagingarchive.net/collection/calgb50303/) | DLBCL 临床试验影像，155 名患者、多个研究；原始影像列为 NIH 受控访问。 | 潜在 DLBCL 双期来源，待授权和逐例筛查 PET/CT 时间点。 |
| [TCIA FDG-PET-CT-Lesions](https://www.cancerimagingarchive.net/collection/fdg-pet-ct-lesions/) | 900 人、1,014 次检查，含淋巴瘤等多癌种 PET/CT 与病灶标注；页面列有可公开下载的去面部影像与受控原始影像。 | 存在重复检查，但公开临床表只标记「lymphoma」，未确认 DLBCL/cHL 亚型、基线＋中期时点及足够 20 例符合条件。不可将 1,014 次检查当成 1,014 组双期病例。可另作导入与分割测试。 |
| [LymphAtlas 仓库](https://github.com/SuperD0122/LymphAtlas-) | 论文描述多检查数据，但仓库 README 明确写明数据目前未公开。 | 当前不能下载和计入验收。 |

用户确认目前没有院内脱敏病例或获批的受控数据权限。下一步：先用开放基准集验证导入和量测；若后续取得 AHOD0831 或 CALGB50303 授权，按患者、时间点、PET/CT 双模态、定量参数和专家标注逐例筛选。20 例的临床耗时与正确率指标必须由实际医师按盲测协议产生，不能用公开影像本身推断达标。
