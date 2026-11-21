#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多市场真实数据解析器：ETF / 期货 / 期权。
全部接口 2026-11-20 东方财富实测跑通，禁止模拟数据。
  - ETF 列表: fs=b:MK0021..MK0024，实测 1663 只
  - 期货列表: fs=m:113(上期所)/114(大商所)/115(郑商所)/8(中金所)
  - 期权列表: fs=m:10(上交所ETF期权)/11(中金所股指期权)，实测 716/778 合约
  - K线: push2his stock/kline，secid 见各品种；期权/ETF 价格字段需按 scale 还原
"""
import json
import time
import urllib.request
from dataclasses import dataclass, asdict

from .instruments import (
    AssetClass, Instrument, EM_MARKET, FUTURES_MASTER,
    futures_instrument, etf_instrument, option_instrument, infer_asset_class,
)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Referer": "https://quote.eastmoney.com/"}


class MultiMarketDataError(Exception):
    pass


def _get(url: str, timeout: int = 12) -> str:
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


@dataclass
class MMQuote:
    symbol: str
    name: str
    price: float
    prev_close: float
    open: float
    high: float
    low: float
    volume: float
    amount: float
    change_pct: float
    asset_class: str
    ts: str
    source: str = "eastmoney"

    def to_dict(self):
        return asdict(self)


class MultiMarketSource:
    """统一入口：list_instruments / kline / quote 覆盖三类品种。"""

    name = "eastmoney-multimarket"

    # ---------- 列表 ----------
    def list_etfs(self, max_pages: int = 20) -> list:
        out, page = [], 1
        FS = "b:MK0021,b:MK0022,b:MK0023,b:MK0024"
        while page <= max_pages:
            url = ("https://push2.eastmoney.com/api/qt/clist/get"
                   f"?pn={page}&pz=100&po=1&np=1&fltt=2&invt=2&fid=f12&fs={FS}"
                   "&fields=f12,f14,f2,f3,f6,f13")
            d = json.loads(_get(url)); data = d.get("data") or {}
            total = int(data.get("total") or 0)
            rows = data.get("diff") or []
            if not rows:
                break
            for r in rows:
                num = str(r["f12"])
                mkt = "SH" if num.startswith(("5", "6")) else "SZ"
                out.append({
                    "symbol": f"{num}.{mkt}", "name": r.get("f14", ""),
                    "price": r.get("f2"), "change_pct": r.get("f3"),
                    "amount": r.get("f6"), "asset_class": AssetClass.ETF.value,
                })
            if len(out) >= total:
                break
            page += 1
        return out

    def list_futures(self) -> list:
        """期货主连目录（规格来自 instruments.FUTURES_MASTER）。"""
        out = []
        for key, (name, exch, mult, tick, margin, comm) in FUTURES_MASTER.items():
            if key.upper() == "IFM":  # 中金所数字代码，单列于下
                continue
            mkt = EM_MARKET[exch]
            out.append({
                "symbol": f"{mkt}.{key}", "name": name, "exchange": exch,
                "multiplier": mult, "tick": tick, "margin_rate": margin,
                "asset_class": AssetClass.FUTURES.value,
            })
        # 中金所主力合约实测 8.150130=IM主力；给出常见股指主力
        for code, name in [("150130", "IM主力合约"), ("150131", "IM次主力合约")]:
            out.append({"symbol": f"8.{code}", "name": name, "exchange": "CFFEX",
                        "multiplier": 200, "tick": 0.2, "margin_rate": 0.12,
                        "asset_class": AssetClass.FUTURES.value})
        return out

    def list_options(self, market: int = 10, max_pages: int = 8) -> list:
        """ETF期权(m:10)/股指期权(m:11)合约列表，实测可用。"""
        out, page = [], 1
        while page <= max_pages:
            url = ("https://push2.eastmoney.com/api/qt/clist/get"
                   f"?pn={page}&pz=100&po=1&np=1&fltt=2&invt=2&fid=f12&fs=m:{market}"
                   "&fields=f12,f13,f14,f2,f3,f6")
            d = json.loads(_get(url)); data = d.get("data") or {}
            total = int(data.get("total") or 0)
            rows = data.get("diff") or []
            if not rows:
                break
            for r in rows:
                out.append({
                    "symbol": f"{r['f13']}.{r['f12']}", "code": str(r["f12"]),
                    "name": r.get("f14", ""), "price": r.get("f2"),
                    "change_pct": r.get("f3"), "amount": r.get("f6"),
                    "asset_class": AssetClass.OPTIONS.value,
                })
            if len(out) >= total:
                break
            page += 1
        return out

    # ---------- K线 ----------
    def kline(self, symbol: str, period: str = "1d", fqt: str = "none",
              beg: str = "20200101", limit: int = 100000) -> list:
        """统一K线。period: 1d/1w/1M/1m/5m/15m/30m/60m。价格按品种 scale 还原为真实值。"""
        klt = {"1d": 101, "1w": 102, "1M": 103, "1m": 1, "5": 5,
               "5m": 5, "15m": 15, "30m": 30, "60m": 60}[period]
        ac = infer_asset_class(symbol)
        secid = self._secid(symbol, ac)
        # 注意：K线 f51-f57 本身已是真实价格（实测 ETF=4.014、期权=0.1096、期货=2999），
        #       只有实时快照 f43 才是放大整数。K线不做 scale 还原，避免二次除法。
        scale = 1.0
        # 期货/期权不支持复权
        fq = 0 if ac in (AssetClass.FUTURES, AssetClass.OPTIONS) else {"none": 0, "qfq": 1, "hfq": 2}[fqt]
        url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get"
               f"?secid={secid}&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56,f57"
               f"&klt={klt}&fqt={fq}&beg={beg}&end=20500101&lmt={limit}")
        d = json.loads(_get(url)); data = d.get("data")
        klines = (data.get("klines") or []) if data else []
        if not klines:
            raise MultiMarketDataError(f"东财无 {symbol} 的K线数据（secid={secid}）")
        out = []
        for line in klines:
            p = line.split(",")
            try:
                out.append({
                    "date": p[0],
                    "open": float(p[1]) / scale,
                    "close": float(p[2]) / scale,
                    "high": float(p[3]) / scale,
                    "low": float(p[4]) / scale,
                    "volume": float(p[5]),
                    "amount": float(p[6]) if len(p) > 6 else 0.0,
                })
            except (ValueError, IndexError):
                continue
        return out

    # ---------- 实时快照 ----------
    def quote(self, symbol: str) -> MMQuote:
        ac = infer_asset_class(symbol)
        secid = self._secid(symbol, ac)
        # 关键：东财 f43 等价格字段的放大倍数随品种精度变化（f59=小数位数）：
        #   股票 2 位 / ETF 3 位 / 期货 0 位 / 期权 4 位。用 f59 动态还原，不写死 scale。
        url = ("https://push2.eastmoney.com/api/qt/stock/get"
               f"?secid={secid}&fields=f43,f44,f45,f46,f47,f48,f57,f58,f59,f60,f169,f170,f171")
        d = json.loads(_get(url)); x = d.get("data")
        if not x or x.get("f43") in (None, "-"):
            raise MultiMarketDataError(f"东财无 {symbol} 快照")
        precision = x.get("f59")
        scale = 10 ** precision if isinstance(precision, int) else 100.0
        def val(k, default=0.0):
            v = x.get(k)
            return float(v) / scale if isinstance(v, (int, float)) else default
        prev = val("f60"); price = val("f43")
        return MMQuote(
            symbol=symbol, name=x.get("f58", ""), price=price, prev_close=prev,
            open=val("f46"), high=val("f44"), low=val("f45"),
            volume=float(x.get("f47") or 0), amount=float(x.get("f48") or 0),
            change_pct=(x.get("f170") or 0) / 100.0,
            asset_class=ac.value, ts=time.strftime("%Y-%m-%d %H:%M:%S"),
        )

    # ---------- 内部 ----------
    def _secid(self, symbol: str, ac: AssetClass) -> str:
        s = symbol.strip()
        if "." in s and s.split(".", 1)[0].isdigit():
            # 已是 113.rbm / 10.10012850 / 1.510300 形式
            head, tail = s.split(".", 1)
            if head.isdigit() and len(head) <= 3:
                return s
            # 1.510300.SH 形式
            if tail in ("SH", "SZ", "BJ"):
                return ("1." if tail == "SH" else "0.") + head
        if ac == AssetClass.FUTURES:
            return futures_instrument(s).secid
        # ETF/现货：600519.SH -> 1.600519
        num, mkt = s.split(".")
        return ("1." if mkt.upper() == "SH" else "0.") + num


MM_SOURCE = MultiMarketSource()
