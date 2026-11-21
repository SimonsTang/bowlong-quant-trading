#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一交易领域模型与 Broker 抽象（补足多市场多品种短板的关键）。
借鉴 vnpy 的网关思想：上层只认统一 Order/Account，底层可插拔
A股QMT / 期货CTP / 港股 等网关，切换市场不改上层代码。

严格边界（修复旧仓库致命缺陷）：
  - mode=validate 只校验不报单；mode=live 才真实下单，且必须显式
  - 连接失败一律抛 BrokerError，绝不静默降级到模拟
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class Market(str, Enum):
    CN_A = "CN_A"       # A股
    ETF = "ETF"         # 场内基金（ETF/LOF）
    CN_FUTURES = "CN_FUTURES"  # 国内期货
    CN_OPTIONS = "CN_OPTIONS"  # 场内期权（ETF期权/股指期权）
    HK = "HK"           # 港股


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    FILLED = "FILLED"
    VALIDATED_ONLY = "VALIDATED_ONLY"


@dataclass
class Order:
    code: str
    side: str            # buy/sell（期货/期权用 open/close 也可用 side 表达方向）
    volume: int
    price: float = 0.0
    market: Market = Market.CN_A
    strategy: str = ""
    status: OrderStatus = OrderStatus.PENDING
    order_id: str = ""
    note: str = ""
    timestamp: str = ""
    offset: str = ""     # 期货/期权开平：open/close/closetoday
    asset_class: str = ""  # SPOT/ETF/FUTURES/OPTIONS

    def to_dict(self):
        return {
            "code": self.code, "side": self.side, "volume": self.volume,
            "price": self.price, "market": self.market.value,
            "strategy": self.strategy, "status": self.status.value,
            "order_id": self.order_id, "note": self.note, "timestamp": self.timestamp,
            "offset": self.offset, "asset_class": self.asset_class,
        }


class BrokerError(Exception):
    pass


class Broker(ABC):
    """统一网关接口。所有市场适配器实现此接口。"""
    market: Market = Market.CN_A

    @abstractmethod
    def connect(self) -> bool: ...

    @abstractmethod
    def query_asset(self, account: str = "") -> dict: ...

    @abstractmethod
    def place_order(self, order: Order) -> Order: ...

    @abstractmethod
    def cancel_order(self, account: str, order_id: str) -> bool: ...
