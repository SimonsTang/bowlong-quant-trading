#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K 段折外稳健性检验（直接借鉴 TSP 的核心诚实机制）。

TSP 做法：参数不选样本内最优，而是把时间序列切成 K 段，
每段独立做样本外回测，稳健分 = 0.6×中位数 + 0.4×最差段，
逼你选"全周期都还行"的参数，而不是"某一段爆赚其余亏死"的过拟合参数。

本模块实现：
  - walk_forward: 滚动折外（训练窗→测试窗推进）
  - k_fold_segments: K 段等分样本外
  - robustness_score: 0.6*中位 + 0.4*最差
"""
from dataclasses import dataclass


@dataclass
class SegmentResult:
    segment: int
    total_return: float
    max_drawdown: float
    sharpe: float


def k_fold_segments(bars: list, k: int = 5) -> list:
    """把 K 线等分 K 段，返回每段切片。"""
    if k < 2:
        raise ValueError("K 段折外要求 k>=2")
    n = len(bars)
    size = n // k
    return [bars[i * size:(i + 1) * size] if i < k - 1 else bars[i * size:]
            for i in range(k)]


def robustness_score(returns: list) -> float:
    """稳健分 = 0.6×中位数 + 0.4×最差值。
    对样本外各段收益打分，惩罚最差段，抑制过拟合。"""
    if not returns:
        return 0.0
    s = sorted(returns)
    mid = s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2
    worst = s[0]
    return 0.6 * mid + 0.4 * worst


def evaluate_segments(bars: list, signal_fn_factory, engine_cls, cfg,
                      k: int = 5, progress_cb=None) -> dict:
    """对 K 段分别做样本外回测，返回稳健分与逐段明细。

    signal_fn_factory: 无参函数，返回该段可用的 signal_fn（同一策略逻辑）
    """
    segments = k_fold_segments(bars, k)
    results: list = []
    for idx, seg in enumerate(segments):
        if len(seg) < 30:
            continue
        eng = engine_cls(cfg, progress_cb=None)
        r = eng.run_on_bars(seg, signal_fn_factory(), code="", strategy="segment")
        results.append(SegmentResult(
            segment=idx + 1,
            total_return=r.summary.get("total_return", 0),
            max_drawdown=r.summary.get("max_drawdown", 0),
            sharpe=r.summary.get("sharpe", 0),
        ))
        if progress_cb:
            progress_cb(idx + 1, len(segments), f"折外检验 第{idx+1}/{len(segments)}段")

    rets = [r.total_return for r in results]
    return {
        "score": round(robustness_score(rets), 4),
        "median": round(sorted(rets)[len(rets) // 2], 4) if rets else 0.0,
        "worst": round(min(rets), 4) if rets else 0.0,
        "positive_segments": sum(1 for r in rets if r > 0),
        "total_segments": len(results),
        "details": [r.__dict__ for r in results],
    }
