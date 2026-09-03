# Invest 系列：投资分析技能组

> 覆盖个股、基金、可转债、商品、REITs、债券、宏观市场、资产配置、大师会诊、机构级研报产出。
> 大道至简，三关审查：懂不懂？好不好？贵不贵？

---

## 技能清单（v2.3）

| 技能 | 职责 | 入口问法 |
|------|------|---------|
| invest | 主入口路由 | 「分析一下茅台」 |
| invest-stock | 个股（A股/港股/美股） | 「看看茅台这只股票」 |
| invest-fund | 基金/ETF/经理 | 「张坤的基金怎么样」 |
| invest-asset | 债券/可转债/商品/REITs（单一品种资产） | 「这只转债值得买吗」「黄金能配吗」「REITs怎么看」「利率债现在怎么看」 |
| invest-macro | 宏观与市场环境 | 「市场过热了吗」 |
| invest-allocation | 资产配置 | 「我的配置合理吗」 |
| invest-discuss | 大师会诊（4视角×3深度） | 「让巴菲特和芒格看看」 |
| invest-analyst | 机构级内容产出 | 「出一份茅台的IC报告」 |
| invest-cli | 统一数据层（CLI） | 「用cli查一下茅台」 |

> 2026-09-03：invest-bond / invest-convertible / invest-commodity / invest-reit 四技能合并为 invest-asset（同一三关模板×四种资产参数，资产细则见 `invest-asset/references/asset-*.md`）。原四技能注册链已删除，历史原文在 `~/.claude/skills-archive/2026-09-03_merged-invest-asset/`。

**市场覆盖**：A股、港股、美股、QDII（全球配置）

---

## 核心框架：三关审查

```
第一关：懂不懂（能力圈/策略理解）   未通过 → 停止，不买
第二关：好不好（护城河/业绩持续性） 未通过 → 停止，不买
第三关：贵不贵（安全边际/估值时机） 未通过 → 等待；通过 → 可考虑买入
```

---

## 数据层（invest-cli，单一数据入口）

- 所有取数走 `invest-cli`（`stock/fund/us/screen/intent`），不为单个数据源单独路由
- 声明真源 `data-sources.yaml`；`invest-cli datasources` 查看本机可用快照链
- 命令入口 `invest-cli`（PATH）；无命令时兜底 `python3 "$HOME/.agents/skills/invest-cli/scripts/invest_cli.py"`
- 整单回退、不混字段；输出必须标注数据来源

---

## 共享方法论

`invest/_shared/references/` 是成员技能的共享方法库（IC 备忘录、估值 DCF、风险仓位、季度深挖、可比公司分析、论点与催化剂），成员以相对 symlink 引用，不复制副本。新增共享方法论只改这一处。

---

## 安装使用

把本目录下 9 个技能目录复制到技能根（`~/.agents/skills/` 或 `~/.zcode/skills/`），即装即用。可选依赖：`pip3 install yfinance`（美股全量快照）、`EASTMONEY_APIKEY`（港股/东财链路）。

```bash
# 建议补一个 PATH 入口（可选）
ln -s "$HOME/.agents/skills/invest-cli/scripts/invest_cli.py" ~/.local/bin/invest-cli
```

---

## 核心原则

1. **不替决策**：提供判断框架，决策权交还用户
2. **不预测排名**：不判断明年业绩第几，只评估持续跑赢能力
3. **不保证收益**：过往业绩不代表未来，需自行承担风险
4. **成本优先**：高费率是长期收益的最大敌人
5. **大道至简**：三关审查，不堆砌复杂度

---

## 版本历史

| 版本 | 说明 |
|------|------|
| v2.3 | 消融式维护：.codex 注册链对齐（删 3 死链补 6 缺失，四套链 9/9）、死路由清理（discuss/analyst/fund）、退役文档对齐（cli-runtime 重写、design 稿归档）、命令路径统一 |
| v2.2 | 薄单品种四合一：invest-bond/convertible/commodity/reit → invest-asset（同一三关模板×四种资产参数，注册数 12→9） |
| v2.1 | 口径统一（cli-runtime 以入口映射表为真源）、回归修复（analyst 路由/导航表）、死引用与断链清理、references 相对 symlink 收敛、invest-cli 命令入口化 |
| v2.0 | 真源归并 `_shared`、接入 invest-analyst、任务后导航、维护机制 |
| v1.0 | 全面重构：统一三关审查框架、动态时间算法、覆盖股基债商+配置+圆桌 |

---

**许可证**：MIT License
