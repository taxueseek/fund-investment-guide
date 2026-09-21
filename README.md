# Invest 系列：投资分析指南

买基金像请管家，买股票像合伙做生意。不懂的人、不靠谱的人、要价太高的人，都不能托付。

这个工具帮你三件事：**看清投的是什么，判断值不值得投，确定价格合不合适**。

---

## 快速安装，输入下列指令即可开始使用

```bash
npx skills add taxueseek/fund-investment-guide
```

安装后直接问 Claude：
- "这只基金怎么样？"
- "分析一下茅台"
- "黄金能买吗？"
- "让大师们看看这只股"

系统会自动识别你要分析什么，进入对应的分析流程。

> **注意**：这个工具只是帮你理清思路，不是投资建议，也不保证赚钱。用它分析后，买不买都是你自己的决定。

---

## 可选：配置数据源（配置后启用对应能力）

装上就能用**判断框架**。不配任何 API 也能分析（公开检索 + 你提供的材料）。

按需配置后，**对应取数能力才会启用**；取数与下判断分离：

| 你配置了 | 启用的能力 |
|:---------|:-----------|
| （什么都不配） | 判断框架 + 公开检索；另有三条免 Key 取数：`invest-cli sec`（SEC 财报原文）、`invest-cli us`（装 yfinance 即可）、`invest-cli intent macro`（FRED 免 Key 通道） |
| 同花顺金融数据服务 `HITHINK_FINANCE_API_KEY` | `invest-cli stock` / `fund` 的 A 股与公募主路（快、字段全） |
| 东方财富 `EASTMONEY_APIKEY` | A 股/港股快照、基金快照、自然语言选股；港股必经此路 |
| Python 包 `yfinance` | `invest-cli us` 美股快照（行情+财务+评级） |
| 官方 `ttskill`（天天基金，可选） | `fund` 快照的深取补充（同类分位/机构占比/经理在管）；未登录自动跳过 |
| [argo](https://github.com/taxueseek/argo)（可选） | `invest-cli info` 资讯/舆情、`intent macro` 宏观走财经垂直源，多数免 Key，省结构化源配额 |

**取数与判断分离**：数据层只负责「把数取回来并标明来源」，判断由 `invest-*` 框架完成。
**零配置也能跑**：不配任何 Key，仍可用 `sec`（SEC EDGAR 官方）、`us`（yfinance）、`intent macro`（FRED）三条免 Key 通道。

**和 argo 的分工**：盈米 / Wind / 同花顺 / 东财管「精确数值」，argo 管「检索资讯」——资讯、舆情、宏观背景优先走 argo 省配额，结构化源失败时也由它兜底（结果需核验）。argo 是可选项，没装则自动跳过，不影响其他能力。

**引擎名不再由 invest-cli 维护白名单**：argo 自带 250+ 引擎且随版本演进，本地名单必然漂移（曾出现名单里的引擎已不存在 → 用户拿到「0 结果 + ok=true」的静默空答复）。现在引擎名原样透传，传错会明确报错并给出清单命令。

详细步骤与排错见 **[docs/data-sources.md](docs/data-sources.md)**。

密钥只放本机环境变量或官方安全存储，不要提交到 Git。本仓库不提供券商交易，也不捆绑第三方基金聚合站 skill。

---

## 这到底是什么

不是纯数据查询工具，是一套**判断框架**（可选取数后端）。

投资最大的坑，不是信息不够，是**不知道该看什么**。这个工具告诉你：看这三样就够了。

```
用户提问
    │
    ▼
┌─────────────┐
│  invest     │  ← 识别你要分析什么
│  主入口     │
└──────┬──────┘
       │
       ├──────────┬──────────┬──────────┬──────────┬──────────┐
       ▼          ▼          ▼          ▼          ▼          ▼
   ┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐
   │ 股票  │  │ 基金  │  │可转债 │  │商品   │  │REITs  │  │资产   │
   │三关   │  │场景   │  │三关   │  │三关   │  │三关   │  │配置   │
   │+深度  │  │路由   │  │审查   │  │审查   │  │审查   │  │       │
   └───┬───┘  └───┬───┘  └───┬───┘  └───┬───┘  └───┬───┘  └───┬───┘
       │          │          │          │          │          │
       └──────────┴────┬─────┴──────────┴──────────┴──────────┘
                       ▼
               ┌───────────────┐
               │  三关审查     │
               │               │
               │ 1. 懂不懂？   │  ← 能力圈/策略理解
               │ 2. 好不好？   │  ← 护城河/持续性
               │ 3. 贵不贵？   │  ← 安全边际/估值
               └───────────────┘
```

---

## 能分析什么

| 你要分析 | 路由到 | 核心问题 | 适用市场 |
|:--------|:-------|:---------|:---------|
| 某只股票 | invest-stock | 懂生意吗？有护城河吗？价格合适吗？ | A股、港股、美股 |
| 某只基金 | invest-fund | 懂策略吗？能跑赢吗？成本合理吗？ | 主动基金、ETF、QDII |
| 可转债/黄金原油/REITs/债券 | invest-asset | 债券：偿付+利差+位置；可转债：条款+债底+溢价；商品：逻辑+位置+波动；REITs：底层+运营+估值 | 债市/大宗/国内外REITs |
| 整体配置 | invest-allocation | 股债比例合理吗？再平衡了吗？ | 跨资产组合 |
| 市场温度/流动性 | invest-macro | 钱紧不紧？市场过热吗？ | 全球流动性、美股情绪、加密底部 |
| 出研报/纪要/日报 | invest-analyst | IC 研报、电话会纪要、一致预期、行业深度、市场日报 | 机构级内容产出 |
| 拿不准？ | invest-discuss | 让多种投资思维同时审视 | 任何标的 |
| `/cli` 分析 | invest-cli | 终端数据获取 + 分析框架 | A股/港股/美股/基金 |

---

## 三关审查是什么

投资分析最怕什么？**该看的没看，不该看的看了太多**。

这三关把复杂的投资决策，拆成三个必答题：

### 第一关：懂不懂

不懂的东西，涨跌你都拿不住。

- 股票：这家公司怎么赚钱？客户为什么选它？
- 基金：投的是什么？策略是什么？基准是什么？
- 可转债：条款看明白了吗？下修、回售、强赎什么意思？

**这一关掉链子，直接放弃。** 不懂的不碰。

### 第二关：好不好

好东西才能持续赚钱。

- 股票：有定价权吗？ROE能持续>12%吗？现金流好吗？
- 基金：长期跑赢基准吗？经理稳定吗？风险调整后收益如何？
- 商品/REITs：底层资产质量如何？分派/收益可持续吗？

**这一关掉链子，说明是平庸标的，不值得花时间。**

### 第三关：贵不贵

再好的东西，买贵了也难受。

- PE/PB在历史什么分位？
- 如果跌30%，能承受吗？
- 现在入场，安全边际够吗？

**这一关掉链子，不是不买，是等更好的时机。**

---

## v2.5 增量：性能与判据层修复（本版）

本版不增加功能，只做两件事：**把日常取数的固定开销降下来，把「判据落在错误的层」这类缺陷修掉**。

### 性能：路由改为惰性探测（最大一笔）

旧实现在建链时**一次性探测整条链**，于是每次查 A 股都要为末位兜底的 yfinance 付一次真实 HTTPS 探测，wind 目录探测也白付。现在只做便宜的能力判定，在**即将调用某个源之前**才探测可用性；主源命中就不再碰兜底源。

| 指标（同机、清空缓存后实测） | 修改前 | 修改后 | 幅度 |
|:---|---:|---:|---:|
| A 股路由探测段（隔离） | 0.53s | **0.012s** | 约 44x |
| `stock 600519` 冷路径 | 1.52s | **0.51–0.60s** | 约 2.6x |
| `fund 110011` 冷路径 | 2.30s | **1.24–1.45s** | 约 1.7x |
| 查 A 股触发的探测次数 | 4 | **1** | — |
| 热路径（缓存命中） | 0.11–0.13s | 0.11–0.13s | 不变（已是地板） |

另去掉一处重复请求：hithink 利润表曾为拿年报年份先发一次 `limit=1` 预览，而批里本来就有同端点的 `limit=5`；现在按年报披露规律直接定位财年，猜错再补一次。

### 正确性：四处「判据选错层」

- **中文名被判成美股代码**：Python 里汉字也是 `isalpha()`，`intent deep 茅台` 会去 Yahoo 找「茅台」（实测 3.2s 白付）。判据改为 ASCII 字母。
- **盈米模糊匹配把股票判成基金**：`GuessFundCode` 是子串式匹配，「中国平安」→「华银平安中国主题灵活配置混合」、「招商银行」→「银叶投资-招商银行-宁海工业园1号」。判据从「盈米返回了东西」改为「返回的基金名与查询确有对应」。
- **空标的打满整条链**：`stock ""` 实测 3.55s 后拼出三句多源错误；现在在入口拦下，0.05s 给一句中文。
- **上游 `data.data=null` 抛裸异常**：`screen ""` 曾直接抛 `TypeError` 并打出 traceback。

### 资源：缓存不再无界增长

TTL 只决定「读时是否命中」，不删文件；SEC 的 companyfacts 单文件约 3.7MB，按查过的公司数无界累积。新增 7 天上限与写时清理，本机实测缓存目录 24MB → 11MB。

### 回归守卫

测试从 156 条增至 **171 条**，新增的每条都对应一个真实发生过的行为（含反向对照，防止「修成一律拒绝」）。

## v2.4 增量

- **argo 协作纠偏**：删除本地引擎白名单，改为向 argo 要一次合法引擎清单再校验。旧白名单里有一个早已不存在的引擎，用户拿到的是「0 结果 + ok=true」的静默空答复；同时合法引擎会被静默换成 eastmoney、`--max-results` 未透传。修完净删代码，可用引擎从 20 个变成 argo 全部 250+ 个。
- **热路径性能**：`fund` 深取（ttskill 两次子进程）此前从不缓存，主快照命中缓存后仍每次重付，**0.985s → 0.104s（9.5x）**；FRED 四条序列由串行改并发并加缓存，`intent macro` **2.380s → 0.076s 热 / 0.889s 冷**。
- **美股三条失态**：未知代码的「非空但全 None 假成功」、yfinance 库内 TypeError 外泄、原始 HTTP 响应体污染 stderr，全部归一为明确中文错误；类别股 `BRK.B` 按**事实**回退到 `BRK-B`（不按字符串形状改写，避免打断 `VOD.L` 这类交易所后缀）。
- **缓存原子性**：临时文件名带 pid，消灭「多进程共用同一个 .tmp 互相截断」这一类；自选股从缓存目录迁到用户数据目录（缓存会被系统清理）。

## v2.3 增量

- **消融式维护**：注册链 9/9 对齐（清 3 条死链）、死路由清理、命令路径统一（禁止写死个人家目录）、`watchlist` 隐藏能力文档化。
- **判定原则**：只处理经实验证据证明有价值或损坏的项，删无可证明必要性的复杂度。

## v2.2 增量

- **薄单品种四合一**：invest-bond / invest-convertible / invest-commodity / invest-reit → invest-asset（同一「三关审查」骨架 × 四种资产参数；注册数 12→9）
- **资产细则下沉**：债券/可转债/商品（含黄金十维度）/REITs 的专属三关、指标表、一票否决、时间定位、输出模板，收敛到 `skills/invest-asset/references/asset-*.md` + `commodity-gold.md`
- **数据措辞统一**：残留 `ttfund bond` / `ttfund gold` 老 CLI 措辞改为 `intent deep bond` / `intent deep commodity`（官方 TTFUND_GOLD_INFO 已封装进 intent）
- **invest-cli 演进同步**：退役 cmd_ttfund.py / ttfund.py，接入 ttskill 官方源 + hithink/bitget/route 回退链与契约测试（本地 09-03 多笔修复：hithink 部分失败整单回退、探测缓存等一并入包）
- **引用面消毒**：invest 入口路由/图谱、README、CHANGELOG、macro/allocation/analyst 分工表全部改指 invest-asset；历史原文见本地 `~/.claude/skills-archive/2026-09-03_merged-invest-asset/`

## v2.0.5 增量

- **配置门闩**：东财 Key / yfinance / 可选 ttfund 探测通过后，才启用对应 CLI 取数
- **invest-cli 加固**：路径可移植、字段别名、JSON 契约、易方达蓝筹映射 **005827**、友好「如何启用」报错
- **数据源文档**：`docs/data-sources.md`（东财 + 美股 + 天天基金引导）
- **路由消毒**：公开包仅 9 件套框架 + invest-cli；死链 skill 清理

## v2.0 功能亮点

### 个股分析统一入口

原来 A股、港股、美股分别用不同 skill，现在统一为 `invest-stock`：

| 能力 | 说明 |
|:-----|:-----|
| 三关审查 | 默认模式，A股/港股通用 |
| 四维评分 | 美股自动切换，ROE/负债/FCF/护城河 → A-D评级 |
| 机构深度 | 说"深度分析"进入，DCF估值+同行比较+IC Memo |
| 港A增强 | A股/港股自动附加政策敏感度、AH溢价、南北资金流检查 |

### 基金分析场景路由

不再一套流程走到底，根据你的问题自动选路径：

| 场景 | 触发 | 核心判断轴 |
|:-----|:-----|:-----------|
| 同经理多选一 | "张坤的几只基金选哪个" | 选最像经理本人的那只（管理时间最长/规模适中/机构占比高） |
| 跨基金横向对比 | "A基金和B基金哪个好" | 多维度对比打分 |
| 行业主题 | "新能源基金怎么样" | 经理-行业匹配度 > 行业β |
| 次新基金 | "这只新基金能买吗" | 经理推断 + 公司基因 |
| ETF | "沪深300ETF" | 费率 + 跟踪误差 + 流动性 |
| 标准体检 | "这只基金怎么样" | 完整三关审查 |

### 大师会诊

四种投资思维同时审视一个标的，暴露单一视角的盲区：

| 视角 | 核心问题 |
|:-----|:---------|
| 生意视角 | 懂这门生意吗？有护城河吗？ |
| 趋势视角 | 价格反映了多少乐观？有催化剂吗？ |
| 配置视角 | 占多少仓位？能承受多大回撤？ |
| 反向视角 | 最可能亏钱的三个场景？ |

支持两档深度：快速扫描（默认）和深度质问（重仓前自检）。

### 投资分析 CLI

终端直接取数，输出快照或 JSON（统一入口 `invest-cli`；PATH 无该命令时用 `"$HOME/.local/bin/invest-cli"` 兜底）：

```bash
invest-cli stock 600519          # A股/港股：行情 + 估值 + 五年财务
invest-cli fund 110011           # 基金：净值/业绩/回撤/费率/经理/重仓
invest-cli us AAPL               # 美股：估值 + 财务 + 评级
invest-cli sec AAPL              # 美股财报原文（SEC EDGAR，免费无 Key）
invest-cli screen "市盈率低于10的银行股"   # 自然语言选股
invest-cli intent macro          # 宏观：净流动性三序列（免 Key 通道）
invest-cli info 茅台             # 资讯/舆情（走 argo）
invest-cli datasources           # 排查「为什么没数据」：各源可用性与默认快照链
```

加 `--json` 输出结构化数据给 Agent 解读；不加则输出终端表格。同一问题不混源，单个源失败整单回退到下一个，并在结果里标明来源。

---

## 跟普通分析有什么区别

| 普通做法 | 这个工具 |
|:---------|:---------|
| 给一堆数据，让你自己判断 | 告诉你该看什么，不该看什么 |
| 预测明天涨不涨 | 不预测，只评估"值不值得持有" |
| 复杂的评分体系 | 简单的通过/未通过/观望 |
| 手动更新年份数据 | 自动计算当前该看什么报告 |
| 只看收益率 | 看风险调整后收益（夏普、卡玛比率）|
| 单只产品分析 | 支持资产配置视角 |

---

## 设计理念

### 1. 大道至简

投资不需要复杂的模型。巴菲特看企业就看三点：懂不懂、好不好、便不便宜。这个工具把这个思路扩展到所有资产类型。

### 2. 不替决策

工具只提供分析框架，决策权完全交还给你。不告诉你"买"或"卖"，只告诉你"这一关过了吗"。

### 3. 动态时间

不用手动改年份。输入当前日期，自动算出该看N年报告还是N-1年报告，数据新鲜度是多少。

### 4. 大师视角

拿不准的时候，启动投资圆桌。让生意视角、趋势视角、配置视角、反向视角四种思维同时审视同一个标的，发现你自己看不到的盲区。

---

## 实际使用示例

### 分析一只股票

```
你：分析一下腾讯 00700

系统：分析腾讯(00700)，进入invest-stock。

三关审查结果：

| 关卡 | 结果 | 关键发现 |
|------|------|----------|
| 懂不懂 | 通过 | 游戏+广告+投资，三块业务清晰 |
| 好不好 | 通过 | 护城河深厚，ROE持续>15%，现金流充沛 |
| 贵不贵 | 观望 | PE在历史70%分位，安全边际不足 |

综合判断：等估值回落到PE<25再考虑。
```

### 分析一只基金

```
你：张坤的基金怎么样？

系统：分析张坤的基金，进入invest-fund。

关键发现：
- 代表作管理5年+，穿越牛熊周期
- 重仓股重合度>80%的几只基金，选费率最低的
- 当前规模>100亿，灵活性受限，超额收益可能下降

建议：如果是张坤的粉丝，选他管理时间最长的代表作。
```

### 资产配置检视

```
你：我的资产配置合理吗？

系统：进入invest-allocation。

战略配置建议（基于你能承受20%回撤、投资期限5年+）：
- 股票：60%
- 债券：30%
- 商品：10%

再平衡规则：
- 每季度检查一次
- 某类资产偏离目标±5%时触发再平衡

当前你的组合偏离：股票超配15%，建议减仓股票或增配债券。
```

### 投资圆桌

```
你：让大师们看看茅台

系统：启动大师会诊，四种视角并行扫描。

生意视角：茅台是理想生意，品牌护城河罕见，定价权极强...
趋势视角：当前价格包含太多乐观预期...
配置视角：如果仓位>10%，波动风险需关注...
反向视角：最可能亏钱的场景是...

共识：生意模式顶级，但当前价格安全边际不足。
```

---

## 使用之前，你要知道

这个工具像字典——帮你认字，但不替你写作文。具体来说：

**第一，盈亏自负。** 这个工具不会告诉你买哪只股、卖哪只基金，也不保证你能赚钱。用它分析后，买不买、买多少，都是你自己的决定，赚了亏了都自己承担。

**第二，信息有限。** 这个工具会尽量用最新的公开数据，但数据可能滞后、可能有错。它给你的只是参考，不是标准答案。

**第三，不能替代专业建议。** 如果你有大额投资需求，应该咨询持牌的投资顾问，而不是依赖一个AI工具。

**一句话：工具只是帮你理清思路，决策在你，风险自担。**

---

## 项目结构

```
docs/
└── data-sources.md            # 可选数据源：配置后启用
skills/
├── invest/                    # 主入口：自动识别标的类型
├── invest-stock/              # 个股分析（三关审查/四维评分/机构深度/港A增强）
├── invest-fund/               # 基金分析（场景路由）
├── invest-asset/              # 单品种资产：债券/可转债/商品（含黄金十维度）/REITs
├── invest-allocation/         # 资产配置
├── invest-macro/              # 宏观与市场环境（流动性/情绪/底部信号）
├── invest-discuss/            # 大师会诊（多视角验证）
├── invest-analyst/            # 机构级内容产出（IC 研报/纪要/一致预期/日报）
└── invest-cli/                # 数据层：CLI + 多源适配器 + 回归测试
    └── docs/                  # 数据源说明 + 性能与缺陷治理报告（实测数据与复现方式）
```

---

## 版本更新记录

| 版本 | 日期 | 变更内容 |
|:-----|:-----|:---------|
| v2.5 | 2026-09 | 路由惰性探测（A 股探测段 0.53s→0.012s，`stock` 冷路径 1.52s→0.51s）；去重复利润表请求；修四处判据错层（中文名误判美股/盈米误配基金/空标的打满整链/`screen` 裸异常）；缓存 7 天上限自清（本机 24MB→11MB）；回归 156→171 |
| v2.4 | 2026-09 | argo 引擎清单不再本地维护（可用引擎 20→250+，修静默空答复）；`fund` 深取缓存（0.985s→0.104s）、FRED 并发+缓存（2.380s→0.076s 热）；美股未知代码/类别股/日志污染三类失态修复；缓存原子写（tmp 带 pid）；自选股迁出缓存目录 |
| v2.3 | 2026-09 | 消融式维护：注册链 9/9 对齐（清 3 条死链）、死路由清理、命令路径统一、`watchlist` 文档化 |
| v2.2 | 2026-09 | 薄单品种四合一：invest-bond/convertible/commodity/reit → invest-asset（同一三关骨架×四资产参数，注册数 12→9）；invest-cli 退役 `ttfund`、接入 ttskill 官方源与 hithink/bitget/route 回退链；引用面消毒 |
| v2.0.5 | 2026-08 | 统一多源数据层（invest-cli 接入 Wind/盈米/东财/yfinance/天天基金 + argo 财经垂直源；intent 意图层收敛接口面、datasources 探测）；新增 invest-bond/invest-macro；黄金十维度并入 invest-commodity；合并 invest-hk-a/us/institutional 进 invest-stock |
| v2.0.2 | 2026-07 | 配置门闩 + 数据源引导（东财/yfinance）；invest-cli 工程加固；公开路由消毒与死链清理 |
| v2.0 | 2026-06 | 统一框架升级：invest-stock 合并原 invest-hk-a/invest-us/invest-institutional，invest-fund 新增场景路由，新增 invest-discuss/invest-cli，移除 invest-report/invest-fund-manager 等 |
| v1.0 | 2026-04 | 全面重构，统一三关审查框架，覆盖股基债商+配置+圆桌 |

---

如果这个项目对你有帮助，欢迎点个 Star。

---

* * *

## English Version

# Invest Series: Investment Analysis Guide

Buy funds like hiring a steward, buy stocks like partnering in business. Don't trust people you don't understand, who are unreliable, or who charge too much.

This tool helps you with three things: **see what you're investing in, judge whether it's worth it, determine if the price is right**.

---

## Quick Start

```bash
npx skills add taxueseek/fund-investment-guide
```

After installation, just ask Claude:
- "How is this fund?"
- "Analyze Moutai"
- "Can I buy gold?"
- "Let the masters take a look at this stock"

The system automatically identifies what you want to analyze and routes to the corresponding analysis flow.

> **Note**: This tool only helps you think clearly. It's not investment advice and doesn't guarantee profits. After using it to analyze, buying or selling is entirely your own decision.

---

## Optional: Configure data sources (capabilities unlock after setup)

The **judgment framework works immediately** without any API.

Configure sources as needed; **structured fetch enables only after config**:

| You configure | Unlocks |
|:--------------|:--------|
| (nothing) | Judgment framework + public search; plus three keyless fetch paths: `invest-cli sec` (SEC filings), `invest-cli us` (install yfinance), `invest-cli intent macro` (FRED keyless) |
| Hithink `HITHINK_FINANCE_API_KEY` | Primary A-share / public-fund snapshot path for `invest-cli stock` / `fund` |
| Eastmoney `EASTMONEY_APIKEY` | A/HK snapshot, fund snapshot, natural-language screening; required for HK |
| Python `yfinance` | `invest-cli us` (quote + financials + analyst) |
| Official `ttskill` (TTFund, optional) | Extra fund fields (peer percentile / institutional ratio / manager AUM); auto-skipped if not logged in |
| [argo](https://github.com/taxueseek/argo) (optional) | `invest-cli info` news/sentiment, `intent macro` via finance vertical sources; mostly keyless, saves structured quota |

**Fetch and judgment are separate**: the data layer only retrieves numbers and labels the source; the `invest-*` frameworks make the call.
**Zero-config still works**: without any key you can still use `sec` (SEC EDGAR), `us` (yfinance) and `intent macro` (FRED).

**Division of labor with argo**: YingMi / Wind / Hithink / Eastmoney handle precise numbers, argo handles retrieval. Engine names are passed through verbatim — invest-cli keeps no local allow-list (it always drifts), so a wrong engine errors out with the command to list valid ones instead of silently returning an empty result.

---

## What This Is

Not only a data tool — a **judgment framework** (optional data backends).

The biggest pitfall in investing isn't lack of information, it's **not knowing what to look at**. This tool tells you: these three things are all you need to check.

```
User Question
    │
    ▼
┌─────────────┐
│  invest     │  ← Identifies what you want to analyze
│  Entry      │
└──────┬──────┘
       │
       ├──────────┬──────────┬──────────┬──────────┬──────────┐
       ▼          ▼          ▼          ▼          ▼          ▼
   ┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐
   │ Stocks│  │ Funds │  │Convert│  │Commod │  │ REITs │  │Asset  │
   │3-Gate │  │Scene  │  │3-Gate │  │3-Gate │  │3-Gate │  │Alloc  │
   │+Deep  │  │Route  │  │Review │  │Review │  │Review │  │       │
   └───┬───┘  └───┬───┘  └───┬───┘  └───┬───┘  └───┬───┘  └───┬───┘
       │          │          │          │          │          │
       └──────────┴────┬─────┴──────────┴──────────┴──────────┘
                       ▼
               ┌───────────────┐
               │  3-Gate Review│
               │               │
               │ 1. Understand?│  ← Capability circle / Strategy
               │ 2. Good?      │  ← Moat / Sustainability
               │ 3. Cheap?     │  ← Margin of safety / Valuation
               └───────────────┘
```

---

## What You Can Analyze

| You want to analyze | Routes to | Core Question | Applicable Markets |
|:--------------------|:----------|:--------------|:-------------------|
| A specific stock | invest-stock | Understand the business? Moat? Right price? | A-shares, HK stocks, US stocks |
| A specific fund | invest-fund | Understand the strategy? Can beat benchmark? Cost reasonable? | Active funds, ETFs, QDII |
| Convertible bonds / Gold & Oil / REITs / Bonds | invest-asset | Bonds: solvency+spread+position; Convertibles: terms+floor+premium; Commodities: logic+position+volatility; REITs: assets+operations+valuation | Bond market / Commodities / REITs |
| Overall allocation | invest-allocation | Stock-bond ratio reasonable? Rebalanced? | Cross-asset portfolio |
| Market temperature / liquidity | invest-macro | Is money tight? Is the market overheated? | Global liquidity, US sentiment, crypto bottom signals |
| Research note / minutes / daily | invest-analyst | IC memo, earnings-call minutes, consensus, industry deep-dive, daily report | Institutional-grade output |
| Not sure? | invest-discuss | Let multiple investment minds examine together | Any target |
| `/cli` analysis | invest-cli | Terminal data fetch + analysis framework | A/HK/US stocks, funds |

---

## What is the 3-Gate Review

What's the biggest fear in investing? **Looking at what you shouldn't, missing what you should**.

These three gates break complex investment decisions into three must-answer questions:

### Gate 1: Do You Understand?

If you don't understand it, you can't hold it through ups and downs.

- Stocks: How does this company make money? Why do customers choose it?
- Funds: What does it invest in? What's the strategy? What's the benchmark?
- Convertible bonds: Do you understand the terms? Put, call, reset — what do they mean?

**Fail this gate: abandon directly.** Don't touch what you don't understand.

### Gate 2: Is It Good?

Only good things can sustain returns.

- Stocks: Pricing power? ROE consistently >12%? Good cash flow?
- Funds: Beats benchmark long-term? Manager stable? Risk-adjusted returns good?
- Commodities/REITs: Underlying asset quality? Distribution/earnings sustainable?

**Fail this gate: it's a mediocre target, not worth your time.**

### Gate 3: Is It Cheap?

Even good things hurt if you buy expensive.

- PE/PB at what historical percentile?
- If it drops 30%, can you handle it?
- Is there margin of safety entering now?

**Fail this gate: not don't buy — wait for a better time.**

---

## v2.0 Feature Highlights

### Unified Stock Entry

Previously A-shares, HK stocks, and US stocks used separate skills. Now unified into `invest-stock`:

| Capability | Description |
|:-----------|:------------|
| 3-Gate Review | Default mode, A-shares/HK stocks |
| 4-Dimension Score | Auto-switches for US stocks, ROE/Debt/FCF/Moat → A-D rating |
| Institutional Deep | Say "deep analysis" to enter, DCF + comparable company + IC Memo |
| HK-A Enhancement | Auto-adds policy sensitivity, AH premium, north/south flow for A/HK stocks |

### Fund Scene Routing

No longer one-size-fits-all. Auto-selects path based on your question:

| Scene | Trigger | Core Judgment Axis |
|:------|:--------|:-------------------|
| Same manager, multiple funds | "Which of Zhang Kun's funds to pick" | Pick the one most like the manager |
| Cross-fund comparison | "Which is better, Fund A or B" | Multi-dimensional comparison scoring |
| Industry theme | "New energy fund" | Manager-industry fit > industry beta |
| New fund | "Is this new fund worth buying" | Manager inference + company DNA |
| ETF | "CSI 300 ETF" | Expense ratio + tracking error + liquidity |
| Standard checkup | "How is this fund" | Full 3-gate review |

### Masters Discussion

Four investment minds examine the same target simultaneously:

| Perspective | Core Question |
|:------------|:--------------|
| Business | Understand this business? Has a moat? |
| Trend | How much optimism is priced in? Any catalyst? |
| Allocation | What position size? Can handle how much drawdown? |
| Contrarian | Three most likely scenarios to lose money? |

### Investment Analysis CLI

Terminal fetch, table or JSON (`invest-cli` entry point; fall back to `"$HOME/.local/bin/invest-cli"` if not on PATH):

```bash
invest-cli stock 600519          # A/HK: quote + valuation + 5y financials
invest-cli fund 110011           # Fund: NAV / returns / drawdown / fees / manager / holdings
invest-cli us AAPL               # US: valuation + financials + analyst rating
invest-cli sec AAPL              # US filings, original source (SEC EDGAR, no key)
invest-cli screen "Bank stocks with PE below 10"
invest-cli intent macro          # Macro: net-liquidity series (keyless path)
invest-cli info 茅台             # News / sentiment (via argo)
invest-cli datasources           # Diagnose "why no data": per-source availability and chains
```

Add `--json` for structured output an agent can parse; omit it for a terminal table. One question never mixes sources: a failing source falls back as a whole, and the result always labels its origin.

---

## Recent Improvements & Performance

No new features in v2.5 — just lower fixed cost per call, and fixes for defects where the judgment was made at the wrong layer.

### Performance: lazy source probing (the big one)

The old router probed **every source in the chain up front**, so every A-share query paid a real HTTPS probe for the last-resort yfinance fallback. Now it only does a cheap capability check up front and probes availability right before calling a source; if the primary succeeds, fallbacks are never touched.

| Metric (same machine, cleared cache) | Before | After |
|:---|---:|---:|
| A-share routing probe segment (isolated) | 0.53s | **0.012s** (~44x) |
| `stock 600519` cold path | 1.52s | **0.51–0.60s** (~2.6x) |
| `fund 110011` cold path | 2.30s | **1.24–1.45s** (~1.7x) |
| Probes triggered by one A-share query | 4 | **1** |
| Hot path (cache hit) | 0.11–0.13s | unchanged (already the floor) |

One duplicate request was also removed: the income statement was fetched twice (a `limit=1` preview plus the `limit=5` batch) to learn the latest fiscal year; it is now derived from the annual-report disclosure rule, with a fallback when the guess is wrong.

### Correctness: four cases of "judged at the wrong layer"

- **Chinese names treated as US tickers**: CJK characters are also `isalpha()` in Python, so `intent deep 茅台` went to Yahoo for "茅台" (3.2s wasted). The test is now ASCII-only.
- **YingMi fuzzy match turning stocks into funds**: `GuessFundCode` is substring-based; "中国平安" matched an unrelated fund. The test changed from "YingMi returned something" to "the returned fund name actually corresponds to the query".
- **Empty target exhausting the whole chain**: `stock ""` took 3.55s and returned three concatenated source errors; now rejected at the entry in 0.05s with one clear message.
- **Upstream `data.data=null` raising a bare exception**: `screen ""` used to print a Python traceback.

### Resources: cache no longer grows unbounded

TTL decides read hits, it does not delete files; a single SEC companyfacts file is ~3.7MB and accumulated per company queried. Added a 7-day cap with cleanup on write — measured 24MB → 11MB locally.

### Regression guards

Tests went from 156 to **171**, each new one tied to a behavior that actually happened (including counter-cases so a fix cannot degrade into "reject everything").

---

## Design Philosophy

1. **Simplicity** — Buffett's three questions extended to all asset types
2. **No Decision-Making for You** — Framework only, decisions are yours
3. **Dynamic Time** — Auto-calculates which report to look at
4. **Master Perspective** — Multi-perspective discussion to expose blind spots

---

## Before You Use This

**First, you bear your own gains and losses.** This tool won't tell you which stock to buy or which fund to sell.

**Second, information is limited.** Data may be delayed or incorrect. It gives you reference, not definitive answers.

**Third, it cannot replace professional advice.** Consult a licensed investment advisor for large investment needs.

**One sentence: The tool only helps you think clearly. The decision is yours. The risk is yours.**

---

## Project Structure

```
docs/
└── data-sources.md            # Optional data sources (unlock after config)
skills/
├── invest/                    # Entry: auto-identifies target type
├── invest-stock/              # Stock analysis (3-Gate/4-Dimension/Institutional Deep/HK-A)
├── invest-fund/               # Fund analysis (scene routing)
├── invest-asset/              # Single-asset: Bonds/Convertibles/Commodities (incl. gold 10D)/REITs
├── invest-allocation/         # Asset allocation
├── invest-macro/              # Macro & market environment (liquidity/sentiment/bottom signals)
├── invest-discuss/            # Masters discussion (multi-perspective validation)
├── invest-analyst/            # Institutional-grade output (IC memo/minutes/consensus/daily)
└── invest-cli/                # Data layer: CLI + multi-source adapters + regression tests
    └── docs/                  # Data-source notes + performance & defect reports (with repro steps)
```

---

## Version History

| Version | Date | Changes |
|:--------|:-----|:--------|
| v2.5 | 2026-09 | Lazy source probing (A-share probe segment 0.53s→0.012s; `stock` cold 1.52s→0.51s); removed a duplicate income-statement request; four wrong-layer fixes (CJK as US ticker / YingMi fund false positive / empty target exhausting the chain / `screen` bare exception); 7-day cache cap with cleanup (24MB→11MB locally); guards 156→171 |
| v2.4 | 2026-09 | argo engine list no longer maintained locally (20→250+ usable engines, silent-empty answer fixed); `fund` deep-fetch cache (0.985s→0.104s) and FRED concurrency+cache (2.380s→0.076s hot); three US failure modes fixed (unknown ticker / share classes / log pollution); atomic cache writes (pid in tmp name); watchlist moved out of the cache dir |
| v2.3 | 2026-09 | Ablation-style maintenance: registration chains 9/9 aligned (3 dead links removed), dead routes cleaned, command paths unified, `watchlist` documented |
| v2.2 | 2026-09 | Thin single-asset 4-in-1: invest-bond/convertible/commodity/reit → invest-asset (same 3-gate skeleton × 4 asset params; registry 12→9); invest-cli retired `ttfund`, adopted ttskill official source + hithink/bitget/route fallback chain |
| v2.0.5 | 2026-08 | Unified multi-source data layer (Wind/YingMi/Eastmoney/yfinance + argo finance verticals; intent-layer convergence; datasources probe); new invest-bond/invest-macro; gold 10-dimension merged into invest-commodity |
| v2.0.2 | 2026-07 | Config gates + data-source guide; invest-cli hardening; public route sanitization |
| v2.0 | 2026-06 | Unified framework: invest-stock merged HK/US/Institutional, invest-fund scene routing, new invest-discuss/invest-cli |
| v1.0 | 2026-04 | Initial release, unified 3-gate review framework |

---

If this project is helpful to you, feel free to give it a Star.

---

MIT License © 2026
