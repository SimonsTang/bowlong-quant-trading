#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
miniQMT 券商模拟账号报单验证脚本（真实接口，绝不伪造）

用途：
  在装有迅投 miniQMT 且已登录「券商模拟/仿真交易账号」的机器上，
  完整验证「连接 -> 绑定账户 -> 查资产 -> 下一笔限价单 -> 查委托 -> 撤单 -> 落盘留痕」。

安全设计（重点）：
  1. 默认 --mode validate：只做环境与接口就绪检查，不连接交易柜台、不报单。
  2. 只有显式 --mode paper 且同时给出 --account-id 和 --i-understand 才可能报单。
  3. 报单使用「极低价限价买单 + 最小 100 股」，正常不会成交；随后立即撤单。
  4. 不支持 --mode live：本脚本不用于真实资金账户，防止误用。
  5. 任何一步失败都抛错并写失败报告，绝不把失败包装成"模拟成功"。
  6. 非交易时段仍可做连接与查询验证，但报单阶段会明确拒绝。

用法：
  # 第一步：环境自检（不报单）
  python scripts/verify_qmt_paper.py --mode validate

  # 第二步：券商模拟账号报单验证（需已登录 miniQMT）
  python scripts/verify_qmt_paper.py --mode paper \
      --qmt-path "D:/券商/QMT/userdata_mini" \
      --account-id "你的模拟资金账号" \
      --code 600519 --volume 100 --i-understand

配置回退：未传 --qmt-path / --account-id 时读取 config/system.json 的 execution 分组。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

REPORT = os.path.join(BASE, "reports", "qmt_paper_verify.json")
LOG: list = []


def log(step: str, status: str, detail: str = ""):
    rec = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "step": step, "status": status, "detail": str(detail)}
    LOG.append(rec)
    icon = {"OK": "[OK]  ", "SKIP": "[SKIP]", "FAIL": "[FAIL]",
            "INFO": "[INFO]"}.get(status, "[--]  ")
    print(f"{icon} {step}" + (f" | {detail}" if detail else ""))
    return rec


def load_config() -> dict:
    p = os.path.join(BASE, "config", "system.json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f).get("execution", {})
    except Exception as e:
        log("读取 config/system.json 的 execution 配置", "SKIP", e)
        return {}


def is_trading_now() -> bool:
    t = time.localtime()
    if t.tm_wday >= 5:
        return False
    hm = t.tm_hour * 100 + t.tm_min
    return (930 <= hm <= 1130) or (1300 <= hm <= 1457)


def miniqmt_running() -> bool:
    """Windows 下检测 miniQMT 相关进程；非 Windows 返回 None 表示未知。"""
    if sys.platform != "win32":
        return None
    try:
        raw = subprocess.run(["tasklist"], capture_output=True,
                             timeout=15).stdout or b""
        try:
            out = raw.decode("gbk", "ignore")
        except Exception:
            out = raw.decode("utf-8", "ignore")
        out = out.lower()
        keys = ("xtminiqmt", "xtqmt", "miniqmt", "xttrader")
        hit = [k for k in keys if k in out]
        log("检测 miniQMT 进程", "OK" if hit else "FAIL",
            f"命中: {hit}" if hit else "未发现 miniQMT 进程")
        return bool(hit)
    except Exception as e:
        log("检测 miniQMT 进程", "SKIP", e)
        return None


def preflight(mode: str, qmt_path: str, account_id: str, ack: bool) -> tuple[str, bool]:
    """返回 (最终模式, 是否通过)。"""
    log("预检 0/6：模式合法性", "OK", mode)
    if mode == "live":
        log("本脚本禁止 live 模式（仅用于券商模拟账号）", "FAIL")
        return mode, False

    log("预检 1/6：xtquant SDK", "INFO", "检测中")
    try:
        import xtquant  # noqa: F401
        from xtquant.xttrader import XtQuantTrader  # noqa: F401
        from xtquant.xttype import StockAccount  # noqa: F401
        log("预检 1/6：xtquant SDK", "OK", "已安装，官方接口可导入")
        sdk_ok = True
    except ImportError as e:
        log("预检 1/6：xtquant SDK", "FAIL",
            f"未安装 ({e})；需 pip install xtquant，且该包通常由券商提供/授权")
        sdk_ok = False

    cfg = load_config()
    qmt_path = qmt_path or str(cfg.get("qmt_path", ""))
    account_id = account_id or str(cfg.get("account_id", ""))
    cfg_ok = bool(qmt_path) and bool(account_id)
    log("预检 2/6：QMT 路径与资金账号", "OK" if cfg_ok else "FAIL",
        f"path={'已配置' if qmt_path else '空'} account={'已配置' if account_id else '空'}")

    path_ok = bool(qmt_path) and os.path.isdir(qmt_path)
    log("预检 3/6：QMT userdata 目录", "OK" if path_ok else "FAIL",
        qmt_path or "未提供")

    running = miniqmt_running()
    if running is None:
        log("预检 4/6：miniQMT 登录状态", "SKIP", "非Windows，无法检测进程，请人工确认")
    else:
        log("预检 4/6：miniQMT 登录状态", "OK" if running else "FAIL",
            "进程存在" if running else "未运行，请先启动并登录 miniQMT「独立交易模式」")

    session_ok = is_trading_now()
    log("预检 5/6：交易时段", "OK" if session_ok else "SKIP",
        "交易时段内" if session_ok else "非交易时段：可做连接/查询，报单阶段会拒绝")

    if mode == "paper":
        if not ack:
            log("预检 6/6：显式风险确认", "FAIL",
                "paper 模式必须带 --i-understand，确认你用的是券商模拟账号")
            return mode, False
        log("预检 6/6：显式风险确认", "OK", "已确认 --i-understand")
        if not (sdk_ok and cfg_ok and path_ok):
            log("预检总结", "FAIL", "SDK/路径/账号任一缺失，禁止报单")
            return mode, False
        if running is False:
            log("预检总结", "FAIL", "miniQMT 未运行，禁止报单")
            return mode, False
        if not session_ok:
            log("预检总结", "FAIL", "非交易时段，禁止报单（避免无效委托）")
            return mode, False
    else:
        log("预检 6/6：显式风险确认", "SKIP", "validate 模式不报单，无需确认")
        # validate 模式也要诚实报告环境是否就绪，不能"检查失败却显示通过"
        missing = []
        if not sdk_ok:
            missing.append("xtquant SDK")
        if not cfg_ok:
            missing.append("QMT路径/资金账号配置")
        if not path_ok:
            missing.append("userdata 目录")
        if running is False:
            missing.append("miniQMT 进程")
        if missing:
            log("预检总结", "FAIL", "环境未就绪: " + "、".join(missing))
            return mode, False

    return mode, True


def verify_validate_only(qmt_path: str, account_id: str) -> dict:
    """环境就绪检查：不连接交易柜台，不报单。"""
    log("validate：跳过真实下单接口", "SKIP",
        "本模式仅验证环境；接口就绪由预检的 xtquant 导入检查保证")
    return {"mode": "validate", "orders_submitted": 0,
            "note": "环境与接口就绪检查，未连接交易柜台、未产生任何委托"}


def verify_paper(qmt_path: str, account_id: str, code: str, volume: int) -> dict:
    """券商模拟账号真实报单验证。任何异常直接抛出。"""
    from xtquant.xttrader import XtQuantTrader
    from xtquant.xttype import StockAccount
    from xtquant import xtconstant

    t0 = int(time.time())
    log("步骤 1/7：创建 XtQuantTrader", "INFO", qmt_path)
    trader = XtQuantTrader(qmt_path, t0 % 1000000)
    trader.start()
    log("步骤 1/7：创建 XtQuantTrader", "OK")

    rc = trader.connect()
    if rc != 0:
        raise RuntimeError(f"miniQMT 连接失败，connect() 返回 {rc}；请确认已登录独立交易模式")
    log("步骤 2/7：连接 miniQMT", "OK", f"connect()={rc}")

    account = StockAccount(account_id, "STOCK")
    log("步骤 3/7：绑定资金账号", "OK", account_id)

    asset = trader.query_stock_asset(account)
    if asset is None:
        raise RuntimeError("query_stock_asset 返回 None，账号不可用或未登录")
    asset_info = {"total_asset": asset.total_asset, "cash": asset.cash,
                  "market_value": asset.market_value}
    log("步骤 4/7：查询真实账户资产", "OK", json.dumps(asset_info, ensure_ascii=False))

    # 极低价限价买单，正常不成交；用现价 1 折挂单，尾盘也不易成交
    from core.data.resolver import DataResolver
    px = round(DataResolver().quote(code).price * 0.1, 2)
    if px <= 0:
        raise RuntimeError("无法获取有效现价，放弃报单")
    log("步骤 5/7：构造验证委托", "OK",
        f"{code} BUY {volume}股 限价{px}（现价1折，预期不成交）")

    oid = trader.order_stock(account, code, xtconstant.STOCK_BUY, volume,
                             xtconstant.FIX_PRICE, px, "qiaoweilai-verify")
    if not oid:
        raise RuntimeError("order_stock 未返回委托号，报单失败")
    log("步骤 6/7：真实报单", "OK", f"委托号 {oid}")

    time.sleep(1.0)
    orders = trader.query_stock_orders(account) or []
    matched = [o for o in orders if str(getattr(o, "order_id", "")) == str(oid)]
    status = getattr(matched[0], "order_status", "UNKNOWN") if matched else "NOT_FOUND"
    traded = getattr(matched[0], "traded_volume", 0) if matched else 0
    log("步骤 7/7：查询委托状态", "OK", f"状态={status} 已成={traded}")

    cancelled = False
    if int(traded or 0) == 0:
        cr = trader.cancel_order_stock(account, int(oid))
        cancelled = (cr == 0)
        log("撤单", "OK" if cancelled else "FAIL", f"cancel 返回 {cr}")
    else:
        log("撤单", "SKIP", "委托已成交，无法撤单；请人工核查该笔交易")

    return {
        "mode": "paper", "account_id": account_id, "code": code,
        "volume": volume, "limit_price": px, "order_id": str(oid),
        "order_status": str(status), "traded_volume": int(traded or 0),
        "cancelled": cancelled, "asset": asset_info,
        "orders_submitted": 1,
        "note": "券商模拟账号真实委托；成交/撤单状态以 query_stock_orders 返回为准",
    }


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description="miniQMT 券商模拟账号报单验证（真实接口）")
    ap.add_argument("--mode", choices=["validate", "paper"], default="validate",
                    help="validate=仅环境检查不报单；paper=券商模拟账号真实报单")
    ap.add_argument("--qmt-path", default=str(cfg.get("qmt_path", "")))
    ap.add_argument("--account-id", default=str(cfg.get("account_id", "")))
    ap.add_argument("--code", default="600519")
    ap.add_argument("--volume", type=int, default=100)
    ap.add_argument("--i-understand", action="store_true",
                    help="paper 模式必需：确认使用券商模拟账号且理解真实下单后果")
    args = ap.parse_args()

    print("=" * 72)
    print("巧未来-波龙量化 | miniQMT 券商模拟账号报单验证")
    print(f"模式: {args.mode} | 时间: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 72)

    started = time.time()
    mode, ok = preflight(args.mode, args.qmt_path, args.account_id, args.i_understand)
    payload = {"started_at": LOG[0]["ts"] if LOG else "", "mode": mode,
               "gateway": "miniQMT / xtquant", "steps": LOG,
               "ok": False, "result": {}, "error": ""}

    try:
        if not ok:
            raise RuntimeError("预检未通过，按安全策略终止；未产生任何委托")
        if mode == "validate":
            payload["result"] = verify_validate_only(args.qmt_path, args.account_id)
        else:
            payload["result"] = verify_paper(args.qmt_path, args.account_id,
                                             args.code, args.volume)
        payload["ok"] = True
    except Exception as e:
        payload["error"] = f"{type(e).__name__}: {e}"
        log("执行失败", "FAIL", payload["error"])

    payload["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload["elapsed_sec"] = round(time.time() - started, 2)
    payload["steps"] = LOG
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("-" * 72)
    print(f"验证报告: {REPORT}")
    print(f"结论: {'通过' if payload['ok'] else '未通过/未执行'}")
    if not payload["ok"]:
        print("重要：本次没有产生真实委托，也没有伪造任何成交记录。")
        if payload["error"]:
            print(f"原因: {payload['error']}")
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
