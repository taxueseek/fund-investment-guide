---
name: invest-cli
description: |
  投资分析 CLI — 数据获取 + 分析框架一体化，dual-mode 运行。

  触发：「/cli」「/投资cli」「invest cli」「终端分析」「命令行分析」
  或：「用cli分析」「终端查一下」「命令行看看」

  也支持直接运行 CLI 脚本：
  python ~/.agents/skills/invest-cli/scripts/invest_cli.py stock 600519
---

## 完整触发条件（原始 description）

投资分析 CLI — 数据获取 + 分析框架一体化，dual-mode 运行。 触发：「/cli」「/投资cli」「invest cli」「终端分析」「命令行分析」 或：「用cli分析」「终端查一下」「命令行看看」 也支持直接运行 CLI 脚本： python ~/.agents/skills/invest-cli/scripts/invest_cli.py stock 600519


# invest-cli — 投资分析 CLI

## 定位

现有 invest 系列 skill 只定义"怎么想"（分析框架），数据靠 web search。
invest-cli 补充"怎么取"（数据获取），把 CLI 脚本和分析框架串起来。

**dual-mode**：
- Skill 触发 → 调用 CLI 脚本（`--json`）→ 用 invest 系列框架解读 → 输出完整分析报告
- 终端直接运行 → 输出表格快照

## 路由逻辑

1. 识别标的类型（股票/基金/美股/选股）
2. 调用对应子命令，`--json` 获取结构化数据
3. 将 JSON 数据传给 invest 系列分析框架
4. 输出完整分析报告

## 子命令

### stock — A股/港股分析

```bash
python ~/.agents/skills/invest-cli/scripts/invest_cli.py stock <代码/名称> [--json]
```

- 数据源：东方财富 API
- 获取：实时行情 + PE/PB/ROE/毛利率/现金流
- 分析框架：对标 invest-stock 三关审查（懂不懂 / 好不好 / 贵不贵）
- 内置名称映射：茅台→600519、五粮液→000858、宁德时代→300750 等

### fund — 基金分析

```bash
python ~/.agents/skills/invest-cli/scripts/invest_cli.py fund <代码/名称> [--json]
```

- 数据源：东方财富 API
- 获取：净值/业绩/风险指标/费率/经理/十大重仓
- 分析框架：对标 invest-fund 三关审查
- 内置名称映射：易方达蓝筹→006195、中欧医疗→003096 等

### us — 美股分析

```bash
python ~/.agents/skills/invest-cli/scripts/invest_cli.py us <代码> [--json]
```

- 数据源：yfinance（已安装）
- 获取：估值/财务/分析师评级/风险指标
- 分析框架：对标 invest-stock 四维评分模式（ROE持续性/负债安全/FCF质量/经济护城河）

### screen — 选股

```bash
python ~/.agents/skills/invest-cli/scripts/invest_cli.py screen <条件> [--json]
```

- 数据源：东方财富选股 API
- 支持自然语言条件："市盈率低于10的银行股"、"近1年收益>30%的基金"

## Skill 触发后的执行流程

1. **识别标的类型**：根据用户输入关键词判断 stock/fund/us/screen
2. **调用 CLI**：执行对应子命令，`--json` 模式获取数据
3. **解读数据**：
   - stock → 按 invest-stock 三关框架输出分析报告
   - fund → 按 invest-fund 三关框架输出分析报告
   - us → 按 invest-stock 四维评分模式输出分析报告
   - screen → 直接输出选股结果表格
4. **补充分析**：CLI 数据 + invest 框架 = 完整分析报告

## 示例

### Skill 触发示例

用户：「/cli 分析一下茅台」
→ 识别为 stock → 调用 `invest_cli.py stock 600519 --json`
→ 解析 JSON → 按 invest-stock 三关框架输出分析报告

用户：「/cli 帮我看看 006195 这只基金」
→ 识别为 fund → 调用 `invest_cli.py fund 006195 --json`
→ 解析 JSON → 按 invest-fund 三关框架输出分析报告

用户：「/cli 看看 AAPL」
→ 识别为 us → 调用 `invest_cli.py us AAPL --json`
→ 解析 JSON → 按 invest-stock 四维评分模式输出分析报告

### 终端直接运行示例

```bash
$ python ~/.agents/skills/invest-cli/scripts/invest_cli.py stock 600519
============================================================
  贵州茅台（600519）— 行情快照
============================================================

  指标              数值
  ------------------------------
  最新价           1680.00
  涨跌幅             1.23%
  市盈率PE          28.50
  ...

$ python ~/.agents/skills/invest-cli/scripts/invest_cli.py us AAPL
============================================================
  Apple Inc.（AAPL）— 美股快照
============================================================
  ...
```

## 与现有 invest 系列的关系

| 能力 | invest 系列 | invest-cli |
|------|------------|------------|
| 分析框架 | ✅ 完整 | 复用 invest 系列 |
| 数据获取 | ❌ 靠 web search | ✅ CLI 脚本 |
| 终端直接运行 | ❌ | ✅ |
| 触发方式 | 自然语言 | /cli + 自然语言 |

**invest-cli 不替代 invest 系列，是补充**。当用户想用 CLI 或明确说"/cli"时走 invest-cli，否则走原有 invest 系列。

## 环境要求

- `EASTMONEY_APIKEY`：东方财富 API Key（stock/fund/screen 必须）
- `yfinance`：Python 包（us 已安装）
- Python 3.10+
