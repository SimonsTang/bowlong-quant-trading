#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
专业交易终端 Web 后端 - 纯标准库 HTTP 服务，零第三方依赖。
提供：
  - 静态页面 /
  - REST API：行情/K线/策略列表/回测/风控/合规/路由/AI对话
  - SSE 实时日志流 /api/stream：回测与全链路运行的每一步实时推送到前端，
    实现"运行窗口可同步观测"。
"""
import json
import os
import queue
import threading
import time
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

import sys
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.data.resolver import DataResolver
from core.data.enriched import enrich, contract_snapshot
from core.strategy.base import list_strategies, get as get_strategy
from core.research.engine import StrategyEngine, EngineConfig
from core.research.robustness import evaluate_segments
from core.research.guard import StrategyGuard
from core.compliance.compliance import AuditLogger
from core.execution.router import OrderRouter
from core.workflow.pipeline import TeamPipeline
from core.ai.assistant import AIAssistant
from core.ai.tools import dispatch
from core.strategy.selector import MarketSelector, SelectorConfig
from core.strategy.selector_strategies import list_selector_strategies
from core.research.etf_rotation import run_rotation, DEFAULT_POOL

# ETF 轮动结果缓存（避免高频重拉数据触发数据源限流）
_ROT_CACHE = {"ts": 0, "result": None}
_ROT_CACHE_TTL = 3600
from core.research.portfolio import PortfolioEngine, PortfolioConfig
from core.research.optimizer import optimize, OptimizeConfig
from core.workflow.selection_pipeline import SelectionPipeline
from core.config.settings import SETTINGS
from core.multimarket import (
    MM_SOURCE, AssetClass, infer_asset_class, futures_instrument, etf_instrument,
    option_instrument, calc_cost, run_single,
)

WEB = os.path.dirname(os.path.abspath(__file__))
resolver = DataResolver()
guard = StrategyGuard()
auditor = AuditLogger()
router = OrderRouter()


def _etf_inst(code: str):
    num, mkt = code.split(".")
    return etf_instrument(code, f"ETF {num}")


def _opt_inst(code: str):
    """从 secid（如 10.10012850）构造期权 Instrument；详情以列表接口为准。"""
    mkt, num = code.split(".")
    return option_instrument(code, f"期权 {num}", code,
                             underlying="510300", multiplier=10000.0)
assistant = AIAssistant()
compliance_gateway = None  # 由 rebuild_runtime 创建


def rebuild_runtime():
    """按最新配置重建运行时组件，让合规/风控设置热生效。"""
    global compliance_gateway
    from core.compliance.compliance import ComplianceGateway, ComplianceConfig
    cc = SETTINGS.get("compliance")
    blacklist = set(x.strip() for x in str(cc.get("blacklist", "")).split(",") if x.strip())
    compliance_gateway = ComplianceGateway(
        ComplianceConfig(
            max_position_pct=SETTINGS.get("risk", "max_position_pct"),
            max_total_pct=SETTINGS.get("risk", "max_total_pct"),
            max_order_value=cc["max_order_value"],
            max_daily_orders=cc["max_daily_orders"],
            block_st=SETTINGS.get("risk", "block_st"),
            block_blacklist=bool(blacklist),
            trading_hours_only=cc["trading_hours_only"],
        ),
        blacklist=blacklist, auditor=auditor,
    )


rebuild_runtime()

# SSE 事件总线：所有运行日志推到队列，前端订阅
EVENTS: list = []          # 历史事件（供新连接回放）
SUBSCRIBERS: list = []     # 当前订阅者的 queue
EVENT_LOCK = threading.Lock()


LAST_RESULT_FILE = os.path.join(BASE, "reports", "last_result.json")
# 最近一次异步任务结果，供页面刷新后直接读取
LATEST = {"optimize": None, "portfolio": None, "selection_pipeline": None}


def save_last_result(data: dict):
    """结果持久化：最近一次运行结果落盘，刷新页面/重启服务不丢失。"""
    try:
        os.makedirs(os.path.dirname(LAST_RESULT_FILE), exist_ok=True)
        with open(LAST_RESULT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, default=str)
    except Exception:
        pass


def emit(event: dict):
    """发布运行事件，供 UI 实时观测。"""
    rec = {"ts": time.strftime("%H:%M:%S"), **event}
    with EVENT_LOCK:
        EVENTS.append(rec)
        if len(EVENTS) > 500:
            EVENTS.pop(0)
        for q in list(SUBSCRIBERS):
            try:
                q.put_nowait(rec)
            except queue.Full:
                pass
    # 关键结果持久化
    if event.get("type") in ("result", "select_result"):
        payload = event.get("data", {})
        save_last_result({"kind": "pipeline" if event["type"] == "result" else "select",
                          "ts": rec["ts"], "data": payload})


def run_pipeline_async(code, strategy, params, result_holder):
    """后台跑全链路，逐步 emit 事件。"""
    def cb(i, n, msg):
        emit({"type": "progress", "stage": "pipeline", "step": i, "total": n, "msg": msg})
    try:
        emit({"type": "log", "level": "info", "msg": f"启动全链路: {code} / {strategy}"})
        p = TeamPipeline(cb)
        r = p.run(code, strategy, params)
        result_holder["result"] = r.to_dict()
        emit({"type": "result", "data": r.to_dict(),
              "msg": f"全链路完成: {code} / {strategy}"})
    except Exception as e:
        emit({"type": "log", "level": "error", "msg": f"全链路失败: {type(e).__name__}: {e}"})
        result_holder["error"] = str(e)


def run_optimize_async(code, strategy, opt_cfg, eng_cfg):
    def cb(i, n, msg):
        emit({"type": "progress", "stage": "optimize", "step": i, "total": n, "msg": msg})
    try:
        emit({"type": "log", "level": "info",
              "msg": f"启动参数寻优: {code}/{strategy} 组合上限={opt_cfg.max_combinations}"})
        bars = enrich(resolver.kline(code, "1d", "qfq", beg="20200101"))
        out = optimize(bars, strategy, opt_cfg, eng_cfg, code=code, progress_cb=cb)
        LATEST["optimize"] = out
        save_last_result({"kind": "optimize", "ts": time.strftime("%H:%M:%S"),
                          "data": {"code": code, **{k: v for k, v in out.items() if k != "all"}}})
        emit({"type": "optimize_result", "data": out,
              "msg": f"寻优完成: {strategy} 共{out['grid_size']}组，最优 {out['best'].get('params')}"})
    except Exception as e:
        emit({"type": "log", "level": "error", "msg": f"参数寻优失败: {type(e).__name__}: {e}"})


def run_selection_pipeline_async(kwargs):
    def cb(i, n, msg):
        emit({"type": "progress", "stage": "selection_pipeline",
              "step": i, "total": n, "msg": msg})
    try:
        emit({"type": "log", "level": "info",
              "msg": f"启动选股一条龙: {kwargs.get('selector_strategy')} top={kwargs.get('top_n')}"})
        p = SelectionPipeline(cb)
        r = p.run(**kwargs)
        out = r.to_dict()
        LATEST["selection_pipeline"] = out
        save_last_result({"kind": "selection_pipeline", "ts": time.strftime("%H:%M:%S"),
                          "data": out})
        emit({"type": "selection_result", "data": out,
              "msg": f"选股一条龙完成: {len(r.orders)} 笔实盘意图(未报单)"})
    except Exception as e:
        emit({"type": "log", "level": "error",
              "msg": f"选股一条龙失败: {type(e).__name__}: {e}"})


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # 静默访问日志

    def _send(self, code, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, default=str)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)

        if path == "/":
            return self._serve_file(os.path.join(WEB, "index.html"), "text/html; charset=utf-8")
        if path == "/app.js":
            return self._serve_file(os.path.join(WEB, "app.js"), "application/javascript; charset=utf-8")
        if path == "/config.js":
            return self._serve_file(os.path.join(WEB, "config.js"), "application/javascript; charset=utf-8")
        if path == "/style.css":
            return self._serve_file(os.path.join(WEB, "style.css"), "text/css; charset=utf-8")
        if path == "/api/strategies":
            return self._send(200, list_strategies())
        if path == "/api/selector-strategies":
            return self._send(200, list_selector_strategies())
        if path == "/api/quote":
            code = qs.get("code", ["600519"])[0]
            try:
                return self._send(200, resolver.quote(code).to_dict())
            except Exception as e:
                return self._send(200, {"error": str(e)})
        if path == "/api/kline":
            code = qs.get("code", ["600519"])[0]
            period = qs.get("period", ["1d"])[0]
            try:
                # 东财分钟线的 beg 必须早于当前日期，否则返回空；用 lmt 控制数量
                rows = resolver.kline(code, period, "qfq", beg="20200101")
                # 前端支持方向键左右平移，放宽返回窗口到最近1000根（真实数据）
                return self._send(200, {"code": code, "period": period,
                                        "rows": rows[-1000:], "total": len(rows)})
            except Exception as e:
                return self._send(200, {"error": str(e)})
        if path == "/api/valuation":
            code = qs.get("code", ["600519"])[0]
            try:
                return self._send(200, resolver.valuation(code))
            except Exception as e:
                return self._send(200, {"error": str(e)})
        if path == "/api/f10":
            code = qs.get("code", ["600519"])[0]
            try:
                return self._send(200, resolver.f10(code))
            except Exception as e:
                return self._send(200, {"error": str(e)})
        # ---- 多市场品种（ETF/期货/期权）----
        if path == "/api/mm/instruments":
            kind = qs.get("kind", ["futures"])[0]
            try:
                if kind == "etf":
                    rows = MM_SOURCE.list_etfs()
                elif kind == "option":
                    rows = MM_SOURCE.list_options(int(qs.get("market", ["10"])[0]))
                else:
                    rows = MM_SOURCE.list_futures()
                return self._send(200, {"kind": kind, "count": len(rows), "rows": rows[:300]})
            except Exception as e:
                return self._send(200, {"error": str(e)})
        if path == "/api/mm/quote":
            code = qs.get("code", ["510300.SH"])[0]
            try:
                return self._send(200, MM_SOURCE.quote(code).to_dict())
            except Exception as e:
                return self._send(200, {"error": str(e)})
        if path == "/api/mm/kline":
            code = qs.get("code", ["510300.SH"])[0]
            period = qs.get("period", ["1d"])[0]
            try:
                rows = MM_SOURCE.kline(code, period)
                return self._send(200, {"code": code, "period": period,
                                        "rows": rows[-1000:], "total": len(rows)})
            except Exception as e:
                return self._send(200, {"error": str(e)})
        if path == "/api/mm/cost":
            code = qs.get("code", ["510300.SH"])[0]
            try:
                price = float(qs.get("price", ["0"])[0])
                volume = int(qs.get("volume", ["100"])[0])
                ac = infer_asset_class(code)
                inst = (_etf_inst(code) if ac == AssetClass.ETF else
                        _opt_inst(code) if ac == AssetClass.OPTIONS else
                        futures_instrument(code))
                c = calc_cost(inst, price, volume)
                return self._send(200, {"asset_class": ac.value, "name": inst.name,
                                        **c.__dict__})
            except Exception as e:
                return self._send(200, {"error": str(e)})
        if path == "/api/mm/route-status":
            return self._send(200, router.status())
        if path == "/api/risk":
            return self._send(200, {"strategies": guard.status(),
                                    "router": router.status()})
        if path == "/api/compliance":
            return self._send(200, {
                "logs": auditor.read(50) if SETTINGS.get("compliance", "audit_enabled") else [],
                "gateway": compliance_gateway.status() if compliance_gateway else {},
            })
        if path == "/api/events":
            return self._send(200, EVENTS[-100:])
        if path == "/api/last_result":
            if os.path.exists(LAST_RESULT_FILE):
                try:
                    with open(LAST_RESULT_FILE, "r", encoding="utf-8") as f:
                        return self._send(200, json.load(f))
                except Exception:
                    pass
            return self._send(200, {})
        if path == "/api/status":
            return self._send(200, {
                "cloud_ai": assistant.cloud_enabled,
                "model": assistant.model,
                "market_mode": "VALIDATE(校验模式,不产生真实委托)",
                "data_sources": ["eastmoney", "tencent", "sina"],
                "engine_contract": contract_snapshot([])["contract"],
                "strategies": len(list_strategies()),
                "selector": True,
            })
        if path == "/api/config":
            return self._send(200, {
                "values": SETTINGS.all(mask_secret=True),
                "schema": SETTINGS.schema(),
                "status": SETTINGS.status(),
            })
        if path == "/api/optimize/result":
            return self._send(200, LATEST["optimize"] or {})
        if path == "/api/portfolio/result":
            return self._send(200, LATEST["portfolio"] or {})
        if path == "/api/selection-pipeline/result":
            return self._send(200, LATEST["selection_pipeline"] or {})
        if path == "/api/config/status":
            return self._send(200, SETTINGS.status())
        if path == "/api/health":
            """数据源健康监控：逐个探测三源真实连通性。"""
            import time as _t
            health = []
            for name, fn in [
                ("东方财富", lambda: resolver.quote("600519")),
                ("腾讯财经", lambda: __import__("core.data.sources", fromlist=["TX"]).TX.quote("600519")),
                ("新浪财经", lambda: __import__("core.data.sources", fromlist=["SINA"]).SINA.quote("600519")),
            ]:
                t0 = _t.time()
                try:
                    q = fn()
                    health.append({"name": name, "ok": True,
                                   "latency_ms": int((_t.time() - t0) * 1000),
                                   "price": q.price, "source": q.source})
                except Exception as e:
                    health.append({"name": name, "ok": False, "error": str(e)[:80]})
            return self._send(200, {"checked_at": _t.strftime("%H:%M:%S"), "sources": health})
        if path == "/api/stream":
            return self._sse()
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        data_bytes = self.rfile.read(length) if length else b"{}"
        # 健壮解码：优先 UTF-8，容错 GBK（兼容 Windows 终端 curl 等客户端）
        try:
            raw = data_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raw = data_bytes.decode("gbk", "ignore")
        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            body = {}

        if path == "/api/config":
            """保存配置（支持单组或全量），并热更新到运行中的组件。"""
            values = body.get("values", {})
            try:
                changed = []
                for group, items in values.items():
                    if isinstance(items, dict):
                        # 跳过脱敏占位值（用户未修改的密钥），防止把 sk-****def 写回覆盖真值
                        secret_keys = {k for k, sp in SETTINGS.schema().get(group, {}).items()
                                       if sp.get("secret")}
                        clean = {k: v for k, v in items.items()
                                 if not (isinstance(v, str) and v and
                                         ((set(v) <= set("*")) or
                                          (k in secret_keys and "*" in v)))}
                        validated = SETTINGS.update(group, clean)
                        changed.append(group)
                # 热更新：让运行中的组件立即生效
                assistant.refresh()
                resolver.refresh_config()
                # 风控/合规/执行器按新配置重建
                rebuild_runtime()
                emit({"type": "log", "level": "ok",
                      "msg": f"配置已保存并热更新: {', '.join(changed)}"})
                return self._send(200, {"ok": True, "updated": changed,
                                        "status": SETTINGS.status()})
            except Exception as e:
                emit({"type": "log", "level": "error", "msg": f"配置保存失败: {e}"})
                return self._send(200, {"ok": False, "error": str(e)})

        if path == "/api/config/test":
            """测试AI云端连接：临时用提交的凭证测试，不污染已保存配置。"""
            test_cfg = body.get("config", {})
            try:
                from core.ai.assistant import AIAssistant
                probe = AIAssistant(
                    api_key=test_cfg.get("api_key", ""),
                    base_url=test_cfg.get("base_url", ""),
                    model=test_cfg.get("model", ""),
                )
                # 若前端传的是脱敏值，则用已保存的真实值测试
                if test_cfg.get("api_key") and "*" in test_cfg["api_key"]:
                    probe = AIAssistant()  # 用配置中心真实值
                result = probe.test_connection()
                return self._send(200, result)
            except Exception as e:
                return self._send(200, {"ok": False, "error": str(e)})

        if path == "/api/config/reset":
            SETTINGS.reset()
            assistant.refresh()
            resolver.refresh_config()
            rebuild_runtime()
            emit({"type": "log", "level": "info", "msg": "配置已恢复默认值"})
            return self._send(200, {"ok": True, "values": SETTINGS.all(mask_secret=True)})

        if path == "/api/backtest":
            code = body.get("code", "600519")
            strategy = body.get("strategy", "dual_ma")
            params = body.get("params", {})
            try:
                def cb(i, n, msg):
                    emit({"type": "progress", "stage": "backtest", "step": i, "total": n, "msg": msg})
                emit({"type": "log", "level": "info", "msg": f"开始回测 {code}/{strategy}"})
                rows = resolver.kline(code, "1d", "qfq", beg="20200101")
                bars = enrich(rows)
                contract = contract_snapshot(bars)
                st = get_strategy(strategy, **params)
                eng = StrategyEngine(EngineConfig(), cb)
                r = eng.run_on_bars(bars, st.signal_fn(), code, strategy, contract)
                guard.update(strategy, r.equity[-1], r.summary.get("net_pnl"))
                payload = {
                    "summary": r.summary, "contract": contract,
                    "equity": [round(x, 2) for x in r.equity[::max(1, len(r.equity)//200)]],
                    "trades": [t.__dict__ for t in r.trades[-40:]],
                    "kline": [{"date": b["date"], "close": b["close"]}
                              for b in bars[::max(1, len(bars)//200)]],
                }
                emit({"type": "log", "level": "ok", "msg": f"回测完成 收益={r.summary['total_return']:.2%}"})
                save_last_result({"kind": "backtest", "ts": time.strftime("%H:%M:%S"),
                                  "data": {"code": code, "strategy": strategy, **payload}})
                return self._send(200, payload)
            except Exception as e:
                emit({"type": "log", "level": "error", "msg": f"回测失败: {e}"})
                return self._send(200, {"error": str(e)})

        if path == "/api/select":
            """全市场选股：真实数据闭环，异步执行避免阻塞。支持策略切换。"""
            strategy = body.get("strategy", "multi_factor")
            top_n = int(body.get("top_n", 10))
            momentum_fetch_n = int(body.get("momentum_fetch_n", 60))
            max_pe = float(body.get("max_pe", 60))  # 兼容旧客户端；实际阈值由策略参数决定
            min_amount = float(body.get("min_amount", 1e8))
            if min_amount < 1e5:  # 前端以"亿"为单位传入
                min_amount *= 1e8
            sp = body.get("strategy_params") or {}
            if not isinstance(sp, dict):
                return self._send(400, {"error": "strategy_params 必须是对象"})
            def run():
                def cb(i, n, msg):
                    emit({"type": "progress", "stage": "select", "step": i,
                          "total": n, "msg": f"选股·{msg} {i}/{n}"})
                try:
                    emit({"type": "select_start", "strategy": strategy,
                          "msg": f"启动全市场选股 [{strategy}] top_n={top_n} 策略参数={sp}"})
                    sel = MarketSelector(SelectorConfig(
                        top_n=top_n, momentum_fetch_n=momentum_fetch_n,
                        max_pe=max_pe, min_amount=min_amount),
                        strategy=strategy, strategy_params=sp)
                    r = sel.select(cb)
                    payload = {**r.to_dict(), "weights": sel.target_weights(r)}
                    emit({"type": "select_result", "data": payload,
                          "msg": f"[{strategy}] 选股完成: {len(r.picks)}只 / 全市场 {r.universe_size}"})
                except Exception as e:
                    # 明确失败事件：前端据此停止进度条并显示错误，而不是静默卡住
                    emit({"type": "select_error", "strategy": strategy,
                          "error": f"{type(e).__name__}: {e}",
                          "msg": f"选股失败 [{strategy}]: {e}"})
            threading.Thread(target=run, daemon=True).start()
            return self._send(200, {"started": True, "msg": "全市场选股已启动"})

        if path == "/api/compare":
            """多策略对比：同一标的跑多个策略，并列绩效。"""
            code = body.get("code", "600519")
            names = body.get("strategies", [])
            if not names:
                names = [s["name"] for s in list_strategies()[:8]]
            out = []
            for name in names:
                try:
                    rows = resolver.kline(code, "1d", "qfq", beg="20200101")
                    bars = enrich(rows)
                    st = get_strategy(name)
                    eng = StrategyEngine(EngineConfig())
                    r = eng.run_on_bars(bars, st.signal_fn(), code, name,
                                        contract_snapshot(bars))
                    out.append({"strategy": name, "display": st.display,
                                "summary": r.summary,
                                "equity": [round(x, 2) for x in r.equity[::max(1, len(r.equity)//100)]],
                                "params": st.param_dict()})
                    emit({"type": "log", "level": "info", "msg": f"对比完成: {name}"})
                except Exception as e:
                    out.append({"strategy": name, "error": str(e)})
            out.sort(key=lambda x: x.get("summary", {}).get("sharpe", -999), reverse=True)
            save_last_result({"kind": "compare", "ts": time.strftime("%H:%M:%S"),
                              "data": {"code": code, "results": out}})
            return self._send(200, {"code": code, "results": out})

        if path == "/api/robustness":
            code = body.get("code", "600519")
            strategy = body.get("strategy", "dual_ma")
            params = body.get("params") or {}
            try:
                rows = resolver.kline(code, "1d", "qfq", beg="20200101")
                bars = enrich(rows)
                def cb(i, n, msg):
                    emit({"type": "progress", "stage": "robustness", "step": i, "total": n, "msg": msg})
                rb = evaluate_segments(bars,
                        lambda: get_strategy(strategy, **params).signal_fn(),
                        StrategyEngine, EngineConfig(), k=5, progress_cb=cb)
                return self._send(200, rb)
            except Exception as e:
                return self._send(200, {"error": str(e)})

        if path == "/api/pipeline":
            code = body.get("code", "600519")
            strategy = body.get("strategy", "dual_ma")
            params = body.get("params", {})
            holder = {}
            t = threading.Thread(target=run_pipeline_async,
                                 args=(code, strategy, params, holder), daemon=True)
            t.start()
            return self._send(200, {"started": True, "msg": "全链路已启动，请观察实时日志"})

        if path == "/api/portfolio":
            """多标的组合回测：真实K线 + 选股权重/等权 + 再平衡 + 真实成本。"""
            codes = [x.strip() for x in str(body.get("codes", "")).replace("，", ",").split(",")
                     if x.strip()]
            if len(codes) < 2:
                return self._send(200, {"error": "组合回测至少需要2个标的，用逗号分隔"})
            strategy = body.get("strategy", "dual_ma")
            signal_mode = body.get("signal_mode", "strategy")
            rebalance = body.get("rebalance", "monthly")
            raw_w = body.get("weights") or {}
            try:
                emit({"type": "log", "level": "info",
                      "msg": f"启动组合回测: {len(codes)}只 / {signal_mode} / {rebalance}"})
                bars, contracts = {}, {}
                for c in codes:
                    bars[c] = enrich(resolver.kline(c, "1d", "qfq", beg="20200101"))
                    contracts[c] = contract_snapshot(bars[c])
                weights = None
                if signal_mode == "weights" and raw_w:
                    weights = {c: float(raw_w.get(c, 0)) for c in codes}
                pcfg = PortfolioConfig(
                    initial_cash=SETTINGS.get("backtest", "initial_cash"),
                    slippage=SETTINGS.get("backtest", "slippage"),
                    max_weight=SETTINGS.get("risk", "max_position_pct"),
                    max_total_weight=SETTINGS.get("risk", "max_total_pct"),
                    rebalance=rebalance, signal_mode=signal_mode)
                def cb(i, n, msg):
                    emit({"type": "progress", "stage": "portfolio",
                          "step": i, "total": n, "msg": msg})
                r = PortfolioEngine(pcfg, cb).run(bars, strategies={c: strategy for c in codes},
                                                  contracts=contracts, weights=weights)
                out = r.to_dict()
                LATEST["portfolio"] = out
                save_last_result({"kind": "portfolio", "ts": time.strftime("%H:%M:%S"),
                                  "data": out})
                emit({"type": "combo_result", "data": out,
                      "msg": f"组合回测完成: 收益={r.summary['total_return']:.2%} "
                             f"回撤={r.summary['max_drawdown']:.2%}"})
                return self._send(200, out)
            except Exception as e:
                emit({"type": "log", "level": "error", "msg": f"组合回测失败: {e}"})
                return self._send(200, {"error": str(e)})

        if path == "/api/optimize":
            """参数自动寻优：网格 + K段折外稳健分排序，异步执行。"""
            code = body.get("code", "600519")
            strategy = body.get("strategy", "dual_ma")
            try:
                oc = OptimizeConfig(
                    k=int(body.get("k", 5)),
                    max_combinations=int(body.get("max_combinations", 40)),
                    top_n=int(body.get("top_n", 10)),
                    objective=body.get("objective", "robustness"))
                ec = EngineConfig(
                    initial_cash=SETTINGS.get("backtest", "initial_cash"),
                    slippage=SETTINGS.get("backtest", "slippage"))
                threading.Thread(target=run_optimize_async,
                                 args=(code, strategy, oc, ec), daemon=True).start()
                return self._send(200, {"started": True,
                                        "msg": "参数寻优已启动，请观察实时日志"})
            except Exception as e:
                return self._send(200, {"error": str(e)})

        if path == "/api/selection-pipeline":
            """选股一条龙：选股→组合回测→风控→合规→实盘意图，异步执行。"""
            try:
                kwargs = {
                    "selector_strategy": body.get("selector_strategy", "multi_factor"),
                    "top_n": int(body.get("top_n", 10)),
                    "rebalance": body.get("rebalance", "monthly"),
                    "momentum_fetch_n": int(body.get("momentum_fetch_n", 60)),
                    "min_amount_yi": float(body.get("min_amount_yi", 1.0)),
                    "live": False,
                    "preset_selection": body.get("selection") or None,
                }
                threading.Thread(target=run_selection_pipeline_async,
                                 args=(kwargs,), daemon=True).start()
                return self._send(200, {"started": True,
                                        "msg": "选股一条龙已启动，请观察实时日志"})
            except Exception as e:
                return self._send(200, {"error": str(e)})

        if path == "/api/mm/backtest":
            try:
                code = body.get("code", "510300.SH")
                strategy = body.get("strategy", "ma_cross")
                fast = int(body.get("fast", 5)); slow = int(body.get("slow", 20))
                cash = float(body.get("cash", 1_000_000))
                ac = infer_asset_class(code)
                inst = (_etf_inst(code) if ac == AssetClass.ETF else
                        _opt_inst(code) if ac == AssetClass.OPTIONS else
                        futures_instrument(code))
                bars = MM_SOURCE.kline(inst.secid, "1d")

                def signal_fn(series, i):
                    if len(series) < slow + 1:
                        return "HOLD"
                    c = [b["close"] for b in series]
                    f_now, s_now = sum(c[-fast:]) / fast, sum(c[-slow:]) / slow
                    f_prev, s_prev = sum(c[-fast-1:-1]) / fast, sum(c[-slow-1:-1]) / slow
                    if f_prev <= s_prev and f_now > s_now:
                        return "BUY"
                    if f_prev >= s_prev and f_now < s_now:
                        return "SELL"
                    return "HOLD"

                r = run_single(inst, bars, signal_fn, initial_cash=cash)
                return self._send(200, {
                    "symbol": code, "name": inst.name, "asset_class": ac.value,
                    "bars": len(bars), "total_return": r.total_return,
                    "max_drawdown": r.max_drawdown, "final_equity": r.final_equity,
                    "trades": len(r.trades), "notes": r.notes,
                })
            except Exception as e:
                return self._send(200, {"error": str(e)})

        if path == "/api/etf-rotation":
            """宽基/大类资产 ETF 动量轮动（实测有效策略）。结果缓存1小时，避免限流。"""
            try:
                lookback = int(body.get("lookback", 22))
                buffer = float(body.get("buffer", 0.0))
                force = bool(body.get("force", False))
                ck = (lookback, buffer)
                if (not force and _ROT_CACHE["result"] is not None
                        and time.time() - _ROT_CACHE["ts"] < _ROT_CACHE_TTL
                        and _ROT_CACHE.get("key") == ck):
                    r = _ROT_CACHE["result"]
                else:
                    r = run_rotation(lookback=lookback, buffer=buffer)
                    _ROT_CACHE.update(ts=time.time(), result=r, key=ck)
                return self._send(200, {
                    "summary": r.summary,
                    "buy_hold": r.buy_hold,
                    "equity": r.equity,
                    "dates": r.dates,
                    "grid": r.grid,
                    "pool": r.summary.get("pool", DEFAULT_POOL),
                    "note": "缓存1小时；强制刷新可传 force=true（受数据源限流约束）",
                })
            except Exception as e:
                return self._send(200, {"error": str(e)})

        if path == "/ai/chat":
            q = body.get("question", "")
            result = assistant.ask(q)
            return self._send(200, result)

        if path == "/ai/tool":
            name = body.get("tool", "")
            args = body.get("args", {})
            return self._send(200, {"result": dispatch(name, args)})

        return self._send(404, {"error": "not found"})

    def _sse(self):
        """Server-Sent Events：实时推送运行日志到前端。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        q = queue.Queue(maxsize=200)
        with EVENT_LOCK:
            SUBSCRIBERS.append(q)
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    rec = q.get(timeout=15)
                    payload = json.dumps(rec, ensure_ascii=False, default=str)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with EVENT_LOCK:
                if q in SUBSCRIBERS:
                    SUBSCRIBERS.remove(q)

    def _serve_file(self, path, ctype):
        if not os.path.exists(path):
            return self._send(404, {"error": f"missing {path}"})
        with open(path, "rb") as f:
            return self._send(200, f.read(), ctype)


def main():
    port = int(os.environ.get("QIAO_PORT", 8765))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"[巧未来-波龙量化] Web终端已启动: http://127.0.0.1:{port}")
    print(f"  引擎口径: {contract_snapshot([])['contract']} | AI云端: {'已配置' if assistant.cloud_enabled else '本地降级'}")
    print("  按 Ctrl+C 停止")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        srv.shutdown()


if __name__ == "__main__":
    main()
