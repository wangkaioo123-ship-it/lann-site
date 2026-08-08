# DEVELOPMENT_LOG.md — lann-site 开发日志

按时间倒序记录每次开发/修复内容，每次完成后在顶部追加。

格式：

```
## [日期] 标题
- 类型：功能 / 修复 / 文档 / 配置
- 内容：
- 改动文件：
- commit：
- 验证方法：
```

---

## 2026-08-08：选址资料只读初审

- 类型：功能 / 安全边界
- 内容：未确认资料包可以先解析 PDF 并生成待补信息，但必须保持 `dashboard_allowed=false`；正式确认后的工作台交接流程不变。
- 改动文件：`scripts/process_remote_site_handoff.py`、`tests/test_remote_site_handoff.py`、`DEVELOPMENT_LOG.md`
- 验证方法：运行远程交接和新店交接测试，确认未确认资料只携带 `--allow-unconfirmed` 做分析，不开放外部写入。

## 2026-08-07：远程新店候选自动分析任务

- 新增 Site 远程取件任务，从工作台中转区读取负责人已确认的 Bot 资料包和原件。
- 下载时复核文件摘要与大小，再复用现有新店交接脚本生成 `site_record/v0.1` 候选并回写工作台。
- 新增每分钟检查一次的 systemd 模板；任务只写 Site staging 和工作台候选区，不写飞书、不创建正式场地。
- OCR 默认关闭，只有服务器完成 OCR 依赖验收后才通过环境变量开启。

**验证方法：**
1. 单元测试覆盖资料落盘、分析函数调用、候选回写和路径越界拒绝。
2. 保留现有候选人工确认和正式场地写入边界。
## 2026-08-01 Site影子分析到Dashboard候选记录生成闭环

- 类型：功能/数据契约/测试
- 内容：新增统一候选记录生成器，将Site影子分析压缩为`site_record/v0.1`待审阅文件。多来源一致的铺位、楼层和面积可作为资料事实进入候选；冲突值不写入并转为待核验。场地阶段、负责人、场地性质、下一动作和工程状态继续保持负责人确认边界，不调用Dashboard、不修改飞书字段、不自动创建工作台字段。
- 改动文件：`scripts/build_site_record_candidate.py`、`tests/test_site_record_candidate_builder.py`、`docs/SITE_FIELD_SCHEMA_V0.1.md`、`DEVELOPMENT_LOG.md`
- commit：本次提交
- 验证方法：候选生成专项测试、`site_record/v0.1`契约校验、Site全量测试及Git差异检查。

## 2026-07-28 Site场地阶段与客户匹配状态收口

- 类型：数据契约/修复/测试
- 内容：将`site_record/v0.1`与影子分析的`current_stage/workflow_stage`统一限制为Dashboard现行8个场地阶段；泗泾场地阶段确认为“可推荐”，两位客户仍在考察只保留在`franchise_customer_decision`匹配摘要，不再影响场地阶段。中性包接收和PDF解析默认保持“待研判”，解析资料本身不推进业务阶段。场地下一动作、下一跟进日和固有卡点与客户跟进分离；会改变业务推进的AI建议继续使用既有字段信封表达为“AI提取候选事实/待负责人确认”，未新增同步架构。文档明确Dashboard只消费场地最小字段，客观无冲突事实可补齐、冲突不覆盖、推进字段只展示待确认更新建议，客户及详细证据留在各自系统。
- 改动文件：`ai/schemas/site_record.v0.1.schema.json`、`ai/schemas/site_shadow_analysis.input.schema.json`、`ai/schemas/site_shadow_analysis.output.schema.json`、`ai/evals/site_record/generic_candidate_record.json`、`ai/evals/site_shadow_analysis/sijing_input.json`、`ai/evals/site_shadow_analysis/README.md`、`scripts/build_site_shadow_analysis.py`、`scripts/convert_neutral_site_input.py`、`scripts/parse_site_intake_pdfs.py`、`tests/test_site_record_schema.py`、`tests/test_site_shadow_analysis.py`、`docs/SITE_FIELD_SCHEMA_V0.1.md`、`docs/SITE_SHADOW_ANALYSIS_V0.1.md`、`DEVELOPMENT_LOG.md`
- 本地样例：`data/staging/sijing_site_record_v0.1.json`同步修正为“可推荐”，场地下一动作改为待负责人确认建议并移除客户跟进日期；继续不进入Git。
- commit：本次聚焦本地提交（未push）
- 验证方法：泗泾本地候选通过`site_record/v0.1`校验；场地/匹配专项21项通过；全量75项测试通过；JSON、Python语法及Git差异检查通过。

## 2026-07-26 候选场地字段方案V0.1确认边界纠偏

- 类型：数据契约/修复/测试
- 内容：修正“只让负责人确认会改变业务状态的字段”边界。多份有效资料一致、无冲突的商场名、城市、L4/L4015a/260㎡改为`原始资料事实 + 无需确认 + confirmed_by=null`，允许工作台直接展示但不表达为负责人判断；从待核验项删除重复确认要求。`responsible_owner`改为可空的核心字段信封，因当前没有明确责任分配证据，泗泾样例设为`null/待负责人确认`，不再由“提供判断的人”推断“项目负责人”。`ownership_model`继续保持待确认。Schema和最小运行时校验器同步限制原始资料事实不得伪装成负责人确认。
- 改动文件：`docs/SITE_FIELD_SCHEMA_V0.1.md`、`ai/schemas/site_record.v0.1.schema.json`、`scripts/validate_site_record.py`、`tests/test_site_record_schema.py`、`DEVELOPMENT_LOG.md`
- 本地样例：`data/staging/sijing_site_record_v0.1.json`（不进入Git）
- commit：未提交
- 验证方法：泗泾样例通过契约校验；原有缺字段/AI伪确认负例及新增原始资料事实伪确认负例均按预期失败；字段专项 4 项、全量 72 项测试通过。

## 2026-07-26 候选场地正式字段方案V0.1

- 类型：数据契约/文档/测试
- 内容：新增面向Bot→Site→未来Dashboard的最小正式记录`site_record/v0.1`，以对象识别、当前推进、关键决策条件、判断与证据四层组织22个业务字段，其中10个核心必填。每个字段统一记录值、数据层级、确认状态、确认人和来源引用，严格区分原始资料事实、AI提取候选事实、负责人确认、AI经营判断和正式业务状态；AI候选必须待负责人确认且不能伪装为负责人确认。详细PDF/OCR/工程逐项证据继续留在Site内部审核数据。泗泾真实样例填入L4/L4015a/260㎡候选、当前有效商务条件、已确认工程/经营阶段、33项工程要求与0/33商场回复、5位客户状态及负责人经营判断，阶段保持等待客户决定，不自动升级确定立项。同步列出shadow直接复用、新增压缩及延后字段，不修改现有shadow schema和解析代码，不写Dashboard或飞书。
- 改动文件：`docs/SITE_FIELD_SCHEMA_V0.1.md`、`ai/schemas/site_record.v0.1.schema.json`、`scripts/validate_site_record.py`、`tests/test_site_record_schema.py`、`DEVELOPMENT_LOG.md`
- 本地样例：`data/staging/sijing_site_record_v0.1.json`（不进入Git）
- commit：未提交
- 验证方法：泗泾样例通过契约校验；删除场地ID、当前阶段或下一动作时校验失败；AI候选伪装负责人确认时校验失败；字段与真实数据一致性检查通过，全量71项测试通过。

## 2026-07-26 泗泾真实截图增量验收

- 类型：功能/真实资料解析/测试
- 内容：仅增量处理指定图片source `src_72e237745dcc5662dbd7`。最新Bot中性包中的路径、175400字节、SHA-256 `d8f958d3adf9f63011d45f403ae93528c5324c11472b7fcb941490962fa8cfe9`、2346×1080尺寸、`image/jpeg`和消息ID均校验通过。修正OCR临时结果路径，确保不会尝试在只读Bot归档目录旁写入结果。本地Windows简体中文OCR识别到明确标签“店铺编号L4015a”和“使用面积260㎡（暂定）”，两项均与PDF一致，归类为重复印证；新增事实0、不一致0。OCR未形成稳定L4标签，L4继续由PDF事实证明；低置信`L-4011b`仅进入人工核验。未判断动线、楼层优劣或经营收益，未写dashboard，未修改Bot。
- 改动文件：`scripts/parse_site_intake_supplements.py`、`scripts/parse_site_intake_pdfs.py`、`tests/test_site_intake_supplements.py`、`docs/SITE_SHADOW_ANALYSIS_V0.1.md`、`DEVELOPMENT_LOG.md`
- 本地输出：`data/staging/sijing_real_internal_input_v0.2.json`、`data/staging/sijing_real_pdf_review_v0.2.json`、`data/staging/sijing_real_pdf_review_v0.2.md`、`data/staging/sijing_real_shadow_analysis_v0.2.json`（均不进入Git）
- commit：未提交
- 验证方法：真实图片归档校验、OCR、PDF交叉对照、低置信分流及禁止Dashboard写回检查通过；图片/PDF/影子专项22项通过，全量68项测试通过。

## 2026-07-26 泗泾图片来源兼容与标准工程表解析

- 类型：功能/资料解析/测试
- 内容：新增neutral input图片和工程工作簿补充解析入口。图片归档先校验路径、字节数和SHA-256，保留原图引用及飞书消息ID；本地OCR的推荐铺位、铺位号、面积和楼层等明确标签只进入待人工核验候选，低置信结果仅进入人工核验清单，不据截图判断动线、楼层优劣或盈利。工程表逐sheet读取OOXML单元格，保留sheet/行/单元格来源，并将LANN标准要求、商场回复原文和机器状态候选分层；空白或含糊回复不得自动判定满足。真实`Lann开店工程条件2024.xlsx`哈希核验通过，识别为LANN标准工程要求清单：1个工作表、33项要求、商场回复0项（覆盖率0%）、含糊项0、可由书面回复识别的关键阻断项0；层高、新排风、空调、电力、给排水、消防等17个关键要求缺少逐项书面回复。负责人确认的总体初筛通过继续保留，不等于逐项已有书面证据。当前中性包无图片source，但不列为泗泾阻断，L4/L4015a/260㎡继续由PDF证明。未写dashboard，未修改Bot。
- 改动文件：`scripts/parse_site_intake_supplements.py`、`scripts/convert_neutral_site_input.py`、`ai/schemas/site_shadow_analysis.input.schema.json`、`tests/test_site_intake_supplements.py`、`requirements-ocr.txt`、`docs/SITE_SHADOW_ANALYSIS_V0.1.md`、`DEVELOPMENT_LOG.md`
- 本地输出：`data/staging/sijing_real_internal_input_v0.2.json`、`data/staging/sijing_real_pdf_review_v0.2.json`、`data/staging/sijing_real_pdf_review_v0.2.md`、`data/staging/sijing_real_shadow_analysis_v0.2.json`（均不进入Git）
- commit：未提交
- 验证方法：真实工程工作簿哈希、结构分类、回复覆盖率、标准要求事实来源、图片OCR候选分流、低置信人工核验、禁止Dashboard写回检查通过；全量68项测试通过。

## 2026-07-26 泗泾客户匹配与负责人经营判断确认

- 类型：资料确认/影子分析/测试
- 内容：录入5位意向客户的独立客户状态与泗泾场地状态：3位仅放弃泗泾花园城、继续保留LANN项目状态；2位仍在考察，原决策期限为2026-07-26，下一跟进日为2026-07-27。影子分析在期限当天标记“期限已到-待负责人跟进”，从次日起标记“超期未决-待负责人确认”，不自动判定放弃。同步录入王凯负责人经营判断：项目值得继续推进，经营亏损概率较低但存在业绩低迷可能，最终由加盟商结合风险承受能力决定；明确不构成盈利保证，项目保持“继续推进/等待客户决定”，不自动升级为确定立项。以上均与PDF事实分层。未写dashboard，未修改Bot。
- 改动文件：`ai/schemas/site_shadow_analysis.input.schema.json`、`scripts/build_site_shadow_analysis.py`、`tests/test_site_shadow_analysis.py`、`DEVELOPMENT_LOG.md`
- 本地输出：`data/staging/sijing_real_internal_input_v0.2.json`、`data/staging/sijing_real_pdf_review_v0.2.json`、`data/staging/sijing_real_pdf_review_v0.2.md`、`data/staging/sijing_real_shadow_analysis_v0.2.json`（均不进入Git）
- commit：未提交
- 验证方法：负责人确认、5位客户状态分离、期限当天与次日状态、经营风险限定语及禁止写回边界通过专项与全量测试。

## 2026-07-26 泗泾当前商务条件与工程状态负责人确认

- 类型：资料确认/影子分析
- 内容：将王凯于2026-07-26确认的当前商务条件和工程阶段作为“负责人当前确认”单独记录，与PDF提案事实分层。商务条件确认为当前有效并正在按固定租金51/56/61元/㎡/月、扣率6%/7%/8%（两者取高）、物业费30元/㎡/月、推广费15元/㎡/月推进；工程状态更新为前期工程初筛已完成且暂未发现明显阻断、经营可行性现场勘察已完成且值得推进、专业工程勘察待完成、合同工程条件待签约前最终确认并写入合同。已消除商务版本有效性和泛化工程状态缺口，继续保留“电子工程条件表原文件未归档，无法逐项追溯电量、给排水、空调、消防、层高”的资料缺口。未写dashboard，未修改Bot。
- 改动文件：`DEVELOPMENT_LOG.md`
- 本地输出：`data/staging/sijing_real_internal_input_v0.2.json`、`data/staging/sijing_real_pdf_review_v0.2.json`、`data/staging/sijing_real_pdf_review_v0.2.md`、`data/staging/sijing_real_shadow_analysis_v0.2.json`（均不进入Git）
- commit：未提交
- 验证方法：重建影子分析后完成负责人确认、来源引用、阶段状态、缺口和禁止写回边界的一致性检查；全量63项测试通过。

## 2026-07-26 泗泾花园城逐页诊断、OCR与表格解析增强

- 类型：功能/资料解析/测试
- 内容：在真实 PDF 第一轮拆解基础上增加逐页质量诊断和本地降级链路。77 页中 73 页触发至少一种检查并全部完成本机 Windows 简体中文 OCR；识别出 59 页以图片或复杂图形为主、35 页以表格为主、23 页 pypdf 文字层疑似乱码、21 页文字层不足，各类可重叠。改用 `pdfplumber` 作为稳定文字层和表格主解析器，保留 32 个二维表格及 OCR 行/词坐标；异常 pypdf 文字层不再单独进入事实。事实由第一轮 28 条增至 43 条且未丢失原事实，新增商场手册客流/覆盖人口口径、调研报告人口预测、足疗按摩/美容 SPA 外溢描述、区域外偏好品牌及居住/办公客群生活服务消费频次。其中报告第15页美容SPA区域内/外占比分别为4.8%/6.6%，第23页办公客群为5.2%/7.5%，均保留页面与版面识别方式。低置信“泗泾站TOP1”“5公里内无竞品”和目标铺位/品牌落位图版本一致性仅进入待人工核验，不进入正式事实。未做动线、楼层优劣或经营判断，未写 dashboard。
- 改动文件：`scripts/parse_site_intake_pdfs.py`、`scripts/windows_ocr_page.ps1`、`tests/test_site_intake_pdf_parser.py`、`ai/schemas/site_shadow_analysis.input.schema.json`、`requirements-ocr.txt`、`docs/SITE_SHADOW_ANALYSIS_V0.1.md`、`DEVELOPMENT_LOG.md`
- 本地输出：`data/staging/sijing_real_internal_input_v0.2.json`、`data/staging/sijing_real_pdf_review_v0.2.json`、`data/staging/sijing_real_pdf_review_v0.2.md`、`data/staging/sijing_real_shadow_analysis_v0.2.json`（均不进入 Git）
- commit：未提交
- 验证方法：真实 5 份 PDF 共 77 页完成逐页文字层、版面对象、表格、页面图像和 OCR 诊断；73 个降级页 OCR 成功、0 失败；渲染抽查调研报告第15页、商场手册第5/6页、租赁提案第3/4页、区块图和 L4 品牌落位图；专项测试与全量测试结果见本次任务最终汇报。

## 2026-07-26 泗泾花园城真实 PDF 第一轮资料拆解

- 类型：功能/资料解析/测试
- 内容：读取 Bot 真实中性输入包并验证 `lann-site-neutral-input/v0.1` 握手，5 份 PDF 的归档路径、文件大小和 SHA-256 均与中性包一致，外写控制保持 `dashboard_allowed=false`、`dashboard_attempted=false`。新增保守型 PDF 解析入口，逐页识别文字层、只抽取带明确标签和值的项目参数、铺位信息、租赁提案和报告口径人口数据；每条事实建立“原文件名+页码”引用，不按泗泾项目名硬编码结论。真实样例生成 28 条可核验事实，确认目标铺位 L4/L4015a、暂定使用面积 260㎡及租赁提案逐年固定租金/扣率等；明确租赁提案不具法律约束力，报告人口数据未完成外部交叉验证，铺位图不产生动线/经营优劣评分。未收到 LANN 标准工程条件表、用户文字或语音转写，因此工程初筛、现场判断和客户匹配仍列为缺口。
- 改动文件：`scripts/parse_site_intake_pdfs.py`、`tests/test_site_intake_pdf_parser.py`、`requirements-ocr.txt`、`docs/SITE_SHADOW_ANALYSIS_V0.1.md`、`DEVELOPMENT_LOG.md`
- 本地输出：`data/staging/sijing_real_internal_input.json`、`data/staging/sijing_real_pdf_review.json`、`data/staging/sijing_real_pdf_review.md`、`data/staging/sijing_real_shadow_analysis.json`（均不进入 Git）
- commit：未提交
- 验证方法：真实 5 份 PDF 共 77 页完成哈希核验和逐页文字层检查；租赁提案第 3、4 页及区块图第 1 页完成渲染抽查；专项测试覆盖文本/扫描/混合分类、标签事实提取、禁止 dashboard 外写和缺口保留；全量测试与语法检查见本次任务最终汇报。

## 2026-07-26 泗泾花园城候选场地影子分析 v0.1

- 类型：功能/数据契约/测试
- 内容：新增通用 `site_shadow_analysis` 任务，为 `lann-bot → lann-site → 人工确认 → lann-dashboard` 最小链路提供本地影子输出。联调评审后补充 Bot 中性输入接收层，严格按 `lann-site-neutral-input/v0.1` 接收项目、来源、原文件存储、语音转写状态、用户文字、分析请求、确认状态和禁止外写控制；Bot不再被要求生成事实、判断、阶段、风险或客户匹配。Site转换层只登记来源并生成解析缺口，未解析时保持 `facts/judgments` 为空并输出“待资料解析”，不把契约握手误报为PDF解析完成。内部结构化契约继续把原始资料、可证实事实、人工判断、阶段状态、风险、客户状态、场地匹配状态和缺失信息分层；输出保留完整来源登记、工程三阶段边界、经营收益风险限定语、客户匹配汇总、7/14天决策期、超期未决和下一步。明确铺位图只承载可证实事实，不做无证据的动线/楼层优劣评分；客户放弃场地不污染客户对LANN项目的状态；结果必须人工确认且禁止正式写回。泗泾只作为固定验收样例，脚本不按项目名称硬编码结论。
- 改动文件：`ai/tasks/site_shadow_analysis.json`、`ai/schemas/lann_site_neutral_input.schema.json`、`ai/schemas/site_shadow_analysis.*.schema.json`、`ai/evals/site_shadow_analysis/`、`scripts/convert_neutral_site_input.py`、`scripts/build_site_shadow_analysis.py`、`tests/test_neutral_site_input.py`、`tests/test_site_shadow_analysis.py`、`docs/SITE_SHADOW_ANALYSIS_V0.1.md`、`docs/AI_TASKS_V0.1.md`、`DEVELOPMENT_LOG.md`
- commit：未提交
- 验证方法：新增JSON均通过解析；Bot握手专项测试覆盖来源文件接收、用户文字保留、未转写语音缺口、禁止dashboard外写、拒绝违规输入及契约转换不冒充PDF解析；原影子规则测试继续覆盖工程边界、风险表述、客户/场地状态分离、推荐顺序、7/14天期限、超期不自动放弃、非泗泾项目复用及来源引用校验。`python -m unittest discover -s tests -v` 全量54项通过；本地完成中性包转换与“待资料解析”影子输出，`facts=0`、`judgments=0`、`dashboard_allowed=false`、`writeback_allowed=false`。

## 2026-07-19 好店 / 差店样本扩展、SABC店型与日级分析协议

- 类型：功能/数据分析/业务评审
- 内容：基于截至2026-06的83个可分析点位，按经济性、稳定性和客户健康三层Gate筛选首批业务评审样本。王凯确认中海环宇城、梅赛德斯奔驰文化中心为独立正向样本，武汉天地、长风大悦城为反向结果样本，百联南方保留反向候选；确认开业零碎月不进入月度Gate、数据不足时转日级分析，已终止且至少6个有效月可作为反向结果例外，丰盛里作为战略压力样本。补充复核丁香国际、虹桥龙湖天街、万科天空、博荟广场及9家反向候选；丁香国际和万科天空之城确认为边界正向样本，15%租售比保留为待更多结果验证的首版基准。只读接入2026门店SABC飞书表，共78家（S4/A17/B35/C22）；温州万象城因分类前已终止而未纳入，不是遗漏。新增可复用导出脚本和解析测试；明确当前SABC是综合商场等级、门店业绩和公司规划形成的业务讨论标签，用于战略店型和同类基准，不覆盖经济性事实，也暂不作为模型真值。新增日级爬坡分析协议，定义7/14/28日窗口、完整日/月和月度Gate衔接。
- 实现：开业零碎月保留原始记录但自动排除出月均营收、CV、趋势和好店Gate；新增7/14/28日日级营收、覆盖率、工作日/周末、月营收及租售比暂估。SABC只读缓存映射到点位，77个日结点位中76个完成分类，世茂广场因讨论稿未列入而保持空值；新增同类28日日均中位数对标。新增14%/15%/16%/18%租售比敏感性输出：至少6月经济性候选分别为3/4/10/12家，说明15%至16%为当前密集边界。
- 改动文件：`scripts/export_store_classification_from_feishu.py`、`scripts/build_daily_ramp_analysis.py`、`scripts/build_rent_ratio_sensitivity.py`、`scripts/build_site_performance.py`、`scripts/build_good_store_validation.py`、`scripts/build_data_manifest.py`、`scripts/rebuild_analysis.py`、`scripts/run_server_batch.py`、`config/store_classification_aliases.json`、`tests/`、`README.md`、`docs/GOOD_BAD_STORE_SAMPLE_REVIEW_V0.1.md`、`docs/DAILY_RAMP_ANALYSIS_V0.1.md`、`DECISIONS.md`、`DEVELOPMENT_LOG.md`
- commit：见本次提交（好店样本、日级爬坡、SABC同类对标与租售比敏感性）
- 验证方法：按 `site_ops_monthly_analysis.csv` 中分析纳入月份重算样本的月均营收、总体CV、近3月变化、新老客结构、留存率和返店频次；与 `site_benchmark.csv`、`good_store_validation.csv`、已有调研报告和飞书SABC表逐项对照；统一重建入口完整通过，数据契约0错误3警告；41项单元测试和语法检查通过。只读导出SABC表78行且分类数量核对为S4/A17/B35/C22。Excel工作簿因官方artifact-tool本机原生渲染模块不可用未生成，未改用其他表格库。

## 2026-07-18 数据身份契约与 Hanson BI 实时源评审

- 类型：功能/数据治理/评审
- 内容：新增分析前数据契约闸门，检查空点位 ID、重复关联 ID、门店映射漂移、经营月表重复主键、输入批次时间差和数据新鲜度；新增物理点位经营期映射、数据批次 manifest、统一重建入口和最小单元测试。根据王凯确认，将瑞虹、大宁、日月光和宝杨宝龙-宝乐汇的迁址前后拆为独立点位，过渡月不强行拆分；复兴 SOHO 停业装修但未换铺，BI“新天地店”完整历史归入 `L0003`。只读核对 Hanson BI 后确认月度指标表截止2026-03，日结表更新到2026-07-18。重叠对账确认营业收入应使用 `prod_amt`；并完成2026-04起双源接续、新老客、客次、留存率和返店频次接入。根据Hanson补充，服务器已在 `/srv/apps/lann-site/repo` 完成独立用户、venv、只读deploy key和飞书凭证设置。新增跟踪版84店映射+4店排除配置、服务器预检、完整批处理入口、运行状态文件和07:30 systemd timer模板；按服务器顺序本地29秒完整跑通，实时抽取96点位（73有测算、23无测算），数据契约0错误3警告。实时租金刷新发现啦啦宝都当前租金67,471元/月，租售比22.41%，从经济性达标名单移除；当前达标为梅赛德斯奔驰文化中心、中海环宇城和大宁新铺，其中大宁只作换铺承接样本。
- 改动文件：`config/site_identity_episodes.json`、`config/ops_source_policy.json`、`config/store_site_mapping.json`、`scripts/validate_data_contract.py`、`scripts/build_site_identity_episodes.py`、`scripts/build_data_manifest.py`、`scripts/rebuild_analysis.py`、`scripts/probe_bi_freshness.py`、`scripts/reconcile_bi_revenue_sources.py`、`scripts/refresh_hanson_daily_ops.py`、`scripts/build_ops_source_bridge.py`、`scripts/build_site_performance.py`、`scripts/build_site_benchmark.py`、`scripts/build_good_store_validation.py`、`scripts/check_server_readiness.py`、`scripts/run_server_batch.py`、`deploy/systemd/`、`tests/`、`README.md`、`requirements.txt`、`requirements-ocr.txt`、`docs/DATA_IDENTITY_CONTRACT_V0.1.md`、`docs/SITE_IDENTITY_RESOLUTION_PROPOSAL_V0.1.md`、`docs/BI_REALTIME_SOURCE_REVIEW_V0.1.md`、`docs/GOOD_STORE_VALIDATION_V0.1.md`、`docs/NEXT_PHASE_PLAN_V0.1.md`、`docs/HANSON_SERVER_HANDOFF_V0.1.md`、`docs/SITE_PERFORMANCE_ATTRIBUTION_V0.1.md`、`docs/ATTRIBUTION_REVIEW_PLAN_V0.1.md`、`docs/server_batch.md`、`docs/lann_site_data_design_v0.1.md`、`AGENTS.md`、`CLAUDE.md`、`DEVELOPMENT_LOG.md`
- commit：未提交
- 验证方法：`python -m scripts.run_server_batch` 按服务器顺序完整通过并写入成功状态，耗时约29秒；`python -m unittest discover -s tests -v`；`python -m compileall -q config services scripts tests`；数据契约0错误、3警告，生成83个可评估点位和3条完整好店复核记录。

## 2026-07-14 花木-盈丰客户资料聚合分析

- 类型：数据/业务复盘
- 内容：基于已归档客户资料 Excel 新增花木-盈丰客户资料分析脚本，只输出门店级聚合，不输出客户明细。识别 `A4-订单数据` 为客户归属门店级汇总表，共 88,630 条客户记录、91 个门店、去重客户数 88,630；同一客户出现在多个所属门店的数量为 0，因此当前文件不能直接验证“花木老客去盈丰后又回流花木”的跨店迁移路径，只能做门店客户资产与 R12 权益/消耗对比。聚合结果显示，花木店客户数 1,671、R12 消耗约 264.5 万、R12 消耗排名第 12；盈丰天地店客户数 360、R12 消耗约 31.9 万、R12 消耗排名第 81。该结果强化“盈丰没有沉淀出足够客户资产”的判断，但花木翻新期间盈丰接近 30 万的来源仍需订单流水级跨店消费数据验证。
- 改动文件：`scripts/analyze_huamu_yingfeng_customers.py`，`docs/HUAMU_YINGFENG_CUSTOMER_MIGRATION_V0.1.md`，`data/staging/huamu_yingfeng_customer_store_summary.csv`
- commit：未提交
- 验证方法：`python -m scripts.analyze_huamu_yingfeng_customers` 生成 91 个门店聚合结果和客户资料分析文档；`python -m compileall scripts\analyze_huamu_yingfeng_customers.py` 通过。

## 2026-07-14 客户资料 Excel 本地归档

- 类型：数据/归档
- 内容：将王凯放入项目根目录的客户资料 Excel `A1 - 资料收集 - 0622(1).xlsx` 移入本地敏感资料目录 `data/raw/customer_materials/2026-07-14/`。新增归档脚本读取 `.xlsx` 压缩 XML 结构，不依赖外部表格库，输出工作簿结构画像和归档说明。当前文件包含 `A2-业务资料` 与 `A4-订单数据` 两个工作表，其中 `A4-订单数据` 约 88,633 行，包含客户姓名、所属门店、最近到店时间、余额、权益金、消耗等字段，可用于后续花木-盈丰会员迁移分析。原始客户资料仅保存在 `data/` 下，不进入 Git；后续分析优先输出脱敏或聚合结果。
- 改动文件：`scripts/archive_customer_materials.py`，`docs/CUSTOMER_MATERIALS_ARCHIVE_V0.1.md`，`data/staging/customer_materials_profile.csv`
- commit：未提交
- 验证方法：`python -m scripts.archive_customer_materials` 生成 2 行工作簿结构画像和归档说明；`python -m compileall scripts\archive_customer_materials.py` 通过。

## 2026-07-13 花木-盈丰专题 V0.2 业务校准

- 类型：文档/业务复盘
- 内容：根据王凯逐项反馈，修正花木-盈丰专题判断。花木店确认可定义为成熟老客资产型门店；盈丰天地不是完全不能承接花木客人，而是短期能承接、长期留不住。关键事实包括：盈丰在 B1、电梯和手扶梯旁，停车路径不绕，理论停车体验优于花木；花木翻新约 20 多天期间，盈丰当月生意接近 30 万；花木恢复后，去过盈丰的客人又回到花木；盈丰天地商场自身客流少、后期空铺率严重，更多成为展会或写字楼公共餐饮配套。复盘口径由“500 米没有带来迁移”升级为“500 米可以带来短期迁移，但不能形成持续留存”，并把商场持续经营活力、品牌形象升级型迁店的老客资产损失、老客短期迁移与长期留存拆分纳入后续选址模型因子。
- 改动文件：`scripts/build_huamu_yingfeng_review.py`，`docs/HUAMU_YINGFENG_REVIEW_V0.1.md`，`DEVELOPMENT_LOG.md`
- commit：未提交
- 验证方法：`python -m scripts.build_huamu_yingfeng_review` 重生成专题文档；`python -m compileall scripts/build_huamu_yingfeng_review.py` 通过。

## 2026-07-13 花木店-盈丰天地 500 米迁移失败复盘专题

- 类型：功能/数据/业务复盘
- 内容：根据王凯补充，明确后续客流、趋势和数据质量由项目侧先拉取并判断，用户主要做业务校准。新增花木店、盈丰天地/云汇天地、花木陆悦坊三店专题复盘脚本，基于 BI 月度经营表、门店映射、租金汇总、门店基础表和样本基准表生成三店月度明细、分阶段汇总和复盘文档。复盘结论先区分盈丰稳定观察期与关停前收缩期，避免把后期异常误当成全周期经营事实；初步判断该案例是微区位/到店路径/老客迁移失败问题，而不是简单商圈或直线距离问题。
- 改动文件：`scripts/build_huamu_yingfeng_review.py`，`docs/HUAMU_YINGFENG_REVIEW_V0.1.md`，`data/staging/huamu_yingfeng_monthly.csv`，`data/staging/huamu_yingfeng_summary.csv`
- commit：未提交
- 验证方法：`python -m scripts.build_huamu_yingfeng_review` 生成 146 行月度明细、10 行阶段汇总和专题文档；`python -m compileall scripts/build_huamu_yingfeng_review.py` 通过；抽查花木近 12 月月均营收约 32.9 万、盈丰 2022-2024 稳定期月均营收约 13.9 万、近 12 月约 9.4 万，与业务反馈方向一致。

## 2026-07-13 BI 经营趋势诊断与 2024Q4 下滑口径

- 类型：功能/数据/业务上下文
- 内容：根据王凯补充，新客储值转化和老客留存纳入选址匹配度观察指标；老客留存越稳定，原则上越说明门店与周边客群匹配，但仍需与运营承接拆分。新增 BI 趋势诊断脚本，直接读取 BI 原始月度表和门店映射表，输出 2023-2025 月度、季度、年度经营趋势。当前 BI 原始表包含实际营收、现金流、开卡收入、新老客、客单、储值会员转化率、留存率、二次到店率、返店频次、点钟、理疗师产值、生产率、差评、打赏、微信关注等字段。趋势诊断显示，总营收 2023-2025 随门店数增加而增长，但折扣后客单价和理疗师日均产值下降；同店口径下，62 家持续经营门店 2024Q3 单店月均营收约 304,308，2024Q4 降至 287,026，2025Q1 降至 277,300，验证“2024Q4 后大部分门店明显下滑并持续至今”的业务观察。后续归因必须分阶段比较，不能把系统性下滑简单归因于单店选址。
- 改动文件：scripts/build_bi_trend_diagnostics.py；docs/BI_TREND_DIAGNOSTICS_V0.1.md；DEVELOPMENT_LOG.md
- commit：待提交
- 验证方法：`python -m scripts.build_bi_trend_diagnostics` 生成 `bi_trend_monthly_2023_2025.csv`、`bi_trend_quarterly_2023_2025.csv`、`bi_trend_annual_2023_2025.csv`；`python -m compileall scripts\build_bi_trend_diagnostics.py` 通过。

## 2026-07-13 补充 LANN 商业模式与选址归因校准

- 类型：文档/业务上下文
- 内容：根据王凯补充，完善 LANN 商业模式、门店扩展方式、收入确认逻辑、经营指标与选址指标差异、门店成熟期、好店定义、门店类型处理、代表成功/失败样本和选址硬性条件。明确 LANN 通过直营、加盟、合资扩展；直营/合资偏 CBD 核心与品牌影响力，加盟用于城市品牌立稳后的快速布局与风险分摊。单店收入由现金消费和储值卡卡耗构成，储值和随享卡由总部收取后按消费门店次月结算。选址归因一阶指标优先看新客数量、新客储值转化率、折扣前客单价；开卡、点钟、理疗师产值等更多用于经营诊断和承接拆分。好店定义校准为新客稳定、老客复购高、业绩波动小、租售比 15% 内、月业绩超过 28 万。新增王凯认可的成功样本和需复盘样本，用于后续归因模型校验。
- 改动文件：docs/LANN_BUSINESS_CONTEXT_V0.1.md；docs/SITE_PERFORMANCE_ATTRIBUTION_V0.1.md；DEVELOPMENT_LOG.md
- commit：待提交
- 验证方法：人工记录业务口径；后续 v0.2 归因模型需先用王凯认可样本做校验，再扩展到全量门店。

## 2026-07-13 记录 LANN 组织架构与目标达成率口径

- 类型：文档/业务上下文
- 内容：根据王凯补充，新增 LANN 业务与组织上下文文档。明确公司由支持中心、上海分公司、华东分公司、产品部和 LANN SPACE 构成；支持中心包括总经办、市场部、连锁经营部、空间体验部、人事部、财务部、IT 部、门店支持与创新部门等，人事下辖总部前台培训部，理疗师手法开发在门店与支持中心下辖。上海分公司与华东分公司每年承担收入和利润指标。同步明确 7 月目标管理周报中的“目标达成率”是集团给分公司的年度实际收入目标推进口径，不直接等同于门店选址好坏，只能作为最新经营状态与分公司经营节奏的校准信号。
- 改动文件：docs/LANN_BUSINESS_CONTEXT_V0.1.md；docs/SITE_PERFORMANCE_ATTRIBUTION_V0.1.md；DEVELOPMENT_LOG.md
- commit：待提交
- 验证方法：人工记录业务口径，后续归因模型需区分选址因素、分公司经营因素、支持中心赋能因素和门店承接因素。

## 2026-07-12 修正新店经营期与成长样本归因口径

- 类型：修复/数据口径
- 内容：根据王凯反馈，复核深圳湾万象城店和成都银泰中心in99店的归因标签。发现旧口径存在两个问题：一是新店有效营收月份不足时，平均月营收按完整 12 个月摊薄，导致深圳湾万象城租售比被错误放大；二是租售比健康且新客强的门店，仅因营收分位暂低被标为反向样本。修正后，经营汇总按有效营收月份计算平均月营收和平均月新客；有效营收月份少于 6 个月的门店进入“观察样本-经营期不足”；新客强且租售比健康的门店进入“成长样本-新客强租售比健康”。深圳湾万象城店现为观察样本，不作正反定性；成都银泰中心in99店现为成长样本，不再作为反向样本。
- 改动文件：scripts/build_site_performance.py；scripts/build_site_performance_attribution.py；scripts/build_attribution_review_plan.py；docs/SITE_PERFORMANCE_ATTRIBUTION_V0.1.md；docs/ATTRIBUTION_REVIEW_PLAN_V0.1.md；DEVELOPMENT_LOG.md
- commit：待提交
- 验证方法：重新执行 `python -m scripts.export_ops_from_bi` 确认 BI 当前数据截止 2026-03；重新执行 `python -m scripts.build_site_performance --rent-file data/staging/rent_extract_feishu.csv --ops-file data/staging/site_ops_monthly_bi.csv --monthly-out data/staging/site_performance_monthly_bi_feishu_rent.csv --summary-out data/staging/site_performance_summary_bi_feishu_rent.csv`、`python -m scripts.build_site_benchmark`、`python -m scripts.build_site_performance_attribution`、`python -m scripts.build_attribution_review_plan`。修正后深圳湾万象城店有效营收月份 4、平均月营收 293984.48、租售比 0.2258、标签为“观察样本-经营期不足”；成都银泰中心in99店平均月营收 212211.1、租售比 0.1704、平均月新客 166.92、标签为“成长样本-新客强租售比健康”。`python -m compileall scripts\build_site_performance.py scripts\build_site_performance_attribution.py scripts\build_attribution_review_plan.py` 通过。

## 2026-07-12 选址归因代表样本复盘计划

- 类型：功能/数据/方案
- 内容：基于现有门店经营归因结果，新增代表样本选择脚本和复盘计划文档。每类经营结果标签最多挑 3 个代表门店，优先选择已有结构化调研报告的样本，生成 `site_attribution_review_plan.csv`。下一步不全量补调研报告，先复盘上海荟聚店、武汉天地店、上海张江陆悦天地店、深圳湾万象城店、成都银泰中心in99店 5 个已有调研报告的代表样本，验证“经营结果标签 -> 调研字段 -> 可能选址归因”的链路。
- 改动文件：scripts/build_attribution_review_plan.py；docs/ATTRIBUTION_REVIEW_PLAN_V0.1.md；DEVELOPMENT_LOG.md
- commit：待提交
- 验证方法：`python -m scripts.build_attribution_review_plan` 生成 24 行代表样本复盘清单；`python -m compileall scripts\build_attribution_review_plan.py` 通过。

## 2026-07-12 现有门店经营归因 v0.1

- 类型：功能/数据/方案
- 内容：根据王凯补充口径，调整 lann-site 第一阶段主线：立项信息表和选址调研报告先用于理解选址业务结构和经营模型字段，不先用历史测算与实际业绩匹配度做主归因。新增现有门店经营归因脚本，基于实际营收、租金、租售比、新客、客单和理疗师产值，对 82 个现有门店打经营结果标签，并反推应优先补充的选址调研字段。新增归因方案文档，同步修正数据设计文档中的 P0 路线。
- 改动文件：scripts/build_site_performance_attribution.py；docs/SITE_PERFORMANCE_ATTRIBUTION_V0.1.md；docs/lann_site_data_design_v0.1.md；DEVELOPMENT_LOG.md
- commit：待提交
- 验证方法：`python -m scripts.build_site_performance_attribution` 生成 82 行经营归因明细和归因汇总，其中正向样本-新客驱动 16 个、正向样本-高产值承接 7 个、正向样本-结构健康 5 个、反向样本-租金高且营收弱 16 个、反向样本-租金不高但营收弱 7 个、压力样本-租金偏高 11 个；已结构化调研报告覆盖 10 个、未覆盖 72 个。`python -m compileall scripts\build_site_performance_attribution.py` 通过。

## 2026-07-12 候选点位初筛 v0.2 接入经营样本对标

- 类型：功能/数据
- 内容：新增候选点位初筛 v0.2 脚本，在原有资料治理版 `candidate_screen.csv` 基础上接入现有门店经营样本 `site_benchmark.csv` 和经营分位阈值，输出 `candidate_screen_v2.csv`。v0.2 不再只判断资料是否完整，而是给出判断层级、推荐等级、核心判断、主要机会/风险、缺失资料、下一步动作、正向/风险对标样本、城市样本概况和外部情报优先级。当前结果显示经营数据底座已经可用，主要瓶颈在候选点位侧的租金、营收、调研报告链接和商圈/商场字段回填；下一步应先补“优先补租金 / 签约前后补经营模型 / 优先补调研”项目，再启动 P1 外部选址情报包。
- 改动文件：scripts/build_candidate_screen_v2.py；docs/CANDIDATE_SCREEN_V0.2.md；DEVELOPMENT_LOG.md
- commit：待提交
- 验证方法：`python -m scripts.build_site_benchmark` 生成 82 个现有门店经营样本；`python -m scripts.build_candidate_screen` 生成 236 个资料治理候选项目；`python -m scripts.build_candidate_screen_v2` 生成 236 个判断增强候选项目，其中优先复核 1 个、签约前后补经营模型 4 个、优先补租金 21 个、优先补调研 14 个、已开业回填复盘 85 个；`python -m compileall scripts\build_candidate_screen_v2.py` 通过。

## 2026-07-12 bot 阶段归档与选址项目交接

- 类型：文档/交接
- 内容：本阶段主要转入 `C:\Users\王凯\lann-work-bot` 建设飞书工作助手，已形成飞书机器人统一入口、自然语言事项编排、DeepSeek 模型路由、工作OS上下文/输出偏好/已确认判断读取、项目进展查询、组织角色上下文、通讯录读取候选和通讯录权限诊断。`lann-site` 继续保持选址分析与外部选址情报层定位，不承载在线机器人服务；后续在 bot 文件夹唤醒时继续工作助手，在本项目唤醒时继续选址项目。下一步选址主线回到候选点位对标、外部选址情报、正反样本库和判断规则沉淀。
- 改动文件：DEVELOPMENT_LOG.md
- commit：待提交
- 验证方法：已核对 `lann-work-bot` 的 DEVELOPMENT_LOG，确认 2026-07-11 至 2026-07-12 的工作助手建设、组织上下文和通讯录权限诊断均已在 bot 项目归档；已核对 `lann-site` 的 DECISIONS.md，确认 AI 矩阵、外部选址情报层和新建 bot 项目的关键决策已留档。

## 2026-07-10 新建 lann-work-bot 承载飞书机器人事项编排

- 类型：功能/架构
- 内容：按王凯确认，新建独立项目 `C:\Users\王凯\lann-work-bot` 承载飞书机器人事项编排，不直接在旧 `Lann-bot-backup-20260525` 上继续开发。第一版实现飞书 webhook、source_packet 本地落盘、“开始编排”触发、读取 `lann-site` / `lann-dashboard` / 工作OS 状态文件和规则型事项编排输出；`lann-site` 的 `DEVELOPMENT_LOG.md`、`DECISIONS.md`、`docs/AI_*.md`、`ai/tasks/*.json` 已作为状态源接入。
- 改动文件：docs/FEISHU_BOT_WORK_ORCHESTRATION_V0.1.md；新项目 `C:\Users\王凯\lann-work-bot`
- commit：本提交
- 验证方法：在 `lann-work-bot` 中执行 `npm.cmd run check` 通过；`npm.cmd install` 完成，0 vulnerabilities。

## 2026-07-10 飞书机器人事项编排项目方案

- 类型：文档/方案
- 内容：将事项编排入口从飞书文档/本地 inbox/CMD 粘贴调整为飞书机器人消息流。新增飞书机器人事项编排项目方案、`feishu_bot_inbox_ingest` 标准任务、`source_packet` schema 和 eval 样本说明；更新 AI 任务清单和第一阶段工作计划。默认每日 21:30 由机器人提醒王凯同步资料，王凯发送“开始编排”后输出今日事项编排到同一机器人会话。
- 改动文件：docs/FEISHU_BOT_WORK_ORCHESTRATION_V0.1.md；docs/AI_TASKS_V0.1.md；docs/AI_PHASE1_WORKPLAN_V0.1.md；ai/tasks/feishu_bot_inbox_ingest.json；ai/schemas/source_packet.schema.json；ai/evals/feishu_bot_inbox_ingest/README.md；DECISIONS.md
- commit：本提交
- 验证方法：待提交前校验 `ai/` 下 JSON 文件可被正常解析。

## 2026-07-10 事项编排任务设为第一阶段最高优先级

- 类型：文档/方案
- 内容：根据王凯反馈，当前最大效率瓶颈是三个项目与日常待办散乱，飞书 AI 助手能列待办但不能稳定识别事项关系。新增 `work_item_orchestration` 标准任务、输出 schema、eval 样本说明和每日事项编排模板；同步更新 AI 矩阵、第一阶段工作计划和任务清单，把事项编排作为第一阶段最高优先级。短期采用轻量模板，不自动改飞书待办、不派任务、不发消息。
- 改动文件：docs/AI_MATRIX_V0.1.md；docs/AI_PHASE1_WORKPLAN_V0.1.md；docs/AI_TASKS_V0.1.md；docs/templates/DAILY_WORK_ITEM_ORCHESTRATION.md；ai/tasks/work_item_orchestration.json；ai/schemas/work_item_orchestration.output.schema.json；ai/evals/work_item_orchestration/README.md；DECISIONS.md
- commit：本提交
- 验证方法：待提交前校验 `ai/` 下 JSON 文件可被正常解析。

## 2026-07-09 连锁经营部 AI 矩阵与第一阶段前置工作启动

- 类型：文档/方案
- 内容：基于王凯确认的连锁经营部 AI 化方向，新增 AI 矩阵 v0.1、第一阶段工作计划、AI 任务清单和模型可插拔前置规范。明确飞书是入口，`lann-site` 是分析判断层，`lann-dashboard` 是展示推进层，工作OS 是判断源沉淀层；外部新闻、点评、小红书、地图、热点等数据归口为 `lann-site` 的外部选址情报层。第一阶段目标定义为让 AI 稳定回答“这件事是什么、关联哪个业务对象、资料是否足够、下一步该补什么、是否值得王凯看”。同时建立 `ai/` 工程骨架，为 `site_candidate_screen` 和 `external_site_intel` 两个任务新增任务定义、输出 schema 和 eval 样本说明。
- 改动文件：docs/AI_MATRIX_V0.1.md；docs/AI_PHASE1_WORKPLAN_V0.1.md；docs/AI_TASKS_V0.1.md；docs/AI_MODEL_PORTABILITY_V0.1.md；ai/tasks/site_candidate_screen.json；ai/tasks/external_site_intel.json；ai/schemas/site_candidate_screen.output.schema.json；ai/schemas/external_site_intel.output.schema.json；ai/evals/site_candidate_screen/README.md；ai/evals/external_site_intel/README.md；DECISIONS.md
- commit：本提交
- 验证方法：已完成人工方案拆解；`ai/` 下 JSON 任务定义和 schema 均通过 `ConvertFrom-Json` 校验；后续按文档逐项推进更多任务 schema、eval 样本和三项目数据契约。

## 2026-07-08 新点位初筛归因分析飞书文档生成

- 类型：功能/文档
- 内容：新增飞书文档生成脚本，读取 `candidate_screen.csv` 汇总初筛结论、调研报告匹配、资料风险 Top 分布、重点样本和下一步资料治理建议，并调用飞书 docx API 新建文档写入正文。
- 改动文件：scripts/create_candidate_analysis_doc.py
- commit：本提交
- 验证方法：`python -m compileall scripts/create_candidate_analysis_doc.py` 通过；已成功生成飞书文档 `https://lann.feishu.cn/docx/WW8Id8exFoQVmOx3MMNceXFgncb`。

## 2026-07-08 新点位初筛/对标表第一版

- 类型：功能/数据
- 内容：新增候选项目初筛脚本，将扩展管理候选项目、选址调研报告结构化事实、现有门店经营基准分位数合并为 `candidate_screen.csv`。第一版优先用报告链接匹配，缺链接时用城市约束后的名称归一化匹配；输出预期营收、租金物业月成本、估算租售比、租售比风险、资料风险、初筛结论和下一步动作。对金额解析做了保护，避免把“6个月”等周期误当营收，并对小于 1000 的候选营收按万元暂估时标记口径提示。
- 改动文件：scripts/build_candidate_screen.py；data/staging/candidate_screen.csv
- commit：本提交
- 验证方法：`python -m scripts.build_candidate_screen` 生成 236 行；`python -m compileall scripts/build_candidate_screen.py` 通过；抽查西岸梦中心、深圳湾万象城、成都 in99、温州印象城等边界样本。

## 2026-07-08 7月3日选址数据治理成果固化

- 类型：文档/配置
- 内容：梳理 7 月 3 日以来 BI、扩展管理飞书表、选址调研报告、现有门店经营基准表相关未提交成果；明确 `data/`、`*.csv`、`.claude/`、`export/` 等本地数据/工具配置不进入 Git；将“测算表默认总额不再作为核心判断依据，改为驱动假设 + BI 实际经营数据”的路线补入关键决策记录。
- 改动文件：.gitignore；DECISIONS.md；DEVELOPMENT_LOG.md
- commit：本提交
- 验证方法：`python -m compileall config services scripts` 通过；`git status --short` 确认本地导出目录已被忽略。

## 2026-07-03 选址调研报告结构化提取第一版

- 类型：功能/数据
- 内容：基于已定位的 14 份可读选址调研报告，新增结构化提取脚本，输出场地信息、商场评级、竞品/点评/周边市调、工程条件、投资分析、稳定营业额预期和总投入等字段。当前 14 份报告全部提取成功，无失败记录。第一版已验证西岸梦中心等样本可提取租金+物业、面积、合同租期、商场开业时间、商圈/商场评级、风险机会文本和投资金额；部分报告字段为空或格式差异，后续可继续扩展解析规则。
- 改动文件：scripts/extract_site_survey_facts.py；data/staging/site_survey_facts.csv；data/staging/site_survey_fact_failures.csv
- commit：未提交
- 验证方法：脚本语法检查通过；只读读取 14 份飞书调研报告并生成 14 行结构化事实表；抽查关键字段输出。

## 2026-07-03 档案表立项信息表中的选址调研报告链路跑通

- 类型：功能/数据
- 内容：重新完成飞书用户身份授权后，从档案表的测算/立项信息表链接进入 71 张表，扫描“选址调研报告/调研表”入口。共发现 15 个报告链接，其中 14 份可读取、1 份报告链接异常；另有 2 张立项表无查看权限。可读取报告模板高度一致，标签页主要为“场地信息 / 店铺工程信息 / 投资分析 / 投资测算”，已能读取场地租金面积、商圈/商场评级、竞品、市调、工程条件、投资分析等选址信息。
- 改动文件：scripts/scan_site_survey_links.py；scripts/inspect_site_survey_reports.py；data/staging/site_survey_links.csv；data/staging/site_survey_report_meta.csv；data/staging/site_survey_report_samples.csv
- commit：未提交
- 验证方法：全量扫描 71 张立项/测算表；输出 15 条报告链接；读取 14 份报告元信息与样本内容成功。

## 2026-07-03 扩展管理飞书多维表接入探测

- 类型：功能/数据
- 内容：接入王凯提供的扩展管理飞书多维表链接，新增通用飞书多维表探测脚本和候选项目导出脚本。该表共 236 个项目、45 个字段，包含项目名称、城市、当前阶段、开店性质、商圈等级、商场评级、物业形态、预期月营业额、立项信息表、选址调研报告、租金等字段。当前 14 个项目资料可初步对标，163 个项目资料部分可用，59 个项目缺基础字段。发现“预期月营业额”疑似存在元/万元口径混用，后续进入新点位对标前需治理单位。
- 改动文件：.env.example；config/settings.py；scripts/inspect_feishu_bitable.py；scripts/export_expansion_candidates.py；data/staging/expansion_table_*.csv；data/staging/expansion_candidates.csv
- commit：未提交
- 验证方法：只读读取飞书扩展管理表成功；字段清单、填充率、样本和候选项目清单均已生成。

## 2026-07-03 现有门店选址经营基准表

- 类型：功能/数据
- 内容：基于飞书结构化租金与 BI 月度经营数据，生成 82 家有效门店的选址经营基准表。输出租售比分层、营收/租金/新客/理疗师产值分位、样本角色与风险提示，用于后续新点位对标和正反样本库建设。当前分层结果：健康 9、正常偏高 20、关注 36、高压 9、异常高压 8；样本角色包括正向样本、反向样本、压力样本、观察样本和中性样本。
- 改动文件：scripts/build_site_benchmark.py；data/staging/site_benchmark.csv；data/staging/site_benchmark_stats.csv
- commit：未提交
- 验证方法：脚本语法检查通过；输出 82 行，与当前有效分析样本一致；抽查正向样本和高风险样本符合业务直觉。

## 2026-07-03 权限、数据源与项目边界协作规则更新

- 类型：文档/协作规则
- 内容：根据王凯确认，后续默认减少无实质风险防控意义的授权弹窗；只读访问已配置好的飞书、BI/API 与本地分析文件可自主推进，确需授权时必须用大白话说明动作、需要用户做什么、隐藏风险和最坏影响。数据源优先飞书/API 线上读取，本地文件仅作缓存/样本/兜底。明确 lann-site 主线仍是选址分析、经营表现、租售比与选址判断数据治理；降租、续租、加盟商管理费、加盟服务流程、工作台产品模块属于隔壁工作台/加盟管理方向，本项目只提供输入指标。
- 改动文件：CLAUDE.md；工作OS `待蒸馏/raw/site-claude.md`
- commit：未提交
- 验证方法：已将新增协作约定写入 CLAUDE.md，并按自动记录规则同步到工作OS。

## 2026-07-02 工作OS判断源候选改为流程完成后自动记录

- 类型：文档/协作规则
- 内容：根据王凯确认，lann-site 相关重要讨论、方案、复盘、数据治理口径、AI协作方法，在流程完成后若满足约定记录条件，应自动追加到工作OS `待蒸馏/raw/site-claude.md`，不再逐条向王凯确认；记录完成后只告知已写入及主题。同步将该规则本身记录到工作OS判断源候选。
- 改动文件：CLAUDE.md；工作OS `待蒸馏/raw/site-claude.md`
- commit：未提交
- 验证方法：已读取 `site-claude.md` 尾部，确认新增“工作OS判断源候选自动记录规则”

## 2026-06-23 测算抽取评估后暂停，重定义抽取口径

- 类型：决策/数据
- 内容：评估测算表自动抽取的可行性。按"2023 年后开业 + 有测算"圈出 46 家试点；验证发现仍有 ~22 种标签结构，但聚成约 4 个家族（营收页：运营测算/新店测算/新店模型；商务页：租赁商务/商务条件）。聚焦版抽取器（只扫营收/租金页+数值过滤）在 46 家上：月营收干净抽出 15、月租金仅 6。关键质量发现：抽出的营收只有 4 个不同值（24万×9、28万×3…），多为模板默认假设值而非逐店精算，"营收达成率"分母可信度存疑。
- 决策（与王凯确认）：① 暂停硬抽测算，不再调脚本死磕；② 测算表抽取口径**重定义**为只抽"业绩预估 + 支撑驱动（新客数/老客数/客单价/客均时长）"——驱动假设比默认总额更有信息量，且对应文档的"新客获取动能"；③ 租金/租赁商务改从**租赁合同**重新抽取（合同为准）；④ 下一步转向更干净的"实际经营数据"（日颗粒），与结构化底表拼出真实经营表现+租售比。
- 改动文件：scripts/{test_sheet_user,sample_forecasts,scan_forecast_access,extract_forecasts,focus_post2023,extract_focus}.py、services/feishu_oauth.py、services/feishu_client.py（直连+重试加固）
- commit：待提交（用户确认后）
- 验证方法：脚本均实跑；结论已与用户对齐
- 提醒：本条为方法路线决策，建议王凯考虑记入 DECISIONS.md

## 2026-06-23 数据清洗启动：Python 骨架 + 飞书读取层 + 第一段底表

- 类型：功能
- 内容：搭建 lann-site Python 骨架（config 配置层 / services 飞书访问层 / scripts 探查与抽取），复用现有飞书 app。探查"租赁信息表"（app_token=PGGyb...，95 条记录）：发现商务条件大多已结构化、可直接 API 拉取；测算/立项数据在 73 张关联的飞书电子表格里（9 标签模板）；合同 PDF 覆盖极低（租赁仅 3/95），P0 暂不解析。云文档读取走"用户身份"OAuth（user_access_token，以王凯身份读，绕开逐张分享），授权 scope 含 drive/sheets/wiki readonly。完成第一段：95 个点位结构化底表 → data/staging/base_table.csv。关键发现：当前年租金月仅 13/95 填充，租金实际在测算表"商务条件"页，故第二段（读测算表）为必需。16 个已终止门店=现成关店反例。
- 改动文件：.gitignore、.env.example、requirements.txt、config/settings.py、services/feishu_client.py、services/feishu_oauth.py、scripts/{inspect_table,inspect_fields,test_sheet,test_sheet_user,feishu_login,extract_base}.py
- commit：待提交
- 验证方法：脚本均已实跑通过；底表已生成并核对字段填充率

## 2026-06-22 Q3 2026 OKR 按承接航道重构（v2）

- 类型：文档
- 内容：在 v1 基础上，结合团队组织现实（圣祥管选址招商、文芳管加盟服务，二人均被事务性工作填满）重构 Q3 OKR。结构从"按主题"改为"按承接航道"，每条 KR 明确 owner，避免重演 Q2 的目标无主归零。服务侧从"轻管理加盟探索"换成"加盟商之声驱动机制"（分类+路由+SLA+自助FAQ，文芳承接、跨部门 SLA 与王凯共担），轻管理加盟暂缓至 Q4。确立两条新设计原则：战略标准必须"自己回本"、每人 Q3 只压 1 个战略标准。
- 改动文件：docs/Q3_2026_OKR.md（v1→v2 覆盖重写）
- commit：待提交
- 验证方法：用户拿去与 CEO 做战略对齐；对齐后如有调整再更新本文件

## 2026-06-22 Q3 2026 OKR 终稿留档（v1）

- 类型：文档
- 内容：经多轮探讨，明确部门 OKR 写"过程/新动作"而非"结果/数字"的原则，定稿 Q3 2026 OKR（O1 点位获取机制化、O2 选址数智化、O3 轻管理加盟探索），留档至 docs/。作为本季度日常工作指引，后续如实际推进偏离较多由 Claude Code 适当提醒。
- 改动文件：docs/Q3_2026_OKR.md（新建）
- commit：待提交
- 验证方法：用户拿去与 CEO 做战略对齐；对齐后如有调整再更新本文件

## 2026-06-21 项目文档初始化（CLAUDE.md / DECISIONS.md / DEVELOPMENT_LOG.md）

- 类型：文档
- 内容：发现目录内原有 CLAUDE.md 实际是 lann-dashboard 项目的内容，与 lann-site 定位不符。重新编写精简版 CLAUDE.md（项目身份、协作纪律、权限边界、文档结构），新建 DECISIONS.md 和 DEVELOPMENT_LOG.md。确认技术栈为 Python，GitHub 仓库地址为 https://github.com/wangkaioo123-ship-it/lann-site.git。
- 改动文件：CLAUDE.md（重写）、DECISIONS.md（新建）、DEVELOPMENT_LOG.md（新建）
- commit：待提交
- 验证方法：用户 review 三份文档内容是否符合预期
# 2026-08-02 新店增长候选统一交接入口

- 类型：跨项目最小闭环
- 内容：新增 `scripts/run_new_store_handoff.py`，把 Bot 已确认的选址资料包按固定顺序完成 PDF/补充资料解析、Site 影子分析、`site_record/v0.1` 候选生成，并可选择调用 Dashboard 既有候选导入脚本。未确认资料包默认拒绝处理；候选导入后仍需负责人确认，不自动写入正式场地。
- 改动文件：`scripts/run_new_store_handoff.py`、`tests/test_new_store_handoff.py`、`README.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m unittest tests.test_new_store_handoff`；再用泗泾花园城真实审核数据运行候选生成和 Dashboard 本地候选导入。

## 2026-08-02 新店增长三场地端到端验收

- 类型：真实业务验收/跨项目闭环
- 内容：使用泗泾花园城、湖滨in77、宝山万象汇三个不同成熟度场地验证候选交接。泗泾验证成熟资料与既有审核候选；湖滨验证已有正式场地的名称与城市关联；宝山验证资料稀疏时仍可进入待研判候选，且不得误关联泗泾。三条候选均进入 Dashboard 本地候选缓冲区，重复导入为更新而非重复创建，正式场地写入仍保持关闭。
- 验收结果：湖滨与已有“湖滨in77”匹配分 1.0、建议关联；宝山与泗泾仅同城、匹配分 0.25、不建议关联；本地候选共 3 条，分别为可推荐、招商接洽、待研判。
- 发现并隔离的问题：真实 Bot 泗泾资料包中混入两条宝山文字说明。Site 正确将其暴露为待核验，但该包不再用于正式导入；项目归属修复在 `lann-work-bot` 单独完成。
- 验证方法：`python -m unittest tests.test_new_store_handoff tests.test_site_record_candidate_builder tests.test_site_shadow_analysis` 共 18 项通过；Dashboard `node scripts/verify_site_intake.js` 通过；三候选重复导入均返回 `updated`。
