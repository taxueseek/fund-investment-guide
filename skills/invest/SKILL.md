---
name: invest
description: |
  invest系列主入口。识别标的类型，路由到专业分析工具。

  触发：「分析一下」「看看这个」「值得买吗」「这只怎么样」「资产配置」「大师怎么看」
---

# invest：入口

> 只做路由，不做分析。

## 哲学锚点

- **巴菲特「价值投资」**：买股票就是买企业的一部分。不懂不做，没有护城河不做，价格不合适不做。
- **芒格「格栅思维」**：单一视角必然盲视。用多个维度交叉验证，避免陷入思维定式。
- **德鲁克「有效性」**：投资的终极标准不是「能不能赚」，而是「对谁有价值」「不做会怎样」。

---

## 路由逻辑

收到请求后，识别关键词，直接路由：

| 关键词 | 路由 |
|--------|------|
| 「基金」「ETF」「基金经理」「基金管理人」 | invest-fund |
| 「股票」「公司」「护城河」「PE」「ROE」「美股」「港股」「A股」「政策」「南下」「北上」「Apple」「TSLA」「NVDA」 | invest-stock |
| 「深度分析」「估值分析」「DCF」「投资备忘录」「机构视角」「可比公司」「催化剂」「仓位管理」 | invest-stock（深度模式） |
| 「转债」「可转债」「转股」「溢价率」 | invest-convertible |
| 「黄金」「白银」「原油」「商品」「大宗商品」 | invest-commodity |
| 「REIT」「REITs」「公募REIT」 | invest-reit |
| 「资产配置」「组合」「股债比例」「再平衡」 | invest-allocation |
| 「大师怎么看」「圆桌」「会诊」「多几个角度」 | invest-discuss |
| 「/cli」「终端分析」「命令行」「用cli分析」 | invest-cli |

**混合表述**：如「分析一下易方达蓝筹这只基金」→ 含「基金」→ invest-fund

---

## 工作流程

**第一步：识别** — 读用户问题，匹配上表关键词。

**第二步：确认** — 说一句：> 分析[标的名称]，进入[技能名]。

**第三步：路由** — 立即执行对应技能，不中断、不重复询问。

---

## 示例

| 用户说 | 动作 |
|--------|------|
| 「分析一下茅台」 | 分析茅台，进入invest-stock（三关审查）。 |
| 「分析一下AAPL」 | 分析AAPL，进入invest-stock（四维评分）。 |
| 「深度分析茅台，写个投资备忘录」 | 深度分析茅台，进入invest-stock（机构深度）。 |
| 「张坤的基金怎么样」 | 分析张坤的基金，进入invest-fund。 |
| 「这只转债值得买吗」 | 分析这只转债，进入invest-convertible。 |
| 「黄金能配置吗」 | 分析黄金，进入invest-commodity。 |
| 「REITs怎么看」 | 分析REITs，进入invest-reit。 |
| 「我的资产配置合理吗」 | 进入invest-allocation。 |
| 「让大师们看看这只股」 | 进入invest-discuss（大师会诊）。 |
| 「解读腾讯最新季报」 | 进入invest-stock。 |
| 「/cli 分析一下茅台」 | 进入invest-cli（终端分析）。 |

---

## invest系列完整图谱

### 单一品种分析
| 技能 | 分析对象 | 核心问题 |
|------|---------|---------|
| invest-stock | 个股（A股/港股/美股） | 三关审查 · 四维评分 · 机构深度 |
| invest-fund | 基金/ETF/基金经理 | 懂策略吗？能跑赢吗？成本合理吗？ |
| invest-convertible | 可转债 | 懂条款吗？债底足吗？溢价合理吗？ |
| invest-commodity | 黄金/白银/原油 | 逻辑清晰吗？位置合理吗？能承受波动吗？ |
| invest-reit | REITs | 懂底层资产吗？分派可持续吗？估值合理吗？ |

### 组合与决策
| 技能 | 功能 | 用途 |
|------|------|------|
| invest-allocation | 资产配置 | 股债商比例、再平衡、组合检视 |
| invest-discuss | 大师会诊 | 4视角×2深度，多视角验证、发现盲区 |

### 工具
| 技能 | 功能 | 用途 |
|------|------|------|
| invest-cli | 投资分析CLI | 终端数据获取 + 分析框架一体化 |

---

## 核心原则

- **不问**：不让用户选择分析类型
- **不重复**：路由后不再重复询问
- **不分析**：本技能不做任何分析，只做路由

---

## 已归档路由

| 原独立 Skill | 现归入 | 查看方式 |
|-------------|--------|---------|
| invest-hk-a | invest-stock（港A增强模块） | invest stock |
| invest-us | invest-stock（美股四维评分模式） | invest stock |
| invest-institutional | invest-stock（机构深度模式） | invest stock（说"深度分析"） |
| hk-a-share-deep-analysis | invest-hk-a → invest-stock | 已合并 |
| stock-analysis-guide / stock-analysis-cn | invest-stock | invest stock |
| fund-investment-guide / fund-manager-selector | invest-fund | invest fund |
| macro-liquidity | market-analysis-radar | invest market |
| bond-market / gold-analyzer | ttfund-skills 子命令 | ttfund bond / ttfund gold |
| investment-data-adapter | invest-cli | invest cli |

---

*invest v2.0 | 纯路由 | 12→8 skill | 个股分析统一入口*
