#!/usr/bin/env python3
"""天天基金数据适配器（invest-cli 数据源，直连 gateway，不依赖 ttskill CLI）。

能力：公募基金结构化快照（默认深取层，对应 invest-fund/references/data-pipeline.md）：
  - 名称/代码解析（TTFUND_SEARCH）
  - 详情+业绩+风险族（夏普/波动/回撤+成立来）+费率梯度+业绩基准（TTFUND_BASE_INFOS）
  - 十大重仓/行业/资产配置 + 报告期（TTFUND_HOLDING_INFO）

约定（与 data-pipeline.md 互为镜像，改映射必须两边同步）：
  - 返回信封对齐 route.fetch：{source, kind, ok, data, error}
  - 快照 schema 对齐 cmd_fund.format_terminal（data 用中文键；holdings 用 stock_name/hold_ratio）

取数路径：**直连官方 gateway**（POST /openapi/skill/invoke），不再起 ttskill 子进程。
  - 认证沿用官方凭据存储（macOS Keychain `com.ttfund.ttskill.base`，兼容 auth/*.json 回退），
    用 ed25519 设备密钥签请求头（与官方基础包同一套认证逻辑，不新造）。
  - 不再依赖官方 CLI 二进制；只依赖「已登录一次」的凭据。

口径（110011 实测 2026-09-03，勿按旧文档改）：
  - BASE：body.expansion.comprehensive_info.fund_profile_overview.{FTYPE,SHORTNAME,FULLNAME,ENDNAV(元),ESTABDATE,JJGS,JJJL,BENCH}
  - 风险在 unique_info[0]（数组首元素，不是对象）；卡玛无直出 = 近1年收益 ÷ |近1年最大回撤|
  - 阶段涨幅 period_increase[]：title∈{Y=近1月,3Y=近3月,6Y=近6月,1N=近1年,2N,3N,5N,JN=今年来,LN=成立来}，Z=近1周不展示
  - 费率 purchase/redeem/service 在 body.expansion.trade_info.fee_rates；管理费/托管费接口不返回
  - HOLDING 有 body.data 包装；QDII 等顶层 top_holdings.stocks 可能为空 → 从 data.periods[-1] 取
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

SOURCE_LABEL = "天天基金"

# ═══ 官方认证（沿用官方凭据存储，不新造）═══
GATEWAY = "https://skills-api.tiantianfunds.com/ai-smart-skill-service"
INVOKE_PATH = "/openapi/skill/invoke"
KEYCHAIN_SERVICE = "com.ttfund.ttskill.base"
RUNTIME_HOME = Path.home() / "Library" / "Application Support" / "TTFund" / "ttfund-skills"
SKILLS_INDEX = RUNTIME_HOME / "skills" / "index.json"
INVOKE_TIMEOUT = 30

# period_increase.title → 展示标签（110011 实测值反推；Z=近1周不进快照）
PERIOD_LABELS = {
    "Y": "近1月回报", "3Y": "近3月回报", "6Y": "近6月回报",
    "1N": "近1年回报", "2N": "近2年回报", "3N": "近3年回报",
    "5N": "近5年回报", "JN": "今年来回报", "LN": "成立来回报",
}
RISK_DISPLAY = {  # unique_info[0] 键 → cmd_fund 展示键
    "STDDEV1": "波动率", "SHARP1": "夏普比率", "MAXRETRA1": "最大回撤",
}


def _b64url(data: bytes) -> str:
    return base64.b64encode(data).decode().replace("+", "-").replace("/", "_").rstrip("=")


def _keychain_account(record: str, legacy_path: str) -> str:
    """官方 Keychain 账户名：`<record>:<legacy_path 的 sha256 前 16 位>`。"""
    return f"{record}:{hashlib.sha256(legacy_path.encode()).hexdigest()[:16]}"


# 凭据在进程生命周期内不会变（CLI 每进程只跑一条命令）：缓存一次，避免每次
# `_invoke` 都重跑 `security find-generic-password`（fund 深取会调 2 次）。
_CRED_CACHE: dict[str, dict[str, Any] | None] = {}


def _read_credential(record: str) -> dict[str, Any] | None:
    """读官方凭据：macOS Keychain 优先，兼容 auth/*.json 回退。

    只读不回显；任何失败都返回 None（调用方按未登录处理）。
    注意：record 是内部名（token/deviceKey），Keychain 账户前缀是官方名（token/device-key）。
    """
    if record in _CRED_CACHE:
        return _CRED_CACHE[record]
    acct_prefix, filename = {
        "token": ("token", "token.json"),
        "deviceKey": ("device-key", "device-key.json"),
    }.get(record, (record, f"{record}.json"))
    legacy = RUNTIME_HOME / "auth" / filename
    result: dict[str, Any] | None = None
    if sys.platform == "darwin":
        acct = _keychain_account(acct_prefix, str(legacy))
        try:
            proc = subprocess.run(
                ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", acct, "-w"],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                data = json.loads(proc.stdout.strip())
                if isinstance(data, dict):
                    result = data
        except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
            result = None
    if result is None:
        try:
            if legacy.is_file():
                data = json.loads(legacy.read_text(encoding="utf-8"))
                result = data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            result = None
    _CRED_CACHE[record] = result
    return result


def _jwt_exp(token: str) -> int:
    """从 JWT 里取 exp（不验签，只读声明）。"""
    parts = (token or "").split(".")
    if len(parts) < 2:
        return 0
    text = parts[1].replace("-", "+").replace("_", "/")
    text += "=" * (4 - len(text) % 4) if len(text) % 4 else ""
    try:
        return int(json.loads(base64.b64decode(text)).get("exp", 0) or 0)
    except Exception:
        return 0


def _token_state() -> tuple[bool, str]:
    """返回 (是否可用, 说明)。判据是「有 token 且未过期」，不是「文件在磁盘上」。"""
    token = _read_credential("token")
    if not token:
        return False, "未登录天天基金（缺 token 凭据）"
    if not _read_credential("deviceKey"):
        return False, "缺少设备密钥凭据（device-key）"
    access = token.get("access_token") or token.get("accessToken") or ""
    if not access:
        return False, "凭据里没有 access_token"
    exp = _jwt_exp(access) or int(token.get("saved_at", 0) or 0) + int(token.get("expires_in", 0) or 0)
    if exp and exp <= int(time.time()):
        return False, f"登录已过期（{time.strftime('%Y-%m-%d', time.gmtime(exp))}）"
    return True, "已登录"


def detect() -> tuple[bool, str]:
    """可用性 = 有凭据且未过期，且本机至少装了一个业务包。

    旧实现跑 `ttskill status --json` 子进程（~0.3s/次，且要 CLI 在 PATH）；
    这里直接读凭据 + 读已装包索引，零子进程。
    """
    ok, detail = _token_state()
    if not ok:
        return False, detail
    if not _installed_skills():
        return False, "已登录但未安装业务包"
    return True, detail


def _installed_skills() -> dict[str, str]:
    """已装业务包 {skill_id: version}，取自官方 skills/index.json（不跑 CLI）。"""
    try:
        data = json.loads(SKILLS_INDEX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    # index.json 形状为 {"skills": [...]}（旧版可能是裸数组，两种都收）
    items = data.get("skills") if isinstance(data, dict) else data
    out: dict[str, str] = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        sid = item.get("skill_id")
        if sid and str(item.get("status", "enabled")) != "disabled":
            out[str(sid)] = str(item.get("version") or "0.0.0")
    return out


def _sign_headers(method: str, path: str, body: bytes, session_id: str, private_key_pem: str) -> dict[str, str]:
    """ed25519 签名头（与官方基础包同一套认证逻辑）。"""
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    body_sha = hashlib.sha256(body).hexdigest()
    sign_path = path
    prefix = "/ai-smart-skill-service"
    if sign_path.startswith(prefix + "/openapi/"):
        sign_path = sign_path[len(prefix):]
    payload = f"{method.upper()}\n{sign_path}\n{body_sha}\n{timestamp}\n{nonce}\n{session_id}".encode()
    key = load_pem_private_key(private_key_pem.encode(), password=None)
    return {
        "X-Session-Id": session_id,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Body-SHA256": body_sha,
        "X-Signature": _b64url(key.sign(payload)),
    }


def _invoke(skill_id: str, body: dict[str, Any], action: str = "query") -> dict[str, Any]:
    """直连 gateway 调业务包 → body 信封。失败抛 RuntimeError。

    与 `ttskill invoke` 等价，但少一次子进程与一次 JSON 往返。
    版本从本机 index.json 取（官方 CLI 也这么做）；409 时用服务端 latest 重试一次。
    """
    token = _read_credential("token")
    key_info = _read_credential("deviceKey")
    if not token or not key_info:
        raise RuntimeError("未登录天天基金（缺凭据），请先完成一次官方登录")
    access = token.get("access_token") or token.get("accessToken") or ""
    session_id = token.get("session_id") or token.get("sessionId") or ""
    if not access or not session_id:
        raise RuntimeError("登录态无效（缺 access_token/session_id），请重新登录")
    pem = key_info.get("device_private_key_pem") or ""
    if not pem:
        raise RuntimeError("设备密钥凭据损坏（缺 device_private_key_pem），请重新登录")
    version = _installed_skills().get(skill_id, "0.0.0")

    def _post(ver: str) -> dict[str, Any]:
        payload = {**body, "skill_id": skill_id, "_skill_version": ver, "action": action}
        data = json.dumps(payload, ensure_ascii=False).encode()
        headers = {
            "Content-Type": "application/json",
            "X-TTSkill-Env": "prod",
            "Authorization": f"Bearer {access}",
            **_sign_headers("POST", INVOKE_PATH, data, session_id, pem),
        }
        req = urllib.request.Request(GATEWAY + INVOKE_PATH, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=INVOKE_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))

    try:
        payload = _post(version)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        if e.code == 401:
            raise RuntimeError("天天基金登录已失效，请重新登录") from e
        if e.code == 409 and "skill_version_required" in err_body:
            # 本地版本落后于 gateway：用响应里的 latest 重试一次
            try:
                meta = json.loads(err_body)
            except json.JSONDecodeError:
                meta = {}
            latest = (meta.get("latest_version") or meta.get("skill_version_required")
                      or (meta.get("data") or {}).get("latest_version"))
            if latest and str(latest) != str(version):
                payload = _post(str(latest))
            else:
                raise RuntimeError(f"{skill_id} 业务包版本不匹配：{err_body[:200]}") from e
        else:
            raise RuntimeError(f"{skill_id} 调用失败 HTTP {e.code}: {err_body[:200]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"天天基金 gateway 不可达: {e}") from e

    if payload.get("code") not in (0, None):
        raise RuntimeError(f"{skill_id} 调用失败: {str(payload.get('message'))[:200]}")
    raw = ((payload.get("data") or {}).get("raw_result") or {}).get("body") or {}
    ec = raw.get("errorCode")
    # 成功码各包不一：BASE/HOLDING 用 0，GOLD 等用 200；以 success=false 或 code∉{0,200} 判失败
    if raw.get("success") is False or (ec is not None and ec not in (0, 200)):
        raise RuntimeError(f"{skill_id} 业务失败: {(raw.get('message') or raw.get('firstError') or ec or '')[:200]}")
    return raw


def _num(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _common_run(a: str, b: str) -> int:
    """最长公共连续子串长度（防模糊解析 fail-open：垃圾名会被服务端配到无关基金）。"""
    best = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            best = max(best, k)
    return best


def resolve_fcode(keyword: str) -> tuple[str, str]:
    """名称/代码 → (fcode, name)。6 位代码直通；名称 SEARCH 结果必须与查询相关。"""
    kw = (keyword or "").strip()
    if kw.isdigit() and len(kw) == 6:
        return kw, kw
    raw = _invoke("TTFUND_SEARCH", {"query": kw, "search_type": "fund", "page_index": 1, "page_size": 5})
    cands = (((raw.get("data") or {}).get("candidates")) or [])
    threshold = max(2, min(3, sum(1 for ch in kw if "\u4e00" <= ch <= "\u9fff")))
    for c in cands:
        name = c.get("name") or ""
        if (c.get("display_code") or "").isdigit() and _common_run(kw, name) >= threshold:
            return c["display_code"], name or kw
    raise RuntimeError(f"基金搜索无相关候选: {kw}")


def _base_snapshot(code: str) -> dict[str, Any]:
    raw = _invoke("TTFUND_BASE_INFOS", {"fcode": code, "nav_range": "n"})
    ci = (raw.get("expansion") or {}).get("comprehensive_info") or {}
    fpo = ci.get("fund_profile_overview") or {}
    ui = (ci.get("unique_info") or [{}])[0] if isinstance(ci.get("unique_info"), list) else (ci.get("unique_info") or {})
    fees = ((raw.get("expansion") or {}).get("trade_info") or {}).get("fee_rates") or {}

    d: dict[str, Any] = {}
    for k, label in [("FTYPE", "基金类型"), ("ESTABDATE", "成立日期"), ("JJGS", "基金管理人")]:
        if fpo.get(k):
            d[label] = fpo[k]
    if fpo.get("SHORTNAME"):
        d["基金名称"] = fpo["SHORTNAME"]
    if fpo.get("ENDNAV") is not None:  # 元 → 保留数值，展示层 ≥1e8 自动换亿
        d["基金规模"] = _num(fpo["ENDNAV"])
    for t, label in PERIOD_LABELS.items():
        for row in ci.get("period_increase") or []:
            if str(row.get("title")) == t and row.get("syl") is not None:
                d[label] = _num(row["syl"])
                # 同类分位 = rank/sc（越小越好），data-pipeline.md 口径；只取风险审查最常用的两个周期
                rank, sc = row.get("rank"), row.get("sc")
                if label in ("近1年回报", "近3年回报") and rank is not None and sc is not None:
                    d[label.replace("回报", "同类分位")] = f"{rank}/{sc}"
                break
    for key, label in RISK_DISPLAY.items():
        if ui.get(key) is not None:
            d[label] = _num(ui[key])
    if ui.get("JGBL") is not None:
        # 机构占比%（fund_holder_structure[].JGBL 同源）；非风险指标，单独映射
        d["机构占比"] = _num(ui["JGBL"])
    y1 = d.get("近1年回报")
    mdd = d.get("最大回撤")
    if y1 is not None and mdd is not None and mdd:
        # 卡玛 = 近1年收益 ÷ |最大回撤幅度|：带符号（亏损期应为负），不能用 abs 抹掉
        d["卡玛比率"] = round(y1 / abs(mdd), 2)
    mgr = (fpo.get("JJJL") or "").split(",")[0].strip()
    if mgr:
        d["经理姓名"] = mgr
    if fees.get("purchase"):
        rates = [r for r in fees["purchase"] if isinstance(r, dict)]
        if rates:
            rate = rates[0].get("rate")
            src = rates[0].get("source")
            d["申购费率"] = rate if rate is not None else src
    return d


def _holding_list(code: str) -> tuple[list[dict[str, Any]], str, str]:
    raw = _invoke("TTFUND_HOLDING_INFO", {"fund_id": code, "holding_type": "stock", "period_mode": "latest"})
    data = raw.get("data") or {}
    ho = data.get("holding_overview") or {}
    report_date = ho.get("report_date") or ""
    periods = data.get("periods") or []
    top = data.get("top_holdings") or {}
    stocks = top.get("stocks") or []
    industry = data.get("industry_allocation") or []
    if not stocks and periods:
        latest = periods[-1]
        stocks = ((latest.get("top_holdings") or {}).get("stocks")) or []
        industry = latest.get("industry_allocation") or industry
        report_date = latest.get("report_date") or report_date
    industry_ratio = ""
    if industry:
        top_ind = max(industry, key=lambda r: _num(r.get("ZJZBL")) or 0)
        industry_ratio = f"{top_ind.get('HYMC', '')} {top_ind.get('ZJZBL', '')}%"
    rows = []
    for s in stocks[:10]:
        rows.append({
            "entityName": s.get("GPJC", ""),
            "stock_name": s.get("GPJC", ""),
            "hold_ratio": _num(s.get("JZBL")),
            "change": s.get("PCTNVCHGTYPE", ""),
        })
    return rows, report_date, industry_ratio


def invoke_scene(skill_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """通用场景透传（intent 等上层用）：调官方业务包并原样返回 body。"""
    try:
        raw = _invoke(skill_id, body)
        return {"source": "ttskill", "kind": skill_id, "ok": True, "data": raw, "error": None}
    except Exception as e:  # noqa: BLE001
        return {"source": "ttskill", "kind": skill_id, "ok": False, "data": None, "error": str(e)}


def fund(keyword: str) -> dict[str, Any]:
    """fund 数据源入口：route.fetch 整单调用，失败抛异常由 route 回退。"""
    try:
        code, name = resolve_fcode(keyword)
        # BASE 与 HOLDING 是两条独立的 ttskill 子进程调用（各含一次 CLI 冷启动），
        # 串行等于把两段等待相加；拿到 code 后两者无依赖，并发提交。
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_base = pool.submit(_base_snapshot, code)
            f_hold = pool.submit(_holding_list, code)
            d = f_base.result()
            holdings, report_date, industry = f_hold.result()
        if not d.get("基金类型"):
            d["基金类型"] = "未知（ttskill 未返回类型）"
        data = {
            "code": code,
            "name": name if not name.isdigit() else d.get("基金名称") or name,
            "timestamp": datetime.now().isoformat(),
            "source_label": SOURCE_LABEL,
            "warnings": [
                "管理费/托管费 ttskill 不返回，需 f10 档案页补查",
                f"持仓报告期 {report_date or '未知'}（滞后一季属正常）",
            ] if report_date else ["报告期未返回"],
            "data": d,
            "holdings": holdings,
        }
        if report_date:
            data["report_date"] = report_date
        if industry:
            data["top_industry"] = industry
        return {"source": "ttskill", "kind": "fund", "ok": True, "data": data, "error": None}
    except Exception as e:  # noqa: BLE001 —— 路由层需要字符串化错误以回退
        return {"source": "ttskill", "kind": "fund", "ok": False, "data": None, "error": str(e)}


if __name__ == "__main__":  # 快速自检：python3 sources/ttskill.py 110011
    code = sys.argv[1] if len(sys.argv) > 1 else "110011"
    print(json.dumps(fund(code), ensure_ascii=False, indent=2, default=str)[:1500])
