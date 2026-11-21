#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
量化团队全程工作流编排（全链路跑通的中枢）。
把研究员→风控→合规→交易员→复盘 的团队协作串成一条可观测流水线：

  1. 数据准备      DataResolver 拉真实数据
  2. 统一口径      enrich() + 契约快照
  3. 策略选择      从策略库枚举/切换
  4. 稳健检验      K段折外（0.6中位+0.4最差）
  5. 回测          StrategyEngine 防未来函数回测
  6. 策略守护      StrategyGuard 健康度评估
  7. 风控网关      RiskGateway 仓位/白名单/熔断
  8. 合规闸        ComplianceGateway 预交易检查+审计
  9. 执行路由      OrderRouter 多市场路由（默认validate）
 10. AI复盘        AIAssistant 生成复盘摘要

每一步通过 progress_cb 上报，供 UI 实时观测。
"""
import time
from dataclasses import dataclass, field

from ..data.resolver import DataResolver
from ..data.enriched import enrich, contract_snapshot
from ..research.engine import StrategyEngine, EngineConfig
from ..research.robustness import evaluate_segments
from ..research.guard import StrategyGuard
from ..risk.risk import RiskGateway, RiskConfig, DrawdownCircuitBreaker
from ..compliance.compliance import ComplianceGateway, ComplianceConfig
from ..execution.base import Order, Market
from ..execution.router import OrderRouter
from ..strategy.base import get as get_strategy
from ..ai.assistant import AIAssistant


@dataclass
class PipelineResult:
    code: str
    strategy: str
    steps: list = field(default_factory=list)
    backtest: object = None
    robustness: dict = field(default_factory=dict)
    order: dict = field(default_factory=dict)
    ai_review: dict = field(default_factory=dict)
    ok: bool = False

    def to_dict(self) -> dict:
        return {
            "code": self.code, "strategy": self.strategy,
            "steps": self.steps, "ok": self.ok,
            "summary": self.backtest.summary if self.backtest else {},
            "contract": self.backtest.contract if self.backtest else {},
            "robustness": {k: v for k, v in self.robustness.items() if k != "details"},
            "order": self.order,
            "ai_review": self.ai_review,
        }


class TeamPipeline:
    def __init__(self, progress_cb=None):
        self.cb = progress_cb or (lambda i, n, m: None)
        self.resolver = DataResolver()
        self.guard = StrategyGuard()
        self.router = OrderRouter(validate_all=True)
        self.risk = RiskGateway(RiskConfig(allow_list_only=False))
        self.circuit = DrawdownCircuitBreaker(0.15)
        self.compliance = ComplianceGateway(ComplianceConfig(),
                                            blacklist={"000001.SZ"})
        self.assistant = AIAssistant()
        self._step = 0
        self._total = 11

    def _log(self, msg: str):
        self._step += 1
        self.cb(min(self._step, self._total), self._total, msg)

    def run(self, code: str, strategy: str = "dual_ma",
            params: dict = None, live: bool = False) -> PipelineResult:
        """跑通全链路。live=False 默认 validate（不产生真实委托）。"""
        self._step = 0
        result = PipelineResult(code, strategy)

        # 1 数据准备
        self._log("① 数据准备：拉取真实历史K线")
        rows = self.resolver.kline(code, "1d", "qfq", beg="20200101")
        if not rows:
            result.steps.append("数据不可用，终止")
            return result
        result.steps.append(f"真实K线 {len(rows)} 根")

        # 2 统一口径
        self._log("② 统一口径：enrich + 契约快照")
        bars = enrich(rows)
        contract = contract_snapshot(bars)
        result.steps.append(f"口径 {contract['contract']} 哈希 {contract['basis_sha256']}")

        # 3 策略选择
        self._log(f"③ 策略选择：{strategy}")
        st = get_strategy(strategy, **(params or {}))
        result.steps.append(f"策略参数 {st.param_dict()}")

        # 4 稳健检验
        self._log("④ 稳健检验：K段折外")
        try:
            rb = evaluate_segments(
                bars, lambda: get_strategy(strategy, **(params or {})).signal_fn(),
                StrategyEngine, EngineConfig(), k=5)
            result.robustness = rb
            result.steps.append(f"稳健分 {rb['score']} (正段 {rb['positive_segments']}/{rb['total_segments']})")
        except Exception as e:
            result.steps.append(f"稳健检验跳过: {e}")

        # 5 回测
        self._log("⑤ 回测：防未来函数引擎")
        eng = StrategyEngine(EngineConfig(), progress_cb=self.cb)
        result.backtest = eng.run_on_bars(bars, st.signal_fn(), code, strategy, contract)
        s = result.backtest.summary
        result.steps.append(f"回测收益 {s.get('total_return')} 回撤 {s.get('max_drawdown')} 夏普 {s.get('sharpe')}")

        # 6 策略守护
        self._log("⑥ 策略守护：健康度评估")
        state = self.guard.update(strategy, result.backtest.equity[-1],
                                  s.get("net_pnl"))
        result.steps.append(f"策略状态 {state.value}")

        # 7 风控网关
        self._log("⑦ 风控网关：仓位/熔断检查")
        tripped = self.circuit.update(result.backtest.equity[-1])
        risk_ok = self.guard.can_trade(strategy) and not tripped
        result.steps.append(f"风控{'通过' if risk_ok else '拦截'} 熔断={tripped}")

        # 8 合规闸
        self._log("⑧ 合规闸：预交易检查+审计留痕")
        quote = self.resolver.quote(code)
        order = Order(code=code, side="buy", volume=100,
                      price=quote.price, market=Market.CN_A, strategy=strategy)
        if risk_ok:
            ok, reason = self.compliance.check(
                code, "buy", 100, quote.price, quote.name,
                strategy=strategy)
            result.steps.append(f"合规 {'通过' if ok else '拒绝'}: {reason}")
        else:
            ok, reason = False, "风控拦截"
            result.steps.append(f"合规未执行: {reason}")

        # 9 执行路由
        self._log("⑨ 执行路由：多市场路由（默认校验模式）")
        if ok:
            executed = self.router.submit(order)
            result.order = executed.to_dict()
            result.steps.append(f"委托 {executed.status.value}: {executed.note}")
        else:
            result.order = {"status": "NOT_SUBMITTED", "reason": reason}

        # 10 AI复盘
        self._log("⑩ AI复盘：生成全链路摘要")
        review_q = (f"请复盘 {code} 用 {strategy} 策略的回测："
                    f"收益{s.get('total_return')}，回撤{s.get('max_drawdown')}，"
                    f"夏普{s.get('sharpe')}，稳健分{result.robustness.get('score')}，"
                    f"策略状态{state.value}。给出专业评价与风险提示。")
        result.ai_review = self.assistant.ask(review_q, use_tools=False)

        result.ok = True
        self._log("✓ 全链路完成")
        return result
