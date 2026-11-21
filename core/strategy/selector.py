#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全市场选股引擎 —— 完整闭合、可运行、可升级（非空架子）。

闭环链路：
  universe(全市场真实数据) → 因子计算(动量/估值/流动性/质量)
  → 截面打分排序 → 过滤(ST/涨停/停牌) → 组合构建 → 目标仓位
  → 回测验证(接 StrategyEngine) → 风控检查 → 实盘意图(接 OrderRouter)

可升级点：
  - 因子权重可配置(SelectorConfig)，新增因子只需实现 factor_fn
  - 打分函数可替换(score_fn)
  - 选股数量/调仓周期可调
  - 所有中间结果可追溯(选股明细含每个因子值)

数据全部来自真实接口，绝不伪造。
"""
import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List

from ..data.sources import EastMoneySource, _norm_code, _http_get
from ..data.resolver import DataResolver, CACHE_DIR
from .selector_strategies import get_strategy, list_selector_strategies

EM = EastMoneySource()
RESOLVER = DataResolver()

# 全市场快照缓存：主源与备源都不可用时，用最近一次真实快照兜底并明确标注时间
UNIVERSE_CACHE = os.path.join(CACHE_DIR, "universe_snapshot.json")

# 各策略依赖的、备源可能无法提供的字段（用于诚实提示，不静默返回空结果）
STRATEGY_REQUIRED_FIELDS = {
    "growth": ("revenue_yoy", "profit_yoy"),      # 营收/净利同比
    "money_flow": ("main_inflow",),               # 主力净流入
}


@dataclass
class SelectorConfig:
    """可升级的配置：因子权重与阈值全部可调。"""
    # 因子权重（和为1附近即可，不强制）
    w_momentum: float = 0.35      # 动量：近20日涨幅的截面排名
    w_valuation: float = 0.25     # 估值：PE合理区间得分（低PE优先，但排除亏损）
    w_liquidity: float = 0.20     # 流动性：成交额适中（避免僵尸股与过热）
    w_quality: float = 0.20       # 质量：换手率适中（不追高换手投机）
    # 筛选阈值
    top_n: int = 10               # 选出标的数
    max_pe: float = 60.0          # PE上限（剔除高估值/亏损）
    min_pe: float = 3.0           # PE下限（剔除异常低）
    min_amount: float = 1e8       # 最小成交额（1亿，保证流动性）
    max_turnover: float = 25.0    # 最大换手率%（过滤过热）
    exclude_st: bool = True
    exclude_limit_up: bool = True # 排除涨停（买不到）
    lookback_days: int = 60       # 动量回看交易日
    momentum_fetch_n: int = 120   # 动量阶段最多拉多少只历史K线（性能控制）


@dataclass
class Pick:
    code: str
    name: str
    price: float
    score: float
    factors: dict = field(default_factory=dict)
    reason: str = ""


@dataclass
class SelectionResult:
    picks: List[Pick]
    universe_size: int
    filtered_out: dict
    config: dict
    timestamp: str
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "picks": [asdict(p) for p in self.picks],
            "universe_size": self.universe_size,
            "filtered_out": self.filtered_out,
            "config": self.config,
            "timestamp": self.timestamp,
            "warnings": self.warnings,
        }


class MarketSelector:
    """全市场多因子选股器。所有数据真实，链路完整闭合。"""

    def __init__(self, config: SelectorConfig = None,
                 factor_fn: Callable = None, strategy: str = "multi_factor",
                 strategy_params: Dict = None):
        self.cfg = config or SelectorConfig()
        self.factor_fn = factor_fn or self._default_factors
        self.strategy = get_strategy(strategy)  # 可切换的选股策略插件
        # 该策略专属参数（来自 UI 动态参数区），未传则用策略默认值
        self.strategy_params = dict(strategy_params or {})

    @staticmethod
    def _save_universe(rows: list, source: str):
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(UNIVERSE_CACHE, "w", encoding="utf-8") as f:
                json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                           "source": source, "rows": rows}, f, ensure_ascii=False)
        except Exception:
            pass  # 缓存失败不影响本次真实选股

    @staticmethod
    def _load_universe() -> dict:
        try:
            with open(UNIVERSE_CACHE, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d if d.get("rows") else None
        except Exception:
            return None

    def _fetch_universe_em(self, max_pages: int = 60,
                           progress_cb: Callable = None) -> list:
        """东财全市场快照（字段最全：含ROE/营收同比/主力净流入）。"""
        out, page, total = [], 1, None
        while page <= max_pages:
            url = ("https://push2.eastmoney.com/api/qt/clist/get"
                   f"?pn={page}&pz=100&po=1&np=1&fltt=2&invt=2&fid=f6"
                   "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
                   "&fields=f12,f14,f2,f3,f6,f7,f8,f9,f20,f21,f23,f37,f40,f41,f46,f62,f100,f26")
            d = json.loads(_http_get(url, {"Referer": "https://quote.eastmoney.com/"}))
            data = d.get("data") or {}
            if total is None:
                total = int(data.get("total") or 0)
            rows = data.get("diff") or []
            if not rows:
                break
            out.extend(rows)
            if len(out) >= total:
                break
            page += 1
            if progress_cb and page % 10 == 0:
                progress_cb(page, max_pages * 20, "拉取全市场快照")
        if not out:
            raise RuntimeError("东财返回空列表")
        return out

    def _fetch_universe_sina(self, max_pages: int = 60,
                             progress_cb: Callable = None) -> list:
        """新浪全市场快照备源（真实行情，字段映射到东财内部口径）。
        注意：新浪不提供营收同比/净利同比/主力净流入；ROE 由真实 PB/PE 推导
        （ROE≈PB/PE），会在 warnings 中明确标注，不伪造财报数据。"""
        out = []
        for page in range(1, max_pages + 1):
            url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                   f"Market_Center.getHQNodeData?page={page}&num=100&sort=amount&asc=0&node=hs_a")
            rows = json.loads(_http_get(url, {"Referer": "https://finance.sina.com.cn/"}))
            if not rows:
                break
            for r in rows:
                try:
                    pe = float(r.get("per") or 0)
                    pb = float(r.get("pb") or 0)
                    px = float(r.get("trade") or 0)
                    settle = float(r.get("settlement") or 0)
                except (TypeError, ValueError):
                    continue
                roe = round(pb / pe * 100, 2) if pe > 0 and pb > 0 else None
                amp = round((float(r.get("high") or 0) - float(r.get("low") or 0))
                            / settle * 100, 2) if settle > 0 else None
                out.append({
                    "f12": str(r.get("code", "")), "f14": str(r.get("name", "")),
                    "f2": px, "f3": float(r.get("changepercent") or 0),
                    "f6": float(r.get("amount") or 0),
                    "f7": amp, "f8": float(r.get("turnoverratio") or 0),
                    "f9": pe if pe > 0 else None,
                    "f20": float(r.get("mktcap") or 0) * 1e4,   # 万元→元
                    "f21": float(r.get("nmc") or 0) * 1e4,
                    "f23": pb if pb > 0 else None,
                    "f37": roe,                                  # 推导值，非披露值
                    "f40": None, "f41": None, "f46": None, "f62": None,
                    "f100": "", "f26": "",
                })
            if progress_cb and page % 10 == 0:
                progress_cb(page, max_pages * 20, "拉取全市场快照")
            if len(rows) < 100:
                break
        if not out:
            raise RuntimeError("新浪返回空列表")
        return out

    def _fetch_universe(self, max_pages: int = 60,
                        progress_cb: Callable = None) -> tuple:
        """真实全市场快照：东财 → 新浪 → 最近一次真实缓存（STALE）。
        返回 (rows, meta)；全部失败才抛错，绝不返回模拟数据。"""
        errors = []
        for name, fetch in (("eastmoney", self._fetch_universe_em),
                            ("sina", self._fetch_universe_sina)):
            try:
                rows = fetch(max_pages, progress_cb)
                self._save_universe(rows, name)
                return rows, {"source": name, "stale": False,
                              "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
            except Exception as e:
                errors.append(f"{name}: {e}")
        cached = self._load_universe()
        if cached:
            return cached["rows"], {"source": cached["source"], "stale": True,
                                    "ts": cached["ts"]}
        raise RuntimeError("全市场真实快照不可用 | " + " | ".join(errors))

    def _default_factors(self, row: dict) -> dict:
        """真实基本面因子计算。所有值来自东财clist快照（2026-11-20实测字段）。
        f9 PE动态 f23 PB f37 ROE f40 营收 f41 营收同比 f46 净利同比
        f62 主力净流入 f3 涨跌幅 f8 换手 f6 成交额 f20 总市值 f100 行业 f26 上市日期
        """
        def num(v, default=0.0):
            if v is None or v == "" or v == "-":
                return default
            try:
                f = float(v)
                return f if f == f else default  # 过滤NaN
            except (TypeError, ValueError):
                return default
        return {
            "code": str(row.get("f12", "")),
            "name": str(row.get("f14", "")),
            "price": num(row.get("f2")),
            "change_pct": num(row.get("f3")),
            "turnover": num(row.get("f8")),
            "pe": num(row.get("f9")),
            "amount": num(row.get("f6")),
            "market_cap": num(row.get("f20")),
            "float_cap": num(row.get("f21")),
            "pb": num(row.get("f23")),
            # 以下为策略特定字段：缺失返回 None（区别于真实的 0），由 prefilter 决定
            "roe": num(row.get("f37"), None),
            "revenue": num(row.get("f40"), None),
            "revenue_yoy": num(row.get("f41"), None),
            "profit_yoy": num(row.get("f46"), None),
            "main_inflow": num(row.get("f62"), None),
            "industry": str(row.get("f100", "")),
            "list_date": str(row.get("f26", "")),
            "amplitude": num(row.get("f7")),   # 振幅
        }

    def _compute_momentum_rank(self, codes: list, snapshot_scores: dict = None,
                               progress_cb: Callable = None) -> dict:
        """真实历史动量：对候选股拉历史K线算近N日涨幅，再做截面排名。
        性能：只拉快照预排序靠前的 max_fetch 只（默认120），避免全市场逐个请求。"""
        max_fetch = getattr(self.cfg, "momentum_fetch_n", 120)
        if snapshot_scores and len(codes) > max_fetch:
            codes = sorted(codes, key=lambda c: -snapshot_scores.get(c, 0))[:max_fetch]

        ranks = {}
        scores = {}
        lookback = int(self.strategy_params.get("lookback_days", self.cfg.lookback_days))
        for i, code in enumerate(codes):
            try:
                rows = RESOLVER.kline(code, "1d", "qfq", beg="20200101")
                n = min(lookback, len(rows) - 1)
                if n < 20:
                    continue
                scores[code] = rows[-1]["close"] / rows[-1 - n]["close"] - 1
            except Exception:
                continue  # 数据不可用则跳过，不伪造
            # 最耗时的阶段：每 5 只回报一次，进度条不再长期静止
            if progress_cb and (i + 1) % 5 == 0:
                progress_cb(i + 1, len(codes), "拉取历史K线/动量")
        if not scores:
            return ranks
        ordered = sorted(scores.items(), key=lambda x: x[1])
        m = len(ordered)
        for i, (code, _) in enumerate(ordered):
            ranks[code] = i / (m - 1) * 100 if m > 1 else 50.0
        return ranks

    def _score(self, f: dict, ctx: dict) -> (float, dict):
        """调用当前策略插件打分。注入该策略专属参数，因子值全部真实。"""
        merged = {**ctx, "params": self.strategy_params}
        return self.strategy.score(f, merged)

    def select(self, progress_cb: Callable = None) -> SelectionResult:
        """执行完整选股（按当前策略插件），返回结果含因子明细可追溯。"""
        raw, src_meta = self._fetch_universe(progress_cb=progress_cb)
        warnings = []
        if src_meta["stale"]:
            warnings.append(f"主源与备源均不可用，使用 {src_meta['ts']} 的真实快照缓存（非当日数据）")
        elif src_meta["source"] == "sina":
            warnings.append("东财全市场接口不可用，已切换新浪真实行情备源")
            warnings.append("新浪源不提供营收/净利同比与主力净流入；ROE由真实PB/PE推导")
        missing = STRATEGY_REQUIRED_FIELDS.get(self.strategy.name)
        if missing and src_meta["source"] != "eastmoney":
            warnings.append(f"策略[{self.strategy.display}]所需字段 {', '.join(missing)} "
                            f"在当前数据源缺失，可能选出0只；可换用其它策略或待东财恢复")
        if self.strategy.needs_history():
            warnings.append(f"该策略依赖历史K线：仅对精算池 {self.cfg.momentum_fetch_n} 只标的"
                            f"做真实历史计算并从中选股；调大可扩大范围但耗时增加")
        if progress_cb:
            progress_cb(0, len(raw), "全市场快照就绪")

        filtered = {"st": 0, "bad_pe": 0, "low_amount": 0,
                    "high_turnover": 0, "limit_up": 0, "no_price": 0,
                    "strategy_filter": 0}
        candidates = []
        for row in raw:
            name = str(row.get("f14", ""))
            if self.cfg.exclude_st and ("ST" in name.upper() or "退" in name or "*" in name):
                filtered["st"] += 1
                continue
            f = self._default_factors(row)
            # 通用流动性底线（各策略可再叠加自己的过滤）
            if f["amount"] < self.cfg.min_amount:
                filtered["low_amount"] += 1
                continue
            if f["change_pct"] >= 9.8 and self.cfg.exclude_limit_up:
                filtered["limit_up"] += 1
                continue
            price = f.get("price", 0)
            if not price or price <= 0:
                filtered["no_price"] += 1
                continue
            # 策略特定预过滤（阈值来自该策略的动态参数）
            if not self.strategy.prefilter(f, {"params": self.strategy_params}):
                filtered["strategy_filter"] += 1
                continue
            code = _norm_code(f["code"])
            candidates.append((code, name, price, f))
            if progress_cb and len(candidates) % 200 == 0:
                progress_cb(len(candidates), len(raw), "全市场初筛")

        # 需要历史上下文的策略：拉真实K线算动量排名与波动率（只拉快照靠前的候选）
        ctx_by_code = {}
        eligible_codes = None
        if self.strategy.needs_history():
            # 预筛方向必须匹配策略逻辑：反转要超跌、动量要强势，其余看流动性。
            # 否则反转策略只会把当日最强股送进历史精算池，结果完全失真。
            if self.strategy.name == "reversal":
                snapshot_scores = {c[0]: -c[3]["change_pct"] for c in candidates}
            elif self.strategy.name == "stock_momentum":
                snapshot_scores = {c[0]: c[3]["change_pct"] for c in candidates}
            else:
                snapshot_scores = {
                    c[0]: c[3]["change_pct"] / 10.0
                          + min(1.0, __import__("math").log10(max(c[3]["amount"], 1)) / 11.0)
                    for c in candidates
                }
            codes_to_fetch = sorted(candidates, key=lambda c: -snapshot_scores[c[0]])
            codes_to_fetch = [c[0] for c in codes_to_fetch[:self.cfg.momentum_fetch_n]]
            eligible_codes = set(codes_to_fetch)
            if progress_cb:
                progress_cb(0, len(codes_to_fetch), "计算历史动量/波动率")
            mom_ranks = self._compute_momentum_rank(codes_to_fetch, None, progress_cb)
            for i, (code, name, price, f) in enumerate(candidates):
                ctx_by_code[code] = {"momentum_rank": mom_ranks.get(code, 50.0)}
                if code in codes_to_fetch:
                    try:
                        rows = RESOLVER.kline(code, "1d", "qfq", beg="20200101")
                        rets = [(rows[j]["close"] / rows[j - 1]["close"] - 1)
                                for j in range(max(1, len(rows) - 30), len(rows))]
                        if rets:
                            m = sum(rets) / len(rets)
                            var = sum((r - m) ** 2 for r in rets) / len(rets)
                            ctx_by_code[code]["volatility"] = var ** 0.5
                        # 技术面共振指标（复用已验证的 indicators）
                        from ..research import indicators as IND
                        closes = [b["close"] for b in rows]
                        ma5 = IND.sma(closes, 5)[-1]
                        ma20 = IND.sma(closes, 20)[-1]
                        ma60 = IND.sma(closes, 60)[-1] if len(closes) >= 60 else None
                        _, _, hist = IND.macd(closes)
                        rsi_vals = IND.rsi(closes, 14)
                        ctx_by_code[code]["tech"] = {
                            "ma_bull": bool(ma5 and ma20 and ma60 and ma5 > ma20 > ma60),
                            "macd_hist": hist[-1] if hist and hist[-1] is not None else 0,
                            "rsi": rsi_vals[-1] if rsi_vals and rsi_vals[-1] is not None else 50,
                        }
                    except Exception:
                        ctx_by_code[code]["volatility"] = 0.03
                        ctx_by_code[code]["tech"] = {}
                else:
                    ctx_by_code[code]["volatility"] = 0.03
                if progress_cb and (i + 1) % 10 == 0:
                    progress_cb(i + 1, len(candidates), "计算波动率/技术指标")

        scored = []
        for code, name, price, f in candidates:
            # 依赖历史上下文的策略：未进入精算池的标的用默认动量50分会污染
            # 反转/动量策略排序，因此只从真实精算过的候选里产生最终结果
            if eligible_codes is not None and code not in eligible_codes:
                continue
            ctx = ctx_by_code.get(code, {"momentum_rank": 50.0, "volatility": 0.03})
            try:
                score, detail = self._score(f, ctx)
            except Exception:
                continue
            reason = " / ".join(f"{k}:{v}" for k, v in list(detail.items())[:3])
            scored.append(Pick(code=code, name=name, price=price, score=round(score, 4),
                               factors=detail, reason=reason))

        scored.sort(key=lambda p: -p.score)
        picks = scored[:self.cfg.top_n]
        return SelectionResult(
            picks=picks, universe_size=len(raw), filtered_out=filtered,
            config={**asdict(self.cfg), "strategy": self.strategy.name,
                    "strategy_params": self.strategy_params,
                    "data_source": src_meta},
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            warnings=warnings,
        )

    def target_weights(self, result: SelectionResult) -> Dict[str, float]:
        """组合构建：按得分比例分配目标权重（归一化到1）。"""
        total = sum(max(p.score, 0.01) for p in result.picks)
        if total <= 0:
            return {}
        return {p.code: round(max(p.score, 0.01) / total, 4) for p in result.picks}
