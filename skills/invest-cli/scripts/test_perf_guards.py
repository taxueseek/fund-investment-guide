"""性能与可用性判据的回归守卫 — 不联网（探针与上游被 monkeypatch）。

守护的是「**判据与真实能力脱节**」这一类缺陷：每条都对应一个曾经真实发生、
且会造成用户可感知损失的行为。

1. 「装了就算可用」的假阳性 —— 让不可达的源排进快照链首位，每次调用先烧满
   库内写死的 30s 超时再回退（实测 31.3s vs 1.0s）。
2. 探针必须**有界** —— 探针自身超时若比数据源还长，探测就成了新瓶颈。
3. 探针失败必须 **fail-open** —— 探测本身出错不能误杀可能好用的源。
4. 缺配置的错误不能被吞成「数据为空」—— 用户会去查数据而不是查配置。
5. 缓存必须真的是单真源、原子写、且**有生产调用者** —— 曾被
   「宣称有缓存、全仓零调用者」坑过。
6. 补丁必须**真的生效** —— yfinance 超时收紧曾是一段完全无效的死代码，
   所以这里有计时断言，而不是「函数被调用过」。

缓存/状态目录隔离与探测缓存清空由 conftest.py 统一提供（见该文件说明）。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent

from sources import registry  # noqa: E402

# ── 1. 可达性判据：不可达的 python 源必须被判不可用

def test_unreachable_python_module_is_not_available(monkeypatch) -> None:
    """端点不可达时，装了模块也必须判为不可用（否则回退链被白白拖慢）。"""
    pytest.importorskip("yfinance")  # 无此模块时 find_spec 短路，_probe_http 永不触发，用例失去意义
    registry._PROBE_CACHE.clear()
    monkeypatch.setattr(registry, "_probe_http", lambda url, timeout=2.0: (False, "URLError"))

    ok, detail = registry._probe_python("yfinance")
    assert ok is False, "不可达的源被判可用 = 每次调用都要付满上游超时"
    assert "不可达" in detail


def test_reachable_python_module_is_available(monkeypatch) -> None:
    """可达时必须判可用 —— 守卫不能反过来把好源误杀（防止修成一律拒绝）。"""
    pytest.importorskip("yfinance")  # 无此模块时 find_spec 短路，_probe_http 永不触发，用例失去意义
    registry._PROBE_CACHE.clear()
    monkeypatch.setattr(registry, "_probe_http", lambda url, timeout=2.0: (True, "HTTP 200"))

    ok, detail = registry._probe_python("yfinance")
    assert ok is True
    assert "可用" in detail


def test_missing_module_is_unavailable_without_probing(monkeypatch) -> None:
    """没装模块时不必（也不该）发起网络探测。"""
    registry._PROBE_CACHE.clear()
    called = {"n": 0}

    def _spy(url, timeout=2.0):
        called["n"] += 1
        return True, "HTTP 200"

    monkeypatch.setattr(registry, "_probe_http", _spy)
    ok, detail = registry._probe_python("definitely_not_installed_module_xyz")
    assert ok is False
    assert "未安装" in detail
    assert called["n"] == 0, "未安装就不该发探测请求"

# ── 2. 探针必须有界

def test_http_probe_timeout_is_bounded() -> None:
    """探针预算必须显著小于数据源自身的连接超时（Yahoo 库内写死 30s）。"""
    assert registry.HTTP_PROBE_TIMEOUT <= 3.0, (
        "探针超时过长会把探测本身变成新瓶颈"
    )


def test_probe_result_is_cached(monkeypatch) -> None:
    """同进程内探针结果必须复用，避免每次调用都付一次网络往返。"""
    pytest.importorskip("yfinance")  # 无此模块时 find_spec 短路，_probe_http 永不触发，用例失去意义
    calls = {"n": 0}

    def _spy(url, timeout=2.0):
        calls["n"] += 1
        return True, "HTTP 200"

    monkeypatch.setattr(registry, "_probe_http", _spy)
    registry._probe_python("yfinance")
    registry._probe_python("yfinance")
    assert calls["n"] == 1, "探针未缓存 = 每次取数都多付一次 RTT"


def test_probe_result_persists_across_processes(monkeypatch, tmp_path) -> None:
    """跨进程复用：CLI 每次调用都是新进程，落盘缓存必须生效。

    否则每次 `invest-cli stock ...` 都要重付一次可达性探测
    （实测 yfinance 冷探测 2.02s，占 pick() 全部耗时；热探测 0.0003s）。
    这里用子进程真实复现「新进程」场景。
    """
    pytest.importorskip("yfinance")  # 无此模块时 find_spec 短路，_probe_http 永不触发，用例失去意义
    import subprocess

    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(tmp_path))
    registry._PROBE_CACHE.clear()
    monkeypatch.setattr(registry, "_probe_http", lambda url, timeout=2.0: (True, "HTTP 200"))
    registry._probe_python("yfinance")  # 首次：写落盘缓存

    probe_files = list((tmp_path / "probe").glob("*.json"))
    assert probe_files, "网络型探测结果未落盘 = 跨进程缓存不生效"

    # 新进程读取该缓存，且**不**发起真实探测
    code = (
        "import sys,json;"
        f"sys.path.insert(0,{str(_SCRIPTS)!r});"
        "import sources.registry as r;"
        "ok,detail=r._probe_python('yfinance');"
        "print(json.dumps({'ok':ok,'detail':detail}))"
    )
    env = {"INVEST_CLI_CACHE_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"}
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )
    assert out.returncode == 0, out.stderr
    payload = json.loads(out.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert "HTTP 200" in payload["detail"], (
        f"新进程未复用落盘探测结果（拿到 {payload['detail']!r}）"
    )


def test_negative_probe_result_expires_fast(monkeypatch) -> None:
    """负结果必须比正结果过期快得多（一次抖动不该禁用一个源几分钟）。

    这是探测类设计的典型自伤：把「瞬时不可达」当「持续不可用」长期缓存，
    结果一个可用源被静默跳过。正/负 TTL 必须**非对称**。
    """
    assert registry._PROBE_DISK_TTL_FAIL < registry._PROBE_DISK_TTL / 5, (
        "负结果缓存过长 = 瞬时网络抖动被放大成持续不可用"
    )
    assert registry._PROBE_DISK_TTL_FAIL <= 60.0


def test_probe_cache_key_includes_cache_root(monkeypatch, tmp_path) -> None:
    """探测缓存键必须含缓存根目录，否则切换缓存位置会命中上一个目录的结果。

    实测过的漏洞形态：在 dir_A 探到 True，把 INVEST_CLI_CACHE_DIR 切到
    dir_B 后仍返回 True（进程内条目没带目录信息，被跨目录复用）。
    """
    pytest.importorskip("yfinance")  # 无此模块时 find_spec 短路，_probe_http 永不触发，用例失去意义
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(dir_a))
    registry._PROBE_CACHE.clear()
    monkeypatch.setattr(registry, "_probe_http", lambda *a, **k: (True, "HTTP 200"))
    assert registry._probe_python("yfinance")[0] is True

    # 换目录 + 换结论：必须重新探测，不能复用 dir_a 的条目
    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(dir_b))
    monkeypatch.setattr(registry, "_probe_http", lambda *a, **k: (False, "URLError"))
    assert registry._probe_python("yfinance")[0] is False, (
        "缓存键未含缓存根目录 → 跨目录串味，测试隔离与运行时切换都会被绕过"
    )


def test_expired_negative_cache_is_reprobed(monkeypatch, tmp_path) -> None:
    """负缓存过期后必须重新探测，而不是继续沿用旧结论。"""
    pytest.importorskip("yfinance")  # 无此模块时 find_spec 短路，_probe_http 永不触发，用例失去意义
    import json as _json
    import os

    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(tmp_path))
    registry._PROBE_CACHE.clear()

    calls = {"n": 0}

    def _spy(url, timeout=2.0):
        calls["n"] += 1
        return True, "HTTP 200"

    monkeypatch.setattr(registry, "_probe_http", _spy)

    # 手写一份「已过期」的负缓存
    path = registry._probe_cache_path(("http", registry._probe_url_for_module("yfinance")))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps({"ok": False, "detail": "stale timeout"}), encoding="utf-8")
    old = time.time() - (registry._PROBE_DISK_TTL_FAIL + 10)
    os.utime(path, (old, old))

    ok, detail = registry._probe_python("yfinance")
    assert calls["n"] == 1, "过期负缓存未被重新探测"
    assert ok is True and "HTTP 200" in detail

# ── 3. fail-open：探测出错不能误杀数据源

def test_probe_exception_fails_open(monkeypatch) -> None:
    """探测函数自身抛异常时，按「不可达」处理但不崩溃；调用方仍能继续。

    （探针把异常归一成 (False, ...)，registry.detect 因此不会抛——
    这是刻意的：可用性判据出问题不该让整条取数链挂掉。）
    """
    registry._PROBE_CACHE.clear()

    def _boom(url, timeout=2.0):
        raise OSError("network stack exploded")

    monkeypatch.setattr(registry, "_probe_http", _boom)
    try:
        ok, detail = registry._probe_python("yfinance")
    except Exception as e:  # pragma: no cover
        raise AssertionError(f"探针异常不得外泄到调用方: {e}") from e
    assert isinstance(ok, bool)


def test_real_probe_normalizes_exceptions(monkeypatch) -> None:
    """_probe_http 必须把任意网络异常归一为 (False, ...)，绝不外抛。"""
    import urllib.request

    def _boom(*a, **kw):
        raise OSError("simulated")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    ok, detail = registry._probe_http("https://example.invalid/x")
    assert ok is False
    assert detail

# ── 4. 缺配置 ≠ 数据为空

def test_missing_key_surfaces_as_config_error_not_empty(monkeypatch) -> None:
    """缺 key 时必须报配置错误，不能吞成「数据为空」让用户去查数据。"""
    from sources import eastmoney as em

    monkeypatch.setattr(em, "load_api_key", lambda: "")
    res = em.stock("600519")
    assert res["ok"] is False
    err = (res.get("error") or "").upper()
    assert "EASTMONEY" in err, f"真实原因被吞掉，用户看到的是: {res.get('error')!r}"
    assert "为空" not in (res.get("error") or ""), "缺配置被误报成空数据"

# ── 5. 缓存单真源与原子性

def test_cache_roundtrip_and_ttl(tmp_path, monkeypatch) -> None:
    """缓存读写往返正常，且过期后必须失效。"""
    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(tmp_path))
    import _common

    _common.cache_set("testns", "k1", {"v": 42})
    assert _common.cache_get("testns", "k1", ttl=60) == {"v": 42}
    # TTL 为 0 → 立即过期
    assert _common.cache_get("testns", "k1", ttl=0) is None

    path = _common.cache_path("testns", "k1")
    assert path.parent.parent == tmp_path, "缓存未落在受控根目录下"


def test_cache_corrupt_file_is_miss_not_crash(tmp_path, monkeypatch) -> None:
    """缓存文件损坏时按未命中处理，绝不抛异常打断取数。"""
    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(tmp_path))
    import _common

    _common.cache_set("testns", "bad", {"v": 1})
    _common.cache_path("testns", "bad").write_text("{not json", encoding="utf-8")
    assert _common.cache_get("testns", "bad", ttl=60) is None


def test_cache_write_is_atomic_no_tmp_left(tmp_path, monkeypatch) -> None:
    """写入必须是「写 tmp 再 replace」，不留半截文件。"""
    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(tmp_path))
    import _common

    _common.cache_set("testns", "atomic", {"v": 7})
    leftovers = list((tmp_path / "testns").glob("*.tmp"))
    assert leftovers == [], f"残留临时文件: {leftovers}"


def test_dead_cache_helpers_are_gone() -> None:
    """反回归：已删除的死代码不得再被重新引入（同一件事的第二份实现）。"""
    import _common

    for name in (
        "get_cached",
        "set_cached",
        "parallel_execute",
        "query_eastmoney_parallel",
        "eastmoney_query_with_cache",
    ):
        assert not hasattr(_common, name), (
            f"{name} 是已删除的死代码；新增缓存/并发能力请复用 cache_get/cache_set "
            f"与 sources/hithink._request_many"
        )


def test_sec_edgar_uses_shared_cache_root(tmp_path, monkeypatch) -> None:
    """sec_edgar 的缓存目录必须来自 _common.cache_root（单真源），不另立平台判断。"""
    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(tmp_path))
    from sources import sec_edgar

    d = sec_edgar.cache_dir()
    assert str(d).startswith(str(tmp_path)), f"未复用共享缓存根: {d}"


def test_cache_layer_has_production_callers() -> None:
    """反回归：统一缓存层必须有生产调用者。

    「宣称有缓存、全仓零调用者」的死缓存治理后当天复发过。守卫真实接线点：
    route.fetch 的快照缓存与 sec_edgar._cached_json，任一断开即失败。
    """
    for rel in ("sources/route.py", "sources/sec_edgar.py"):
        src = (_SCRIPTS / rel).read_text(encoding="utf-8")
        assert "cache_get" in src and "cache_set" in src, (
            f"{rel} 与统一缓存层断开接线——死缓存将复发"
        )

# ── 6. yfinance 超时必须真的被收紧（曾经是「看起来在工作」的死代码）
#
# 教训：首版实现给 `requests.Session.request` 打补丁、并拦 CURLOPT 的
# 13/78（秒档）。两处都无效——
#   ① yfinance 1.2.0 用 curl_cffi.requests.Session，它不是 requests.Session
#      的子类（issubclass → False），补丁打在不同类上；
#   ② curl_cffi 实际设置的是 _MS 变体（155/156，毫秒），13/78 从不被设置。
# 结果：请求 30s 超时照旧 30s 才返回，"修复" 100% 不生效却全程静默。
# 这组用例专门防止「补丁存在但不起作用」的回归。

def test_curl_cffi_session_is_not_requests_session() -> None:
    """记录前提：两者无继承关系——这正是首版补丁失效的原因。"""
    import requests
    from curl_cffi import requests as creq

    assert not issubclass(creq.Session, requests.Session), (
        "若此断言失败，说明上游改用 requests.Session，补丁策略需重新评估"
    )


def test_bound_timeouts_uses_ms_option_codes() -> None:
    """必须拦 _MS 档（155/156）；只拦秒档等于没拦。"""
    from curl_cffi.const import CurlOpt

    assert int(CurlOpt.TIMEOUT_MS) == 155 and int(CurlOpt.CONNECTTIMEOUT_MS) == 156


def test_bound_yfinance_timeouts_actually_bounds(monkeypatch) -> None:
    """端到端：显式请求 30s 超时时，被预算收紧到 ~3s 内返回。

    用一个「接受连接但永不响应」的本地 socket 复现读超时。
    这条用例在首版实现下会失败（实测 30s），在修正后通过（3.00s）。
    """
    import socket
    import threading

    import pytest

    curl_cffi = pytest.importorskip("curl_cffi")
    from curl_cffi import requests as creq

    monkeypatch.setenv("INVEST_CLI_HTTP_TIMEOUT", "2")
    from cmd_us import _bound_yfinance_timeouts

    # 清掉可能存在的旧补丁标记，确保本次真的装上新补丁
    from curl_cffi import Curl

    monkeypatch.delattr(Curl, "_invest_cli_bounded", raising=False)
    _bound_yfinance_timeouts()

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    srv.settimeout(40)
    port = srv.getsockname()[1]

    def _accept_and_stall():
        try:
            conn, _ = srv.accept()
            time.sleep(40)  # 接受连接但永不回包 → 触发读超时
        except Exception:
            pass

    threading.Thread(target=_accept_and_stall, daemon=True).start()

    t0 = time.perf_counter()
    try:
        creq.get(f"http://127.0.0.1:{port}/x", timeout=30)
    except Exception:
        pass
    elapsed = time.perf_counter() - t0

    assert elapsed < 8.0, (
        f"超时未被收紧（耗时 {elapsed:.1f}s）——补丁很可能又打在了无效的类或选项码上"
    )


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))

# ── 7. 缓存写入的临时文件必须按进程分名（跨进程原子性）

def test_cache_set_tmp_name_is_per_process(monkeypatch, tmp_path) -> None:
    """共用同一个 .tmp 时，两个进程写同一键会互相截断，并让其中一个 replace 丢缓存。"""
    from pathlib import Path as _P

    import _common

    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(_common.os, "getpid", lambda: 4242)
    seen: list[str] = []
    orig = _P.replace

    def _spy(self, target):  # noqa: ANN001
        seen.append(self.name)
        return orig(self, target)

    monkeypatch.setattr(_P, "replace", _spy)
    _common.cache_set("unit", "k", {"v": 1})

    assert seen, "cache_set 未走原子替换"
    assert "4242" in seen[0], f"临时文件名未含 pid：{seen[0]}"
    assert _common.cache_get("unit", "k", 60) == {"v": 1}

# ── 8. 缓存必须能自清：TTL 只决定读时是否命中，不删文件

def test_cache_prunes_stale_files(monkeypatch, tmp_path) -> None:
    """过期缓存与残留 .tmp 必须在写时被清掉。

    TTL 只在读时生效，文件本身不会消失；`sec` 的 companyfacts 单文件约 3.7MB，
    没有这一步就会按「查过的公司数」无界增长（实测本机已累积 24MB）。
    """
    import os

    import _common

    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(tmp_path))
    ns = "prune-guard-ns"

    stale = _common.cache_path(ns, "stale-key")
    stale.write_text("{}", encoding="utf-8")
    old = time.time() - (_common.CACHE_MAX_AGE + 60)
    os.utime(stale, (old, old))

    tmp_left = stale.with_name(stale.name + ".999.tmp")
    tmp_left.write_text("partial", encoding="utf-8")
    os.utime(tmp_left, (old, old))

    _common.cache_set(ns, "fresh-key", {"v": 1})

    assert not stale.exists(), "过期缓存未被清理 = 磁盘占用无界增长"
    assert not tmp_left.exists(), "崩溃残留的 .tmp 未被清理"
    assert _common.cache_get(ns, "fresh-key", 60) == {"v": 1}, "清理不得误删刚写的条目"


def test_cache_max_age_is_finite() -> None:
    """清理阈值必须是一个有限值，否则等于没有清理。"""
    import math

    import _common

    assert math.isfinite(_common.CACHE_MAX_AGE) and _common.CACHE_MAX_AGE > 0

if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
