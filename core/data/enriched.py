#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enriched 统一数据口径（核心借鉴 TSP 的第一大机制）。

TSP 做法：只持久化约15列基础数据，68列指标全部现算，
策略扫描/回测/监控/复盘共享同一份 enriched 结果，杜绝口径漂移。

本模块复刻该思路：
  - 基础数据 = DataResolver 拉回的真实K线（date/open/high/low/close/volume/amount）
  - enriched() 现算全部指标，返回带指标列的 bar 列表
  - 任何策略、回测、实盘信号都必须经过 enriched()，不允许各自算指标
  - 带契约版本 CONTRACT_VERSION，口径变更必须升版（借鉴 TSP 契约快照）
"""
import hashlib
import json

from ..research import indicators as ind

CONTRACT_VERSION = "enriched-v1.0.0"

# 基础列（持久化层）——借鉴 TSP 的"少存基础、多现算"
BASE_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount"]

# 现算指标列（按需计算，不落库）
DERIVED_COLUMNS = [
    "ma5", "ma10", "ma20", "ma60", "ema12", "ema26",
    "dif", "dea", "macd_hist", "rsi14",
    "boll_mid", "boll_up", "boll_low",
    "k", "d", "j", "atr14",
    "donchian_up20", "donchian_low20",
    "ret1", "ret5", "ret20", "rps20",
]


def enrich(bars: list) -> list:
    """把基础K线 enrich 为统一口径。输入必须按时间正序。
    返回新的 bar 字典列表（不修改入参），每根 bar 附带全部指标列。"""
    if not bars:
        return []
    closes = [b["close"] for b in bars]
    out = [dict(b) for b in bars]

    for col, vals in zip(
        ["ma5", "ma10", "ma20", "ma60"],
        [ind.sma(closes, w) for w in (5, 10, 20, 60)],
    ):
        for i, v in enumerate(vals):
            out[i][col] = v

    ema12, ema26 = ind.ema(closes, 12), ind.ema(closes, 26)
    dif, dea, hist = ind.macd(closes)
    rsi = ind.rsi(closes, 14)
    bm, bu, bl = ind.bollinger(closes, 20)
    k, d, j = ind.kdj(bars, 9)
    atr = ind.atr(bars, 14)
    du, dl = ind.donchian(bars, 20)
    ret1 = ind.pct_change(closes, 1)
    ret5 = ind.pct_change(closes, 5)
    ret20 = ind.pct_change(closes, 20)
    rps = ind.rolling_return_rank(closes, 20)

    series = {
        "ema12": ema12, "ema26": ema26, "dif": dif, "dea": dea,
        "macd_hist": hist, "rsi14": rsi, "boll_mid": bm, "boll_up": bu,
        "boll_low": bl, "k": k, "d": d, "j": j, "atr14": atr,
        "donchian_up20": du, "donchian_low20": dl,
        "ret1": ret1, "ret5": ret5, "ret20": ret20, "rps20": rps,
    }
    for i in range(len(out)):
        for col, vals in series.items():
            out[i][col] = vals[i]
    return out


def contract_snapshot(bars: list) -> dict:
    """数据契约快照：记录口径版本+基础数据哈希，供回测结果可追溯。
    借鉴 TSP 的契约快照+CI守护，解决'跨版本结果不一致'问题。"""
    basis = [{c: b.get(c) for c in BASE_COLUMNS} for b in bars]
    payload = json.dumps(basis, sort_keys=True, ensure_ascii=False, default=str)
    return {
        "contract": CONTRACT_VERSION,
        "rows": len(bars),
        "basis_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16],
        "derived_columns": DERIVED_COLUMNS,
    }
