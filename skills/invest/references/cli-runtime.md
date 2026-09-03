# CLI Runtime（数据层统一约定）

一行原则：**PATH 优先，skill 树兜底；禁止写死个人家目录。** 取数口径以 invest 入口「场景 → invest-cli 取数映射」表为真源，本文件只管运行时解析与外部分工。

## 解析顺序

```bash
# 1) 用户覆盖
# 2) PATH 上的同名命令（真实运行态，优先 invest-cli）
# 3) 相邻 skill 树 bin/（打包快照）
# 4) 常见 skills 根下的探测
command -v invest-cli
# invest-cli 兜底：
#   $INVEST_CLI | $INVEST_CLI_ROOT/scripts/invest_cli.py
#   | sibling invest-cli/scripts/invest_cli.py
#   | $HOME/.agents|/.claude|/.grok|/.codex/skills/invest-cli/...
```

## 数据层外部依赖（仅两类）

invest-cli 是唯一数据入口。它对外部技能的依赖只允许两类的其中一种：

| 外部依赖 | 用途 | 例 |
|---------|------|-----|
| **登录态源** | 需用户凭据/登录的官方源（缺登录态时按优先级降级，整单回退） | hithink（同花顺 key/凭据）、wind（Wind key）、yingmi（盈米登录）、ttskill（天天基金登录）、eastmoney（东财 key） |
| **搜索技能** | 无结构化 API 的资讯/舆情/宏观补充检索 | argo（`info` / `intent macro`） |

不外接任何「分析技能」当取数依赖。ttfund / fundfof / fundscreen 已退役（2026-09-03，能力并入官方 ttskill 业务包与 invest-cli `intent`），不作为活性依赖。

## 数据源分工（单一优先级，消灭双入口掷骰）

| 意图 | 命令 | 运行时链（依本机可用性） |
|------|------|------------------------|
| 个股三关快照（A股） | `invest-cli stock` | hithink > eastmoney |
| 个股三关快照（港股） | `invest-cli stock` | eastmoney（当前机器缺 key 则空链） |
| 美股快照 | `invest-cli us` | yfinance > bitget |
| 基金三关快照 | `invest-cli fund` | hithink > [ttskill 深取] > eastmoney |
| 基金诊断雷达 | `intent deep fund` | yingmi GetFundDiagnosis |
| 债券 | `intent deep bond` | wind bond_data |
| 黄金/商品 | `intent deep commodity` | ttskill 官方 TTFUND_GOLD_INFO |
| 宏观/市场 | `intent macro` | argo |
| 组合/配置 | `intent portfolio` / `intent plan` | yingmi |
| 自然语言选股 | `intent screen` / `invest-cli screen` | eastmoney（当前机器缺 key 则空链） |
| 资讯/舆情检索 | `invest-cli info` | argo |
| HTML 报告摘要 | `intent present` | 本地提取 |

> 链以 `invest-cli datasources` 运行时探测为准；空链 = 该场景当前机器无可用源，属外部登录态缺口，不是代码缺陷。

## 数据源可用性（运行时，2026-09 实测）

| 源 | 状态 | 依赖 |
|----|------|------|
| hithink 同花顺 | 可用 | `HITHINK_FINANCE_API_KEY` 或用户级 credentials |
| eastmoney 东财 | 缺 key（当前空链：港股/选股） | `EASTMONEY_APIKEY` |
| yfinance | 可用 | 已装 `yfinance` |
| bitget | 可用 | 免 key 公开 API |
| wind | 可用 | wind-mcp-skill 目录 + key |
| yingmi | 可用 | `yingmi-skill-cli init` 完成 |
| ttskill | 可用 | 已登录 |
| argo | 可用 | argo skill 目录含 `scripts/search.py` |

## 模糊词默认

| 用户说 | 默认 |
|--------|------|
| 「诊断一下 005827」（无买/不买） | `invest-cli intent deep fund`（盈米诊断雷达） |
| 「这只基金怎么样 / 值不值得」 | invest-fund（判断） |
| 「查某标的行情/数据」 | `invest-cli stock/fund/us`（按标的类型） |
| 「市场环境/宏观」 | `intent macro`（argo） |

## 未知环境兼容

1. 先 `command -v invest-cli`；失败再读 skill 树 `bin/`。
2. CLI 缺失：降级 web_search / 用户粘贴数据，**不得假装已取数**。
3. 名称→代码：以各 CLI 自己的 resolve 为准；经理人名**不得**绑死单只产品代码。
4. 口径不一致不合并；输出必须标注数据来源。