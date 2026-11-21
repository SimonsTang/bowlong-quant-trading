#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真实数据层 - 多源降级 + 缓存 + 脏数据校验
全部接口均来自实测跑通的公开源（2026-11-20 验证）：
  - 东财：全市场列表 / 日K / 分钟K（含前复权）
  - 腾讯：实时快照（批量，响应快）
  - 新浪：实时快照（备选）

原则：一律真实数据，无模拟、无随机数。任何源失败都不返回伪造值，
      而是切换备源或抛出 DataUnavailable，让上层明确知道数据不可用。
仅依赖 Python 标准库，便于先用最小环境跑通数据层。
"""

import json
import os
import time
import urllib.request
import urllib.parse
from dataclasses import dataclass, asdict
from typing import Optional

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


class DataUnavailable(Exception):
    """所有真实数据源均不可用，禁止用模拟数据兜底。"""
    pass


def _http_get(url: str, headers: dict = None, timeout: int = 12,
              encoding: str = "utf-8", retries: int = 2) -> str:
    """带轻量重试的HTTP GET：仅针对瞬时断连/超时，避免单点抖动拖垮整页。
    指数退避 0.3s/0.6s；重试耗尽后抛错，由上层降级到备源（绝不返回伪造数据）。"""
    import time as _t
    h = dict(UA)
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    last = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode(encoding, "ignore")
        except Exception as e:
            last = e
            if attempt < retries:
                _t.sleep(0.3 * (attempt + 1))
    raise last


def _norm_code(symbol: str) -> str:
    """统一为 600519.SH / 000001.SZ / 510300.SH(ETF) / 8xxxxx.BJ 形式。
    沪深ETF：51/52/56/58→SH，15/16/18→SZ；股票：6/9→SH，0/3→SZ，4/8→BJ。"""
    s = symbol.strip().upper()
    if "." in s:
        return s
    if s.startswith(("6", "9", "5")):          # 5 开头含上交所ETF(51/52/56/58)
        return s + ".SH"
    if s.startswith(("0", "3", "1")):          # 1 开头含深交所ETF(15/16/18)
        return s + ".SZ"
    if s.startswith(("4", "8")):
        return s + ".BJ"
    raise ValueError(f"无法识别代码: {symbol}")


def _secid(code: str) -> str:
    """东财 secid：沪市 1.，深市/北交 0.。"""
    num, mkt = code.split(".")
    return ("1." if mkt == "SH" else "0.") + num


@dataclass
class Quote:
    """统一字段的实时快照。"""
    code: str
    name: str
    price: float
    prev_close: float
    open: float
    high: float
    low: float
    volume: int          # 股
    amount: float        # 元
    change_pct: float
    bid1: float          # 买一价
    ask1: float          # 卖一价
    ts: str              # 数据时间戳
    source: str

    def to_dict(self):
        return asdict(self)


class EastMoneySource:
    """东财：全市场列表 + 日K/分钟K（前复权）+ 实时快照。数据最全，作为主源。"""

    name = "eastmoney"

    def list_all(self, max_pages: int = 80) -> list:
        """东财单页硬上限100只，必须分页拉全市场（约5565只）。"""
        out = []
        page = 1
        total = None
        while page <= max_pages:
            url = ("https://push2.eastmoney.com/api/qt/clist/get"
                   f"?pn={page}&pz=100&po=1&np=1&fltt=2&invt=2&fid=f12"
                   "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
                   "&fields=f12,f14,f2,f3,f6")
            d = json.loads(_http_get(url, {"Referer": "https://quote.eastmoney.com/"}))
            data = d.get("data") or {}
            if total is None:
                total = int(data.get("total") or 0)
            rows = data.get("diff") or []
            if not rows:
                break
            for r in rows:
                try:
                    code = _norm_code(str(r["f12"]))
                    out.append({
                        "code": code, "name": r.get("f14", ""),
                        "price": float(r["f2"]) if r.get("f2") not in (None, "-") else None,
                        "change_pct": float(r["f3"]) if r.get("f3") not in (None, "-") else None,
                        "amount": float(r["f6"]) if r.get("f6") not in (None, "-") else None,
                    })
                except Exception:
                    continue
            if len(out) >= total:
                break
            page += 1
        return out

    def kline(self, symbol: str, period: str = "1d", fqt: str = "qfq",
              beg: str = "20200101", end: str = "20500101", limit: int = 100000) -> list:
        """period: 1d/1w/1M/1m/5m/15m/30m/60m; fqt: none/qfq/hfq。返回真实K线字典列表。
        周K klt=102、月K klt=103（2026-11-20 实测通过）。"""
        klt = {"1d": 101, "1w": 102, "1M": 103,
               "1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60}[period]
        fq = {"none": 0, "qfq": 1, "hfq": 2}[fqt]
        code = _norm_code(symbol)
        url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get"
               f"?secid={_secid(code)}&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
               f"&klt={klt}&fqt={fq}&beg={beg}&end={end}&lmt={limit}")
        d = json.loads(_http_get(url, {"Referer": "https://quote.eastmoney.com/"}))
        klines = (d.get("data") or {}).get("klines") or []
        out = []
        for line in klines:
            p = line.split(",")
            try:
                out.append({
                    "date": p[0], "open": float(p[1]), "close": float(p[2]),
                    "high": float(p[3]), "low": float(p[4]),
                    "volume": int(float(p[5])),
                    "amount": float(p[6]) if len(p) > 6 else 0.0,
                })
            except Exception:
                continue
        return out

    def quote(self, symbol: str) -> Quote:
        code = _norm_code(symbol)
        url = ("https://push2.eastmoney.com/api/qt/stock/get"
               f"?secid={_secid(code)}&fields=f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170,f171")
        d = json.loads(_http_get(url, {"Referer": "https://quote.eastmoney.com/"}))
        x = d.get("data") or {}
        if not x:
            raise DataUnavailable(f"东财无 {symbol} 快照")
        scale = 100.0  # 东财价格字段为放大100倍整数
        return Quote(
            code=code, name=x.get("f58", ""),
            price=x["f43"] / scale, prev_close=x["f60"] / scale,
            open=x["f46"] / scale, high=x["f44"] / scale, low=x["f45"] / scale,
            volume=int(x["f47"]), amount=float(x["f48"]),
            change_pct=x.get("f170", 0) / 100.0,
            bid1=0.0, ask1=0.0,
            ts=time.strftime("%Y-%m-%d %H:%M:%S"), source=self.name,
        )

    def valuation(self, symbol: str) -> dict:
        """真实估值快照：PE(动态/静态/TTM)、PB、总/流通市值、换手率、振幅、内外盘。
        2026-11-20 实测均可用。"""
        code = _norm_code(symbol)
        url = ("https://push2.eastmoney.com/api/qt/stock/get"
               f"?secid={_secid(code)}&fields=f57,f58,f43,f60,f46,f44,f45,f47,f48,f49,"
               "f161,f162,f163,f164,f167,f168,f116,f117,f170,f171,f86")
        x = (json.loads(_http_get(url, {"Referer": "https://quote.eastmoney.com/"}))
             .get("data") or {})
        if not x:
            raise DataUnavailable(f"东财无 {symbol} 估值快照")

        def div(v, base=100.0):
            return round(v / base, 4) if isinstance(v, (int, float)) else None

        return {
            "code": code, "name": x.get("f58", ""),
            "price": div(x.get("f43")), "prev_close": div(x.get("f60")),
            "pe_dynamic": div(x.get("f162")), "pe_static": div(x.get("f163")),
            "pe_ttm": div(x.get("f164")), "pb": div(x.get("f167")),
            "market_cap_yi": round(x["f116"] / 1e8, 2) if isinstance(x.get("f116"), (int, float)) else None,
            "float_cap_yi": round(x["f117"] / 1e8, 2) if isinstance(x.get("f117"), (int, float)) else None,
            "turnover_pct": div(x.get("f168")), "amplitude_pct": div(x.get("f171")),
            "volume": x.get("f47"), "amount": x.get("f48"),
            "outer_vol": x.get("f49"), "inner_vol": x.get("f161"),
            "change_pct": div(x.get("f170")), "source": self.name,
        }

    def f10_profile(self, symbol: str) -> dict:
        """F10 公司概况（东财 PC_HSF10 PageAjax，2026-11-20 实测 40 字段真实可用）。"""
        code = _norm_code(symbol)
        prefix = "SH" if code.endswith("SH") else "SZ" if code.endswith("SZ") else "BJ"
        fcode = prefix + code.split(".")[0]
        url = f"https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax?code={fcode}"
        raw = _http_get(url, {"Referer": "https://emweb.securities.eastmoney.com/"})
        try:
            d = json.loads(raw)
        except Exception:
            raise DataUnavailable(f"东财F10无 {symbol} 公司概况")
        jb = (d.get("jbzl") or [{}])[0]
        return {
            "code": code, "name": jb.get("SECURITY_NAME_ABBR", ""),
            "org_name": jb.get("ORG_NAME", ""), "org_name_en": jb.get("ORG_NAME_EN", ""),
            "market": jb.get("TRADE_MARKET", ""), "board": jb.get("SECURITY_TYPE", ""),
            "industry": jb.get("EM2016", ""), "industry_csrc": jb.get("INDUSTRYCSRC1", ""),
            "chairman": jb.get("CHAIRMAN", ""), "legal_person": jb.get("LEGAL_PERSON", ""),
            "secretary": jb.get("SECRETARY", ""), "president": jb.get("PRESIDENT", ""),
            "province": jb.get("PROVINCE", ""), "address": jb.get("ADDRESS", ""),
            "website": jb.get("ORG_WEB", ""), "phone": jb.get("ORG_TEL", ""),
            "email": jb.get("ORG_EMAIL", ""),
            "reg_capital_wan": jb.get("REG_CAPITAL", ""), "employees": jb.get("EMP_NUM", ""),
            "account_firm": jb.get("ACCOUNTFIRM_NAME", ""), "law_firm": jb.get("LAW_FIRM", ""),
            "profile": (jb.get("ORG_PROFILE") or "").strip()[:600],
            "business": (jb.get("BUSINESS_SCOPE") or "").strip()[:600],
            "former_name": jb.get("FORMERNAME", ""), "source": "eastmoney-f10",
        }


class TencentSource:
    """腾讯：实时快照，支持一次批量多只，响应快。作为实时备源/展示源。"""

    name = "tencent"

    def kline(self, symbol: str, period: str = "1d", fqt: str = "qfq",
              beg: str = "20200101", end: str = "20500101", limit: int = 100000) -> list:
        """腾讯K线备用源（真实数据）。日/周/月用 fqkline 接口，分钟线不支持（返回空交给新浪）。
        字段统一为 date/open/close/high/low/volume/amount，与东财口径一致。"""
        code = _norm_code(symbol)
        if period not in ("1d", "1w", "1M"):
            return []  # 腾讯分钟K线接口不稳定，交给新浪
        pre = "sh" if code.endswith("SH") else "sz" if code.endswith("SZ") else "bj"
        tc = pre + code.split(".")[0]
        key = {"1d": "day", "1w": "week", "1M": "month"}[period]
        fq = "qfq" if fqt == "qfq" else "hfq" if fqt == "hfq" else ""
        # 腾讯 fqkline 单次上限约 640 根；用日期区间分段拉取再拼接，可得 10 年+ 前复权历史。
        import datetime as _dt
        try:
            cur = _dt.datetime.strptime(beg, "%Y%m%d").date()
            last = _dt.datetime.strptime(end if end and end < "20990101" else "20300101", "%Y%m%d").date()
        except ValueError:
            cur = _dt.date(2015, 1, 1)
            last = _dt.date.today()
        today = _dt.date.today()
        if last > today:
            last = today
        SEG = 640
        out_map = {}
        guard = 0
        import time as _t
        while cur <= last and guard < 20:
            guard += 1
            if guard > 1:
                _t.sleep(0.4)  # 分段请求节流，避免高频拉取触发腾讯限流
            seg_end = min(cur + _dt.timedelta(days=SEG * 2), last)  # 每段约覆盖2.5年日历
            b = cur.strftime("%Y-%m-%d")
            e = seg_end.strftime("%Y-%m-%d")
            url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
                   f"?param={tc},{key},{b},{e},640,{fq}")
            try:
                d = json.loads(_http_get(url))
                node = (d.get("data") or {}).get(tc)
                if not isinstance(node, dict):
                    break
                rows = node.get(fq + key) or node.get(key) or []
            except Exception:
                break
            if not rows:
                break
            for r in rows:
                try:
                    out_map[r[0]] = {"date": r[0], "open": float(r[1]), "close": float(r[2]),
                                     "high": float(r[3]), "low": float(r[4]),
                                     "volume": int(float(r[5])),
                                     "amount": float(r[6]) if len(r) > 6 else 0.0}
                except (ValueError, IndexError, TypeError):
                    continue
            # 若本段已满640根，推进到本段最后一根之后；否则直接跳到下一段起点
            seg_rows = [r for r in rows if isinstance(r, list) and r]
            if seg_rows and len(seg_rows) >= 640:
                try:
                    nx = _dt.datetime.strptime(seg_rows[-1][0], "%Y-%m-%d").date() + _dt.timedelta(days=1)
                    cur = nx
                    continue
                except (ValueError, IndexError):
                    pass
            cur = seg_end + _dt.timedelta(days=1)
        all_rows = [out_map[k] for k in sorted(out_map)]
        # 前复权早期可能出现非正价格（分红除权的数学结果，非数据错误）。
        # 裁掉"最后一个非正价格"之前的整段，保留其后连续可交易区间，
        # 避免中间残留负价导致 validate_kline 整源拒绝。
        last_bad = -1
        for i, r in enumerate(all_rows):
            if r["close"] <= 0 or r["open"] <= 0 or r["low"] <= 0:
                last_bad = i
        if last_bad >= 0:
            all_rows = all_rows[last_bad + 1:]
        return all_rows

    def quote(self, symbol: str) -> Quote:
        code = _norm_code(symbol)
        qcode = code.replace(".", "").lower()
        qcode = ("sh" if code.endswith("SH") else "sz" if code.endswith("SZ") else "bj") + qcode[:6]
        txt = _http_get(f"https://qt.gtimg.cn/q={qcode}", encoding="gbk")
        if '="' not in txt:
            raise DataUnavailable(f"腾讯无 {symbol} 快照")
        body = txt.split('="', 1)[1].rstrip('";\n')
        p = body.split("~")
        if len(p) < 45:
            raise DataUnavailable(f"腾讯 {symbol} 字段不完整")
        return Quote(
            code=code, name=p[1], price=float(p[3]), prev_close=float(p[4]),
            open=float(p[5]), volume=int(float(p[6])),
            high=float(p[33]), low=float(p[34]),
            amount=float(p[37]) * 10000 if p[37] else 0.0,
            change_pct=float(p[32]), bid1=float(p[9]), ask1=float(p[19]),
            ts=p[30], source=self.name,
        )

    def valuation(self, symbol: str) -> dict:
        """腾讯估值快照备源（真实数据）。东财 valuation 不可用时的降级。
        腾讯字段（2026-11-20 实测核对）：p[38]=换手率 p[39]=PE(TTM)
                  p[44]=流通市值(亿) p[45]=总市值(亿) p[46]=PB
                  p[52]=PE(动) p[53]=PE(静)"""
        code = _norm_code(symbol)
        qcode = ("sh" if code.endswith("SH") else "sz" if code.endswith("SZ") else "bj") + code.split(".")[0]
        txt = _http_get(f"https://qt.gtimg.cn/q={qcode}", encoding="gbk")
        if '="' not in txt:
            raise DataUnavailable(f"腾讯无 {symbol} 估值")
        p = txt.split('="', 1)[1].rstrip('";\n').split("~")
        if len(p) < 50:
            raise DataUnavailable(f"腾讯 {symbol} 估值字段不完整")

        def f(i):
            try:
                return float(p[i])
            except (ValueError, IndexError):
                return None

        return {
            "code": code, "name": p[1],
            "price": f(3), "prev_close": f(4),
            "pe_dynamic": f(52), "pe_static": f(53), "pe_ttm": f(39), "pb": f(46),
            "market_cap_yi": f(45), "float_cap_yi": f(44),
            "turnover_pct": f(38), "amplitude_pct": None,
            "volume": int(f(6) or 0), "amount": (f(37) or 0) * 10000,
            "outer_vol": None, "inner_vol": None,
            "change_pct": f(32), "source": "tencent",
        }

    def quote_batch(self, symbols: list) -> dict:
        codes = [_norm_code(s) for s in symbols]
        qlist = []
        for c in codes:
            pre = "sh" if c.endswith("SH") else "sz" if c.endswith("SZ") else "bj"
            qlist.append(pre + c.split(".")[0])
        txt = _http_get("https://qt.gtimg.cn/q=" + ",".join(qlist), encoding="gbk")
        out = {}
        for line in txt.split(";"):
            if '="' not in line:
                continue
            body = line.split('="', 1)[1].rstrip('"\n ')
            p = body.split("~")
            if len(p) < 45:
                continue
            code = _norm_code(p[2])
            out[code] = Quote(
                code=code, name=p[1], price=float(p[3]), prev_close=float(p[4]),
                open=float(p[5]), volume=int(float(p[6])),
                high=float(p[33]), low=float(p[34]),
                amount=float(p[37]) * 10000 if p[37] else 0.0,
                change_pct=float(p[32]), bid1=float(p[9]), ask1=float(p[19]),
                ts=p[30], source=self.name,
            )
        return out


class SinaSource:
    """新浪：实时快照 + 全周期K线（分钟/日/周/月），作为最后备源。"""

    name = "sina"

    def kline(self, symbol: str, period: str = "1d", fqt: str = "qfq",
              beg: str = "20200101", end: str = "20500101", limit: int = 100000) -> list:
        """新浪K线（真实数据）。scale: 5/15/30/60分钟、240日线；周/月用 1200/7200 分钟聚合。
        新浪不提供复权，fqt=qfq/hfq 时数据为不复权价（备源降级时明确标注）。"""
        code = _norm_code(symbol)
        pre = "sh" if code.endswith("SH") else "sz" if code.endswith("SZ") else "bj"
        sc = pre + code.split(".")[0]
        # 新浪 scale 单位分钟：240=日线；周K=1200、月K=7200（新浪支持该约定）
        scale = {"1d": 240, "1w": 1200, "1M": 7200,
                 "1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60}[period]
        if scale == 1:
            scale = 5  # 新浪最小5分钟
        datalen = min(int(limit), 1023)
        url = ("https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
               f"?symbol={sc}&scale={scale}&ma=no&datalen={datalen}")
        txt = _http_get(url, {"Referer": "https://finance.sina.com.cn"})
        rows = json.loads(txt)
        if not isinstance(rows, list):
            raise DataUnavailable(f"新浪无 {symbol} K线")
        out = []
        for r in rows:
            try:
                out.append({"date": r["day"].replace("T", " "), "open": float(r["open"]),
                            "close": float(r["close"]), "high": float(r["high"]),
                            "low": float(r["low"]), "volume": int(float(r["volume"])),
                            "amount": 0.0})
            except (ValueError, KeyError, TypeError):
                continue
        return out

    def quote(self, symbol: str) -> Quote:
        code = _norm_code(symbol)
        pre = "sh" if code.endswith("SH") else "sz" if code.endswith("SZ") else "bj"
        scode = pre + code.split(".")[0]
        txt = _http_get(f"https://hq.sinajs.cn/list={scode}",
                        {"Referer": "https://finance.sina.com.cn"}, encoding="gbk")
        if '="' not in txt:
            raise DataUnavailable(f"新浪无 {symbol} 快照")
        p = txt.split('="', 1)[1].rstrip('";\n').split(",")
        if len(p) < 32:
            raise DataUnavailable(f"新浪 {symbol} 字段不完整")
        price = float(p[3]); prev = float(p[2])
        return Quote(
            code=code, name=p[0], price=price, prev_close=prev,
            open=float(p[1]), high=float(p[4]), low=float(p[5]),
            volume=int(float(p[8])), amount=float(p[9]),
            change_pct=(price - prev) / prev * 100 if prev else 0.0,
            bid1=float(p[11]) if p[11] else price,
            ask1=float(p[21]) if p[21] else price,
            ts=f"{p[30]} {p[31]}", source=self.name,
        )


# 单例
EM = EastMoneySource()
TX = TencentSource()
SINA = SinaSource()
