---
name: invest
description: |
  invest系列主入口。识别标的类型，路由到专业分析工具。

  触发：「分析一下」「看看这个」「值得买吗」「这只怎么样」「资产配置」「大师怎么看」「债券」「流动性」「市场环境」「比特币抄底」
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
| 「股票」「公司」「护城河」「PE」「ROE」「美股」「Apple」「TSLA」「NVDA」「港股」「南下」「北上」「深度分析」「DCF」「机构视角」「IC」 | invest-stock（A股/港股/美股+机构深度） |
| 「转债」「可转债」「转股」「溢价率」 | invest-convertible |
| 「黄金」「白银」「原油」「商品」「大宗商品」 | invest-commodity |
| 「REIT」「REITs」「公募REIT」 | invest-reit |
| 「资产配置」「组合」「股债比例」「再平衡」 | invest-allocation |
| 「大师怎么看」「圆桌」「巴菲特和芒格」「会诊」「多几个角度」 | invest-discuss |
| 「债券」「国债」「利率债」「信用债」「城投」「债市」「利差」「久期」 | invest-bond |
| 「流动性」「美联储」「缩表」「SOFR」「MOVE」「市场环境」「美股情绪」「NAAIM」「市场过热」「比特币抄底」「MVRV」「钱紧不紧」 | invest-macro |

**混合表述**：如「分析一下易方达蓝筹这只基金」→ 含「基金」→ invest-fund

---

## 工作流程

**第一步：识别**
读用户问题，匹配上表关键词。

**第二步：确认**
说一句：

> 分析[标的名称]，进入[技能名]。

**第三步：路由**
立即执行对应技能，不中断、不重复询问。

---

## 示例

| 用户说 | 动作 |
|--------|------|
| 「分析一下茅台」 | 分析茅台，进入invest-stock。 |
| 「张坤的基金怎么样」 | 分析张坤的基金，进入invest-fund。 |
| 「这只转债值得买吗」 | 分析这只转债，进入invest-convertible。 |
| 「黄金能配置吗」 | 分析黄金，进入invest-commodity。 |
| 「REITs怎么看」 | 分析REITs，进入invest-reit。 |
| 「我的资产配置合理吗」 | 进入invest-allocation。 |
| 「让巴菲特和芒格看看这只股」 | 进入invest-discuss（大师会诊）。 |
| 「解读腾讯最新季报」 | 解读腾讯最新季报，进入invest-stock。 |
| 「深度分析茅台，写个投资备忘录」 | 深度分析茅台，进入invest-stock（深度研报模式）。 |

---

## invest系列完整图谱

### 单一品种分析
| 技能 | 分析对象 | 核心问题 |
|------|---------|---------|
| invest-stock | 个股（A股/港股/美股+机构深度） | 懂生意吗？有护城河吗？价格合适吗？ |
| invest-fund | 基金/ETF/基金经理 | 懂策略吗？能跑赢吗？成本合理吗？ |
| invest-convertible | 可转债 | 懂条款吗？债底足吗？溢价合理吗？ |
| invest-commodity | 黄金/白银/原油 | 逻辑清晰吗？位置合理吗？能承受波动吗？ |
| invest-reit | REITs | 懂底层资产吗？分派可持续吗？估值合理吗？ |
| invest-bond | 债券（利率/信用） | 偿付可靠吗？收益好吗？收益率/利差贵吗？ |

### 组合与决策
| 技能 | 功能 | 用途 |
|------|------|------|
| invest-allocation | 资产配置 | 股债商比例、再平衡、组合检视 |
| invest-discuss | 大师会诊 | 4视角×3深度，多视角验证、发现盲区 |
| invest-macro | 宏观与市场环境 | 全球流动性、美股情绪、加密底部信号、市场温度 |

---

## 核心原则

- **不问**：不让用户选择分析类型
- **不重复**：路由后不再重复询问
- **不分析**：本技能不做任何分析，只做路由

---

## 数据层（invest-cli，单一数据入口）

**Agent 只需这一个数据点：** 所有取数走 `invest-cli`（intent / info / datasources），不要为每个数据源单独加载或路由一个 skill。invest-cli 自含，直接调各数据源的 HTTP API / 全局 CLI / 引擎，不 import 任何独立 skill 文件。

各分析 skill 的取数统一交给 `invest-cli`，按数据源门闩路由：

| 数据源 | 覆盖 | 优先级 |
| --- | --- | --- |
| Wind（万得） | 个股/基金/指数/债券/宏观/资讯 | 80 |
| 盈米且慢 | 基金/策略/财富/资讯 | 70 |
| 东方财富 | 行情/基金/选股 | 50 |
| yfinance | 美股 | 40 |
| 天天基金（ttfund） | 基金/债券/黄金/宏观/配置/研究（需登录） | 30 |

- 取数前先执行 `invest-cli datasources --json` 探测可用源。
- 场景级路由与降级规则见 `invest-cli/docs/data-sources.md`。
- 数据来源必须在输出中标注，口径不一致不合并。

### 场景 → invest-cli 取数映射（单一真源）

各分析 skill 取数以此表为准，优先走 invest-cli，不靠 web_search 猜数据。

**取数一律走 intent 语义入口（接口面收敛，内部路由到权威源）：**

| 场景 | intent 命令 |
| --- | --- |
| 个股深查（A股/港股/美股） | `invest-cli intent deep stock <代码>` |
| 基金深查 | `invest-cli intent deep fund <代码>` |
| 债券 | `invest-cli intent deep bond <代码>` |
| 黄金/商品 | `invest-cli intent deep commodity` |
| 宏观/市场 | `invest-cli intent macro`（argo 垂直源：nbs_stats/eurostat/jin10/fred，免配额） |
| 组合诊断/配置 | `invest-cli intent portfolio <持仓json>` |
| 家庭财务规划 | `invest-cli intent plan <家庭数据json>` |
| 筛选 | `invest-cli intent screen <条件>` |
| 报告呈现 | `invest-cli intent present <html>` |
| 资讯 / 舆情 / 宏观背景 | `invest-cli info <查询词>`（走 argo，省配额） |

高级/调试：直接透传数据源 `invest-cli wind/yingmi/ttfund ...`（默认不鼓励）。

---

## 已归档路由（2026-06-07 合并）

| 原独立 Skill | 现归入 | 查看方式 |
|-------------|--------|---------|
| hk-a-share-deep-analysis | invest-stock | invest stock |
| stock-analysis-guide / stock-analysis-cn | invest-stock | invest stock |
| fund-investment-guide / fund-manager-selector / invest-fund-read | invest-fund | invest fund |
| macro-liquidity / market-analysis-radar | invest-macro | invest macro |
| bond-market / gold-analyzer | invest-bond / invest-commodity（黄金十维度） | invest bond / invest commodity |
| eastmoney-financial-data/search/select-stock | eastmoney 子命令 | eastmoney query/search-news/screen |
| smart-investor-final | invest 入口 | invest |
| investment-data-adapter | invest-cli | invest cli |

---

*invest v1.3 | 纯路由 + 统一数据层 | 股基债商+债券+宏观市场+配置+圆桌+机构深度*
