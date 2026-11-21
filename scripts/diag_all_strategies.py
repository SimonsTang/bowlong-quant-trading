# -*- coding: utf-8 -*-
"""诊断全部交易策略：实例化 + 真实数据回测 + 汇总收益矩阵。
复现用户观察"13个策略除2个打不开外全亏"，找出根因。
"""
import sys
import os
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.strategy.base import get as get_strategy, list_strategies
from core.data.resolver import DataResolver
from core.data.enriched import enrich, contract_snapshot
from core.research.engine import StrategyEngine, EngineConfig

R = DataResolver()

# 标的池：宽基ETF(可代表A股主要beta) + 两个个股
SYMBOLS = ["510300.SH", "000300.SH", "600519.SH", "000858.SZ"]
BEG = "20180101"

print("=" * 90)
print("全策略诊断：实例化 + 真实回测（T+1、真实费用、前复权）")
print("=" * 90)

strategies = [s["name"] for s in list_strategies()]
print("策略数:", len(strategies), strategies)
print()

# 1) 实例化测试
print("--- 实例化测试（默认参数）---")
instantiable = []
for name in strategies:
    try:
        st = get_strategy(name)
        sig = st.signal_fn()
        instantiable.append(name)
        print(f"  [OK]   {name:14s} params={st.params() if hasattr(st,'params') else ''}")
    except Exception as e:
        print(f"  [FAIL] {name:14s} {type(e).__name__}: {str(e)[:100]}")
print()

# 2) 数据准备
bars_by_code = {}
for code in SYMBOLS:
    try:
        rows = R.kline(code, "1d", "qfq", beg=BEG)
        bars_by_code[code] = (enrich(rows), contract_snapshot(rows))
        print(f"数据 {code}: {len(rows)} 根, {rows[0]['date']} ~ {rows[-1]['date']}")
    except Exception as e:
        print(f"数据 {code} FAIL: {e}")
print()

# 3) 回测矩阵
print("--- 回测收益矩阵（总收益率%）---")
print(f"{'策略':16s}", "".join(f"{c:>14s}" for c in SYMBOLS), "  平均")
results = {}
for name in strategies:
    if name not in instantiable:
        continue
    rets = []
    for code in SYMBOLS:
        if code not in bars_by_code:
            rets.append(None)
            continue
        try:
            bars, contract = bars_by_code[code]
            st = get_strategy(name)
            eng = StrategyEngine(EngineConfig())
            r = eng.run_on_bars(bars, st.signal_fn(), code, name, contract)
            tr = r.summary["total_return"]
            rets.append(tr)
            results[(name, code)] = r
        except Exception as e:
            rets.append(None)
            results[(name, code)] = {"error": f"{type(e).__name__}: {e}"}
    avg = sum(x for x in rets if x is not None) / max(1, len([x for x in rets if x is not None]))
    cells = "".join((f"{x*100:>13.1f}%" if x is not None else f"{'ERR':>14s}") for x in rets)
    print(f"{name:16s}{cells}{avg*100:>8.1f}%")

# 4) 买入持有基准
print()
print("--- 买入持有基准（总收益率%）---")
for code in SYMBOLS:
    if code not in bars_by_code:
        continue
    bars, contract = bars_by_code[code]
    def bh(b, i):
        return "BUY" if i == 1 else "HOLD"
    r = StrategyEngine(EngineConfig()).run_on_bars(bars, bh, code, "buy_hold", contract)
    print(f"  {code}: {r.summary['total_return']*100:.1f}%  交易数 {r.summary.get('trade_pairs',0)}")

# 5) 统计
print()
print("--- 统计 ---")
valid = [(k, v) for k, v in results.items() if isinstance(v, dict) and "error" in v]
if valid:
    print("回测报错:", len(valid))
    for k, v in valid[:20]:
        print("  ", k, v["error"][:100])

# 保存JSON
import json
out = {}
for (name, code), r in results.items():
    if isinstance(r, dict):
        out[f"{name}|{code}"] = r
    else:
        out[f"{name}|{code}"] = {"summary": r.summary, "n_trades": len(r.trades)}
with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "reports", "diag_all_strategies.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("已保存 reports/diag_all_strategies.json")
