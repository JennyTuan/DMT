# 肺 CT 工作站界面方向 · 2026-11-05

用户选定：A（西门子 syngo.via）的数据组织，参考 C（联影）的控件层次和底部阶段导航。后续明确要求采用独立的深色配色与统一字体，避免沿用联影配色。

- 入口：左侧病例/检查结果表，右上所属序列，右下图像预览；患者与检查信息位于左下。列表选中状态与详情联动。
- 灰阶：石墨灰底（#171d24）、深钢灰面板（#232c36）、青蓝选中（#2d4859 / #86b5ca）、清楚的按钮边界与选中高亮；使用细分隔线组织信息，避免大圆角卡片和大间距。
- 流程：选择检查 → 肺结节分析 → 复核与测量 → 完成与导出。当前步骤使用浅灰高亮，右侧主按钮随任务状态改变。
- 导航只调用现有工作流程：质控不合格序列不能进入分析；分析中等待；无模型可人工复核；待复核项阻止完成；完成复核前保留整例浏览确认；导出只读取完成快照。
- 入口与阅片功能共用底部流程栏；流程导航不自动确认观察、不代替人工浏览确认、不伪造完成状态。

参考：西门子官方 syngo.via VB60 操作手册第 73 页；联影官方 uCT 528 肺部后处理展示。只学习组织、灰阶和控件层次，不使用厂商商标、图标或品牌皮肤。

https://doclib.siemens-healthineers.com/rest/v1/view?document-id=1088936

https://eu.united-imaging.com/en/product-service/products/ct/uct-528

实现：`apps/lungct/static/workstation-theme.css`；流程与业务状态在 `app.js`、`model-ui.js`、`review-ui.js`、`export-ui.js` 联动。

字体：Segoe UI Variable Text / Segoe UI，中文回退 Microsoft YaHei UI / Microsoft YaHei；正文 13px、常规字重，标题 16px / 600。步骤编号使用 12px 方形标记，避免细字和大号装饰数字。
