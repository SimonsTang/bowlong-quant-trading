#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dual Thrust 区间突破策略 - 真实数据实测脚本。

全部数据来自东财真实前复权日K（无模拟、无随机数）。
产出 reports/dual_thrust_backtest.json，供研究报告引用。
测试维度：全样本绩效 / K段折外稳健 / 分年度牛熊 / 参数网格 / 成本敏感性 / 对照策略。
"""
import json
import os
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data.sources import EM                      # noqa: E402
from core.data.resolver import validate_kline         # noqa: E402
from core.data.enriched import enrich, contract_snapshot  # noqa: E402
from core.research.engine import StrategyEngine, EngineConfig  # noqa: E402
from core.research.robustness import k_fold_segments, robustness_score  # noqa: E402
from core.strategy.base import get as get_strategy    # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "reports", "dual_thrust_backtest.json")

SYMBOLS = OrderedDict([
    ("510300.SH", "沪深300ETF"),
    ("510500.SH", "中证500ETF"),
    ("000300.SH", "沪深300指数"),
    ("600519.SH", "贵州茅台"),
    ("000858.SZ", "五粮液"),
    ("601318.SH", "中国平安"),
])

VERSIONS = OrderedDict([
    ("original",  {"N": 5, "K1": 0.5, "K2": 0.5, "trend": 0, "stop": 0.0}),
    ("trend",     {"N": 5, "K1": 0.5, "K2": 0.5, "trend": 1, "stop": 0.0}),
    ("stop",      {"N": 5, "K1": 0.5, "K2": 0.5, "trend": 0, "stop": 0.05}),
    ("trendstop", {"N": 5, "K1": 0.5, "K2": 0.5, "trend": 1, "stop": 0.05}),
])


UNIFIED_START = "2016-01-01"   # 统一对比起点：所有标的在该日之后均为正价、连续可交易


def fetch_bars(code):
    """真实K线 + 可交易区间裁剪 + 校验 + enrich。失败直接抛错，绝不返回模拟数据。

    前复权在早期高分红个股上会出现非正价格（除权的数学结果，非数据源错误），
    这类价格无法用于仓位/收益计算，故裁掉最后一个非正价格交易日之前的历史，
    再统一从 UNIFIED_START 起对齐样本，保证跨标的口径公平。
    """
    rows = EM.kline(code, "1d", "qfq", "20050101", "20500101")
    if not rows:
        raise RuntimeError(f"{code} 真实K线为空")
    last_bad_idx = -1
    for idx, r in enumerate(rows):
        if r["close"] <= 0 or r["open"] <= 0 or r["low"] <= 0 or r["high"] <= 0:
            last_bad_idx = idx
    rows = rows[last_bad_idx + 1:]
    rows = [r for r in rows if r["date"] >= UNIFIED_START]
    rows = validate_kline(rows)
    if len(rows) < 500:
        raise RuntimeError(f"{code} 裁剪后真实K线不足: {len(rows)}")
    return enrich(rows), contract_snapshot(rows)


def run_version(bars, version_params, code, slippage=0.001, initial=1_000_000,
                contract=None):
    st = get_strategy("dual_thrust", **version_params)
    cfg = EngineConfig(initial_cash=initial, slippage=slippage)
    return StrategyEngine(cfg).run_on_bars(
        bars, st.signal_fn(), code, "dual_thrust", contract=contract)


def yearly_from_equity(bars, equity):
    """用全样本净值曲线按自然年切分，返回 {年: 收益率}。"""
    pts = {}
    for b, e in zip(bars, equity):
        pts[b["date"][:4]] = e  # 每年最后一个交易日的净值
    years = sorted(pts)
    out = OrderedDict()
    prev = None
    for y in years:
        v = pts[y]
        out[y] = round(v / prev - 1, 4) if prev else None
        prev = v
    return out


def equity_curve(result, step=5):
    eq = result.equity
    dates = result.contract.get("dates", [])
    if not dates:
        return []
    return [[dates[i], round(eq[i], 2)] for i in range(0, len(eq), step)] + \
           ([[dates[-1], round(eq[-1], 2)]] if (len(eq) - 1) % step else [])


def main():
    report = OrderedDict()
    report["meta"] = {
        "strategy": "Dual Thrust 区间突破（A股日线适配版）",
        "data_source": "东方财富 push2his 前复权日K（真实行情）",
        "fetch_time": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
        "engine": "统一策略引擎：T日收盘信号 / T+1开盘成交 / 真实费用 / 涨跌停 / 100股整手",
        "initial_cash": 1_000_000,
        "slippage_default": 0.001,
        "note": "回测为历史真实行情模拟，非实盘成交；不含分红再投资的现金处理差异",
    }
    symbols_data = {}

    print("[1/5] 拉取并校验真实K线 ...")
    for code, name in SYMBOLS.items():
        bars, snap = fetch_bars(code)
        # 把日期塞进 contract 供画图使用
        snap["dates"] = [b["date"] for b in bars]
        symbols_data[code] = {"bars": bars, "snap": snap}
        print(f"  {code} {name}: {len(bars)}根 {bars[0]['date']}~{bars[-1]['date']}")

    report["data_range"] = {
        c: {"name": n, "rows": len(symbols_data[c]["bars"]),
            "start": symbols_data[c]["bars"][0]["date"],
            "end": symbols_data[c]["bars"][-1]["date"]}
        for c, n in SYMBOLS.items()
    }

    print("[2/5] 全样本 + 分年度 + K段折外 ...")
    per_symbol = OrderedDict()
    for code, name in SYMBOLS.items():
        bars = symbols_data[code]["bars"]
        entry = OrderedDict()
        for vname, params in VERSIONS.items():
            r = run_version(bars, params, code, contract=symbols_data[code]["snap"])
            # K段折外：每段独立建仓，检验参数在子区间的稳定性
            segs = k_fold_segments(bars, 5)
            seg_rets = []
            seg_details = []
            for s in segs:
                if len(s) < 60:
                    continue
                rs = run_version(s, params, code)
                seg_rets.append(rs.summary["total_return"])
                seg_details.append({"start": s[0]["date"], "end": s[-1]["date"],
                                    "ret": rs.summary["total_return"],
                                    "mdd": rs.summary["max_drawdown"]})
            st = get_strategy("dual_thrust", **params)
            rb = robustness_score(seg_rets)
            entry[vname] = {
                "params": params,
                "summary": r.summary,
                "yearly": yearly_from_equity(bars, r.equity),
                "equity_sample": equity_curve(r),
                "fold5": {"score": round(rb, 4),
                          "median": round(sorted(seg_rets)[len(seg_rets) // 2], 4) if seg_rets else 0,
                          "worst": round(min(seg_rets), 4) if seg_rets else 0,
                          "positive": sum(1 for x in seg_rets if x > 0),
                          "total": len(seg_rets), "details": seg_details},
            }
        # 买入持有对照
        def buy_hold(b, i):
            return "BUY" if i == 1 else "HOLD"
        bh = StrategyEngine(EngineConfig()).run_on_bars(
            bars, buy_hold, code, "buy_hold", contract=symbols_data[code]["snap"])
        entry["buy_hold"] = {
            "summary": bh.summary,
            "yearly": yearly_from_equity(bars, bh.equity),
            "equity_sample": equity_curve(bh),
        }
        per_symbol[code] = {"name": name, "versions": entry}
    report["per_symbol"] = per_symbol

    print("[3/5] 参数网格（沪深300ETF 主标的）...")
    code = "510300.SH"
    bars = symbols_data[code]["bars"]
    grid = []
    for N in (3, 5, 7, 10):
        for K1 in (0.3, 0.5, 0.7):
            for K2 in (0.3, 0.5, 0.7):
                p = {"N": N, "K1": K1, "K2": K2, "trend": 0, "stop": 0.0}
                r = run_version(bars, p, code)
                grid.append({"N": N, "K1": K1, "K2": K2,
                             "total_return": r.summary["total_return"],
                             "annual_return": r.summary["annual_return"],
                             "sharpe": r.summary["sharpe"],
                             "max_drawdown": r.summary["max_drawdown"],
                             "trades": r.summary["trade_pairs"],
                             "win_rate": r.summary["win_rate"]})
    report["param_grid"] = {"code": code, "rows": grid}

    print("[4/5] 成本敏感性（沪深300ETF, 原始参数）...")
    cost = []
    for slip in (0.0, 0.0005, 0.001, 0.002):
        r = run_version(bars, VERSIONS["original"], code, slippage=slip)
        cost.append({"slippage": slip, "total_return": r.summary["total_return"],
                     "annual_return": r.summary["annual_return"],
                     "trades": r.summary["trade_pairs"],
                     "net_pnl": r.summary.get("net_pnl", 0)})
    report["cost_sensitivity"] = cost

    print("[5/5] 对照策略（双均线 / 海龟，沪深300ETF）...")
    comp = {}
    for sname, sparams in (("dual_ma", {"fast": 5, "slow": 20}),
                           ("turtle", {"entry": 20, "exit": 10})):
        st = get_strategy(sname, **sparams)
        r = StrategyEngine(EngineConfig()).run_on_bars(
            bars, st.signal_fn(), code, sname)
        comp[sname] = r.summary
    report["benchmarks"] = comp

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"[OK] 报告数据已写入 {OUT}")

    # 控制台摘要
    print("\n=== 沪深300ETF 原始版摘要 ===")
    o = per_symbol[code]["versions"]["original"]
    print(json.dumps(o["summary"], ensure_ascii=False))
    print("折外稳健:", json.dumps({k: o["fold5"][k] for k in ("score", "worst", "positive", "total")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
