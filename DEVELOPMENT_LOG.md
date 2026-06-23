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
