# lann-site 服务器批处理部署预案

> 状态（2026-07-18）：Hanson 已在 `/srv/apps/lann-site/repo` 完成独立用户、venv、只读deploy key和只读飞书凭证设置，`extract_base` 已成功执行。完整经营分析和timer尚待本轮代码上线验收。

lann-site 不开放公网，只做批处理输出。目标服务器侧只跑“只读数据源 → 清洗/聚合 → 输出本地 staging”这一类无人值守任务。

Hanson BI 日结 `prod_amt` 已在本地主分析链完成接入：完整月更新至 2026-06，滚动趋势截止 2026-07-17。完整服务器交接见 `docs/HANSON_SERVER_HANDOFF_V0.1.md`。

## 环境
- Python 3.11+（本地用 3.14 验证过；3.11/3.12 均可）
- 依赖：见 `requirements.txt`（当前仅 `requests`）
  ```
  pip install -r requirements.txt
  ```
- 凭证：复制 `.env.example` 为 `.env` 并填入（**专用只读飞书 app**，详见该文件注释）。`.env` 已 gitignore，不进库。

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
- 第一条只读 Hanson BI，生成门店级日/月聚合和趋势。
- 第二条不访问网络，使用本地源文件通过质量闸门后重建分析结果。
- 完整批处理会在重建后自动执行加盟/合资门店经营异常月度核查，读取全部可覆盖门店，结果只写 Site 本地 shadow/staging，不写 Dashboard。
- 建议服务器每日在门店全部结算后的低峰时段运行；即使当天只完成部分门店，趋势截止日也不会前移到不完整日。
- 确认频率：每天北京时间07:30；输出当前只由lann-site本地分析消费，不写飞书或dashboard。

## 不在服务器批处理范围（需交互，跑不了无人值守）
- `extract_focus.py` / `extract_forecasts.py`：读测算云文档，需用户 OAuth（2h 过期、要人工登录）
- 合同租金抽取（`download_file` / `ocr_contract` / 看图）：需 OAuth + OCR + 人工读图；OCR 还需系统装 tesseract

## 边界（务必遵守）
- 只读：租赁信息表、加盟商意见记录表；不写入、不删除、不改表结构、不访问无关 Base/table
- deploy key 只读（不勾 Allow write access）
- 飞书凭证用专用 app，不复用生产；密钥只存服务器 `.env`，不提交 git
