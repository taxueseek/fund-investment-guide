#!/usr/bin/env python3
"""能力发现层 + ttskill 透传命令的离线契约测试 — 不联网。

守护 2026-09-03 补齐的三件事：
1. yingmi 数组 bug 修复不回归（适配器支持 `[` 开头；行为见 test_yingmi.py）；
2. invest-cli 命令面必须注册 ttskill 透传 + capabilities 发现层（防"声明不可达"复发）；
3. 收敛白名单语义不漂移（GetPopularFund 等批量工具应标注"透传可用"而非误标已收敛）。
"""
from __future__ import annotations

from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SKILL = SCRIPTS.parent

from cmd_capabilities import YINGMI_CONVERGED, TTSKILL_CONVERGED, converge_status  # noqa: E402


def test_cli_registers_ttskill_and_capabilities() -> None:
    """主入口必须注册两个新子命令。"""
    text = (SCRIPTS / "invest_cli.py").read_text(encoding="utf-8")
    assert 'add_parser("ttskill"' in text
    assert 'add_parser("capabilities"' in text
    assert '"ttskill": cmd_ttskill' in text
    assert '"capabilities": cmd_capabilities' in text


def test_cmd_modules_exist_and_export_run() -> None:
    for mod_name in ("cmd_ttskill", "cmd_capabilities"):
        mod = __import__(mod_name)
        assert callable(getattr(mod, "run")), f"{mod_name} 缺 run()"


def test_yingmi_array_fix_intact() -> None:
    """适配器必须认 `[` 开头（数组型工具直返），防修复回退。"""
    text = (SCRIPTS / "sources" / "yingmi.py").read_text(encoding="utf-8")
    assert 'startswith(("{", "["))' in text


def test_converged_whitelist_semantics() -> None:
    """已收敛项标注为 ✅；批量/列表类（GetPopularFund/Batch*）必须仍是透传。"""
    assert YINGMI_CONVERGED["GetFundDiagnosis"]
    assert converge_status("yingmi", "GetFundDiagnosis").startswith("✅")
    assert converge_status("yingmi", "GetPopularFund").startswith("⬜")
    assert converge_status("yingmi", "BatchGetFundNavHistory").startswith("⬜")
    assert TTSKILL_CONVERGED["TTFUND_BASE_INFOS"]
    assert converge_status("ttskill", "TTFUND_BASE_INFOS").startswith("✅")
    assert converge_status("ttskill", "TTFUND_MANAGER_INFO").startswith("⬜")
    assert converge_status("ttskill", "ACCOUNT_HOLDING").startswith("🔒")
    assert converge_status("ttskill", "CONDITION_ORDER").startswith("🔒")


def test_gap_matrix_doc_present() -> None:
    """差距矩阵文档必须存在（设计真源，随实现同步维护）。"""
    assert (SKILL / "docs" / "capability-gap.md").is_file()
