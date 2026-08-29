# lann-site

LANN 后台专业分析服务。Site 只读使用获批数据，当前承载选址、门店经营、人员辅助证据、租金压力和投资测算等可解释分析；Dashboard 保存正式业务事实、人工评审、执行动作与后续结果，Work OS 保存长期规则。Site 不直接修改正式业务状态，也不因单次反馈自动改变规则。

## 当前运行形态

- 生产目录为 `/srv/apps/lann-site/repo`，使用独立 `app_lann_site` 身份和最小只读权限运行；不开放公网、不写飞书或 Dashboard。
- 2026-08-29 只读核验确认远端 `master` 与生产 `current_commit` 均为 `1d078d603a1e18d558767bab362b6930b8e258a0`。现役受限入口只能检查版本与部署，不能读取 timer 或业务产物，因此不能把“代码已部署”误报成“2026-06/07 v0.2 业务产物已验收”。
- 加盟经营评审的正式人员输入来自 lann-data 脱敏 canonical 月度聚合；经营评审消费已准备好的门店月度正式输入。旧 Metabase/BI 直读脚本仅保留为历史诊断与迁移兼容，不是 Dashboard 应依赖的数据契约。
- 生产安排为北京时间 07:30 自然运行，输出保存在 Site 自身 `data/staging/`。当前最小运维缺口是 Site 结果只读查看/下载能力，不是 lann-data 数据接口。

## 环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

OCR 合同脚本需要额外安装：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ocr.txt
```

复制 `.env.example` 为 `.env`。只读飞书和历史诊断脚本所需凭证只保存在运行环境；密钥和 `data/` 不进入 Git。加盟月度评审本身只消费已准备好的正式月表和 canonical 人员聚合，不要求 Dashboard 直连 BI。

## 标准分析顺序

当前正式生产顺序是：Data 发布只读正式输入 → Site 执行 Gate → Site 生成只读分析产物。`refresh_hanson_daily_ops`、`export_ops_from_bi` 和旧双源桥接属于历史数据诊断/迁移能力，不再作为跨系统正式消费契约。

每次更新正式经营月表、租金、门店映射后，可以执行本地分析重建入口：

已确认的换铺/迁址经营期维护在 `config/site_identity_episodes.json`，源表不因分析需要被覆盖。

```powershell
.\.venv\Scripts\python.exe -m scripts.rebuild_analysis
```

服务器现有批处理入口为：

```powershell
.\.venv\Scripts\python.exe -m scripts.run_server_batch
```

该入口会运行现有资料抽取、历史兼容步骤和下游分析。正式跨系统边界以 lann-data 发布的只读 canonical 输出及本节月度评审输入为准，不能因为仓库仍保留旧 BI 脚本就把旧表当成正式数据契约。存在 `ERROR` 时停止下游重建。关键本地输出：

- `hanson_monthly_prod_amt.csv`：全部门店月及完整性判断。
- `hanson_monthly_customer_metrics.csv`：门店月级新客、老客、客次、留存与返店频次汇总，不含客户个人数据。
- `hanson_revenue_trends.csv`：门店滚动30/90天营收。
- `site_ops_monthly_combined.csv`：王磊月度稿 + Hanson完整月的统一经营输入。
- `hanson_daily_quality_issues.csv`：不完整月、零营收、未映射等问题。
- `good_store_validation.csv`：经济性达标店的客户结构、营收波动和样本限制复核表。
- `store_2026_classification.csv`：飞书SABC讨论稿的只读本地缓存。
- `daily_ramp_analysis.csv`：7/14/28日营收、覆盖率、工作日/周末和同SABC对标，只作趋势与预警。
- `rent_ratio_sensitivity.csv` / `rent_ratio_sensitivity_summary.csv`：14%/15%/16%/18%阈值敏感性明细与汇总，不自动修改正式标准。

`pipeline_manifest.json` 记录本轮输入输出的行数、时间范围和文件指纹，用于判断结果是否来自同一批数据。

## 加盟经营异常月度核查

完整自然月经营数据和脱敏人员月表就绪后，生成只读核查候选与人员证据增强包：

```powershell
.\.venv\Scripts\python.exe -m scripts.build_franchise_operating_review `
  --auto-backfill-from 2026-06 `
  --workforce-contract .\config\store_workforce_monthly.v1.contract.json
```

生产自动任务从2026-06起，每次只处理最早一个尚无成功报告的完整自然月；失败月份保留在队首，后续自动重试，全部追平后恢复最新完整月常规幂等运行。生产默认只读人员出口：`/opt/management-dashboard/data/canonical-snapshot/store_workforce_monthly.csv`，正式契约为 `config/store_workforce_monthly.v1.contract.json`。Site 精确校验 25 列顺序、`data_version` 和生产 commit，并把每次实际文件 SHA-256 写入运行记录；SHA 变化本身不阻断正常月度刷新。Gate 未通过时不生成候选；同一月份、同一输入重复运行不会制造重复候选；不写 Dashboard。首次固定 9 家 2026-07 回放、产物结构和失败提示见 `docs/FRANCHISE_OPERATING_REVIEW_V0.1.md`。

每次成功运行还生成全店只读业务评审。`data/staging/franchise_operating_reviews/business_review.html`可在已成功月份间切换；即使候选数为0，也会按营收直接变化率展示全部参与计算门店、目标月经营/人员事实、现行门槛距离、可能解释与证据缺口。`business_review.json` 同时按 `franchise-store-three-month-operating/v0.1` 输出每店最近3个完整自然月的营业额、已知租金与物业费合计、按两者金额重算的租售比、来源和完整性；上游租售比仅用于一致性诊断，没有权威拆分的纯租金、物业费、管理费保持 `null/unknown`，不计算利润。该页面不使用综合风险评分，不写Dashboard，也不会用固定9家历史校准名单替代正常全量扫描。

同一 run 还生成 `analysis_catalog.json`：按 `professional-analysis-catalog/v0.1` 为每家门店提供稳定 `analysis_id`、canonical 门店、期间、输入指纹、规则版本、可信度、事实/统计差异/代理指标/假设/缺口、结论和建议。Dashboard 后续按 `professional-analysis-feedback/v0.1` 导出人工评审、动作和结果，Site 可生成只读校准质量汇总；详见 `docs/PROFESSIONAL_ANALYSIS_FEEDBACK_V0.1.md`。

只读检查 Hanson BI 数据新鲜度与对账：

```powershell
.\.venv\Scripts\python.exe -m scripts.probe_bi_freshness --candidates
.\.venv\Scripts\python.exe -m scripts.reconcile_bi_revenue_sources
```

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q config services scripts tests
```

## 当前业务边界

- 第一阶段先解释历史，不直接预测新店。
- “好店达标 Gate”与“归因研究样本”必须分层，当前代码中的正向样本不等同于正式好店结论。
- lann-site 只提供证据、分析、风险和建议，不承载飞书机器人、业务审批、加盟服务流程或 dashboard 产品功能。
- 正式业务状态由 Dashboard 维护，长期规则和判断由 Work OS 维护。

## 新店增长事项交接

Bot 资料摘要经负责人确认后，可用统一入口依次完成资料解析、Site 影子分析和 Dashboard 候选记录生成：

```powershell
python -m scripts.run_new_store_handoff `
  --input-package C:\path\to\input-package.json `
  --storage-root C:\path\to\site-intake `
  --output-dir data\staging\handoff `
  --enable-ocr
```

需要同时导入本机 Dashboard 候选缓冲区时增加：

```powershell
  --import-dashboard `
  --dashboard-repo C:\Work\Projects\lann-dashboard `
  --operator 王凯
```

负责人已在 Bot 对话中确认正式交接，且 Dashboard 校验负责人、重复项和字段均通过时，结果可直接进入正式场地跟进。存在疑似重复、负责人无效或字段冲突时，结果只进入候选区并返回明确原因。
