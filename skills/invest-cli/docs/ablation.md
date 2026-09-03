# 消融实验记录：2026-09-03 invest-cli 数据源补齐

> 原则：每一项抽象/组件/机制都必须能证明其必要性，否则删除。
> 方法：每个机制做 A/B（无它 vs 有它），记录实际调用证据；"考虑过但没加"的复杂度列在末尾并说明删除理由。

## 1. yingmi 适配器数组解析修复（改 1 行 + 7 条单测）

**机制**：`sources/yingmi.py` call() 从只认 `{` 信封 → 兼容 `{`/`[`（对象信封 / 业务对象 / 数组直返）。

| 实验 | 结果 |
|---|---|
| A（修复前） | `GetPopularFund` 报"盈米未返回结构化数据"（2026-09-03 实测复现） |
| B（修复后） | `invest-cli yingmi GetPopularFund --input '{"size":5}'` → ok，返回数组 ✅ |
| 影响面 | 批量/列表类工具全被旧 bug 挡：GetPopularFund、BatchGetFundNavHistory、GetBatchFundPerformance、Search* 等约 20+ 工具 |

**保留判定**：✅ 保留。非新增抽象而是修复既有抽象的错误分支，A/B 差异是"完全不可用 → 可用"，无争议。
**守护**：test_yingmi.py（7 条离线 mock，覆盖数组/信封/业务对象/错误 4 形态 + 非 JSON）。

## 2. cmd_ttskill 透传命令（新 1 文件 + 注册 3 处）

**机制**：`invest-cli ttskill <skill_id> --input '<json>'`，复用既有 `sources/ttskill.invoke_scene()`。

| 实验 | 结果 |
|---|---|
| A（无命令） | 37 个官方包仅 4 个可达（fund 三合一 + GOLD 特判）；MANAGER_INFO/NAV_INFO/实时行情等 30+ 包"声明不可达"，Agent 只能现场翻官方包学调用（本次此前一轮实测踩坑） |
| B（有命令） | `invest-cli ttskill TTFUND_MANAGER_INFO --input '{"manager_name":"谢治宇"}'` → 经理画像+在管5只 ✅；`TTFUND_STOCK_PRICE_QUERY` → 东方财富 19.01 +0.53% @行情时间戳 ✅ |

**保留判定**：✅ 保留。接口面补齐（30+ 能力可达），非逐包封装，成本 1 个薄转发文件。
**为何不逐包收敛**：管理器/净值等高频包未来若被 invest-fund 场景反复消费，再收敛成高层入口（登记 capability-gap.md）；现在收敛是预支复杂度。
**守护**：test_capabilities.py（注册契约 + 边界标注）。

## 3. capabilities 能力发现层（新 1 文件 + 注册 3 处）

**机制**：`invest-cli capabilities [yingmi|ttskill]` 动态列官方能力 + 标注 ✅已收敛/⬜透传/🔒边界外。

| 实验 | 结果 |
|---|---|
| A（无发现层） | 盈米 69 工具只收敛 5 个、ttskill 37 包只封装 4 个，其余靠 Agent 记忆；本次此前一轮确实不知道有 `GetPopularFund`（走了弯路逐包翻 ttskill） |
| B（有发现层） | `capabilities yingmi` 命中 GetPopularFund/SearchFunds 等全部 69 工具 + 描述 + 收敛标注；`capabilities ttskill` 命中 37 包 + 本地描述 ✅ |

**保留判定**：✅ 保留。它是"根治不知道有什么"的最小机制：纯动态清单 + 一个白名单标注字典（~30 行），无第二份数据源。
**为何不做静态能力文档库**：官方工具会增删，静态表必然过期；动态 mcp list/skill list 为准，白名单只标注"收敛到哪"（低频变更）。

## 4. 消融"考虑过但删除"的复杂度

| 候选机制 | 删除理由（无法证明必要性） |
|---|---|
| `invest-cli hot [n]` 热门基金快捷命令 | GetPopularFund 一次透传即够，包一层只省 10 个字符，不构成独立意图 |
| CONDITION_SELECT 参数编码翻译层（自然语言→rsbType/orderField） | 编码含义未经官方释义逐字段核实，金融场景贸然翻译有误差风险；透传 + 官方 example 已可达，待 invest-fund 场景真实反复需求再收敛 |
| ttskill 返回结构归一化（各包 body 层级不同） | 透传语义=原样返回；归一化解释器需逐包维护字段表，纯增复杂度，等有消费方再说 |
| 账户/交易类包高层入口 | 边界纪律：invest-cli 是只读数据分析层，交易执行/持仓资金归账户职责；列为 🔒 标注防止误用 |

## 5. 回归基线

- pytest：67（改造前基线）→ 79 passed（+12：yingmi 7 + capabilities 5），全离线无网络依赖
- 实测冒烟：fund 主链（hithink）不受影响；wind/yingmi/argo 探测全绿
- 数据准确纪律：实时数据带行情时间戳（quote_timestamp）+ 来源标注（source_label），快照链整单回退不混字段（既有 route.py 约束，未改动）
