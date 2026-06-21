# DEVELOPMENT_LOG.md — lann-site 开发日志

按时间倒序记录每次开发/修复内容，每次完成后在顶部追加。

格式：

```
## [日期] 标题
- 类型：功能 / 修复 / 文档 / 配置
- 内容：
- 改动文件：
- commit：
- 验证方法：
```

---

## 2026-06-21 项目文档初始化（CLAUDE.md / DECISIONS.md / DEVELOPMENT_LOG.md）

- 类型：文档
- 内容：发现目录内原有 CLAUDE.md 实际是 lann-dashboard 项目的内容，与 lann-site 定位不符。重新编写精简版 CLAUDE.md（项目身份、协作纪律、权限边界、文档结构），新建 DECISIONS.md 和 DEVELOPMENT_LOG.md。确认技术栈为 Python，GitHub 仓库地址为 https://github.com/wangkaioo123-ship-it/lann-site.git。
- 改动文件：CLAUDE.md（重写）、DECISIONS.md（新建）、DEVELOPMENT_LOG.md（新建）
- commit：待提交
- 验证方法：用户 review 三份文档内容是否符合预期
