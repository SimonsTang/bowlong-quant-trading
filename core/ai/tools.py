#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 助手工具集：把系统能力暴露成结构化工具，供云端 LLM 通过 function-call 调用。
同时提供无 LLM 时的直接调用入口，保证无 Key 也能跑通（降级为命令式）。

工具：
  get_quote      查实时行情（真实源）
  get_kline      查历史K线（真实源）
  list_strategies 列出可选策略
  run_backtest   用指定策略跑真实数据回测
  risk_status    查风控与策略守护状态
  compliance_log 查合规审计日志
  router_status  查执行路由状态
"""
import json

from ..data.resolver import DataResolver
from ..data.enriched import enrich, contract_snapshot
from ..strategy.base import get as get_strategy, list_strategies as _list
from ..research.engine import StrategyEngine, EngineConfig
from ..research.guard import StrategyGuard
from ..compliance.compliance import AuditLogger
from ..execution.router import OrderRouter

_resolver = DataResolver()
_guard = StrategyGuard()
_auditor = AuditLogger()
_router = OrderRouter()


# OpenAI function-calling 风格的工具定义
TOOL_SPECS = [
    {"name": "get_quote", "description": "查询A股实时行情快照(真实数据源)",
     "parameters": {"type": "object", "properties": {"code": {"type": "string", "description": "股票代码如600519"}}, "required": ["code"]}},
    {"name": "get_kline", "description": "查询A股历史日K线(真实数据,前复权)",
     "parameters": {"type": "object", "properties": {"code": {"type": "string"}, "days": {"type": "integer", "default": 120}}, "required": ["code"]}},
    {"name": "list_strategies", "description": "列出所有可切换的量化策略及其参数",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "run_backtest", "description": "用指定策略在真实历史上回测,返回绩效指标",
     "parameters": {"type": "object", "properties": {
         "code": {"type": "string"}, "strategy": {"type": "string"},
         "params": {"type": "object", "default": {}}}, "required": ["code", "strategy"]}},
    {"name": "risk_status", "description": "查询策略健康状态与风控熔断状态",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "compliance_log", "description": "查询最近的合规审计日志",
     "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "default": 10}}}},
    {"name": "router_status", "description": "查询执行路由与当日委托状态",
     "parameters": {"type": "object", "properties": {}}},
]


def get_quote(code: str) -> dict:
    q = _resolver.quote(code)
    return q.to_dict()


def get_kline(code: str, days: int = 120) -> dict:
    rows = _resolver.kline(code, "1d", "qfq", beg="20200101")
    return {"code": code, "count": len(rows), "recent": rows[-days:]}


def list_strategies() -> list:
    return _list()


def run_backtest(code: str, strategy: str, params: dict = None) -> dict:
    rows = _resolver.kline(code, "1d", "qfq", beg="20200101")
    bars = enrich(rows)
    st = get_strategy(strategy, **(params or {}))
    eng = StrategyEngine(EngineConfig())
    r = eng.run_on_bars(bars, st.signal_fn(), code=code, strategy=strategy,
                        contract=contract_snapshot(bars))
    return {"code": code, "strategy": strategy, "summary": r.summary,
            "contract": r.contract, "params": st.param_dict()}


def risk_status() -> dict:
    return {"strategies": _guard.status(), "circuit_breakers": "见风控网关状态"}


def compliance_log(limit: int = 10) -> list:
    return _auditor.read(limit)


def router_status() -> dict:
    return _router.status()


def dispatch(name: str, args: dict) -> str:
    """工具分发：返回 JSON 字符串供 LLM 消费。"""
    funcs = {
        "get_quote": get_quote, "get_kline": get_kline,
        "list_strategies": list_strategies, "run_backtest": run_backtest,
        "risk_status": risk_status, "compliance_log": compliance_log,
        "router_status": router_status,
    }
    if name not in funcs:
        return json.dumps({"error": f"未知工具 {name}"}, ensure_ascii=False)
    try:
        result = funcs[name](**args)
        return json.dumps(result, ensure_ascii=False, default=str)[:8000]
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)
