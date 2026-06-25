# Invest Series: Investment Analysis Guide

Buy funds like hiring a steward, buy stocks like partnering in business. Don't trust people you don't understand, who are unreliable, or who charge too much.

This tool helps you with three things: **see what you're investing in, judge whether it's worth it, determine if the price is right**.

---

## Quick Start

```bash
npx skills add taxueseek/fund-investment-guide
```

After installation, just ask Claude:
- "How is this fund?"
- "Analyze Moutai"
- "Can I buy gold?"
- "Let the masters take a look at this stock"

The system automatically identifies what you want to analyze and routes to the corresponding analysis flow.

> **Note**: This tool only helps you think clearly. It's not investment advice and doesn't guarantee profits. After using it to analyze, buying or selling is entirely your own decision.

---

## What This Is

Not a data query tool — it's a **judgment framework**.

The biggest pitfall in investing isn't lack of information, it's **not knowing what to look at**. This tool tells you: these three things are all you need to check.

```
User Question
    │
    ▼
┌─────────────┐
│  invest     │  ← Identifies what you want to analyze
│  Entry      │
└──────┬──────┘
       │
       ├──────────┬──────────┬──────────┬──────────┬──────────┐
       ▼          ▼          ▼          ▼          ▼          ▼
   ┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐
   │ Stocks│  │ Funds │  │Convert│  │Commod │  │ REITs │  │Asset  │
   │3-Gate │  │Scene  │  │3-Gate │  │3-Gate │  │3-Gate │  │Alloc  │
   │+Deep  │  │Route  │  │Review │  │Review │  │Review │  │       │
   └───┬───┘  └───┬───┘  └───┬───┘  └───┬───┘  └───┬───┘  └───┬───┘
       │          │          │          │          │          │
       └──────────┴────┬─────┴──────────┴──────────┴──────────┘
                       ▼
               ┌───────────────┐
               │  3-Gate Review│
               │               │
               │ 1. Understand?│  ← Capability circle / Strategy
               │ 2. Good?      │  ← Moat / Sustainability
               │ 3. Cheap?     │  ← Margin of safety / Valuation
               └───────────────┘
```

---

## What You Can Analyze

| You want to analyze | Routes to | Core Question | Applicable Markets |
|:--------------------|:----------|:--------------|:-------------------|
| A specific stock | invest-stock | Understand the business? Moat? Right price? | A-shares, HK stocks, US stocks |
| A specific fund | invest-fund | Understand the strategy? Can beat benchmark? Cost reasonable? | Active funds, ETFs, QDII |
| Convertible bonds | invest-convertible | Bond floor sufficient? Premium reasonable? | A-share convertible bonds |
| Gold/Oil | invest-commodity | Logic clear? Position reasonable? | Commodities |
| REITs | invest-reit | Asset quality? Distribution sustainable? | Domestic and international REITs |
| Overall allocation | invest-allocation | Stock-bond ratio reasonable? Rebalanced? | Cross-asset portfolio |
| Not sure? | invest-discuss | Let multiple investment minds examine together | Any target |
| /cli analysis | invest-cli | Terminal data fetch + analysis framework | A/HK/US stocks, funds |

---

## What is the 3-Gate Review

What's the biggest fear in investing? **Looking at what you shouldn't, missing what you should**.

These three gates break complex investment decisions into three must-answer questions:

### Gate 1: Do You Understand?

If you don't understand it, you can't hold it through ups and downs.

- Stocks: How does this company make money? Why do customers choose it?
- Funds: What does it invest in? What's the strategy? What's the benchmark?
- Convertible bonds: Do you understand the terms? Put, call, reset — what do they mean?

**Fail this gate: abandon directly.** Don't touch what you don't understand.

### Gate 2: Is It Good?

Only good things can sustain returns.

- Stocks: Pricing power? ROE consistently >12%? Good cash flow?
- Funds: Beats benchmark long-term? Manager stable? Risk-adjusted returns good?
- Commodities/REITs: Underlying asset quality? Distribution/earnings sustainable?

**Fail this gate: it's a mediocre target, not worth your time.**

### Gate 3: Is It Cheap?

Even good things hurt if you buy expensive.

- PE/PB at what historical percentile?
- If it drops 30%, can you handle it?
- Is there margin of safety entering now?

**Fail this gate: not don't buy — wait for a better time.**

---

## v2.0 Feature Highlights

### Unified Stock Entry

Previously A-shares, HK stocks, and US stocks used separate skills. Now unified into `invest-stock`:

| Capability | Description |
|:-----------|:------------|
| 3-Gate Review | Default mode, A-shares/HK stocks |
| 4-Dimension Score | Auto-switches for US stocks, ROE/Debt/FCF/Moat → A-D rating |
| Institutional Deep | Say "deep analysis" to enter, DCF + comparable company + IC Memo |
| HK-A Enhancement | Auto-adds policy sensitivity, AH premium, north/south flow for A/HK stocks |

### Fund Scene Routing

No longer one-size-fits-all. Auto-selects path based on your question:

| Scene | Trigger | Core Judgment Axis |
|:------|:--------|:-------------------|
| Same manager, multiple funds | "Which of Zhang Kun's funds to pick" | Pick the one most like the manager (longest tenure / right scale / high institutional share) |
| Cross-fund comparison | "Which is better, Fund A or B" | Multi-dimensional comparison scoring |
| Industry theme | "New energy fund" | Manager-industry fit > industry beta |
| New fund | "Is this new fund worth buying" | Manager inference + company DNA |
| ETF | "CSI 300 ETF" | Expense ratio + tracking error + liquidity |
| Standard checkup | "How is this fund" | Full 3-gate review |

### Masters Discussion

Four investment minds examine the same target simultaneously, exposing blind spots from any single perspective:

| Perspective | Core Question |
|:------------|:--------------|
| Business | Understand this business? Has a moat? |
| Trend | How much optimism is priced in? Any catalyst? |
| Allocation | What position size? Can handle how much drawdown? |
| Contrarian | Three most likely scenarios to lose money? |

Supports two depth levels: Quick Scan (default) and Deep Interrogation (pre-position sizing).

### Investment Analysis CLI

Terminal data fetch + analysis framework integrated:

```bash
python invest_cli.py stock 600519      # A/HK stock real-time quotes + valuation
python invest_cli.py fund 006195      # Fund NAV / performance / fees / top holdings
python invest_cli.py us AAPL         # US stock valuation / financials / ratings
python invest_cli.py screen "Bank stocks with PE below 10"  # Stock screening
```

---

## How It Differs from Ordinary Analysis

| Ordinary Approach | This Tool |
|:------------------|:----------|
| Gives you data, you figure it out | Tells you what to look at and what not to |
| Predicts tomorrow's move | Doesn't predict, only assesses "worth holding?" |
| Complex scoring systems | Simple pass / fail / wait |
| Manually updated year data | Auto-calculates which report to look at |
| Only looks at returns | Looks at risk-adjusted returns (Sharpe, Calmar) |
| Single product analysis | Supports asset allocation perspective |

---

## Design Philosophy

### 1. Simplicity

Investing doesn't need complex models. Buffett looks at three things: understand it, is it good, is it cheap. This tool extends that logic to all asset types.

### 2. No Decision-Making for You

The tool only provides a judgment framework. Decision power is entirely yours. It doesn't tell you "buy" or "sell" — only "did you pass this gate?"

### 3. Dynamic Time

No manual year updates. Input today's date, auto-calculates whether to look at N or N-1 year reports, and data freshness.

### 4. Master Perspective

When unsure, start the discussion round. Let business, trend, allocation, and contrarian perspectives examine the same target, revealing blind spots you can't see alone.

---

## Usage Examples

### Analyzing a Stock

```
You: Analyze Tencent 00700

System: Analyzing Tencent (00700), entering invest-stock.

3-Gate Review Results:

| Gate | Result | Key Findings |
|------|--------|--------------|
| Understand | Pass | Gaming + advertising + investments, three segments clear |
| Good | Pass | Deep moat, ROE consistently >15%, strong cash flow |
| Cheap | Wait | PE at 70th historical percentile, insufficient margin of safety |

Overall: Wait for valuation to回落 to PE<25 before considering.
```

### Analyzing a Fund

```
You: How is Zhang Kun's fund?

System: Analyzing Zhang Kun's fund, entering invest-fund.

Key Findings:
- Flagship fund managed for 5+ years, through bull and bear cycles
- Multiple funds with >80% holdings overlap — pick the lowest expense ratio
- Current scale >10B RMB, flexibility limited, alpha may decline

Recommendation: If you're a Zhang Kun fan, pick his longest-tenured flagship.
```

### Asset Allocation Review

```
You: Is my asset allocation reasonable?

System: Entering invest-allocation.

Strategic allocation suggestion (based on 20% max drawdown, 5+ year horizon):
- Stocks: 60%
- Bonds: 30%
- Commodities: 10%

Rebalancing rules:
- Check quarterly
- Trigger when any asset deviates ±5% from target

Current deviation: Stocks over-allocated by 15%, suggest reducing stocks or adding bonds.
```

### Investment Roundtable

```
You: Let the masters take a look at Moutai

System: Starting masters discussion, four perspectives scanning in parallel.

Business: Moutai is an ideal business, rare brand moat, extreme pricing power...
Trend: Current price contains too much optimism...
Allocation: If position >10%, volatility risk needs attention...
Contrarian: Most likely loss scenarios are...

Consensus: Top-tier business model, but current price lacks margin of safety.
```

---

## Before You Use This

This tool is like a dictionary — helps you recognize characters, but doesn't write essays for you. Specifically:

**First, you bear your own gains and losses.** This tool won't tell you which stock to buy or which fund to sell, and doesn't guarantee you'll make money. After using it to analyze, whether to buy and how much is entirely your decision. You bear all profits and losses.

**Second, information is limited.** This tool tries to use the latest public data, but data may be delayed or incorrect. It gives you reference, not definitive answers.

**Third, it cannot replace professional advice.** If you have large investment needs, consult a licensed investment advisor rather than relying on an AI tool.

**One sentence: The tool only helps you think clearly. The decision is yours. The risk is yours.**

---

## Project Structure

```
skills/
├── invest/                    # Entry: auto-identifies target type
├── invest-stock/              # Stock analysis (3-Gate/4-Dimension/Institutional Deep/HK-A Enhancement)
├── invest-fund/               # Fund analysis (Scene routing A/B/C/E/F/G)
├── invest-convertible/        # Convertible bond analysis
├── invest-commodity/          # Commodity analysis
├── invest-reit/               # REITs analysis
├── invest-allocation/         # Asset allocation
├── invest-discuss/            # Masters discussion (multi-perspective validation)
└── invest-cli/                # Investment CLI (data fetch + analysis framework)
```

---

## Version History

| Version | Date | Changes |
|:--------|:-----|:--------|
| v2.0 | 2026-06 | Unified framework upgrade: invest-stock merged former invest-hk-a/invest-us/invest-institutional, invest-fund added scene routing, new invest-discuss/invest-cli added, removed invest-report/invest-fund-manager/invest-upgrade/zaoren-invest-roundtable |
| v1.0 | 2026-04 | Initial release, unified 3-gate review framework, covering stocks/bonds/commodities/allocation/roundtable |

---

If this project is helpful to you, feel free to give it a Star.

---

* * *

## 中文版

# Invest 系列：投资分析指南

买基金像请管家，买股票像合伙做生意。不懂的人、不靠谱的人、要价太高的人，都不能托付。

这个工具帮你三件事：**看清投的是什么，判断值不值得投，确定价格合不合适**。

---

## 快速开始，输入下列指令，即可安装。

```bash
npx skills add taxueseek/fund-investment-guide
```

安装后直接问 Claude：
- "这只基金怎么样？"
- "分析一下茅台"
- "黄金能买吗？"
- "让大师们看看这只股"

系统会自动识别你要分析什么，进入对应的分析流程。

> **注意**：这个工具只是帮你理清思路，不是投资建议，也不保证赚钱。用它分析后，买不买都是你自己的决定。

---

## 这到底是什么

不是数据查询工具，是一套**判断框架**。

投资最大的坑，不是信息不够，是**不知道该看什么**。这个工具告诉你：看这三样就够了。

```
用户提问
    │
    ▼
┌─────────────┐
│  invest     │  ← 识别你要分析什么
│  主入口     │
└──────┬──────┘
       │
       ├──────────┬──────────┬──────────┬──────────┬──────────┐
       ▼          ▼          ▼          ▼          ▼          ▼
   ┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐
   │ 股票  │  │ 基金  │  │可转债 │  │商品   │  │REITs  │  │资产   │
   │三关   │  │场景   │  │三关   │  │三关   │  │三关   │  │配置   │
   │+深度  │  │路由   │  │审查   │  │审查   │  │审查   │  │       │
   └───┬───┘  └───┬───┘  └───┬───┘  └───┬───┘  └───┬───┘  └───┬───┘
       │          │          │          │          │          │
       └──────────┴────┬─────┴──────────┴──────────┴──────────┘
                       ▼
               ┌───────────────┐
               │  三关审查     │
               │               │
               │ 1. 懂不懂？   │  ← 能力圈/策略理解
               │ 2. 好不好？   │  ← 护城河/持续性
               │ 3. 贵不贵？   │  ← 安全边际/估值
               └───────────────┘
```

---

## 能分析什么

| 你要分析 | 路由到 | 核心问题 | 适用市场 |
|:--------|:-------|:---------|:---------|
| 某只股票 | invest-stock | 懂生意吗？有护城河吗？价格合适吗？ | A股、港股、美股 |
| 某只基金 | invest-fund | 懂策略吗？能跑赢吗？成本合理吗？ | 主动基金、ETF、QDII |
| 可转债 | invest-convertible | 债底够吗？溢价合理吗？ | A股可转债 |
| 黄金/原油 | invest-commodity | 逻辑清晰吗？位置合理吗？ | 大宗商品 |
| REITs | invest-reit | 资产质量如何？分派可持续吗？ | 国内外REITs |
| 整体配置 | invest-allocation | 股债比例合理吗？再平衡了吗？ | 跨资产组合 |
| 拿不准？ | invest-discuss | 让多种投资思维同时审视 | 任何标的 |
| /cli 分析 | invest-cli | 终端数据获取 + 分析框架 | A股/港股/美股/基金 |

---

## 三关审查是什么

投资分析最怕什么？**该看的没看，不该看的看了太多**。

这三关把复杂的投资决策，拆成三个必答题：

### 第一关：懂不懂

不懂的东西，涨跌你都拿不住。

- 股票：这家公司怎么赚钱？客户为什么选它？
- 基金：投的是什么？策略是什么？基准是什么？
- 可转债：条款看明白了吗？下修、回售、强赎什么意思？

**这一关掉链子，直接放弃。** 不懂的不碰。

### 第二关：好不好

好东西才能持续赚钱。

- 股票：有定价权吗？ROE能持续>12%吗？现金流好吗？
- 基金：长期跑赢基准吗？经理稳定吗？风险调整后收益如何？
- 商品/REITs：底层资产质量如何？分派/收益可持续吗？

**这一关掉链子，说明是平庸标的，不值得花时间。**

### 第三关：贵不贵

再好的东西，买贵了也难受。

- PE/PB在历史什么分位？
- 如果跌30%，能承受吗？
- 现在入场，安全边际够吗？

**这一关掉链子，不是不买，是等更好的时机。**

---

## v2.0 功能亮点

### 个股分析统一入口

原来 A股、港股、美股分别用不同 skill，现在统一为 `invest-stock`：

| 能力 | 说明 |
|:-----|:-----|
| 三关审查 | 默认模式，A股/港股通用 |
| 四维评分 | 美股自动切换，ROE/负债/FCF/护城河 → A-D评级 |
| 机构深度 | 说"深度分析"进入，DCF估值+同行比较+IC Memo |
| 港A增强 | A股/港股自动附加政策敏感度、AH溢价、南北资金流检查 |

### 基金分析场景路由

不再一套流程走到底，根据你的问题自动选路径：

| 场景 | 触发 | 核心判断轴 |
|:-----|:-----|:-----------|
| 同经理多选一 | "张坤的几只基金选哪个" | 选最像经理本人的那只（管理时间最长/规模适中/机构占比高） |
| 跨基金横向对比 | "A基金和B基金哪个好" | 多维度对比打分 |
| 行业主题 | "新能源基金怎么样" | 经理-行业匹配度 > 行业β |
| 次新基金 | "这只新基金能买吗" | 经理推断 + 公司基因 |
| ETF | "沪深300ETF" | 费率 + 跟踪误差 + 流动性 |
| 标准体检 | "这只基金怎么样" | 完整三关审查 |

### 大师会诊

四种投资思维同时审视一个标的，暴露单一视角的盲区：

| 视角 | 核心问题 |
|:-----|:---------|
| 生意视角 | 懂这门生意吗？有护城河吗？ |
| 趋势视角 | 价格反映了多少乐观？有催化剂吗？ |
| 配置视角 | 占多少仓位？能承受多大回撤？ |
| 反向视角 | 最可能亏钱的三个场景？ |

支持两档深度：快速扫描（默认）和深度质问（重仓前自检）。

### 投资分析 CLI

终端直接获取数据 + 分析框架一体化：

```bash
python invest_cli.py stock 600519      # A股/港股实时行情+估值
python invest_cli.py fund 006195      # 基金净值/业绩/费率/重仓
python invest_cli.py us AAPL         # 美股估值/财务/评级
python invest_cli.py screen "市盈率低于10的银行股"  # 选股
```

---

## 跟普通分析有什么区别

| 普通做法 | 这个工具 |
|:---------|:---------|
| 给一堆数据，让你自己判断 | 告诉你该看什么，不该看什么 |
| 预测明天涨不涨 | 不预测，只评估"值不值得持有" |
| 复杂的评分体系 | 简单的通过/未通过/观望 |
| 手动更新年份数据 | 自动计算当前该看什么报告 |
| 只看收益率 | 看风险调整后收益（夏普、卡玛比率）|
| 单只产品分析 | 支持资产配置视角 |

---

## 设计理念

### 1. 大道至简

投资不需要复杂的模型。巴菲特看企业就看三点：懂不懂、好不好、便不便宜。这个工具把这个思路扩展到所有资产类型。

### 2. 不替决策

工具只提供分析框架，决策权完全交还给你。不告诉你"买"或"卖"，只告诉你"这一关过了吗"。

### 3. 动态时间

不用手动改年份。输入当前日期，自动算出该看N年报告还是N-1年报告，数据新鲜度是多少。

### 4. 大师视角

拿不准的时候，启动投资圆桌。让生意视角、趋势视角、配置视角、反向视角四种思维同时审视同一个标的，发现你自己看不到的盲区。

---

## 实际使用示例

### 分析一只股票

```
你：分析一下腾讯 00700

系统：分析腾讯(00700)，进入invest-stock。

三关审查结果：

| 关卡 | 结果 | 关键发现 |
|------|------|----------|
| 懂不懂 | 通过 | 游戏+广告+投资，三块业务清晰 |
| 好不好 | 通过 | 护城河深厚，ROE持续>15%，现金流充沛 |
| 贵不贵 | 观望 | PE在历史70%分位，安全边际不足 |

综合判断：等估值回落到PE<25再考虑。
```

### 分析一只基金

```
你：张坤的基金怎么样？

系统：分析张坤的基金，进入invest-fund。

关键发现：
- 代表作管理5年+，穿越牛熊周期
- 重仓股重合度>80%的几只基金，选费率最低的
- 当前规模>100亿，灵活性受限，超额收益可能下降

建议：如果是张坤的粉丝，选他管理时间最长的代表作。
```

### 资产配置检视

```
你：我的资产配置合理吗？

系统：进入invest-allocation。

战略配置建议（基于你能承受20%回撤、投资期限5年+）：
- 股票：60%
- 债券：30%
- 商品：10%

再平衡规则：
- 每季度检查一次
- 某类资产偏离目标±5%时触发再平衡

当前你的组合偏离：股票超配15%，建议减仓股票或增配债券。
```

### 投资圆桌

```
你：让大师们看看茅台

系统：启动大师会诊，四种视角并行扫描。

生意视角：茅台是理想生意，品牌护城河罕见，定价权极强...
趋势视角：当前价格包含太多乐观预期...
配置视角：如果仓位>10%，波动风险需关注...
反向视角：最可能亏钱的场景是...

共识：生意模式顶级，但当前价格安全边际不足。
```

---

## 使用之前，你要知道

这个工具像字典——帮你认字，但不替你写作文。具体来说：

**第一，盈亏自负。** 这个工具不会告诉你买哪只股、卖哪只基金，也不保证你能赚钱。用它分析后，买不买、买多少，都是你自己的决定，赚了亏了都自己承担。

**第二，信息有限。** 这个工具会尽量用最新的公开数据，但数据可能滞后、可能有错。它给你的只是参考，不是标准答案。

**第三，不能替代专业建议。** 如果你有大额投资需求，应该咨询持牌的投资顾问，而不是依赖一个AI工具。

**一句话：工具只是帮你理清思路，决策在你，风险自担。**

---

## 项目结构

```
skills/
├── invest/                    # 主入口：自动识别标的类型
├── invest-stock/              # 个股分析（三关审查/四维评分/机构深度/港A增强）
├── invest-fund/               # 基金分析（场景路由A/B/C/E/F/G）
├── invest-convertible/        # 可转债分析
├── invest-commodity/          # 大宗商品分析
├── invest-reit/               # REITs分析
├── invest-allocation/         # 资产配置
├── invest-discuss/            # 大师会诊（多视角验证）
└── invest-cli/                # 投资分析CLI（数据获取+分析框架）
```

---

## 版本更新记录

| 版本 | 日期 | 变更内容 |
|:-----|:-----|:---------|
| v2.0 | 2026-06 | 统一框架升级：invest-stock合并原invest-hk-a/invest-us/invest-institutional，invest-fund新增场景路由，新增invest-discuss/invest-cli，移除invest-report/invest-fund-manager/invest-upgrade/zaoren-invest-roundtable |
| v1.0 | 2026-04 | 全面重构，统一三关审查框架，覆盖股基债商+配置+圆桌 |

---

如果这个项目对你有帮助，欢迎点个 Star。

---

MIT License © 2026
