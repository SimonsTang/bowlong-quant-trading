#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StrategyEngine - 回测与实盘共用的统一执行内核（核心借鉴 TSP 第二大机制）。

TSP 做法：回测和实盘共用同一个 StrategyEngine.run，
分钟策略逐日回放 +「当日已知」约束，从根上防未来函数。

本引擎复刻该纪律：
  - 策略只接收截至当前 bar 的历史（past-only），看不到未来
  - 信号在 t 日收盘产生，成交在 t+1 日开盘（A股 T+1 + 防偷看）
  - 回测与实盘用同一个 run_on_bars / step 逻辑，只是数据源不同
  - 支持 enriched 口径、真实成本、涨跌停、100股整数倍
"""
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .costs import AShareCosts, TradeRules
from . import metrics as M


@dataclass
class Trade:
    date: str
    code: str
    side: str
    price: float
    volume: int
    fee: float
    reason: str = ""


@dataclass
class EngineConfig:
    initial_cash: float = 1_000_000
    slippage: float = 0.001
    max_position_pct: float = 0.95   # 单标的最大资金占比
    commission_rate: float = 0.00025


@dataclass
class BacktestResult:
    code: str
    strategy: str
    equity: List[float] = field(default_factory=list)
    trades: List[Trade] = field(default_factory=list)
    initial: float = 0.0
    summary: dict = field(default_factory=dict)
    contract: dict = field(default_factory=dict)


class StrategyEngine:
    """统一执行内核。signal_fn(enriched_bars, i) -> 'BUY'/'SELL'/'HOLD'，
    只能看到 enriched_bars[:i+1]，i 当日收盘出信号，i+1 开盘成交。"""

    def __init__(self, cfg: EngineConfig = None, progress_cb: Callable = None):
        self.cfg = cfg or EngineConfig()
        self.progress_cb = progress_cb  # 供 UI 实时观测回测进度

    def run_on_bars(self, bars: list, signal_fn: Callable, code: str = "",
                    strategy: str = "", contract: dict = None) -> BacktestResult:
        """回测入口：吃 enriched 后的真实K线。"""
        if not bars:
            raise ValueError("K线为空，拒绝回测（不使用模拟数据）")

        cash = self.cfg.initial_cash
        pos = 0
        buy_date = None
        trades: List[Trade] = []
        equity: list = []
        prev_close = None
        n = len(bars)
        board = TradeRules.board_of(code)
        # 关键修正：信号在第 i 日收盘产生，成交必须在第 i+1 日开盘。
        # 原实现用第 i 日收盘信号、第 i 日开盘价成交，构成前视偏差（未来函数）。
        # 这里用 pending 把信号延迟一根 bar 执行，杜绝"偷看当天"。
        pending = "HOLD"

        for i in range(n):
            bar = bars[i]

            # 1) 执行上一交易日收盘产生的信号：用今日开盘价成交
            price = bar["open"] * (1 + self.cfg.slippage)
            if pending == "BUY" and pos == 0 and cash > 0:
                if not TradeRules.is_limit_up(prev_close, bar["open"], board):
                    vol = TradeRules.round_lot(int(cash * self.cfg.max_position_pct / price))
                    if vol >= 100:
                        amount = price * vol
                        fee = AShareCosts.total_buy(amount)
                        if amount + fee <= cash:
                            cash -= amount + fee
                            pos = vol
                            buy_date = bar["date"]
                            trades.append(Trade(bar["date"], code, "buy", price, vol, fee, "signal"))
            elif pending == "SELL" and pos > 0 and bar["date"] != buy_date:
                if not TradeRules.is_limit_down(prev_close, bar["open"], board):
                    sell_px = bar["open"] * (1 - self.cfg.slippage)
                    amount = sell_px * pos
                    fee = AShareCosts.total_sell(amount)
                    cash += amount - fee
                    trades.append(Trade(bar["date"], code, "sell", sell_px, pos, fee, "signal"))
                    pos = 0

            # 2) 今日收盘产生信号，延迟到下一根 bar 开盘执行（只看 bars[:i+1]）
            pending = signal_fn(bars[:i + 1], i) if i > 0 else "HOLD"

            prev_close = bar["close"]
            equity.append(cash + pos * bar["close"])

            if self.progress_cb and (i % max(1, n // 20) == 0 or i == n - 1):
                self.progress_cb(i + 1, n, "回测计算中")

        summary = M.summarize(equity, self.cfg.initial_cash, trades)
        return BacktestResult(code, strategy, equity, trades,
                              self.cfg.initial_cash, summary, contract or {})

    def step_live(self, enriched_bar: dict, signal: str, position: int,
                  cash: float, code: str) -> dict:
        """实盘单步：与 run_on_bars 同一套信号/成本语义。
        返回执行意图，交给合规层+执行层。实盘只产生意图，不在这里下单。"""
        price = enriched_bar.get("close", 0)
        board = TradeRules.board_of(code)
        intent = {"action": "HOLD", "code": code, "reason": ""}
        if signal == "BUY" and position == 0:
            if TradeRules.is_limit_up(enriched_bar.get("prev_close", price), price, board):
                intent["reason"] = "涨停，放弃买入"
            else:
                vol = TradeRules.round_lot(int(cash * self.cfg.max_position_pct / price))
                intent = {"action": "BUY", "code": code, "volume": vol,
                          "ref_price": price, "reason": "策略信号"}
        elif signal == "SELL" and position > 0:
            intent = {"action": "SELL", "code": code, "volume": position,
                      "ref_price": price, "reason": "策略信号"}
        return intent
