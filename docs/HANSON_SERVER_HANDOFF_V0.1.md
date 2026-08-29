# Hanson 服务器上线交接 v0.1

> 本文件保留服务器建设历史。现行专业分析、月度评审和反馈契约分别以 `README.md`、`docs/FRANCHISE_OPERATING_REVIEW_V0.1.md`、`docs/PROFESSIONAL_ANALYSIS_FEEDBACK_V0.1.md` 为准。

## 已知服务器基线

- 目录：`/srv/apps/lann-site/repo`
- 用户：`app_lann_site`
- 独立Python venv、GitHub只读deploy key、专用只读飞书凭证已配置。
- 不开放公网、不写飞书、不使用root/sudo、不接触生产项目目录。
- `python -m scripts.extract_base` 已在服务器成功执行。

2026-08-29 只读核验确认生产 `current_commit` 与远端 `master` 均为 `1d078d603a1e18d558767bab362b6930b8e258a0`。代码部署已经完成；受限入口没有 timer/产物读取命令，因此 2026-06、2026-07 v0.2 自然产物的 Gate、参与门店数和候选数仍未能从当前授权通道验收。这是 Site 结果可见性缺口，不是 lann-data 接口缺失。

## 建议频率和消费者

- 生产安排为每天北京时间07:30运行；调度状态和每次结果需以服务器状态/manifest为准，不能根据文档推断成功。
- 该时间用于读取前一日店长日结；若个别门店延迟，程序自动沿用最近全网结算完成日。
- 当前输出只由 lann-site 自身消费，保存在 `data/staging/`，供选址分析和人工复核。
- 暂不写飞书、不推送dashboard；展示层等数据契约稳定后另行接入。

## 完整批处理

```bash
cd /srv/apps/lann-site/repo
.venv/bin/python -m scripts.run_server_batch
```

顺序为：配置预检 → 飞书底表 → 飞书租金 → BI历史月表 → Hanson日报/客户月指标 → 数据契约 → 完整分析。

成功状态写入：

`/srv/apps/lann-site/repo/data/staging/server_batch_status.json`

## 历史上线清单（已被当前部署状态替代）

以下命令仅保留为历史安装参考，不再表示当前“待完成事项”。正式数据输入由 lann-data 只读发布，Site 以自身身份运行；不要把旧 BI 凭证配置当成反馈闭环或月度经营评审的正式接口要求。

## 管理员安装参考

```bash
sudo cp /srv/apps/lann-site/repo/deploy/systemd/lann-site-refresh.service /etc/systemd/system/
sudo cp /srv/apps/lann-site/repo/deploy/systemd/lann-site-refresh.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lann-site-refresh.timer
systemctl list-timers lann-site-refresh.timer
```

timer只运行分析，不自动拉代码，避免未经验证的代码自动上线。
