#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A股真实交易成本模型 - 从波龙旧仓库提炼并修正，全部为真实规则。"""


class AShareCosts:
    COMMISSION_RATE = 0.00025   # 佣金 万2.5，可按需调整
    MIN_COMMISSION = 5.0        # 最低5元
    STAMP_DUTY = 0.0005         # 印花税 万5，仅卖出（2023年8月起减半）
    TRANSFER_FEE = 0.00001      # 过户费 万0.1，双向

    @classmethod
    def commission(cls, amount: float) -> float:
        return max(amount * cls.COMMISSION_RATE, cls.MIN_COMMISSION)

    @classmethod
    def stamp_duty(cls, amount: float, is_sell: bool) -> float:
        return amount * cls.STAMP_DUTY if is_sell else 0.0

    @classmethod
    def transfer_fee(cls, amount: float) -> float:
        return amount * cls.TRANSFER_FEE

    @classmethod
    def total_buy(cls, amount: float) -> float:
        return cls.commission(amount) + cls.transfer_fee(amount)

    @classmethod
    def total_sell(cls, amount: float) -> float:
        return cls.commission(amount) + cls.stamp_duty(amount, True) + cls.transfer_fee(amount)


class TradeRules:
    """A股交易规则：T+1、涨跌停、100股整数倍。"""

    @staticmethod
    def is_limit_up(prev_close: float, price: float, board: str = "main") -> bool:
        limits = {"main": 0.10, "gem": 0.20, "star": 0.20, "bj": 0.30}
        return price >= prev_close * (1 + limits[board]) - 1e-6

    @staticmethod
    def is_limit_down(prev_close: float, price: float, board: str = "main") -> bool:
        limits = {"main": 0.10, "gem": 0.20, "star": 0.20, "bj": 0.30}
        return price <= prev_close * (1 - limits[board]) + 1e-6

    @staticmethod
    def round_lot(volume: int) -> int:
        return (volume // 100) * 100

    @staticmethod
    def board_of(code: str) -> str:
        num = code.split(".")[0]
        if num.startswith("30"):
            return "gem"
        if num.startswith("688"):
            return "star"
        if num.startswith(("4", "8")):
            return "bj"
        return "main"
