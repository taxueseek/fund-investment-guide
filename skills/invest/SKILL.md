---
name: invest
description: |
  invest系列主入口。识别标的类型，路由到专业分析工具。

  触发：「分析一下」「看看这个」「值得买吗」「这只怎么样」「资产配置」「大师怎么看」
  「用cli查」「终端分析」
version: 2.0.2
---

# invest：入口

> 只做路由，不做分析。

## 哲学锚点

- **巴菲特「价值投资」**：买股票就是买企业的一部分。不懂不做，没有护城河不做，价格不合适不做。
- **芒格「格栅思维」**：单一视角必然盲视。用多个维度交叉验证，避免陷入思维定式。
- **德鲁克「有效性」**：投资的终极标准不是「能不能赚」，而是「对谁有价值」「不做会怎样」。

---

## 路由逻辑

收到请求后，识别关键词，直接路由（**先专项、后通用**）：

| 关键词 | 路由 |
|--------|------|
| 「/cli」「终端查」「invest cli」「用cli分析」 | invest-cli |
| 「基金」「ETF」「基金经理」「基金管理人」 | invest-fund |
| 「股票」「公司」「护城河」「PE」「ROE」「美股」「港股」「A股」「政策」「南下」「北上」「Apple」「TSLA」「NVDA」 | invest-stock |
| 「深度分析」「估值分析」「DCF」「投资备忘录」「机构视角」「可比公司」「催化剂」「仓位管理」 | invest-stock（深度模式） |
| 「转债」「可转债」「转股」「溢价率」 | invest-convertible |
| 「黄金」「白银」「原油」「商品」「大宗商品」 | invest-commodity |
| 「REIT」「REITs」「公募REIT」 | invest-reit |
| 「资产配置」「组合」「股债比例」「再平衡」 | invest-allocation |
| 「大师怎么看」「圆桌」「会诊」「几个角度」 | invest-discuss |

**混合表述**：如「分析一下易方达蓝筹这只基金」→ 含「基金」→ invest-fund  
**数据优先**：用户明确要「命令行 / cli 查数」时，优先 invest-cli，再视需要套框架。

---

## 数据能力（配置后启用）

安装后**始终可用**的是判断框架（三关 / 场景 / 大师会诊等）。  
结构化取数按配置探测启用，详见仓库 `docs/data-sources.md`。

| 探测条件 | 启用能力 |
|----------|----------|
| 环境变量 `EASTMONEY_APIKEY` 已设置 | `invest-cli` 的 stock / fund / screen（东方财富） |
| `yfinance` 可导入（或 skill 内 `.venv` 已装） | `invest-cli us`（美股） |
| 本机存在 `ttfund` 命令（用户自装/官方工具） | 基金公开取数优先，结果再交给 invest-fund |

- **未配置**：框架 + web_search / 用户材料，不假装已拉行情。  
- **已配置**：应优先用对应 CLI 取结构化数据，再套 invest-* 框架。  
- **分离可组合**：框架不内嵌厂商；换源不必改三关正文。

---

## 工作流程

**第一步：识别** — 读用户问题，匹配上表关键词。

**第二步：确认** — 说一句：> 分析[标的名称]，进入[技能名]。

**第三步：路由** — 立即执行对应技能，不中断、不重复询问。  
若目标 skill 的 `SKILL.md` 不在本会话列表中：读取安装目录下 `skills/<name>/SKILL.md` 后按正文执行。

---

## Path resolution（脚本类 skill）

```bash
# 禁止写死个人家目录绝对路径
# 在 invest-cli skill 根目录：
python3 scripts/invest_cli.py stock 600519 --json

# 可选覆盖
export INVEST_CLI=/path/to/invest_cli.py
export INVEST_CLI_ROOT=/path/to/invest-cli
```

未知环境：先探测 skill 根与 `command -v ttfund`；CLI 缺失则降级检索，不得假装已取数。

---

## 示例

| 用户说 | 动作 |
|--------|------|
| 「分析一下茅台」 | 分析茅台，进入invest-stock（三关审查）。 |
| 「分析一下AAPL」 | 分析AAPL，进入invest-stock（四维评分）。 |
| 「深度分析茅台，写个投资备忘录」 | 深度分析茅台，进入invest-stock（机构深度）。 |
| 「张坤的基金怎么样」 | 分析张坤的基金，进入invest-fund。 |
| 「这只转债值得买吗」 | 分析这只转债，进入invest-convertible。 |
| 「黄金能配置吗」 | 分析黄金，进入invest-commodity。 |
| 「REITs怎么看」 | 分析REITs，进入invest-reit。 |
| 「我的资产配置合理吗」 | 进入invest-allocation。 |
| 「让大师们看看这只股」 | 进入invest-discuss（大师会诊）。 |
| 「/cli 茅台」 | 进入invest-cli → stock 600519（需已配置东财 Key）。 |

---

## invest系列完整图谱

### 单一品种分析

| 技能 | 分析对象 | 核心问题 |
|------|---------|---------|
| invest-stock | 个股（A股/港股/美股） | 三关审查 · 四维评分 · 机构深度 |
| invest-fund | 基金/ETF/基金经理 | 懂策略吗？能跑赢吗？成本合理吗？ |
| invest-convertible | 可转债 | 懂条款吗？债底足吗？溢价合理吗？ |
| invest-commodity | 黄金/白银/原油 | 逻辑清晰吗？位置合理吗？能承受波动吗？ |
| invest-reit | REITs | 懂底层资产吗？分派可持续吗？估值合理吗？ |

### 组合与决策

| 技能 | 功能 | 用途 |
|------|------|------|
| invest-allocation | 资产配置 | 股债商比例、再平衡、组合检视 |
| invest-discuss | 大师会诊 | 4视角×2深度，多视角验证、发现盲区 |

### 数据适配（可选，配置后启用）

| 技能 | 层 | 用途 |
|------|----|------|
| invest-cli | 数据适配 | 东财快照 / yfinance 美股 → `--json` 再套框架 |

**设计原则：分离 + 可组合**

| 层 | 职责 | 边界 |
|----|------|------|
| 框架 | invest-stock / fund / …：怎么想 | **不内嵌**某一家 API |
| 数据 | invest-cli / 用户自备 ttfund / web_search：怎么取 | 取数不代替下结论 |
| 路由 | invest | 只转发 |

---

## 核心原则

- **不问**：不让用户选择分析类型
- **不重复**：路由后不再重复询问
- **不分析**：本技能不做任何分析，只做路由
- **分离可组合**：框架不内嵌厂商；有数据源时鼓励组合使用
- **配置门闩**：未配置不启用对应 CLI；已配置应优先取数
- **不硬编码路径**：脚本根用探测 / 环境变量

---

## 已归档路由

旧名 `invest-hk-a` / `invest-us` / `invest-institutional` / `invest-report` / `invest-fund-manager` 等均已并入 invest-stock / invest-fund。运行时不要再路由到已删除 skill。

---

## Changelog

**v2.0.2** — 配置门闩（东财 / yfinance / 可选 ttfund 探测）；CLI 工程加固；公开路由消毒；死链清理

**v2.0** — 统一框架：invest-stock 合并港A/美股/机构深度；invest-fund 场景路由；invest-discuss / invest-cli

---

*invest v2.0.2 | 纯路由 | 分离 · 可组合 | 配置后启用*
