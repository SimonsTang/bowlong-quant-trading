#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
参数自动寻优（网格搜索 + K 段折外稳健分排序）。

与常见"样本内最优参数"不同，本模块的排序主依据是 TSP 式稳健分：
    score = 0.6 × 各段收益中位数 + 0.4 × 最差段收益
并展示样本内绩效作为参考，但**不让样本内收益决定冠军**，
从机制上抑制过拟合。

流程：
  1. 读取策略声明的 ParamSpec（low/high/step）生成参数网格
  2. 每个候选参数：全样本回测（参考） + K 段独立样本外回测（排序依据）
  3. 按 objective 排序，输出 top_n 与逐组合明细
  4. 全程真实数据，不注入随机数、不生成模拟行情
"""
import itertools
import time
from dataclasses import dataclass, field
from typing import Callable, List

from .engine import StrategyEngine, EngineConfig
from .robustness import evaluate_segments
from ..strategy.base import get as get_strategy, list_strategies


@dataclass
class OptimizeConfig:
    k: int = 5
    max_combinations: int = 60      # 组合爆炸保护，超过则均匀抽样
    max_points_per_param: int = 7   # 单参数离散点数上限
    top_n: int = 10
    objective: str = "robustness"   # robustness / sharpe / total_return

    def validate(self):
        if self.k < 2:
            raise ValueError("k 至少为 2")
        if self.max_combinations < 1:
            raise ValueError("max_combinations 至少为 1")
        if self.objective not in ("robustness", "sharpe", "total_return"):
            raise ValueError("objective 仅支持 robustness/sharpe/total_return")


def build_grid(strategy: str, cfg: OptimizeConfig = None) -> List[dict]:
    """按策略 ParamSpec 生成参数网格，组合数超限时做确定性均匀抽样。"""
    cfg = cfg or OptimizeConfig()
    cfg.validate()
    specs = next((s for s in list_strategies() if s["name"] == strategy), None)
    if specs is None:
        raise KeyError(f"未注册策略: {strategy}")
    axes = []
    for p in specs["params"]:
        step = p["step"] or 1
        vals = []
        v = p["low"]
        while v <= p["high"] + 1e-9 and len(vals) < 200:
            vals.append(int(v) if float(v).is_integer() else round(v, 4))
            v += step
        if not vals:
            vals = [p["default"]]
        if len(vals) > cfg.max_points_per_param:
            idxs = [round(i * (len(vals) - 1) / (cfg.max_points_per_param - 1))
                    for i in range(cfg.max_points_per_param)]
            vals = [vals[i] for i in sorted(set(idxs))]
        axes.append((p["name"], vals))

    combos = [dict(zip([a[0] for a in axes], vals))
              for vals in itertools.product(*[a[1] for a in axes])]
    if len(combos) > cfg.max_combinations:
        idxs = [round(i * (len(combos) - 1) / (cfg.max_combinations - 1))
                for i in range(cfg.max_combinations)]
        combos = [combos[i] for i in sorted(set(idxs))]
    return combos


def optimize(bars: list, strategy: str, cfg: OptimizeConfig = None,
             engine_cfg: EngineConfig = None, code: str = "",
             progress_cb: Callable = None) -> dict:
    """参数寻优主入口。bars 必须是 enriched 后的真实K线。"""
    cfg = cfg or OptimizeConfig()
    cfg.validate()
    if not bars:
        raise ValueError("K线为空，拒绝寻优（不使用模拟数据）")
    grid = build_grid(strategy, cfg)
    ec = engine_cfg or EngineConfig()
    rows = []
    t0 = time.time()

    for i, params in enumerate(grid):
        try:
            st = get_strategy(strategy, **params)
            eng = StrategyEngine(ec)
            full = eng.run_on_bars(bars, st.signal_fn(), code, strategy)

            rb = evaluate_segments(
                bars,
                lambda p=params: get_strategy(strategy, **p).signal_fn(),
                StrategyEngine, ec, k=cfg.k)
            ins = full.summary
            rows.append({
                "params": params,
                "robustness": rb["score"],
                "oos_median": rb["median"],
                "oos_worst": rb["worst"],
                "positive_segments": rb["positive_segments"],
                "total_segments": rb["total_segments"],
                "in_sample_return": ins.get("total_return", 0.0),
                "in_sample_sharpe": ins.get("sharpe", 0.0),
                "in_sample_drawdown": ins.get("max_drawdown", 0.0),
                "trades": ins.get("trade_pairs", 0),
                "objective": {
                    "robustness": rb["score"],
                    "sharpe": ins.get("sharpe", 0.0),
                    "total_return": ins.get("total_return", 0.0),
                }[cfg.objective],
            })
        except Exception as e:
            rows.append({"params": params, "error": f"{type(e).__name__}: {e}",
                         "objective": -999.0})
        if progress_cb:
            progress_cb(i + 1, len(grid), f"参数寻优 {i + 1}/{len(grid)}")

    rows.sort(key=lambda x: x["objective"], reverse=True)
    best = rows[0] if rows else {}
    return {
        "strategy": strategy,
        "objective": cfg.objective,
        "k_folds": cfg.k,
        "grid_size": len(grid),
        "elapsed_sec": round(time.time() - t0, 2),
        "best": best,
        "top": rows[:cfg.top_n],
        "all": rows,
        "note": "排序主依据为K段折外稳健分(0.6中位+0.4最差)，样本内绩效仅作参考",
    }
