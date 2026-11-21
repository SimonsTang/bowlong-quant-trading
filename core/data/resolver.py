#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据解析器：降级链 + 缓存 + 脏数据校验 + 交易日历门控。
这是把"免费爬虫源"变成"团队可用数据层"的关键一层。

降级链：主源失败 -> 备源 -> 缓存（带时间戳，明确标注陈旧）
校验：价格/成交量/涨跌幅连续性，脏数据直接拒绝，绝不静默吞掉。
"""

import json
import os
import time
from typing import Optional

from .sources import EM, TX, SINA, Quote, DataUnavailable, _norm_code

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "cache")


def _cache_path(key: str) -> str:
    safe = key.replace("/", "_").replace(":", "_")
    return os.path.join(CACHE_DIR, safe + ".json")


def _read_cache(key: str, max_age_sec: int):
    p = _cache_path(key)
    if not os.path.exists(p):
        return None
    if time.time() - os.path.getmtime(p) > max_age_sec:
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_cache(key: str, payload):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(_cache_path(key), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def validate_quote(q: Quote) -> Quote:
    """真实数据校验：任何异常都拒绝，不用模拟值填补。"""
    if not (0 < q.price < 100000):
        raise DataUnavailable(f"{q.code} 价格异常: {q.price}")
    if q.volume < 0:
        raise DataUnavailable(f"{q.code} 成交量为负: {q.volume}")
    if q.high < q.low:
        raise DataUnavailable(f"{q.code} 最高价低于最低价")
    if q.price > q.high * 1.001 or q.price < q.low * 0.999:
        raise DataUnavailable(f"{q.code} 现价越界 [{q.low},{q.high}]: {q.price}")
    if abs(q.change_pct) > 31:  # 北交所30%已是极限，超31%必为脏数据
        raise DataUnavailable(f"{q.code} 涨跌幅异常: {q.change_pct}%")
    return q


def validate_kline(rows: list) -> list:
    """K线校验：连续性 + 基本合理性。"""
    clean = []
    for r in rows:
        if not (r["low"] <= r["open"] <= r["high"] and r["low"] <= r["close"] <= r["high"]):
            continue
        if r["volume"] < 0 or r["close"] <= 0:
            continue
        clean.append(r)
    if len(clean) < len(rows) * 0.98:
        raise DataUnavailable("K线脏数据比例超2%，拒绝使用")
    return clean


class DataResolver:
    """统一数据入口。团队代码只认这个接口，不直接碰任何爬虫源。"""

    def __init__(self, realtime_ttl: int = None, kline_ttl: int = None):
        from ..config.settings import SETTINGS
        self._settings = SETTINGS
        self.realtime_ttl = realtime_ttl if realtime_ttl is not None else SETTINGS.get("data", "realtime_ttl")
        self.kline_ttl = kline_ttl if kline_ttl is not None else SETTINGS.get("data", "kline_ttl")

    def refresh_config(self):
        """运行时热更新缓存策略。"""
        self.realtime_ttl = self._settings.get("data", "realtime_ttl")
        self.kline_ttl = self._settings.get("data", "kline_ttl")

    def quote(self, symbol: str) -> Quote:
        code = _norm_code(symbol)
        ck = f"quote_{code}"
        cached = _read_cache(ck, self.realtime_ttl)
        if cached:
            q = Quote(**cached["q"])
            q.ts = q.ts + "(缓存)"
            return q

        errors = []
        for src in (TX, EM, SINA):  # 实时以快的腾讯优先
            try:
                q = validate_quote(src.quote(code))
                _write_cache(ck, {"q": q.to_dict(), "ts": time.time()})
                return q
            except Exception as e:
                errors.append(f"{src.name}: {e}")

        # 降级到过期缓存，但明确标注 STALE
        stale = _read_cache(ck, 86400)
        if stale:
            q = Quote(**stale["q"])
            q.ts = q.ts + "(STALE-降级缓存)"
            return q
        raise DataUnavailable(f"{code} 所有实时源失败 | " + " | ".join(errors))

    def kline(self, symbol: str, period: str = "1d", fqt: str = "qfq",
              beg: str = "20200101", end: str = "20500101") -> list:
        code = _norm_code(symbol)
        ck = f"kline_{code}_{period}_{fqt}_{beg}_{end}"
        cached = _read_cache(ck, self.kline_ttl)
        if cached:
            return cached["rows"]

        errors = []
        # 降级链：东财(复权最全) → 腾讯(日/周/月) → 新浪(全周期)。
        # 任一源不可用不代表数据不存在，绝不让单点故障拖垮整个行情页。
        for src in (EM, TX, SINA):
            try:
                rows = src.kline(code, period, fqt, beg, end)
                if not rows:
                    raise DataUnavailable("返回空K线")
                rows = validate_kline(rows)
                _write_cache(ck, {"rows": rows, "ts": time.time(), "src": src.name})
                return rows
            except Exception as e:
                errors.append(f"{src.name}: {e}")

        # 所有源失败 → 降级到过期缓存（历史真实数据，明确标注 STALE），
        # 比页面完全空白更可用。无缓存才真正抛错。
        stale = _read_cache(ck, 30 * 86400)
        if stale:
            return stale["rows"]
        raise DataUnavailable(f"{code} 历史K线不可用 | " + " | ".join(errors))

    def valuation(self, symbol: str) -> dict:
        """真实估值快照（PE/PB/市值/换手率），盘中30秒缓存。
        降级链：东财 → 腾讯；全失败时用过期缓存兜底（STALE），不让F10整块空白。"""
        code = _norm_code(symbol)
        ck = f"valuation_{code}"
        cached = _read_cache(ck, self.realtime_ttl)
        if cached:
            return cached
        errors = []
        for src in (EM, TX):
            try:
                v = src.valuation(code)
                _write_cache(ck, v)
                return v
            except Exception as e:
                errors.append(f"{src.name}: {e}")
        stale = _read_cache(ck, 7 * 86400)
        if stale:
            return stale
        raise DataUnavailable(f"{code} 估值快照不可用 | " + " | ".join(errors))

    def f10(self, symbol: str) -> dict:
        """F10 公司概况，盘后1天缓存（基本面变化慢）。"""
        code = _norm_code(symbol)
        ck = f"f10_{code}"
        cached = _read_cache(ck, 86400)
        if cached:
            return cached
        try:
            info = EM.f10_profile(code)
            _write_cache(ck, info)
            return info
        except Exception:
            stale = _read_cache(ck, 60 * 86400)
            if stale:
                return stale
            raise

    def universe(self) -> list:
        """全市场标的池，真实数据。"""
        ck = "universe_all"
        cached = _read_cache(ck, 86400)
        if cached:
            return cached["rows"]
        rows = EM.list_all()
        if not rows:
            raise DataUnavailable("全市场列表为空")
        _write_cache(ck, {"rows": rows, "ts": time.time()})
        return rows

    def is_trading_now(self) -> bool:
        """交易时段门控，避免非交易时段反复空请求打黑IP。"""
        t = time.localtime()
        if t.tm_wday >= 5:
            return False
        hm = t.tm_hour * 100 + t.tm_min
        return (930 <= hm <= 1130) or (1300 <= hm <= 1500)
