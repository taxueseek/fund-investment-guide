# 可选数据源：配置后启用

本仓库首先是一套**投资判断框架**。不配置任何 API 也能使用：靠公开检索、你提供的材料，以及三条免 Key 取数通道，跑三关审查 / 场景路由 / 大师会诊。

配置数据源之后，对应的**结构化取数能力才会启用**；取数与下判断分离，也都不构成投资建议。

---

## 能力总览

| 数据源 | 配置物 | 启用后多出来的能力 | 不配置时 |
|--------|--------|--------------------|----------|
| （无） | — | 框架 + 检索 + 用户材料 + 免 Key 取数（含腾讯行情） | 默认路径 |
| **腾讯行情**（零鉴权） | — | `invest-cli quote` 多标的实时行情、`kline` K 线；美股/港股快照的兜底 | 始终可用 |
| **腾讯微证券 CLI**（可选） | 安装 westock 二进制 | `invest-cli westock` 长尾能力：筹码/龙虎榜/北向/两融/一致预期/ESG/机构评级/产业链/板块估值/转债条款等 40+ 子命令 | 跳过该源 |
| **同花顺金融数据服务** | 环境变量 `HITHINK_FINANCE_API_KEY` | `invest-cli stock` / `fund` 的 A 股与公募主路 | 回退东财 |
| **东方财富** | 环境变量 `EASTMONEY_APIKEY` | A股/港股快照、基金快照、自然语言选股（港股必经） | 该源跳过 |
| **Yahoo（yfinance）** | 安装 Python 包 `yfinance` | `invest-cli us` 美股快照 | 回退腾讯行情，再退 Bitget rToken 报价（仅行情） |
| **SEC EDGAR** | 免费无 Key（可选 `SEC_EDGAR_USER_AGENT` 声明身份） | `invest-cli sec` 美股财报原文（10-K XBRL + 申报清单） | 始终可用 |
| **FRED** | 可选 `FRED_API_KEY` | `invest-cli intent macro` 净流动性三序列（免 Key 走 CSV 回退） | 仍可用（CSV 通道） |
| **argo**（可选） | 安装 [argo](https://github.com/taxueseek/argo) | `invest-cli info` 资讯/舆情、宏观检索兜底 | 跳过该源 |
| **Wind / 盈米 / 官方 ttskill**（可选外部） | 各自官方登录或 Key | 债券行情、基金诊断/组合、基金深取字段 | 跳过该源 |

本公开包**不包含**第三方基金聚合网站 skill，也不提供券商交易或代操作账户。

---

## 0. 零配置也能用：免 Key 通道

装上就能取数的几条路（不需要任何 Key）：

```bash
invest-cli quote 600519,00700,AAPL   # 腾讯行情：多标的实时行情（零鉴权，跨 A股/港股/美股/ETF/可转债）
invest-cli kline 600519 --period day # K 线（腾讯原生快路径，年线按自然年聚合）
invest-cli sec AAPL          # 美股财报原文（SEC EDGAR 官方 XBRL）
invest-cli us AAPL           # 美股快照（需先安装 yfinance，见下）
invest-cli intent macro      # 宏观净流动性（FRED 免 Key CSV 通道）
```

先自检当前机器能打到谁：

```bash
invest-cli datasources        # 各源可用性 + 默认快照链（排查「为什么没数据」时跑）
invest-cli capabilities       # 外部源能力清单与收敛状态
```

`datasources` 只用于诊断，**不要**作为每次取数的前置——`stock` / `fund` 内部已按可用性自动选源与回退。

### 腾讯行情（零鉴权，多市场）

腾讯行情是**免 Key** 的原生行情内核，一次请求可带任意多个标的，跨 A 股 / 港股 / 美股 / ETF / 可转债：

```bash
invest-cli quote 600519,00700,AAPL   # 纯行情：实测三市场一次 186ms，6 标的混合 189ms
invest-cli kline 600519 --period day # K 线（年线按自然年聚合，未知周期会明确报错而非静默降级）
```

- **定位**：只回答「现在多少钱、涨跌多少、这几只对比一下」。问基本面请用 `stock` / `fund` / `us`（含 ROE / 净利润等，冷取数 0.5s 起）。
- **不进 `stock` / `fund` 主位**：腾讯只有行情、没有基本面（净利润 / ROE / EPS / 资产负债率一个都没有），进主位会把 A 股快照从 13 项基本面退化成纯行情。链序为 `us = yfinance > 腾讯 > bitget`、`stock = 同花顺 > 东财 > yfinance > 腾讯`，`fund` / `screen` 不含腾讯。
- **号码重叠会明说**：`quote 000001` 会同时说明「也是沪市指数 sh000001」；`stock` 遇到基金代码会直接拒绝并指向 `fund`。
- 安装腾讯微证券 CLI 后，`invest-cli westock <子命令>` 可透传 40+ 长尾能力（筹码 / 龙虎榜 / 陆股通 / 北向 / 两融 / 一致预期 / ESG / 机构评级 / 产业链 / 板块估值 / 可转债条款 / 停复牌 / 风险事件）；`invest-cli westock --help` 列出命令树。

---

## 1. 同花顺金融数据服务（推荐，A 股与公募主路）

```bash
export HITHINK_FINANCE_API_KEY="你的密钥"
```

- 覆盖：A 股个股（行情 + 估值 + 近 5 年年报 + 官方财务指标）、公募基金（资料/费率/收益/回撤/重仓）。
- 不覆盖：港股、美股、自然语言选股——这些走东财 / yfinance / SEC。
- 验证：`invest-cli stock 600519 --json` 能返回贵州茅台即为启用。

## 2. 东方财富（港股、选股、回退）

```bash
export EASTMONEY_APIKEY="你的密钥"
```

- 覆盖：A 股/港股快照、基金快照、自然语言选股（`invest-cli screen`）。
- **港股必经此路**（同花顺不覆盖港股）。
- 也可写入用户级凭据文件（不提交到 Git）：

```bash
mkdir -p ~/.config/invest-cli
printf 'EASTMONEY_APIKEY=%s\n' "你的密钥" > ~/.config/invest-cli/eastmoney.env
```

示例：

```bash
invest-cli stock 00700 --json          # 港股
invest-cli fund 005827 --json          # 基金
invest-cli screen "市盈率低于10的银行股"
```

名称映射提示：口语「易方达蓝筹 / 易方达蓝筹精选」对应代码 **005827**。

## 3. 美股 yfinance（启用 `us` 全量快照）

```bash
# 在 invest-cli skill 目录内建独立环境，避免污染系统 Python
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

之后 `invest-cli us AAPL --json` 可返回估值/财务/评级。未安装时自动回退 Bitget rToken 报价（仅行情、USDT 计价、非交易所官方价，结果里会明确标注）。

## 4. SEC EDGAR（美股财报原文，免费无 Key）

```bash
invest-cli sec AAPL --filings 5
```

- 数据来自 SEC 官方 XBRL（`companyfacts` + `submissions`），是「原文级」依据，可与 Wind / yfinance 的结构化数字交叉验证。
- SEC 要求 User-Agent 含联系方式；默认用占位邮箱通过校验，建议声明真实身份：

```bash
export SEC_EDGAR_USER_AGENT="your-name your@email"
```

- 单公司原始 JSON 约 3.7MB，磁盘缓存 24 小时；缓存文件有 7 天上限并自动清理。

## 5. FRED 宏观时序（净流动性，免 Key 可回退）

```bash
invest-cli intent macro
```

- 取美联储总资产（WALCL）− TGA（WDTGAL）− ON RRP（RRPONTSYD）+ SOFR。
- 无 Key 时走 `fredgraph.csv` 免 Key 通道（同源同口径）；两条通道都失败才降级到 argo 检索。
- 想用官方 API（更稳、带元数据）：免费注册后写入 `FRED_API_KEY` 或 `~/.config/invest-cli/fred.env`。

## 6. argo（资讯 / 舆情 / 宏观检索，可选）

```bash
invest-cli info 茅台
invest-cli info 美联储 缩表 --engine cls_telegraph
```

- 与结构化源的分工：盈米 / Wind / 同花顺 / 东财管「精确数值」，argo 管「检索资讯」，省结构化源配额。
- **引擎名原样透传给 argo，invest-cli 不维护白名单**（本地名单必然随 argo 版本漂移，曾造成「0 结果 + ok=true」的静默空答复）。传错会明确报错并给出清单命令：

```bash
python3 <argo>/scripts/search.py --list-engines          # 全部引擎
python3 <argo>/scripts/search.py --list-engines --detail # 含 key / 熔断 / 可路由状态
```

## 7. 其他可选外部源（Wind / 盈米 / 官方 ttskill）

- **Wind**：机构级数据，直连 Wind MCP（JSON-RPC over HTTP，不依赖 wind-mcp-skill 的 node CLI）；配好 `WIND_API_KEY` 或 `~/.wind-aifinmarket/config` 后 `invest-cli wind <server_type> <tool> --input '<json>'` 透传。
- **盈米且慢**：基金诊断、组合诊断、配置方案；配好 apiKey（`~/.yingmi-skill-cli/config.json`）后走 `invest-cli intent deep fund <代码>` / `intent portfolio` / `intent plan`。
- **官方 ttskill（天天基金）**：`fund` 快照的深取补充（同类分位 / 机构占比 / 经理在管）；登录就绪才补充，未登录自动跳过。37 个官方业务包清单见 `invest-cli capabilities ttskill`。

这三者都是**可选增强**：不可用时整条链自动跳过，不影响其他能力。三者均已改为**直连官方 API**，不再依赖外部 CLI 子进程。

---

## 取数规则（重要）

- **同一问题不混源**：整单回退，不把 A 源的字段和 B 源的字段拼在一张表里（口径不同）。
- **不同问题才组合**：行情走 A、选股走 B、资讯走 C 是三个不同问题，可以分别选源。
- **来源必须标注**：结果里会写明实际取数来源；`cached: true` 表示命中本地缓存。
- **路由自动**：不要在分析 skill 里猜数据源；统一走 `invest-cli stock/fund/us/sec/screen/intent`。

---

## 推荐组合顺序

| 场景 | 建议路径 |
|------|----------|
| 只想快速判断、未配任何源 | invest-* 框架 + 检索 |
| A 股看茅台 | `invest-cli stock 600519` → invest-stock 三关 |
| 港股 | `invest-cli stock 00700`（东财）→ invest-stock |
| 基金快照 | `invest-cli fund 110011` → invest-fund |
| 基金诊断 / 组合 | `invest-cli intent deep fund <代码>` → invest-fund |
| 美股 | `invest-cli us AAPL` → invest-stock 四维评分 |
| 美股财报原文核验 | `invest-cli sec AAPL` 与 Wind / yfinance 交叉验证 |
| 市场温度 / 流动性 | `invest-cli intent macro` → invest-macro |
| 资讯 / 舆情 | `invest-cli info <词>`（走 argo） |

---

## 隐私与安全

1. **密钥只放本机环境变量或用户级凭据文件**，禁止提交到 Git。
2. 日志、Issue、PR 中不要粘贴 Key、Cookie、完整账户持仓。
3. 本仓库示例仅使用公开基金/股票代码（如 600519、005827、AAPL）。
4. 工具不构成投资建议；盈亏自负。

---

## 故障排查

| 现象 | 处理 |
|------|------|
| `未设置 EASTMONEY_APIKEY` | 配置后**新开终端**再试；或检查 `~/.config/invest-cli/eastmoney.env` |
| `未安装 yfinance` / `us` 只剩 Bitget 报价 | 建 `.venv` 并 `pip install -r requirements.txt` |
| `无可用数据源: kind=fund` | 该 kind 在本机没有任何可用源；用 `invest-cli datasources` 看每源原因 |
| 港股查不到 | 港股只走东财，需配 `EASTMONEY_APIKEY` |
| `invest-cli: command not found` | 用 `"$HOME/.local/bin/invest-cli"` 兜底，或直接 `python3 skills/invest-cli/scripts/invest_cli.py` |
| `info` 报「不认识引擎」 | 引擎名写错；按报错里给出的命令列清单，或换 `eastmoney` |
| 网络/502 | 换时段重试；框架仍可用检索材料继续分析 |

---

*docs/data-sources.md · fund-investment-guide v2.7*
