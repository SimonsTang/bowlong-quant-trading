#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""均值回归类策略：布林带、RSI、KDJ。均为公开经典技术指标逻辑。"""
from .base import BaseStrategy, ParamSpec, register


@register
class BollingerRevert(BaseStrategy):
    name = "bollinger"
    display = "布林带均值回归"
    category = "mean_revert"
    desc = "触及下轨买入，触及上轨卖出，回归中轨平仓。"
    source = "公开经典（Bollinger）"
    params = [
        ParamSpec("window", 20, 10, 40, 1, "窗口"),
        ParamSpec("nstd", 2.0, 1.0, 3.0, 0.1, "标准差倍数"),
    ]

    def on_bars(self, bars, i):
        if i < self.cfg["window"]:
            return "HOLD"
        b = bars[i]
        low, up, mid, close = b.get("boll_low"), b.get("boll_up"), b.get("boll_mid"), b["close"]
        if None in (low, up, mid):
            return "HOLD"
        if close <= low:
            return "BUY"
        if close >= up or (mid and close >= mid and bars[i - 1]["close"] < mid):
            return "SELL"
        return "HOLD"


@register
class RSIStrategy(BaseStrategy):
    name = "rsi"
    display = "RSI 超买超卖"
    category = "mean_revert"
    desc = "RSI 低于超卖线买入，高于超买线卖出。"
    source = "公开经典（Wilder）"
    params = [
        ParamSpec("period", 14, 6, 24, 1, "RSI周期"),
        ParamSpec("oversold", 30, 10, 45, 1, "超卖线"),
        ParamSpec("overbought", 70, 55, 90, 1, "超买线"),
    ]

    def on_bars(self, bars, i):
        rsi = bars[i].get("rsi14")
        if rsi is None:
            return "HOLD"
        if rsi <= self.cfg["oversold"]:
            return "BUY"
        if rsi >= self.cfg["overbought"]:
            return "SELL"
        return "HOLD"


@register
class KDJStrategy(BaseStrategy):
    name = "kdj"
    display = "KDJ 随机指标"
    category = "mean_revert"
    desc = "J 值超卖区上穿 K 买入，超买区下穿卖出。"
    source = "公开经典（Stochastic）"
    params = [
        ParamSpec("low", 20, 5, 40, 1, "超卖阈值"),
        ParamSpec("high", 80, 60, 95, 1, "超买阈值"),
    ]

    def on_bars(self, bars, i):
        j, k = bars[i].get("j"), bars[i].get("k")
        pj, pk = (bars[i - 1].get("j"), bars[i - 1].get("k")) if i > 0 else (None, None)
        if None in (j, k, pj, pk):
            return "HOLD"
        if pj <= self.cfg["low"] and j > self.cfg["low"] and j > k:
            return "BUY"
        if pj >= self.cfg["high"] and j < self.cfg["high"] and j < k:
            return "SELL"
        return "HOLD"
