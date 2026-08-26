# Changelog

## v2.0（2026-08-03）

- **真源归并**：invest-stock 与 invest-institutional 的 6 个重复 references（1526 行）收敛到 `_shared/references/`，两成员改为引用共享路径
- **接入 invest-analyst**：路由表 + 图谱新增「IC报告/电话会/一致预期/主题策略 → invest-analyst」
- **任务后导航**：新增「结论信号 → 下一步」导航表（仿 dbs 的闭环设计）
- **维护机制**：新增维护段落（版本/共享方法论/归档记录）
- **清理过期引用**：invest-us 删除对不存在的 invest-report 的引用

## v1.1

- 纯路由入口，覆盖股基债商+配置+圆桌+机构深度分析
