#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
因子归因（借鉴 TSP 的因子贡献分析）。
把策略收益拆到各因子贡献上，回答"钱是哪个因子赚的"，
避免策略失效时不知道问题出在哪。用简单的分桶归因法，纯标准库。
"""
from collections import defaultdict


def factor_attribution(signal_log: list, trades: list) -> dict:
    """signal_log: [{date, code, signal, factors:{ma:..., rsi:..., ...}}]
    trades: 成交流水。按 signal 里激活的因子，把对应卖出实现的盈亏归到因子。"""
    factor_pnl = defaultdict(float)
    factor_count = defaultdict(int)

    # 建立 code -> 最近一次买入因子 的映射
    entry_factors = {}
    for s in signal_log:
        if s.get("signal") == "BUY":
            entry_factors[s.get("code", "")] = s.get("factors", {})

    open_price = {}
    for t in trades:
        if t.side == "buy":
            open_price[t.code] = t.price
        elif t.side == "sell" and t.code in open_price:
            pnl = (t.price - open_price[t.code]) * t.volume - t.fee
            factors = entry_factors.get(t.code, {})
            active = [f for f, v in factors.items() if v] or ["unattributed"]
            for f in active:
                factor_pnl[f] += pnl / len(active)
                factor_count[f] += 1
            open_price.pop(t.code, None)

    total = sum(factor_pnl.values())
    return {
        "factors": [
            {"factor": f, "pnl": round(v, 2), "trades": factor_count[f],
             "contribution": round(v / total, 4) if total else 0.0}
            for f, v in sorted(factor_pnl.items(), key=lambda x: -abs(x[1]))
        ],
        "total_pnl": round(total, 2),
    }
