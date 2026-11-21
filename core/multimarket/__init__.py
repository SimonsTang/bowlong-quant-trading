#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多市场品种模块：期货 / 期权 / ETF 真实数据、品种规格、成本、执行。"""
from .instruments import (
    AssetClass, OptionType, Instrument, FUTURES_MASTER, EM_MARKET,
    futures_instrument, etf_instrument, option_instrument, infer_asset_class,
)
from .data import MM_SOURCE, MultiMarketSource, MMQuote, MultiMarketDataError
from .costs import calc_cost, TradeCost, lot_size, round_lot, t_plus, price_limit
from .backtest import run_single, MMResult, MMTrade

__all__ = [
    "AssetClass", "OptionType", "Instrument", "FUTURES_MASTER", "EM_MARKET",
    "futures_instrument", "etf_instrument", "option_instrument", "infer_asset_class",
    "MM_SOURCE", "MultiMarketSource", "MMQuote", "MultiMarketDataError",
    "calc_cost", "TradeCost", "lot_size", "round_lot", "t_plus", "price_limit",
    "run_single", "MMResult", "MMTrade",
]
