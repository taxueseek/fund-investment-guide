---
name: invest-upgrade
description: |
  升级 invest 系列 skills 到最新版本。
  触发：/invest-upgrade、「升级invest」、「更新投资系列」
---

# invest-upgrade

升级 invest 系列 skills，显示版本变化和更新内容。

## invest 系列成员

```
invest/          ← 主入口路由
invest-stock/    ← 股票分析
invest-fund/     ← 基金/ETF分析
invest-report/   ← 财报解读（含科技股专项）
invest-hk-a/     ← 港A股深度分析
invest-us/       ← 美股价值投资
invest-upgrade/  ← 本工具
```

备份位置：`~/.claude/skills/_invest_backup_20260324/`

## 升级方式

invest 系列目前为本地维护版本，暂无远程仓库自动更新。升级步骤：

1. 运行 `/skill-creator` 对需要改进的子 skill 进行迭代
2. 更新对应 skill 目录下的 SKILL.md 和 references/ 文件
3. 如有跨 skill 改动，同步更新 `invest/SKILL.md` 路由表

如需查看当前各 skill 版本信息：
```bash
grep -h "^name:" ~/.claude/skills/invest*/SKILL.md
```
