#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略统一接口与注册中心。
借鉴成熟框架（vnpy/backtrader/qlib）的"策略即插件"思想：
  - 所有策略继承 BaseStrategy，实现 on_bars(enriched_bars, i) -> signal
  - 通过 @register 注册，UI 可枚举切换
  - 每个策略声明参数默认值与可调范围，供稳健性检验与 UI 参数面板
  - 同一策略对象既服务回测也服务实盘（与 StrategyEngine 契约一致）
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, List


@dataclass
class ParamSpec:
    name: str
    default: float
    low: float
    high: float
    step: float = 1.0
    desc: str = ""


class BaseStrategy:
    name = "base"
    display = "基础策略"
    category = "other"
    desc = ""
    source = "经典公开逻辑"
    params: List[ParamSpec] = []

    def __init__(self, **kwargs):
        self.cfg = {p.name: kwargs.get(p.name, p.default) for p in self.params}

    def on_bars(self, bars: list, i: int) -> str:
        """核心：只看 bars[:i+1]，返回 BUY/SELL/HOLD。禁止访问 i 之后数据。"""
        raise NotImplementedError

    def signal_fn(self) -> Callable[[list, int], str]:
        """返回供 StrategyEngine 使用的函数（绑定 self）。"""
        return lambda bars, i: self.on_bars(bars, i)

    def param_dict(self) -> dict:
        return {p.name: self.cfg[p.name] for p in self.params}


# ---------------- 注册中心 ----------------
_REGISTRY: Dict[str, type] = {}
_CATEGORY_LABELS = {
    "trend": "趋势跟随", "momentum": "动量", "mean_revert": "均值回归",
    "breakout": "突破", "factor": "多因子", "pairs": "套利", "grid": "网格",
}


def register(cls):
    _REGISTRY[cls.name] = cls
    return cls


def get(name: str, **kwargs) -> BaseStrategy:
    if name not in _REGISTRY:
        raise KeyError(f"未注册策略: {name}，可选: {list(_REGISTRY)}")
    return _REGISTRY[name](**kwargs)


def list_strategies() -> list:
    """供 UI 枚举全部可选策略。"""
    out = []
    for name, cls in _REGISTRY.items():
        out.append({
            "name": name,
            "display": cls.display,
            "category": cls.category,
            "category_label": _CATEGORY_LABELS.get(cls.category, cls.category),
            "desc": cls.desc,
            "source": cls.source,
            "params": [{"name": p.name, "default": p.default, "low": p.low,
                        "high": p.high, "step": p.step, "desc": p.desc}
                       for p in cls.params],
        })
    return out
