# Data → Site → Dashboard 阿里云同机通道 V0.2

## 当前架构

```text
Hanson / lann-data
  版本化 HTTPS 月度聚合包（只读）
              ↓
LANN 阿里云 / app_lann_site
  校验版本、SHA、大小与回滚 → 运行 Gate 和专业分析
              ↓
/var/lib/lann-site/output/dashboard-v0.1
  最小只读分析快照
              ↓ lann_site_readers
LANN 阿里云 / app_lann_dashboard
  校验后原子更新自身 mirror → 页面展示与人工评审
```

## 责任边界

- Data 只发布脱敏月度聚合，不开放数据库、BI/飞书凭证、SSH 或远程执行。
- Site 只读 Data，保留输入版本和证据，输出分析；不写 Dashboard 业务状态。
- Dashboard 不读取 Data 输入包，只读取 Site 最小快照；正式人工评审和事项仍由 Dashboard 保存。
- Site 与 Dashboard 使用独立系统账号。`app_lann_dashboard` 只能通过 `lann_site_readers` 读取固定导出目录，不能写 Site。

## 发布与失败行为

- Site 的 `scripts.run_remote_franchise_review` 在 Gate 通过后调用同一不可变导出器，发布 `dashboard-v0.1`。
- 导出器只发布版本化最小 DTO；经营汇总严格限制为固定 36 列，源文件中的路径、内部字段及未批准信息不会原样透传。
- 每个可供 Dashboard 读取的快照必须同时携带 Data 包来源审计信息；`source_data` 不允许缺失或为空，导出 manifest 与最新成功指针中的内容必须一致。
- 经营与人员 Gate 的 `ready` 只接受 JSON 布尔值 `true`；字符串、数字、空值和 `false` 均不得发布为 ready。
- 四份 DTO、可选汇总和导出 manifest 先写入不可变 `<month>/<run_id>` 目录；全部完成后才原子提升唯一可变的 `latest_success.json`。指针提升失败会撤销本次新 run，上一完整快照保持可用。
- 分析失败或导出校验失败时不提升导出指针；Dashboard 保留上一成功镜像并标记 stale。
- 相同 run_id 内容变化、月份回滚、HTTP 重定向、4xx 配置/权限错误均硬失败。
- 临时网络失败只允许使用已重新校验的最近成功 Data 包，并在 Site 和 Dashboard 两端明确标旧。
- 导出指针携带 Data 包 ID、数据期间、生成时间、manifest SHA、同步状态和 `stale` 布尔值；Dashboard 镜像必须原样保留并据此标旧。

## 不再需要

- Hanson 主机上的 `site_export` SSH 用户、rrsync、阿里云私钥和来源 IP 白名单。
- Hanson 代跑 Site 或手工拷贝分析结果。
- Dashboard 直接读取 Hanson 仓库目录或 Data 原始文件。
