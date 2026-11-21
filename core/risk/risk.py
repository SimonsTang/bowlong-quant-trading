#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""风控网关：实盘下单前的最后一道闸。任何不通过都拒绝下单。"""

from dataclasses import dataclass


@dataclass
class RiskConfig:
    max_position_pct: float = 0.20      # 单票最大仓位
    max_total_pct: float = 0.80         # 总仓位上限
    max_daily_loss_pct: float = 0.02    # 日内最大亏损熔断
    max_drawdown_pct: float = 0.10      # 最大回撤熔断
    allow_list_only: bool = True        # 仅允许白名单标的
    block_st_limit: bool = True         # 禁止ST股


class RiskGateway:
    def __init__(self, cfg: RiskConfig, whitelist: set = None):
        self.cfg = cfg
        self.whitelist = whitelist or set()

    def check(self, code: str, side: str, amount: float, total_asset: float,
              current_pos_value: float, name: str = "") -> (bool, str):
        if side not in ("buy", "sell"):
            return False, "非法买卖方向"
        if self.cfg.allow_list_only and code not in self.whitelist:
            return False, f"{code} 不在白名单"
        if self.cfg.block_st_limit and ("ST" in name.upper() or "*" in name):
            return False, f"{code} 为ST股，禁止交易"
        if side == "buy":
            if amount > total_asset * self.cfg.max_position_pct:
                return False, f"单票仓位超限: {amount:.0f} > {total_asset*self.cfg.max_position_pct:.0f}"
            if current_pos_value + amount > total_asset * self.cfg.max_total_pct:
                return False, "总仓位超限"
        return True, "PASS"


class DrawdownCircuitBreaker:
    """回撤熔断：触发后强制清仓并停用策略，需人工复核重启。"""
    def __init__(self, max_dd: float):
        self.max_dd = max_dd
        self.peak = 0.0
        self.tripped = False

    def update(self, equity: float) -> bool:
        self.peak = max(self.peak, equity)
        dd = equity / self.peak - 1 if self.peak else 0
        if dd < -self.max_dd:
            self.tripped = True
        return self.tripped
