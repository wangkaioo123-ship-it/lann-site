# Site → 阿里云 Dashboard 只读数据通道 V0.1

> 状态：已被 V0.2 替代。V0.1 记录 Site 留在 Hanson 主机时的跨机 rsync 方案；当前 Site 与 Dashboard 已决定同迁 LANN 阿里云，正式方案见 `SITE_DASHBOARD_DATA_CHANNEL_V0.2.md`。

## 结论

当前 lann-data 正式出口是 Hanson 服务器本地的脱敏 canonical 文件/视图，只对同机 `app_lann_site` 开放；仓库与生产说明中没有可供阿里云访问的正式 HTTP API、下载接口或对象存储出口。服务器本地文件可读不等于存在网络接口。

本阶段采用方案 A：Site 自然运行成功后发布最小只读导出目录，阿里云 Dashboard 使用独立受限身份拉取。Site 继续在原服务器自主分析，Dashboard 不挂载仓库目录，也不获得 lann-data 原始文件或凭证。

## 三种通道比较

| 通道 | 改动量 | 稳定性与回滚 | 安全边界 | Hanson/管理员动作 | 结论 |
| --- | --- | --- | --- | --- | --- |
| A. Dashboard 受限拉取 Site 固定产物 | 小；复用 Dashboard PR #5 的 rsync、校验和 stale 回退 | 高；run 不可变，指针最后原子提升，失败保留最近成功快照 | 最小；只读一个导出目录，无 Shell、无仓库与 Data 权限 | 一次创建受限只读身份、公钥、目录 ACL 和来源 IP 白名单 | 当前采用 |
| B. Site 主动推送到阿里云 ingest/OSS | 中；需在 Site 保存外部写凭证并建设重试、幂等、失败队列 | 可做，但发送端写权限与凭证轮换增加故障面 | 较弱；Hanson 主机需持有阿里云写凭证 | 一次配置出站与密钥，后续还需轮换 | 暂不采用 |
| C. 阿里云部署 Site runner 直读 lann-data | 大；需迁移运行环境并先建设 Data 的远程正式出口 | 当前不可验收；Data 只有同机只读出口 | 需新增 Data 网络面或复制数据 | 不只是一次动作，会改变 Data/Site 生产边界 | 当前不可行 |

## 正式数据流

```text
lann-data 本地脱敏出口（只读）
        ↓ app_lann_site
Site 07:30 自然运行、Data Gate、专业分析
        ↓ 成功后本机发布
/srv/apps/lann-site/repo/data/exports/dashboard-v0.1
        ↓ site_export 受限只读 rsync
阿里云 Dashboard incoming
        ↓ 本地契约校验与原子提升
Dashboard mirror（失败时保留上一成功快照并标记 stale）
```

Site 不写 Dashboard，导出始终 `dashboard_write_allowed=false`。Dashboard 的人工评审与正式事项仍由 Dashboard 自己保存。

## Site 导出契约

发布命令已加入 `scripts.run_server_batch` 的最后一步，也可在本地显式验证：

```bash
python -m scripts.publish_dashboard_analysis_export
```

默认源与目标：

- 源：`data/staging/franchise_operating_reviews`
- 目标：`data/exports/dashboard-v0.1`
- 可选经营汇总：`data/staging/site_performance_summary_bi_feishu_rent.csv`

目标目录只包含跨系统所需内容：

```text
dashboard-v0.1/
├── site_performance_summary_bi_feishu_rent.csv       # 可选
└── franchise_operating_reviews/
    ├── export_manifest.json                           # site-dashboard-analysis-export/v0.1
    ├── latest_success.json                            # 最后原子提升
    └── <YYYY-MM>/<run_id>/
        ├── manifest.json
        ├── business_review.json
        ├── analysis_catalog.json
        └── review.json
```

发布前 Site 会检查月份/run_id、各 schema、经营和人员 Gate、`dashboard_write_allowed=false`、专业分析目录身份。相同 run_id 内容变化时拒绝覆盖；失败不移动导出 `latest_success.json`。`export_manifest.json` 记录四个必要文件的 SHA-256 和字节数。正式 schema：`ai/schemas/site_dashboard_analysis_export.v0.1.schema.json`。

Dashboard PR #5 的 `SITE_ANALYSIS_SOURCE` 应指向上述 `dashboard-v0.1` 根目录，而不是仓库或 `data/staging`。

## 唯一一次性服务器动作

代码无法自行创建跨主机身份。Site 服务器管理员需一次完成：

1. 创建无登录 Shell、无 sudo、无写权限的 `site_export` 系统用户。
2. 只允许阿里云 Dashboard 的固定公网 IP 连接该 SSH 身份。
3. 将阿里云生成的专用公钥写入 `site_export` 的 `authorized_keys`，使用 OpenSSH `restrict` 与 forced command，将命令固定为系统实际路径的 `rrsync -ro /srv/apps/lann-site/repo/data/exports/dashboard-v0.1`。不得开放通用 Shell、端口转发、代理、PTY 或任意路径 rsync。
4. 导出目录由 `app_lann_site` 写；`site_export` 仅获得各祖先目录的 traverse（`--x`）和导出目录树的目录 `r-x`/文件 `r--`。在导出根目录设置同样的默认 ACL，保证未来月份继承只读权限；不得对 `/srv/apps/lann-site/repo` 或 `data/staging` 授予目录读取权。
5. 阿里云仅保存该专用私钥（0600），配置 Dashboard PR #5 的 `SITE_ANALYSIS_SOURCE=site_export@<site-host>:/`。`rrsync` 的 `/` 已被限制为上述导出根目录。

这一步完成后，Site 每日自动发布，Dashboard 每15分钟自动拉取；Hanson不运行 Site 分析、不长期搬文件，也不维护业务规则。

## 失败与回滚

- Site Gate 或导出校验失败：不更新导出指针，Dashboard 继续保留上一成功快照并标记 stale。
- 网络/SSH/rsync 失败：不影响 Site 分析，Dashboard mirror 不提升。
- 相同 run_id 内容变化：两端均拒绝覆盖历史。
- 回滚 Dashboard 时只切回上一应用 release；mirror 与 Site 不需要反向写入。
- 回滚 Site 时旧导出仍是只读不可变快照；恢复服务后再次运行发布命令即可。
