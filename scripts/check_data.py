#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据层自检：全部使用真实数据，验证降级链可用性。零第三方依赖。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data.sources import EM, TX, SINA
from core.data.resolver import DataResolver

r = DataResolver()
print("=" * 60)
print("波龙量化 V3 · 真实数据层自检（无模拟数据）")
print("=" * 60)

# 1. 三源实时快照
print("\n[1] 三源实时快照 600519")
for src in (TX, EM, SINA):
    try:
        q = src.quote("600519")
        print(f"  {src.name:10s} {q.name:6s} 价={q.price:8.2f} 涨跌={q.change_pct:+6.2f}% ts={q.ts}")
    except Exception as e:
        print(f"  {src.name:10s} FAIL: {e}")

# 2. 降级链
print("\n[2] 统一入口（降级链+校验+缓存）")
q = r.quote("600519")
print(f"  结果: {q.name} 价={q.price:.2f} 来源={q.source} ts={q.ts}")

# 3. 全市场批量
print("\n[3] 全市场标的池")
uni = r.universe()
print(f"  A股标的数: {len(uni)}  样本: {uni[0]['code']} {uni[0]['name']}")

# 4. 历史日K（前复权，真实）
print("\n[4] 历史日K 600519（前复权）")
k = r.kline("600519", "1d", "qfq", "20240101", "20261120")
print(f"  根数={len(k)}  最新: {k[-1]['date']} 收={k[-1]['close']:.2f} 量={k[-1]['volume']}")

# 5. 分钟K
print("\n[5] 1分钟K 600519")
km = r.kline("600519", "1m", "qfq")
print(f"  根数={len(km)}  最新: {km[-1]['date']} 收={km[-1]['close']:.2f}")

# 6. 交易时段门控
print(f"\n[6] 当前交易时段: {'是' if r.is_trading_now() else '否（非交易时段，应读缓存）'}")
print("\n全部检查完成。数据源均为真实公开接口，无模拟数据。")
