#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
选股一条龙：选股 → 自动组合回测 → 稳健检验 → 风控 → 合规 → 实盘意图 → AI复盘。

与 TeamPipeline（单标的全链路）互补：
  TeamPipeline        = 研究视角，一个标的 + 一个交易策略
  SelectionPipeline   = 组合视角，全市场选股结果 + 组合级验证 + 委托意图

安全边界：
  - 本管线**只生成实盘意图**，所有委托统一走 ValidateBroker，绝不真实报单
  - 真实报单只能通过 scripts/verify_qmt_paper.py 在券商模拟账号上显式执行
  - 非交易时段合规闸会拒绝，链路仍完整跑完并明确标注原因
"""
import time
from dataclasses import dataclass, field
from typing import Callable

from ..config.settings import SETTINGS
from ..data.resolver import DataResolver
from ..data.enriched import enrich, contract_snapshot
from ..strategy.selector import MarketSelector, SelectorConfig, Pick, SelectionResult
from ..research.portfolio import PortfolioEngine, PortfolioConfig
from ..research.robustness import k_fold_segments, robustness_score
from ..research.guard import StrategyGuard
from ..risk.risk import RiskGateway, RiskConfig, DrawdownCircuitBreaker
from ..compliance.compliance import ComplianceGateway, ComplianceConfig, AuditLogger
from ..execution.base import Order, Market
from ..execution.router import OrderRouter
from ..ai.assistant import AIAssistant


@dataclass
class SelectionPipelineResult:
    selector_strategy: str
    steps: list = field(default_factory=list)
    selection: dict = field(default_factory=dict)
    portfolio: dict = field(default_factory=dict)
    robustness: dict = field(default_factory=dict)
    risk: dict = field(default_factory=dict)
    compliance: dict = field(default_factory=dict)
    orders: list = field(default_factory=list)
    ai_review: dict = field(default_factory=dict)
    ok: bool = False

    def to_dict(self) -> dict:
        return {
            "selector_strategy": self.selector_strategy,
            "steps": self.steps, "ok": self.ok,
            "selection": self.selection,
            "portfolio": self.portfolio,
            "robustness": self.robustness,
            "risk": self.risk,
            "compliance": self.compliance,
            "orders": self.orders,
            "ai_review": self.ai_review,
            "disclaimer": "本链路只生成实盘意图，未产生真实委托；真实报单须单独走券商模拟账号验证脚本",
        }


class SelectionPipeline:
    """选股到实盘意图的一条龙编排器。"""

    TOTAL_STEPS = 8   # 8 次 _log，与 SSE 进度条分母严格一致

    def __init__(self, progress_cb: Callable = None):
        self.cb = progress_cb or (lambda i, n, m: None)
        self._step = 0
        self.resolver = DataResolver()
        self.guard = StrategyGuard()
        self.router = OrderRouter(validate_all=True)   # 恒定校验模式
        self.assistant = AIAssistant()
        self.auditor = AuditLogger()

    def _log(self, msg: str):
        self._step += 1
        self.cb(min(self._step, self.TOTAL_STEPS), self.TOTAL_STEPS, msg)

    def _build_compliance(self) -> ComplianceGateway:
        cc = SETTINGS.get("compliance")
        rc = SETTINGS.get("risk")
        blacklist = set(x.strip() for x in str(cc.get("blacklist", "")).split(",") if x.strip())
        return ComplianceGateway(
            ComplianceConfig(
                max_position_pct=rc.get("max_position_pct", 0.2),
                max_total_pct=rc.get("max_total_pct", 0.8),
                max_order_value=cc.get("max_order_value", 2_000_000),
                max_daily_orders=cc.get("max_daily_orders", 50),
                block_st=rc.get("block_st", True),
                block_blacklist=bool(blacklist),
                trading_hours_only=cc.get("trading_hours_only", True),
            ),
            blacklist=blacklist, auditor=self.auditor)

    def run(self, selector_strategy: str = "multi_factor",
            top_n: int = 10, rebalance: str = "monthly",
            momentum_fetch_n: int = 60, min_amount_yi: float = 1.0,
            live: bool = False, preset_selection: dict = None) -> SelectionPipelineResult:
        """执行一条龙。live 参数保留但被强制拒绝：本管线不产生真实委托。

        preset_selection：可传入「全市场选股」页刚跑出的结果（picks/weights/...），
        此时跳过重新扫描全市场，直接复用该结果做组合回测与风控。
        """
        self._step = 0
        res = SelectionPipelineResult(selector_strategy)
        if live:
            res.steps.append("已拒绝 live=True：选股管线只生成实盘意图，请走独立报单验证脚本")
            self._log("⛔ 拒绝真实报单参数")
            return res

        # ① 全市场选股（或复用已有选股结果）
        self._log("① 全市场选股：真实快照 + 策略插件打分")
        def sel_cb(i, n, msg):
            self.cb(min(self._step, self.TOTAL_STEPS), self.TOTAL_STEPS,
                    f"选股·{msg} {i}/{n}")
        sel = MarketSelector(SelectorConfig(
            top_n=top_n, momentum_fetch_n=momentum_fetch_n,
            min_amount=min_amount_yi * 1e8), strategy=selector_strategy)
        if preset_selection and preset_selection.get("picks"):
            picks = []
            for p in preset_selection["picks"]:
                code = str(p.get("code", "")).strip()
                if not code:
                    continue
                picks.append(Pick(
                    code=code, name=str(p.get("name") or ""),
                    price=float(p.get("price") or 0), score=float(p.get("score") or 0),
                    factors=p.get("factors") or {}, reason=str(p.get("reason") or "")))
            selection = SelectionResult(
                picks=picks,
                universe_size=int(preset_selection.get("universe_size") or len(picks)),
                filtered_out={}, config=preset_selection.get("config") or {},
                timestamp=preset_selection.get("timestamp") or time.strftime("%H:%M:%S"))
            weights_all = preset_selection.get("weights") or sel.target_weights(selection)
            res.steps.append(f"复用已选股结果 {len(picks)} 只（不再重新扫描全市场）")
        else:
            selection = sel.select(sel_cb)
            weights_all = sel.target_weights(selection)
            res.steps.append(f"选出 {len(selection.picks)} 只 / 全市场 {selection.universe_size} 只")
        res.selection = selection.to_dict()
        res.selection["weights"] = weights_all
        if not selection.picks:
            res.steps.append("选股为空，链路终止")
            return res

        # ② 拉真实K线并统一口径
        self._log("② 数据准备：入选标的真实K线 + enrich")
        bars, contracts, picked = {}, {}, []
        for p in selection.picks:
            try:
                rows = self.resolver.kline(p.code, "1d", "qfq", beg="20200101")
                if len(rows) < 60:
                    res.steps.append(f"{p.code} 历史不足60根，剔除")
                    continue
                bars[p.code] = enrich(rows)
                contracts[p.code] = contract_snapshot(bars[p.code])
                picked.append(p)
            except Exception as e:
                res.steps.append(f"{p.code} 数据不可用，剔除: {str(e)[:60]}")
        if len(bars) < 2:
            res.steps.append("可用标的少于2只，组合回测终止")
            return res
        risk_cfg = SETTINGS.get("risk")
        weights = {c: weights_all.get(c, 0) for c in bars}
        tot = sum(weights.values()) or 1
        weights = {c: v / tot for c, v in weights.items()}
        # 先按风控上限收缩权重，避免"组合回测过了但风控闸必挂"的自相矛盾
        single_cap = risk_cfg.get("max_position_pct", 0.2)
        total_cap = risk_cfg.get("max_total_pct", 0.8)
        weights = {c: min(v, single_cap) for c, v in weights.items()}
        tot = sum(weights.values())
        # 留 0.5% 缓冲，避免浮点误差/整手取整导致风控闸末位标的总仓位超限
        effective_total = total_cap * 0.995
        if tot > effective_total:
            weights = {c: v * effective_total / tot for c, v in weights.items()}
        res.steps.append(f"可用标的 {len(bars)} 只，统一口径 "
                         f"{contracts[list(bars)[0]]['contract']}，目标总仓位 {sum(weights.values()):.1%}")

        # ③ 自动组合回测
        self._log("③ 自动组合回测：选股权重 + 真实成本 + T+1")
        pcfg = PortfolioConfig(
            initial_cash=SETTINGS.get("backtest", "initial_cash"),
            slippage=SETTINGS.get("backtest", "slippage"),
            signal_mode="weights", rebalance=rebalance,
            max_weight=risk_cfg.get("max_position_pct", 0.2),
            max_total_weight=risk_cfg.get("max_total_pct", 0.8),
            rebalance_threshold=0.02,
        )
        def pc_cb(i, n, msg):
            self.cb(min(self._step, self.TOTAL_STEPS), self.TOTAL_STEPS, msg)
        pf = PortfolioEngine(pcfg, pc_cb).run(bars, contracts=contracts, weights=weights)
        res.portfolio = pf.to_dict()
        ps = pf.summary
        res.steps.append(f"组合收益 {ps['total_return']:.2%} 回撤 {ps['max_drawdown']:.2%} "
                         f"夏普 {ps['sharpe']} 换手 {ps['turnover_ratio']}")

        # ④ K段折外稳健性
        self._log("④ 稳健检验：组合层K段折外")
        try:
            k = int(SETTINGS.get("backtest", "k_folds"))
            # 先按共同交易日对齐，再切段，避免各标的长度不同导致越界或错位
            common_dates = sorted(set.intersection(*[set(b["date"] for b in v)
                                                     for v in bars.values()]))
            segs = k_fold_segments(common_dates, k)
            seg_rets = []
            for seg in segs:
                if len(seg) < 30:
                    continue
                dmap = {c: {b["date"]: i for i, b in enumerate(v)} for c, v in bars.items()}
                sub = {c: [bars[c][dmap[c][d]] for d in seg] for c in bars}
                r = PortfolioEngine(pcfg).run(sub, contracts=contracts, weights=weights)
                seg_rets.append(r.summary["total_return"])
            score = robustness_score(seg_rets)
            res.robustness = {
                "score": round(score, 4),
                "segment_returns": [round(x, 4) for x in seg_rets],
                "positive_segments": sum(1 for x in seg_rets if x > 0),
                "total_segments": len(seg_rets),
            }
            res.steps.append(f"组合稳健分 {score:.4f} (正段 {res.robustness['positive_segments']}/{len(seg_rets)})")
        except Exception as e:
            res.robustness = {"error": str(e)}
            res.steps.append(f"稳健检验异常: {e}")

        # ⑤ 策略守护 + 风控
        self._log("⑤ 风控网关：策略守护/仓位/回撤熔断")
        gname = f"selection_{selector_strategy}"
        state = self.guard.update(gname, pf.equity[-1], ps.get("net_pnl"))
        circuit = DrawdownCircuitBreaker(risk_cfg.get("max_drawdown_pct", 0.15))
        tripped = circuit.update(pf.equity[-1])
        rg = RiskGateway(RiskConfig(
            max_position_pct=risk_cfg.get("max_position_pct", 0.2),
            max_total_pct=risk_cfg.get("max_total_pct", 0.8),
            max_daily_loss_pct=risk_cfg.get("max_daily_loss_pct", 0.02),
            max_drawdown_pct=risk_cfg.get("max_drawdown_pct", 0.15),
            allow_list_only=False, block_st_limit=risk_cfg.get("block_st", True)))
        risk_rows, total_asset = [], pf.equity[-1]
        pos_value = 0.0
        for p in picked:
            c = p.code
            amt = total_asset * weights.get(c, 0)
            ok, why = rg.check(c, "buy", amt, total_asset, pos_value, p.name)
            risk_rows.append({"code": c, "name": p.name, "amount": round(amt, 2),
                              "pass": ok, "reason": why})
            if ok:
                pos_value += amt
        risk_ok = (not tripped) and self.guard.can_trade(gname) and all(r["pass"] for r in risk_rows)
        res.risk = {"pass": risk_ok, "circuit_breaker": tripped,
                    "guard_state": state.value, "checks": risk_rows}
        res.steps.append(f"风控{'通过' if risk_ok else '拦截'} 熔断={tripped} 状态={state.value}")

        # ⑥ 合规闸
        self._log("⑥ 合规闸：禁投池/限额/交易时段 + 审计留痕")
        gw = self._build_compliance()
        comp_rows, comp_ok = [], False
        if risk_ok:
            for p in picked:
                c = p.code
                try:
                    q = self.resolver.quote(c)
                    px = q.price
                except Exception as e:
                    comp_rows.append({"code": c, "pass": False, "reason": f"行情不可用: {e}"})
                    continue
                amt = total_asset * weights.get(c, 0)
                vol = (int(amt / px / 100) * 100) if px > 0 else 0
                ok, why = gw.check(c, "buy", vol, px, q.name or p.name,
                                   total_asset=total_asset, current_pos_value=0,
                                   strategy=gname)
                comp_rows.append({"code": c, "name": p.name, "volume": vol,
                                  "price": px, "pass": ok, "reason": why})
            comp_ok = any(r["pass"] for r in comp_rows)
        else:
            comp_rows.append({"pass": False, "reason": "风控拦截，合规检查未执行"})
        res.compliance = {"pass": comp_ok, "checks": comp_rows}
        res.steps.append(f"合规{'通过' if comp_ok else '未通过'} ({sum(1 for r in comp_rows if r['pass'])}/{len(comp_rows)})")

        # ⑦ 实盘意图（validate 路由，绝不真实报单）
        self._log("⑦ 实盘意图：生成委托意图（校验模式）")
        orders = []
        by_code = {r["code"]: r for r in comp_rows if r.get("pass")}
        for p in picked:
            c = p.code
            if c not in by_code:
                continue
            r = by_code[c]
            order = Order(code=c, side="buy", volume=r["volume"], price=r["price"],
                          market=Market.CN_A, strategy=gname)
            out = self.router.submit(order)
            orders.append(out.to_dict())
        res.orders = orders
        res.steps.append(f"生成委托意图 {len(orders)} 笔，状态 VALIDATED_ONLY（未报单）")

        # ⑧ AI复盘
        self._log("⑧ AI复盘：组合视角总结")
        review_q = (
            f"请复盘全市场[{selector_strategy}]选股组合：{len(picked)}只标的，"
            f"组合收益{ps['total_return']:.2%}，回撤{ps['max_drawdown']:.2%}，"
            f"夏普{ps['sharpe']}，稳健分{res.robustness.get('score')}，"
            f"风控{'通过' if risk_ok else '拦截'}，合规{'通过' if comp_ok else '未通过'}。"
            f"给出专业评价与风险提示，并说明这只是实盘意图不是真实成交。")
        res.ai_review = self.assistant.ask(review_q, use_tools=False)
        self._log("✓ 选股一条龙完成")
        res.ok = True
        return res
