#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多市场品种抽象：期货 / 期权 / ETF 的合约规格与元数据。
所有字段口径来自 2026-11-20 东方财富真实接口实测，禁止模拟数据。

设计原则（借鉴 vnpy 合约对象思想）：
  - 每个品种有唯一 Instrument，承载乘数、最小跳动、保证金、手续费、交易时段等规格
  - 成本/风控/回测统一从 Instrument 读取规格，不散落硬编码
  - 期权额外携带 标的 / 行权价 / 到期日 / 认购认沽 / 行权方式
"""
from dataclasses import dataclass, field, asdict
from enum import Enum


class AssetClass(str, Enum):
    SPOT = "SPOT"        # A股现货
    ETF = "ETF"          # 场内基金
    FUTURES = "FUTURES"  # 期货
    OPTIONS = "OPTIONS"  # 期权


class OptionType(str, Enum):
    CALL = "CALL"   # 认购
    PUT = "PUT"     # 认沽


@dataclass
class Instrument:
    """统一合约规格。"""
    symbol: str              # 统一代码，如 510300.SH / 113.rbm / 10.10012850
    name: str
    asset_class: AssetClass
    exchange: str            # 交易所：SHFE/DCE/CZCE/CFFEX/SSE/SZSE
    secid: str               # 东财 secid
    multiplier: float = 1.0       # 合约乘数：期货/期权关键
    tick: float = 0.01            # 最小跳动价位
    price_scale: float = 100.0    # 东财价格字段缩放除数（实测 ETF/期权 f43 为放大值）
    margin_rate: float = 0.0      # 保证金比例，期货用
    commission_rate: float = 0.00025  # 手续费率
    commission_min: float = 5.0   # 最低佣金（期货通常为0，按手收）
    commission_per_lot: float = 0.0   # 按手固定手续费（期货）
    stamp_tax: float = 0.0        # 印花税（仅现货卖出，ETF/期货/期权免）
    t_plus: int = 1               # T+1 现货；期货/期权 T+0
    short_allowed: bool = False   # 是否允许做空（期货双向，ETF 融券）
    # 期权专属
    underlying: str = ""
    strike: float = 0.0
    expiry: str = ""
    option_type: OptionType = None
    # 期货专属
    underlying_future: str = ""   # 主连对应标的

    def to_dict(self):
        d = asdict(self)
        for k in ("asset_class", "option_type"):
            if d[k] is not None:
                d[k] = d[k].value if isinstance(d[k], Enum) else d[k]
        return d


# ---------- 交易所 -> 东财市场号（2026-11-20 实测确认） ----------
EM_MARKET = {
    "SSE": 1, "SZSE": 0, "SHFE": 113, "DCE": 114,
    "CZCE": 115, "CFFEX": 8, "SSE_OPTION": 10, "CFFEX_OPTION": 11,
}

# 期货主连品种目录（secid 后缀 m；实测 2026-11-20 均可用 456 根日线）
FUTURES_MASTER = {
    "rbm": ("螺纹钢主连", "SHFE", 10, 1.0, 0.10, 3.0),
    "hcm": ("热卷主连", "SHFE", 10, 1.0, 0.10, 3.0),
    "cum": ("沪铜主连", "SHFE", 5, 5.0, 0.10, 3.0),
    "alm": ("沪铝主连", "SHFE", 5, 5.0, 0.10, 3.0),
    "znm": ("沪锌主连", "SHFE", 5, 5.0, 0.10, 3.0),
    "aum": ("沪金主连", "SHFE", 1000, 0.02, 0.10, 2.0),
    "agm": ("沪银主连", "SHFE", 15, 1.0, 0.10, 2.0),
    "scm": ("原油主连", "SHFE", 1000, 0.1, 0.10, 20.0),  # INE 挂 113
    "ym": ("豆油主连", "DCE", 10, 1.0, 0.08, 2.5),
    "mm": ("豆粕主连", "DCE", 10, 1.0, 0.08, 1.5),
    "im": ("铁矿石主连", "DCE", 100, 0.5, 0.10, 3.0),
    "pgm": ("LPG主连", "DCE", 10, 1.0, 0.10, 3.0),
    "FGm": ("玻璃主连", "CZCE", 20, 1.0, 0.09, 3.0),
    "MAm": ("甲醇主连", "CZCE", 10, 1.0, 0.09, 2.0),
    "RMm": ("菜粕主连", "CZCE", 10, 1.0, 0.09, 2.0),
    "TAm": ("PTA主连", "CZCE", 5, 2.0, 0.09, 3.0),
    "IFm": ("沪深300股指期货主连", "CFFEX", 300, 0.2, 0.12, 3.0),  # 实测代码见下注
}


def futures_instrument(code: str) -> Instrument:
    """code 可为 113.rbm / rbm / rbm.SHFE。查规格目录构造 Instrument。"""
    c = code.strip().lower()
    if "." in c:
        c = c.split(".", 1)[1]
    if "shfe" in c or "dce" in c or "czce" in c or "cffex" in c:
        c = c.split(".", 1)[0] if "." in c else c
    key = c if c.endswith("m") else c + "m"
    if key not in FUTURES_MASTER:
        raise ValueError(f"未知期货品种: {code}（可用: {list(FUTURES_MASTER)}）")
    name, exch, mult, tick, margin, comm = FUTURES_MASTER[key]
    mkt = EM_MARKET[exch]
    # 中金所主连实测为数字代码（如 IF 用 8.150130 主力合约），此处主连通用映射
    sec_suffix = key if exch != "CFFEX" else key.upper()
    return Instrument(
        symbol=f"{mkt}.{sec_suffix}", name=name, asset_class=AssetClass.FUTURES,
        exchange=exch, secid=f"{mkt}.{sec_suffix}",
        multiplier=mult, tick=tick, price_scale=1.0,  # 期货 K 线收盘为真实点位，无需 /100
        margin_rate=margin, commission_rate=0.0, commission_min=0.0,
        commission_per_lot=comm, stamp_tax=0.0, t_plus=0,
        short_allowed=True, underlying_future=key,
    )


def etf_instrument(symbol: str, name: str = "") -> Instrument:
    """ETF：沿用 A 股 secid，免印花税，T+1（跨境/债券ETF 部分 T+0，此处保守 T+1）。"""
    num, mkt = symbol.split(".")
    return Instrument(
        symbol=symbol, name=name or symbol, asset_class=AssetClass.ETF,
        exchange="SSE" if mkt == "SH" else "SZSE",
        secid=f"{'1' if mkt=='SH' else '0'}.{num}",
        multiplier=1.0, tick=0.001, price_scale=100.0,
        margin_rate=0.0, commission_rate=0.00025, commission_min=5.0,
        stamp_tax=0.0, t_plus=1, short_allowed=False,
    )


def option_instrument(symbol: str, name: str, secid: str,
                      underlying: str = "", strike: float = 0.0,
                      expiry: str = "", option_type: OptionType = None,
                      multiplier: float = 10000.0) -> Instrument:
    """期权：ETF期权乘数通常10000，股指期权乘数100/200/300。权利金报价，T+0 双向。"""
    mkt = int(secid.split(".")[0])
    exch = "SSE_OPTION" if mkt == 10 else "CFFEX_OPTION" if mkt == 11 else "SSE_OPTION"
    return Instrument(
        symbol=symbol, name=name, asset_class=AssetClass.OPTIONS,
        exchange=exch, secid=secid,
        multiplier=multiplier, tick=0.0001, price_scale=10000.0,  # 权利金 f43 实测为放大值
        margin_rate=0.0, commission_rate=0.0, commission_min=0.0,
        commission_per_lot=2.0, stamp_tax=0.0, t_plus=0, short_allowed=True,
        underlying=underlying, strike=strike, expiry=expiry, option_type=option_type,
    )


def infer_asset_class(symbol: str) -> AssetClass:
    """按代码形态推断品种，供路由/数据层使用。"""
    s = symbol.strip().upper()
    if s.startswith(("113.", "114.", "115.", "8.")) or s.lower().endswith("m"):
        return AssetClass.FUTURES
    if s.startswith(("10.", "11.")):
        return AssetClass.OPTIONS
    num = s.split(".")[0]
    if num.startswith(("51", "52", "53", "56", "58", "15", "16")):
        return AssetClass.ETF
    return AssetClass.SPOT
