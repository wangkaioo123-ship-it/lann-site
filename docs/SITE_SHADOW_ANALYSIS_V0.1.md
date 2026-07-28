# 候选场地影子分析 v0.1

## 目的

为 `lann-bot → lann-site → 人工确认 → lann-dashboard` 的最小链路提供稳定的分析契约。本阶段只生成本地影子结果：

- 不修改 dashboard。
- 不写飞书或其他正式业务数据。
- 不自动改变客户、场地或匹配状态。
- 不把人工判断伪装成资料事实。
- 不把经营收益风险表达为盈利保证。

## 链路边界

1. `lann-bot` 接收 PDF、表格、语音和用户补充，生成 `lann-site-neutral-input/v0.1`；它不提取选址事实、不形成判断。
2. `lann-site` 接收中性包，保留原文件、飞书来源、文字补充、转写状态、请求/确认状态和禁止外写边界。
3. `lann-site` 完成文件解析、事实提取、判断结构化和缺口分析后，才形成内部分析输入。
4. `lann-site` 校验引用、计算决策期、汇总阶段、风险、缺口和下一步。
5. 输出先由负责人确认；v0.1 明确 `writeback_allowed=false`。
6. dashboard 集成和正式写回不在本阶段范围。

## Bot 中性输入

Schema：`ai/schemas/lann_site_neutral_input.schema.json`

中性输入只包含：

- 项目标识和 Bot 项目状态。
- 飞书来源元数据。
- 原文件存储引用和归档失败信息。
- 语音转写状态及已有转写文本。
- 用户文字补充。
- 是否请求分析和输入摘要是否确认。
- `dashboard_allowed=false`、`dashboard_attempted=false`。

转换脚本：`scripts/convert_neutral_site_input.py`

转换只完成接收和登记。没有真实解析器或人工结构化结果时：

- `facts=[]`
- `judgments=[]`
- `risk_assessments=[]`
- `customer_matches=[]`
- `analysis_status=待资料解析`
- 未转写语音、未解析文件和未结构化文字进入 `missing_information`

因此“Bot → Site 契约转换成功”不等于“PDF 内容已解析”或“选址分析已经完成”。

## 输入契约

Schema：`ai/schemas/site_shadow_analysis.input.schema.json`

输入分为七层：

| 层 | 说明 |
|---|---|
| `sources` | 原始资料及引用，记录可读取、缺失或不可读取 |
| `facts` | 资料可直接证实的事实，每条必须引用来源 |
| `judgments` | 王凯、分公司、工程或商务人员的判断，不能混入事实 |
| `stage_status` | 租金、工程初筛、经营勘察、专业工程勘察、合同工程确认分别记录 |
| `risk_assessments` | 风险类型、等级、原始表述、判断人和来源 |
| `customer_matches` | 客户状态与场地匹配状态分开记录 |
| `missing_information` | 当前仍缺的资料或结论 |
| `intake_control` | 上游契约、请求/确认状态和禁止 dashboard 写入边界 |

铺位图仅能进入可直接证实的事实，例如“目标铺位已标注”。动线、楼层或生意优劣属于判断，当前没有证据时不得输出评分。

## 输出契约

Schema：`ai/schemas/site_shadow_analysis.output.schema.json`

输出包含：

- 资料覆盖情况。
- 带来源引用的证据事实。
- 人工判断原文。
- 当前阶段及工程边界。
- 带限定语的风险判断。
- 客户/场地匹配汇总。
- 决策期和超期未决状态。
- 缺失信息和下一步行动。
- `human_confirmation_required=true`。
- `writeback_allowed=false`。

## 客户与匹配规则

- 客户状态、场地状态和匹配状态独立。
- “已放弃该场地”不自动改变客户对 LANN 项目的状态。
- 仍在考察该场地的客户按推荐时间排序。
- 普通决策期 14 天，紧急项目 7 天。
- 到期后标记“超期未决-待负责人确认”，不得自动写为“放弃”。

## 工程边界

- 前期工程初筛：判断是否存在已知阻断问题。
- 专业工程现场勘察：核实详细工程条件和改造风险。
- 签约前最终工程确认：把工程责任、条件和未决事项固化到合同。

三者必须分别记录。前期无阻断问题不等于最终工程确认。

## 本地运行

Bot 中性包转换：

```powershell
python -m scripts.convert_neutral_site_input `
  --input ai/evals/site_shadow_analysis/sijing_neutral_input.json `
  --output data/staging/site_shadow_analysis_sijing_internal_from_bot.json
```

生成“待资料解析”的影子输出：

```powershell
python -m scripts.build_site_shadow_analysis `
  --input data/staging/site_shadow_analysis_sijing_internal_from_bot.json `
  --output data/staging/site_shadow_analysis_sijing_from_bot.json
```

解析 Bot 已归档的真实 PDF，并生成带文件名和页码的审核稿：

```powershell
python -m scripts.parse_site_intake_pdfs `
  --input C:\path\to\input-package.json `
  --storage-root C:\path\to\site-intake `
  --internal-output data/staging/site_real_internal_input.json `
  --review-output data/staging/site_real_pdf_review.json `
  --review-markdown data/staging/site_real_pdf_review.md
```

解析器会校验文件哈希，逐页判断文字层覆盖，只抽取带明确标签的值。引用以“原文件名 + 页码”保留；调研报告的人口数字标记为报告口径，不视为完成外部交叉验证。图纸仅用于核验图面标注，不产生动线、楼层或经营优劣评分。

### 图文混合与异常文字层降级

真实资料解析 v0.2 增加逐页质量诊断：

- 文字层不足：页面可提取文字少于最低阈值。
- 文字层疑似乱码：异常字符比例超过阈值。
- 以表格为主：优先使用 `pdfplumber` 保留二维行列。
- 以图片或复杂图形为主：渲染页面后调用本机 Windows 简体中文 OCR，保留 OCR 行和词坐标。

OCR 只是一条降级证据链。OCR 单独命中的事实最高按中置信进入事实层；营销口径、版本不一致或无法可靠定位的结果按低置信进入 `manual_review_items`，不得进入正式事实。品牌落位图、铺位图只登记可视文字、铺号、面积、楼层和品牌标签，不产生动线、楼层优劣或经营判断。

本机启用 OCR：

```powershell
python -m scripts.parse_site_intake_pdfs `
  --input C:\path\to\input-package.json `
  --storage-root C:\path\to\site-intake `
  --internal-output data/staging/site_real_internal_input_v0.2.json `
  --review-output data/staging/site_real_pdf_review_v0.2.json `
  --review-markdown data/staging/site_real_pdf_review_v0.2.md `
  --enable-ocr `
  --baseline-review data/staging/site_real_pdf_review.json
```

Windows OCR 由 `scripts/windows_ocr_page.ps1` 调用系统已安装的 `zh-Hans-CN` 识别器，资料不上传外部服务。非 Windows 环境需提供等价本地 OCR 适配器；没有 OCR 时仍可完成文字层与表格解析，但审核稿必须明确 OCR 未执行。

### 图片与工程工作簿补充资料

图片和工程工作簿通过补充解析入口合并到既有内部输入和审核数据：

```powershell
python -m scripts.parse_site_intake_supplements `
  --input-package C:\path\to\input-package.json `
  --storage-root C:\path\to\site-intake `
  --internal-input data/staging/site_real_internal_input_v0.2.json `
  --review-json data/staging/site_real_pdf_review_v0.2.json
```

- 图片：校验归档路径、字节数和 SHA-256，保留飞书消息 ID；本地 OCR 的明确标签和值只进入待人工核验候选，低置信结果进入 `manual_review_items`，不据截图判断动线、楼层优劣或盈利。
- 工程工作簿：逐 sheet 读取 OOXML 单元格，保留 sheet、行号和单元格来源。LANN 标准要求、商场自由文本回复、机器归一化状态分层保存。
- 商场回复归一化状态仅允许“满足/有条件满足/不满足/信息不足”，始终标记为机器解释并等待人工确认；空白回复不等于满足，主观或含糊回复不得自动判定通过。
- 负责人确认的总体工程初筛状态不代表每一项都有商场书面证据；专业工程勘察和合同工程确认继续独立记录。

运行已完成结构化的固定验收样例：

```powershell
python -m scripts.build_site_shadow_analysis `
  --input ai/evals/site_shadow_analysis/sijing_input.json `
  --output data/staging/site_shadow_analysis_sijing.json
```

泗泾样例只用于验收规则。脚本不识别项目名称，也不包含泗泾专属结论。

## 当前缺口

泗泾真实中性包已验证 Bot → Site 接收、PDF与工程工作簿哈希校验、文字层/OCR识别、保守事实提取和来源引用。商务、总体工程阶段、经营判断和客户匹配已由负责人确认。当前仍缺：

- LANN标准工程要求已归档并识别33项，但“物业反馈/回复”列0/33填写；缺少逐项现场或商场书面反馈证据。空白不等于满足，也无法据此识别明确阻断项。
- 工程人员专业现场勘察和签约前合同工程确认仍待完成。
- L4品牌落位图的可视OCR仍未识别到租赁提案所列`L4015a`，需最新版带铺号平面图核对版本一致性；但租赁提案PDF已能证明L4/L4015a/260㎡。
- 调研报告的外部原始数据尚未交叉核验，人口等数字当前只能作为“报告口径”。
- 当前中性包已归档1张真实截图；路径、字节、SHA-256、尺寸和消息ID校验通过。本地OCR识别的L4015a与260㎡均与PDF一致，属于重复印证；低置信图面文字只进入人工核验。
