# lann-site 服务器批处理部署预案

> 当前状态（2026-08-29）：生产 `current_commit` 与远端 `master` 均为 `1d078d603a1e18d558767bab362b6930b8e258a0`。生产代码部署已经完成；现役受限入口不能读取 timer 和 `data/staging` 结果，因此自然运行产物仍需通过后续 Site 只读结果入口验收，不能继续写成“代码待上线”，也不能反向声称业务产物已验收。

lann-site 不开放公网，只做批处理输出。目标服务器侧只跑“只读数据源 → 清洗/聚合 → 输出本地 staging”这一类无人值守任务。

正式跨系统输入以 lann-data 发布的只读 canonical 聚合及准备好的经营月表为准。仓库中的 Hanson BI/Metabase 直读和双源桥接保留为历史诊断与迁移兼容，不再作为 Dashboard 或其他系统依赖的正式契约。加盟经营评审的当前契约见 `docs/FRANCHISE_OPERATING_REVIEW_V0.1.md`。

## 环境
- Python 3.11+（本地用 3.14 验证过；3.11/3.12 均可）
- 依赖：见 `requirements.txt`（当前仅 `requests`）
  ```
  pip install -r requirements.txt
  ```
- 凭证：复制 `.env.example` 为 `.env` 并按实际启用的只读能力填写。`.env` 已 gitignore，不进库；月度经营评审只消费已准备的正式月表和 canonical 人员聚合，不要求下游获得 Data 原始凭证。

## 批处理入口
```
python -m scripts.extract_base
```
- 作用：读"租赁信息表"（多维表格，租户 token）→ 输出 `data/staging/base_table.csv`
- 只读、不写飞书、不碰云文档、不需要用户 OAuth —— 符合 lann-site 只读边界
- 退出码 0 = 成功；缺凭证会报 `缺少必填配置 XXX`（不泄密钥）

经营数据刷新与分析重建：
```
python -m scripts.refresh_hanson_daily_ops
python -m scripts.rebuild_analysis
python -m scripts.run_server_batch
```
- 第一条是保留的历史 BI 诊断入口，不是现行跨系统正式数据契约。
- 第二条不访问网络，使用本地源文件通过质量闸门后重建分析结果。
- 完整批处理会在重建后自动执行加盟/合资门店经营异常月度核查，读取全部可覆盖门店，结果只写 Site 本地 shadow/staging，不写 Dashboard。
- 月度核查从2026-06自动补跑，每次只推进最早一个尚无成功报告的完整月。Gate失败时保留失败manifest与`auto_backfill_status.json`并让批处理失败，下一次timer继续重试；全部月份成功后恢复最新完整月常规幂等运行。
- 成功月份同时生成全店业务评审与`data/staging/franchise_operating_reviews/business_review.html`静态查看页。页面按月切换并在0候选时继续展示全部参与计算门店；它不新增服务、不调用Dashboard，也不改变候选阈值。
- 月度评审成功后，批处理把最新成功 run 的四个必要 JSON 与可选经营汇总发布到 `data/exports/dashboard-v0.1`。异机 Dashboard 只读拉取该独立目录，不读取仓库、`data/staging` 或 lann-data 原始出口；发布失败不移动跨系统最新成功指针。
- 展示schema升级后，旧成功月份若缺少当前全店评审产物，会由既有补跑机制按月份重新生成一次；旧run保留，不覆盖。
- 建议服务器每日在门店全部结算后的低峰时段运行；即使当天只完成部分门店，趋势截止日也不会前移到不完整日。
- 生产安排频率：每天北京时间07:30；输出当前只由lann-site本地分析消费，不写飞书或dashboard。是否已经形成指定月份成功产物必须读取 manifest/Gate 验证，不能仅根据部署版本或调度安排推断。

## 不在服务器批处理范围（需交互，跑不了无人值守）
- `extract_focus.py` / `extract_forecasts.py`：读测算云文档，需用户 OAuth（2h 过期、要人工登录）
- 合同租金抽取（`download_file` / `ocr_contract` / 看图）：需 OAuth + OCR + 人工读图；OCR 还需系统装 tesseract

## 边界（务必遵守）
- 只读：租赁信息表、加盟商意见记录表；不写入、不删除、不改表结构、不访问无关 Base/table
- deploy key 只读（不勾 Allow write access）
- 飞书凭证用专用 app，不复用生产；密钥只存服务器 `.env`，不提交 git
