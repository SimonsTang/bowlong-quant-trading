#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绩效指标：回撤、夏普、卡玛、胜率、盈亏比。纯标准库。"""
import math


def max_drawdown(equity: list) -> float:
    """最大回撤（负数，如 -0.23）。"""
    peak, mdd = 0.0, 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1)
    return mdd


def annual_return(equity: list, initial: float, trading_days: int = 244) -> float:
    """年化收益率（几何）。"""
    if not equity or equity[-1] <= 0 or initial <= 0 or len(equity) < 2:
        return 0.0
    years = len(equity) / trading_days
    if years <= 0:
        return 0.0
    return (equity[-1] / initial) ** (1 / years) - 1


def sharpe(equity: list, trading_days: int = 244, rf: float = 0.02) -> float:
    """年化夏普比率。"""
    if len(equity) < 2:
        return 0.0
    rets = [equity[i] / equity[i - 1] - 1 for i in range(1, len(equity)) if equity[i - 1] > 0]
    if not rets:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    sd = var ** 0.5
    if sd == 0:
        return 0.0
    return (mean - rf / trading_days) / sd * math.sqrt(trading_days)


def calmar(equity: list, initial: float) -> float:
    """卡玛比率 = 年化收益 / |最大回撤|。"""
    mdd = abs(max_drawdown(equity))
    if mdd == 0:
        return 0.0
    return annual_return(equity, initial) / mdd


def trade_stats(trades: list) -> dict:
    """基于成交流水统计胜率/盈亏比。按 code 配对买卖。"""
    pnl = []
    open_pos = {}
    for t in trades:
        if t.side == "buy":
            open_pos[t.code] = (t.price, t.volume, t.fee)
        elif t.side == "sell" and t.code in open_pos:
            bp, bv, bf = open_pos.pop(t.code)
            pnl.append((t.price - bp) * min(bv, t.volume) - bf - t.fee)
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    return {
        "trade_pairs": len(pnl),
        "win_rate": len(wins) / len(pnl) if pnl else 0.0,
        "profit_factor": avg_win / avg_loss if avg_loss else (999.0 if avg_win else 0.0),
        "net_pnl": sum(pnl),
    }


def summarize(equity: list, initial: float, trades: list) -> dict:
    return {
        "final_equity": round(equity[-1], 2) if equity else initial,
        "total_return": round(equity[-1] / initial - 1, 4) if equity else 0.0,
        "annual_return": round(annual_return(equity, initial), 4),
        "max_drawdown": round(max_drawdown(equity), 4),
        "sharpe": round(sharpe(equity), 3),
        "calmar": round(calmar(equity, initial), 3),
        **trade_stats(trades),
    }
