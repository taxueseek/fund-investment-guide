---
name: invest-cli
description: |
  投资分析 CLI — 数据获取 + 分析框架一体化，dual-mode 运行。配置数据源后启用对应子命令。

  触发：「/cli」「/投资cli」「invest cli」「终端分析」「命令行分析」
  或：「用cli分析」「终端查一下」「命令行看看」

  也支持直接运行 CLI 脚本：
  python3 scripts/invest_cli.py stock 600519
---

# invest-cli — 数据适配 CLI

## 定位

与 invest 框架 **分离，但鼓励组合**：

| | invest-stock / invest-fund … | invest-cli |
|--|------------------------------|------------|
| 职责 | 怎么想（框架） | 怎么取（结构化快照） |
| 关系 | 消费任意可信数据 | 提供可选数据源（东财 / yfinance） |
| 是否必须 | 分析要靠框架 | **配置后启用**；不是唯一取数方式 |

**dual-mode**：

- Skill 触发 → CLI `--json` → **再套** invest 框架解读（组合）
- 终端直接运行 → 表格快照

配置说明见仓库 `docs/data-sources.md`。

## 配置门闩（未配置则不启用）

| 子命令 | 启用条件 | 未配置时 |
|--------|----------|----------|
| `stock` / `fund` / `screen` | 环境变量 `EASTMONEY_APIKEY` | 退出并提示如何配置以启用 |
| `us` | 已安装 `yfinance`（可用 skill 内 `.venv`） | 提示安装命令 |

未配置时**不要**编造行情；引导用户完成配置后再重试。

## 路由逻辑

| 用户意图 | 子命令 |
|----------|--------|
| A股/港股代码或名称 | `stock` |
| 基金代码或名称 | `fund` |
| 美股 ticker | `us` |
| 自然语言选股条件 | `screen` |

### stock — A股/港股（需东财 Key）

```bash
python3 scripts/invest_cli.py stock <代码/名称> [--json]
```

- **数据源**：东方财富 claw API（`EASTMONEY_APIKEY`）
- 获取：实时行情 + PE/PB/ROE/毛利率/现金流
- 字段形状对齐 invest-stock 三关所需指标
- 内置名称映射：茅台→600519、五粮液→000858 等

### fund — 基金快照（需东财 Key）

```bash
python3 scripts/invest_cli.py fund <代码/名称> [--json]
```

- **数据源**：东财 claw
- 获取：净值/业绩/风险/费率/经理/重仓
- 内置名称映射：易方达蓝筹精选→**005827**、中欧医疗→003096 等

### us — 美股快照（需 yfinance）

```bash
python3 scripts/invest_cli.py us <代码> [--json]
```

- **数据源**：yfinance → Yahoo Finance
- 字段形状对齐 invest-stock 四维所需指标

### screen — 选股（需东财 Key）

```bash
python3 scripts/invest_cli.py screen <条件> [--json]
```

- **数据源**：东财选股 API
- 支持自然语言条件，如「市盈率低于10的银行股」

## Skill 触发后的执行流程

1. 识别子命令与代码  
2. **先检查配置门闩**；未通过则输出配置引导并停止  
3. 调用 CLI `--json`  
4. 将 JSON 交给 invest-stock / invest-fund 等框架解读  

### 示例

```
用户：「/cli 茅台」且已配置东财
→ invest_cli.py stock 600519 --json → invest-stock 三关报告

用户：「/cli AAPL」且已装 yfinance
→ invest_cli.py us AAPL --json → 四维/框架解读
```

## Path resolution

```bash
cd /path/to/invest-cli   # skill 根
python3 scripts/invest_cli.py stock 600519 --json

export INVEST_CLI=/path/to/invest_cli.py
# 或
export INVEST_CLI_ROOT=/path/to/invest-cli
```

禁止写死 `/Users/<name>/`。系统 Python 若无 yfinance，会自动尝试 skill 内 `.venv`（见 `requirements.txt`）。

## 环境要求

- Python 3.10+
- `EASTMONEY_APIKEY`：启用 stock / fund / screen
- `yfinance`、`requests`：见 `requirements.txt`（建议 `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`）

## JSON 契约

所有子命令 `--json` 提供扁平 `data` 字段（stock/fund/us 一致），便于 Agent 消费。  
美股额外保留 `quote` / `financial` 分区。

## Changelog

**v2.0.2** — 配置门闩文案；字段别名；路径可移植；蓝筹映射 005827；venv reexec；契约测试

---

*invest-cli v2.0.2 | 配置后启用 · 与框架分离可组合*
