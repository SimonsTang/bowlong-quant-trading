#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
技术指标库 - 纯标准库实现，零第三方依赖。
借鉴 TSP 的「现算指标」思路：只存基础K线，指标全部按需计算，
策略/回测/监控/复盘吃同一份口径，从根上消除口径漂移。

所有函数输入为按时间正序排列的 K线 dict 列表，
返回与输入等长的 list（暖机期为 None），保证不会引入未来数据。
"""


def sma(values: list, window: int) -> list:
    """简单移动平均。"""
    out = [None] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= window:
            s -= values[i - window]
        if i >= window - 1:
            out[i] = s / window
    return out


def ema(values: list, window: int) -> list:
    """指数移动平均，首值用第一个数据点初始化。"""
    out = [None] * len(values)
    if not values:
        return out
    k = 2.0 / (window + 1)
    prev = values[0]
    out[0] = prev
    for i in range(1, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def macd(values: list, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD：返回 (DIF, DEA, MACD柱)。"""
    ef, es = ema(values, fast), ema(values, slow)
    dif = [f - s if f is not None and s is not None else None for f, s in zip(ef, es)]
    dea = ema([d if d is not None else 0.0 for d in dif], signal)
    hist = [(d - e) * 2 if d is not None and e is not None else None for d, e in zip(dif, dea)]
    return dif, dea, hist


def rsi(values: list, window: int = 14) -> list:
    """RSI（Wilder 平滑）。"""
    out = [None] * len(values)
    if len(values) <= window:
        return out
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[:window]) / window
    avg_l = sum(losses[:window]) / window
    out[window] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    for i in range(window, len(gains)):
        avg_g = (avg_g * (window - 1) + gains[i]) / window
        avg_l = (avg_l * (window - 1) + losses[i]) / window
        out[i + 1] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return out


def bollinger(values: list, window: int = 20, nstd: float = 2.0):
    """布林带：返回 (中轨, 上轨, 下轨)。"""
    mid = sma(values, window)
    up, low = [None] * len(values), [None] * len(values)
    for i in range(window - 1, len(values)):
        seg = values[i - window + 1:i + 1]
        m = mid[i]
        var = sum((x - m) ** 2 for x in seg) / window
        sd = var ** 0.5
        up[i], low[i] = m + nstd * sd, m - nstd * sd
    return mid, up, low


def kdj(bars: list, n: int = 9, m1: int = 3, m2: int = 3):
    """KDJ 随机指标：返回 (K, D, J)。"""
    k_vals, d_vals, j_vals = [None] * len(bars), [None] * len(bars), [None] * len(bars)
    k, d = 50.0, 50.0
    for i in range(len(bars)):
        if i < n - 1:
            continue
        seg = bars[i - n + 1:i + 1]
        hh = max(b["high"] for b in seg)
        ll = min(b["low"] for b in seg)
        rsv = 50.0 if hh == ll else (bars[i]["close"] - ll) / (hh - ll) * 100
        k = (m1 - 1) / m1 * k + 1 / m1 * rsv
        d = (m2 - 1) / m2 * d + 1 / m2 * k
        k_vals[i], d_vals[i], j_vals[i] = k, d, 3 * k - 2 * d
    return k_vals, d_vals, j_vals


def atr(bars: list, window: int = 14) -> list:
    """真实波幅 ATR。"""
    out = [None] * len(bars)
    if len(bars) < 2:
        return out
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < window:
        return out
    prev = sum(trs[:window]) / window
    out[window] = prev
    for i in range(window, len(trs)):
        prev = (prev * (window - 1) + trs[i]) / window
        out[i + 1] = prev
    return out


def donchian(bars: list, window: int = 20):
    """唐奇安通道：返回 (上轨, 下轨)，取前 window 根不含当前（防未来）。"""
    up, low = [None] * len(bars), [None] * len(bars)
    for i in range(window, len(bars)):
        seg = bars[i - window:i]   # 关键：不含 i，海龟突破用前N日高低点
        up[i] = max(b["high"] for b in seg)
        low[i] = min(b["low"] for b in seg)
    return up, low


def pct_change(values: list, n: int = 1) -> list:
    """N 日涨跌幅。"""
    out = [None] * len(values)
    for i in range(n, len(values)):
        if values[i - n]:
            out[i] = values[i] / values[i - n] - 1
    return out


def rolling_return_rank(values: list, window: int = 20) -> list:
    """简化 RPS：当前值在近 window 个值中的百分位排名(0-100)。
    注意：这是时序相对强弱，非全市场截面 RPS。全市场 RPS 见 factor.py。"""
    out = [None] * len(values)
    for i in range(window - 1, len(values)):
        seg = values[i - window + 1:i + 1]
        cur = seg[-1]
        out[i] = sum(1 for x in seg if x < cur) / (window - 1) * 100
    return out
