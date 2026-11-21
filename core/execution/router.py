#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易路由器：按市场把订单路由到对应 Broker。
上层策略引擎只产出 Order 意图，不关心底层是哪个市场哪个柜台。
"""
from .base import Broker, BrokerError, Market, Order, OrderStatus
from .brokers import (QMTBroker, CTPBroker, CTPFuturesBroker, HKStockBroker,
                      ETFBroker, OptionsBroker, ValidateBroker, market_of)


class OrderRouter:
    """统一订单入口。validate_all=True 时全部走校验器（全链路跑通用）。"""
    def __init__(self, brokers: dict = None, validate_all: bool = True):
        self.brokers = brokers or {}
        self.validate_all = validate_all
        self._validator = ValidateBroker()
        # 按市场区分的校验器，保证校验阶段也能标注正确品种
        self._market_validators = {
            m: ValidateBroker(m) for m in Market
        }
        self.history: list = []

    @staticmethod
    def default_brokers(mode: str = "validate", qmt_path: str = "",
                        ctp_front: str = "", ctp_broker: str = "",
                        ctp_account: str = "", ctp_password: str = "") -> dict:
        """构造全市场默认 Broker 注册表（真实网关，未配置则明确拒绝 live）。"""
        return {
            Market.CN_A: QMTBroker(qmt_path, mode) if qmt_path else ValidateBroker(Market.CN_A),
            Market.ETF: ETFBroker(qmt_path, mode),
            Market.CN_FUTURES: CTPFuturesBroker(mode, ctp_front, ctp_broker, ctp_account, ctp_password),
            Market.CN_OPTIONS: OptionsBroker(mode),
            Market.HK: HKStockBroker(mode),
        }

    def register(self, market: Market, broker: Broker):
        self.brokers[market] = broker

    def submit(self, order: Order) -> Order:
        market = order.market or market_of(order.code)
        order.market = market
        if not order.asset_class:
            order.asset_class = market.value
        if self.validate_all:
            broker = self._market_validators.get(market, self._validator)
        else:
            broker = self.brokers.get(market)
            if not broker:
                raise BrokerError(f"市场 {market.value} 未注册 Broker")
            if not order.order_id and hasattr(broker, "trader") and broker.trader is None:
                broker.connect()
        result = broker.place_order(order)
        self.history.append(result.to_dict())
        return result

    def status(self) -> dict:
        return {
            "mode": "VALIDATE(链路校验,不报单)" if self.validate_all else "LIVE(真实报单)",
            "registered_markets": {m.value: type(b).__name__ for m, b in self.brokers.items()},
            "orders_today": len(self.history),
            "recent": self.history[-10:],
        }
