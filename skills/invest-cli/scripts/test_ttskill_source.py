#!/usr/bin/env python3
"""ttskill 数据源接入的离线契约测试 — 不联网。

守护三件事：
1. yaml 声明与适配器文件必须同步存在（防「文档有、实现无」复发）；
2. ttskill 优先级必须高于 hithink（fund 默认链首位，官方结构化优先）；
3. period 标题→中文标签映射不被误改（110011 实测反推，改了会错位）。
"""
from __future__ import annotations

from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SKILL = SCRIPTS.parent

from sources.ttskill import PERIOD_LABELS  # noqa: E402


def test_yaml_and_adapter_both_present() -> None:
    yaml_text = (SKILL / "data-sources.yaml").read_text(encoding="utf-8")
    assert "ttskill:" in yaml_text, "data-sources.yaml 缺少 ttskill 声明"
    assert (SCRIPTS / "sources" / "ttskill.py").is_file(), "适配器 sources/ttskill.py 缺失"
    assert "adapters: [ttskill]" in yaml_text


def test_native_primary_then_optional_ttskill() -> None:
    """fund 主路=自带 hithink(60) > ttskill 可选(55) > eastmoney(50)。"""
    import re
    yaml_text = (SKILL / "data-sources.yaml").read_text(encoding="utf-8")

    def prio_of(name: str) -> int:
        m = re.search(rf"\n  {name}:\n(?:\s+\S[^\n]*\n)*?\s+priority:\s*(\d+)", yaml_text)
        return int(m.group(1)) if m else -1

    assert prio_of("hithink") > prio_of("ttskill") > prio_of("eastmoney"), "应为 hithink>ttskill>eastmoney"


def test_period_label_mapping_intact() -> None:
    """实测（110011）反推的映射，关键码不得缺失/错位。"""
    assert PERIOD_LABELS["Y"] == "近1月回报"
    assert PERIOD_LABELS["3Y"] == "近3月回报"
    assert PERIOD_LABELS["1N"] == "近1年回报"
    assert PERIOD_LABELS["JN"] == "今年来回报"
    assert PERIOD_LABELS["LN"] == "成立来回报"


def test_module_exposes_fund() -> None:
    import importlib
    mod = importlib.import_module("sources.ttskill")
    assert callable(getattr(mod, "fund"))
    assert getattr(mod, "SOURCE_LABEL") == "天天基金"


def test_ttskill_adapter_does_not_shell_out() -> None:
    """直连 gateway 的守护：适配器不得再起 ttskill 子进程（外部 CLI 依赖）。"""
    import importlib

    text = (SCRIPTS / "sources" / "ttskill.py").read_text(encoding="utf-8")
    assert "shutil.which" not in text, "ttskill 适配器又去 PATH 找 CLI 了"
    mod = importlib.import_module("sources.ttskill")
    assert hasattr(mod, "GATEWAY") and "openapi/skill/invoke" in mod.INVOKE_PATH
    # 认证沿用官方凭据存储，不自建第二套
    assert mod.KEYCHAIN_SERVICE == "com.ttfund.ttskill.base"


# ── 直连认证层（官方凭据 + ed25519 签名）──

def test_installed_skills_parses_both_shapes(monkeypatch, tmp_path) -> None:
    """index.json 为 {"skills": [...]}（旧版可能是裸数组），两种都要能读。"""
    import json as _json

    from sources import ttskill as t

    wrapped = tmp_path / "a.json"
    wrapped.write_text(_json.dumps({"skills": [
        {"skill_id": "TTFUND_BASE_INFOS", "version": "1.3.8", "status": "enabled"},
        {"skill_id": "OLD", "version": "1.0.0", "status": "disabled"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(t, "SKILLS_INDEX", wrapped)
    assert t._installed_skills() == {"TTFUND_BASE_INFOS": "1.3.8"}

    bare = tmp_path / "b.json"
    bare.write_text(_json.dumps([{"skill_id": "X", "version": "2.0.0"}]), encoding="utf-8")
    monkeypatch.setattr(t, "SKILLS_INDEX", bare)
    assert t._installed_skills() == {"X": "2.0.0"}


def test_sign_headers_shape() -> None:
    """ed25519 签名头必须齐五件（与官方基础包同一套认证逻辑）。"""
    import pytest

    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

    from sources import ttskill as t

    pem = Ed25519PrivateKey.generate().private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    headers = t._sign_headers("POST", "/ai-smart-skill-service/openapi/skill/invoke", b"{}", "sess", pem)
    assert set(headers) == {"X-Session-Id", "X-Timestamp", "X-Nonce", "X-Body-SHA256", "X-Signature"}
    assert all(headers.values())
    assert headers["X-Session-Id"] == "sess"


def test_detect_false_without_credentials(monkeypatch) -> None:
    """无凭据时不得假装可用（旧实现靠 CLI status 文本，容易误判）。"""
    from sources import ttskill as t

    monkeypatch.setattr(t, "_read_credential", lambda record: None)
    ok, detail = t.detect()
    assert ok is False and "未登录" in detail


def test_invoke_without_credentials_raises(monkeypatch) -> None:
    from sources import ttskill as t

    monkeypatch.setattr(t, "_read_credential", lambda record: None)
    try:
        t._invoke("TTFUND_BASE_INFOS", {"fcode": "110011"})
        raise AssertionError("无凭据时必须报错，不得静默返回空")
    except RuntimeError as e:
        assert "未登录" in str(e)


def test_token_state_detects_expiry(monkeypatch) -> None:
    """过期 token 必须判不可用（判据是 exp，不是「文件在磁盘上」）。"""
    from sources import ttskill as t

    expired = {"access_token": "a.b.c", "session_id": "s",
               "saved_at": 1, "expires_in": 1}
    monkeypatch.setattr(t, "_read_credential",
                        lambda record: expired if record == "token" else {"device_private_key_pem": "x"})
    ok, detail = t._token_state()
    assert ok is False and "过期" in detail
