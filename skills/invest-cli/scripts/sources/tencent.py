"""腾讯行情数据源适配器（零鉴权原生内核）。

血缘
----
内核移植自 `~/.workbuddy/skills/tencent-invest/scripts/txdata.py`。该技能是 invest
系列的**平行实现**（自带 SKILL.md + 4 个脚本 + 3 轮缺陷修复记录），2026-09-22 并入
本系列：能用得上的能力（腾讯行情内核 / westock CLI 扩展 / neodata 研究通道）收进
invest-cli 成为一等数据源，技能层只留一个入口，避免同一天花板维护两份。

**移植不是复制**。下面三处是原实现的缺陷，本文件刻意不继承（每处都有实测证据）：

1. 原 `txdata` 用 `_never_raise` 把网络故障降级成空 list/dict，于是
   「通道故障」与「查无此标的」在调用方看来完全一样 —— 正是本仓第四轮定为
   缺陷的那一类（rc=0 的假成功）。本适配器**区分两者**：
   HTTP 失败 → `{ok: False, error=...}`；HTTP 成功但标的不在响应里 →
   这条**只在多标的批量里有意义**，故在 `quote_batch` 里逐标的标记 missing。

2. 原实现只有一张字段表，而 qt 同一下标在不同市场含义不同。实测（三个市场各取
   一个标的，用独立源核对）：
       市净率     A股 [46]=6.24（同花顺 6.238129 ✓） 美股 [51]=46.01（yfinance 46.057 ✓）
       换手率     A股 [38]=0.20%                    港股 [59]=0.78%（东财 0.78% ✓）
       成交额     A股 [37]=308853（万元）            港/美 [37] 已是元
   于是原实现的 `hk00700.turnover_rate` **恒为 0.0**，而真值是 0.78% ——
   一个「像数据」的错值，比空值更难回查（known-issues 自己把这类列为最危险）。
   这里按市场分表（`_QT_MAP`），且**只登记用独立源核对过的下标**：没核对的
   宁缺勿错（港股 PE 在 [39] 给 16.50、东财给 15.39，口径不同，故不登记）。

3. 原 `_alt_market` 在标的不命中时换交易所补查。对裸 6 位代码是善意，但它
   会静默返回**另一个标的**：实测 `quote(["sz110011"])` 回的是
   `sh110011 歌华转债`（问的是基金 110011）。这里把纠正限制在
   「同一只标的的不同市场写法」不可能越界的范围内，并**要求纠正结果与请求代码
   同号**（见 `_alt_market` 的注释与 `test_tencent_source.py`）。

定位（为什么不与既有源重叠）
----------------------------
腾讯 qt 是**零鉴权 + 一次请求取多标的 + 跨市场**的公开行情接口，实测单标的
冷取数 ~130ms，6 标的混合（沪/深/港/美/ETF/可转债）132ms。而三条现实链的主源是：
A股 hithink 487ms、港股 eastmoney 3.5s、美股 yfinance 冷 4.4s。
但腾讯**没有基本面**（净利润/ROE/EPS/资产负债率一个都没有），所以它不进主位 ——
`stock`/`us` 的主位必须留给带基本面的富源，否则是能力降级。它的价值在**兜底位**：
今天的兜底是 yfinance(4s) 或 bitget（实测会返回 `ok=True` 的**空快照**），
腾讯是 130ms 且一定有数。这与 route「同一问题只问一个源」的纪律一致：
链上第一个 ok 的源整单回答，不做跨源字段拼接。
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

# ── 端点（腾讯公开行情接口，无需鉴权） ──────────────────────────────────────
QT_URL = "https://qt.gtimg.cn/q={codes}"
KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
MINUTE_URL = "https://ifzq.gtimg.cn/appstock/app/day/query"
SEARCH_URL = "https://proxy.finance.qq.com/ifzqgtimg/appstock/smartbox/search/get"

# 超时与重试：原实现是 10s × 2 次（最坏 20s+）。本适配器**可能**被排在链尾，
# 兜底位烧 20s 比不回答更糟：调用方等不到结果还以为是网络慢。取 6s × 1 次重试
# 与仓内其它源的量级对齐（东财 30s 是它的 agentic 查询，不可比；同花顺 DEFAULT_TIMEOUT 同量级）。
_TIMEOUT = 6
_RETRY = 2
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# ── 字段口径表（按市场分，只登记已用独立源核对的下标） ──────────────────────
# 公共段：三个市场语义一致，且与同花顺/东财逐字段核对过。
_QT_COMMON = {
    "name": 1, "code": 2, "price": 3, "prev_close": 4, "open": 5,
    "volume": 6, "time": 30, "change": 31, "change_pct": 32,
    "high": 33, "low": 34,
}
# 市场专属段。注释里的数值是 2026-09-22 的实测值 + 核对来源，改动前请重新核对。
# 市场专属段。**每个下标都由具名独立源反查得到**（不是看数值猜的）：
# 取同一时刻的 westock CLI `quote` 输出，它带 48 个**列名**（price/pe_ratio/
# high_52week/...），按值反查 qt 的原始下标，得到下面这张表。样本与对照落在
# scripts/tencent_samples.json（`sh600519` 等原始行 + `_cliq_*` 具名列），
# test_tencent_source.py 会逐字段比对 —— 下标写错会直接红，不靠注释的正确性。
#
# 为什么必须分市场：同一个下标在不同市场是**不同的量**，实测三例
#   [47] A股=涨停价 1377.83 / 港股=股息率TTM 1.18
#   [38] A股=换手率 0.20 / 港股=0（该位无值）/ 美股=换手率 0.24
#   [57] A股=成交额(万元) / 港股=市盈率 15.15 / 美股=ROE 148.75
# （这三个例子都来自上表反查，不是推测。）
_QT_MAP: dict[str, dict[str, int]] = {
    "a": {
        "amount": 37,             # 万元，需 ×1e4 → amount（CLI 给元）
        "turnover_rate": 38,      # turnover_rate
        "pe_ttm": 39,             # pe_ratio
        "range_pct": 43,          # range_pct（振幅）
        "mktcap_circ": 44,        # circulating_market_cap
        "mktcap": 45,             # total_market_cap
        "pb": 46,                 # pb_ratio
        "price_ceiling": 47,      # price_ceiling（涨停价）
        "price_floor": 48,        # price_floor（跌停价）
        "volume_ratio": 49,       # volume_ratio（量比）
        "avg_price": 51,          # avg_price
        "pe_fwd": 52,             # pe_fwd
        "pe_lyr": 53,             # pe_lyr
        "chg_ytd": 62,            # chg_ytd
        "chg_5d": 63,             # chg_5d
        "dividend_ttm": 64,       # dividend_ratio_ttm（%）
        "w52_high": 67,           # high_52week
        "w52_low": 68,            # low_52week
        "chg_10d": 69,            # chg_10d
        "chg_20d": 70,            # chg_20d
        "chg_60d": 71,            # chg_60d
    },
    "hk": {
        "amount": 37,             # 已是元
        "range_pct": 43,          # range_pct
        "mktcap_circ": 44,        # circulating_market_cap
        "mktcap": 45,             # total_market_cap
        "dividend_ttm": 47,       # dividend_ratio_ttm（注意：A股这个位是涨停价）
        "w52_high": 48,           # high_52week
        "w52_low": 49,            # low_52week
        "volume_ratio": 50,       # volume_ratio
        # 注意：港股 PE 有**三个不同值**，取决于问谁 —— qt[39]=16.50、qt[57]=15.15、
        # 东财 15.39。本表取 [57]（CLI 把它命名为 pe_ratio，与 A股 pe_ratio 的取法一致）；
        # 腾讯只是港股链的兜底位，主位是东财，故日常看到的仍是东财那个值。
        "pe_ttm": 57,             # pe_ratio
        "pb": 58,                 # pb_ratio
        "turnover_rate": 59,      # turnover_rate（HK 的 [38] 是 0，不是换手率）
        "chg_ytd": 61,            # chg_ytd
        "chg_5d": 62,             # chg_5d
        "chg_10d": 66,            # chg_10d
        "chg_20d": 67,            # chg_20d
        "chg_60d": 68,            # chg_60d
        "avg_price": 73,          # avg_price
    },
    "us": {
        "amount": 37,             # 已是元
        "turnover_rate": 38,      # turnover_rate
        "pe_ttm": 39,             # pe_ratio
        "range_pct": 43,          # range_pct
        "mktcap_circ": 44,        # circulating_market_cap
        "mktcap": 45,             # total_market_cap
        "w52_high": 48,           # high_52week
        "w52_low": 49,            # low_52week
        "pb": 51,                 # pb_ratio
        "dividend_ttm": 52,       # dividend_ratio_ttm
        "chg_ytd": 54,            # chg_ytd
        "chg_5d": 55,             # chg_5d
        "chg_10d": 59,            # chg_10d
        "chg_20d": 60,            # chg_20d
        "chg_60d": 61,            # chg_60d
        "volume_ratio": 64,       # volume_ratio
        "avg_price": 67,          # avg_price
        # 证据类型不同：CLI 的美股列里**没有** roe，这条来自与 yfinance 具名字段
        # `roe` 的值一致（1.4875101 → 148.75% vs qt[57] 148.75，两位小数吻合）。
        # 比具名反查弱一档，但 148.75 这种量级的值不可能巧合；
        # 若将来 qt 该位变了，test_us_values_match_yfinance 会红。
        "roe": 57,                # （yfinance: roe）
    },
}
_QT_NUMERIC = {"price", "prev_close", "open", "volume", "change", "change_pct",
               "high", "low", "amount", "turnover_rate", "pe_ttm", "pe_fwd", "pe_lyr",
               "pb", "mktcap", "mktcap_circ", "w52_high", "w52_low", "range_pct",
               "dividend_ttm", "volume_ratio", "avg_price", "price_ceiling", "price_floor",
               "chg_ytd", "chg_5d", "chg_10d", "chg_20d", "chg_60d", "roe"}

# 无前缀代码 → 交易所推断。与 _common.kind_from_code 的分工：
# 那边判「这是不是股票/基金/可转债」（业务语义），这边判「该问哪个交易所」（传输语义）。
# 段位重叠时（000922 既是沪市指数也是深市代码）由 _alt_market 兜底。
_SH_PREFIX = ("60", "68", "51", "58", "56", "50", "11", "13", "9")
_SZ_PREFIX = ("00", "30", "12", "15", "16", "18", "20", "39")
_BJ_PREFIX = ("43", "83", "87", "88")


# 计价货币与成交量单位**按市场推导**（不是从接口读的：qt 只对美股给 currency 位，
# 港股那一位放的是价格）。不推导的后果是跨市场对比直接错：
#   实测 quote 三市场时 A股 volume=24573（**手**）、港股 70723438（**股**），
#   直接相比会得出 2878 倍的差距，而按股换算后只有 28.78 倍 —— **100 倍误差**。
# 成交额同理：A股是 CNY、港股 HKD、美股 USD，不标注就没法判断能不能相加。
_CURRENCY = {"a": "CNY", "hk": "HKD", "us": "USD"}
_VOLUME_UNIT = {"a": "手", "hk": "股", "us": "股"}


def _market_of(symbol: str) -> str:
    """符号前缀 → 口径表键（a/hk/us）。未知一律按 a 处理（A股占绝对多数）。"""
    s = str(symbol or "").lower()
    if s.startswith("hk"):
        return "hk"
    if s.startswith("us"):
        return "us"
    return "a"


def normalize_code(code: str) -> str:
    """各种写法 → 腾讯接口前缀形式。

    sh600519 / 600519.SH / 600519 / hk00700 / 00700.HK / AAPL / usAAPL → 前缀形式。
    美股 ticker **保持大写**：接口区分 usAAPL 与 usaapl（原实现踩过，5 标的只回 4 条）。
    """
    c = str(code).strip().replace(" ", "")
    if not c:
        return ""
    m = re.fullmatch(r"(\d{5,6})\.(SH|SZ|BJ|HK|US)", c, re.I)
    if m:
        c = m.group(2).lower() + m.group(1)
    low = c.lower()
    if low.startswith("us"):
        return "us" + c[2:].upper()
    if low.startswith(("sh", "sz", "bj", "hk")):
        return low
    if c.isdigit():
        if len(c) == 5:
            return "hk" + c
        if len(c) == 6:
            if c.startswith(_SH_PREFIX):
                return "sh" + c
            if c.startswith(_SZ_PREFIX):
                return "sz" + c
            if c.startswith(_BJ_PREFIX):
                return "bj" + c
            return "sh" + c
    if re.fullmatch(r"[A-Za-z][A-Za-z.\-]{0,9}", c):
        return "us" + c.upper()
    # 认不出来的一律空串。原实现在这里 `return low`，于是**任何**字符串都会变成
    # 一个「像代码的东西」被送进接口：解析失败的中文名会以 `没有这个标的名` 的形状
    # 出现在请求 URL 里，而接口不报错、只是不回那一行 —— 用户看到的是「少了一条」，
    # 无从知道是名字没解析出来。返回空串后，上层才能如实报「无法解析」。
    return ""


class TencentError(RuntimeError):
    """传输层故障。**不降级成空结果**——那是「通道坏」被读成「查无数据」的根源。"""


def _http_get(url: str, encoding: str = "utf-8") -> str:
    """带重试的 GET。失败抛 TencentError（由调用方转成 ok=False 信封）。"""
    last: Optional[Exception] = None
    for attempt in range(_RETRY):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": _UA,
                "Referer": "https://gu.qq.com/",
                "Accept": "*/*",
            })
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return resp.read().decode(encoding, "replace")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if attempt < _RETRY - 1:
                time.sleep(0.3)
    raise TencentError(f"腾讯行情请求失败: {last}")


def _num(raw: str) -> Optional[float]:
    """数值解析：空串/非数一律 None（**不写 0**——0 是有效值，不能拿来表示缺失）。"""
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _parse_qt_line(line: str) -> Optional[dict]:
    """解析一行 `v_sh600519="..."`，按该行自身的前缀选口径表。"""
    if "=" not in line:
        return None
    var, payload = line.split("=", 1)
    var = var.strip()
    # 精确剥 "v_" 前缀：lstrip("v_") 是按字符集剥，符号名以 v 开头时会被啃掉
    symbol = var[2:] if var.startswith("v_") else var
    fields = payload.strip().strip('";').split("~")
    if len(fields) < 35:
        return None
    market = _market_of(symbol)
    out: dict[str, Any] = {"symbol": symbol, "_market": market,
                           "currency": _CURRENCY[market],
                           "volume_unit": _VOLUME_UNIT[market]}
    for name, idx in {**_QT_COMMON, **_QT_MAP[market]}.items():
        if idx >= len(fields):
            continue
        raw = fields[idx]
        if name in _QT_NUMERIC:
            val = _num(raw)
            # 缺失与 0 必须分开，但**分开的方式是各归各位**：
            #   · 空串/非数 → 字段不出现（这是「接口没给」）
            #   · 0 → 如实落 0（停牌股换手率就是 0，不分红的公司股息率就是 0）
            # 早期版本用「比例字段遇 0 一律剔除」来消灭假 0，那是把脏水和孩子一起倒掉：
            # 假 0 的真因是**读了别的市场的位置**（港股 [38] 恒为 0，真值在 [59]），
            # 已由分市场口径表修正；剩下的 0 都是真实取值，删掉反而是信息损失。
            if val is None:
                continue
            out[name] = val
        else:
            out[name] = raw
    # 成交额口径统一到元：A股接口给万元，港美股给元。统一在源头做，
    # 下游就不必记住「哪个市场要乘 1e4」（原实现把两者混在同一张表里）。
    if market == "a" and "amount" in out:
        out["amount"] = round(out["amount"] * 1e4, 2)
    ts = out.get("time", "")
    if isinstance(ts, str) and ts:
        if len(ts) == 14 and ts.isdigit():
            out["time"] = (f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]} "
                           f"{ts[8:10]}:{ts[10:12]}:{ts[12:14]}")
        else:
            out["time"] = ts.replace("/", "-")
    return out


def quote_batch(codes: list[str]) -> tuple[list[dict], list[str]]:
    """一次 HTTP 取多标的行情。返回 (行列表, 未命中的代码)。

    为什么返回「未命中」而不是静默少几条：接口对未知代码**不报错**，只是不返回
    那一行。原实现只回 rows，调用方看到的条数变少却无从判断是「代码错」还是
    「接口少给」——这正是本仓反复治理的静默失败。这里把两者分开交给上层。
    """
    norm = [normalize_code(c) for c in codes]
    norm = [c for c in norm if c]
    if not norm:
        return [], []
    url = QT_URL.format(codes=",".join(norm))
    text = _http_get(url, encoding="gbk")
    rows = []
    for line in text.splitlines():
        row = _parse_qt_line(line)
        if row:
            rows.append(row)
    got = {r["symbol"] for r in rows}
    return rows, [c for c in norm if c not in got]


# 占位行的判据（实测 sh113050 / sh110011，2026-09-22）：
#   v_sh113050="1~南银转债~113050~144.967~144.967~0.000~0~0~…~20260922090000~0.000~…"
#   价格=前收、开/高/低/量/额**全为 0**、时间停在 09:00:00（开盘前）。
# 对照真实标的（sh600519）：开 1252.15、高 1265.88、低 1248.10、量 24573、时间 16:14:42。
# 这种行**不能当行情输出**：用户会看到「最新价 144.967、涨跌 0.0、成交额 0」，
# 以为它今天一分钱没成交。同厂商的权威源（`westock quote sh113050`）给的是
# 「未找到行情数据」。注意停牌股也会呈现同一形状，所以只陈述可观测事实，
# 不替它下「停牌」的结论。
_PLACEHOLDER_FIELDS = ("open", "high", "low", "volume", "amount")


def is_placeholder(row: dict) -> bool:
    """接口返回的占位行（无成交数据）：开高低收量与额全 0 而价格大于 0。"""
    price = row.get("price")
    if not price:
        return False
    return all(not row.get(f) for f in _PLACEHOLDER_FIELDS)


def _placeholder_reason(row: dict) -> str:
    return (f"「{row.get('name') or row.get('symbol')}」当前无成交数据：接口返回的是占位行"
            f"（开/高/低/成交量/成交额全为 0，时间停在开盘前），可能停牌或无行情；"
            f"最后价格 {row.get('price')} 只是前收，不是今天的成交价")


def _alt_market(code: str) -> str:
    """裸 6 位代码的沪/深互换候选，用于**同号不同市场**的补查。

    只在「代码位数/前缀完全一致」时生成，因此补查到的一定是**同一号码**的另一种
    交易所写法（000922：沪市指数 vs 深市代码），不会跨号。
    原实现在此处把 `sz110011`（基金）纠正成 `sh110011`（歌华转债）——两个**不同**
    标的共享号码却分属不同品种，静默换标的比查不到更坏。品种判定属业务语义，
    交回 `_common.kind_from_code` 与 route 的代码域守卫，本函数只管交易所。
    """
    m = re.fullmatch(r"(sh|sz)(\d{6})", str(code))
    if not m:
        return ""
    return ("sz" if m.group(1) == "sh" else "sh") + m.group(2)


def _needs_resolution(raw: str) -> bool:
    """输入是「名称/拼音」而非代码时返回 True（需要先经搜索解析）。

    全大写字母串**不**走解析：`AAPL` 本身就是 ticker，再搜一次纯属多付一次
    往返（实测这一步约 130ms，是 us 兜底路径总耗时的一半），而且解析结果
    还可能被同名境外标的抢走。小写（`maotai`）与中文才当作自然语言写法。
    """
    s = str(raw).strip()
    if not s:
        return False
    if re.search(r"[\u4e00-\u9fff]", s):
        return True
    if re.match(r"(?i)^(sh|sz|bj|hk|us)", s):
        return False
    if re.fullmatch(r"[A-Z][A-Z.\-]{0,9}", s):   # 全大写：已是 ticker
        return False
    return bool(re.fullmatch(r"[A-Za-z]{2,10}", s))


_MARKET_PREFERENCE = ("sh", "sz", "bj", "hk")
# 名称→代码的映射几乎不变（上市公司改名是低频事件），落盘 24h；
# 走 invest-cli 统一的 _common 缓存，不另起第二套缓存文件。
_SEARCH_TTL = 86400.0


def search(keyword: str, limit: int = 10) -> list[dict]:
    """名称/代码/拼音搜索 → [{"market","code","symbol","name","type"}]。

    美股命中带交易所后缀（AAPL.OQ / TCEHY.PS），而行情接口只认不带后缀的形式，
    在**源头**剥掉后缀，下游不必各自踩这个坑。

    「没有命中」返回 `[]`，**通道故障抛 TencentError** —— 两者必须可分：
    前者可以如实告诉用户「没这个标的」，后者是我方通道问题，不该被读成
    「查无此标的」。原实现在这里 `except: return []`，两种情形在调用方看来一样。
    """
    kw = str(keyword or "").strip()
    if not kw:
        return []
    # 名称→代码的映射几乎不变，落盘 24h：中文名查询因此从「2 次往返」降到 1 次。
    # 走 invest-cli 统一的 _common 缓存，不另起第二套缓存文件。
    ckey = f"{kw}|{limit}"
    try:
        from _common import cache_get, cache_set
    except Exception:  # pragma: no cover
        cache_get = cache_set = None
    if cache_get:
        hit = cache_get("tencent_search", ckey, _SEARCH_TTL)
        if isinstance(hit, list):
            return hit
    url = f"{SEARCH_URL}?{urllib.parse.urlencode({'q': kw})}"
    try:
        payload = json.loads(_http_get(url))
    except json.JSONDecodeError as e:
        raise TencentError(f"搜索接口返回非 JSON: {e}") from e
    data = payload.get("data") or {}
    out = []
    for item in (data.get("stock") or [])[:limit]:
        if len(item) < 3:
            continue
        market, code, name = str(item[0]), str(item[1]), str(item[2])
        pure = code.split(".")[0] if market == "us" else code
        out.append({
            "market": market, "code": code, "symbol": f"{market}{pure}",
            "name": name, "type": (item[4] if len(item) > 4 else ""),
        })
    if cache_set:
        cache_set("tencent_search", ckey, out)
    return out


def resolve_name(name: str) -> str:
    """名称/拼音 → 符号，**境内市场优先**。

    同名标的常带境外版本：搜「沪深300」时命中的 usASHR 中文名干脆就是
    「沪深300 ETF-Xtrackers」，而接口给的中文排序不能改，只好在消费端重排。
    """
    hits = search(name, limit=5)
    for pref in _MARKET_PREFERENCE:
        for h in hits:
            if str(h.get("symbol", "")).startswith(pref):
                return str(h["symbol"])
    return str(hits[0].get("symbol", "")) if hits else ""


_PERIOD_ALIAS = {"d": "day", "day": "day", "daily": "day", "日": "day", "日线": "day",
                 "w": "week", "week": "week", "weekly": "week", "周": "week", "周线": "week",
                 "m": "month", "month": "month", "monthly": "month", "月": "month", "月线": "month",
                 "y": "year", "year": "year", "yearly": "year", "年": "year", "年线": "year"}


# ── 适配器对外接口 ────────────────────────────────────────────────────────

def _envelope(kind: str, ok: bool, data: Any = None, error: str = "") -> dict:
    return {"source": "tencent", "kind": kind, "ok": ok,
            "data": data if ok else None, "error": error or None}


def _resolve_one(raw: str) -> str:
    """名称/拼音 → 符号；已是代码则原样返回（不额外付一次往返）。

    解析不出**返回空串**而不是原样回吐：回吐会让上层把一个中文名当代码送进接口，
    接口不报错、只是不回那一行，于是「名字没解析出来」被读成「接口少给了一条」。
    通道故障则向上抛，与「没这个标的」区分开（见 search 的边界说明）。
    """
    s = str(raw).strip()
    if _needs_resolution(s):
        return resolve_name(s)
    return s


def _codes_for(raw: str) -> tuple[list[str], list[str]]:
    """名称/代码混合输入 → (规范化代码列表, 未解析成功的原始输入)。

    名称解析失败**不静默丢弃**，也不原样当成代码送出去：留在 unresolved 里让
    上层如实报出。解析过程中的通道故障同样归到这一项（带原因），
    因为对使用者而言结论都是「这个标的没查成」，但错误文案里能看出是哪种。
    """
    raw_list = [c for c in re.split(r"[,\s]+", str(raw or "").strip()) if c]
    resolved, unresolved = [], []
    for item in raw_list:
        try:
            sym = _resolve_one(item)
        except TencentError:
            unresolved.append(item)
            continue
        code = normalize_code(sym)
        if code:
            resolved.append(code)
        else:
            unresolved.append(item)
    return resolved, unresolved


def _fetch_with_alt(norm: list[str]) -> list[dict]:
    """取行情；对未命中的裸代码做**同号**换市场补查一次。"""
    rows, missing = quote_batch(norm)
    alts = [a for a in (_alt_market(c) for c in missing) if a and a not in norm]
    if alts:
        rows = rows + quote_batch(alts)[0]
    return rows


# ── stock：A股/港股快照（中文键，与同花顺/东财同一契约） ─────────────────────
# 键名按 cmd_stock.format_terminal 消费的别名表选：收盘价/最新价/现价 三别名任一命中
# 即渲染到「收盘价」行且标签跟着事实走。这里给「最新价」——qt 给的是最新价而不是收盘价，
# 印成「收盘价」就是失真（format_terminal 的注释专门写了这条）。
_STOCK_KEYS = {
    "price": "最新价", "open": "开盘价", "prev_close": "昨收",
    "high": "最高价", "low": "最低价",
    "amount": "成交额", "turnover_rate": "换手率", "range_pct": "振幅",
    "volume_ratio": "量比", "avg_price": "均价",
    "pe_ttm": "市盈率PE(TTM)", "pe_fwd": "市盈率PE(Forward)", "pe_lyr": "市盈率PE(静态)",
    "pb": "市净率PB", "mktcap": "总市值", "mktcap_circ": "流通市值",
    "price_ceiling": "涨停价", "price_floor": "跌停价",
    "w52_high": "52周最高", "w52_low": "52周最低", "dividend_ttm": "股息率TTM",
    "change": "涨跌额", "change_pct": "涨跌幅",
    "chg_ytd": "年初至今涨跌幅", "chg_5d": "5日涨跌幅", "chg_10d": "10日涨跌幅",
    "chg_20d": "20日涨跌幅", "chg_60d": "60日涨跌幅",
}
# 带百分号后缀的字段（其余是纯数值，加单位反而妨碍二次计算）
_STOCK_PCT = {"turnover_rate", "range_pct", "change_pct", "dividend_ttm",
              "chg_ytd", "chg_5d", "chg_10d", "chg_20d", "chg_60d", "roe"}


def stock(keyword: str) -> dict:
    """A股/港股快照（腾讯行情口径，**无基本面**）。

    调用方须知：本方法不返回净利润/ROE/EPS/资产负债率——腾讯行情接口没有这些。
    因此它不该出现在这两个 kind 的主位（会让快照从「13 项」退化成「纯行情」）；
    它的位置是兜底位。若上游富源失败而这里成功，`source=tencent` 会让用户看见
    当前拿到的是行情口径而非财务口径。
    """
    try:
        from _common import kind_from_code
    except Exception:  # pragma: no cover - 只在前端异常路径触发
        kind_from_code = None
    dom = kind_from_code(keyword) if kind_from_code else None
    if dom == "fund":
        # 基金代码与可转债号码共用号段：110011 既是基金（易方达中小盘）也是
        # 沪市可转债（歌华转债）。腾讯行情接口只认后者，直接查会**返回另一个标的**。
        # 措辞与 route.code_domain_error 对齐：同一条链上只该有一种说法
        return _envelope("stock", False,
                         error=f"「{keyword}」是基金代码，不是股票。请改用：invest-cli fund {keyword}")

    codes, unresolved = _codes_for(keyword)
    if not codes:
        return _envelope("stock", False, error=f"无法解析标的：{keyword}")
    try:
        rows = _fetch_with_alt(codes)
    except TencentError as e:
        return _envelope("stock", False, error=str(e))
    if not rows:
        return _envelope("stock", False, error=f"腾讯行情未返回 {keyword} 的数据")
    row = rows[0]
    if is_placeholder(row):
        return _envelope("stock", False, error=_placeholder_reason(row))
    data = {}
    if row.get("volume") is not None:
        # 单位分市场：A股接口给「手」（1 手 = 100 股），港美股给「股」。
        # 实测：sh600519 volume=24573 手（×100=246 万股，与成交额/均价反算一致）；
        # hk00700 volume=70723438 股（与 成交额/均价 454.821 反算一致）。
        # 把单位写进键名，而不是让下游去猜。
        data[f"成交量（{'手' if row.get('_market') == 'a' else '股'}）"] = row["volume"]
    for key, label in _STOCK_KEYS.items():
        val = row.get(key)
        if val is None:
            continue
        data[label] = f"{val}%" if key in _STOCK_PCT and key != "change_pct" else val
    if row.get("change_pct") is not None:
        # 只管百分比：东财/同花顺的「涨跌幅」键也是纯百分比，涨跌额另有其键。
        # 拼成「+1.23（+0.10%）」会让同名键在不同源下含义不同。
        data["涨跌幅"] = f"{row['change_pct']:+.2f}%"
    snap = {
        "source": "tencent",
        "kind": "stock",
        "code": str(row.get("code", "")),
        "name": str(row.get("name", "")),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "quote": {"last": row.get("price"), "open": row.get("open"),
                  "prev": row.get("prev_close")},
        "valuation": {"pe_ttm": row.get("pe_ttm"), "pb_mrq": row.get("pb")},
        "data": {k: v for k, v in data.items() if v is not None},
        "note": "腾讯行情口径：只有行情字段（无净利润/ROE/EPS 等基本面）",
    }
    if unresolved:
        # 未解析的入参必须留下痕迹，不能让调用方以为「就这些」
        snap["warnings"] = [f"未解析的入参：{', '.join(unresolved)}"]
    if row.get("time"):
        snap["quote_time"] = row["time"]
    return _envelope("stock", True, data=snap)


# ── us：美股快照（yfinance 载荷形状，由 cmd_us 的渲染器复用） ────────────────
# 为什么复用 yfinance 的形状而不是另起一套：cmd_stock.format_terminal 已经会把
# 「source=yfinance 且带 quote 分组」的载荷交给 cmd_us 的渲染器（一表多用）。
# 腾讯只填它真有的字段，缺的渲染成 `-`，不猜、不补。
def us(symbol: str) -> dict:
    """美股快照（腾讯行情口径）。单位对齐 yfinance 的约定，见下。"""
    codes, _unresolved = _codes_for(symbol)
    if not codes:
        return _envelope("us", False, error=f"无法解析美股标的：{symbol}")
    try:
        rows = _fetch_with_alt([codes[0]])
    except TencentError as e:
        return _envelope("us", False, error=str(e))
    if not rows:
        return _envelope("us", False, error=f"腾讯行情未返回 {symbol} 的数据")
    row = rows[0]
    if is_placeholder(row):
        return _envelope("us", False, error=_placeholder_reason(row))
    # 单位口径（与 yfinance 载荷一致，否则渲染器会算错一个数量级）：
    #   market_cap    yfinance 给绝对值；腾讯给「亿」→ ×1e8
    #   dividend_yield/roe  yfinance 给小数（0.0031 / 1.4875）；
    #                       腾讯给百分数（0.31 / 148.75）→ ÷100
    # 实测校对（AAPL，2026-09-22）：市值 49471.35 亿 → 4.947e12（yfinance 4.9471e12 ✓）
    #   股息率 0.31%→0.0031（yfinance 0.0031 ✓）ROE 148.75%→1.4875（yfinance 1.4875 ✓）
    quote: dict[str, Any] = {}
    if row.get("price") is not None:
        quote["price"] = row["price"]
    if row.get("change_pct") is not None:
        quote["change_pct"] = row["change_pct"]
    if row.get("pe_ttm") is not None:
        quote["pe_trailing"] = row["pe_ttm"]
    if row.get("pb") is not None:
        quote["pb"] = row["pb"]
    if row.get("dividend_ttm") is not None:
        quote["dividend_yield"] = round(row["dividend_ttm"] / 100.0, 6)
    if row.get("mktcap") is not None:
        quote["market_cap"] = round(row["mktcap"] * 1e8, 2)
    if row.get("w52_high") is not None:
        quote["high_52w"] = row["w52_high"]
    if row.get("w52_low") is not None:
        quote["low_52w"] = row["w52_low"]
    financial: dict[str, Any] = {}
    if row.get("roe") is not None:
        # ROE 在**载荷**里出现，不能只留在解析层：文档与 note 都声明了它，
        # 「解析出来但没落到快照上」= 声称的能力没兑现（独立验证正是这么发现的）。
        # 数值与 yfinance 的具名字段 roe 校对过：1.4875 → qt[57]=148.75 → 1.4875。
        financial["roe"] = round(row["roe"] / 100.0, 6)
    raw_code = str(row.get("code") or symbol)
    snap: dict[str, Any] = {
        "source": "tencent",
        # 美股行 [2] 带交易所后缀（AAPL.OQ），而 CLI 全域用裸 ticker（route 的缓存键、
        # 各 skill 文档、watchlist 都按裸 ticker 写）。带后缀会让同一标的在
        # 「quote 查一次、us 查一次」时看起来是两个东西；后缀另存 exchange_code。
        "symbol": raw_code.split(".")[0].upper(),
        "name": str(row.get("name", "")),
        "currency": "USD",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "quote": quote,
        # 能力边界写进载荷：缺的是什么，让下游一眼看见，不必回来读代码
        "note": "腾讯行情口径：价格/涨跌/高低/量额/换手/量比/均价/PE/PB/市值/52周/股息率/多周期涨跌；"
                "无营收/净利润/现金流/分析师评级",
    }
    if financial:
        snap["financial"] = financial
    if "." in raw_code:
        snap["exchange_code"] = raw_code
    if row.get("time"):
        snap["quote_time"] = row["time"]
    return _envelope("us", True, data=snap)


# ── 免鉴权批量行情（invest-cli quote 命令的数据面） ──────────────────────────
# 行情缓存 TTL：**故意比 route 层的快照缓存（60s）更短**。这条命令回答的是
# 「现在多少钱」，10s 是行情语境下可以忽略的陈旧度，同时让同一会话里的连续
# 批量查询（换几只标的再看一遍）不必重付一次往返。缓存里记了行情时间，
# 终端会把时间打出来，用户看得见这份数是什么时候的。
# 用 _common 的统一缓存（跨进程）：CLI 每次都是新进程，进程内缓存救不了日常调用，
# 这一点是被移植技能踩过的坑（known-issues ㉗ 实测跨进程复用 3.5×）。
_QUOTE_TTL = 10.0


def _domain_conflict(code: str, row: dict) -> str:
    """号码重叠检测：同一串数字既是场外基金又是交易所可转债时，接口只给后者。

    实测 2026-09-22：`quote(["sz110011"])` 回的是 `sh110011 歌华转债`，而用户问
    110011 时几乎总是指基金（易方达中小盘）。接口没有「品种」字段，但**名字里带
    品种**：转债名一律以「转债」结尾。这里用可观测的事实判冲突，判不出来就不判
    （宁缺勿错）——不要用「前缀像基金就拦」这类猜测，那会把正常的 ETF 查询
    （510300 按 _common.kind_from_code 也判 fund，但接口给的就是它）一起误伤。
    """
    if not re.fullmatch(r"\d{6}", str(code).strip()):
        return ""
    try:
        from _common import kind_from_code
    except Exception:
        return ""
    if kind_from_code(code) != "fund":
        return ""
    name = str(row.get("name") or "")
    if "转债" not in name:
        return ""
    return (f"{code} 既是场外基金代码也是沪市可转债号码，行情接口只覆盖后者"
            f"（返回的是「{name}」）。若你要的是基金：invest-cli fund {code}")


def _index_probe_symbols(codes: list[str]) -> dict[str, str]:
    """同号重叠探针：{请求代码: 同日同号的沪市指数代码}。

    为什么需要：沪市指数用 `000xxx`（000001 上证指数、000300 沪深300），深市主板股票
    也用 `000xxx`（000001 平安银行）。裸写 6 位数字时接口按股票推断，**拿到的是股票、
    指数被放弃，且不给任何提示**——与 `_domain_conflict` 处理「基金 vs 可转债」的
    态度自相矛盾（同一类歧义两种待遇，独立验证抓到的正是这处不一致）。
    而 `000001` 是三义的：沪指 sh000001、平安银行 sz000001、场外基金 000001。

    判据**不靠猜**：指数到底存不存在，用接口自己回答。同一次批量请求里多带一个代码
    的代价可忽略（实测 6 个标的 189ms vs 1 个标的 187ms），拿不到行就**不发提示**
    （宁缺勿错：宁可不说，也不告诉用户「这也是指数」而其实不是）。

    与 `_alt_market` 的分工（同号问题的两种情况，别重复实现）：
    - 只在一边存在（`000300`：sz 没有这只股票、sh000300 是沪深300）→ `_alt_market` 补查，
      直接给用户那个能用的一边，这是**取值**问题；
    - 两边都有（`000001`：sz000001 平安银行 + sh000001 上证指数）→ 接口按股票推断、
      指数的解释被丢掉，这是**告知**问题，本函数处理。
    """
    out: dict[str, str] = {}
    for c in codes:
        m = re.fullmatch(r"sz(000\d{3})", str(c))
        if m:
            out[c] = "sh" + m.group(1)
    return out


def _index_conflict(probe: str, probe_row: dict, got_symbol: str) -> str:
    """重叠成立时的提示文案。只在探针**真的取到行情**时调用。"""
    name = str(probe_row.get("name") or "").strip()
    label = f"「{name}」" if name else ""
    return (f"{probe[-6:]} 同时也是沪市指数 {probe}{label}；本次按 {got_symbol} 取"
            f"——要指数请写 {probe}")


def quote(codes: str, fields: Optional[list[str]] = None) -> dict:
    """多标的实时行情（一次 HTTP 请求，跨市场）。返回信封。

    与 `stock()`/`us()` 的分工：那两个产**快照**（要能被表格渲染、要能与富源
    对比），本方法产**行情**（快、批量、纯数值），供「现在多少钱」这类问题。
    """
    codes, unresolved = _codes_for(codes)
    if not codes:
        return _envelope("quote", False, error="没有可查询的标的（代码或名称）")
    requested = list(codes)
    requested_set = set(requested)
    # 探针代码随请求一起取，但**不进结果表**：它只用来回答「同号还有没有别的标的」。
    probes = _index_probe_symbols(requested)
    fetch_codes = requested + [p for p in probes.values() if p not in requested_set]
    keys = ",".join(sorted(fetch_codes))
    try:
        from _common import cache_get, cache_set
    except Exception:  # pragma: no cover
        cache_get = cache_set = None
    cached = False
    rows: list[dict] = []
    missing: list[str] = []
    if cache_get:
        hit = cache_get("tencent_quote", keys, _QUOTE_TTL)
        if isinstance(hit, dict) and isinstance(hit.get("rows"), list):
            rows, missing, cached = hit["rows"], list(hit.get("missing") or []), True
    if not cached:
        try:
            rows = _fetch_with_alt(fetch_codes)
        except TencentError as e:
            return _envelope("quote", False, error=str(e))
        got = {r["symbol"] for r in rows}
        # missing 只统计**用户真问的**代码：探针没取到不是「缺数据」，是「没这回事」
        missing = [c for c in requested if c not in got]
        if cache_set:
            cache_set("tencent_quote", keys, {"rows": rows, "missing": missing})
    out = []
    no_quote: list[dict] = []
    conflicts: list[str] = []
    by_symbol = {r.get("symbol"): r for r in rows}
    # 探针行要藏起来，但它也可能是「同号换市场」补查的结果 —— 用户问 `000300` 时
    # sz000300 不存在、sh000300（沪深300）就是他要的答案，藏掉会让本来能答的查询变成
    # 「未返回任何标的」（我第一版就踩了这个：`quote 000300` 从正常返回退化成 rc=1）。
    # 判据：**请求的那个同号代码自己也回行**，这一行才是纯探针。
    got_symbols = {r.get("symbol") for r in rows}
    probe_set = {p for c, p in probes.items()
                 if p not in requested_set and c in got_symbols}
    for r in rows:
        symbol = r.get("symbol")
        if symbol in probe_set:
            # 探针行不是用户要的标的：既不进 quotes，也不该落进 no_quote
            continue
        if is_placeholder(r):
            # 不把占位行当行情：单独列出并说明原因，字段名用 last_close 以免被当成现价
            no_quote.append({"symbol": r.get("symbol"), "name": r.get("name"),
                             "last_close": r.get("price"), "reason": _placeholder_reason(r)})
            continue
        item = {k: v for k, v in r.items() if k != "_market"}
        if fields:
            item = {k: v for k, v in item.items() if k in fields or k in ("symbol", "name")}
        # 号码重叠时**不静默换标的**：数值照给（接口确实只覆盖后者），
        # 但把冲突写在行内并在信封顶层汇总，让调用方无法忽略。
        warns = []
        warn = _domain_conflict(str(r.get("code") or r.get("symbol") or ""), r)
        if warn:
            warns.append(warn)
        probe = probes.get(symbol)
        # 只在「拿到的是用户写的那个代码」时提示：若结果本身就是换市场补查来的指数，
        # 或用户已经把两个写法都写上了，提示就是噪音。
        if probe and symbol in requested_set and probe not in requested_set:
            probe_row = by_symbol.get(probe)
            # 三种情况都不发提示：探针没回、探针是占位行、探针没有名字（拿不准就别断言）
            if probe_row and not is_placeholder(probe_row) and probe_row.get("name"):
                warns.append(_index_conflict(probe, probe_row, str(symbol)))
        if warns:
            item["code_domain_warning"] = "；".join(warns)
            conflicts.extend(warns)
        out.append(item)
    if not out:
        if no_quote:
            return _envelope("quote", False, error="; ".join(n["reason"] for n in no_quote))
        return _envelope("quote", False,
                         error=f"腾讯行情未返回任何标的：{', '.join(requested)}")
    data = {"quotes": out, "count": len(out)}
    if no_quote:
        data["no_quote"] = no_quote
    if conflicts:
        data["conflicts"] = conflicts
    if missing:
        data["missing"] = missing
    if unresolved:
        data["unresolved"] = unresolved
    if cached:
        data["cached"] = True
    return _envelope("quote", True, data=data)


def _aggregate_years(months: list[dict]) -> list[dict]:
    """月K → 年K（按自然年）。开=首月开，收=末月收，高/低=极值，量=累加。

    为什么必须自己合：接口的 `year` 周期**只回 1 根**，实测 `param=sh600519,year,,,12,qfq`
    返回的 key 是 `year`、内容 1 根，数值等于**当日**的 OHLC（开 1252.15 / 高 1265.88 /
    低 1248.1 / 收 1253.8 / 量 24573，与当天日线逐位相同）。直接透传出去，用户问年线
    会拿到一根标着「2026-09-22」的当日 K 线 —— 被移植实现为此专门写了聚合
    （它自己的 known-issues ⑯），我在首版移植里漏掉了，验证时被抓出来。
    """
    buckets: dict[str, list[dict]] = {}
    for m in months:
        buckets.setdefault(str(m["date"])[:4], []).append(m)
    out = []
    for year in sorted(buckets):
        bars = buckets[year]
        out.append({
            "date": bars[-1]["date"],
            "open": bars[0]["open"],
            "close": bars[-1]["close"],
            "high": max(b["high"] for b in bars),
            "low": min(b["low"] for b in bars),
            "volume": round(sum(b["volume"] for b in bars), 4),
        })
    return out


def kline(code: str, period: str = "day", limit: int = 60) -> dict:
    """K 线（日/周/月/年，前复权）。period 见 `_PERIOD_ALIAS`。"""
    code_n = normalize_code(_resolve_one(code))
    if not code_n:
        return _envelope("kline", False, error="空代码")
    raw_period = str(period).lower()
    if raw_period not in _PERIOD_ALIAS:
        # 不许静默降级：原实现把未知周期一律当 day，于是「要季线拿到日线」，
        # 而且因为结果非空，上层精心设计的 CLI 兜底永远走不到
        # （westock CLI 确实支持 season 等更多周期）。这里如实报错，让调用方降级。
        return _envelope("kline", False,
                         error=f"腾讯 K线不支持周期 {period!r}：原生命中内核只有 day/week/month/"
                               f"year（及中文别名 日/周/月/年）。season 与分钟级 m1…m120 由 "
                               f"westock CLI 提供，`invest-cli kline` 会自动转过去")
    period = _PERIOD_ALIAS[raw_period]
    limit = max(1, min(int(limit or 60), 2000))
    # K线按日更新，落盘 300s：同一会话里反复看同一标的的走势不必重取。
    # 与 quote 相反，这里**没有**陈旧度问题（日线当日内不变，最新一根的收盘前
    # 会变，故不取更长 TTL）。
    ckey = f"{code_n}|{period}|{limit}"
    try:
        from _common import cache_get, cache_set
    except Exception:  # pragma: no cover
        cache_get = cache_set = None
    if cache_get:
        hit = cache_get("tencent_kline", ckey, 300.0)
        if isinstance(hit, dict) and hit.get("rows"):
            return _envelope("kline", True, data={**hit, "cached": True})
    # 年线：接口给不出多年序列，必须由月K按自然年聚合（见 _aggregate_years）
    fetch_period, fetch_limit = period, limit
    if period == "year":
        fetch_period, fetch_limit = "month", min(limit * 12 + 12, 2000)
    param = f"{code_n},{fetch_period},,,{fetch_limit},qfq"
    url = f"{KLINE_URL}?param={urllib.parse.quote(param, safe=',')}"
    try:
        payload = json.loads(_http_get(url))
    except (TencentError, json.JSONDecodeError) as e:
        return _envelope("kline", False, error=f"K线取数失败: {e}")
    node = (payload.get("data") or {}).get(code_n) or {}
    # 复权序列挂在 `<fq><period>` 键下（qfq → qfqday / qfqmonth），不复权才是裸 period。
    # 原实现取裸 period，于是**默认前复权的调用永远取不到数据**（known-issues ⑩）。
    series = node.get(f"qfq{fetch_period}") or node.get(fetch_period) or []
    rows = []
    for bar in series:
        if not isinstance(bar, (list, tuple)) or len(bar) < 6:
            continue
        try:
            rows.append({"date": str(bar[0]), "open": float(bar[1]), "close": float(bar[2]),
                         "high": float(bar[3]), "low": float(bar[4]), "volume": float(bar[5])})
        except (TypeError, ValueError):
            continue
    if period == "year":
        rows = _aggregate_years(rows)
    # 接口按「count」给的是**含起始那一根**的窗口，实测 count=5 回 6 根、count=60 回 61 根。
    # 裁到调用方要的根数，与 CLI `--limit N` 的行为对齐；否则分页取历史时
    # 每页都会多一根，跨页拼接会出现重复。
    rows = rows[-limit:]
    if not rows:
        return _envelope("kline", False, error=f"腾讯 K线未返回 {code} 的数据")
    qt = (node.get("qt") or {}).get(code_n) or []
    # 复权口径写进载荷，而不只写在终端文案里：机器消费方（skill/脚本）拿到的 JSON
    # 也必须自带这个说明。前复权适合算区间收益，**不等于**当日真实成交价 ——
    # 被移植实现正是把历史某日的前复权价当成真实成交价用的（它的审计里 F13）。
    data = {"symbol": code_n, "period": period, "fq": "qfq", "rows": rows,
            "name": qt[1] if len(qt) > 1 else ""}
    if cache_set:
        cache_set("tencent_kline", ckey, data)
    return _envelope("kline", True, data=data)


# ── 可用性探测 ────────────────────────────────────────────────────────────
# 零鉴权意味着「不需要凭据」，但不等于「一定连得上」。判据必须与取数用同一条
# 通道：探一个固定标的，拿到 HTTP 响应且解析出名字才算可用。
# 冷探测成本 = 一次往返（~130ms），比 yfinance 的 2s HTTPS 探测低一个量级；
# registry 会把它缓存（成功 300s / 失败 120s，落盘），所以不是每次调用都付。
_PROBE_CODE = "sh000001"   # 上证指数：永远存在，不依赖任何用户输入


def detect() -> tuple[bool, str]:
    """真实可达性探测（不是「有没有装」）。"""
    try:
        rows, _missing = quote_batch([_PROBE_CODE])
    except TencentError as e:
        return False, f"腾讯行情不可达（{e}）"
    if not rows:
        return False, "腾讯行情可达但未返回上证指数，接口口径可能已变"
    return True, f"腾讯行情可用（{rows[0].get('name', '')}）"
