#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多品种真实成本模型：ETF / 期货 / 期权。
全部基于公开真实交易规则，供回测与实盘意图共用，禁止模拟数值。
  - ETF：免印花税，佣金万2.5最低5元，T+1（跨境/债券ETF部分T+0，保守取T+1）
  - 期货：按手固定手续费 + 保证金占用（乘数×价格×保证金率），T+0 双向
  - 期权：权利金 = 价×乘数，按张手续费，无印花税，T+0 双向，买方不交保证金
"""
from dataclasses import dataclass
from .instruments import AssetClass, Instrument


@dataclass
class TradeCost:
    commission: float      # 手续费
    tax: float             # 印花税（ETF/期货/期权均0）
    margin: float          # 保证金占用（期货）
    premium: float         # 权利金（期权）
    notional: float        # 名义金额

    @property
    def total_cash_out(self) -> float:
        """买入/开仓当下实际现金流支出。"""
        return self.commission + self.tax + self.margin + self.premium


def calc_cost(inst: Instrument, price: float, volume: int, is_sell: bool = False) -> TradeCost:
    """按合约规格计算真实交易成本。volume 单位：ETF=股，期货=手，期权=张。"""
    ac = inst.asset_class
    if ac in (AssetClass.SPOT, AssetClass.ETF):
        notional = price * volume
        commission = max(notional * inst.commission_rate, inst.commission_min)
        transfer = notional * 0.00001  # 过户费万0.1，沪深双向
        tax = notional * inst.stamp_tax if is_sell else 0.0
        return TradeCost(commission=commission + transfer, tax=tax,
                         margin=0.0, premium=0.0, notional=notional)

    if ac == AssetClass.FUTURES:
        notional = price * inst.multiplier * volume
        commission = inst.commission_per_lot * volume
        margin = notional * inst.margin_rate
        return TradeCost(commission=commission, tax=0.0,
                         margin=margin, premium=0.0, notional=notional)

    if ac == AssetClass.OPTIONS:
        premium = price * inst.multiplier * volume
        commission = inst.commission_per_lot * volume
        return TradeCost(commission=commission, tax=0.0,
                         margin=0.0, premium=premium, notional=premium)

    raise ValueError(f"不支持的品种: {ac}")


def lot_size(inst: Instrument) -> int:
    """最小交易单位：ETF 100 股整数倍，期货/期权 1 手/张。"""
    return 100 if inst.asset_class in (AssetClass.SPOT, AssetClass.ETF) else 1


def round_lot(inst: Instrument, volume: int) -> int:
    unit = lot_size(inst)
    return max(0, (int(volume) // unit) * unit)


def t_plus(inst: Instrument) -> int:
    return inst.t_plus


def price_limit(inst: Instrument, prev_close: float, price: float) -> str:
    """返回 'up'/'down'/'none'。期货涨跌停因品种而异，用规格近似（保守）。"""
    if inst.asset_class in (AssetClass.FUTURES, AssetClass.OPTIONS):
        # 期货涨跌停各品种不同（4%~10%），此处不做硬拦截，避免误判；实盘由柜台风控
        return "none"
    limit = 0.10  # ETF 主板 10%
    if price >= prev_close * (1 + limit) - 1e-6:
        return "up"
    if price <= prev_close * (1 - limit) + 1e-6:
        return "down"
    return "none"
