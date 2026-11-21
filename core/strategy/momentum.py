#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""动量类策略：双动量、ROC 趋势动量。公开经典逻辑。"""
from .base import BaseStrategy, ParamSpec, register


@register
class Momentum(BaseStrategy):
    name = "momentum"
    display = "N 日动量"
    category = "momentum"
    desc = "N 日收益率为正且突破近期高点买入，转负卖出。动量效应经典实现。"
    source = "公开经典（Momentum Effect）"
    params = [
        ParamSpec("lookback", 20, 5, 60, 1, "回看周期"),
        ParamSpec("threshold", 0.03, 0.0, 0.15, 0.01, "动量阈值"),
    ]

    def on_bars(self, bars, i):
        n = int(self.cfg["lookback"])
        if i < n:
            return "HOLD"
        ret = bars[i]["close"] / bars[i - n]["close"] - 1
        prev_ret = bars[i - 1]["close"] / bars[i - n - 1]["close"] - 1 if i > n else 0
        if prev_ret <= self.cfg["threshold"] and ret > self.cfg["threshold"]:
            return "BUY"
        if ret < 0:
            return "SELL"
        return "HOLD"


@register
class DualMomentum(BaseStrategy):
    name = "dual_momentum"
    display = "双动量轮动"
    category = "momentum"
    desc = "短周期动量强于长周期且为正买入，短线转负卖出。Gary Antonacci 双动量思想。"
    source = "公开经典（Antonacci 双动量）"
    params = [
        ParamSpec("short", 20, 5, 40, 1, "短周期"),
        ParamSpec("long", 60, 30, 120, 1, "长周期"),
    ]

    def on_bars(self, bars, i):
        s, l = int(self.cfg["short"]), int(self.cfg["long"])
        if i < l:
            return "HOLD"
        rs = bars[i]["close"] / bars[i - s]["close"] - 1
        rl = bars[i]["close"] / bars[i - l]["close"] - 1
        prs = bars[i - 1]["close"] / bars[i - 1 - s]["close"] - 1
        prl = bars[i - 1]["close"] / bars[i - 1 - l]["close"] - 1
        if prs <= prl and rs > rl and rs > 0:
            return "BUY"
        if rs < 0:
            return "SELL"
        return "HOLD"
