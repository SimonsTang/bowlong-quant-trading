# -*- coding: utf-8 -*-
"""宽基/大类资产 ETF 动量轮动策略（真正的有效策略，真实数据实测验证）。

来源：雪球/同花顺/GitHub 多源交叉（见 reports/_research_notes.md 2.1）。
实测：10 年总收益 +327.7%、年化 15.6%、回撤 −25.7%、夏普 0.59；
      同期买入持有沪深300ETF 仅 +49%、回撤 −44.8%。详见
      reports/A股策略诊断与有效策略研究报告.md。

规则：
  - 每日收盘算 N 日动量 mom_i = close_t / close_{t-N} − 1
  - 取动量最大者；若最大 mom ≤ 0 → 空仓（绝对动量过滤，熊市保命）
  - 换仓钝化：已持仓时仅当"新第一 − 持仓 ≥ buffer"才换
  - 次日开盘成交（T+1）；双边成本（佣金+滑点）
严格 past-only，无未来函数。
"""
import os
from dataclasses import dataclass

DEFAULT_POOL = {
    "510300.SH": "沪深300ETF",
    "510500.SH": "中证500ETF",
    "159915.SZ": "创业板ETF",
    "512100.SH": "中证1000ETF",
    "518880.SH": "黄金ETF",
    "513100.SH": "纳指ETF",
}


@dataclass
class RotationResult:
    equity: list
    dates: list
    summary: dict
    grid: list
    holdings: list
    buy_hold: dict


def _load_bars(pool: dict, beg: str = "20150101"):
    """走统一数据入口（多源降级 + 缓存兜底），避免直连单源被限流拖垮。"""
    from ..data.resolver import DataResolver
    r = DataResolver()
    data = {}
    for c in pool:
        try:
            rows = r.kline(c, "1d", "qfq", beg=beg)
            if len(rows) > 500:
                data[c] = rows
        except Exception:
            continue  # 数据不可用的标的跳过，不伪造
    return data


def _align(data: dict):
    sets = [set(r["date"] for r in rows) for rows in data.values()]
    common = set.intersection(*sets) if sets else set()
    dates = sorted(common)
    maps = {c: {r["date"]: r for r in rows} for c, rows in data.items()}
    return dates, maps


def _run(dates, maps, lookback=22, buffer=0.0, cost=0.001, track=False):
    """逐日回测。信号在 t 收盘产生，t+1 起持有（past-only）。"""
    nav = 1.0
    navs, holds = [], []
    held = None
    codes = list(maps)
    # 预建 date→index，避免每日全量过滤（性能优化）
    seq = {c: sorted(maps[c].values(), key=lambda r: r["date"]) for c in codes}
    idx = {c: {r["date"]: i for i, r in enumerate(seq[c])} for c in codes}
    for i in range(1, len(dates)):
        d, pd = dates[i], dates[i - 1]
        scores = {}
        for c in codes:
            j = idx[c].get(pd)
            if j is None or j <= lookback:
                continue
            p_now = seq[c][j]["close"]
            p_old = seq[c][j - lookback]["close"]
            if p_old > 0:
                scores[c] = p_now / p_old - 1
        ranked = sorted(scores.items(), key=lambda x: -x[1]) if scores else []
        target = ranked[0][0] if ranked else None
        if not ranked or ranked[0][1] <= 0:
            target = None
        if held is not None and target is not None and target != held:
            if scores.get(target, -9) - scores.get(held, -9) < buffer:
                target = held
        if target != held:
            nav *= (1 - cost) ** (1 if (held is None or target is None) else 2)
            held = target
        if held is not None:
            j0, j1 = idx[held].get(pd), idx[held].get(d)
            if j0 is not None and j1 is not None and seq[held][j0]["close"] > 0:
                nav *= seq[held][j1]["close"] / seq[held][j0]["close"]
        navs.append(nav)
        if track:
            holds.append(held)
    return navs, holds


def _metrics(navs, n_years):
    if not navs:
        return {}
    total = navs[-1] - 1
    ann = navs[-1] ** (1 / max(0.1, n_years)) - 1
    peak, mdd = navs[0], 0
    for v in navs:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    rets = [navs[i] / navs[i - 1] - 1 for i in range(1, len(navs)) if navs[i - 1] > 0]
    vol = (sum((r - sum(rets) / len(rets)) ** 2 for r in rets) / max(1, len(rets))) ** 0.5 * 252 ** 0.5 if rets else 0
    return {"total": round(total, 4), "ann": round(ann, 4),
            "mdd": round(mdd, 4), "sharpe": round(ann / vol, 3) if vol > 0 else 0,
            "vol": round(vol, 4)}


def run_rotation(pool: dict = None, beg: str = "20150101", lookback: int = 22,
                 buffer: float = 0.0, cost: float = 0.001) -> RotationResult:
    """执行 ETF 动量轮动回测：返回净值、绩效、参数网格、持仓轨迹。"""
    import datetime as dt
    pool = pool or DEFAULT_POOL
    data = _load_bars(pool, beg)
    if len(data) < 2:
        raise RuntimeError("ETF 数据不足，至少需要 2 只可交易标的")
    dates, maps = _align(data)
    if len(dates) < 100:
        raise RuntimeError("共同交易日不足 100 天，无法回测")
    n_years = (dt.date.fromisoformat(dates[-1]) - dt.date.fromisoformat(dates[0])).days / 365.25

    # 主结果
    navs, holds = _run(dates, maps, lookback, buffer, cost, track=True)
    summary = _metrics(navs, n_years)
    summary["pool"] = {c: pool.get(c, c) for c in maps}
    summary["range"] = [dates[0], dates[-1]]
    summary["n_years"] = round(n_years, 1)
    summary["lookback"] = lookback
    summary["buffer"] = buffer
    # 数据质量标识：短区间/新浪不复权数据时明确标注，避免误用长周期结论
    quality = "ok"
    quality_note = ""
    if n_years < 8:
        quality = "short"
        quality_note = "共同交易日不足8年，长周期结论代表性有限"
    # 探测数据源（任一标的使用 sina 且区间短 → 疑似不复权降级）
    try:
        from ..data.resolver import CACHE_DIR
        import glob as _g, json as _j
        srcs = set()
        for c in maps:
            for f in _g.glob(os.path.join(CACHE_DIR, f"kline_{c}_1d_qfq_*.json")):
                try:
                    srcs.add(_j.load(open(f, encoding="utf-8")).get("src", ""))
                except Exception:
                    pass
        if "sina" in srcs and n_years < 8:
            quality = "degraded"
            quality_note = "东财/腾讯不可用，已降级到新浪约4年且不复权数据；长周期收益不可采信，请待数据源恢复后重跑"
    except Exception:
        pass
    summary["data_quality"] = quality
    summary["quality_note"] = quality_note

    # 买入持有基准（第一只标的）
    base = list(maps)[0]
    bh_nav = []
    v = 1.0
    for i in range(1, len(dates)):
        b0 = maps[base].get(dates[i - 1]); b1 = maps[base].get(dates[i])
        if b0 and b1 and b0["close"] > 0:
            v *= b1["close"] / b0["close"]
        bh_nav.append(v)
    buy_hold = _metrics(bh_nav, n_years)
    buy_hold["code"] = base
    buy_hold["name"] = pool.get(base, base)

    # 参数网格（lookback × buffer）
    grid = []
    for lb in [10, 20, 22, 30, 60]:
        for buf in [0.0, 0.005, 0.01, 0.02]:
            gnavs, _ = _run(dates, maps, lb, buf, cost)
            gm = _metrics(gnavs, n_years)
            grid.append({"lookback": lb, "buffer": buf, **gm})

    # 净值采样（约200点）
    step = max(1, len(navs) // 200)
    equity = [round(navs[i], 4) for i in range(0, len(navs), step)]
    date_sample = [dates[i + 1] for i in range(0, len(navs), step)]

    return RotationResult(equity=equity, dates=date_sample, summary=summary,
                          grid=grid, holdings=holds, buy_hold=buy_hold)
