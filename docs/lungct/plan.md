# 肺结节 CT P0 执行计划

Goal: 保留 PET，交付单次 CT 人工科研工作流，并接入可验证的离线模型协议；真实推理缺条件时如实阻塞。
Spec: `spec/LungCT_Codex_Spec_v1.0.md`。
Architecture: 独立 Flask/Canvas 入口，复用 PET ImageGeometry；SQLite 事务、原始来源映射、追加修订与冻结快照。保持 PET 原文件不变。

## 全局约束与裁定

- 用户已指定设计和执行顺序，本计划是施工展开，不增设方案审批。
- 恢复 PET 是最新请求的必要前提；本轮分支与上一轮清空 main 分开。
- 沿用 Flask 和 Canvas，肺入口采用原生 ES module 小前端，避免改动 PET React 构建；并非迁移 PET 框架。
- 每个工单先写验收测试，观察缺功能失败，再实现并运行。证据与台账保留在 docs/lungct，不删除用户要求的验收记录。
- 只做 P0；没有自动分割、肺叶模型、三维、纵向随访或报告诊断。

## 依赖预检

T00→T01: schema 的 project/series/slice_key 对应导入持久化键。
T01→T02: geometry、源切片键与 HU 数组；PNG 只显示，不用于测量。
T02→T03: 点选从 Canvas 逆变换到源像素，再转 LPS，修订引用同一 slice_key。
T01→T04: 只允许质控通过的 series；失败不能发布候选；模型 LPS 输出回到源片。
T03→T05: 导出只读冻结快照、纳入确认项，保留零确认检查及全部审计。
T02–T05→T06: 人工链可先集成，A04 阻塞使 T06 只能部分验证。

## 工单

- [ ] T00: 恢复盘点、基线、领域契约、模型可行性。证据：PET unittest/contract、启动 HTTP 200、文件摘要一致。
- [ ] T01: `dicom_io.py geometry.py repository.py service.py`；`test_import.py` 验证 A01 + 输入隐私、几何门禁。顺序/去重/不同项目/UID 冲突/定位像/缺间距/非均匀/左右。
- [ ] T02: `viewer.py server.py static/*`；`test_viewer.py` 验证源切片回查、患者冠状图、各向异性/逆向方向的往返误差；浏览器两尺寸交互。
- [ ] T03: `review.py service.py` 与 UI；`test_review.py` 验证 A03/A06/A07 人工路径、10/6 mm、缺测原因、过期修订拒绝、撤销/重开、快照不变。
- [ ] T04: `model.py` 离线固定配置适配器、任务状态与错误；`test_model.py` 仅证明协议与降级；A04 真实数据/权重/人工核对独立阻塞。
- [ ] T05: `export.py` 与预览 UI；`test_export.py` 验证 A08/A09、CSV BOM/空值/哈希/白名单、零确认分母、项目边界、落盘事务。
- [ ] T06: 全套 unittest、浏览器 1440×900/1280×800、PET 回归、README/acceptance；新上下文全分支审查。未达到 A04 不宣称 AI 版通过。
- [ ] T07: 依赖 T06 和真实研究者，保留空白研究记录模板与招募条件，不填写假结果。

## 每项执行合同

新增测试首先运行 `python -m unittest discover -s tests/lungct -p test_<ticket>.py -v`，预期缺功能失败；实现后同命令预期通过。提交工单涉及的源文件、测试、证据、`tickets/Txx.md`（修改文件、命令、结果、剩余风险）。总回归分开运行 PET 与 lungct，避免旧 tests 导入路径污染。

Review Focus: 输入授权与反序列化边界；DICOM 错侧/错层和不规则几何；模型空间回写；修订/快照不可变；项目隔离；日志与导出 PHI；浏览器焦点/标记陈旧/测量屏幕逆变换。
