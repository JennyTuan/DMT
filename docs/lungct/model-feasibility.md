# T04 模型可行性与真实运行（2026-11-03）

**权重、环境、公开病例和真实推理的技术问题已解决。A04 仍缺实际人员的像素/病例确认、候选位置核对，以及批准后的真实应用闭环；不能勾选整体通过。**

此前仅查到公开模型资料，未主动下载验证就把本机资源缺失列为外部阻塞，调查不充分。本轮已修正；以下均为真实执行记录，测试适配器未参与。

## 来源和固定版本

- [MONAI 模型](https://huggingface.co/MONAI/lung_nodule_ct_detection/tree/7226a40a4c3713f7d5469559b7f2fc296fd54825)：bundle 0.6.9，固定修订 `7226a40a4c3713f7d5469559b7f2fc296fd54825`，Apache-2.0；权重 83,709,381 字节，SHA-256 `b5e79231466adae93a6fe8e8594029e9add142914e223b879aa0343bb2402d01`，与发布方 LFS 摘要一致。
- 原始环境 MONAI 1.4.0 / torch 2.4.0；本机 Windows 实测 2.4.0 导入 fbgemm.dll 报 WinError 126。[PyTorch 2.4.1 官方记录](https://github.com/pytorch/pytorch/releases/tag/v2.4.1)明确修复此问题，故登记使用 2.4.1+cu121 / torchvision 0.19.1+cu121；Python 3.11.16、NumPy 1.24.4、MONAI 1.4.0。独立 `.venv-lungct-model`，PET 环境未改变。
- [NLST 公共 CT](https://www.cancerimagingarchive.net/collection/nlst/)（DOI 10.7937/TCIA.HMQ8-J677，CC BY 4.0）与 [LIDC-annot-NLST501 人工标注](https://portal.imaging.datacommons.cancer.gov/analysis_results/lidc_annot_nlst501/)（DOI 10.7937/y2dx-e334，CC BY 4.0）。只下载 NLST-100206 的一个 CT 序列和一位读者的 SEG。参考中 6 个 MANUAL segment 仅用于输出后坐标对照，自动 Lung mask 不作为结节真值，参考不输入检测器。
- 初选 LIDC-IDRI-0001 的 ContrastBolusAgent=IV，被筛除；没有篡改增强标签。NLST 为成人筛查来源，公开影像人口年龄范围 43–75。成人/筛查/非增强判断有来源支持，但本例年龄和增强字段为空；病例级确认仍由研究者完成，不把空字段等同于已证实非增强。

## 病例与隐私

CT 160 层，512×512，层厚/层间距 2 mm，像素间距 0.6640625 mm，倾斜 0°，最大间距误差约 1.4e-14 mm。下载逐文件核对发布对象大小/ETag，登记 SHA-256。原始文件不变；独立 intake 副本清除研究姓名/检查号、PN 与私有字段，逐层确认 PixelData 字节哈希不变。

入模文件集摘要：`ab5587b203be92373fedc6922e4219ccfab4057c26128ab3f3bf3e5ecf8d753f`。清理映射、原片和参考留在忽略的 `data/lungct-assets/nlst100206/`。Git 仅提交脱敏运行清单/参数/摘要，不提交图像、DICOM、参考掩膜或权重。

本例 PatientIdentityRemoved=YES，BurnedInAnnotation 未填写。Codex 已查看覆盖 160 层的四张拼图，未见身份文字；这不冒充授权人员的像素核查。因此只做隔离的离线适配器资格实验，没有填写应用的 pixels_checked=true，没有写入应用病例数据库，没有伪造研究者身份或完成快照。

## 真实结果

硬件：RTX 3060 Laptop，独立显存 6 GB。阈值固定 .02；RAS、0.703125/0.703125/1.25 mm、HU [-1024,300]、NMS .22、overlap .25、CUDA AMP。标准配置采用发布方 512×512×192 滑窗；低内存配置显式改为 256×256×96，分别登记配置哈希。

| 实验 | 耗时（含装载/预处理/对照） | 候选 | PyTorch 峰值分配 | 人工参考范围内的候选中心 |
|---|---:|---:|---:|---:|
| standard，qualification-01 | 131.906 s | 8 | 9,521,035,264 bytes（8.87 GiB） | 2 |
| low-memory，qualification-02 | 30.015 s | 7 | 1,699,881,472 bytes（1.58 GiB） | 2 |
| low-memory 重复，qualification-03 | 30.015 s | 7 | 同上，详见清单 | 2 |

标准配置峰值超过独立显存，不能据此声称只需 6 GB；Windows 共享内存机制可能参与，未单独测量。低内存配置峰值预留 2,006,974,464 bytes（1.87 GiB）。两次低内存实验的候选数组和 model_to_lps 完全一致。配置改变会改变候选（8→7），不声称两配置检出表现等价，也不静默切换配置。

重复实验 ID：`qualification_e130f720b3134a238dc4dbca2d5e12cd`，是独立实验 ID，**不是应用 run_id**。配置摘要 `ffed4be32478863defee120c120c1a69924a95933734b8748f4dc97f3bd2eb70`；代码摘要/软件版本在清单。候选 3（零基序号）对应源索引 131（界面 132/160），中心距参考 segment 2 体素质心约 0.952 mm；另一匹配源索引 121，约 0.068 mm。只检查位置对应，不报告灵敏度、假阳性率或准确率。

证据：`evidence/T04-real-inference.json`、`T04-real-inference-01.txt` 至 `03.txt`、`T04-public-intake.json`。本地 `data/lungct-assets/nlst100206/review-location.png` 展示原片、8 倍像素放大、青色真实模型框和黄色该层人工掩膜边界。全部候选和变换在本地实验 JSON。推理开始前禁止进程 socket 连接；未调用远程模型。

## 复现命令

仓库根目录执行。首次准备需联网；运行使用本地资源。下载工具、模型、PET 三套环境独立。

```powershell
uv venv .venv-lungct-model --python 3.11
uv pip install --python .venv-lungct-model/Scripts/python.exe torch==2.4.1 torchvision==0.19.1 --index-url https://download.pytorch.org/whl/cu121
uv pip install --python .venv-lungct-model/Scripts/python.exe -r apps/lungct/requirements-model.txt
uv venv data/lungct-download-env --python 3.11
uv pip install --python data/lungct-download-env/Scripts/python.exe idc-index
.\.venv\Scripts\python.exe -X utf8 tools/lungct/prepare_public_case.py
.\data\lungct-download-env\Scripts\python.exe -X utf8 tools/lungct/prepare_nlst_case.py
.\.venv\Scripts\python.exe -X utf8 tools/lungct/inspect_public_case.py
.\.venv-lungct-model\Scripts\python.exe -X utf8 tools/lungct/qualify_real_model.py --profile low-memory --output data/lungct-assets/nlst100206/qualification-new.json
```

每次用新输出名保留旧实验。本机 uv 路径为 `C:\Users\STN\.local\bin\uv.exe`。IDC 包在 Windows 用 `-X utf8`，默认 GBK 读取发布包 SQL 曾失败，已解决。IDC S3 下载慢时改用官方 GCS 镜像，核对同一对象，没有改变数据来源。

人工确认后，应用使用 `--model-bundle data/lungct-assets/monai-0.6.9 --model-profile low-memory`，在正常导入/Run/复核/快照/导出路径补足 T06 真实证据。ProtocolFixture 仍只供测试，生产入口不能选用。

## A04 剩余项

2026-11-05 更新：O001 已在聊天中确认全片像素核查及成人非增强胸部筛查来源条件；已据此完成正常应用入库。记录在本地 `human-acceptance-O001.json`、`application-import-O001.json`，项目 `NLST-100206`、病例 `R-001`。以下第 1 项已完成；第 2、3 项仍待用户亲自操作的新应用 Run、位置核对与导出结果。

1. 实际授权检查者完成像素检查和本例成人胸部/非增强来源确认，记录代号、时间、依据。
2. 人工核对至少一个真实候选的源片位置，登记采用的 qualification/run、候选与参考对象。
3. 获准入库后跑应用 Run 至人工复核、快照、导出，保存真实工作站证据。

这些是具体的验收记录，不再是缺权重、缺数据、环境跑不起来。人的核查不能由 Codex 代签；T07 用户试验另行执行。
