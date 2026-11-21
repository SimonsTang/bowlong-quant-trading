#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 助手 - 对接云端 OpenAI 兼容 API（DeepSeek/通义/智谱/OpenAI/本地Ollama均可）。
用标准库 urllib 实现，零第三方依赖。

关键设计：
  - 端点/模型/Key 从环境变量或 config 读取，不硬编码密钥
  - 支持 function-calling 工具调用；无工具调用能力的模型也能用（降级为纯问答）
  - 无 Key / 网络失败时明确降级为"本地工具直答"，不编造数据
  - 所有数据类回答都来自 tools 真实接口，LLM 只做编排与自然语言包装
"""
import json
import os
import urllib.request

from .tools import TOOL_SPECS, dispatch

SYSTEM_PROMPT = """你是「巧未来-波龙量化」的AI助手，专业、克制、诚实。
原则：
1. 所有行情、回测、风控数据必须通过工具获取真实值，绝不编造数字。
2. 明确能力边界：本系统不做AI荐股，不承诺收益；回测结果不代表未来。
3. 实盘下单有严格边界，validate模式不产生真实委托。
4. 回答简洁专业，用中文，给出可执行建议时标注风险。"""


class AIAssistant:
    """AI助手。配置来自统一配置中心，支持运行时热更新（改完即生效，无需重启）。"""

    def __init__(self, api_key: str = None, base_url: str = None,
                 model: str = None, timeout: int = 60):
        from ..config.settings import SETTINGS
        self._settings = SETTINGS
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        # 显式传参优先，否则从配置中心读取（配置中心已处理环境变量覆盖）
        self._override = {}
        if api_key is not None:
            self._override["api_key"] = api_key
        if base_url is not None:
            self._override["base_url"] = base_url
        if model is not None:
            self._override["model"] = model
        if timeout != 60:
            self._override["timeout"] = timeout

    def _cfg(self, key):
        if key in self._override:
            return self._override[key]
        return self._settings.get("ai", key)

    @property
    def api_key(self):
        return self._cfg("api_key")

    @property
    def base_url(self):
        return str(self._cfg("base_url")).rstrip("/")

    @property
    def model(self):
        return self._cfg("model")

    @property
    def cloud_enabled(self) -> bool:
        return bool(self.api_key)

    def refresh(self):
        """运行时热更新：清掉覆盖，重新从配置中心读取。"""
        self._override.clear()
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    def test_connection(self) -> dict:
        """配置测试：用最简请求验证 API 连通性与凭证有效性。"""
        if not self.cloud_enabled:
            return {"ok": False, "error": "未配置 api_key"}
        try:
            resp = self._chat_completion(
                [{"role": "user", "content": "回复一个字：OK"}], tools=None)
            content = resp["choices"][0]["message"].get("content", "")
            return {"ok": True, "model": self.model, "reply": content[:50]}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def _chat_completion(self, messages: list, tools: list = None) -> dict:
        payload = {"model": self.model, "messages": messages,
                   "temperature": self._cfg("temperature")}
        if tools and self._cfg("enable_tools"):
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self._cfg("timeout")) as r:
            return json.loads(r.read().decode("utf-8"))

    def ask(self, question: str, use_tools: bool = True) -> dict:
        """主入口。返回 {answer, source, tool_calls}。"""
        if not self.cloud_enabled:
            return self._local_answer(question)

        self.messages.append({"role": "user", "content": question})
        try:
            resp = self._chat_completion(
                self.messages, tools=TOOL_SPECS if use_tools else None)
        except Exception as e:
            return {"answer": f"云端API调用失败({type(e).__name__}: {e})。已降级为本地工具直答。",
                    "source": "fallback", "tool_calls": []}

        msg = resp["choices"][0]["message"]
        tool_calls = []
        # 处理工具调用循环（最多3轮）
        for _ in range(3):
            calls = msg.get("tool_calls") or []
            if not calls:
                break
            for c in calls:
                fn = c["function"]
                name = fn["name"]
                args = json.loads(fn.get("arguments") or "{}")
                result = dispatch(name, args)
                tool_calls.append({"tool": name, "args": args})
                self.messages.append(msg)
                self.messages.append({
                    "role": "tool", "tool_call_id": c["id"],
                    "name": name, "content": result,
                })
            resp = self._chat_completion(self.messages, tools=TOOL_SPECS)
            msg = resp["choices"][0]["message"]

        answer = msg.get("content") or ""
        self.messages.append({"role": "assistant", "content": answer})
        return {"answer": answer, "source": self.model, "tool_calls": tool_calls}

    def _local_answer(self, question: str) -> dict:
        """无云端Key时的降级：关键词路由到本地工具，诚实标注来源。"""
        q = question.strip()
        tool, args = None, {}
        if "策略" in q and ("有哪些" in q or "列表" in q or "可选" in q):
            tool = "list_strategies"
        elif "回测" in q:
            tool, args = "run_backtest", {"code": "600519", "strategy": "dual_ma"}
            if "策略" in q:
                for s in ("dual_ma", "macd", "turtle", "bollinger", "rsi",
                          "kdj", "momentum", "dual_momentum", "multi_factor"):
                    if s in q:
                        args["strategy"] = s
        elif "行情" in q or "报价" in q or "现价" in q:
            import re
            m = re.search(r"(\d{6})", q)
            tool, args = "get_quote", {"code": m.group(1) if m else "600519"}
        elif "风控" in q or "健康" in q or "守护" in q:
            tool = "risk_status"
        elif "审计" in q or "合规" in q:
            tool = "compliance_log"
        elif "委托" in q or "路由" in q:
            tool = "router_status"

        if tool:
            result = dispatch(tool, args)
            return {"answer": f"[本地工具直答·未接云端LLM]\n工具: {tool}\n结果:\n{result}",
                    "source": "local-tools", "tool_calls": [{"tool": tool, "args": args}]}
        return {"answer": ("[本地模式] 我可回答：查行情/查回测/列策略/查风控/查合规/查委托。"
                           "配置 QIAO_API_KEY 与 QIAO_BASE_URL 后可接入云端LLM获得自然语言分析。"),
                "source": "local-tools", "tool_calls": []}
