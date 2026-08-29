# Site 专业分析身份与反馈契约 V0.1

## 1. 责任边界

Site 是后台专业分析层：只读使用获批数据，输出可解释分析、证据、缺口、结论与建议。Dashboard 保存人工评审、执行动作、后续结果和正式业务状态；Work OS 保存长期规则。Site 不直接修改 Dashboard，也不会根据单次反馈自动改变规则。

本轮不新增 API、数据库、队列或在线服务。契约通过版本化 JSON 文件交接，先跑通真实反馈闭环，再考虑统一助手工具化。

## 2. 现有分析产物盘点

| 分析能力 | 当前主要产物 | 共同身份现状 | 本轮处理 |
|---|---|---|---|
| 加盟门店月度经营评审 | `manifest.json`、`business_review.json`、`review.json` | 已有 run、月份、输入摘要和规则版本，但缺少逐门店 `analysis_id` | 新增 `analysis_catalog.json`，作为首个正式共同身份实现 |
| 候选场地/新店初审 | `site_record/v0.1`、shadow analysis、资料审核稿 | 已有场地/项目身份和证据，但没有统一 `analysis_id` | 暂保持原契约；后续只需套用同一分析记录信封，不重写 OCR/PDF 细节 |
| 历史经营归因/选址样本 | CSV、manifest、归因文档 | 有对象和月份，输入指纹不完全一致 | 本轮只记录迁移边界，不重做历史产物 |
| 租金压力/投资测算 | 敏感性与项目测算产物 | 规则、输入假设和对象身份分散 | 后续采用同一信封；正式商务事实仍归 Dashboard |

## 3. Site → Dashboard：专业分析目录

文件：每个月度经营 run 目录中的 `analysis_catalog.json`。

- 目录版本：`professional-analysis-catalog/v0.1`
- 记录版本：`professional-analysis-record/v0.1`
- Schema：`ai/schemas/professional_analysis_catalog.v0.1.schema.json`
- 当前首个 `analysis_type`：`franchise_operating_review`
- 写入边界：`dashboard_write_allowed=false`

每条记录统一包含：

- `analysis_id`：由分析类型、源 run、canonical 对象、分析期间、规则版本和规范化完整输入身份摘要稳定生成；
- `canonical_object`：当前为 canonical `Lxxxx` 门店；
- `analysis_period`：自然月起止；
- `input_identity`：源 run、分析管线版本，以及每个必要输入的 `source`、`sha256`、`data_version`、`source_commit` 和行数；输入按 `source` 规范排序、空值统一为 `null` 后计算 `identity_sha256`。输入顺序变化不改变身份，任何输入内容或版本变化都会生成不同 `analysis_id`；
- `rule_version`：本次分析使用的业务规则版本；
- `confidence`：经营 Gate、人员 Gate 和人员可信等级；
- `evidence.direct_facts`：原始或正式聚合事实；
- `evidence.statistical_differences`：计算差异，不表达因果；
- `evidence.proxy_metrics`：工作人天等代理指标；
- `evidence.hypotheses`：待核查解释；
- `evidence_gaps`：当前证据不能回答的事实；
- `conclusion`、`suggestions`、`generated_at`。

简化示例：

```json
{
  "schema_version": "professional-analysis-record/v0.1",
  "analysis_id": "ana_0123456789abcdef01234567",
  "analysis_type": "franchise_operating_review",
  "canonical_object": {
    "object_type": "store",
    "canonical_id": "L0015",
    "display_name": "示例门店"
  },
  "analysis_period": {"grain": "month", "start": "2026-07", "end": "2026-07"},
  "rule_version": "franchise-operating-check/v0.1",
  "confidence": {
    "level": "medium",
    "operating_gate": "passed",
    "workforce_gate": "passed",
    "workforce_data_trust": "中",
    "note": "人员证据只用于交叉解释；低可信或缺失时不支持较强人员结论。"
  },
  "dashboard_write_allowed": false
}
```

## 4. Dashboard → Site：人工反馈导出

- 版本：`professional-analysis-feedback/v0.1`
- Schema：`ai/schemas/professional_analysis_feedback.v0.1.schema.json`
- `source_system` 必须是 `lann-dashboard`。
- 一条反馈必须同时匹配 `analysis_id + canonical_object + analysis_period + rule_version`。
- 支持的评审状态：`accepted`、`false_positive`、`continue_observation`、`data_missing`、`known_special_cause`。
- `actions=null` 表示动作关联未知；`actions=[]` 表示已确认没有动作；两者不能混用。
- `outcome=null` 表示后续结果尚未提供，不得解释成“没有结果”或“结果为0”。
- 相同 `feedback_id` 且内容完全相同视为幂等重复；相同 ID 内容冲突或同一分析出现两个不同反馈 ID 时拒绝。

简化示例：

```json
{
  "schema_version": "professional-analysis-feedback/v0.1",
  "export_id": "dashboard-export-2026-08-29",
  "source_system": "lann-dashboard",
  "exported_at": "2026-08-29T10:00:00+08:00",
  "feedbacks": [
    {
      "feedback_id": "review-001",
      "analysis_id": "ana_0123456789abcdef01234567",
      "canonical_object": {
        "object_type": "store",
        "canonical_id": "L0015",
        "display_name": "示例门店"
      },
      "analysis_period": {"grain": "month", "start": "2026-07", "end": "2026-07"},
      "rule_version": "franchise-operating-check/v0.1",
      "review": {
        "status": "continue_observation",
        "reviewed_at": "2026-08-29T10:00:00+08:00",
        "reviewer_id": "dashboard-user-id",
        "note": "继续观察一个完整月",
        "special_cause": null
      },
      "actions": null,
      "outcome": null
    }
  ]
}
```

## 5. Site 校准质量汇总

命令：

```powershell
python -m scripts.build_analysis_calibration_summary `
  --analysis-catalog C:\path\to\analysis_catalog.json `
  --feedback-export C:\path\to\dashboard_feedback.json
```

输出根目录默认为 `data/staging/analysis_calibration/`：

```text
analysis_calibration/
├── last_attempt.json
├── latest_success.json
└── cal_<stable-id>/
    ├── manifest.json
    └── calibration_summary.json
```

汇总版本为 `professional-analysis-calibration-summary/v0.1`，包含总分析数、已评审数、各评审类型、存在动作数、已有结果数、未评审清单、动作关联未知清单和缺结果清单。原始分析不会被覆盖，`automatic_rule_change_allowed=false`。

目录、反馈或输出任一阶段失败时：

- `last_attempt.json` 写入 `stale=true`、原始错误类型与原因，并用 `failure_source` 区分 `catalog`、`feedback`、`output`；状态分别为 `blocked_by_analysis_catalog`、`blocked_by_feedback_input`、`blocked_by_output`；
- `latest_success.json` 与上一份成功汇总保持不变；
- 不生成新汇总、不修改原始分析、不写 Dashboard。

## 6. Dashboard 后续最小配合

Dashboard 只需：

1. 读取并展示 `analysis_catalog.json` 的分析事实、可信度、缺口和建议；
2. 在自己的正式数据中保存评审、动作和结果；
3. 按反馈 schema 导出当前评审快照；
4. 保证四元身份不被页面字段转换或门店名称匹配破坏；
5. 把反馈导出失败、身份冲突和待补结果显示给业务人员，不把 Site 结论直接升级为正式事项。

## 7. 生产事实与当前可见性

截至 2026-08-29，只读核验确认：

- 远端 `master` 与生产 `current_commit` 均为 `1d078d603a1e18d558767bab362b6930b8e258a0`；
- lann-data → Site 的只读数据通路不属于当前阻断；
- 现役受限入口仅开放 `lann-site status/preflight/deploy`，不能读取 timer 状态或服务器 `data/staging` 产物。

因此当前能够确认代码部署，不能从现有授权通道确认 2026-06、2026-07 的 v0.2 自然产物、Gate、参与门店数、候选数和三个月明细。最小缺口是 Site 自身的只读结果状态/下载能力；这不等于数据接口未上线，也不应要求数据侧重新开放接口。
