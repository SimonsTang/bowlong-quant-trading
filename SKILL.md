---
name: quant-aio
version: 3.0.0
description: 🐉 巧未来·波龙量化 v1.6 — A股/ETF/期货/期权全链路量化工作台。10角度全市场选股 · 13策略回测 · ETF动量轮动 · 组合回测/参数寻优 · 选股一条龙 · 合规闸 · QMT模拟验证 · 专业Web终端 · 全部真实数据零模拟。搜索关键词：波龙量化、波龙股神、量化交易、选股、A股、ETF、期货、期权、QMT、回测、策略、Dual Thrust、ETF轮动、巧未来。Keywords: Bowlong Quant, Quant Trading, Stock Picker, A-Share, ETF, Futures, Options, Backtest, QMT, Real Data, SimonsTang.
author: SimonsTang
license: MIT
homepage: https://learn2study.cn
repository: https://github.com/SimonsTang/bowlong-quant-trading
triggers:
  - "波龙量化"
  - "波龙选股"
  - "波龙回测"
  - "量化交易"
  - "全市场选股"
  - "ETF轮动"
  - "Dual Thrust"
metadata:
  openclaw:
    emoji: "📈"
    category: "finance"
    tags: ["波龙量化", "量化交易", "A股", "ETF", "期货", "期权", "选股", "回测", "QMT", "实盘", "风控", "合规", "Dual Thrust", "ETF轮动", "巧未来", "Quant Trading", "Stock Picker", "Backtest"]
    requires:
      bins: ["python3"]
---

# quant-aio · 巧未来·波龙量化 v1.6

> 研究层借鉴 TSP，补足实盘执行、多市场、机构合规、AI 助手与专业 Web 终端。**一律真实数据，零模拟、零随机数**；数据源失败明示或降级到标注缓存，绝不伪造价格。

## 什么时候用这个技能

- 用户说「波龙量化」「波龙选股」「全市场选股」「帮我回测某策略」「ETF 轮动」「Dual Thrust 效果如何」等量化相关请求。
- 需要 A 股 / ETF / 期货 / 期权的真实数据查询、选股、回测、组合分析、风控与合规检查。

## 快速开始

```bash
# Windows：双击根目录 start.bat（自动探测 Python，已有服务则直接打开浏览器）
start.bat

# 或命令行（Python 3.9+，仅标准库，无第三方依赖）
python web/server.py
# 浏览器打开 http://127.0.0.1:8765
```

启动后先看左侧「系统配置」：选择运行模式（backtest / paper / live）、AI 接口、数据源与风控参数。配置保存在本地 `config/system.json`，密钥在界面脱敏显示；也可用 `QIAO_AI__API_KEY` 等双下划线环境变量覆盖。

命令行自检与研究脚本：

```bash
python scripts/check_data.py            # 数据层自检
python scripts/run_fullchain.py         # 全链路真实数据跑通
python scripts/research_dual_thrust.py  # Dual Thrust 区间突破实测
python scripts/research_etf_rotation.py # ETF 动量轮动实测
python scripts/diag_all_strategies.py   # 13 策略全市场诊断
python scripts/verify_qmt_paper.py      # QMT 环境验证（默认只校验，不报单）
```

## 核心能力

| 模块 | 位置 | 能力 |
|---|---|---|
| 专业 Web 终端 | `web/` | 9 个功能页 + SSE 实时运行窗口；K 线含成交量、三条可调均线、方向键平移缩放、F10 窗口 |
| 数据层 | `core/data/` | 东财/腾讯/新浪三源降级、前复权、真实截面字段、过期缓存 STALE 标识、enrich 统一口径 |
| 研究层 | `core/research/` | T 日信号 T+1 开盘成交（无前视）、K 段折外稳健分 `0.6×中位+0.4×最差`、组合回测、参数寻优、ETF 轮动 |
| 策略库 | `core/strategy/` | 13 个交易择时策略 + 10 个全市场选股策略，插件化、参数可调 |
| 风控合规 | `core/risk/`、`core/compliance/` | 仓位/回撤/ST 过滤、预交易闸、限额、禁投池、append-only 审计 |
| 执行层 | `core/execution/` | 统一 Broker + 多市场路由；validate/live 严格隔离，失败抛错，不明转模拟 |
| AI 助手 | `core/ai/` | OpenAI 兼容接口 + 7 大工具 function-calling；无 Key 自动降级本地工具直答 |
| 多市场 | `core/multimarket/` | 期货保证金×乘数、期权权利金×合约乘数、ETF 免印花税；`f59` 精度还原 |
| 工作流 | `core/workflow/` | 单标的 10 步全链路 + 选股→组合回测→风控→合规→实盘意图 8 步一条龙 |

## 13 个交易择时策略（何时买卖）

双均线、MACD、海龟突破、Dual Thrust（含趋势/止损/趋势止损三版）、ATR 通道、布林回归、RSI、KDJ、N 日动量、双动量轮动、多因子（真实截面 RPS）、配对交易、网格交易。

策略库参数会真正带入回测、稳健性检验与全链路；寻优结果可一键回写参数面板。

## 10 个全市场选股策略（买什么）

价值、成长、动量、反转、质量、低波、资金流、多因子、小盘、技术面。每个策略有独立专属参数（如 PE 上限、营收增速、动量窗口、换手率下限），不是固定参数加滑块；候选池按策略逻辑预筛，结果记录各因子原始值与打分明细。

## 实测结论（诚实数据，先看局限）

- **Dual Thrust**：沪深300ETF 十年真实前复权数据下收益 −12.49%，同期买入持有 +43.1%；36 组参数中位数 −3.4%。旧代码曾因「当日收盘信号用当日开盘成交」的前视偏差虚增到 +3258%，已修正。
- **13 策略诊断**：使用正确十年数据后 11/13 平均收益为正，但多数跑输茅台买入持有 +395%；网格 −39%，多因子/配对不适合单标的择时。
- **ETF 动量轮动**：22 日动量、N=20~22 甜区，十年 +327.7%、年化 15.6%、最大回撤 −25.7%、夏普 0.59；同期买入持有 +49%、回撤 −44.8%。样本外高收益含纳指/黄金大牛成分，需打折看待。
- **小市值因子**受 2024 新国九条制度性影响；**北向实时因子**因 2024-05-13 实时披露取消而失效。不建议照搬旧论文参数。

详细数据与来源见 `reports/` 目录内的研究报告。

## 实盘边界（必须遵守）

1. 默认 `backtest` / `paper` 模式；只有显式切到 `live` 且所有前置条件通过才可能真实报单。
2. QMT 需券商开通 miniQMT 权限（通常 10 万门槛 + C4 测评 + 6 个月经验），Windows 常开并登录独立交易模式；实际下单需人工复核。
3. CTP 期货需柜台参数；港股仅预留接口，未接入实盘。
4. 免费数据源非生产级 SLA；机构级、高频、五档深度需商业数据源。
5. 不承诺收益，不做 AI 荐股；所有数字来自真实工具调用。

## v3.0.0 相对旧版升级点

- 升级为完整 Web 终端 + 研究/风控/合规/执行全链路，不再只是脚本集合。
- 新增 10 个选股策略与专属参数、13 策略库、组合回测、参数寻优、选股一条龙。
- 新增 ETF/期货/期权多市场品种与差异化成本模型。
- 修复前视偏差、K 线/F10 限流、估值字段错用、全市场选股进度卡住等真实问题。
- 新增 `reports/` 内 TSP 调研、Dual Thrust、策略诊断、安装说明书等正式报告。

---
*本技能仅供量化研究与教育交流，不构成投资建议。股市有风险，投资需谨慎。*
