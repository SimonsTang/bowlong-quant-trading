#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全链路命令行演示：真实数据 数据→enrich→策略→稳健→回测→守护→风控→合规→路由→AI复盘。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.workflow.pipeline import TeamPipeline


def main():
    code = sys.argv[1] if len(sys.argv) > 1 else "600519"
    strategy = sys.argv[2] if len(sys.argv) > 2 else "dual_ma"

    def cb(i, n, msg):
        print(f"  [{i:>2}/{n}] {msg}")

    print("=" * 64)
    print(f"巧未来-波龙 全链路演示 | {code} / {strategy} | 真实数据")
    print("=" * 64)
    p = TeamPipeline(cb)
    r = p.run(code, strategy)

    print("\n" + "=" * 64)
    print("执行步骤：")
    for s in r.steps:
        print("  •", s)
    if r.backtest:
        print("\n绩效摘要：")
        for k, v in r.backtest.summary.items():
            print(f"  {k:>16}: {v}")
    print(f"\n稳健分: {r.robustness.get('score')} | 全链路状态: {'成功' if r.ok else '失败'}")
    print("\nAI复盘：")
    print("  " + (r.ai_review.get("answer", "")[:400]).replace("\n", "\n  "))


if __name__ == "__main__":
    main()
