# 肺 CT P0 验收记录

日期：2026-11-03；分支 `codex/lungct-p0`。M1 人工工作站内部演示闭环通过；M2 完整 AI 科研版尚待 A04 人工核对与真实链路验收；M3 研究者价值试验未执行。

环境：Windows / PET 与人工测试 Python 3.13.15；独立模型 Python 3.11.16、MONAI 1.4.0、PyTorch 2.4.1+cu121、NumPy 1.24.4；RTX 3060 Laptop 6 GB；Edge + Playwright，1440×900 和 1280×800。PET 代码保留，模型依赖不进入原 PET 环境。

| 项 | 结果 | 证据与范围 |
|---|---|---|
| A01 导入 | 通过 | test_import：薄层与定位像、乱序、去重、项目边界、UID/受试者冲突、几何/语法拦截；浏览器导入 |
| A02 定位 | 通过（合成几何） | test_viewer 与浏览器：各向异性/逆向、LPS 往返、源层/左右、缩放返回、延迟加载拒绝错层编辑 |
| A03 径线 | 通过 | test_review + 浏览器 10.0/6.0 mm；误差 ≤0.1 mm；重绘长径不会保留旧短径 |
| A04 真推理 | **未整体通过** | 公开权重/环境/NLST 真 CT 真实运行通过；低内存两次均 7 候选，约 30 s，峰值分配 1.58 GiB；仍缺授权人员核查与应用真实闭环，见 model-feasibility.md |
| A05 模型状态 | 通过（协议故障注入） | test_model：未配置/失败/null 与真实成功空集/0 语义分开；缺权重、OOM、部分结果、重启中断、重复请求 |
| A06 R-017 | 通过（工程用例） | T06-R017.json：3 个协议候选 + 1 人工观察；确认 2/排除 1/存疑 1；检查 1/导出结节 2/审计 4；pending 拦截 |
| A07 修订 | 通过（工程用例） | 修改、撤销、重开、重算分支、进程恢复、过期写拒绝、旧快照摘要稳定；浏览器重开恢复病例 |
| A08 导出 | 通过 | test_export：草稿排除、零确认分母、CSV BOM/null、哈希/项目校验、落盘失败、编号回查；浏览器导出 |
| A09 隔离 | 通过（合成与工程边界） | PHI/未确认像素拦截；socket 禁网人工导入至导出；浏览器非回环请求阻断；白名单包无姓名/路径/像素。真实病例授权人员检查仍须单列 |
| A10 中文操作 | 通过（自动化与截图核查） | 两尺寸全流程；键盘输入焦点保护；按钮/保存状态可见。不是 5 位研究者试用结论 |

## 运行命令与文件

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/lungct -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe schemas/v0/test_contract.py -v
.\.venv\Scripts\python.exe tools/lungct/make_synthetic.py --output data/lungct-demo
.\.venv\Scripts\python.exe tools/lungct/acceptance_r017.py
& 'C:\Users\STN\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' tools/lungct/browser_qa.cjs
```

`evidence/T06-unit.txt`：32/32；`T06-pet-regression.txt`：132/132；`T06-pet-contract.txt`：8/8。PET 测试的原有 ResourceWarning/弃用警告保留在日志内，不记为新失败。

合成样本仅首次在空输出目录生成；已有样本时跳过生成。浏览器运行前启动 `--data-dir data/lungct-qa-v2 --allow-root D:\STN02\DMT\data\lungct-demo`，该数据仅为合成体模。`T06-browser.json` 记录非回环请求为 0、无非预期错误；预期 400 对应未处理观察的结案拦截。三张 `T06-synthetic-*.png` 是最终截图；`T06-browser-failure.png` 保留旧失败现场，不充作通过截图。

R-017 样例包在 `evidence/R017-synthetic-export/`；它验证结构、数量和追溯，明确不作为 A04。真实 DICOM、权重、环境和数据副本只在忽略的 `data/` 或独立虚拟环境内，不进入版本库。

## 未验证和限制

公开病例实际推理只是一次技术复现，不能报告临床准确率、外部泛化或本地人群效果。A04 的授权人员像素检查/候选确认记录须由实际检查者签署；Codex 的图像查看、自动参考匹配和源数据读者标注分别记录，不相互冒充。T07 的 5 人/12 例尚未实施。没有提前开发 P1/P2。
