#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略守护（借鉴 TSP 的策略健康度机制）。
策略不是上线就永久使用，而是持续监控三态：
  HEALTHY 健康  -> 正常运行
  WATCH   观察  -> 表现退化，降权/减仓，需关注
  RETIRED 退役  -> 失效，停用，需人工复核重启

触发条件基于实盘/样本外跟踪的：滚动收益、回撤、连败次数、数据健康。
"""
from dataclasses import dataclass, field
from enum import Enum


class StrategyState(str, Enum):
    HEALTHY = "HEALTHY"
    WATCH = "WATCH"
    RETIRED = "RETIRED"


@dataclass
class GuardConfig:
    watch_drawdown: float = -0.08     # 回撤到此进入观察
    retire_drawdown: float = -0.15    # 回撤到此退役
    max_consecutive_losses: int = 5   # 连败次数
    min_rolling_return: float = -0.10 # 滚动收益下限


@dataclass
class StrategyHealth:
    name: str
    state: StrategyState = StrategyState.HEALTHY
    peak_equity: float = 0.0
    consecutive_losses: int = 0
    reasons: list = field(default_factory=list)
    updates: int = 0

    def update(self, equity: float, trade_pnl: float = None, cfg: GuardConfig = None) -> StrategyState:
        cfg = cfg or GuardConfig()
        self.peak_equity = max(self.peak_equity, equity)
        dd = equity / self.peak_equity - 1 if self.peak_equity else 0
        self.reasons = []

        if trade_pnl is not None:
            self.consecutive_losses = self.consecutive_losses + 1 if trade_pnl <= 0 else 0

        if dd <= cfg.retire_drawdown:
            self.state = StrategyState.RETIRED
            self.reasons.append(f"回撤{dd:.1%}触及退役线")
        elif dd <= cfg.watch_drawdown or self.consecutive_losses >= cfg.max_consecutive_losses:
            self.state = StrategyState.WATCH
            if dd <= cfg.watch_drawdown:
                self.reasons.append(f"回撤{dd:.1%}进入观察")
            if self.consecutive_losses >= cfg.max_consecutive_losses:
                self.reasons.append(f"连续亏损{self.consecutive_losses}次")
        else:
            self.state = StrategyState.HEALTHY
        self.updates += 1
        return self.state

    def can_trade(self) -> bool:
        return self.state == StrategyState.HEALTHY

    def to_dict(self):
        return {"name": self.name, "state": self.state.value,
                "reasons": self.reasons, "updates": self.updates,
                "can_trade": self.can_trade()}


class StrategyGuard:
    """多策略守护注册表。实盘下单前必须查 can_trade()。"""
    def __init__(self, cfg: GuardConfig = None):
        self.cfg = cfg or GuardConfig()
        self._health: dict = {}

    def register(self, name: str):
        if name not in self._health:
            self._health[name] = StrategyHealth(name)
        return self._health[name]

    def update(self, name: str, equity: float, trade_pnl: float = None) -> StrategyState:
        return self.register(name).update(equity, trade_pnl, self.cfg)

    def can_trade(self, name: str) -> bool:
        return name in self._health and self._health[name].can_trade()

    def status(self) -> list:
        return [h.to_dict() for h in self._health.values()]
