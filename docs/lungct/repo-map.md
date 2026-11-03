# T00 仓库盘点与边界（2026-11-03）

执行依据：`spec/LungCT_Codex_Spec_v1.0.md`，用户要求按 T00→P0 执行，保留 PET。

## 实际起点

本轮开始 HEAD 为 `7f50275`，工作树只有 `.git`。按用户最新要求，从本机 `DMT-backup-before-restart-20261103` 恢复 PET 源码、测试及本地环境/数据；并非假设空仓库没有既有资产。恢复前备份包含尚未提交的 PET Web 实现，全部保留。当前分支 `codex/lungct-p0`。

| 模块 | 实际实现 | 肺结节复用边界 |
|---|---|---|
| apps/petfollow-lymphoma/geometry.py | ImageGeometry，LPS 原始层面映射 | 直接加载只读几何类；外围增加更严格的 CT 验证，不改变 PET |
| imaging.py | PET+CT 成对导入，存在缺几何时按 InstanceNumber 回退 | 不复用导入策略；肺 CT 禁止回退，独立白名单导入 |
| mpr.py | 正交冠/矢状/MIP 切面 | 借鉴显示间距；P0 仅患者冠状定位小窗，不暴露完整 MPR |
| web/server.py、web/client | Flask + React/Canvas，本机 8765 | 沿用 Flask/PNG/Canvas；独立入口 8766，无 PET 页面改造 |
| roi_store.py、schemas/v0 | PET ROI、SUV、跨期病灶状态 | 不混用；肺 CT 独立 schema、SQLite、追加修订/快照 |
| suv/diameter/pairing/report_draft | PET 专用量化、配对、报告 | 保留原实现，肺 CT 不调用 |
| 模型 | 无 MONAI/PyTorch、无肺结节权重 | 新建可替换离线适配器；真实验收独立阻塞 |

## 机器与入口

Windows；Python 3.13.15；Intel i7-11800H；物理内存 34,077,446,144 bytes；RTX 3060 Laptop 6144 MiB（nvidia-smi），驱动 581.32。现有环境有 numpy、pydicom、Flask、Pillow、jsonschema、PySide6；没有 torch/monai/scipy。

PET 启动：`.\.venv\Scripts\python.exe apps/petfollow-lymphoma/web/server.py`（127.0.0.1:8765）。PET 基线：`evidence/T00-pet-baseline.txt`、`evidence/T00-pet-contract.txt`。沿用已有前端构建产物；源码构建命令在根 README。

肺 CT 计划入口：`.\.venv\Scripts\python.exe -m apps.lungct.server --enable-lungct`（127.0.0.1:8766）；不开开关不启用。数据独立位于 `data/lungct`，项目隔离，运行期无下载、遥测或上传。PET 文件不作为肺结节真实验收样本。

## 支持格式与样本清单

仅经典单帧 CT Image Storage，Implicit/Explicit VR Little Endian，单通道 MONOCHROME1/2，成人胸部非增强、厚度 (0,2.5] mm。按位置沿法向排序；方向、重复位置、间距、倾斜、缺层、跨序列及 UID 冲突执行门禁。来源/授权/脱敏/像素烧录核查必须登记。

| 样本 | 可用性 | 可证明 / 不可证明 |
|---|---|---|
| 现有 PET 合成及公开病例 | 本地恢复、Git 排除 | PET 回归；不证明肺 CT 检测 |
| lungct 合成 DICOM 体模 | 工单 T01 生成 | 几何、10/6 mm 径线、拒绝条件；不证明真实模型 |
| R-017 合成候选 | 仅测试注入，不是生产 AI 结果 | 3 AI + 1 人工状态计数、导出审计 |
| 获准肺 CT + 可核查结节参考 | 尚未提供/登记 | A04 阻塞，不能用 PET 数据或合成样本代替 |
| MONAI 0.6.9 权重 | 本地不存在 | A04 阻塞；存在下载入口不代表已运行 |

## 领域与接口

项目→研究受试者→检查→序列；run→原始 finding→追加 revision；draft 绑定一个 series 和一个 run/人工模式；snapshot 冻结采用的修订及原始记录；export 绑定同项目快照集合。finding_id 不是跨期病灶 ID。SQLite 写事务防止并发覆盖，修订采用 expected_revision_id，所有读取校验所属项目。模型框用于定位；测量只接受同一源层面的物理端点。

合成验收与真实推理证据分栏，A04 未通过时 T04/T06/M2 均不标完成，T07 不代填结果。
