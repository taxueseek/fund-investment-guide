---
name: fund-investment-guide
description: |
  invest系列主入口。识别标的类型，路由到专业分析工具。覆盖个股、基金、可转债、大宗商品、REITs、资产配置、大师会诊；可选 invest-cli 取数（配置东财/yfinance 后启用）。

  触发：「分析一下」「看看这个」「值得买吗」「这只怎么样」「资产配置」「大师怎么看」「基金分析」「股票分析」「黄金能买吗」「转债」「REITs」「/cli」

  Fund analysis and investment guidance. Trigger whenever users mention any fund-related questions.
  Optional structured data via invest-cli after configuring EASTMONEY_APIKEY / yfinance.
license: MIT
version: 2.0.2
---

# Invest 系列：投资分析指南

> 买基金像请管家，买股票像合伙做生意。不懂的人、不靠谱的人、要价太高的人，都不能托付。

这个工具帮你三件事：**看清投的是什么，判断值不值得投，确定价格合不合适**。

## 快速开始

```bash
npx skills add taxueseek/fund-investment-guide
```

装上即用判断框架。可选配置数据源后启用结构化取数，见 `docs/data-sources.md`。

## 路由

进入 `skills/invest/SKILL.md`，按标的类型转发到 invest-stock / invest-fund / … / invest-cli。

## 版本

**v2.0.2** — 配置门闩、数据源引导、CLI 加固、公开路由消毒。

> 本工具仅供教育与研究，不构成投资建议。
