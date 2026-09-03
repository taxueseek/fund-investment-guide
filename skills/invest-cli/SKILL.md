---
name: invest-cli
description: |
  投资分析 CLI — 数据获取 + 分析框架一体化，dual-mode 运行。

  触发：「/cli」「/投资cli」「invest cli」「终端分析」「命令行分析」
  或：「用cli分析」「终端查一下」「命令行看看」

  命令入口：`invest-cli stock 600519`（PATH 无 invest-cli 时兜底：`python3 "$HOME/.agents/skills/invest-cli/scripts/invest_cli.py" stock 600519`）
---

## 完整触发条件（原始 description）

投资分析 CLI — 数据获取 + 分析框架一体化，dual-mode 运行。 触发：「/cli」「/投资cli」「invest cli」「终端分析」「命令行分析」 或：「用cli分析」「终端查一下」「命令行看看」 命令入口：invest-cli（兜底脚本见下）


# invest-cli — 投资分析 CLI

## 定位

现有 invest 系列 skill 只定义"怎么想"（分析框架），数据靠 web search。
invest-cli 补充"怎么取"（数据获取），把 CLI 脚本和分析框架串起来。

**dual-mode**：
- Skill 触发 → 调用 CLI 脚本（`--json`）→ 用 invest 系列框架解读 → 输出完整分析报告
- 终端直接运行 → 输出表格快照

**入口约定**：优先 `invest-cli` 命令（PATH，wrapper 在 `~/.local/bin/`）；PATH 无该命令时用 `python3 "$HOME/.agents/skills/invest-cli/scripts/invest_cli.py"` 兜底。

## 路由逻辑

1. 识别标的类型（股票/基金/美股/选股）
2. 调用对应子命令，`--json` 获取结构化数据
3. 将 JSON 数据传给 invest 系列分析框架
4. 输出完整分析报告

## 子命令

### stock — A股/港股分析

```bash
python3 ~/.agents/skills/invest-cli/scripts/invest_cli.py stock <代码/名称> [--json]
```

- 数据源：同花顺金融数据服务优先（A 股官方 REST）；失败或港股回退东方财富
- 获取：实时行情 + PE/PB/PS/PCF + 近 5 年年报 + ROE/毛利率/现金流（港股仍走东财）
- 分析框架：对标 invest-stock 三关审查（懂不懂 / 好不好 / 贵不贵）
- 内置名称映射：茅台→600519、五粮液→000858、宁德时代→300750 等

### fund — 基金分析

```bash
python3 ~/.agents/skills/invest-cli/scripts/invest_cli.py fund <代码/名称> [--json]
```

- 数据源：同花顺金融数据服务优先；失败回退东方财富（intent deep fund 仍先盈米）
- 获取：净值/业绩/回撤/费率/经理/十大重仓
- 分析框架：对标 invest-fund 三关审查
- 内置名称映射：易方达蓝筹→110011、中欧医疗→003096 等

### us — 美股分析

```bash
python3 ~/.agents/skills/invest-cli/scripts/invest_cli.py us <代码> [--json]
```

- 数据源：yfinance 优先（估值/财务/评级）；缺失或失败时回退 Bitget rToken 报价（USDT，非官方价）
- 获取：全量快照（yfinance）或行情-only（bitget，`quote_type=rtoken`）
- 分析框架：对标 invest-stock 美股四维度（ROE持续性/负债安全/FCF质量/经济护城河）；Bitget 回退仅有报价，无财务
### screen — 选股

```bash
python3 ~/.agents/skills/invest-cli/scripts/invest_cli.py screen <条件> [--json]
```

- 数据源：东方财富选股 API
- 支持自然语言条件："市盈率低于10的银行股"、"近1年收益>30%的基金"

### datasources — 数据源探测（统一门闩）

```bash
python3 ~/.agents/skills/invest-cli/scripts/invest_cli.py datasources [--json]
```

- 列出所有已登记数据源（配置真源 `data-sources.yaml`）及运行时可用性
- 同时打印默认快照链（yaml × 真方法 × 可用性）；`--json` 含 `_chains`
- 取数走 `stock/fund/us/intent`，由 `sources/route.py` 选源，禁止在分析 skill 里猜源

### wind — 万得 Wind（机构级）

```bash
python3 ~/.agents/skills/invest-cli/scripts/invest_cli.py wind <server_type> <tool> --input '<json>' [--json]
```

- 透传 wind-mcp-skill 契约工具（stock_data/fund_data/index_data/...）
- 定位：`WIND_SKILL_DIR` 或 `INVEST_SKILL_ROOTS` 指向 wind skill 目录
- Key：wind skill 自身的 config（`~/.wind-aifinmarket/config`）

### yingmi — 盈米且慢

```bash
python3 ~/.agents/skills/invest-cli/scripts/invest_cli.py yingmi <tool> --input '<json>' [--json]
```

- 透传 `yingmi-skill-cli mcp call` 工具（基金/策略/财富/资讯）
- 前置：`yingmi-skill-cli init` 完成

### 天天基金官方（ttskill，fund 源，已封装）

老 ttfund CLI 已退役（2026-09-03）：能力被官方 ttskill 业务包取代。
- fund 默认链为**自带源优先** `hithink > [ttskill 可选深取] > eastmoney`；ttskill 仅在已登录就绪时补充同类分位/机构占比/经理在管等深取字段
- 黄金深取走 `intent deep commodity` → 官方 `TTFUND_GOLD_INFO`
- Agent 不要直接调 ttskill 的 37 个业务包；口径真源 = `references/data-pipeline.md`（invest-fund）+ `sources/ttskill.py`

### intent — 意图层（默认取数入口，收敛接口面）

```bash
python3 ~/.agents/skills/invest-cli/scripts/invest_cli.py intent <deep/screen/portfolio/plan/macro/present> <参数> [--json]
```

- 把盈米 69 个 MCP 工具 + Wind 7 类收敛为 6 个语义入口，内部按场景 + 标的类型路由到权威源
- 接口面小、能力面全；`--json` 输出统一信封（source/ok/data/error）
- 推荐作为分析 skill 的首选取数方式；wind/yingmi 透传仅作高级/调试

## Skill 触发后的执行流程

1. **识别标的类型**：根据用户输入关键词判断 stock/fund/us/screen
2. **调用 CLI**：执行对应子命令，`--json` 模式获取数据
3. **解读数据**：
   - stock → 按 invest-stock 三关框架输出分析报告
   - fund → 按 invest-fund 三关框架输出分析报告
   - us → 按 invest-stock 美股四维度框架输出分析报告
   - screen → 直接输出选股结果表格
4. **补充分析**：CLI 数据 + invest 框架 = 完整分析报告

## 示例

### Skill 触发示例

用户：「/cli 分析一下茅台」
→ 识别为 stock → 调用 `invest_cli.py stock 600519 --json`
→ 解析 JSON → 按 invest-stock 三关框架输出分析报告

用户：「/cli 帮我看看 110011 这只基金」
→ 识别为 fund → 调用 `invest_cli.py fund 110011 --json`
→ 解析 JSON → 按 invest-fund 三关框架输出分析报告

用户：「/cli 看看 AAPL」
→ 识别为 us → 调用 `invest_cli.py us AAPL --json`
→ 解析 JSON → 按 invest-stock 美股四维度框架输出分析报告

### 终端直接运行示例

```bash
$ python3 ~/.agents/skills/invest-cli/scripts/invest_cli.py stock 600519
============================================================
  贵州茅台（600519）— 行情快照
============================================================

  指标              数值
  ------------------------------
  最新价           1680.00
  涨跌幅             1.23%
  市盈率PE          28.50
  ...

$ python3 ~/.agents/skills/invest-cli/scripts/invest_cli.py us AAPL
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

## 数据源接入（统一门闩）

数据源声明真源为 `data-sources.yaml`，可用性由 `invest-cli datasources` 运行时探测。各源启用条件：

| 数据源 | 启用条件 | 覆盖 |
| --- | --- | --- |
| 同花顺金融数据服务 | `HITHINK_FINANCE_API_KEY` 或用户级 `credentials.env` | stock/fund（A 股与公募，不含港股/美股/自然语言选股） |
| 东方财富 | `EASTMONEY_APIKEY` | stock/fund/screen |
| yfinance | `pip3 install yfinance` | us（行情+财务） |
| Bitget rToken | 始终可用（公开 API） | us（仅行情/USDT） |
| 万得 Wind | 定位 wind skill + key | stock/fund/index/bond/news/macro |
| 盈米且慢 | `yingmi-skill-cli init` 完成 | fund/strategy/wealth/news |
| 天天基金（官方 ttskill，可选深取） | `ttskill` 已登录且装齐业务包（缺省自动跳过） | fund（同类分位/机构占比/在管列表等深取补充） |
| argo | `argo` skill 目录内含 `scripts/search.py` | news/macro（资讯/舆情/宏观检索；不经快照链，`info`/`intent macro` 直调） |

能力矩阵与详细配置见 `docs/data-sources.md`。取数与降级：单一场景优先最高优先级源，整单失败才降级，禁止跨源合并字段。

## 环境要求

- `HITHINK_FINANCE_API_KEY` 或 `~/Library/Application Support/hithink-finance/credentials.env`：同花顺官方源（A 股/公募优先）
- `EASTMONEY_APIKEY`：东方财富 API Key（港股、自然语言选股、以及同花顺失败时的回退）
- `yfinance`：Python 包（us 全量快照推荐；缺省可回退 Bitget）
- Python 3.10+
