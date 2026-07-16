# 可选数据源：配置后启用

本仓库首先是一套**投资判断框架**。不配置任何 API 也能使用：靠公开检索与你提供的材料，跑三关审查 / 场景路由 / 大师会诊。

配置数据源之后，对应的**结构化取数能力才会启用**；取数与下判断分离，也都不构成投资建议。

---

## 能力总览

| 数据源 | 配置物 | 启用后多出来的能力 | 不配置时 |
|--------|--------|--------------------|----------|
| （无） | — | 框架 + 检索 + 用户材料 | 默认路径 |
| **东方财富** | 环境变量 `EASTMONEY_APIKEY` | `invest-cli`：`stock` / `fund` / `screen` | 上述子命令拒绝执行并提示配置 |
| **Yahoo（yfinance）** | 安装 Python 包 `yfinance` | `invest-cli us` 美股快照 | 提示安装；可建 skill 内 `.venv` |
| **天天基金**（可选外部） | 本机安装官方/社区 `ttfund` 等工具并完成其自身登录或密钥配置 | 净值、重仓披露、经理等公开基金数据；**优先喂给 invest-fund** | 跳过该源，改用东财 fund 或检索 |

本公开包**不包含**第三方基金聚合网站 skill，也不提供券商交易或代操作账户。

---

## 1. 东方财富（推荐，启用 invest-cli 主能力）

### 1.1 你需要什么

1. 向东方财富开放平台 / FinSkills 等相关渠道申请 **API Key**（以官方当时说明为准）。  
2. 仅在**本机**写入环境变量，**不要**把 Key 写进仓库、截图或聊天记录。

### 1.2 配置

```bash
# 当前会话
export EASTMONEY_APIKEY="你的密钥"

# 持久化（示例：写入 shell 配置后重新打开终端）
# echo 'export EASTMONEY_APIKEY=你的密钥' >> ~/.zshrc
```

验证是否启用：

```bash
# 在 invest-cli skill 目录
python3 scripts/invest_cli.py stock 600519 --json
```

- **成功**：打印 JSON 行情/财务字段 → 可交给 invest-stock 做三关。  
- **失败且提示未设置 Key**：说明尚未启用东财能力，按上文配置后重试。

### 1.3 启用的命令

| 命令 | 用途 |
|------|------|
| `stock <代码/名称>` | A股/港股行情 + 估值 + 财务要点 |
| `fund <代码/名称>` | 基金净值/业绩/费率/经理/重仓快照 |
| `screen "<条件>"` | 自然语言选股 |

示例：

```bash
python3 scripts/invest_cli.py stock 茅台 --json
python3 scripts/invest_cli.py fund 005827 --json
python3 scripts/invest_cli.py screen "市盈率低于10的银行股" --json
```

名称映射提示：口语「易方达蓝筹 / 易方达蓝筹精选」对应代码 **005827**（易方达蓝筹精选混合）。

---

## 2. 美股 yfinance（启用 `us`）

```bash
cd skills/invest-cli   # 以你的安装路径为准
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# 之后可直接：
python3 scripts/invest_cli.py us AAPL --json
```

系统 Python 若未装 yfinance，入口脚本会尝试自动使用 skill 内 `.venv`（若已创建）。

---

## 3. 天天基金（可选外部，配置后优先服务 invest-fund）

### 3.1 定位

- **取数**：净值、持仓披露、经理画像等公开信息（以你所装工具支持的范围为准）。  
- **判断**：仍由 `invest-fund` 三关 / 场景路由完成。  
- 本仓库**不内嵌**天天基金登录实现；请使用官方或你信任的 CLI/skill，凭证留在本机安全存储中。

### 3.2 如何「配置并启用」

1. 按天天基金 / 相关开放能力的**官方文档**安装 CLI 或 skill（名称常见为 `ttfund` 等）。  
2. 完成其要求的登录或 API 配置（官方安全存储 / 环境变量等，以官方为准）。  
3. 确认 shell 中可执行：

```bash
command -v ttfund && ttfund --help
```

4. 在对话里分析基金时：若 Agent 探测到 `ttfund` 可用，应**优先**用其拉取数据，再进入 invest-fund；若探测不到，则自动降级为东财 `invest-cli fund`（若已配 Key）或检索。

### 3.3 与 invest 的组合方式

```
ttfund diagnose/info/holding  →  结构化摘要
        ↓
   invest-fund 场景/三关      →  懂不懂 / 好不好 / 贵不贵
```

不要用取数工具直接输出「建议买入/卖出」替代框架结论。

---

## 4. 推荐组合顺序

| 场景 | 建议路径 |
|------|----------|
| 只想快速判断、未配任何源 | invest-* 框架 + 检索 |
| 已配东财，看茅台 | `/cli` 或 `invest-cli stock` → invest-stock |
| 已配东财，看基金快照 | `invest-cli fund` → invest-fund |
| 已装 ttfund，深度看一只基 | ttfund 取数 → invest-fund |
| 美股 | `invest-cli us`（yfinance）→ invest-stock 四维 |

---

## 5. 隐私与安全

1. **密钥只放本机环境变量或官方安全存储**，禁止提交到 Git。  
2. 日志、Issue、PR 中不要粘贴 Key、Cookie、完整账户持仓。  
3. 本仓库示例仅使用公开基金/股票代码（如 600519、005827、AAPL）。  
4. 工具不构成投资建议；盈亏自负。

---

## 6. 故障排查

| 现象 | 处理 |
|------|------|
| `未设置 EASTMONEY_APIKEY` | export Key 后**新开终端**再试 |
| `未安装 yfinance` | 建 `.venv` 并 `pip install -r requirements.txt` |
| ttfund 命令不存在 | 未启用天天路径，属正常；改用东财或检索 |
| 网络/502 | 换时段重试；框架仍可用检索材料继续分析 |

---

*docs/data-sources.md · fund-investment-guide v2.0.2*
