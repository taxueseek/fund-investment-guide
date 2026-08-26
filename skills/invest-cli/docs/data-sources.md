# invest-cli 数据源与能力矩阵

本文件是 invest 系列**数据层**的接入说明与能力矩阵。投资分析 skill 只负责「怎么想」，数据层（invest-cli）负责「怎么取」，二者分离。

- 数据源声明真源：`../data-sources.yaml`（新增/修改数据源只改它，不重写适配器）
- 可用性探测：`invest-cli datasources`（统一门闩，运行时才判定）
- 取数命令：`invest-cli <源> <标的/工具> ...`，统一输出 JSON

---

## 数据源总览

| 数据源 | 类型 | 覆盖场景 | 优先级 | 启用条件 |
| --- | --- | --- | --- | --- |
| Wind（万得） | CLI | stock / fund / index / bond / news / macro / analytics | 80 | 找到 `wind-mcp-skill`（`WIND_SKILL_DIR` 或 `INVEST_SKILL_ROOTS`）且有 key |
| 盈米（且慢） | CLI | fund / strategy / wealth / news | 70 | `yingmi-skill-cli init` 完成、`hasApiKey=true` |
| 东方财富 | API | stock / fund / screen | 50 | 设置 `EASTMONEY_APIKEY` |
| Yahoo Finance（yfinance） | python | us | 40 | 安装 `yfinance` |
| 天天基金（ttfund） | CLI | fund / bond / gold / macro / strategy / allocate / research | 30 | 本机装有 `ttfund`，且已 `ttfund login` |

优先级的含义：同一场景有多个数据源可用时，按优先级从高到低选取；高优先级源失败才降级到低优先级源，避免重复调用。

---

## 能力矩阵（数据源 × 场景）

| 场景 | Wind | 盈米 | 东财 | yfinance | ttfund |
| --- | --- | --- | --- | --- | --- |
| 个股行情/估值（A股/港股） | 强（低延迟、指标全） | — | 强 | — | — |
| 个股财务/高管/股东/事件 | 强 | — | 中 | — | — |
| 选股（多条件筛选） | 强 | — | 强（自然语言） | — | — |
| 美股行情/财务 | 强 | — | — | 强 | — |
| 基金净值/业绩/风险 | 强 | 强 | 强 | — | 中 |
| 基金重仓/持仓穿透 | 强 | 中 | 强 | — | 中 |
| 基金经理画像/产品对比 | 强 | 中 | 中 | — | — |
| 策略/组合筛选 | 中 | 强（策略、持仓） | — | — | — |
| 财富规划/资产配置 | 中 | 强（wealth-* 场景） | — | — | — |
| 宏观/行业/汇率指标 | 强（economic_data） | 中 | — | — | — |
| 财经资讯/舆情/经理观点 | 强（financial_docs） | 强（content/*） | 中 | — | — |
| 债券/转债 | 强（bond_data） | 中 | — | — | — |

同一格内越靠前越推荐；`—` 表示该源基本不覆盖该场景。

---

## 取数与降级约定

1. **先探测，再调用**：任何取数前先 `invest-cli datasources --json` 拿到可用源列表，按 `priority` 降序选源。
2. **单源优先，降级补全**：一个场景优先用最高优先级源一次性取全；若其关键字段缺失或返回错误，再降级到下一可用源补齐，不重复调用已成功的源。
3. **逐项探针**：同一源需要批量标的时，先发第一个作探针，成功才继续其余；探针返回错误中止该批。
4. **口径标注**：数据来自哪个源必须在输出里标注，冲突字段并列，禁止口径未对齐合并。
5. **Wind 接口错误**：`AUTH_ERROR`、`RATE_LIMIT_ERROR`、`backend_error` 等必须原样报告，不得用其它源掩盖，也不得切换到 `analytics_data` 伪装支持。

---

## 数据源成本与降级链

数据源按「精确度 × 成本」分两类，取数优先结构化权威源，配额不足降级到检索源：

| 类别 | 数据源 | 特点 | 用在哪 |
| --- | --- | --- | --- |
| 结构化权威 | 盈米 / Wind / 东财 / yfinance | 精确但限额、需 key | 净值 / 行情 / 财务 / 筛选 / 配置 |
| 检索资讯 | argo（eastmoney/zhihu/cninfo/财经垂直源） | 广覆盖、低成本、需核验 | 资讯 / 舆情 / 宏观背景 / 观点；结构化源兜底 |

**降级链**：结构化源 → 同域其他结构化源 → `invest-cli info <词>`（argo 检索，结果需核验）。
**省配额**：资讯 / 舆情 / 宏观背景优先用 `invest-cli info <词>`，把盈米 / Wind 的配额留给结构化数值取数。
**取代关系**：`invest-cli intent` 是主取数入口（分析层不再直接依赖盈米/Wind skill，二者降为后端数据源）；argo 仅作检索资讯与兜底。

### argo 宏观 / 财经垂直源池（环节配额）

`invest-cli info <词> --engine <源>` 可从这些垂直源取数，把盈米/Wind 配额留给结构化取数：

| 引擎 | 领域 | 需 key |
| --- | --- | --- |
| nbs_stats | 国家统计局（GDP/CPI/工业等） | 否 |
| jin10 / cls_telegraph / em_flow / em_global_news / em_miaoxiang | 财经快讯/资讯 | 否 |
| eastmoney / cninfo / cn_ai_news | 东财/上市公司披露/资讯 | 否 |
| finviz / fx_rate / gdelt / coingecko | 美股可视化/汇率/全球事件/加密 | 否 |
| fred | 圣路易斯联储（联邦基金利率/美债等） | 是（需 FRED key） |
| eurostat / eu_opendata / fr_opendata | 欧盟/欧洲官方统计 | 是 |
| worldbank | 世界银行数据 | 是 |

`intent macro` 默认走 nbs_stats（无需 key）；如需 fred/eurostat，请先配置对应 API key。

---

## 配置方法

### 东方财富（A股/港股/基金快照、选股）

```bash
export EASTMONEY_APIKEY=你的_key
```

启用能力：`invest-cli stock/fund/screen`。

### 美股

```bash
pip3 install yfinance
```

启用能力：`invest-cli us`。

### 万得 Wind（机构级）

1. 安装 Wind skill 并完成 Key 配置（见 Wind 官方 `skill.md` 流程）。
2. 让 invest-cli 能定位到它，两种方式任一：
   - 设置 `WIND_SKILL_DIR` 指向 wind-mcp-skill 目录（skill 装在项目内时推荐）
   - 或设置 `INVEST_SKILL_ROOTS` 指向包含 `.agents/skills` 的项目根（冒号分隔多个）

```bash
export WIND_SKILL_DIR="$INVEST_SKILL_ROOTS/wind-mcp-skill"
# 或
export INVEST_SKILL_ROOTS="/你的项目根/.agents/skills"
```

启用能力：`invest-cli wind <server_type> <tool> --input '<json>'`。

### 盈米且慢（基金/策略/财富/资讯）

```bash
yingmi-skill-cli init setup --api-key <apiKey>   # 或手机号验证码流程
yingmi-skill-cli init status                      # 确认 hasApiKey=true
```

启用能力：`invest-cli yingmi <tool> --input '<json>'`。

### 天天基金（ttfund，场景引擎）

```bash
ttfund login     # 首次需登录（账号 / Token）
```

登录后 `invest-cli datasources` 检测到 ttfund 可用，`invest-cli ttfund <bond/gold/macro/diagnose/...>` 可透传其场景命令。覆盖债券 / 黄金 / 宏观 / 基金诊断 / 选基 / 资产配置 / 研究等场景，是 invest 系列在债券、黄金、宏观市场的场景引擎。

---

## 快速自检

```bash
invest-cli datasources              # 查看各数据源是否可用
invest-cli wind stock_data get_stock_price_indicators --input '{"windcode":"600519.SH"}'
invest-cli yingmi GetCurrentTime
```

数据来源于万得 Wind 金融数据服务 / 盈米且慢 / 东方财富 / Yahoo Finance。
