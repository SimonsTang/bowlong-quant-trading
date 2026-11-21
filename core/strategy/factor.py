#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多因子策略 + 全市场截面 RPS 选股。
修正旧仓库 stock-picker 的"假 RPS"（个股涨幅映射），
这里实现真正的全市场截面排名 RPS（借鉴 qlib/WorldQuant Alpha 思想）。

cross_sectional_rps: 传入当日全市场 {code: ret} 字典，返回真实截面百分位排名。
"""
from .base import BaseStrategy, ParamSpec, register


def cross_sectional_rps(returns: dict) -> dict:
    """真实截面 RPS：当日全市场 N 日收益率的百分位排名(0-100)。
    returns: {code: n日收益率}。返回 {code: rps}。"""
    if not returns:
        return {}
    items = sorted(returns.items(), key=lambda x: x[1])
    n = len(items)
    return {code: i / (n - 1) * 100 if n > 1 else 50.0
            for i, (code, _) in enumerate(items)}


def multi_factor_score(quote: dict, rps: float, pe: float = None,
                       low_turnover: bool = False) -> float:
    """多因子打分（防追涨杀跌，借鉴旧仓库 V2.1 思路但用真实截面RPS）：
    - 动量因子：截面 RPS 在 [rps_low, rps_high] 甜区（不追极端高位）
    - 估值因子：PE 在合理区间
    - 低换手：过滤过热标的
    """
    score = 0.0
    if 70 <= rps <= 85:
        score += 1.0       # 强势但未极端
    elif 60 <= rps < 70:
        score += 0.5
    elif rps > 90:
        score -= 0.5       # 过热，追高风险
    if pe is not None:
        if 5 <= pe <= 30:
            score += 1.0
        elif pe > 60 or pe <= 0:
            score -= 0.5
    if low_turnover:
        score += 0.3
    return score


@register
class MultiFactorSelect(BaseStrategy):
    name = "multi_factor"
    display = "多因子选股（真实截面RPS）"
    category = "factor"
    desc = "截面RPS甜区+估值+低换手综合打分， score 越界触发买卖。用于选股，非择时。"
    source = "借鉴 qlib/WorldQuant Alpha + 修正旧仓库假RPS"
    params = [
        ParamSpec("buy_score", 1.5, 0.5, 2.5, 0.1, "买入分数阈值"),
        ParamSpec("sell_score", 0.0, -1.0, 1.0, 0.1, "卖出分数阈值"),
    ]

    def on_bars(self, bars, i):
        # 单标的上下文中用时序 RPS 近似；全市场选股请用 cross_sectional_rps
        b = bars[i]
        rps = b.get("rps20")
        if rps is None:
            return "HOLD"
        pe = b.get("pe")
        score = multi_factor_score(b, rps, pe)
        if score >= self.cfg["buy_score"]:
            return "BUY"
        if score <= self.cfg["sell_score"]:
            return "SELL"
        return "HOLD"
