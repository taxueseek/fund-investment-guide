# CLI Runtime（数据 skill 统一约定）

一行原则：**PATH 优先，skill 树兜底；禁止写死个人家目录。**

## 解析顺序

```bash
# 1) 用户覆盖
# 2) PATH 上的同名命令（真实运行态）
# 3) 相邻 skill 树 bin/（打包快照）
# 4) 常见 skills 根下的探测
command -v ttfund fundfof fundscreen
# invest-cli：
#   $INVEST_CLI | $INVEST_CLI_ROOT/scripts/invest_cli.py
#   | sibling invest-cli/scripts/invest_cli.py
#   | $HOME/.agents|/.claude|/.grok|/.codex/skills/invest-cli/...
```

## 数据 skill 分工（单一优先级，消灭双入口掷骰）

| 意图 | 首选 | 次选 / 禁止 |
|------|------|-------------|
| 查净值、持仓、账户、登录、回测组合 | **ttfund** | 不要用 fundfof 代替账户 |
| 公开排行、夏普/卡玛、热力、ETF 资金、见基 | **fundfof** | fundscreen 仅当 fundfof 不可用且已装 ttfund |
| 已登录天天、要在 ttfund 净值上本地算指标 | **fundscreen** | 非默认筛选入口 |
| A/港/美股结构化快照、东财选股 | **invest-cli** | 需 `EASTMONEY_APIKEY`（美股仅 yfinance） |
| 值不值得买、三关/场景判断 | **invest-*** 框架 | 先取数再套框架，不反客为主 |

## 模糊词默认

| 用户说 | 默认 |
|--------|------|
| 「诊断一下 005827」（无买/不买） | fundfof diagnose（公开指标） |
| 「这只基金怎么样 / 值不值得」 | invest-fund（判断） |
| 「我的持仓 / 净值」 | ttfund |
| 「筛选夏普>1.5」 | fundfof screen/rank |

## 未知环境兼容

1. 先 `command -v <cli>`；失败再读 skill 树 `bin/`。
2. CLI 缺失：降级 web_search / 用户粘贴数据，**不得假装已取数**。
3. 名称→代码：以各 CLI 自己的 resolve 为准；经理人名**不得**绑死单只产品代码。
