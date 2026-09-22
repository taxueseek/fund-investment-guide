"""invest-cli 数据源适配器包。

设计：
- 数据源声明真源 = ../data-sources.yaml（单一真源，改造只动这一处）。
- 本包只提供适配器与统一接口，不重复硬编码数据来源清单。
- 各适配器统一暴露：

    def detect() -> (bool, str)          # 可用性 + 说明
    def call(...) -> dict                # 取数，返回 JSON 兼容 dict

外部代码（CLI / invest-* 分析 skill）应通过 registry 拿到数据源状态，
再按 coverage + priority 做路由与降级，不要自行猜测某数据源是否可用。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def repo_config_path() -> Path:
    """data-sources.yaml 所在路径（invest-cli 根目录）。"""
    return Path(__file__).resolve().parent.parent.parent / "data-sources.yaml"


def load_registry() -> dict[str, Any]:
    """读取数据源配置真源，返回 {source_id: conf}。

    配置缺失或无法解析时返回空字典，调用方按「无数据源」处理并给出明确提示。

    `import yaml` 刻意放在**函数内**：PyYAML 的 import 自耗时实测约 9ms
    （reader/dumper/resolver/cyaml 一整串），而快照命中这条路径根本不需要配置
    ——route.fetch 现在先判缓存、命中即返回（见 route.fetch 注释），
    完全不会走到这里。放在模块顶层就等于让每次命中都白付一次 yaml 的 import。
    """
    import yaml  # type: ignore

    cfg_path = repo_config_path()
    if not cfg_path.is_file():
        return {}
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:
        # 配置解析失败不应让整个 CLI 崩溃，交给上层报具体原因
        return {}
    return (data or {}).get("sources", {})
