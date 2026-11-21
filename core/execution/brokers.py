#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多市场 Broker 适配器：
  - QMTBroker: A股，迅投官方 xtquant（真实下单）
  - CTPBroker: 国内期货，上期所 CTP（预留真实接口，未装库时明确拒绝）
  - HKBroker: 港股，预留（需券商API）
  - ValidateBroker: 全市场通用链路校验器，只校验不报单，用于全链路跑通

所有真实网关连接失败一律抛错，绝不静默转模拟。
"""
import time
from .base import Broker, BrokerError, Order, OrderStatus, Market


class QMTBroker(Broker):
    """A股实盘：迅投官方 xtquant SDK + miniQMT。pip install xtquant。"""
    market = Market.CN_A

    def __init__(self, qmt_path: str, mode: str = "validate"):
        if mode not in ("live", "validate"):
            raise BrokerError("mode 必须是 live 或 validate")
        self.mode, self.qmt_path = mode, qmt_path
        self.trader = None
        self.account = None

    def connect(self) -> bool:
        try:
            from xtquant.xttrader import XtQuantTrader
        except ImportError:
            raise BrokerError("未安装 xtquant，pip install xtquant（需券商miniQMT权限）")
        try:
            self.trader = XtQuantTrader(self.qmt_path, int(time.time()) % 1000000)
            self.trader.start()
            if self.trader.connect() != 0:
                raise BrokerError("无法连接 miniQMT，请确认已登录独立交易模式")
            return True
        except BrokerError:
            raise
        except Exception as e:
            raise BrokerError(f"QMT连接失败: {e}")

    def bind_account(self, account_id: str):
        from xtquant.xttype import StockAccount
        self.account = StockAccount(account_id, "STOCK")

    def query_asset(self, account: str = "") -> dict:
        if not self.trader or not self.account:
            raise BrokerError("请先 connect + bind_account")
        r = self.trader.query_stock_asset(self.account)
        return {"total": r.total_asset, "cash": r.cash,
                "market_value": r.market_value, "source": "QMT真实账户"}

    def place_order(self, order: Order) -> Order:
        if self.mode == "validate":
            order.status = OrderStatus.VALIDATED_ONLY
            order.note = "校验模式，未产生真实委托"
            order.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            return order
        if not self.trader or not self.account:
            raise BrokerError("实盘下单前必须 connect + bind_account")
        from xtquant import xtconstant
        ot = xtconstant.STOCK_BUY if order.side == "buy" else xtconstant.STOCK_SELL
        pt = xtconstant.FIX_PRICE if order.price > 0 else xtconstant.MARKET_PRICE
        oid = self.trader.order_stock(self.account, order.code, ot, order.volume,
                                      pt, order.price, "qiaoweilai")
        if not oid:
            raise BrokerError("下单失败，未返回委托号")
        order.status, order.order_id = OrderStatus.SUBMITTED, str(oid)
        order.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        return order

    def cancel_order(self, account: str, order_id: str) -> bool:
        if self.mode == "validate":
            return True
        return self.trader.cancel_order_stock(self.account, int(order_id)) == 0


class CTPBroker(Broker):
    """国内期货：CTP 网关（vnpy 同源思想）。需 pip install vnpy_ctp 与柜台权限。
    未安装依赖时明确拒绝，不伪造成交。"""
    market = Market.CN_FUTURES

    def __init__(self, mode: str = "validate"):
        if mode not in ("live", "validate"):
            raise BrokerError("mode 必须是 live 或 validate")
        self.mode = mode
        self.api = None

    def connect(self) -> bool:
        try:
            import vnpy_ctp  # noqa: F401
        except ImportError:
            raise BrokerError("未安装 vnpy_ctp，pip install vnpy_ctp（需期货CTP柜台权限）")
        if self.mode == "validate":
            return True
        raise BrokerError("CTP实盘需配置柜台参数(Front/Broker/Account/Password)，请在config中填写后再连")

    def query_asset(self, account: str = "") -> dict:
        raise BrokerError("CTP账户查询需柜台连接，validate模式不提供")
        return {}

    def place_order(self, order: Order) -> Order:
        if self.mode == "validate":
            order.status = OrderStatus.VALIDATED_ONLY
            order.note = "CTP校验模式，未报单"
            return order
        raise BrokerError("CTP实盘下单未启用")

    def cancel_order(self, account: str, order_id: str) -> bool:
        return self.mode == "validate"


class HKStockBroker(Broker):
    """港股：预留适配器。需接券商 OpenAPI（如富途/老虎），此处明确标注未实现边界。"""
    market = Market.HK

    def __init__(self, mode: str = "validate"):
        self.mode = mode

    def connect(self) -> bool:
        raise BrokerError("港股实盘需券商OpenAPI凭证，当前版本仅提供接口占位，不伪造成交")

    def query_asset(self, account: str = "") -> dict:
        raise BrokerError("港股账户不可用")

    def place_order(self, order: Order) -> Order:
        order.status = OrderStatus.REJECTED
        order.note = "港股实盘未接入，需券商API"
        return order

    def cancel_order(self, account: str, order_id: str) -> bool:
        return False


class ValidateBroker(Broker):
    """全市场通用校验器：走完整下单链路但不产生真实委托。
    用于全链路跑通与UI演示，行为明确标注，绝不冒充真实成交。"""
    market = Market.CN_A

    def __init__(self, market: Market = Market.CN_A):
        self.market = market

    def connect(self) -> bool:
        return True

    def query_asset(self, account: str = "") -> dict:
        return {"total": 1_000_000, "cash": 1_000_000,
                "market_value": 0, "source": "链路校验(非真实账户)"}

    def place_order(self, order: Order) -> Order:
        order.status = OrderStatus.VALIDATED_ONLY
        order.note = "链路校验通过，未产生真实委托"
        order.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        return order

    def cancel_order(self, account: str, order_id: str) -> bool:
        return True


class ETFBroker(Broker):
    """ETF：走券商股票通道（xtquant 与 A 股同源，ETF 即为场内基金份额）。
    未配置真实通道时只做链路校验，绝不伪造。"""
    market = Market.ETF

    def __init__(self, qmt_path: str = "", mode: str = "validate"):
        if mode not in ("live", "validate"):
            raise BrokerError("mode 必须是 live 或 validate")
        self.mode, self.qmt_path = mode, qmt_path
        self._inner = QMTBroker(qmt_path, mode) if qmt_path else None

    def connect(self) -> bool:
        if self.mode == "validate":
            return True
        if not self._inner:
            raise BrokerError("ETF live 模式需配置 qmt_path（券商通道）")
        return self._inner.connect()

    def query_asset(self, account: str = "") -> dict:
        if self.mode == "validate" or not self._inner:
            return {"source": "ETF链路校验(非真实账户)", "total": 0, "cash": 0}
        return self._inner.query_asset(account)

    def place_order(self, order: Order) -> Order:
        if self.mode == "validate":
            order.status = OrderStatus.VALIDATED_ONLY
            order.note = "ETF校验模式，未报单（ETF免印花税/T+1）"
            order.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            return order
        if not self._inner:
            raise BrokerError("ETF live 未配置券商通道")
        return self._inner.place_order(order)

    def cancel_order(self, account: str, order_id: str) -> bool:
        return self.mode == "validate" or bool(self._inner and self._inner.cancel_order(account, order_id))


class CTPFuturesBroker(CTPBroker):
    """期货 CTP 真实网关（继承 CTPBroker 边界）。mode=live 必须带齐柜台参数，
    否则抛错；未装 vnpy_ctp 明确拒绝。绝不静默模拟。"""
    market = Market.CN_FUTURES

    def __init__(self, mode: str = "validate", front: str = "", broker_id: str = "",
                 account: str = "", password: str = ""):
        super().__init__(mode)
        self.front, self.broker_id = front, broker_id
        self.account, self.password = account, password

    def connect(self) -> bool:
        try:
            import vnpy_ctp  # noqa: F401
        except ImportError:
            raise BrokerError("未安装 vnpy_ctp，pip install vnpy_ctp（需期货CTP柜台权限）")
        if self.mode == "validate":
            return True
        if not all([self.front, self.broker_id, self.account, self.password]):
            raise BrokerError("CTP live 需 front/broker_id/account/password 完整配置")
        # 真实网关创建在此：vnpy_ctp.api.CtpTdApi + 登录。本环境无柜台，不伪造。
        raise BrokerError("CTP 真实柜台连接需在具备期货账户的环境完成，当前不伪造成交")

    def place_order(self, order: Order) -> Order:
        if self.mode == "validate":
            order.status = OrderStatus.VALIDATED_ONLY
            order.note = f"期货校验模式，未报单（{order.offset or 'open'} {order.volume}手）"
            order.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            return order
        raise BrokerError("CTP 实盘下单未启用")


class OptionsBroker(Broker):
    """期权：ETF期权走券商期权通道（如 xtquant 期权/CTP 期权），股指期权走 CTP 期权。
    当前环境无真实期权账户，validate 只校验；live 明确要求配置真实通道。"""
    market = Market.CN_OPTIONS

    def __init__(self, mode: str = "validate", channel: str = ""):
        if mode not in ("live", "validate"):
            raise BrokerError("mode 必须是 live 或 validate")
        self.mode, self.channel = mode, channel

    def connect(self) -> bool:
        if self.mode == "validate":
            return True
        raise BrokerError("期权 live 需配置券商期权通道并装入对应SDK，当前不伪造成交")

    def query_asset(self, account: str = "") -> dict:
        if self.mode == "validate":
            return {"source": "期权链路校验(非真实账户)", "total": 0, "cash": 0}
        raise BrokerError("期权账户查询需真实通道")

    def place_order(self, order: Order) -> Order:
        if self.mode == "validate":
            order.status = OrderStatus.VALIDATED_ONLY
            order.note = f"期权校验模式，未报单（{order.offset or 'open'} {order.volume}张，权利金{order.price}）"
            order.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            return order
        raise BrokerError("期权实盘下单未启用")

    def cancel_order(self, account: str, order_id: str) -> bool:
        return self.mode == "validate"


# 按代码推断市场（扩展 ETF/期货/期权）
def market_of(code: str) -> Market:
    """按代码或 secid 推断市场，供路由器使用。"""
    c = code.strip().upper()
    # 东财 secid 形态：113/114/115/8=期货，10/11=期权，1/0=股票或ETF
    if c.startswith(("113.", "114.", "115.", "8.")):
        return Market.CN_FUTURES
    if c.startswith(("10.", "11.")):
        return Market.CN_OPTIONS
    if c.endswith(".HK") or (c.isdigit() and len(c) == 5):
        return Market.HK
    if c.endswith(".SHF") or c.endswith(".DCE") or c.endswith(".CZC") or "-" in c:
        return Market.CN_FUTURES
    num = c.split(".")[0]
    if num.startswith(("51", "52", "53", "56", "58", "15", "16")):
        return Market.ETF
    return Market.CN_A
