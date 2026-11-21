#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一配置中心 —— 全系统唯一配置入口（用户需求调研后设计）。

调研结论（QMT/vnpy/AQ开源设计共识）：
  - 配置分层：mode 一键切换 backtest/paper/live
  - 覆盖：AI接口、数据源、回测成本、风控、合规、执行器、通知、系统
  - 敏感信息(API Key)脱敏显示 + 环境变量覆盖
  - 前端可视化编辑，运行时热更新，不重启生效

设计：
  - CONFIG_SCHEMA 定义每个配置项的类型/默认/范围/说明/敏感标记
  - 持久化到 config/system.json（JSON，便于阅读与版本管理）
  - 环境变量优先级最高（QIAO_* ），支持容器化部署
  - get/set 提供类型校验，非法值拒绝
"""
import copy
import json
import os
import threading

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_FILE = os.path.join(BASE, "config", "system.json")

# 配置 schema：group -> key -> {type, default, desc, min, max, options, secret}
CONFIG_SCHEMA = {
    "system": {
        "mode": {"type": "str", "default": "paper", "options": ["backtest", "paper", "live"],
                 "desc": "运行模式：backtest回测 / paper模拟 / live实盘（实盘需显式确认）"},
        "theme": {"type": "str", "default": "dark", "options": ["dark", "light"], "desc": "界面主题"},
        "log_level": {"type": "str", "default": "INFO", "options": ["DEBUG", "INFO", "WARNING", "ERROR"], "desc": "日志级别"},
        "server_port": {"type": "int", "default": 8765, "min": 1024, "max": 65535, "desc": "Web终端端口"},
    },
    "ai": {
        "provider": {"type": "str", "default": "deepseek",
                     "options": ["deepseek", "openai", "qwen", "zhipu", "moonshot", "ollama", "custom"],
                     "desc": "云端AI服务商"},
        "api_key": {"type": "str", "default": "", "secret": True, "desc": "API密钥（仅本地保存，界面脱敏显示）"},
        "base_url": {"type": "str", "default": "https://api.deepseek.com/v1", "desc": "OpenAI兼容API地址"},
        "model": {"type": "str", "default": "deepseek-chat", "desc": "模型名称"},
        "temperature": {"type": "float", "default": 0.3, "min": 0, "max": 2, "desc": "生成温度"},
        "timeout": {"type": "int", "default": 60, "min": 5, "max": 300, "desc": "请求超时(秒)"},
        "enable_tools": {"type": "bool", "default": True, "desc": "允许AI调用工具查真实数据"},
    },
    "data": {
        "primary_source": {"type": "str", "default": "eastmoney",
                           "options": ["eastmoney", "tencent", "sina"], "desc": "主数据源"},
        "realtime_ttl": {"type": "int", "default": 30, "min": 5, "max": 600, "desc": "实时行情缓存(秒)"},
        "kline_ttl": {"type": "int", "default": 3600, "min": 60, "max": 86400, "desc": "K线缓存(秒)"},
        "adjust": {"type": "str", "default": "qfq", "options": ["qfq", "hfq", "none"], "desc": "复权方式"},
        "validate_data": {"type": "bool", "default": True, "desc": "启用脏数据校验（强烈建议开启）"},
    },
    "backtest": {
        "initial_cash": {"type": "float", "default": 1000000, "min": 10000, "desc": "初始资金(元)"},
        "slippage": {"type": "float", "default": 0.001, "min": 0, "max": 0.05, "desc": "滑点比例"},
        "commission_rate": {"type": "float", "default": 0.00025, "min": 0, "max": 0.01, "desc": "佣金费率"},
        "benchmark": {"type": "str", "default": "000300", "desc": "业绩基准指数代码"},
        "k_folds": {"type": "int", "default": 5, "min": 2, "max": 10, "desc": "稳健性检验折数"},
    },
    "risk": {
        "max_position_pct": {"type": "float", "default": 0.20, "min": 0.01, "max": 1, "desc": "单票仓位上限"},
        "max_total_pct": {"type": "float", "default": 0.80, "min": 0.1, "max": 1, "desc": "总仓位上限"},
        "max_drawdown_pct": {"type": "float", "default": 0.15, "min": 0.01, "max": 0.5, "desc": "回撤熔断线"},
        "max_daily_loss_pct": {"type": "float", "default": 0.02, "min": 0.001, "max": 0.2, "desc": "日内亏损熔断线"},
        "block_st": {"type": "bool", "default": True, "desc": "禁止交易ST/退市风险股"},
        "whitelist_only": {"type": "bool", "default": False, "desc": "仅允许白名单标的交易"},
    },
    "compliance": {
        "max_order_value": {"type": "float", "default": 2000000, "min": 10000, "desc": "单笔金额上限(元)"},
        "max_daily_orders": {"type": "int", "default": 50, "min": 1, "max": 1000, "desc": "日内最大委托次数"},
        "trading_hours_only": {"type": "bool", "default": True, "desc": "仅交易时段允许下单"},
        "audit_enabled": {"type": "bool", "default": True, "desc": "启用审计留痕（合规要求）"},
        "blacklist": {"type": "str", "default": "", "desc": "禁投池标的代码，逗号分隔"},
    },
    "execution": {
        "broker": {"type": "str", "default": "qmt", "options": ["qmt", "ctp", "hk", "validate"], "desc": "执行网关"},
        "qmt_path": {"type": "str", "default": "", "desc": "QMT安装目录(userdata_mini路径)"},
        "account_id": {"type": "str", "default": "", "secret": True, "desc": "交易账户ID"},
        "require_confirm": {"type": "bool", "default": True, "desc": "实盘下单需二次确认（强烈建议开启）"},
    },
    "selector": {
        "default_topn": {"type": "int", "default": 10, "min": 3, "max": 50, "desc": "默认选股数量"},
        "momentum_fetch_n": {"type": "int", "default": 60, "min": 20, "max": 300, "desc": "历史精算池大小（仅历史类策略）"},
        "max_pe": {"type": "float", "default": 60, "min": 1, "desc": "PE上限（兼容旧版；实际阈值由各策略专属参数控制）"},
        "min_amount_yi": {"type": "float", "default": 1, "min": 0, "desc": "最小成交额(亿元，全局流动性底线)"},
        "w_momentum": {"type": "float", "default": 0.35, "min": 0, "max": 1, "desc": "动量权重（兼容旧版；现由策略专属参数控制）"},
        "w_valuation": {"type": "float", "default": 0.25, "min": 0, "max": 1, "desc": "估值权重（兼容旧版；现由策略专属参数控制）"},
        "w_liquidity": {"type": "float", "default": 0.20, "min": 0, "max": 1, "desc": "流动性权重（兼容旧版；现由策略专属参数控制）"},
        "w_quality": {"type": "float", "default": 0.20, "min": 0, "max": 1, "desc": "质量权重（兼容旧版；现由策略专属参数控制）"},
    },
    "notify": {
        "channel": {"type": "str", "default": "none", "options": ["none", "webhook", "email"], "desc": "告警通知渠道"},
        "webhook_url": {"type": "str", "default": "", "secret": True, "desc": "Webhook地址(企业微信/钉钉等)"},
        "on_circuit_break": {"type": "bool", "default": True, "desc": "熔断触发时通知"},
        "on_strategy_retire": {"type": "bool", "default": True, "desc": "策略退役时通知"},
    },
}

# 环境变量映射：QIAO_AI__API_KEY 等（双下划线表示层级）
ENV_PREFIX = "QIAO_"


def _default_config() -> dict:
    return {g: {k: v["default"] for k, v in items.items()}
            for g, items in CONFIG_SCHEMA.items()}


def _coerce(value, spec):
    """按 schema 类型转换并校验。"""
    t = spec["type"]
    try:
        if t == "int":
            v = int(value)
        elif t == "float":
            v = float(value)
        elif t == "bool":
            v = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
        else:
            v = str(value)
    except (TypeError, ValueError):
        raise ValueError(f"配置类型错误，期望 {t}: {value}")
    if "min" in spec and v < spec["min"]:
        raise ValueError(f"配置值 {v} 小于最小值 {spec['min']}")
    if "max" in spec and v > spec["max"]:
        raise ValueError(f"配置值 {v} 大于最大值 {spec['max']}")
    if "options" in spec and v not in spec["options"]:
        raise ValueError(f"配置值 {v} 不在可选项 {spec['options']}")
    return v


class Settings:
    """线程安全的配置管理器（单例）。"""
    _instance = None
    _lock = threading.RLock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def _load(self):
        with self._lock:
            if self._loaded:
                return
            cfg = _default_config()
            if os.path.exists(CONFIG_FILE):
                try:
                    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                        saved = json.load(f)
                    for g, items in saved.items():
                        if g in cfg and isinstance(items, dict):
                            for k, v in items.items():
                                if k in cfg[g]:
                                    cfg[g][k] = _coerce(v, CONFIG_SCHEMA[g][k])
                except Exception:
                    pass  # 配置损坏则用默认值，不崩溃
            # 环境变量覆盖（最高优先级）
            for g, items in CONFIG_SCHEMA.items():
                for k, spec in items.items():
                    env = f"{ENV_PREFIX}{g.upper()}__{k.upper()}"
                    if env in os.environ:
                        cfg[g][k] = _coerce(os.environ[env], spec)
            self._data = cfg
            self._loaded = True

    def get(self, group: str, key: str = None):
        self._load()
        with self._lock:
            if key is None:
                return copy.deepcopy(self._data.get(group, {}))
            return self._data.get(group, {}).get(key)

    def set(self, group: str, key: str, value):
        self._load()
        if group not in CONFIG_SCHEMA or key not in CONFIG_SCHEMA[group]:
            raise KeyError(f"未知配置项: {group}.{key}")
        v = _coerce(value, CONFIG_SCHEMA[group][key])
        with self._lock:
            self._data[group][key] = v
        self.save()
        return v

    def update(self, group: str, values: dict):
        """批量更新一个分组，全部校验通过后才写入（原子性）。"""
        self._load()
        if group not in CONFIG_SCHEMA:
            raise KeyError(f"未知配置分组: {group}")
        validated = {}
        for k, v in values.items():
            if k not in CONFIG_SCHEMA[group]:
                continue
            validated[k] = _coerce(v, CONFIG_SCHEMA[group][k])
        with self._lock:
            self._data[group].update(validated)
        self.save()
        return validated

    def save(self):
        self._load()
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with self._lock:
            data = copy.deepcopy(self._data)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def reset(self):
        with self._lock:
            self._data = _default_config()
            self._loaded = True
        self.save()
        return copy.deepcopy(self._data)

    def all(self, mask_secret: bool = True) -> dict:
        """返回全部配置。敏感字段脱敏。"""
        self._load()
        with self._lock:
            data = copy.deepcopy(self._data)
        if mask_secret:
            for g, items in CONFIG_SCHEMA.items():
                for k, spec in items.items():
                    if spec.get("secret") and data[g].get(k):
                        val = data[g][k]
                        data[g][k] = val[:3] + "*" * max(4, len(val) - 6) + val[-3:] if len(val) > 6 else "****"
        return data

    def schema(self) -> dict:
        """返回配置 schema 供 UI 动态渲染表单。"""
        return copy.deepcopy(CONFIG_SCHEMA)

    def status(self) -> dict:
        """配置完成度检查：帮助用户知道还差什么没配。"""
        self._load()
        checks = []
        ai = self._data["ai"]
        checks.append({"item": "AI 云端接口", "ok": bool(ai["api_key"]),
                       "hint": "未配置时将使用本地工具直答（功能可用但无自然语言分析）"})
        if self._data["system"]["mode"] == "live":
            ex = self._data["execution"]
            checks.append({"item": "实盘执行器", "ok": bool(ex["qmt_path"] and ex["account_id"]),
                           "hint": "实盘模式需配置 QMT 路径与账户ID"})
        checks.append({"item": "风控参数", "ok": True,
                       "hint": f"单票上限{self._data['risk']['max_position_pct']:.0%} 总仓位{self._data['risk']['max_total_pct']:.0%}"})
        checks.append({"item": "合规审计", "ok": self._data["compliance"]["audit_enabled"],
                       "hint": "审计留痕已开启" if self._data["compliance"]["audit_enabled"] else "审计未开启，不符合合规要求"})
        return {"mode": self._data["system"]["mode"], "checks": checks,
                "ready": all(c["ok"] for c in checks)}


SETTINGS = Settings()
