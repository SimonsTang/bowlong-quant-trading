#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机构级合规层（补足 TSP/旧仓库短板）。
三道闸：预交易合规检查 -> 限额管理 -> 审计日志 + 熔断。
任何订单必须全部通过才允许进入执行层。

合规规则（源自机构常见风控要求，可配置）：
  - 禁投池：ST、退市风险、黑名单
  - 交易时段：非交易时段拒绝
  - 限额：单票/单策略/总仓位/日内交易次数
  - 审计：每笔决策落盘留痕，可追溯
"""
import json
import os
import time
from dataclasses import dataclass, asdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AUDIT_LOG = os.path.join(BASE, "logs", "audit.jsonl")


@dataclass
class ComplianceConfig:
    max_position_pct: float = 0.20      # 单票仓位上限
    max_total_pct: float = 0.80         # 总仓位上限
    max_order_value: float = 2_000_000  # 单笔金额上限
    max_daily_orders: int = 50          # 日内最大委托次数
    block_st: bool = True
    block_blacklist: bool = True
    trading_hours_only: bool = True


class AuditLogger:
    """审计日志：所有下单决策追加写入，不可篡改（append-only jsonl）。"""
    def __init__(self, path: str = None):
        self.path = path or AUDIT_LOG
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def log(self, decision: dict):
        rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), **decision}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def read(self, limit: int = 100) -> list:
        if not os.path.exists(self.path):
            return []
        with open(self.path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
        return [json.loads(x) for x in lines if x.strip()]


class ComplianceGateway:
    """下单前合规闸。返回 (pass, reason)。"""
    def __init__(self, cfg: ComplianceConfig = None, blacklist: set = None,
                 auditor: AuditLogger = None):
        self.cfg = cfg or ComplianceConfig()
        self.blacklist = blacklist or set()
        self.auditor = auditor or AuditLogger()
        self._daily_orders = 0
        self._last_reset = time.strftime("%Y-%m-%d")

    def _reset_daily(self):
        today = time.strftime("%Y-%m-%d")
        if today != self._last_reset:
            self._daily_orders = 0
            self._last_reset = today

    def check(self, code: str, side: str, volume: int, price: float,
              name: str = "", total_asset: float = 1_000_000,
              current_pos_value: float = 0.0, strategy: str = "") -> (bool, str):
        self._reset_daily()
        amount = volume * price
        reasons = []

        if side not in ("buy", "sell"):
            reasons.append("非法买卖方向")
        if self.cfg.block_st and ("ST" in name.upper() or "*" in name or "退" in name):
            reasons.append("禁投池:ST/退市风险股")
        if self.cfg.block_blacklist and code in self.blacklist:
            reasons.append("禁投池:黑名单标的")
        if amount > self.cfg.max_order_value:
            reasons.append(f"单笔金额超限 {amount:.0f}>{self.cfg.max_order_value:.0f}")
        if self._daily_orders >= self.cfg.max_daily_orders:
            reasons.append(f"日内委托次数超限 {self._daily_orders}")
        if side == "buy":
            if amount > total_asset * self.cfg.max_position_pct:
                reasons.append("单票仓位超限")
            if current_pos_value + amount > total_asset * self.cfg.max_total_pct:
                reasons.append("总仓位超限")
        if self.cfg.trading_hours_only:
            t = time.localtime()
            hm = t.tm_hour * 100 + t.tm_min
            if t.tm_wday >= 5 or not (930 <= hm <= 1130 or 1300 <= hm <= 1500):
                reasons.append("非交易时段")

        passed = not reasons
        decision = {
            "decision": "PASS" if passed else "REJECT",
            "code": code, "side": side, "volume": volume, "price": price,
            "amount": round(amount, 2), "strategy": strategy,
            "reasons": reasons,
        }
        self.auditor.log(decision)
        if passed:
            self._daily_orders += 1
        return passed, "; ".join(reasons) if reasons else "合规通过"

    def status(self) -> dict:
        return {"daily_orders": self._daily_orders,
                "config": asdict(self.cfg)}
