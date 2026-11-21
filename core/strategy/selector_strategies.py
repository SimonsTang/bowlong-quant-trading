#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
选股策略插件库 —— 10 个不同角度的选股策略（全部基于公开金融理论 + 真实数据）。

借鉴来源（已在 GitHub 核实）：
  - qlib Alpha158 / WorldQuant Alpha101：因子化选股思想（价值/动量/质量/波动/流动性）
  - Fama-French 三因子/五因子：价值(HML)、规模(SMB)、盈利(RMW)
  - 格雷厄姆价值投资：低PE/PB安全边际
  - 动量效应(Jegadeesh-Titman)：强者恒强
  - 反转效应(De Bondt-Thaler)：超跌反弹
  - 质量因子(ROE/ROA)、低波动异象、资金流选股

每个策略实现 score(f, ctx) -> (score, detail)，f 为真实基本面字段，
ctx 为历史动量/波动率等上下文。**每个策略通过 PARAMS 声明自己的可调参数**，
UI 按策略动态渲染，不再使用固定一套参数。默认值与历史回测口径一致。

许可：全部为公开金融理论，按公式自研实现，无代码许可风险。
"""
from abc import ABC, abstractmethod
from typing import Dict


def _P(key, label, default, lo, hi, step=1, tip=""):
    """参数定义（供 UI 动态渲染）。"""
    return {"key": key, "label": label, "default": default,
            "min": lo, "max": hi, "step": step, "tip": tip}


class BaseSelectorStrategy(ABC):
    name = "base"
    display = "基础选股"
    theory = ""
    angle = ""
    needed = ""
    desc = ""
    PARAMS = []          # 每个策略覆盖：仅声明自己真正用到的参数
    COMMON_PARAMS = []   # 通用参数由 UI 单独渲染（选股数 / 最小成交额 / 动量候选池）

    @abstractmethod
    def score(self, f: dict, ctx: dict) -> tuple:
        """返回 (分数, 因子明细dict)。分数越高越优先。"""
        raise NotImplementedError

    def prefilter(self, f: dict, ctx: dict = None) -> bool:
        """策略特定过滤，默认不过滤。ctx 携带该策略的可调参数。"""
        return True

    def needs_history(self) -> bool:
        """是否需要历史K线上下文（动量/反转/低波/技术/多因子）。"""
        return False

    def info(self) -> dict:
        return {"name": self.name, "display": self.display, "theory": self.theory,
                "angle": self.angle, "needed": self.needed, "desc": self.desc,
                "needs_history": self.needs_history(), "params": self.PARAMS}


def _rank(v, low, high, reverse=False):
    """把值映射到0-1分数，reverse=True表示越小越好。"""
    if v is None or v != v:
        return 0.5
    r = (v - low) / (high - low) if high > low else 0.5
    r = max(0.0, min(1.0, r))
    return 1 - r if reverse else r


def _params(ctx):
    """从上下文取该策略参数（缺省时用类内默认值，由 PARAMS 推导）。"""
    return (ctx or {}).get("params") or {}


def _pv(p, key, fallback):
    v = p.get(key, fallback)
    try:
        return float(v)
    except (TypeError, ValueError):
        return fallback


# ---------------- 1. 价值选股 ----------------
class ValueStrategy(BaseSelectorStrategy):
    name = "value"
    display = "价值选股 · 低估值"
    theory = "格雷厄姆安全边际 / Fama-French HML价值因子"
    angle = "寻找被低估的股票：低PE、低PB，有安全边际"
    needed = "PE(动/静)、PB、市值"
    desc = "低PE+低PB双低筛选，选蓝筹价值股。适合震荡市与长期持有。"
    PARAMS = [
        _P("pe_upper", "PE上限", 40, 1, 300, 1, "剔除PE高于该值的标的"),
        _P("pb_upper", "PB上限", 10, 0.1, 50, 0.1, "剔除PB高于该值的标的"),
        _P("w_pe", "PE权重", 0.6, 0, 1, 0.05, "PB权重自动取 1-PE权重"),
    ]

    def prefilter(self, f, ctx=None):
        p = _params(ctx)
        pe, pb = f.get("pe"), f.get("pb")
        return (pe is not None and 0 < pe <= _pv(p, "pe_upper", 40)
                and pb is not None and 0 < pb <= _pv(p, "pb_upper", 10))

    def score(self, f, ctx):
        p = _params(ctx)
        pe, pb = f["pe"], f["pb"]
        s_pe = _rank(pe, 3, _pv(p, "pe_upper", 40), reverse=True)
        s_pb = _rank(pb, 0.5, _pv(p, "pb_upper", 10) * 0.6, reverse=True)
        w = _pv(p, "w_pe", 0.6)
        score = w * s_pe + (1 - w) * s_pb
        return score, {"PE": round(pe, 2), "PB": round(pb, 2),
                       "f_pe": round(s_pe, 3), "f_pb": round(s_pb, 3)}


# ---------------- 2. 成长选股 ----------------
class GrowthStrategy(BaseSelectorStrategy):
    name = "growth"
    display = "成长选股 · 高增长"
    theory = "成长投资 / 盈利因子(RMW)"
    angle = "寻找业绩高速增长的公司：营收同比、净利同比双高"
    needed = "营收同比、净利同比、营收规模"
    desc = "营收与净利润同比增速双高优先，捕捉业绩爆发期公司。波动较大。"
    PARAMS = [
        _P("min_rev_yoy", "营收同比下限%", 0, -50, 100, 1, "低于该增速的标的剔除"),
        _P("min_profit_yoy", "净利同比下限%", -50, -100, 200, 5, "低于该增速的标的剔除"),
        _P("w_revenue", "营收权重", 0.45, 0, 1, 0.05, "净利权重自动取 1-营收权重"),
    ]

    def prefilter(self, f, ctx=None):
        p = _params(ctx)
        rev, profit = f.get("revenue_yoy"), f.get("profit_yoy")
        return (rev is not None and profit is not None
                and rev > _pv(p, "min_rev_yoy", 0)
                and profit > _pv(p, "min_profit_yoy", -50))

    def score(self, f, ctx):
        p = _params(ctx)
        rev, profit = f["revenue_yoy"], f["profit_yoy"]
        s_rev = _rank(rev, _pv(p, "min_rev_yoy", 0), 50)
        s_profit = _rank(profit, -20, 100)
        w = _pv(p, "w_revenue", 0.45)
        score = w * s_rev + (1 - w) * s_profit
        return score, {"营收同比%": round(rev, 2), "净利同比%": round(profit, 2),
                       "f_营收": round(s_rev, 3), "f_净利": round(s_profit, 3)}


# ---------------- 3. 动量选股 ----------------
class MomentumStrategy(BaseSelectorStrategy):
    name = "stock_momentum"
    display = "动量选股 · 强者恒强"
    theory = "Jegadeesh-Titman 动量效应 / qlib Alpha158 价格动量"
    angle = "买入近期涨幅领先、趋势强劲的股票"
    needed = "近N日涨幅(历史K线)、当日涨跌幅"
    desc = "真实历史动量截面排名 + 近期强势，选趋势龙头。趋势市表现好，反转市回撤大。"
    PARAMS = [
        _P("lookback_days", "动量回看日", 60, 20, 250, 5, "历史涨幅计算窗口，影响截面排名"),
        _P("chg_high", "今日涨幅上限%", 8, -20, 30, 1, "当日涨幅打分的上界，避免追高"),
        _P("w_momentum", "历史动量权重", 0.75, 0, 1, 0.05, "当日强度权重自动取 1-该值"),
    ]

    def needs_history(self):
        return True

    def score(self, f, ctx):
        p = _params(ctx)
        mr = ctx.get("momentum_rank", 50.0)
        chg = f.get("change_pct", 0)
        s_mr = mr / 100.0
        s_chg = _rank(chg, -5, _pv(p, "chg_high", 8))
        w = _pv(p, "w_momentum", 0.75)
        score = w * s_mr + (1 - w) * s_chg
        return score, {"动量排名": round(mr, 1), "今日涨幅%": round(chg, 2),
                       "f_动量": round(s_mr, 3), "f_强度": round(s_chg, 3)}


# ---------------- 4. 反转选股 ----------------
class ReversalStrategy(BaseSelectorStrategy):
    name = "reversal"
    display = "反转选股 · 超跌反弹"
    theory = "De Bondt-Thaler 长期反转效应 / 短期超卖修复"
    angle = "寻找超跌但基本面健康的股票，博反弹"
    needed = "近N日涨幅(历史K线)、当日涨跌幅、ROE"
    desc = "历史跌幅大 + 基本面不差(ROE>0) 的错杀股。与动量策略互补。"
    PARAMS = [
        _P("min_roe", "ROE下限%", 0, -20, 50, 1, "剔除基本面恶化标的，默认0"),
        _P("roe_high", "ROE评分上界%", 20, 1, 100, 1, "ROE打分达到满分的上界"),
        _P("w_reversal", "超跌因子权重", 0.6, 0, 1, 0.05, "质量因子权重自动取 1-该值"),
    ]

    def needs_history(self):
        return True

    def prefilter(self, f, ctx=None):
        roe = f.get("roe")
        return roe is not None and roe > _pv(_params(ctx), "min_roe", 0)

    def score(self, f, ctx):
        p = _params(ctx)
        mr = ctx.get("momentum_rank", 50.0)  # 排名低=跌得多
        roe = f.get("roe", 0)
        s_rev = 1 - mr / 100.0
        s_qual = _rank(roe, _pv(p, "min_roe", 0), _pv(p, "roe_high", 20))
        w = _pv(p, "w_reversal", 0.6)
        score = w * s_rev + (1 - w) * s_qual
        return score, {"动量排名(低=超跌)": round(mr, 1), "ROE%": round(roe, 2),
                       "f_超跌": round(s_rev, 3), "f_质量": round(s_qual, 3)}


# ---------------- 5. 质量选股 ----------------
class QualityStrategy(BaseSelectorStrategy):
    name = "quality"
    display = "质量选股 · 高ROE"
    theory = "质量因子 / Novy-Marx 盈利能力 / Fama-French RMW"
    angle = "选盈利能力强的好公司：高ROE + 合理估值"
    needed = "ROE、PE、PB"
    desc = "高ROE为核心，PE/PB适度约束避免为质量付过高溢价。适合长期持有。"
    PARAMS = [
        _P("min_roe", "ROE下限%", 5, -10, 60, 1, "低于该盈利能力的标的剔除"),
        _P("pe_upper", "PE上限", 40, 1, 300, 1, "估值约束，避免为质量付过高溢价"),
        _P("w_roe", "ROE权重", 0.7, 0, 1, 0.05, "估值权重自动取 1-该值"),
    ]

    def prefilter(self, f, ctx=None):
        p = _params(ctx)
        roe = f.get("roe")
        return roe is not None and roe > _pv(p, "min_roe", 5)

    def score(self, f, ctx):
        p = _params(ctx)
        roe = f["roe"]
        pe = f.get("pe") or 30
        s_roe = _rank(roe, _pv(p, "min_roe", 5), 30)
        s_val = _rank(pe, 5, _pv(p, "pe_upper", 40), reverse=True)
        w = _pv(p, "w_roe", 0.7)
        score = w * s_roe + (1 - w) * s_val
        return score, {"ROE%": round(roe, 2), "PE": round(pe, 2),
                       "f_盈利": round(s_roe, 3), "f_估值": round(s_val, 3)}


# ---------------- 6. 低波动选股 ----------------
class LowVolStrategy(BaseSelectorStrategy):
    name = "low_volatility"
    display = "低波动选股 · 稳健"
    theory = "低波动异象(Black 1972) / qlib Alpha158 波动因子"
    angle = "选波动小、走势平稳的股票，追求风险调整后收益"
    needed = "历史波动率(历史K线)、换手率、振幅"
    desc = "低历史波动 + 低换手，选防御性标的。熊市抗跌，牛市弹性不足。"
    PARAMS = [
        _P("vol_upper", "日波动率上界%", 6, 1, 20, 0.5, "波动率打分上界（输入百分数）"),
        _P("turnover_upper", "换手率上界%", 15, 1, 50, 1, "换手越低越稳健"),
        _P("w_vol", "波动率权重", 0.5, 0, 1, 0.05, "换手/振幅权重按 3:2 分配剩余"),
    ]

    def needs_history(self):
        return True

    def score(self, f, ctx):
        p = _params(ctx)
        vol = ctx.get("volatility", 0.03)
        turn = f.get("turnover", 5)
        amp = f.get("amplitude", 3)
        s_vol = _rank(vol, 0.01, _pv(p, "vol_upper", 6) / 100, reverse=True)
        s_turn = _rank(turn, 1, _pv(p, "turnover_upper", 15), reverse=True)
        s_amp = _rank(amp, 1, 8, reverse=True)
        w = _pv(p, "w_vol", 0.5)
        score = w * s_vol + (1 - w) * (0.6 * s_turn + 0.4 * s_amp)
        return score, {"日波动率%": round(vol * 100, 2), "换手%": round(turn, 2),
                       "振幅%": round(amp, 2), "f_波动": round(s_vol, 3)}


# ---------------- 7. 资金流选股 ----------------
class MoneyFlowStrategy(BaseSelectorStrategy):
    name = "money_flow"
    display = "资金流选股 · 主力动向"
    theory = "资金流选股 / 聪明钱效应"
    angle = "跟随主力资金净流入，选被资金追捧的股票"
    needed = "主力净流入额、成交额、涨跌幅"
    desc = "主力净流入占成交额比例越高越优先，捕捉资金驱动行情。短线为主。"
    PARAMS = [
        _P("inflow_high", "净流入评分上界%", 25, -50, 100, 5, "净流入占成交额比例满分线"),
        _P("w_inflow", "资金流权重", 0.7, 0, 1, 0.05, "当日涨幅权重自动取 1-该值"),
    ]

    def score(self, f, ctx):
        p = _params(ctx)
        inflow = f.get("main_inflow")
        amount = f.get("amount", 1) or 1
        chg = f.get("change_pct", 0)
        ratio = (inflow / amount) if inflow is not None and amount else 0
        s_ratio = _rank(ratio, -0.1, _pv(p, "inflow_high", 25) / 100)
        s_chg = _rank(chg, -3, 6)
        w = _pv(p, "w_inflow", 0.7)
        score = w * s_ratio + (1 - w) * s_chg
        return score, {"主力净流入(万)": round(inflow / 1e4, 0) if inflow is not None else "无数据",
                       "净流入占比%": round(ratio * 100, 2),
                       "f_资金": round(s_ratio, 3), "f_趋势": round(s_chg, 3)}


# ---------------- 8. 多因子综合 ----------------
class MultiFactorStrategy(BaseSelectorStrategy):
    name = "multi_factor"
    display = "多因子综合 · 均衡"
    theory = "Fama-French 多因子 / qlib Alpha158 综合打分"
    angle = "动量+估值+流动性+质量四维均衡，不偏执单一因子"
    needed = "动量、PE、成交额、换手率"
    desc = "四因子加权综合，稳健均衡。适合作为默认选股策略。"
    PARAMS = [
        _P("pe_upper", "PE评分上界", 30, 1, 200, 1, "PE越低分越高，高于此值得0分"),
        _P("turnover_low", "换手率下限%", 3, 0, 30, 0.5, "低于此值得0.5分"),
        _P("turnover_high", "换手率上限%", 15, 1, 60, 1, "高于此值得0.5分"),
        _P("w_momentum", "动量权重", 0.35, 0, 1, 0.05, "剩余权重按 5:4:4 分配给估值/流动性/质量"),
    ]

    def needs_history(self):
        return True

    def score(self, f, ctx):
        import math
        p = _params(ctx)
        mr = ctx.get("momentum_rank", 50.0)
        pe = f.get("pe") or 30
        amount = f.get("amount", 0)
        turn = f.get("turnover", 5)
        s_mom = mr / 100.0
        s_val = _rank(pe, 3, _pv(p, "pe_upper", 30), reverse=True)
        s_liq = min(1.0, math.log10(max(amount, 1)) / 11.0)
        lo, hi = _pv(p, "turnover_low", 3), _pv(p, "turnover_high", 15)
        s_qual = 1.0 if lo <= turn <= hi else 0.5
        w = _pv(p, "w_momentum", 0.35)
        rest = 1 - w
        # 剩余权重按 5:4:4 分配（与原版 0.25/0.20/0.20 同比例）
        score = w * s_mom + rest * (5 / 13 * s_val + 4 / 13 * s_liq + 4 / 13 * s_qual)
        return score, {"动量排名": round(mr, 1), "PE": round(pe, 2),
                       "成交额(亿)": round(amount / 1e8, 2), "换手%": round(turn, 2),
                       "f_动量": round(s_mom, 3), "f_估值": round(s_val, 3),
                       "f_流动性": round(s_liq, 3), "f_质量": s_qual}


# ---------------- 9. 小盘成长(Fama-French SMB) ----------------
class SmallCapStrategy(BaseSelectorStrategy):
    name = "small_cap"
    display = "小盘风格 · SMB因子"
    theory = "Fama-French 规模因子(SMB)"
    angle = "选市值较小但有流动性的公司，捕捉小盘超额收益"
    needed = "总市值、流通市值、成交额"
    desc = "中小市值 + 流动性达标，选弹性小盘股。风险高于大盘，需严格止损。"
    PARAMS = [
        _P("cap_min_yi", "市值下限(亿)", 20, 1, 500, 5, "低于该市值剔除"),
        _P("cap_max_yi", "市值上限(亿)", 500, 10, 5000, 10, "高于该市值剔除"),
        _P("w_size", "规模权重", 0.7, 0, 1, 0.05, "流动性权重自动取 1-该值"),
    ]

    def prefilter(self, f, ctx=None):
        p = _params(ctx)
        cap = f.get("market_cap")
        return (cap is not None
                and _pv(p, "cap_min_yi", 20) * 1e8 < cap < _pv(p, "cap_max_yi", 500) * 1e8)

    def score(self, f, ctx):
        import math
        p = _params(ctx)
        cap = f["market_cap"]
        amount = f.get("amount", 0)
        lo, hi = _pv(p, "cap_min_yi", 20) * 1e8, _pv(p, "cap_max_yi", 500) * 1e8
        s_size = _rank(cap, lo, hi, reverse=True)
        s_liq = min(1.0, math.log10(max(amount, 1)) / 10.0)
        w = _pv(p, "w_size", 0.7)
        score = w * s_size + (1 - w) * s_liq
        return score, {"总市值(亿)": round(cap / 1e8, 1),
                       "成交额(亿)": round(amount / 1e8, 2),
                       "f_规模": round(s_size, 3), "f_流动性": round(s_liq, 3)}


# ---------------- 10. 技术面共振 ----------------
class TechnicalStrategy(BaseSelectorStrategy):
    name = "technical"
    display = "技术面共振 · 多头排列"
    theory = "趋势跟踪 / 均线多头排列 + MACD + RSI"
    angle = "技术面多指标共振：均线多头 + MACD多头 + RSI未超买"
    needed = "历史K线(MA5/20/60、MACD、RSI)"
    desc = "MA5>MA20>MA60多头排列 + MACD柱>0 + RSI适中，选技术面强势共振股。"
    PARAMS = [
        _P("rsi_high", "RSI超买线", 70, 50, 95, 1, "高于此值视为超买并降权"),
        _P("w_ma", "均线权重", 0.4, 0, 1, 0.05, "MACD/RSI/涨幅按 3:2:1 分配剩余"),
    ]

    def needs_history(self):
        return True

    def score(self, f, ctx):
        p = _params(ctx)
        tech = ctx.get("tech", {})
        ma_bull = tech.get("ma_bull", False)
        macd_pos = tech.get("macd_hist", 0) > 0
        rsi = tech.get("rsi", 50)
        chg = f.get("change_pct", 0)
        s_ma = 1.0 if ma_bull else 0.0
        s_macd = 1.0 if macd_pos else 0.0
        high = _pv(p, "rsi_high", 70)
        s_rsi = _rank(rsi, 40, high, reverse=True) if rsi > high else 1.0
        s_chg = _rank(chg, -3, 6)
        w = _pv(p, "w_ma", 0.4)
        rest = 1 - w
        score = w * s_ma + rest * (0.5 * s_macd + 1 / 3 * s_rsi + 1 / 6 * s_chg)
        return score, {"均线多头": "是" if ma_bull else "否",
                       "MACD柱": round(tech.get("macd_hist", 0), 3),
                       "RSI": round(rsi, 1),
                       "f_趋势": round(s_ma, 2), "f_动能": round(s_macd, 2)}


# ---------------- 注册中心 ----------------
_REGISTRY = {}


def _register(cls):
    _REGISTRY[cls.name] = cls()
    return cls


for _c in (ValueStrategy, GrowthStrategy, MomentumStrategy, ReversalStrategy,
           QualityStrategy, LowVolStrategy, MoneyFlowStrategy,
           MultiFactorStrategy, SmallCapStrategy, TechnicalStrategy):
    _register(_c)


def get_strategy(name: str) -> BaseSelectorStrategy:
    if name not in _REGISTRY:
        raise KeyError(f"未知选股策略: {name}，可选: {list(_REGISTRY)}")
    return _REGISTRY[name]


def list_selector_strategies() -> list:
    return [s.info() for s in _REGISTRY.values()]
