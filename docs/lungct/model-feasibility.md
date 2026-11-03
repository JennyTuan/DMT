# T04 模型可行性（2026-11-03）

结论：离线接入代码与错误状态协议已实现；**A04 阻塞，真实模型适配器未运行验证，不能发布 AI 科研版**。

已核官方源：
- [MONAI 0.6.9 许可](https://huggingface.co/MONAI/lung_nodule_ct_detection/blob/0.6.9/LICENSE)：Apache-2.0；获准渠道提供 models/model.pt（约 83.7 MB）。本地未下载/预置权重，无可报告的权重 SHA-256。
- [模型元数据](https://huggingface.co/MONAI/lung_nodule_ct_detection/blob/0.6.9/configs/metadata.json)：MONAI 1.4.0、PyTorch 2.4.0；现有 Python 3.13 PET 环境不安装这些依赖，另建 Python 3.11 模型环境。
- [推理配置](https://huggingface.co/MONAI/lung_nodule_ct_detection/blob/0.6.9/configs/inference.json)：RAS、0.703125/0.703125/1.25 mm、HU [-1024,300]、阈值默认 .02、NMS .22、滑窗 512×512×192；输出框映射回 LPS 后关联源片。
- [模型说明](https://huggingface.co/MONAI/lung_nodule_ct_detection/blob/0.6.9/docs/README.md) 中 GPU 内存描述是训练/导出条件，不能直接当成本机推理门槛。RTX 3060 Laptop 6 GB 的实际峰值、速度、是否 OOM 均未验证。

实现：模型调用使用本机已预置的 bundle，检查版本、读取权重摘要，禁止运行期联网下载。严格加载状态字典（weights_only），错误不会降级为成功零候选。任务排队/运行/成功/失败分别落盘；同请求去重，重算新分支不覆盖原始结果或人工修订。

阻塞解除必须同时具备：获准本地权重 + 兼容运行环境 + 经登记授权且有参考结节的真实肺 CT + 人工核对候选位置。执行并提供真实 run_id、输入/权重/预处理摘要、model_to_lps、耗时、硬件峰值和脱敏截图；这些字段当前均不虚构。

现有 ProtocolFixture 仅在 tests/lungct/test_model.py，生产入口无法选用。其成功空集只用于 A05 状态机验证，不构成 A04。
