# 模型可插拔前置规范 v0.1

本文档定义 AI 矩阵的模型可插拔原则。目标是让业务能力依赖“任务”和“结构化输出”，而不是依赖某一家大模型。

## 一、基本原则

1. 业务代码不直接调用具体模型。
2. 业务流程只依赖标准任务。
3. prompt 独立存放并带版本号。
4. 关键任务输出必须结构化。
5. 每个任务保留评测样本和评分标准。
6. 模型供应商可以替换，业务 schema 不轻易变。

## 二、推荐目录

```text
ai/
  tasks/
    site_candidate_screen.yaml
    site_survey_fact_extract.yaml
    ops_root_cause_analysis.yaml
  prompts/
    site_candidate_screen_v1.md
    meeting_recap_extract_v1.md
  schemas/
    site_candidate_screen.output.schema.json
    external_site_intel.output.schema.json
  evals/
    site_candidate_screen/
    meeting_recap_extract/
  providers/
    openai.py
    anthropic.py
    gemini.py
    local.py
  llm_client.py
```

第一阶段只需要先建规范和少量 schema，不急着接入多个模型。

## 三、标准任务定义

每个任务至少包含：

- `task_id`
- `task_name`
- `owner_project`
- `purpose`
- `input_schema`
- `output_schema`
- `prompt_version`
- `default_model`
- `fallback_model`
- `permission_level`
- `eval_dataset`
- `last_reviewed_at`

## 四、输出结构要求

核心任务必须输出结构化字段，避免只有散文。

示例：候选点位初筛输出应包含：

- `conclusion`
- `confidence`
- `key_evidence`
- `missing_fields`
- `risk_flags`
- `rent_to_sales_ratio`
- `similar_samples`
- `next_actions`
- `source_refs`

## 五、prompt 版本规则

prompt 命名：

```text
{task_id}_v{major}.md
```

升级规则：

- 小幅措辞调整：记录在开发日志，不升级主版本。
- 输出字段变化：升级主版本。
- 判断口径变化：升级主版本，并补 DECISIONS.md。
- 重大失败修正：补评测样本。

## 六、评测样本规则

每个核心任务至少维护：

- 输入材料。
- 王凯认可的标准答案。
- 必须命中的证据。
- 不允许犯的错误。
- 评分标准。

第一阶段最低要求：

- `site_candidate_screen`：10 个样本。
- `site_survey_fact_extract`：5 个样本。
- `meeting_recap_extract`：5 个样本。
- `ops_root_cause_analysis`：5 个样本。

## 七、模型路由原则

第一阶段暂不做复杂模型路由，只定义规则：

- 结构化抽取优先选稳定输出 JSON 的模型。
- 长文会议复盘优先选长上下文和中文理解稳定的模型。
- 经营判断优先选能遵守证据引用和业务规则的模型。
- 外部情报摘要优先选带检索/引用能力的模型或工具链。

任何模型上线前，都必须跑对应任务的 eval 样本。

## 八、权限和审计

每次 AI 任务执行应记录：

- `task_id`
- `prompt_version`
- `model`
- `input_digest`
- `output_path`
- `source_refs`
- `created_at`
- `permission_level`

写入飞书表、修改 dashboard 正式数据、修改工作OS正式判断源，一律不由模型直接执行，必须经过确认。

## 九、第一阶段不做

- 不做多模型自动竞价。
- 不做复杂 multi-agent 调度。
- 不做自动写业务系统。
- 不做未授权外部数据抓取。
- 不把模型输出当作最终业务事实。

