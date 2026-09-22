# invest-cli 数据源与能力矩阵

本文件是 invest 系列**数据层**的接入说明与能力矩阵。投资分析 skill 只负责「怎么想」，数据层（invest-cli）负责「怎么取」，二者分离。

- 数据源声明真源：`../data-sources.yaml`（新增/修改数据源只改它，不重写适配器）
- 可用性探测：`invest-cli datasources`（统一门闩，运行时才判定）
- 取数命令：`invest-cli <源> <标的/工具> ...`，统一输出 JSON

---

## 数据源总览

| 数据源 | 类型 | 覆盖场景 | 优先级 | 启用条件 |
| --- | --- | --- | --- | --- |
| Wind（万得，直连 MCP） | API | stock / fund / index / bond / news / macro / analytics | 80 | 有 `WIND_API_KEY`（`~/.wind-aifinmarket/config` 或环境变量） |
| 盈米（且慢，直连 OpenAPI） | API | fund / strategy / wealth / news | 70 | `~/.yingmi-skill-cli/config.json` 有 apiKey |
| 同花顺金融数据服务 | API | stock / fund（A 股与公募） | 60 | `HITHINK_FINANCE_API_KEY` 或用户级 `credentials.env` |
| 东方财富 | API | stock / fund / screen | 50 | 设置 `EASTMONEY_APIKEY` |
| Yahoo Finance（yfinance） | python | us | 40 | 安装 `yfinance` |
| SEC EDGAR（美股财报原文） | API | us 财报原文（10-K XBRL 指标 + 申报清单） | 45 | 免费无 key（可选 `SEC_EDGAR_USER_AGENT` 声明身份）；`invest-cli sec <代码>` 直取，不经快照链 |
| Bitget rToken | API | us（仅行情） | 35 | 始终可用（公开 API，无 key，stdlib） |
| 天天基金（直连 gateway，可选深取引擎） | API | fund（同类分位/机构占比/在管列表深取） | 55 | 官方凭据未过期（Keychain）+ 已装业务包；缺省自动跳过（主路=自带 hithink>eastmoney） |

优先级的含义：同一**问题**有多个数据源可用时，按优先级从高到低选取；高优先级源失败才整单降级。yaml 的 coverage 只是声明；适配器必须暴露 `stock()` / `fund()` / `us()` / `screen()` 才会进入默认快照链。Wind 声明覆盖 stock 但只有 `call()`，因此**不会**出现在 `invest-cli stock` 里。

运行时链由 `scripts/sources/route.py` 计算，`invest-cli datasources` 打印。不要在各 cmd_* 里再写一套 if/else。

---

## 能力矩阵（数据源 × 场景）

| 场景 | Wind | 盈米 | 同花顺 | 东财 | 天天官方 ttskill | yfinance | Bitget |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 个股行情/估值（A股） | 强 | — | 强（官方 REST） | 强 | — | — | — |
| 个股行情/估值（港股） | 强 | — | — | 强 | — | — | — |
| 个股财务（近 5 年年报） | 强 | — | 强 | 中（最新一期） | — | — | — |
| 选股（多条件筛选） | 强 | — | — | 强（自然语言） | — | — | — |
| 美股行情 | 强 | — | — | — | 强 | 中（rToken/USDT，非官方价） | — |
| 美股财务 | 强 | — | — | — | 强 | — | — |
| 基金净值/业绩/风险 | 强 | 强 | 强 | 强 | — | — | 中 |
| 基金重仓/持仓穿透 | 强 | 中 | 强 | 强 | — | — | 中 |
| 基金经理画像/产品对比 | 强 | 中 | 中（经理列表） | 中 | — | — | — |
| 策略/组合筛选 | 中 | 强（策略、持仓） | — | — | — | — | — |
| 财富规划/资产配置 | 中 | 强（wealth-* 场景） | — | — | — | — | — |
| 宏观/行业/汇率指标 | 强（economic_data） | 中 | — | — | — | — | — |
| 财经资讯/舆情/经理观点 | 强（financial_docs） | 强（content/*） | — | 中 | — | — | — |
| 债券/转债 | 强（bond_data） | 中 | — | — | — | — | — |

同一格内越靠前越推荐；`—` 表示该源基本不覆盖该场景。

---

## 取数与降级约定

1. **取数走命令，探测走内部**：`stock/fund/us/screen/intent` 内部由 `route.pick` 做准入（coverage × 真方法 × detect）。`datasources` 是诊断命令，不要当作每次取数的前置——它会额外探测 Wind/盈米等 CLI，把一次茅台查询拖成十几秒。
2. **单源优先，整单回退**：一个场景优先用最高优先级源一次性取全；失败才降级到下一可用源，禁止跨源合并字段。
3. **逐项探针**：同一源需要批量标的时，先发第一个作探针，成功才继续其余；探针返回错误中止该批。
4. **口径标注**：数据来自哪个源必须在输出里标注，冲突字段并列，禁止口径未对齐合并。
5. **Wind 接口错误**：`AUTH_ERROR`、`RATE_LIMIT_ERROR`、`backend_error` 等必须原样报告，不得用其它源掩盖，也不得切换到 `analytics_data` 伪装支持。

---

## 数据源成本与降级链

数据源按「精确度 × 成本」分两类，取数优先结构化权威源，配额不足降级到检索源：

| 类别 | 数据源 | 特点 | 用在哪 |
| --- | --- | --- | --- |
| 结构化权威 | 盈米 / Wind / 同花顺 / 东财 / yfinance / SEC EDGAR / Bitget(rToken 行情) | 精确但限额、部分需 key（SEC 免费无 key） | 净值 / 行情 / 财务 / 财报原文 / 筛选 / 配置 |
| 检索资讯 | argo（eastmoney/zhihu/cninfo/财经垂直源） | 广覆盖、低成本、需核验 | 资讯 / 舆情 / 宏观背景 / 观点；结构化源兜底 |

**降级链**：结构化源 → 同域其他结构化源 → `invest-cli info <词>`（argo 检索，结果需核验）。
**省配额**：资讯 / 舆情 / 宏观背景优先用 `invest-cli info <词>`，把盈米 / Wind 的配额留给结构化数值取数。
**取代关系**：`invest-cli intent` 是主取数入口（分析层不再直接依赖盈米/Wind skill，二者降为后端数据源）；argo 仅作检索资讯与兜底。

### argo 财经垂直源池

`invest-cli info <词> --engine <源>` 可从 argo 的垂直源取数，把盈米/Wind 配额留给结构化取数。

**引擎清单不在 invest-cli 维护**：argo 自带 250+ 引擎且随版本演进，任何本地白名单都会
漂移（曾出现白名单里的 `cn-web-search` 已不存在 → 用户拿到「0 结果 + ok=true」的静默空答复；
合法引擎如 anysearch 被静默换成 eastmoney）。现在引擎名原样透传，传错会明确报错：

```bash
python3 <argo>/scripts/search.py --list-engines          # 全部引擎
python3 <argo>/scripts/search.py --list-engines --detail # 含 key/熔断/可路由状态
```

投资场景常用的几个：

| 引擎 | 领域 | 备注 |
| --- | --- | --- |
| eastmoney / cninfo / cn_ai_news | 东财资讯 / 上市公司披露 / AI 资讯 | 免 key，`info` 默认 eastmoney |
| jin10 / cls_telegraph / em_flow / em_global_news / em_miaoxiang | 财经快讯 / 资金流 / 全球资讯 | 免 key |
| finviz / fx_rate / gdelt / coingecko | 美股可视化 / 汇率 / 全球事件 / 加密 | 免 key |
| nbs_stats | 国家统计局（GDP/CPI/工业等） | 免 key，`intent macro` 的 argo 兜底引擎 |
| zhihu / anysearch | 中文观点 / 通用中文检索 | 免 key |
| fred / eurostat / eu_opendata / worldbank / fr_opendata | 欧美官方统计 | 需各自 key；未配置时 argo 会给出原因 |

`intent macro` 取数顺序：**FRED 结构化净流动性优先**（`sources/fred.py`，有 key 走官方 API、
无 key 走 fredgraph.csv），失败或取不到净流动性时才降级为 `info --engine nbs_stats` 检索兜底。

---

## 配置方法

### 同花顺金融数据服务（A 股 / 公募优先）

统一凭据（不要写进仓库或对话）：

```bash
export HITHINK_FINANCE_API_KEY=你的_key
# 或用户级文件（macOS）：
# ~/Library/Application Support/hithink-finance/credentials.env
```

启用能力：`invest-cli stock`（A 股）、`invest-cli fund`。港股、自然语言选股、美股不走此源。
A 股个股降级链：Wind（透传）→ 同花顺 → 东财。基金 intent：盈米 → 同花顺 → 东财。
名称消歧走官方 search，禁止猜测 `.SH` / `.SZ` / `.OF`。null 不补零。跨源禁止混字段。

### 东方财富（A股/港股/基金快照、选股）

```bash
export EASTMONEY_APIKEY=你的_key
```

启用能力：`invest-cli stock/fund/screen`。

### 美股

```bash
pip3 install yfinance
```

启用能力：`invest-cli us`（yfinance 全量快照：估值/财务/评级）。

**Bitget rToken 报价兜底**（无需配置）：公开行情 API，stdlib 即可。未装 yfinance 或取数失败时，`invest-cli us` / `intent deep us` 自动回退到 Bitget，输出为 USDT 代币价（`quote_type=rtoken`），**不是**美股交易所官方报价。美股行情降级链：**yfinance → 腾讯行情 → bitget**（Wind 只走 `invest-cli wind` 透传，不在快照链上，运行时链以 `invest-cli datasources` 的 `_chains` 为准）。

### 腾讯行情（零鉴权，多市场实时行情）

无需任何配置。`qt.gtimg.cn` 公开行情接口，一次请求可带多个标的（逗号分隔），
覆盖 A股/港股/美股/ETF/可转债/指数。

- **优先场景**：`invest-cli quote <代码...>`（纯行情，实测 6 标的混合 132ms）
- **兜底场景**：`us` 链的兜底位（yfinance 不可达时 130ms 给出真实美股行情，
  而 bitget 只有代币成交价、无 PE/PB/ROE/市值）；A股/港股链的末位
- **能力边界**：**没有基本面**（净利润/ROE/EPS/资产负债率一项都没有），
  因此不占主位——`stock`/`us` 的主位必须留给带基本面的富源，否则是能力降级
- **不含基金**：`fund` 链不走腾讯。场外基金号码与沪市可转债共用号段
  （110011 既是易方达中小盘也是歌华转债），行情接口只覆盖后者，
  直接查会**返回另一个标的**；适配器对这类输入直接拒绝并指向 `invest-cli fund`
- **口径注意**：qt 返回的字段下标**按市场不同**（市净率 A股在 [46]、美股在 [51]；
  换手率 A股在 [38]、港股在 [59]；成交额 A股是万元而港美股是元）。
  适配器按市场分表并只登记已用独立源核对过的下标，见 `scripts/sources/tencent.py`

### SEC EDGAR（美股财报原文，免费官方源）

无需任何配置（SEC 官方公开 API）。建议设置真实联系方式（SEC 要求 UA 含邮箱，www.sec.gov 域不带邮箱会 403；默认用占位邮箱通过校验）：

```bash
export SEC_EDGAR_USER_AGENT="your-name your@email"
invest-cli sec AAPL                  # 终端可读输出
invest-cli sec AAPL --json           # 结构化（给分析层）
invest-cli sec MSFT --forms 10-K --filings 3
```

- 取数：10-K 年报 XBRL 关键指标（营收/净利/营业利润/毛利/经营现金流/总资产/股东权益/EPS）+ 最近申报清单（带 edgar 原文链接）
- 口径：只取 `form=10-K` + `fp=FY`；时长型事实限 300~400 天（季度值不进）；标签漂移按优先级回退
- 缓存：`~/Library/Caches/invest-cli/sec/`（ticker 映射 7 天、companyfacts 24h、submissions 6h）
- 边界：仅美股发行人；20-F（外国私人发行人）与基金 N-CSR 不在覆盖内，会明确报错
- 定位：与 Wind / yfinance 数字交叉验证的原文级依据；**不经快照链**（`route.pick` 只认 stock/fund/us/screen 方法）

### FRED（宏观时序，可选 key）

```bash
invest-cli intent macro            # 净流动性三序列（WALCL/TGA/ON RRP）+ SOFR
```

- 有 `FRED_API_KEY`（环境变量或 `~/.config/invest-cli/fred.env`）：走官方 API
- 无 key：自动回退 `fredgraph.csv` 免 key 通道（同源同口径，内置 3 次重试）；输出 `transport` 字段标注走了哪条通道
- 长期使用建议免费注册 key（https://fred.stlouisfed.org/docs/api/api_key.html ，约 2 分钟）

### 万得 Wind（机构级，直连 MCP）

只需要一个 Key，**不需要安装 wind-mcp-skill 的 node CLI**。Key 顺序与官方一致：

```bash
export WIND_API_KEY=<你的Key>      # 或写入 ~/.wind-aifinmarket/config
```

启用能力：`invest-cli wind <server_type> <tool> --input '<json>'`。
server_type：stock_data / fund_data / index_data / bond_data / financial_docs / economic_data / analytics_data。

### 盈米且慢（基金/策略/财富/资讯，直连 OpenAPI）

只需要 apiKey，**不需要安装 `yingmi-skill-cli`**（仍沿用它的凭据位置）：

```json
// ~/.yingmi-skill-cli/config.json
{"apiKey": "<你的apiKey>"}
```

启用能力：`invest-cli yingmi <tool> --input '<json>'`。操作清单取官方 docs.json（磁盘缓存 6h），不在本地维护第二份。

### 天天基金（直连 gateway）

**不需要安装 ttskill CLI**：直接调官方 gateway（`POST /openapi/skill/invoke`），认证沿用官方凭据存储（macOS Keychain `com.ttfund.ttskill.base`）与 ed25519 签名（与官方基础包同一套逻辑）。只需完成一次官方登录（用官方基础包或任何写同一 Keychain 的工具）。

invest-cli 只暴露两处入口，Agent 不直接管理 37 个业务包：
- `invest-cli fund <代码/名称>`：三关快照（SEARCH/BASE_INFOS/HOLDING_INFO；链位 55，登录就绪才参与，主路仍是自带 hithink）
- `invest-cli intent deep commodity ...`：黄金 → `TTFUND_GOLD_INFO`
- 其他包透传：`invest-cli ttskill <skill_id> --input '<json>'`（清单 `invest-cli capabilities ttskill`）

字段口径真源：invest-fund `invest-fund/references/data-pipeline.md` + `sources/ttskill.py`。

---

## 快速自检

```bash
invest-cli datasources              # 查看各数据源是否可用
invest-cli sec AAPL                 # SEC 财报原文（免费，无需配置）
invest-cli wind stock_data get_stock_price_indicators --input '{"windcode":"600519.SH"}'
invest-cli yingmi GetCurrentTime
```

数据来源于万得 Wind 金融数据服务 / 盈米且慢 / 同花顺金融数据服务 / 东方财富 / Yahoo Finance / SEC EDGAR / Bitget rToken。
