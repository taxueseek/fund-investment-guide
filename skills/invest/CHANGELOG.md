# Changelog

## v2.5（2026-09-21 · 第二轮：判据层修复 + 路由惰性探测 + 缓存自清）

本轮接着 v2.4 的实测方法重跑一遍，找到的都是「v2.4 之后才暴露或上轮没看到」的项。
完整报告见 `docs/审查报告_2026-09-21_第二轮.md`。

- **最大性能收益：路由探测改为惰性（`sources/route.py`）**。v2.4 之前的 `fetch`
  先 `pick()` 一次性探测整条链，于是每次查 A 股都要为末位兜底的 yfinance
  付一次真实 HTTPS 探测（实测 0.5s），wind 目录探测也白付。现在 `candidates()`
  只做便宜的能力判定（coverage + 真有方法），`fetch` 在**即将调用某个源之前**
  才 `detect()`，主源命中就不再碰兜底源。隔离实测：A 股路由探测段
  **0.515s → 0.007s（73x）**；`stock 600519` 冷路径 **1.52s → 0.51s**。
  `pick()` 保留给 `datasources` / `chains()` 这类「一次看清全链可用性」的场景。
- **hithink 利润表不再请求两次（`sources/hithink.py`）**。v2.4 为拿年报年份先发一次
  `income-statements limit=1` 预览，而批里又有 `limit=5` 的同一端点。现在按年报
  披露规律直接猜财年（5 月起 year-1，1-4 月 year-2）并把 indicators 放进同一批；
  猜错时用批里拿到的真实年份补一次（新增守卫）。A 股冷路径再省一段 RTT。
- **一处修复消灭一类：中文名被判成美股代码（`cmd_intent.classify`）**。
  Python 里汉字也是 `isalpha()`，旧判据 `t.isalpha() and 1<=len(t)<=5` 对
  「茅台」「腾讯」为真，`intent deep 茅台` 会去 Yahoo 找「茅台」（实测 3.2s 白付）。
  判据改为 `t.isascii()`。
- **一处修复消灭一类：盈米名称模糊匹配把股票判成基金（`_is_fund_by_yingmi`）**。
  GuessFundCode 是子串式匹配，实测「中国平安」→「华银平安中国主题灵活配置混合」、
  「招商银行」→「银叶投资-招商银行-宁海工业园1号」。判据从「盈米返回了东西」
  改为「返回的基金名与查询确有对应」（前缀，或查询占基金名 60% 以上）；
  另对 ≤2 字短名不做模糊匹配。19 个常见股票/基金名分类全部正确。
- **一处修复消灭一类：空标的打满整条链（`sources/route.py`）**。
  `stock ""` / `fund ""` / `us ""` / `screen ""` 现在在取数前就被拦下并给一句
  明确中文（原来要 0.1–3.5s、拼三句多源错误）。
- **一处修复消灭一类：上游 data.data 为 null 时抛裸异常（`cmd_screen.py`）**。
  `screen ""` 曾直接抛 `TypeError: 'NoneType' object is not subscriptable`（用户看到
  traceback）。现在逐层容错，`securityCount` 缺失/为 null 按 0 算。
- **缓存自清，磁盘不再无界增长（`_common.py`）**。TTL 只决定读时是否命中，
  不删文件；`sec` 的 companyfacts 单文件约 3.7MB，按查过的公司数无限累积。
  新增 `CACHE_MAX_AGE`（7 天）与写时清理（含残留 `.tmp`），进程内每命名空间一次。
  另清理 7 个 v2.4 重构前的 SEC 旧命名孤儿文件（实测释放 13MB，本机 24M → 11M）。
- **argo 非零退出的原因不再只有 traceback 表头（`sources/argo.py`）**。
  stderr 取最后一行非空内容，用户看到的是真实异常行。
- **`intent deep <type>` 缺标的给出明确报错**，`commodity`/`gold` 是固定场景不受影响
  （反向对照守卫）。
- **回归守卫 156 → 171 passed**，新增 15 条：CJK 分类、盈米误配、短名不模糊匹配、
  缺标的报错、空标的拦截、惰性探测与反向对照、整链不可用措辞不变、缓存清理与阈值有限、
  选股 null 回包与缺失计数、利润表单次请求、财年猜测边界、猜错财年的 fallback、
  argo 取最后一行原因。

## v2.4（2026-09-21 · argo 协作纠偏 + 热路径性能）

本轮从第一性原理重测 invest-cli 的日常耗时与错误形态，全部结论以实机测量为依据。
完整报告见 `invest-cli/docs/性能与缺陷治理报告_2026-09-21.md`。

- **argo 协作三处纠偏（正确性 + 能力解锁）**：`sources/argo.py` 的本地引擎白名单已删除。
  - `cn-web-search` 早已不在 argo 的引擎表里，旧实现把它当合法引擎，用户拿到
    「0 结果 + ok=true」的**静默空答复**；现在以 argo 自己的 `--list-engines`
    清单（磁盘缓存 1h）为准，在发起检索之前就拦下并给出可执行的清单命令。
    注：第一版判据是读 argo stderr 的 `未知引擎`，**第二次同 query 就会失效**
    （argo 命中自身缓存后不再解析引擎，stderr 变空），故改为清单校验，stderr 仅作兜底。
  - 白名单外的合法引擎（如 `anysearch`）会被**静默替换**成 eastmoney；现在引擎名原样透传。
  - `--max-results` 未透传，`limit>5` 被 argo 默认值静默截断；现已透传。
  - 无结果时的原因改为引用 argo 信封里的 `errors`（不再本地猜「缺 key」）。
  - 净删常量与分支，可用引擎从 20 个变成 argo 全部 250+ 个。
- **热路径性能**：
  - `fund` 深取（ttskill 两次子进程，实测 1.0–1.3s）此前**从不缓存**，主快照命中缓存后仍每次重付；
    现按 1h 落盘缓存，只缓存成功结果。热路径 **0.985s → 0.104s（9.5x）**。
  - FRED 四条序列此前串行取数（实测网络段 1.958s）；现并发 + 30min 缓存。
    `intent macro` **2.380s → 0.076s 热 / 0.889s 冷**。
- **低级 bug 修复**：
  - `us <未知代码>`：yfinance 返回非空但无内容的 `info`（`{'trailingPegRatio': None}`）
    会造成全 None 的静默假成功，`history` 还会抛库内 TypeError；现由实体守卫转成明确中文错误。
    守卫**刻意不含 `symbol`/`currency`**，因为它们是请求侧原样回显的。
  - yfinance 把原始 HTTP 响应体经 root logger 打进 stderr；现压到 CRITICAL。
  - `us BRK.B`（类别股点号写法）此前返回空壳快照；现按**事实**回退到 `BRK-B` 取真实数据。
    注意**不做**字符串形状改写：点号也可能是交易所后缀（`VOD.L` 伦敦、`VOW3.F` 法兰克福），
    按形状改会打断它们（中间版本实测打断过 `us VOD.L`，已纠正）。
  - `screen` 的「还有 N 条结果」按固定 15 算，17 条结果时说「还有 2 条」（实际少 7 条）；
    现按实际打印行数算。
  - 缓存临时文件共用 `<name>.tmp`，跨进程写同一键时会互相截断并丢缓存；现按 pid 分名（两处）。
  - 自选股从 `~/.cache/invest-cli/` 迁到 `state_root()`（默认 `~/.config/invest-cli/`，
    可用 `INVEST_CLI_STATE_DIR` 覆盖）：用户数据不该放会被系统清理的缓存目录。旧文件自动迁移。
  - FRED 宏观缓存此前「部分失败也写」，会把缺一条序列的半成品固定 30 分钟；现只在四条全成时写。
  - `fred.liquidity(use_cache=False)` 此前只绕过读、仍然写，测试 mock 会污染生产缓存
    （实测发生过）；现改为不读也不写，`test_fred.py` 另加缓存目录隔离。
- **文档纠偏 3 处**：`--engine` 的引擎示例、`intent macro` 的取数顺序（FRED 优先，nbs_stats 兜底）、
  `screen` 的作用域（只筛股票，基金条件走 `intent screen`）。
- **回归守卫**：全仓测试 129 → 156 passed。测试按不变式拆成三个模块
  （`test_perf_guards.py` 427 行 / `test_source_guards.py` 700 行 / `test_cli_guards.py` 126 行）：
  原单文件 1235 行已越过 1000 行，且混装了探测判据、数据源契约、CLI 输出三类关注点。
  缓存/状态目录隔离与探测缓存清空提到 `conftest.py`，**对所有测试文件生效**
  （不再依赖每个新测试文件作者记得加夹具）。新增 26 条守卫中 15 条经红绿验证，
  5 条为反向对照，6 条为新增能力（对应场景均在修复前用活数据复现过）。
- **严格可维护性复查**：删掉仪式性代码而非美化它（argo 从 stderr 解析引擎名、
  其值与入参恒等）；把无捕获的闭包 `_deep_fetch`、内联的并发取数、内联的读时迁移、
  内联的类别股回退分别提成具名步骤（`_ttskill_deep` / `_collect_series` /
  `_migrate_legacy` / `_resolve_snapshot`），主函数回到单一职责。
  另把内联在入口 `invest_cli.py` 里的 72 行选股排版挪回 `cmd_screen.py`——
  兄弟命令都各自成模块，入口只该做 argparse + 分发（330 → 263 行）。
- 本轮改动经独立审查者对抗复核，其找到的 1 个 P0、2 个 P1 全部成立并已修
  （详见报告第八节），另修正两处测试卫生问题。

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
