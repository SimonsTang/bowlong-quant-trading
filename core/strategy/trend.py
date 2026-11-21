#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""趋势类策略：双均线、MACD、海龟。均为公开经典逻辑，无许可约束。"""
from .base import BaseStrategy, ParamSpec, register


@register
class DualMA(BaseStrategy):
    name = "dual_ma"
    display = "双均线金叉死叉"
    category = "trend"
    desc = "短均线上穿长均线买入，下穿卖出。最经典的趋势跟踪策略。"
    source = "公开经典（均线理论）"
    params = [
        ParamSpec("fast", 5, 3, 30, 1, "快线周期"),
        ParamSpec("slow", 20, 10, 60, 1, "慢线周期"),
    ]

    def on_bars(self, bars, i):
        f, s = int(self.cfg["fast"]), int(self.cfg["slow"])
        if i < s:
            return "HOLD"
        closes = [b["close"] for b in bars]
        ma_f_now = sum(closes[-f:]) / f
        ma_f_prev = sum(closes[-f - 1:-1]) / f
        ma_s_now = sum(closes[-s:]) / s
        ma_s_prev = sum(closes[-s - 1:-1]) / s
        if ma_f_prev <= ma_s_prev and ma_f_now > ma_s_now:
            return "BUY"
        if ma_f_prev >= ma_s_prev and ma_f_now < ma_s_now:
            return "SELL"
        return "HOLD"


@register
class MACDStrategy(BaseStrategy):
    name = "macd"
    display = "MACD 金叉死叉"
    category = "trend"
    desc = "DIF 上穿 DEA 买入，下穿卖出。"
    source = "公开经典（Appel）"
    params = [
        ParamSpec("fast", 12, 5, 20, 1, "快线"),
        ParamSpec("slow", 26, 15, 40, 1, "慢线"),
        ParamSpec("signal", 9, 5, 15, 1, "信号线"),
    ]

    def on_bars(self, bars, i):
        if i < self.cfg["slow"] + self.cfg["signal"]:
            return "HOLD"
        dif, dea = bars[i].get("dif"), bars[i].get("dea")
        pdif, pdea = bars[i - 1].get("dif"), bars[i - 1].get("dea")
        if None in (dif, dea, pdif, pdea):
            return "HOLD"
        if pdif <= pdea and dif > dea:
            return "BUY"
        if pdif >= pdea and dif < dea:
            return "SELL"
        return "HOLD"


@register
class Turtle(BaseStrategy):
    name = "turtle"
    display = "海龟通道突破"
    category = "breakout"
    desc = "价格突破前N日高点买入，跌破前M日低点卖出（唐奇安通道），ATR 定仓位。"
    source = "公开经典（Richard Dennis 海龟法则）"
    params = [
        ParamSpec("entry", 20, 10, 55, 1, "入市通道天数"),
        ParamSpec("exit", 10, 5, 20, 1, "离市通道天数"),
    ]

    def on_bars(self, bars, i):
        e, x = int(self.cfg["entry"]), int(self.cfg["exit"])
        if i < max(e, x) + 1:
            return "HOLD"
        close = bars[i]["close"]
        hh = max(b["high"] for b in bars[i - e:i])   # 不含当日，防未来
        ll = min(b["low"] for b in bars[i - x:i])
        if close >= hh:
            return "BUY"
        if close <= ll:
            return "SELL"
        return "HOLD"
