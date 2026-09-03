# Changelog

## v2.3（2026-09-03 · 消融式维护）

本次按「第一性原理 + MECE + 消融实验」梳理系列，只处理经实验证据证明有价值或损坏的项，删无可证明必要性的复杂性。

- **注册链对齐**：`.codex` 注册链残留 3 个死链（invest-commodity/convertible/reit，指向已删源目录）已删，补齐缺失 6 技能（invest/asset/cli/discuss/macro/stock + fund）。四套链（`.agents` 真源 / `.claude` / `.zcode` / `.codex`）现全部 9/9 对齐。消融证据：`find -xtype l` 死链接扫描为零。
- **死路由清理（消融确认的真实断链）**：
  - invest-discuss 下游路由 `invest-us`（已归档）、`invest-hk-a`（已并入 stock）改指 `invest-stock` / `invest-asset`
  - invest-analyst 下游 `eastmoney`（已删，功能并入 invest-cli）、`market-analysis-radar`（已并入 macro）、能力确认列表同步改指 `invest-macro`/`invest-cli`
  - invest-fund 「言行一致」引用 `references/manager-patterns.md`（相对本目录断裂）统一为跨目录 `../invest-stock/references/manager-patterns.md`，与同文件 403 行一致
- **跨技能引用补前缀**：invest-cli SKILL/docs 中指向 invest-fund 口径真源的 `references/data-pipeline.md` 补全为 `invest-fund/references/data-pipeline.md`，消除 agent 按字面路径解析失败的风险。
- **过期文档对齐退役现状**：
  - 重写 `invest/references/cli-runtime.md`：删 ttfund/fundfof/fundscreen 全篇活性引用（2026-09-03 已退役），改为只声明「登录态源 + 搜索技能」两类外部依赖，并记录运行时数据源可用性矩阵
  - `invest/_shared/invest-asset-merge-design.md`（v2.2 已完成）归档 `.trash/`
- **命令路径统一**：invest-macro / invest-asset(asset-bond) 内硬编码家目录 `python ~/.agents/...` 改统一 `invest-cli` 命令（PATH 优先 + $HOME 兜底），符合 cli-runtime「禁止写死个人家目录」约定
- **隐藏能力文档化**：invest-cli `watchlist` 子命令（本地自选股，复用 route.fetch）此前有实现无文档，SKILL 补齐命令说明（不依赖外部登录态）
- **消融实验放行/不放行的判定**（不删项）：
  - 8 个数据源适配器各有测试覆盖（11 个 test 文件 67 测全绿），无孤儿组件，全部保留
  - 入口 table 所有路由目标技能齐全；9 技能 frontmatter 完整可触发——路由正确性消融通过
  - 端到端冒烟：`stock 600519`(茅台，hithink)、`fund 110011`(易方达优质精选，hithink)、`intent macro`(argo) 真实取数全部成功
  - 6 个分析 SKILL 头部「数据获取」段保留：每段含本技能特有命令（asset 用 `intent deep bond/commodity`、macro 用 `intent macro`），删整段会破坏自包含，非纯冗余

## v2.2（2026-09-03）

- **薄单品种四合一**：invest-bond / invest-convertible / invest-commodity / invest-reit 合并为 invest-asset（同一「三关审查」骨架 × 四种资产参数），资产细则下沉到 `invest-asset/references/asset-{bond,convertible,commodity,reit}.md` + `commodity-gold.md`
- **注册数收敛**：12 → 9（四个旧技能目录从 `.agents`/`.claude`/`.zcode` 三条注册链删除，原文归档 `~/.claude/skills-archive/2026-09-03_merged-invest-asset/`）
- **触发词归一**：四技能 description 触发词全集并入 invest-asset description（A1 验证 100% 覆盖），入口路由表/示例/图谱/归档记录同步改指
- **数据措辞统一**：asset-*.md 内残留 `ttfund bond` / `ttfund gold` 措辞改为 `intent deep bond` / `intent deep commodity`（官方 TTFUND_GOLD_INFO 已封装进 intent，不再裸透传老 CLI）
- **引用同步**：invest-macro / invest-allocation 分工表中四个旧技能名改指 invest-asset

## v2.1（2026-08-30）

- **回归修复**：v2.0 声称的 invest-analyst 路由行、「结论信号 → 下一步」导航表、维护段落此前被误删，本次补回；版本号从 v1.3 对齐到 v2.1
- **数据层口径统一**：cli-runtime.md 声明取数口径以入口「场景 → invest-cli 取数映射」表为真源；「诊断一下 XXXX」统一为 `intent deep fund`（盈米）优先、fundfof 降级备选；invest-cli 各源启用条件写全（同花顺免 key / 东财需 `EASTMONEY_APIKEY` 且港股必经 / 美股 yfinance 未装回退 bitget）
- **死引用清理**：invest-fund 分工表删除已归档的 invest-report / invest-fund-manager 两行，补 invest-allocation / invest-discuss；invest-cli 文案中 invest-us 改为 invest-stock 美股
- **断链清理**：invest-institutional 及 4 个已归档技能的断链入口（invest-fund-read / invest-hk-a / invest-us / fund-investor）移入 `.trash/`；补齐 invest-bond / invest-macro 缺失的 `.claude`、`.zcode` 注册链
- **references 收敛落地**：invest-stock 6 个重复 references 副本改为指向 `invest/_shared/references/` 的相对 symlink，原件归档 `.trash/2026-08-30_invest-stock-references-dup/`
- **入口可用性**：invest-cli SKILL.md 13 处硬编码家目录路径改为 `invest-cli` 命令 + `$HOME` 兜底说明；新增 `~/.local/bin/invest-cli` wrapper
- **测试修复**：route.fetch 新增 `order` / `invoke` 注入参数，回退逻辑测试不再依赖本机数据源配置；新增「整单失败返回 tried 信封」「单源异常续回退」两测
- **frontmatter 清理**：invest-discuss 删除冗余 aliases、description 去 markdown 星号

## v2.0（2026-08-03）

- **真源归并**：invest-stock 与 invest-institutional 的 6 个重复 references（1526 行）收敛到 `_shared/references/`，两成员改为引用共享路径
- **接入 invest-analyst**：路由表 + 图谱新增「IC报告/电话会/一致预期/主题策略 → invest-analyst」
- **任务后导航**：新增「结论信号 → 下一步」导航表（仿 dbs 的闭环设计）
- **维护机制**：新增维护段落（版本/共享方法论/归档记录）
- **清理过期引用**：invest-us 删除对不存在的 invest-report 的引用

## v1.1

- 纯路由入口，覆盖股基债商+配置+圆桌+机构深度分析
