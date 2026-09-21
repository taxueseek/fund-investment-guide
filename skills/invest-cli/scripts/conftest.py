"""invest-cli 测试公共夹具与导入路径。

两个 autouse 夹具对**所有**测试文件生效（含以后新增的），因为这两件事一旦漏掉，
后果都是「假数据跨用例、跨进程流动」，而且不会立刻报错：

1. **缓存目录隔离**：`cache_root()` 默认落在用户真实目录（macOS 是
   `~/Library/Caches/invest-cli`）。测试若往那里写，假数据会被之后的**真实查询**
   读到。实测发生过：`fred.liquidity(use_cache=False)` 第一版只绕过读、仍然写，
   把 mock 的 100.0 写进 macro 缓存。放在 conftest 而不是各测试文件里，
   是为了让这条防线不依赖「每个新测试文件作者都记得加夹具」。
2. **探测缓存清空**：registry 的可达性探测结果会跨进程落盘，上一条用例的结果
   会污染下一条（假通过或假失败）。

状态目录一并隔离：自选股等本地状态不该在测试里落到用户真实目录。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


@pytest.fixture(autouse=True)
def isolated_cli_dirs(tmp_path, monkeypatch):
    """每个用例一份独立的缓存/状态目录，物理上碰不到用户真实目录。"""
    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("INVEST_CLI_STATE_DIR", str(tmp_path / "state"))
    yield


@pytest.fixture(autouse=True)
def clean_probe_cache():
    """探测结果在进程内也会缓存，用例之间必须互不可见。"""
    from sources import registry

    registry._PROBE_CACHE.clear()
    yield
    registry._PROBE_CACHE.clear()
