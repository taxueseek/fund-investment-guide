# invest-cli 复核报告（第三轮：hunt + check 协作）

日期：2026-09-22
范围：`~/.agents/skills/invest-cli`（scripts 全量），接续 09-19 / 09-21 两轮报告，不重复其已修项。
方法：check（整体质量审查）+ hunt（根因先行）协作；每项结论带实测，修完带前后对比。

## 一、本轮对「最大瓶颈」的重新定义

前两轮把「探测开销」「深取不缓存」「串行 RTT」修掉后，本轮用同一套方法复测，
热路径已全部落在 0.07-0.13s（解释器 + 读缓存，无下压空间）。剩下的日常性能损失
集中在一处**未被前两轮覆盖的窗口**：

```
us 冷 2.6s = 2.0s 探测（Yahoo 不可达，付满 2s 预算）
           + 0.55s yfinance 取数失败
           + 0.05s bitget 成功
```

前两轮把**失败探测的负缓存设为 20s**（防「瞬时抖动禁用源 5 分钟」）。但实测
`_probe_http` 的 False 只来自「连不上/握手失败」——HTTPError 有状态码 = 可达 = True。
这类网络级不可达的恢复以分钟计，20s 窗口的结果是：**快照 60s TTL 一过，
探测负缓存多半也过了，每次 us 都重付 2.55s**。量化（同机、间隔 5-10 分钟的使用密度）：

| 场景 | 修前 | 修后 |
| --- | --- | --- |
| us 快照过期 + 探测窗口内 | 2.55s（重付探测） | **0.57s**（4.5x） |
| us 全冷（首次或 >120s） | 2.60s | 2.60s（不变，网络本质） |
| us 全热 | 0.06-0.09s | 0.06-0.09s（不变） |

**修法**：负缓存 20s → 120s，`INVEST_CLI_PROBE_TTL_FAIL` 可覆盖。非对称设计保留
（120s < 成功缓存 300s），且判据落在被声明的事实上——False 的语义从根上就不是「抖动」。

## 二、其余修复（最小修改集）

| 项 | 问题 | 修法 |
| --- | --- | --- |
| cached 标记断链 | `cmd_us` 的 bitget 回退分支把 route 层的 `cached: True` / `fallback_from` 丢了；stock/fund 都透传，唯独 us 丢。agent 看到的 us 热路径「不像缓存的」 | 三个字段补透传（4 行） |
| 死代码 | `_common.parse_eastmoney_tables` / `eastmoney_ensure_ok` AST 全仓**零调用者**（`cmd_stock`/`cmd_fund` 各有自己的 `parse_tables`），与 09-19「宣称有缓存、零调用者」同一类 | 删 35 行 |
| 冗余兜底 | `eastmoney.load_api_key` 尾行 `os.environ.get(ENV_KEY, "")`——`read_env` 已按 env→launchctl→rc 查过，走到这里 env 必空 | 改 `return ""`，连带删 `import os` |

## 三、核查过、判定不改的（举一反三的另一半）

- **`intent macro` 兜底引擎 `nbs_stats`**：实测在 argo 243 引擎清单内，链路合法。
- **fund 链中 ttskill 的角色**：yaml coverage `[fund]` + 适配器有 `fund()` → 进快照链候选；
  SKILL.md 写「hithink > [ttskill 可选深取] > eastmoney」，实际 candidates 顺序
  `hithink > ttskill > eastmoney`，与文档语义一致（ttskill 在 hithink 之后）。
- **`secret_from_file` / `json_out` / `find_invest_cli`**：本轮也是零调用者，但它们是
  `_common` 头注释承诺的公共 API 面（密钥不入环境约定、跨 skill 库调用入口），
  删除收益小、破坏契约风险大，保留。
- **git 卫生**：`__pycache__` / `.venv` / `.pytest_cache` 均已被 skills/.gitignore 覆盖且零误跟踪。
- **skill_roots 的 Documents glob**：实测 0.024s（28 个项目目录），不值得动。
- **subprocess 写死 `python3`（argo 调用）**：实测系统 python3 跑 argo search.py 正常；
  argo 是独立 skill，不该假设它跑在 invest-cli 的 venv 里，维持现状是对的。

## 四、实测矩阵（本轮复测）

| 命令 | 冷 | 热 | 状态 |
| --- | --- | --- | --- |
| stock 600519 | 0.66-0.76s | 0.093-0.125s | 正常 |
| fund 110011（含深取） | 1.27s | 0.093-0.11s | 正常，深取缓存生效 |
| us AAPL | 2.60s | 0.073-0.093s（cached=True 已透传） | 正常 |
| us（快照过期、探测窗内） | 2.55s → **0.57s** | — | 本轮修复 |
| intent macro | 0.81s | 0.079s | 正常 |
| screen 银行股 | 1.65s | 1.65s（按设计不缓存） | 正常 |
| info 茅台 --engine cninfo | 2.4s | — | 正常，引擎透传 |
| wind 透传 | 0.57s | — | 正常，真实回执 |
| sec BADTICKER / us 非法 / stock 模糊匹配拦截 / fund 999999 / intent deep 缺参 | 全部 rc=1 明确报错 | | 正常 |
| 空环境（HOME=临时目录、凭据清空） | us/macro/watchlist/datasources rc=0，stock rc=1 如实报缺 key | | 正常 |

守卫：**186 → 187 passed（系统口径；venv 口径 192 → 193）**（负缓存非对称断言改为新口径 + 新增 env 覆盖守卫；
`test_expired_negative_cache_is_reprobed` 语义未变——过期必重探）。

## 五、诚实的遗留

1. **us 首次冷 2.6s**：Yahoo 不可达机器的固有成本（2s 探测预算 + 0.55s 失败）。
   若要归零，需把「取数失败」也纳入负缓存（失败快照不缓存是有意设计，防把抖动固定 60s），
   两者的张力需要单独一轮权衡，本轮不动。
2. **screen 冷 1.65s**：东财选股 API 本身耗时，且按设计不缓存（条件查询随行情变）。
3. **分析层 token 量**：9 技能 frontmatter 常驻约 706 tokens（健康）；SKILL.md 正文
   合计约 2.9 万 tokens、references 按需约 13.9 万，均按需加载，不构成瓶颈。
4. **注册链**：`.zcode/skills`、`.grok/skills` 仍无 invest 条目（09-21 报告遗留，
   属方向级决定，需单独一轮）。

## 六、口径注记（接续 09-21 报告第十一节）

本轮对用户要求的几处判断沿用前两轮报告的口径，不再重复论证，只标注出处：

| 判断点 | 本轮口径 | 出处 |
| --- | --- | --- |
| 「最大的性能瓶颈」 | 日常**单次调用**耗时（非吞吐/并发） | 09-19 报告第一节、09-21 报告第十一节 |
| 「不同对话」 | 不同**调用上下文**（cwd/库调用/冷启动；本 CLI 无跨会话状态） | 09-21 报告第五节、第十一节 |
| 「未知使用需求的普适性」 | 覆盖「没配 key」「上游不通」「输入不存在」三类；**未覆盖**期权外汇等从未见过的标的类型 | 09-21 报告第十一节；本轮补测了 BTC-USD（如实报错）与盈米数组工具 |
| 「一行修改消灭一类」 | 最接近的是 adapter 负缓存不落盘（一行 `unlink` 消灭「凭据秒恢复被压制 2 分钟」一类） | 本轮第二节、第七节纠正 2 |


## 七、对抗性审查（独立 agent，活数据实测）

本轮改动交独立审查者复核（不看我的结论，自己跑数据），找到 **3 个真实问题**：

### 纠正 1（低-中）：us 的 yfinance 成功分支 cached 标记仍丢失

我只修了 bitget 回退分支的 cached 透传，yfinance 成功分支走 `return data`
（内层快照），信封上的 `cached: True` 同样没带出来。已修（3 行）。

### 纠正 2（中）：「探测 False 只来自连不上」只对 http 型成立

提交信息声称的判据覆盖不全：adapter 型探测（ttskill/wind/yingmi/hithink，
`detect()` 经 `_cached(("adapter",...))` 共享同一落盘负缓存）的 False 来自
「凭据缺失/过期」——用户补好凭据是**秒级**恢复，却被 120s 负缓存压制，
`datasources` 排障时会给出 2 分钟前的旧结论。已修：adapter 型 False 不落盘
（仅进程内 30s），附守卫 `test_adapter_negative_probe_not_persisted`。

### 纠正 3（轻微）：提交信息测试计数口径

提交信息写 187 passed，审查者在干净提交树上（venv，有 yfinance）测得 193。
精确归因（逐树数测试函数）：`43131af` 树共 **193** 个测试函数，venv 下全部执行
= 193 passed；本会话在系统 python3（无 yfinance）跑 = 187 passed + 6 skipped
（yfinance 相关 6 条被 `importorskip` 跳过）。即 **187+6=193，两数完全一致**，
差异纯粹是「venv 有无 yfinance」，不是收集口径。提交信息当时应写 193（venv 口径）
或注明系统口径。`81e2d49` 再增 1 条守卫后：venv 194 passed / 系统 188+6skipped。

### 审查者确认正确的部分

- TTL=0 时失败完全不缓存（`age < 0` 恒假，实验证实 fn 被真实调用两次）
- env 覆盖与非法值回退符合预期
- grep + AST 双重确认删除的两个函数零引用
- us bitget 分支 cached/fallback_reason 透传实测生效
- 120s 负缓存对 http 型（yfinance）的收益成立

### 主线程自查补充

`capability-gap.md` 的 GetPopularFund P0 行过时：直连版 `_wrap` 已支持
数组返回，实测 `window=7` 返回正常（该 P0 在 09-03 已修，文档未回填）。已回填。

## 八、修复后最终基线

| 项 | 结果 |
| --- | --- |
| 守卫 | 系统 python3：188 passed, 6 skipped（yfinance 缺）；venv：194 passed。两口径合计一致 |
| us 热 | cached=True 透传到位（bitget/yfinance 两分支一致） |
| adapter 失败 | 不落盘，秒级恢复可见 |
| 提交 | 81e2d49（对抗审查修复）、c113b35（口径注记） |
