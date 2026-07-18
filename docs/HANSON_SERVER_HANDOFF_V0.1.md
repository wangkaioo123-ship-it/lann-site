# Hanson 服务器上线交接 v0.1

## 已知服务器基线

- 目录：`/srv/apps/lann-site/repo`
- 用户：`app_lann_site`
- 独立Python venv、GitHub只读deploy key、专用只读飞书凭证已配置。
- 不开放公网、不写飞书、不使用root/sudo、不接触生产项目目录。
- `python -m scripts.extract_base` 已在服务器成功执行。

以上说明服务器框架已部署；完整经营分析定时任务尚未验收。

## 建议频率和消费者

- 每天北京时间07:30运行，随机延迟0–5分钟。
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

## 上线前还需确认

1. 服务器 `.env` 除飞书凭证外，还必须有 `BI_API_BASE_URL` 与 `BI_API_KEY`；代码当前访问BI API，不会自动改用lann-data直连。
2. 将本轮代码commit并push后，由服务器通过只读deploy key执行 `git pull --ff-only`。
3. 以 `app_lann_site` 手工执行一次完整批处理，确认状态为 `success`。
4. systemd单元文件位于 `deploy/systemd/`。安装到 `/etc/systemd/system/` 和启用timer需要Hanson管理员执行；`app_lann_site` 本身继续不授予sudo。

## 管理员安装参考

```bash
sudo cp /srv/apps/lann-site/repo/deploy/systemd/lann-site-refresh.service /etc/systemd/system/
sudo cp /srv/apps/lann-site/repo/deploy/systemd/lann-site-refresh.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lann-site-refresh.timer
systemctl list-timers lann-site-refresh.timer
```

timer只运行分析，不自动拉代码，避免未经验证的代码自动上线。
