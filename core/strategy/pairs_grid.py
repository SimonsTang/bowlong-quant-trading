#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配对交易 + 网格策略。均为公开经典逻辑，无许可约束。"""
import math

from .base import BaseStrategy, ParamSpec, register


def spread_zscore(spread: list, window: int) -> list:
    """价差序列的滚动 z-score（配对交易核心信号）。"""
    out = [None] * len(spread)
    for i in range(window - 1, len(spread)):
        seg = spread[i - window + 1:i + 1]
        m = sum(seg) / window
        sd = (sum((x - m) ** 2 for x in seg) / window) ** 0.5
        out[i] = (spread[i] - m) / sd if sd else 0.0
    return out


@register
class PairTrade(BaseStrategy):
    name = "pairs"
    display = "配对交易（价差Z-Score）"
    category = "pairs"
    desc = "价差z-score超上轨做空价差、低于下轨做多价差。需传入配对合成价差bar（含spread字段）。"
    source = "公开经典（统计套利 Pairs Trading）"
    params = [
        ParamSpec("window", 20, 10, 60, 1, "价差窗口"),
        ParamSpec("entry_z", 2.0, 1.0, 3.0, 0.1, "入场z阈值"),
        ParamSpec("exit_z", 0.5, 0.0, 1.5, 0.1, "出场z阈值"),
    ]

    def on_bars(self, bars, i):
        w = int(self.cfg["window"])
        if i < w or "spread" not in bars[i]:
            return "HOLD"
        spread = [b["spread"] for b in bars]
        z = spread_zscore(spread, w)[i]
        if z is None:
            return "HOLD"
        if z <= -self.cfg["entry_z"]:
            return "BUY"      # 做多价差
        if z >= self.cfg["entry_z"]:
            return "SELL"     # 做空价差（简化为离场）
        if abs(z) <= self.cfg["exit_z"]:
            return "SELL"     # 回归，平仓
        return "HOLD"


@register
class GridTrade(BaseStrategy):
    name = "grid"
    display = "网格交易"
    category = "grid"
    desc = "以基准价为中心按固定步长铺设网格，跌一格买、涨一格卖。震荡市有效。"
    source = "公开经典（Grid Trading）"
    params = [
        ParamSpec("step", 0.02, 0.005, 0.05, 0.005, "网格步长(比例)"),
        ParamSpec("lookback", 20, 10, 60, 1, "基准回看周期"),
    ]

    def on_bars(self, bars, i):
        lb = int(self.cfg["lookback"])
        if i < lb:
            return "HOLD"
        base = bars[i - lb]["close"]
        step = self.cfg["step"]
        if base <= 0:
            return "HOLD"
        level_now = math.floor(math.log(bars[i]["close"] / base) / math.log(1 + step))
        level_prev = math.floor(math.log(bars[i - 1]["close"] / base) / math.log(1 + step))
        if level_now < level_prev:
            return "BUY"
        if level_now > level_prev:
            return "SELL"
        return "HOLD"


@register
class DualThrust(BaseStrategy):
    name = "dual_thrust"
    display = "Dual Thrust 区间突破"
    category = "breakout"
    desc = "用前N日HH/LC/HC/LL算区间，开盘突破上轨做多、下轨做空。期货日内经典。"
    source = "公开经典（Dual Thrust，vnpy_ctastrategy 同源逻辑自研）"
    params = [
        ParamSpec("window", 5, 3, 10, 1, "回看天数N"),
        ParamSpec("k1", 0.5, 0.2, 1.0, 0.1, "上轨系数K1"),
        ParamSpec("k2", 0.5, 0.2, 1.0, 0.1, "下轨系数K2"),
    ]

    def on_bars(self, bars, i):
        n = int(self.cfg["window"])
        if i < n:
            return "HOLD"
        hist = bars[i - n:i]
        hh = max(b["high"] for b in hist)
        lc = min(b["close"] for b in hist)
        hc = max(b["close"] for b in hist)
        ll = min(b["low"] for b in hist)
        rng = max(hh - lc, hc - ll)
        upper = bars[i]["open"] + self.cfg["k1"] * rng
        lower = bars[i]["open"] - self.cfg["k2"] * rng
        close = bars[i]["close"]
        if close > upper:
            return "BUY"
        if close < lower:
            return "SELL"
        return "HOLD"


@register
class ATRChannel(BaseStrategy):
    name = "atr_channel"
    display = "ATR 通道突破+波动止损"
    category = "breakout"
    desc = "突破N日高点入场，入场后以2倍ATR移动止损。风控完善的趋势策略。"
    source = "公开经典（海龟衍生 / vnpy ATR 通道自研）"
    params = [
        ParamSpec("window", 20, 10, 55, 1, "突破通道"),
        ParamSpec("atr_mult", 2.0, 1.0, 4.0, 0.1, "ATR止损倍数"),
    ]

    def on_bars(self, bars, i):
        w = int(self.cfg["window"])
        if i < w:
            return "HOLD"
        close = bars[i]["close"]
        hh = max(b["high"] for b in bars[i - w:i])
        if close >= hh:
            return "BUY"
        # 简化移动止损：跌破 N 日均线视为离场（完整 ATR 追踪止损见风控层）
        ma = bars[i].get("ma20")
        if ma and close < ma:
            return "SELL"
        return "HOLD"
