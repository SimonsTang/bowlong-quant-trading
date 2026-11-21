#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
突破类策略：Dual Thrust 区间突破（Michael Chalek 1980s）A股日线适配版。

原始版本：日内用「今开 ± K×过去N日区间」构造上下轨，突破上轨开多、
跌破下轨反手开空，收盘平仓。A股现货不能日内反手做空、且 T+1，
因此本实现改为：
  - 用过去 N 日（不含当日）计算 HH/LC/HC/LL 与 Range=max(HH-LC, HC-LL)
  - 当日收盘价相对「今开 ± K×Range」确认突破（收盘确认，避免盘中假突破）
  - 引擎统一在次日开盘成交（前视零容忍）
  - SELL 只平多，不开空（A股现货约束）
  - 可选 MA20 趋势过滤、可选固定百分比止损（以信号收盘价为成本参考）

严格 past-only：on_bars(bars, i) 只读 bars[:i+1]，不使用 i 之后任何数据。
"""
from .base import BaseStrategy, ParamSpec, register


@register
class DualThrust(BaseStrategy):
    name = "dual_thrust"
    display = "Dual Thrust 区间突破"
    category = "breakout"
    desc = ("过去N日区间 Range=max(HH-LC,HC-LL)，收盘确认突破 开盘±K×Range；"
            "A股版只做多、T+1次日开盘成交，支持趋势过滤与止损")
    source = "Michael Chalek(1980s) 经典区间突破；A股日线适配"
    params = [
        ParamSpec("N", 5, 2, 15, 1, "回看交易日数（不含当日）"),
        ParamSpec("K1", 0.5, 0.1, 1.0, 0.1, "上轨系数：开盘价 + K1×Range"),
        ParamSpec("K2", 0.5, 0.1, 1.0, 0.1, "下轨系数：开盘价 − K2×Range"),
        ParamSpec("trend", 0, 0, 1, 1, "1=仅在收盘价站上MA20时允许开多"),
        ParamSpec("stop", 0.0, 0.0, 0.10, 0.01, "固定止损比例，0=不启用"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._long = False
        self._entry_ref = 0.0
        self._last_i = -1

    def on_bars(self, bars, i):
        # 新序列/回卷时重置内部持仓镜像
        if i <= self._last_i:
            self._long, self._entry_ref = False, 0.0
        self._last_i = i

        n = int(self.cfg["N"])
        if i < n + 1:
            return "HOLD"

        # 只用过去 N 根（不含当日），避免把当日极值混入 Range
        past = bars[i - n:i]
        hh = max(b["high"] for b in past)
        lc = min(b["close"] for b in past)
        hc = max(b["close"] for b in past)
        ll = min(b["low"] for b in past)
        rng = max(hh - lc, hc - ll)
        if rng <= 0:
            return "HOLD"

        today = bars[i]
        upper = today["open"] + float(self.cfg["K1"]) * rng
        lower = today["open"] - float(self.cfg["K2"]) * rng
        close = today["close"]

        # 止损优先：成本参考取上一次 BUY 信号收盘价（因果可知）
        stop = float(self.cfg["stop"])
        if self._long and stop > 0 and self._entry_ref > 0 and close <= self._entry_ref * (1 - stop):
            self._long = False
            return "SELL"

        if close >= upper:
            ma20 = today.get("ma20")
            if int(self.cfg["trend"]) == 1 and (ma20 is None or close < ma20):
                return "HOLD"
            if not self._long:
                self._long = True
                self._entry_ref = close
            return "BUY"          # 已持仓时引擎会忽略重复 BUY

        if close <= lower and self._long:
            self._long = False
            return "SELL"

        return "HOLD"
