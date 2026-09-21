---
name: invest-cli
description: |
  投资分析 CLI — 数据获取 + 分析框架一体化，dual-mode 运行。

  触发：「/cli」「/投资cli」「invest cli」「终端分析」「命令行分析」
  或：「用cli分析」「终端查一下」「命令行看看」

  命令入口：`invest-cli stock 600519`（PATH 无 invest-cli 时兜底：`"$HOME/.local/bin/invest-cli" stock 600519`——wrapper 优先用 skill 自带 venv，含 yfinance）
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

**入口约定**：优先 `invest-cli` 命令（PATH，wrapper 在 `~/.local/bin/`）；PATH 无该命令时用 `"$HOME/.local/bin/invest-cli"` 兜底。不要绕过 wrapper 直接 `python3` 裸跑系统解释器——那样会丢掉 venv 里的 yfinance，美股路径静默降级到 Bitget rToken 报价。

## 路由逻辑

1. 识别标的类型（股票/基金/美股/选股）
2. 调用对应子命令，`--json` 获取结构化数据
3. 将 JSON 数据传给 invest 系列分析框架
4. 输出完整分析报告

## 子命令

### stock — A股/港股分析

```bash
invest-cli stock <代码/名称> [--json]
```

- 数据源：同花顺金融数据服务优先（A 股官方 REST）；失败或港股回退东方财富
- 获取：实时行情 + PE/PB/PS/PCF + 近 5 年年报 + ROE/毛利率/现金流（港股仍走东财）
- 分析框架：对标 invest-stock 三关审查（懂不懂 / 好不好 / 贵不贵）
- 内置名称映射：茅台→600519、五粮液→000858、宁德时代→300750 等

### fund — 基金分析

```bash
invest-cli fund <代码/名称> [--json]
```

- 数据源：同花顺金融数据服务优先；失败回退东方财富（intent deep fund 仍先盈米）
- 获取：净值/业绩/回撤/费率/经理/十大重仓
- 分析框架：对标 invest-fund 三关审查
- 内置名称映射：易方达蓝筹→110011、中欧医疗→003096 等

### us — 美股分析

```bash
invest-cli us <代码> [--json]
```

- 数据源：yfinance 优先（估值/财务/评级）；缺失或失败时回退 Bitget rToken 报价（USDT，非官方价）
- 获取：全量快照（yfinance）或行情-only（bitget，`quote_type=rtoken`）
- 分析框架：对标 invest-stock 美股四维度（ROE持续性/负债安全/FCF质量/经济护城河）；Bitget 回退仅有报价，无财务

### sec — 美股财报原文（SEC EDGAR，免费官方源）

```bash
invest-cli sec <代码> [--forms 10-K,10-Q,8-K] [--filings 5] [--json]
```

- 数据源：SEC EDGAR 官方 XBRL API（companyfacts + submissions），免费无 key
- 身份声明：SEC 要求 UA 含邮箱（www.sec.gov 强制，否则 403）；默认用占位邮箱通过校验，建议设置 `SEC_EDGAR_USER_AGENT="你的名字 你的邮箱"` 声明真实联系方式
- 获取：最近年报（10-K，form=10-K + fp=FY）关键指标——营收/净利/营业利润/毛利/经营现金流/总资产/股东权益/EPS；附最近申报清单（带原文链接）
- 口径：标签漂移按优先级回退（如 Apple 的 Revenues 停在 2018，自动改用 RevenueFromContractWithCustomerExcludingAssessedTax）；时长型事实限 300~400 天，季度值不进结果
- 定位：与 Wind / yfinance 的结构化数字交叉验证的「原文级」依据；原始 JSON 磁盘缓存 24h（单公司约 3.7MB）
- 不做：外国私人发行人（20-F）、投资公司（N-CSR）不在覆盖内，会明确报错

### screen — 选股（**股票**筛选）

```bash
invest-cli screen <条件> [--json]
```

- 数据源：东方财富**选股** API（stock-screen）——按定义只筛股票
- 支持自然语言条件："市盈率低于10的银行股"、"ROE大于20%的消费股"
- 筛**基金**不要用本命令（基金条件会被服务端当成股票的主营业务关键词，结果不是基金）：
  走 `invest-cli intent screen <条件>`，带「基金/ETF/债基」等词时自动路由到盈米基金搜索

### watchlist — 本地自选股

```bash
invest-cli watchlist add <代码> [--name N] [--type fund|stock]
invest-cli watchlist remove <代码>
invest-cli watchlist list [--with-quote]
```

- 本地存储 `<state_root>/watchlist.json`（默认 `~/.config/invest-cli/`，可用 `INVEST_CLI_STATE_DIR` 覆盖；用户数据不放缓存目录），不依赖任何外部账户登录态
- 行情预览走 route.fetch（A 股/基金快照链），按 `--type` 选 stock 或 fund

### datasources — 数据源探测（统一门闩）

```bash
invest-cli datasources [--json]
```

- 列出所有已登记数据源（配置真源 `data-sources.yaml`）及运行时可用性
- 同时打印默认快照链（yaml × 真方法 × 可用性）；`--json` 含 `_chains`
- 取数走 `stock/fund/us/intent`，由 `sources/route.py` 选源，禁止在分析 skill 里猜源

### wind — 万得 Wind（机构级）

```bash
invest-cli wind <server_type> <tool> --input '<json>' [--json]
```

- 透传 wind-mcp-skill 契约工具（stock_data/fund_data/index_data/...）
- 定位：`WIND_SKILL_DIR` 或 `INVEST_SKILL_ROOTS` 指向 wind skill 目录
- Key：wind skill 自身的 config（`~/.wind-aifinmarket/config`）

### yingmi — 盈米且慢

```bash
invest-cli yingmi <tool> --input '<json>' [--json]
```

- 透传 `yingmi-skill-cli mcp call` 工具（基金/策略/财富/资讯，共 69 个）
- 前置：`yingmi-skill-cli init` 完成
- 已收敛高层入口（优先走，勿重复透传）：GuessFundCode/GetFundDiagnosis/SearchFunds/DiagnoseFundPortfolio/GetAssetAllocationPlan
- 批量/列表类工具（GetPopularFund/Batch*）返回 JSON 数组，适配器已支持（2026-09-03 修复）

### ttskill — 天天基金官方业务包（透传，37 包可达）

```bash
invest-cli ttskill <skill_id> --input '<json>' [--json]
```

- 透传官方 ttskill 业务包（2026-09-03 新增，此前 37 包仅 4 个"声明可达"）
- 常用：`MANAGER_INFO`（经理画像/在管）、`NAV_INFO`（历史净值）、`STOCK_PRICE_QUERY`（实时行情）、`MACRO_DATA`（中美宏观）、`VALUATION_MAP`（指数/行业估值分位）、`INDEX_FUND_SELECTION`、`CONDITION_SELECT`
- 参数以官方包 `examples/*.example.json` 为准；返回为原始结构（各包层级不一，透传不解释）
- fund 深取层内嵌 SEARCH/BASE_INFOS/HOLDING_INFO（走 `fund <code>`，勿手动透传）；黄金走 `intent deep commodity`
- 账户/交易类包（ACCOUNT_*/TRADE_QUERY/CONDITION_ORDER/SIM_TRADE/RATION_PLAN/SUBACCOUNT）为边界外：invest-cli 数据链路不消费，不建高层入口
- 全套 37 包用途与收敛标注：`invest-cli capabilities ttskill`

### capabilities — 能力发现层

```bash
invest-cli capabilities [yingmi|ttskill] [--json]
```

- 取数前先查：官方（盈米 69 工具 / 天天 37 包）有什么、invest-cli 收敛到哪、怎么调——一处可见，根治"不知道有 X 能力"的重复低效
- 空参=数据源总览 + 高层入口速查；`--json` 给 skill 层做路由决策
- 只列清单不取业务数据；拿不准参数先看 `capabilities` 输出里的工具描述

### 天天基金官方（ttskill，fund 源，已封装）

老 ttfund CLI 已退役（2026-09-03）：能力被官方 ttskill 业务包取代。
- fund 默认链为**自带源优先** `hithink > [ttskill 可选深取] > eastmoney`；ttskill 仅在已登录就绪时补充同类分位/机构占比/经理在管等深取字段
- 黄金深取走 `intent deep commodity` → 官方 `TTFUND_GOLD_INFO`
- 分析 skill 不要绕过 invest-cli 直接调官方包：fund 深取走 `fund <code>`，其余包走 `invest-cli ttskill <skill_id>` 透传
- 口径真源 = `invest-fund/references/data-pipeline.md` + `sources/ttskill.py`；差距与收敛进度见 `docs/capability-gap.md`

### intent — 意图层（默认取数入口，收敛接口面）

```bash
invest-cli intent <deep/screen/portfolio/plan/macro/present> <参数> [--json]
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
$ invest-cli stock 600519
============================================================
  贵州茅台（600519）— 行情快照
============================================================

  指标              数值
  ------------------------------
  最新价           1680.00
  涨跌幅             1.23%
  市盈率PE          28.50
  ...

$ invest-cli us AAPL
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
| SEC EDGAR | 免费无 key（可选 `SEC_EDGAR_USER_AGENT` 声明身份） | us 财报原文（10-K XBRL 指标 + 申报清单，`invest-cli sec` 直取，不经快照链） |
| Bitget rToken | 始终可用（公开 API） | us（仅行情/USDT） |
| 万得 Wind | 定位 wind skill + key | stock/fund/index/bond/news/macro |
| 盈米且慢 | `yingmi-skill-cli init` 完成 | fund/strategy/wealth/news |
| 天天基金（官方 ttskill，可选深取） | `ttskill` 已登录且装齐业务包（缺省自动跳过） | fund（同类分位/机构占比/在管列表等深取补充） |
| argo | `argo` skill 目录内含 `scripts/search.py` | news/macro（资讯/舆情/宏观检索；不经快照链，`info`/`intent macro` 直调）。引擎名原样透传给 argo（250+ 个，传错即报错、不静默换源）；清单见 argo `search.py --list-engines` |

能力矩阵与详细配置见 `docs/data-sources.md`。取数与降级：单一场景优先最高优先级源，整单失败才降级，禁止跨源合并字段。

## 环境要求

- `HITHINK_FINANCE_API_KEY` 或 `~/Library/Application Support/hithink-finance/credentials.env`：同花顺官方源（A 股/公募优先）
- `EASTMONEY_APIKEY`：东方财富 API Key（港股、自然语言选股、以及同花顺失败时的回退）
- `yfinance`：Python 包（us 全量快照推荐；缺省可回退 Bitget）
- Python 3.10+
