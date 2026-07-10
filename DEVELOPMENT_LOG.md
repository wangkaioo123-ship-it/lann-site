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
