# site_shadow_analysis eval 样本说明

本目录验证候选场地的本地影子分析契约。结果仅用于人工验收，不写飞书、dashboard 或其他正式业务数据。

## Bot 中性输入握手

`sijing_neutral_input.json` 按 lann-work-bot `buildInputPackage()` 的
`lann-site-neutral-input/v0.1` 构造。验收要求：

- 来源文件和本地存储引用能够进入 Site 内部资料登记。
- 用户文字补充保留原文，但转换时不直接冒充资料事实或王凯判断。
- 未转写语音明确进入缺失信息。
- 转换完成后 `facts`、`judgments` 仍为空，状态为“待资料解析”。
- `dashboard_allowed=false` 必须贯穿转换和影子输出；若上游允许或已经尝试 dashboard 写入，Site 拒绝接收。
- 契约转换成功不能表述为 PDF 内容已经解析。

## 泗泾固定样例必须满足

- 租金状态为“已明确”。
- 前期工程初筛为“已完成-无阻断问题”，但专业工程现场勘察仍为“未开始”。
- 经营可行性勘察为“已完成-值得推进”，明确这是王凯与分公司总经理的人工判断。
- 场地阶段固定为Dashboard枚举“可推荐”，不得因客户仍在考察改成“等待客户决定”。
- 经营收益风险为“低”，同时输出“不构成盈利保证”的限定语。
- 共推荐 5 位客户，其中 3 位只放弃该场地，客户状态仍为“继续考察LANN项目”；2 位仍考察该场地。
- 两位考察客户按推荐时间排序。
- 普通客户决策期 14 天，紧急客户 7 天。
- 超期只能写“超期未决-待负责人确认”，不得自动改成“已放弃”。
- 客户匹配结果不得改变场地阶段。
- 铺位图只贡献可直接证实的资料事实，不输出动线、楼层或生意优劣评分。
- 输出必须为 `writeback_allowed=false` 且 `human_confirmation_required=true`。

## 运行

先验证 Bot → Site 中性握手：

```powershell
python -m scripts.convert_neutral_site_input `
  --input ai/evals/site_shadow_analysis/sijing_neutral_input.json `
  --output data/staging/site_shadow_analysis_sijing_internal_from_bot.json

python -m scripts.build_site_shadow_analysis `
  --input data/staging/site_shadow_analysis_sijing_internal_from_bot.json `
  --output data/staging/site_shadow_analysis_sijing_from_bot.json
```

再验证已完成人工结构化的内部分析态：

```powershell
python -m scripts.build_site_shadow_analysis `
  --input ai/evals/site_shadow_analysis/sijing_input.json `
  --output data/staging/site_shadow_analysis_sijing.json
```

自动测试见 `tests/test_neutral_site_input.py` 和 `tests/test_site_shadow_analysis.py`。
