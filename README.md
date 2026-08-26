# lann-site

LANN 专业分析与 AI 判断项目。当前主线仍是选址分析：用已开业门店的实际经营结果、租金和选址调研资料建立可解释的历史归因，再用于候选点位初筛。后续可以在同一分析层扩展经营分析、租金压力和投资测算，但不承接业务流程或正式数据写入。

## 当前运行形态

- Hanson 已在 `/srv/apps/lann-site/repo` 建立独立用户、venv、只读deploy key和只读飞书凭证；飞书底表抽取已验证。
- 完整经营分析仍待本轮代码push、服务器BI只读凭证确认和systemd timer安装验收。
- 建议每天北京时间07:30运行，当前输出只保存在服务器本地供 lann-site 消费；详见 `docs/HANSON_SERVER_HANDOFF_V0.1.md`。
- 经营主链已完成双源接续：王磊月度稿使用至 2026-03，Hanson 日结 `prod_amt` 从 2026-04 接续。当前完整月已更新至 2026-06，滚动趋势统一截止最近全网结算完成日 2026-07-17；详见 `docs/BI_REALTIME_SOURCE_REVIEW_V0.1.md`。

## 环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

OCR 合同脚本需要额外安装：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ocr.txt
```

复制 `.env.example` 为 `.env`，只填写只读飞书与 BI 凭证。密钥和 `data/` 不进入 Git。

## 标准分析顺序

刷新 Hanson 日结是只读网络操作，先执行：

```powershell
.\.venv\Scripts\python.exe -m scripts.refresh_hanson_daily_ops
```

该命令只输出本地日结聚合、完整月结果、质量问题和30/90天趋势。当天只有部分门店完成结算时，趋势会自动退回最近一个全网结算完成日。

每次更新飞书底表、BI 月表、租金、门店映射或 Hanson 日结后，执行统一重建入口：

已确认的换铺/迁址经营期维护在 `config/site_identity_episodes.json`，源表不因分析需要被覆盖。

```powershell
.\.venv\Scripts\python.exe -m scripts.rebuild_analysis
```

服务器完整批处理入口为：

```powershell
.\.venv\Scripts\python.exe -m scripts.run_server_batch
```

该入口先按 `config/ops_source_policy.json` 生成双源月表，再执行身份与数据契约检查；存在 `ERROR` 时停止下游重建。关键本地输出：

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

每次成功运行还生成全店只读业务评审。`data/staging/franchise_operating_reviews/business_review.html`可在已成功月份间切换；即使候选数为0，也会按营收直接变化率展示全部参与计算门店、目标月经营/人员事实、现行门槛距离、可能解释与证据缺口。该页面不使用综合风险评分，不写Dashboard，也不会用固定9家历史校准名单替代正常全量扫描。

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
