#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多标的组合回测引擎（Web 终端组合回测能力的底层）。

设计纪律：
  - T 日收盘用 bars[:i+1] 产生信号，T+1 开盘执行，防未来函数
  - 组合层统一管现金、权重、再平衡、换手成本，个股层只用同一套策略插件
  - A 股真实规则：T+1、涨跌停不可成交、100 股整数倍、佣金/印花税/过户费/滑点
  - 所有 K 线来自 DataResolver 真实数据，不用随机数、不生成模拟行情
  - 输出组合净值、逐标的贡献、相关性矩阵、换手率、暴露度、绩效指标

与单标的 StrategyEngine 的关系：
  StrategyEngine 是"满仓单票"特例；PortfolioEngine 是多票资金约束版本，
  两者共用 enriched 口径、策略插件和成本模型，语义一致。
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List

from . import metrics as M
from .costs import AShareCosts, TradeRules
from ..strategy.base import get as get_strategy


@dataclass
class PortfolioConfig:
    initial_cash: float = 1_000_000.0
    slippage: float = 0.001
    max_weight: float = 0.20          # 单票最大权重
    max_total_weight: float = 0.80    # 组合最大持仓比例
    rebalance: str = "monthly"        # daily / weekly / monthly / none
    signal_mode: str = "strategy"     # strategy=按策略信号 / weights=按选股权重持有篮子
    rebalance_threshold: float = 0.02 # 权重偏离小于该值不交易，抑制换手
    commission_rate: float = 0.00025

    def validate(self):
        if self.rebalance not in ("daily", "weekly", "monthly", "none"):
            raise ValueError("rebalance 仅支持 daily/weekly/monthly/none")
        if self.signal_mode not in ("strategy", "weights"):
            raise ValueError("signal_mode 仅支持 strategy / weights")
        if not (0 < self.max_weight <= 1 and 0 < self.max_total_weight <= 1):
            raise ValueError("权重上限必须在 (0,1] 区间")
        if self.initial_cash <= 0:
            raise ValueError("初始资金必须大于 0")


@dataclass
class PortfolioTrade:
    date: str
    code: str
    side: str
    price: float
    volume: int
    fee: float
    amount: float


@dataclass
class PortfolioResult:
    codes: List[str]
    dates: List[str]
    equity: List[float]
    trades: List[PortfolioTrade]
    summary: dict
    weights: Dict[str, List[float]] = field(default_factory=dict)
    contributions: dict = field(default_factory=dict)
    correlation: dict = field(default_factory=dict)
    turnover: dict = field(default_factory=dict)
    avg_exposure: float = 0.0
    contracts: dict = field(default_factory=dict)
    rebalances: int = 0

    def to_dict(self, sample: int = 200) -> dict:
        step = max(1, len(self.dates) // sample)
        return {
            "codes": self.codes,
            "dates": self.dates[::step],
            "equity": [round(x, 2) for x in self.equity[::step]],
            "weights": {c: [round(w, 4) for w in ws[::step]]
                        for c, ws in self.weights.items()},
            "trades": [t.__dict__ for t in self.trades[-60:]],
            "summary": self.summary,
            "contributions": self.contributions,
            "correlation": self.correlation,
            "turnover": self.turnover,
            "avg_exposure": round(self.avg_exposure, 4),
            "contracts": self.contracts,
            "rebalances": self.rebalances,
        }


def _pearson(a: list, b: list) -> float:
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    return round(cov / (va * vb) ** 0.5, 4) if va > 0 and vb > 0 else 0.0


def _period_key(date: str, freq: str) -> str:
    d = datetime.strptime(date, "%Y-%m-%d")
    if freq == "daily":
        return date
    if freq == "weekly":
        return f"{d.isocalendar()[0]}-W{d.isocalendar()[1]}"
    if freq == "monthly":
        return date[:7]
    return "once"


class PortfolioEngine:
    """组合级回测：多标的 + 权重 + 再平衡 + 真实成本。"""

    def __init__(self, cfg: PortfolioConfig = None, progress_cb: Callable = None):
        self.cfg = cfg or PortfolioConfig()
        self.cfg.validate()
        self.cb = progress_cb or (lambda i, n, m: None)

    def run(self, bars_by_code: Dict[str, list],
            strategies: Dict[str, str] = None,
            params: Dict[str, dict] = None,
            contracts: dict = None,
            weights: Dict[str, float] = None) -> PortfolioResult:
        """bars_by_code: {code: enriched bars}。strategies: {code: 策略名}。
        weights: 选股器给出的目标权重；不传则等权。"""
        if not bars_by_code:
            raise ValueError("组合为空，拒绝回测（不使用模拟数据）")
        codes = sorted(bars_by_code.keys())
        for c in codes:
            if not bars_by_code[c]:
                raise ValueError(f"{c} K线为空，拒绝回测")

        strategies = strategies or {}
        params = params or {}
        contracts = contracts or {}
        st_objs = {}
        for c in codes:
            name = strategies.get(c, "dual_ma")
            st_objs[c] = get_strategy(name, **(params.get(c) or {}))

        # 日期对齐：取所有标的的共同交易日，避免停牌日拿不到价格却用前收盘伪造
        sets = [set(b["date"] for b in bars_by_code[c]) for c in codes]
        common = sorted(set.intersection(*sets)) if len(sets) > 1 else sorted(sets[0])
        if len(common) < 30:
            raise ValueError(f"共同交易日仅 {len(common)} 根，不足以做组合回测")
        idx = {c: {b["date"]: i for i, b in enumerate(bars_by_code[c])}
               for c in codes}

        base_w = weights or {c: 1.0 / len(codes) for c in codes}
        total_w = sum(max(base_w.get(c, 0), 0) for c in codes)
        if total_w <= 0:
            raise ValueError("目标权重之和为 0")
        base_w = {c: max(base_w.get(c, 0), 0) / total_w for c in codes}

        cash = self.cfg.initial_cash
        pos = {c: 0 for c in codes}
        target = {c: 0.0 for c in codes}
        dates, equity, trades = [], [], []
        wseries = {c: [] for c in codes}
        daily_ret, exposure = [], []
        turnover_value = 0.0
        rebalances = 0
        last_period = None
        prev_open_eq = None

        n = len(common)
        for j, date in enumerate(common):
            # ---- 执行段：用前一交易日收盘产生的目标权重，在今日开盘成交 ----
            if j > 0:
                opens = {c: bars_by_code[c][idx[c][date]]["open"] for c in codes}
                prev_idx = {c: idx[c][common[j - 1]] for c in codes}
                prev_close = {c: bars_by_code[c][prev_idx[c]]["close"] for c in codes}
                eq_open = cash + sum(pos[c] * opens[c] for c in codes)

                # 先卖后买，释放现金
                for c in sorted(codes, key=lambda x: (target[x] - pos[x] * opens[x] / eq_open)):
                    bar = bars_by_code[c][idx[c][date]]
                    board = TradeRules.board_of(c)
                    current_w = pos[c] * opens[c] / eq_open if eq_open else 0
                    delta = target[c] - current_w
                    if abs(delta) < self.cfg.rebalance_threshold or eq_open <= 0:
                        continue
                    if delta < 0 and pos[c] > 0:
                        if TradeRules.is_limit_down(prev_close[c], bar["open"], board):
                            continue
                        px = bar["open"] * (1 - self.cfg.slippage)
                        vol = TradeRules.round_lot(int(-delta * eq_open / px))
                        vol = min(vol, pos[c])
                        if vol < 100:
                            continue
                        amount, fee = px * vol, AShareCosts.total_sell(px * vol)
                        cash += amount - fee
                        pos[c] -= vol
                        turnover_value += amount
                        trades.append(PortfolioTrade(date, c, "sell", px, vol, fee, amount))
                    elif delta > 0:
                        if TradeRules.is_limit_up(prev_close[c], bar["open"], board):
                            continue
                        px = bar["open"] * (1 + self.cfg.slippage)
                        budget = min(delta * eq_open, cash / (1 + 0.0003))
                        vol = TradeRules.round_lot(int(budget / px))
                        if vol < 100:
                            continue
                        amount = px * vol
                        fee = AShareCosts.total_buy(amount)
                        if amount + fee > cash:
                            vol = TradeRules.round_lot(int((cash - fee) / px))
                            if vol < 100:
                                continue
                            amount, fee = px * vol, AShareCosts.total_buy(px * vol)
                        cash -= amount + fee
                        pos[c] += vol
                        turnover_value += amount
                        trades.append(PortfolioTrade(date, c, "buy", px, vol, fee, amount))

            # ---- 信号段：只看截至今日的历史，生成明日开盘目标权重 ----
            period = _period_key(date, self.cfg.rebalance)
            can_rebalance = self.cfg.rebalance == "daily" or (
                self.cfg.rebalance != "none" and period != last_period)
            if can_rebalance:
                rebalances += 1
                raw = {}
                for c in codes:
                    series = bars_by_code[c]
                    i = idx[c][date]
                    if self.cfg.signal_mode == "weights":
                        # 选股篮子模式：目标权重来自选股器，不做个股择时
                        raw[c] = base_w[c]
                        continue
                    try:
                        # 关键：只传截至当日的历史，与 StrategyEngine 一致的防未来函数纪律
                        sig = st_objs[c].on_bars(series[:i + 1], i)
                    except Exception:
                        sig = "HOLD"
                    if sig == "BUY":
                        raw[c] = base_w[c]
                    elif sig == "SELL":
                        raw[c] = 0.0
                    else:
                        cur_close_eq = cash + sum(pos[k] * bars_by_code[k][idx[k][date]]["close"]
                                                  for k in codes)
                        raw[c] = (pos[c] * bars_by_code[c][i]["close"] / cur_close_eq
                                  if cur_close_eq else 0.0)
                # 单票与总仓位约束（按比例缩放，不突破上限）
                raw = {c: min(v, self.cfg.max_weight) for c, v in raw.items()}
                tot = sum(raw.values())
                if tot > self.cfg.max_total_weight:
                    raw = {c: v * self.cfg.max_total_weight / tot for c, v in raw.items()}
                target = raw
                last_period = period

            # ---- 收盘结算 ----
            eq_close = cash + sum(pos[c] * bars_by_code[c][idx[c][date]]["close"]
                                  for c in codes)
            if prev_open_eq and prev_open_eq > 0:
                daily_ret.append(eq_close / prev_open_eq - 1)
            prev_open_eq = eq_close
            dates.append(date)
            equity.append(eq_close)
            for c in codes:
                wseries[c].append(
                    pos[c] * bars_by_code[c][idx[c][date]]["close"] / eq_close
                    if eq_close else 0.0)
            exposure.append(sum(wseries[c][-1] for c in codes))

            if self.cb and (j % max(1, n // 20) == 0 or j == n - 1):
                self.cb(j + 1, n, f"组合回测 {date}")

        # ---- 归因与统计 ----
        contributions = defaultdict(float)
        for t in trades:
            contributions[t.code] += (-1 if t.side == "buy" else 1) * t.amount - t.fee
        contributions = {c: round(v, 2) for c, v in contributions.items()}

        rets_by_code = {}
        for c in codes:
            closes = [bars_by_code[c][idx[c][d]]["close"] for d in common]
            rets_by_code[c] = [closes[k] / closes[k - 1] - 1
                               for k in range(1, len(closes))]
        corr = {a: {b: _pearson(rets_by_code[a], rets_by_code[b])
                    for b in codes if b != a} for a in codes}

        summary = M.summarize(equity, self.cfg.initial_cash, trades)
        summary.update({
            "avg_exposure": round(sum(exposure) / len(exposure), 4),
            "total_turnover": round(turnover_value, 2),
            "turnover_ratio": round(turnover_value / self.cfg.initial_cash, 4),
            "rebalances": rebalances,
            "holding_days": len(common),
        })
        return PortfolioResult(
            codes=codes, dates=dates, equity=equity, trades=trades,
            summary=summary, weights=wseries, contributions=dict(contributions),
            correlation=corr,
            turnover={"total_amount": round(turnover_value, 2),
                      "times_initial": round(turnover_value / self.cfg.initial_cash, 3)},
            avg_exposure=summary["avg_exposure"], contracts=contracts,
            rebalances=rebalances,
        )
