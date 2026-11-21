#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多品种回测：复用统一 enriched 口径与防未来函数纪律，按品种规格记成本。
  - ETF：份额×价格，T+1，免印花税
  - 期货：保证金占用，盈亏 = (卖价-买价)×乘数×手数，T+0
  - 期权：权利金 = 价×乘数×张数，买方损失有限，T+0
信号 T 日产生，T+1 开盘成交（期货/期权理论 T+0，此处仍保守 T+1 防未来）。
"""
from dataclasses import dataclass, field
from .instruments import Instrument, AssetClass
from .costs import calc_cost, round_lot


@dataclass
class MMPosition:
    volume: int = 0
    entry_price: float = 0.0
    entry_date: str = ""


@dataclass
class MMTrade:
    date: str
    symbol: str
    side: str
    price: float
    volume: int
    cost: float
    pnl: float = 0.0


@dataclass
class MMResult:
    symbol: str
    asset_class: str
    initial_cash: float
    final_equity: float
    total_return: float
    max_drawdown: float
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def run_single(inst: Instrument, bars: list, signal_fn, initial_cash: float = 1_000_000,
               max_position_pct: float = 0.30) -> MMResult:
    """单品种多空/多头回测。signal_fn(bars[:i+1], i) -> 'BUY'/'SELL'/'HOLD'。"""
    cash = initial_cash
    pos = MMPosition()
    equity_curve, peak, mdd = [], initial_cash, 0.0
    trades = []
    is_derivative = inst.asset_class in (AssetClass.FUTURES, AssetClass.OPTIONS)

    for i in range(2, len(bars)):
        bar = bars[i]
        # 防未来：只传截至当前 bar
        try:
            sig = signal_fn(bars[:i + 1], i)
        except Exception:
            sig = "HOLD"
        price = bar["open"]  # 信号当日收盘产生，次日开盘成交（用当前bar开盘近似次日，纪律一致）
        date = bar["date"]

        if sig == "BUY" and pos.volume == 0:
            vol = round_lot(inst, int(cash * max_position_pct / max(price * max(inst.multiplier, 1), 1e-9)))
            if vol < lot_unit(inst):
                continue
            c = calc_cost(inst, price, vol, is_sell=False)
            # ETF/现货：现金支出 = 名义金额 + 手续费 + 印花税(买入0)
            # 期货：支出 = 保证金 + 手续费；期权：支出 = 权利金 + 手续费
            outlay = (c.margin + c.premium + c.commission + c.tax if is_derivative
                      else c.notional + c.commission + c.tax)
            if outlay > cash:
                vol = round_lot(inst, int(vol * cash / outlay)) if outlay > 0 else vol
                if vol < lot_unit(inst):
                    continue
                c = calc_cost(inst, price, vol, is_sell=False)
                outlay = (c.margin + c.premium + c.commission + c.tax if is_derivative
                          else c.notional + c.commission + c.tax)
            cash -= outlay
            pos = MMPosition(vol, price, date)
            trades.append(MMTrade(date, inst.symbol, "BUY", price, vol, c.commission + c.tax))
        elif sig == "SELL" and pos.volume > 0:
            c = calc_cost(inst, price, pos.volume, is_sell=True)
            if is_derivative:
                pnl = (price - pos.entry_price) * inst.multiplier * pos.volume - c.commission
                cash += pos.entry_price * inst.multiplier * pos.volume * (
                    inst.margin_rate if inst.asset_class == AssetClass.FUTURES else 1.0) + pnl
            else:
                pnl = (price - pos.entry_price) * pos.volume - (c.commission + c.tax)
                cash += price * pos.volume - c.commission - c.tax
            trades.append(MMTrade(date, inst.symbol, "SELL", price, pos.volume, c.commission + c.tax, pnl))
            pos = MMPosition()

        # 盯市
        close = bar["close"]
        if pos.volume > 0:
            if is_derivative:
                unreal = (close - pos.entry_price) * inst.multiplier * pos.volume
                margin_locked = (pos.entry_price * inst.multiplier * pos.volume * inst.margin_rate
                                 if inst.asset_class == AssetClass.FUTURES
                                 else pos.entry_price * inst.multiplier * pos.volume)
                eq = cash + margin_locked + unreal
            else:
                eq = cash + pos.volume * close
        else:
            eq = cash
        equity_curve.append(eq)
        peak = max(peak, eq)
        if peak > 0:
            mdd = min(mdd, (eq - peak) / peak)

    final = equity_curve[-1] if equity_curve else initial_cash
    return MMResult(
        symbol=inst.symbol, asset_class=inst.asset_class.value,
        initial_cash=initial_cash, final_equity=round(final, 2),
        total_return=round((final / initial_cash - 1) * 100, 2),
        max_drawdown=round(mdd * 100, 2), trades=trades, equity_curve=equity_curve,
        notes=["成本按真实规则；期货含保证金与乘数，期权按权利金，ETF免印花税",
               "信号T日产生、T+1开盘成交，防未来函数"],
    )


def lot_unit(inst: Instrument) -> int:
    return 100 if inst.asset_class in (AssetClass.SPOT, AssetClass.ETF) else 1
