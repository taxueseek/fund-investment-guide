"""westock CLI 扩展能力适配器（腾讯微证券命令行）。

血缘与定位
----------
移植自 `~/.workbuddy/skills/tencent-invest/scripts/westock.py`（平行实现，2026-09-22
并入本系列）。它在原技能里的角色是「原生内核够不到的能力的兜底」；在 invest-cli 里
角色更清楚：**长尾能力的唯一出口**。

invest-cli 的既有源覆盖「快照三关」（stock/fund/us，同花顺/东财/yfinance/腾讯），
但没有下面这些：
    筹码分布 · 龙虎榜 · 陆股通成份 · 北向/南下资金持仓 · 融资融券 · 大宗交易
    一致预期 · ESG 评级 · 机构评级 · 研报 · 股票评分 · 产业链图谱
    板块估值/盈利预测/申万财务 · 可转债条款与现金流明细 · 停复牌 · 风险事件
    新股日历 · 交易日历 · 财报披露日历 · 回购 · 股东研究 · 外汇/期货品种
这些经 `invest-cli westock <args...>` 透传使用，不进快照链（本模块不暴露
stock()/fund()/us()/screen() 方法），因此不与既有源产生字段口径冲突。

移植时改掉的三处（原实现的缺陷，不继承）
----------------------------------------
1. **不返回空串**：原 `_run` 的 `except` 会把 CLI 失败吞成 `""`，调用方读成
   「查无数据」。这里失败一律抛 `WestockError`，由 `call()` 转成可读信封。
   特别注意 `rc=0 但输出为空` 也算失败 —— 原实现踩过 `westock etf` 把 usage
   帮助文本打到 stdout 且 `exit=0` 的坑（known-issues ⑮），那时「一段用法说明」
   被当成了 ETF 数据返回。
2. **代码位置归一化**：CLI 要求 `sh600519` / `usAAPL`，而用户与 agent 会说
   `600519` / `AAPL` / `600519.SH`。原实现里 11 个包装函数**共享同一个死因**
   （裸代码 → `[code=-1] 股票代码错误`）。这里用一张「命令 → 代码参数下标」表
   （`_CODE_AT`）把作用域收窄到那一个位置，而不是扫描所有参数 —— 扫描会把
   `hot stock` 的 `stock`、`ranking CompScore` 的 metric、`--market hs` 的取值
   一起改成 `usSTOCK`/`usCompScore`/`usHS`，引入的 bug 比修掉的多。
3. **通用错误要给方向**：服务端对取值域不对的请求只回 `service error` /
   `param invalid`，看起来像「对方挂了」，实际是「我的取值不在契约内」。
   这类错误一律附上「怎么查到真实取值」的提示，把不可修的表象变成可修的动作。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from typing import Optional

# 命令 → 代码参数下标。键是命令前缀（tuple，支持两级命令），值是下标。
#
# 这张表**逐条实测得来**，不是照着 `--help` 抄的：对每个命令分别用「裸代码」与
# 「带市场前缀」各打一次，看哪一侧能拿到表格。实测 24 组，23 组是「裸代码给不出
# 数据 / 前缀才对」，因此下面几乎每一项都有必要：
#   quote 600519        → "未找到行情数据"        quote sh600519        → 表格
#   kline 600519        → 查询失败 [code=1620053001]                   → 表格
#   minute 600519       → "不支持的市场: 600519"                        → 表格
#   chip 600519         → "仅支持沪深A股（sh/sz/bj 前缀）"              → 表格
#   profile 600519      → 只有 code 一列的残表                          → 完整表
#   report list 600519  → "股票代码错误"                                → 表格
#   news list 600519    → "param invalid"                              → 表格
#   fund flow 600519    → "数据为空"                                    → 表格
#   etf profile 510300  → "ETF 代码仅支持 sh/sz 前缀"                    → 表格
#   bond 113050         → "bond 仅支持沪深可转债代码"                    → 表格
#   disclosure 600519   → "未找到业绩预告数据"（**像"没有数据"，其实是代码没写对**）→ 表格
#
# ⚠️ `rating` **刻意不在表里**：它要的是**裸代码**，加前缀反而查不到 ——
#   实测 `rating AAPL` → 表格，`rating usAAPL` → 空；`rating 00700` → 表格，
#   而 `rating hk00700` → 空。这是全表唯一的反例，别把它「顺手补上」。
_CODE_AT: dict[tuple[str, ...], int] = {
    ("finance",): 1, ("profile",): 1, ("technical",): 1,
    ("shareholder",): 1, ("dividend",): 1, ("chip",): 1, ("score",): 1,
    ("consensus",): 1, ("events",): 1, ("risk",): 1, ("notice",): 1,
    ("esg",): 1, ("disclosure",): 1, ("bond",): 1,
    ("quote",): 1, ("kline",): 1, ("minute",): 1,
    ("report", "list"): 2, ("news", "list"): 2,
    ("fund", "flow"): 2, ("etf", "profile"): 2, ("etf", "holdings"): 2,
}
_MAX_DEPTH = max(len(k) for k in _CODE_AT)
# 代码形状守卫：只有「像代码」的输入才归一化。否则 normalize_code 会把
# `CompScore` 这类取值变成 `usCompScore` —— 一个不报错、只查无结果的错值。
_SYM_SHAPE = re.compile(r"^(?:[a-zA-Z]{2})?\d{4,6}(?:\.[a-zA-Z]{2})?$")
_TICKER_SHAPE = re.compile(r"^[A-Za-z][A-Za-z.\-]{0,9}$")
_CJK = re.compile(r"[\u4e00-\u9fff]")
# 服务端「通用错误」的表征：命中即提示怎么查真实取值域（而不是让它看起来像对方故障）
_GENERIC_ERR = re.compile(r"service error|param invalid|参数(错误|不合法)|未识别的|不支持")
# CLI 在「参数对不上任何子命令」时会**打印帮助并 rc=0**（实测 `westock macro gdp`：
# 35 行帮助文本、零 stderr、退出码 0）。把它当数据返回，用户拿到的就是一份
# 说明书而不是行情 —— 原实现只在 `etf` 一个调用点上绕开（改成 `etf profile`），
# 属于按点补丁；这里在**边界**上判一次，40+ 个子命令一起受益。
_HELP_REQUEST = re.compile(r"^(-h|--help)$")
# 除帮助页之外，CLI 还有一类「rc=0 但不是数据」的输出：限流与服务通告。
# 实测 `westock kline sh600519 --period m5 ...` 连续调用后打印
# `请求过于频繁，请稍后再试`、退出码 **0**、stderr 为空 —— 直接当数据返回的话，
# 用户拿到的是一句「稍后再试」当成了 K 线。判据取「单行 + 短 + 已知通告措辞」，
# 宁可漏判也不误伤：真数据是 markdown 表格或 JSON，不会长成这个样子。
# 措辞来自对 45 个子命令的**实测普查**（见测试 test_notice_survey_*）：
# 45 条里 39 条是表格、4 条是合法非表格数据（`macro list` 的清单、`events`/`buyback`
# 的「数据为空」标题行、`screen strategy --list` 的取值清单），另外 2 条是伪成功：
#   `bond 113050`   -> "bond 仅支持沪深可转债代码"（rc=0）
#   `futures list`  -> 一页帮助文本（rc=0）
# 所以判据只能收「明确不是数据」的措辞，**不能**改成「没有表格就是通告」——
# 那会把 `macro list` 这类合法清单一起拦掉。
_NOTICE = re.compile(
    r"^(请求过于频繁|请稍后再试|服务(异常|不可用|繁忙)|系统繁忙|网络(超时|异常)|超时"
    r"|错误[:：]|.*仅支持|.*不支持|.*请(使用|提供|指定|改用)"
    # 失败类：vendor 把这类也当 rc=0 正常输出打出来（实测）
    r"|.*失败[:：\[]|.*service error|param invalid"
    # 「查到了空」类：单行的空结果不该冒充数据，多行的（带标题的）仍算结构化结果
    r"|未找到|数据为空|未识别的|无此|不存在)")
# 长度门取消：实测失败信息 67 字（查询策略选股失败：[code=…] service error），
# 卡在 60 会把最典型的一条放过去。改由「单行」这一条承担鉴别：
# 结构化输出（表格/标题/清单）必然多行，单行输出必是通告或提示。
_NOTICE_MAX_LEN = 400
_TIMEOUT = 30


class WestockError(RuntimeError):
    """CLI 调用失败（缺二进制/非零退出/输出为空）。绝不降级成空串。"""


def _find_bin() -> Optional[str]:
    """定位 CLI：环境变量优先，其次 PATH。"""
    env = (os.environ.get("WESTOCK_BIN") or "").strip()
    if env and os.path.exists(env):
        return env
    return shutil.which("westock")


def detect() -> tuple[bool, str]:
    """可用性 = 二进制在 + `--help` 真的跑得起来。

    为什么不能只判断文件存在：原技能的 westock-data 通道就栽在这上面 ——
    目录里只有 setup.sh 没有 index.js，「存在」为真而调用永远失败，
    16 个函数静默返回空串（known-issues ①）。`--help` 实测 22ms，值得付。
    """
    binary = _find_bin()
    if not binary:
        return False, "未找到 westock CLI（装法见 https://github.com/tencent/westock 或设 WESTOCK_BIN）"
    try:
        proc = subprocess.run([binary, "--help"], capture_output=True, timeout=10,
                              text=True, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"westock CLI 无法执行: {e}"
    if proc.returncode != 0:
        return False, f"westock --help 退出码 {proc.returncode}"
    return True, "westock CLI 可用"


def _run(args: list[str], timeout: int = _TIMEOUT) -> str:
    """执行 CLI 并返回 stdout。

    三条纪律（都来自原实现踩过的坑）：
      · 固定 `encoding="utf-8"`：交给 locale 猜编码时，非 UTF-8 系统
        （如中文 Windows 的 cp936）解码失败会被 `except` 吞成空串（known-issues ⑱）；
      · 非零退出 → 抛错，带 stderr 内容；
      · **rc=0 但输出为空 → 也算失败**：那是「命令跑通但没有数据」的假成功，
        继续往下传会让调用方以为查到了空结果（known-issues ⑮）。
    """
    binary = _find_bin()
    if not binary:
        raise WestockError("未找到 westock CLI")
    try:
        proc = subprocess.run([binary, *args], capture_output=True, timeout=timeout,
                              text=True, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as e:
        raise WestockError(f"westock {' '.join(args)} 超时（>{timeout}s）") from e
    except OSError as e:
        raise WestockError(f"westock 无法执行: {e}") from e
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        err = (proc.stderr or "").strip() or out
        # 原因不能是空的：CLI 偶尔 rc≠0 却两个流都空，光报「失败」等于没说
        # （原实现的这条消息只剩 `rc=0 `，不满足它自家的守则 5）。
        raise WestockError(f"westock {' '.join(args)} 失败(rc={proc.returncode})"
                           f"{': ' + err[:400] if err else '，且 CLI 没有输出任何错误信息'}")
    if not out:
        raise WestockError(f"westock {' '.join(args)} 退出码为 0 但没有输出（非空结果才可信）")
    if not _is_help_request(args) and _looks_like_notice(out):
        raise WestockError(f"westock {' '.join(args)} 返回的不是数据，而是通告：{out.strip()[:80]}"
                           f"（rc=0，所以只能靠形状判定）")
    if not _is_help_request(args) and _looks_like_help(out):
        # 参数没对上子命令：CLI 打帮助 + rc=0。这不是数据，必须报出来，
        # 否则「命令写错了」会被读成「查到了东西」（known-issues ⑮ 的同一类）。
        scope = next((a for a in args if not a.startswith("-")), "")
        raise WestockError(
            f"westock {' '.join(args)} 没有匹配到子命令，CLI 只打印了帮助文本（rc=0），"
            f"这不是数据。请检查子命令拼写；可用 `invest-cli westock {scope} --help`"
            f" 看该命令的子命令与参数。")
    return proc.stdout


def _looks_like_help(out: str) -> bool:
    """输出是不是「本命令的帮助页」。判据取 CLI 自己固定打的三个标记。"""
    head = out.lstrip()
    # 三个标记任取其二：CLI 的帮助页固定打 "Usage:"，并按命令层级附三种清单之一。
    # 实测 `westock futures list`（该命令其实只支持 `search --type futures`）
    # 打的是 "Group: 期货" + "Usage:"，只有加上 Group 才拦得住。
    return "Usage:" in head and ("Available Commands:" in head or "Flags:" in head
                                or "Group:" in head)


def _looks_like_notice(out: str) -> bool:
    """单行通告（限流/失败/空结果）——不是数据。

    判据是「**单行** + 已知措辞」：结构化输出（markdown 表格、`#` 标题、清单）必然多行，
    实测 45 个子命令里 39 条表格 + 4 条多行非表格（`macro list` 清单、`events`/`buyback`
    的空结果标题、`screen strategy --list` 取值清单）全部是多行，因此不会被误伤。
    """
    lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
    return len(lines) == 1 and len(lines[0]) <= _NOTICE_MAX_LEN and bool(_NOTICE.match(lines[0]))


def _is_help_request(args: list[str]) -> bool:
    """调用方**主动**要帮助时，帮助文本就是正确结果，不该拦。"""
    return any(_HELP_REQUEST.match(str(a)) for a in args)


def _code_index(sub: list[str]) -> int:
    """查该命令的代码参数下标；不在表里返回 -1。"""
    for depth in range(min(_MAX_DEPTH, len(sub)), 0, -1):
        if tuple(sub[:depth]) in _CODE_AT:
            return _CODE_AT[tuple(sub[:depth])]
    return -1


def _norm_symbol(arg: str) -> str:
    """归一成 CLI 要求的写法；不确定就原样返回（宁可让 CLI 报错，也不猜）。"""
    from . import tencent

    if _SYM_SHAPE.fullmatch(arg) or _TICKER_SHAPE.fullmatch(arg):
        return tencent.normalize_code(arg) or arg
    if _CJK.search(arg) and len(arg) <= 24:
        # 中文名交给腾讯搜索解析（复用同一实现，不另写一份映射）；
        # 通道不可用时原样放行，由 CLI 自己报错，随后我们补提示。
        try:
            return tencent.resolve_name(arg) or arg
        except Exception:
            return arg
    return arg


def normalize_args(sub: list[str]) -> list[str]:
    """只归一化「代码位置」上的那一个参数，其余（旗标/取值/关键词）原样放行。"""
    idx = _code_index(sub)
    if idx < 0:
        return list(sub)
    out = list(sub)
    if idx < len(out) and not out[idx].startswith("-"):
        out[idx] = _norm_symbol(out[idx])
    return out


def _hint_for_generic_error(text: str, sub: list[str]) -> str:
    """通用错误 → 直接把**真实取值域**拉出来附在后面。

    known-issues ㉑ 的教训：`strategy("高股息")` 得到 `service error`，排查方向被
    指向服务端；真相是取值域是英文标识符。
    这里刻意**不硬编码**取值清单（被移植实现的 `_PRESETS` 硬编码 9 个、真实有 22 个，
    于是 13 个合法取值被它判成「非法」）：现拉一次 `--list`，它说什么就是什么；
    拉不到就退回一句「怎么查」的提示。只在错误路径上付这一次调用。
    """
    if not _GENERIC_ERR.search(text):
        return ""
    scope = [x for x in sub[:2] if not x.startswith("-")] or ["<命令>"]
    got = list_values(scope)
    if got.get("ok"):
        vals = [v for v in got["data"]["values"] if not v.startswith("#")][:12]
        more = "" if len(got["data"]["values"]) <= 12 else f" …（共 {len(got['data']['values'])} 个）"
        return ("（这类通用错误多因取值不在契约内。该命令的真实取值域前几项："
                + "、".join(vals) + more + "）")
    return (f"（提示：这类通用错误多因取值不在契约内。用 `invest-cli westock {' '.join(scope)} --list`"
            f" 查真实取值域——常见取值是英文标识符，如 high_dividend / cn_gdp）")


def _clean_args(args) -> tuple[list[str], str]:
    """规范化入参：只接受字符串，拒绝 NUL。返回 (参数, 错误原因)。

    为什么要挡：`subprocess` 对含 None 的 argv 抛 TypeError、对含 NUL 的抛 ValueError，
    两者都会穿透调用方（原实现实测 17/23 个对外函数在 None 入参下抛异常）。
    边界上判一次，比在 20 多个包装函数里各判一次可靠。
    """
    out: list[str] = []
    for a in args or []:
        if not isinstance(a, str) or a == "":
            continue
        if "\x00" in a:
            return [], "参数里含 NUL 字节"
        out.append(a)
    return out, ""


def call(args) -> dict:
    """透传执行。返回信封 {source, kind, ok, data|error}。"""
    sub, bad = _clean_args(args)
    if bad:
        return {"source": "westock", "kind": "cli", "ok": False, "data": None,
                "error": f"参数非法：{bad}"}
    if not sub:
        return {"source": "westock", "kind": "cli", "ok": False, "data": None,
                "error": "缺少 westock 子命令；用 `invest-cli westock --help` 看命令树"}
    norm = normalize_args(sub)
    try:
        out = _run(norm)
    except WestockError as e:
        msg = str(e)
        hint = _hint_for_generic_error(msg, sub)
        return {"source": "westock", "kind": "cli", "ok": False, "data": None,
                "error": msg + ("\n" + hint if hint else "")}
    return {"source": "westock", "kind": "cli", "ok": True,
            "data": {"command": "westock " + " ".join(norm),
                     "argv_normalized": norm != sub,
                     "output": out},
            "error": None}


def list_values(command: list[str]) -> dict:
    """取某命令的合法取值域（`--list`）。成功返回信封，元素为原始行。"""
    try:
        out = _run(list(command) + ["--list"])
    except WestockError as e:
        return {"source": "westock", "kind": "list", "ok": False, "data": None, "error": str(e)}
    rows = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return {"source": "westock", "kind": "list", "ok": True,
            "data": {"command": "westock " + " ".join(command) + " --list", "values": rows},
            "error": None}


def _main() -> int:
    """直接执行本模块时的最小入口（调试用）。"""
    res = call(sys.argv[1:])
    if res["ok"]:
        print(res["data"]["output"])
        return 0
    print(f"错误: {res['error']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(_main())
