# LANN Data → Site 只读远程数据包 v1

## 目标

Dashboard 与 Site 运行在 LANN 阿里云，Data 继续由 Hanson 侧治理和发布。跨服务器只传输获批的门店月度聚合，不开放数据库、BI 凭证、个人级明细、SSH 或远程执行能力。

## Manifest

```json
{
  "schema_version": "lann-data-site-package/v1",
  "package_id": "2026-07-20260901T080000Z-a1b2c3d4",
  "generated_at": "2026-09-01T08:00:00+08:00",
  "source_commit": "0123456789abcdef0123456789abcdef01234567",
  "data_period": "2026-07",
  "files": [
    {
      "role": "operating_monthly",
      "url": "site_performance_monthly_bi_feishu_rent.csv",
      "sha256": "64位小写SHA-256",
      "size_bytes": 12345
    },
    {
      "role": "workforce_monthly",
      "url": "store_workforce_monthly.csv",
      "sha256": "64位小写SHA-256",
      "size_bytes": 12345
    }
  ]
}
```

两个正式角色必须同时存在。经营文件需覆盖目标月份及其前两个月；人员文件继续遵守 `store-workforce-monthly/v1` 的25列脱敏契约。

## 安全与运行

- 正式地址只允许 HTTPS。
- 使用独立只读 Bearer Token；Token 只保存在阿里云 root 管理的凭证文件中，不进入代码、日志或 URL。
- Bearer Token 只发送给与 manifest 同源的下载地址；如文件使用对象存储跨域地址，必须使用自身受限签名 URL，Site 不向该域转发 Token。
- 每个文件限制 20MB；下载后同时核对声明大小和 SHA-256。月度聚合超过该规模时先核对是否误含明细数据，不直接放宽限制。
- manifest 与文件地址必须是最终 HTTPS 地址，Site 拒绝所有 HTTP 重定向，避免凭证被降级或转发。
- `data_period` 必须严格使用 `YYYY-MM`；SHA-256 必须是 64 位小写十六进制，禁止通过自动转小写掩盖上游契约错误。
- 同一 `package_id` 内容不可变化；内容变化必须发布新包。
- 远端月份或生成时间不得早于本地最近成功包；同 ID 冲突、校验失败和回滚信号均硬失败，不使用旧包掩盖完整性问题。
- 只有两个文件全部下载并通过校验后，才原子更新 `latest_success.json`。
- 仅连接超时、读取超时、连接中断、分块传输中断及明确的 408/429/500/502/503/504 上游响应可继续使用最近成功包；TLS、认证/4xx、契约校验、完整性校验以及本地文件权限错误均硬失败，不得回退掩盖。
- 回退前重新校验最近成功指针；`package_path` 必须位于配置根目录的 `packages/<package_id>` 内，角色文件也必须位于该包内，防止指针越界读取。
- 阿里云不向 Data 回写，不向 Hanson 服务器发起 SSH，也不要求 Hanson 执行 Site 代码。

V1 的发布信任锚是受控 HTTPS 地址及只读 Token，SHA-256 用于核对传输与不可变性，不防御发布端自身被接管。若后续安全等级提升，再增加独立签名，不在本轮引入第二套密钥体系。

## 迁移门禁

阿里云只启用 `lann-site-remote-review.timer`。安装前必须执行：

```bash
sudo groupadd --system lann_site_readers 2>/dev/null || true
id app_lann_site >/dev/null 2>&1 || sudo useradd --system --home /var/lib/lann-site --shell /usr/sbin/nologin app_lann_site
sudo usermod -aG lann_site_readers app_lann_site
sudo install -d -o root -g root -m 0755 /srv/lann-site/releases
sudo install -d -o root -g root -m 0755 /srv/lann-site/venv
sudo install -d -o root -g root -m 0750 /etc/lann-site
sudo install -d -o app_lann_site -g app_lann_site -m 0750 /var/lib/lann-site/remote-data
sudo install -d -o app_lann_site -g lann_site_readers -m 2750 /var/lib/lann-site/output
sudo chown root:app_lann_site /etc/lann-site/remote-review.env /etc/lann-site/data-package.token
sudo chmod 0640 /etc/lann-site/remote-review.env /etc/lann-site/data-package.token
```

代码发布到 `/srv/lann-site/releases/<commit>`，`/srv/lann-site/current` 只指向通过验收的 release；独立 venv 固定在 `/srv/lann-site/venv`。Site 导出目录及新建子目录必须保持 `app_lann_site:lann_site_readers` 和 setgid，Dashboard 账号只加入 `lann_site_readers`，不得加入 `app_lann_site` 主组。

```bash
systemctl disable --now lann-site-refresh.timer lann-site-refresh.service 2>/dev/null || true
systemctl mask lann-site-refresh.timer lann-site-refresh.service
systemctl is-enabled lann-site-refresh.timer
```

最后一条必须返回 `masked`。旧 `lann-site-refresh` 会运行含 BI/飞书直连的兼容批处理，不得与远程版本包入口并存。启用新 timer 前使用 `systemd-analyze verify` 与 `systemd-analyze calendar '*-*-* 08:10:00 Asia/Shanghai'` 在目标机核验。

每次数据 Gate 通过后，同一任务还会原子发布 `/var/lib/lann-site/output/dashboard-v0.1`。指针同时携带 Data 包期间、生成时间、包 ID、manifest SHA 和 `stale` 状态，使 Dashboard 能明确显示旧数据。只有 Dashboard 使用的最小只读分析产物进入该目录；Data 输入包仍留在 Site 私有目录，不向 Dashboard 暴露。

## 运行入口

```bash
python -m scripts.run_remote_franchise_review
```

所需环境变量：

- `LANN_DATA_PACKAGE_MANIFEST_URL`
- `LANN_DATA_PACKAGE_TOKEN_FILE`
- `LANN_SITE_REMOTE_INPUT_ROOT`
- `LANN_FRANCHISE_OPERATING_REVIEW_ROOT`
- `LANN_SITE_DASHBOARD_EXPORT_ROOT`
