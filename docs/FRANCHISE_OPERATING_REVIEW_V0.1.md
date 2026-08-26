# 加盟经营异常月度核查 V0.1

## 目的与边界

每个完整自然月的数据就绪后，lann-site 生成一次加盟/合资门店经营异常候选与人员证据增强评审包。

- 不是实时预警，不增加综合风险评分。
- 候选规则仍为 `franchise-operating-check/v0.1`，人员数据只解释现有候选，不决定候选名单。
- 输出是 Site 只读候选；`dashboard_write_allowed=false`。人工领取后，才由 Dashboard 建立正式加盟服务事项。
- 只读取门店月度脱敏聚合，禁止读取或复制北森个人级数据。
- 候选数组与业务评审展示分开：即使当月 `candidate_count=0`，业务评审仍展示全部形成连续比较窗口的门店，不能把空候选解释为“没有经营问题”。

## 正式输入

1. 经营月表：`data/staging/site_performance_monthly_bi_feishu_rent.csv`。
2. 人员月表：`/opt/management-dashboard/data/canonical-snapshot/store_workforce_monthly.csv`。
3. 历史回放可选固定候选：`ai/evals/fixed_2026_07_franchise_candidates.json`。

人员文件必须是正式固定 25 列聚合 schema，并能映射到以下语义：canonical `store_id`、自然月、月初/月末/月均在岗人数、入职/离职/调入/调出、短期支援调入/调出、净变化、店长更换候选、可信等级、覆盖状态和截止日期。

生产核验已确认：2026-08-18 12:31:08 +08:00 时文件为 25 列、412 行（含表头）、411 条数据、54,193 bytes，`data_version=store-workforce-monthly/v1`，生产代码 commit 为 `64080775db87793e5308e3a9e7d0a1a58dba4d23`；CSV 没有独立 `schema_version` 或 `source_version` 列。完整正式表头与语义映射已固化在 `config/store_workforce_monthly.v1.contract.json`。

Site 不按相似列名猜测。运行时通过 `--workforce-contract` 读取精确且有序的 25 列、`data_version` 列、期望版本、生产 commit 和语义映射。表头顺序、版本或映射任一不一致，均视为 Gate 失败，不生成候选。每次运行计算实际 CSV SHA-256 并写入 manifest；2026-08-18 参考文件 SHA 为 `df248f55dea3cd1595e7ec8083da3219b585655696832a8d218aedf46c9a5959`，仅用于当次核对，不作为未来月份固定允许值。

## 数据 Gate

只有以下 Gate 全部通过才生成候选评审：

- 经营数据截止最新完整自然月；显式历史回放月份也必须已经闭月。
- 经营门店覆盖率和核心字段完整度均达到既有 V0.1 要求。
- 人员文件恰为 25 列，不含姓名、人员键、电话、证件、薪资或个人排班字段。
- 人员门店编号全部为 canonical `Lxxxx`，门店月不重复。
- 加盟/合资范围人员覆盖率不低于 80%，本轮候选人员覆盖率为 100%。
- 候选人员字段完整度和映射完整度均为 100%。
- 候选人员数据通常要求中或高可信；2026-06已确认只能低可信使用，字段和覆盖通过时允许作为辅助限制进入报告，但不得形成较强人员结论。其他月份的低可信和所有未知可信仍会阻断。
- `snapshot_coverage_status=unavailable/missing/failed` 会阻断；`partial/incomplete` 可保留为有限证据，但不能单独支持快照型较强结论。

当月未闭月数据只写入 `trend_only_months`，不参与候选。任一关键 Gate 失败时，运行状态为 `blocked_by_data_gate`，`review.json` 的候选数组为空，并在 `data_gate.json` 与 `review.md` 给出原因。

## 证据表达

每家候选固定分为四层：

1. **直接事实**：月初/月末/月均人数、入离职、调动、支援、店长更换候选、覆盖和可信等级。
2. **代理指标**：每名月均在岗理疗师对应工作人天，以及人员数量与营收、客次、人效的同向关系。
3. **核查假设**：人员侧事实是否增强、辅助或削弱原核查方向。
4. **证据缺口**：现场原因、排班与技能结构、支援持续时间、店长实际变更及已采取动作。

“人员侧较强交叉证据 / 有辅助证据 / 无法支持或证据不足”只是证据归类，不是风险评分。报告不得把相关性写成因果。

全店业务评审另按“最近2个完整月平均营收相对此前3个月平均营收的变化率”由下降大到增长排序。该排序只是一项直接统计差异，不生成综合风险评分，也不改变候选门槛。每店展示目标完整月营收、订单客次、总客数、新老客、折扣后客单价、理疗师工作人天、日均产值、生产率及可用人员聚合。若订单客次缺失，不用总客数冒充客次；若人员事实缺失，不用工作人天冒充在岗人数。

每家门店同时列出两条现行候选路径的实际值、门槛、是否达到及尚差幅度：经营组合下降路径为营收下降至少8%，并伴随总客数/老客至少下降5%、新客至少下降15%或工作人天下降至少8%；租金压力路径为近3月平均租售比高于25%，且营收下降至少3%。这些只是对既有`franchise-operating-check/v0.1`的透明解释，没有调整阈值。

此前固定9家是2026-07历史校准回放，需要显式`--candidate-freeze`；正常自动运行不使用冻结名单，而是全量扫描。二者的候选数不能直接横比。页面会显示本次运行模式，并明确“全量扫描0候选”只代表本次输入未达到规则门槛。

证据归类规则固定为：近 2 月月均人数较此前 3 月下降至少 8%、目标月末较上月末减少至少 1 人，或最近单月离职+调出至少 2 人（最近两月合计至少 3 人）时，视为存在人员变化信号。鉴于 2026-01—06 只能作辅助，只有“目标月事件覆盖完整且离职+调出至少 2 人”，或“目标月与上月均有中/高可信完整快照且月末减少至少 1 人”，并同时与营收及至少一项客次/工作人天/生产率同向下降，才归为“人员侧较强交叉证据”。仅由早期估算月份形成的趋势最多归为“有辅助证据”。这些条件只整理证据，不参与候选生成。

## 运行

生产自动补跑（`lann-site-refresh.timer`调用的服务器批处理使用此模式）：

```bash
cd /srv/apps/lann-site/repo
.venv/bin/python -m scripts.build_franchise_operating_review \
  --auto-backfill-from 2026-06 \
  --workforce-contract /srv/apps/lann-site/repo/config/store_workforce_monthly.v1.contract.json
```

调度从2026-06扫描到当前最新完整自然月。每次只处理最早一个没有`ready_for_business_review`成功manifest的月份：首次运行选择2026-06；成功后下一次选择下一个缺失月；Gate失败的月份不算成功，继续留在队首，输入数据刷新后自动产生新的稳定run并重试。全部月份追平后，同一命令恢复最新完整月的常规幂等运行。自动模式读取全门店范围，不接受`--candidate-freeze`。

每月正常运行：

```bash
cd /srv/apps/lann-site/repo
.venv/bin/python -m scripts.build_franchise_operating_review \
  --workforce-contract /srv/apps/lann-site/repo/config/store_workforce_monthly.v1.contract.json
```

首次 2026-07 固定 9 家回放：

```bash
.venv/bin/python -m scripts.build_franchise_operating_review \
  --month 2026-07 \
  --candidate-freeze ai/evals/fixed_2026_07_franchise_candidates.json \
  --workforce-contract /srv/apps/lann-site/repo/config/store_workforce_monthly.v1.contract.json
```

生产契约示例路径：

```bash
.venv/bin/python -m scripts.build_franchise_operating_review \
  --workforce-contract /srv/apps/lann-site/repo/config/store_workforce_monthly.v1.contract.json
```

生产契约只保存表头、版本、生产 commit 和字段映射，不保存数据、固定文件 SHA 或密钥。

## 产物与幂等

产物根目录：`data/staging/franchise_operating_reviews/`。

```text
franchise_operating_reviews/
├── auto_backfill_status.json
├── last_attempt.json
├── latest_success.json
└── YYYY-MM/<run_id>/
    ├── manifest.json
    ├── data_gate.json
    ├── review.json
    ├── review.md
    ├── business_review.json  # 全部参与计算门店的结构化业务评审
    ├── business_review.md    # 全店差异排序与规则距离
    └── candidates.csv       # Gate通过时才有
```

产物根目录还会生成：

- `business_review_index.json`：当前展示版本已成功月份及其run索引；
- `business_review.html`：无需服务端的只读静态页面，可在2026-06、2026-07及后续成功月份之间切换。

展示版本加入run身份和成功判定。上线后，旧的成功manifest若没有当前`business_review_schema_version`，自动补跑会从最早缺少展示产物的完整月份重新生成一次；同一输入的新展示run仍保持稳定ID与幂等，旧产物不覆盖。

`run_id` 由运行月份、经营和人员文件 SHA-256、规则版本、固定候选文件摘要及候选顺序共同生成。同一输入重复运行返回 `unchanged`，不创建第二批候选；输入发生变化则保留新的 run 目录，旧版本不被覆盖。

`manifest.json` 记录输入路径、摘要、行数、25 列映射、规则版本、候选顺序、生成时间和写入边界，可用于复盘与回滚核对。

`auto_backfill_status.json`记录扫描起点、最新完整月、成功月份、待补月份、本次选择月份、run状态与路径。它是Site本地运行状态，不是Dashboard业务事项。

## 常见失败提示

- `目标月份尚未闭月`：本月只能看趋势。
- `人员聚合 schema 应为 25 列`：发布契约发生变化，停止读取。
- `缺少经数据发布方确认的人员生产契约`：检查已发布的 `config/store_workforce_monthly.v1.contract.json` 是否存在，不按名称相似度或列位置猜测。
- `人员数据缺少候选门店`：补齐 canonical 门店月后重跑。
- `候选门店人员可信等级不足`：除已确认只作辅助的2026-06低可信外，只保留 Gate 失败记录，不生成候选。

生产部署后由 Site 现有 `lann-site-refresh.timer` 在经营月表刷新成功后自动调用补跑模式。调度每日最多推进一个缺失成功月；Gate失败会让服务器批处理明确失败并在下一次自动重试。同一月份、同一输入只会形成一个run；这不是实时预警。Hanson/lann-data只负责持续发布只读聚合出口，不代替Site执行分析。

正常生产运行读取正式出口覆盖的全部门店。固定 9 家文件只用于 2026-07 历史校准，不限制数据读取范围。`data_gate.json` 会记录人员出口的总行数、门店数、月份、目标范围覆盖数和缺失门店，先用于确认数据通道是否满足分析需要。
