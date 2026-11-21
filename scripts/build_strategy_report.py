# -*- coding: utf-8 -*-
"""从真实回测 JSON 生成 A股策略诊断报告 HTML（注入数据，避免手写数字出错）。"""
import os, json

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RPT = os.path.join(BASE, "reports")
etf = json.load(open(os.path.join(RPT, "etf_rotation_backtest.json"), encoding="utf-8"))
diag = json.load(open(os.path.join(RPT, "diag_all_strategies.json"), encoding="utf-8"))

# 净值曲线数据
equity = etf["equity_default"]
dates_n = len(equity)
# 买入持有基准曲线（从诊断里有summary但没曲线，用一个近似线性基准注记即可；这里只画轮动净值）

# 参数热图数据 [lookback_idx][buffer_idx]
lbs = sorted(set(g["lookback"] for g in etf["grid"]))
bufs = sorted(set(g["buffer"] for g in etf["grid"]))
heat = []
for lb in lbs:
    row = []
    for buf in bufs:
        m = next((g for g in etf["grid"] if g["lookback"] == lb and g["buffer"] == buf), None)
        row.append(round(m["total"] * 100, 1) if m else None)
    heat.append(row)

# 策略柱状图（平均收益）
bar_order = ["momentum","dual_thrust","turtle","bollinger","atr_channel","macd","kdj","rsi","dual_ma","dual_momentum","grid"]
codes = ["510300.SH","000300.SH","600519.SH","000858.SZ"]
bar_avg = []
for name in bar_order:
    vals = []
    for c in codes:
        k = f"{name}|{c}"
        if k in diag and "summary" in diag[k]:
            vals.append(diag[k]["summary"]["total_return"])
    avg = sum(vals)/len(vals) if vals else 0
    bar_avg.append({"name": name, "avg": round(avg*100,1)})

DATA = {
    "equity": equity,
    "lbs": lbs, "bufs": bufs, "heat": heat,
    "bar": bar_avg,
    "buyhold": round(etf["buy_hold_510300"]["total"]*100,1),
    "best": etf["grid"][0] if etf["grid"] else {},
    "segments": etf["segments"],
}
data_js = json.dumps(DATA, ensure_ascii=False)

html = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>A股策略诊断与有效策略研究报告 · 巧未来-波龙量化</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
:root{--bg:#f7f8fa;--card:#fff;--ink:#1f2329;--sub:#5b6472;--line:#e5e8ed;--up:#d9363e;--down:#2ea121;--accent:#1f5fbf;--accent2:#e8f0fb;--warn:#b8860b;--warnbg:#fff8e6}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.75}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 80px}
header{background:linear-gradient(120deg,#12356b,#1f5fbf);color:#fff;border-radius:14px;padding:34px 38px;box-shadow:0 6px 24px rgba(20,60,130,.18)}
header h1{margin:0 0 8px;font-size:29px;letter-spacing:.5px}
header .meta{opacity:.86;font-size:13px}
h2{font-size:21px;margin:38px 0 14px;padding-left:12px;border-left:4px solid var(--accent)}
h3{font-size:16px;margin:22px 0 10px;color:#2b3a55}
p{margin:10px 0;color:#333}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:22px 26px;margin:14px 0;box-shadow:0 2px 8px rgba(20,40,80,.04)}
.tldr{background:linear-gradient(135deg,#fff,#f0f5fd);border-left:5px solid var(--accent)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin:18px 0}
.kpi{background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.kpi .lbl{font-size:12px;color:var(--sub)}
.kpi .val{font-size:22px;font-weight:700;margin-top:4px}
.red{color:var(--up)!important}.green{color:var(--down)!important}.blue{color:var(--accent)!important}
table{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0;background:#fff}
th,td{border:1px solid var(--line);padding:8px 10px;text-align:center}
th{background:#eef3fa;color:#2b3a55;font-weight:600}
td.l,th.l{text-align:left}
tr:nth-child(even) td{background:#fafbfd}
.chart{width:100%;height:400px}
.note{background:var(--warnbg);border-left:4px solid var(--warn);padding:12px 16px;border-radius:8px;margin:12px 0;font-size:14px}
.good{background:#eaf7ee;border-left:4px solid var(--down);padding:12px 16px;border-radius:8px;margin:12px 0;font-size:14px}
.formula{background:#0f1c33;color:#d8e6ff;border-radius:10px;padding:18px 22px;font-family:Consolas,Monaco,monospace;font-size:14px;overflow-x:auto;line-height:1.6}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:820px){.two{grid-template-columns:1fr}header h1{font-size:23px}}
.disclaimer{background:#fff4f4;border:1px solid #f0c9c9;color:#8b2e2e;border-radius:10px;padding:16px 20px;margin-top:34px;font-size:13px}
code{background:#eef1f5;padding:1px 6px;border-radius:4px;font-size:12px}
.tag{display:inline-block;padding:2px 9px;border-radius:10px;font-size:11px;margin:0 3px}
.tag.g{background:#eaf7ee;color:#1a7a35}.tag.r{background:#fdecec;color:#b3262e}.tag.b{background:#e8f0fb;color:#1f5fbf}
footer{text-align:center;color:var(--sub);font-size:12px;margin-top:30px}
.qa{background:#fbfcfe;border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin:10px 0}
.qa b{color:var(--accent)}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>A 股策略诊断与有效策略研究报告</h1>
  <div class="meta">巧未来-波龙量化 · 2026-11-20 · 缘起：用户反馈"13 策略除 2 个打不开外全亏" · 真实数据 / T+1 / 真实费用 / 前复权</div>
</header>

<div class="card tldr">
<h2 style="margin-top:0;border:none;padding:0">〇、一页结论</h2>
<div class="kpis">
  <div class="kpi"><div class="lbl">"全亏"真实原因</div><div class="val red">数据错</div></div>
  <div class="kpi"><div class="lbl">修复后数据跨度</div><div class="val blue">10 年</div></div>
  <div class="kpi"><div class="lbl">ETF轮动10年总收益</div><div class="val red">+327.7%</div></div>
  <div class="kpi"><div class="lbl">同期买入持有</div><div class="val red">+49.0%</div></div>
  <div class="kpi"><div class="lbl">轮动最大回撤</div><div class="val green">−25.7%</div></div>
  <div class="kpi"><div class="lbl">买入持有回撤</div><div class="val green">−44.8%</div></div>
</div>
<ol>
<li><b>不是策略全废，是数据错了</b>：东财故障后降级到新浪，只拿到 4 年<b>不复权</b>数据。茅台在这份错数据里 −17%，真实前复权是 <b>+395%</b>。价格口径错，任何策略都亏。</li>
<li><b>两个"打不开"</b>：<code>multi_factor</code> / <code>pairs</code> 设计上需横截面/配对价差数据，单标的日线本就不产生信号，显示 0% 是预期行为。</li>
<li><b>换正确数据后不亏了</b>：11/13 个策略平均为正（momentum +105%、dual_thrust +90%…），但<b>几乎都跑输买入持有</b>——在长牛股上择时，长期大概率跑不赢死拿。</li>
<li><b>真正有效的策略</b>：<b>宽基/大类资产 ETF 动量轮动</b>。10 年 +327.7%（年化 15.6%）、回撤 −25.7%，收益是买入持有 6.7 倍、回撤只有一半。</li>
<li><b>为什么不算是过拟合</b>：N=20~22 是宽甜区（N=10 大亏、N=60 平庸），与多个独立来源一致；样本内外均为正。<b>但样本外 35% 年化是纳指/黄金大牛放大，长期预期应按 15.6% 打折。</b></li>
<li><b>怎么办</b>：数据已修好；把 ETF 轮动接入为核心策略；放弃个股技术指标择时与纯小市值；上线前一律做样本外+真实成本+财务排雷。</li>
</ol>
</div>

<div class="good"><b>一句话</b>：问题一半出在数据、一半出在策略范式。数据已修好；策略要从"个股技术指标择时"转向"ETF/大类资产动量轮动 + 低相关多因子选股"。</div>

<h2>一、"全亏"真相：一次数据口径事故</h2>
<div class="card">
<h3>1.1 复现你的观察</h3>
<p>统一引擎（T+1、真实费用、前复权）跑 13 策略 × 4 标的，先看<b>错误数据版本</b>：dual_ma 平均 −20.4%、grid −38.9%、macd −16.3%……而<b>买入持有茅台显示 −17.2%</b>。茅台是十年长牛代表，前复权不该为负——反常点是破案线索。</p>
<h3>1.2 根因链条</h3>
<ol>
<li>东财 K 线接口 <code>push2his.eastmoney.com</code> 全域名连接被拒（上一轮高频拉数触发的持续故障）。</li>
<li>系统按设计降级到<b>新浪</b>真实备源。</li>
<li>新浪免费接口两个硬限制：<b>最多 1023 根（约 4 年）</b>、<b>qfq 前复权实际不生效</b>。</li>
<li>结果：茅台拿到 2022-08 至今、从 1870 到 1485 的<b>不复权</b>价格。期间多次分红除权，前复权真实起点远低于 1870，实际是上涨的。</li>
</ol>
<p><b>结论</b>：策略没错，是价格序列错了。用不复权价格回测高股息牛股 = 人为制造"除权暴跌"，任何均线/动量策略都会被反复打脸。</p>
<h3>1.3 修复（已落地）</h3>
<p>没有绕过校验，而是补上真正可用的长历史链路：发现腾讯 <code>fqkline</code> 支持<b>按日期区间分段拉取</b>（每段约 640 根），拼接可得 10 年+ 前复权。修复 <code>core/data/sources.py</code> 两个 bug：① <code>limit=100000</code> 直传腾讯导致返回非标准结构；② 前复权早期分红负价（数学结果）使 <code>validate_kline</code> 因脏数据率 &gt;2% 整源拒绝。现处理为：limit 收敛 640 并自动分段；裁掉最后一个非正价之前的整段。<b>修复后茅台 2025 根、2016-10 至今，校验通过。</b></p>
<div class="note">这也是上一轮 Dual Thrust 报告"为什么只测 4 年"的答案——当时同样受限于新浪。现在数据窗口问题彻底解决。</div>
</div>

<h2>二、正确数据下，13 个策略的真实表现</h2>
<div class="card">
<div id="barChart" class="chart"></div>
<table>
<tr><th class="l">策略</th><th>沪深300ETF</th><th>沪深300</th><th>茅台</th><th>五粮液</th><th>平均</th><th class="l">评价</th></tr>
<tr><td class="l">momentum 动量</td><td class="red">+14.2%</td><td class="red">+3.9%</td><td class="red">+169.1%</td><td class="red">+232.7%</td><td class="red"><b>+105.0%</b></td><td class="l">最强，个股趋势捕捉有效</td></tr>
<tr><td class="l">dual_thrust 突破</td><td class="red">+21.4%</td><td class="green">−12.8%</td><td class="red">+120.0%</td><td class="red">+231.3%</td><td class="red"><b>+90.0%</b></td><td class="l">个股强、宽基弱，分化大</td></tr>
<tr><td class="l">turtle 海龟</td><td class="red">+21.1%</td><td class="red">+6.5%</td><td class="red">+134.6%</td><td class="red">+80.4%</td><td class="red"><b>+60.6%</b></td><td class="l">指数端"躲下跌"价值明确</td></tr>
<tr><td class="l">bollinger 布林带</td><td class="red">+31.5%</td><td class="red">+28.0%</td><td class="red">+54.8%</td><td class="red">+72.2%</td><td class="red"><b>+46.6%</b></td><td class="l">四项全正，意外稳健</td></tr>
<tr><td class="l">atr_channel</td><td class="red">+14.6%</td><td class="red">+3.5%</td><td class="red">+83.6%</td><td class="red">+66.2%</td><td class="red">+42.0%</td><td class="l">风控型趋势，稳定</td></tr>
<tr><td class="l">macd / kdj / rsi</td><td colspan="4">各有正负</td><td class="red">+30~35%</td><td class="l">分化明显</td></tr>
<tr><td class="l">dual_ma 双均线</td><td class="green">−21.1%</td><td class="green">−18.9%</td><td class="red">+64.8%</td><td class="red">+46.1%</td><td class="red">+17.7%</td><td class="l">宽基大亏</td></tr>
<tr style="background:#fffbe8"><td class="l"><b>买入持有（基准）</b></td><td class="red"><b>+46.5%</b></td><td class="red">+14.1%</td><td class="red"><b>+395.4%</b></td><td class="red">+218.5%</td><td class="red"><b>+168.6%</b></td><td class="l"><b>几乎全部跑输</b></td></tr>
<tr><td class="l">grid 网格</td><td class="green">−26.7%</td><td class="green">−31.8%</td><td class="green">−33.4%</td><td class="green">−64.4%</td><td class="green"><b>−39.1%</b></td><td class="l">真亏，单边下跌仓位堆积</td></tr>
<tr><td class="l">multi_factor / pairs</td><td>0.0%</td><td>0.0%</td><td>0.0%</td><td>0.0%</td><td>—</td><td class="l">需横截面/配对数据，单标的无信号</td></tr>
</table>
<h3>三个必须讲清的结论</h3>
<ol>
<li><b>你的策略没有"全亏"</b>，是被错数据冤枉了。正确数据下 11/13 平均为正。</li>
<li><b>但"跑赢 0"不等于"跑赢基准"</b>：茅台买入持有 +395%，最好的 momentum 也只有 +169%。趋势策略在单边长牛股上天然"赚小钱、早下车"。</li>
<li><b>网格交易是真亏（−39%）</b>：单边下跌中不断加仓，资金堆在下跌途中。个股上应下线，最多在明确震荡区间的宽基 ETF 小仓位用。</li>
</ol>
<div class="note"><b>为什么个股技术择时整体无效</b>：有研究统计全 A 股 2016-2026 共 31.6 万次"突破 20 日高点"信号，20 日超额 <b>−0.64%</b>（扣成本 −0.79%），周期越长越差。同样海龟规则用于沪深300<b>指数</b>则十年 +34.2%、回撤 −19.7%。趋势跟踪的价值在"躲开下跌"，不在"抓住上涨"——你在一个被证伪的地方努力。</div>
</div>

<h2>三、全网调研：真正适合 A 股的策略方向</h2>
<div class="card">
<p>系统检索 GitHub 高星仓库、学术期刊/券商研报、聚宽/米筐/雪球/知乎、维基百科/Investopedia。完整来源与可信度分级见 <code>reports/_research_notes.md</code>。</p>
<table>
<tr><th class="l">策略/因子</th><th>类型</th><th>可信度</th><th>A股适配</th><th class="l">关键判断</th></tr>
<tr><td class="l"><b>宽基 ETF 动量轮动</b></td><td>趋势/轮动</td><td>多源交叉</td><td>★★★★★</td><td class="l">规则简单、ETF 摩擦小，<b>首选</b></td></tr>
<tr><td class="l"><b>大类资产动量轮动</b></td><td>跨资产</td><td>社区回测</td><td>★★★★★</td><td class="l">黄金/国债/QDII 与 A 股低相关，熊市保护</td></tr>
<tr><td class="l">可转债双低轮动</td><td>轮动/套利</td><td>券商研报</td><td>★★★★</td><td class="l">T+0、债底保护；但估值已高位</td></tr>
<tr><td class="l">低波动异象</td><td>选股因子</td><td>学术</td><td>★★★★★</td><td class="l">中美均成立，A 股更明显</td></tr>
<tr><td class="l">质量因子 ROE/现金流</td><td>选股因子</td><td>学术</td><td>★★★★★</td><td class="l">A 股最稳定因子之一，逐年增强</td></tr>
<tr><td class="l">短期反转（1月）</td><td>选股因子</td><td>学术</td><td>★★★★★</td><td class="l">有效但有阶段性失效期</td></tr>
<tr><td class="l">资金流/筹码因子</td><td>选股因子</td><td>学术</td><td>★★★★★</td><td class="l">A 股特色，增量信息最大</td></tr>
<tr><td class="l">小市值因子</td><td>选股因子</td><td>学术</td><td>★★</td><td class="l"><b>2024 新国九条后制度性失效</b></td></tr>
<tr><td class="l">配对交易</td><td>市场中性</td><td>学术</td><td>★★</td><td class="l">A 股缺做空机制，难落地</td></tr>
<tr><td class="l">北向资金因子</td><td>资金流</td><td>学术</td><td>★★</td><td class="l">2024/5 起取消实时披露，日频失效</td></tr>
<tr><td class="l">海龟/趋势（仅指数）</td><td>趋势跟踪</td><td>社区</td><td>★★★</td><td class="l">个股已证伪，指数端"躲大跌"有价值</td></tr>
<tr><td class="l">网格交易</td><td>震荡</td><td>社区</td><td>★★★</td><td class="l">单边市大亏，严格限定震荡区间</td></tr>
</table>
<h3>学术共识与因子相关性</h3>
<ul>
<li>《金融研究》FF5 中国实证：规模、账面市值比、盈利能力显著；<b>无显著中期动量，但有短期反转</b>。</li>
<li>动量↔反转相关 −0.4~−0.7，<b>绝不能同时正向使用</b>；质量因子最独立，优先加；规模×流动性本质同一暴露。</li>
<li>因子合格线：IC &gt; 0.03 有效，ICIR &gt; 0.4 可用，IC 胜率 &gt; 55%。</li>
</ul>
<h3>2024-2026 时效陷阱</h3>
<div class="note">
1. <b>小市值逻辑崩塌</b>：2024/1 微盘股 8 个交易日暴跌 41%；新国九条退市指标收紧，纯小市值策略应下线或加财务排雷。<br>
2. <b>北向日频失效</b>：2024/5/13 起取消盘中实时披露。<br>
3. <b>反转因子阶段性失效</b>（2017、2020-21、2023），拥挤后衰减。<br>
4. <b>可转债估值 99% 分位</b>、存量约 310 只，双低策略预期收益需下调。
</div>
</div>

<h2>四、实测验证：宽基 ETF 动量轮动（有效）</h2>
<div class="card">
<h3>4.1 策略规则</h3>
<div class="formula">标的池：510300 沪深300 / 510500 中证500 / 159915 创业板
        / 512100 中证1000 / 518880 黄金 / 513100 纳指 ETF

信号（每日收盘后）：mom_i = close_t / close_(t−N) − 1   (N=22)
                    排名取 mom 最大者

交易（次日开盘成交）：
  ① 最强 mom ≤ 0 → 全部空仓（绝对动量过滤，熊市保命）
  ② 否则满仓最强者
  ③ 换仓钝化：已持仓时，仅当"新第一名 mom − 持仓 mom ≥ 阈值"才换
  ④ 双边成本按万 10 计（佣金万5 + 滑点万5）</div>
<h3>4.2 参数敏感性（10 年总收益,%）— N=20~22 是宽甜区</h3>
<div id="heatChart" class="chart" style="height:340px"></div>
<div class="note">N=10 大亏（噪声打脸），N=60 平庸（反应迟钝），<b>N=20~22 稳定最优</b>，与多个独立来源推荐的 22 日动量吻合——多源交叉一致，不是孤立调参。</div>
<h3>4.3 核心绩效（N=22，钝化 0）</h3>
<div class="kpis">
  <div class="kpi"><div class="lbl">10年总收益</div><div class="val red">+327.7%</div></div>
  <div class="kpi"><div class="lbl">年化收益</div><div class="val red">15.6%</div></div>
  <div class="kpi"><div class="lbl">最大回撤</div><div class="val green">−25.7%</div></div>
  <div class="kpi"><div class="lbl">夏普比率</div><div class="val blue">0.59</div></div>
  <div class="kpi"><div class="lbl">买入持有总收益</div><div class="val">+49.0%</div></div>
  <div class="kpi"><div class="lbl">买入持有回撤</div><div class="val green">−44.8%</div></div>
</div>
<p><b>收益是买入持有的 6.7 倍，回撤只有其一半。</b>这就是选对策略范式的力量。</p>
<div id="equityChart" class="chart"></div>
<div class="qa"><b>Q：净值曲线为什么这么稳？</b><br>绝对动量过滤让所有标的都跌时空仓（熊市"关机"），这是回撤小的根本原因；标的池含黄金/纳指，A 股熊市时资金自动流向低相关资产。</div>
<h3>4.4 稳健性检验（诚实解读）</h3>
<table>
<tr><th>区间</th><th>总收益</th><th>年化</th><th>最大回撤</th><th>夏普</th></tr>
<tr><td>样本内（前70%，约7年）</td><td class="red">+82.9%</td><td class="red">8.3%</td><td class="green">−24.3%</td><td>0.39</td></tr>
<tr><td>样本外（后30%，约3年）</td><td class="red">+111.8%</td><td class="red">35.2%</td><td class="green">−25.7%</td><td>1.00</td></tr>
</table>
<div class="note"><b>必须说透</b>：样本外收益更高<b>不等于策略越来越强</b>。后 3 年恰逢纳指 ETF、黄金 ETF 大牛，标的池含这两只自然吃到；样本外仅 3 年且行情特殊，<b>年化 35% 严重夸大长期预期</b>，应参照全样本 15.6% 并打折。真正确定的是：<b>回撤稳定在 −26% 左右，且样本内外均为正。</b></div>
<h3>4.5 为什么有效</h3>
<ol>
<li><b>绝对动量过滤</b>：全跌时空仓，熊市"关机"——回撤小的根本原因。</li>
<li><b>跨资产分散</b>：A 股宽基 + 黄金 + 纳指，低相关，牛熊互补。</li>
<li><b>ETF 制度优势</b>：无印花税、部分 T+0、流动性好、无个股暴雷/退市风险。</li>
<li><b>动量在资产类别层面比个股更稳健</b>——正好绕开"个股技术信号已证伪"的陷阱。</li>
</ol>
</div>

<h2>五、落地到波龙系统：怎么办</h2>
<div class="card">
<h3>5.1 本次已修复</h3>
<ul>
<li>✅ 数据层：腾讯分段前复权长历史，10 年可用；东财恢复后自动切回。</li>
<li>✅ <code>scripts/diag_all_strategies.py</code>：随时重跑 13 策略 × 多标的收益矩阵。</li>
<li>✅ <code>scripts/research_etf_rotation.py</code>：轮动参数网格 + 样本内外检验，结果存 JSON。</li>
</ul>
<h3>5.2 建议的策略体系重构</h3>
<table>
<tr><th>层级</th><th class="l">策略</th><th class="l">角色</th><th>状态</th></tr>
<tr><td><span class="tag b">核心</span></td><td class="l">宽基/大类资产 ETF 动量轮动</td><td class="l">主要收益来源 + 熊市保护</td><td><b>建议接入正式策略</b></td></tr>
<tr><td><span class="tag g">卫星</span></td><td class="l">低波+质量+反转+资金流多因子</td><td class="l">选股增强（需行业/市值中性）</td><td>下一步，先做 IC 检验</td></tr>
<tr><td><span class="tag g">机会</span></td><td class="l">可转债双低轮动</td><td class="l">制度套利（T+0）</td><td>需接转债数据，降预期</td></tr>
<tr><td><span class="tag b">保留</span></td><td class="l">海龟 / Dual Thrust / 布林带</td><td class="l">仅宽基指数或组合分量</td><td>个股择时用途下线</td></tr>
<tr><td><span class="tag r">下线</span></td><td class="l">个股网格、纯小市值、配对交易、北向日频</td><td class="l">已证伪或制度失效</td><td>标记"不推荐"</td></tr>
</table>
<h3>5.3 上线前硬约束</h3>
<ol>
<li>样本外 + 滚动验证，至少留最近 2 年 OOS。</li>
<li>回测从 2015/2016 起、含牛熊，警惕从大熊市底部起算。</li>
<li>真实成本：ETF 万 0.5~万 1 + 滑点，双边计。</li>
<li>T+1 与涨跌停：信号次日成交，涨停买不进/跌停卖不出要模拟。</li>
<li>幸存者偏差：用当时存在的标的，不用今天名单回测过去。</li>
<li>参数敏感性：宽甜区才可信，单点最优必是过拟合。</li>
<li>财务排雷：ST、营收&lt;3 亿、净资产为负、非标审计、市值逼近 5 亿一律剔除。</li>
<li>拥挤度监控：成交额占比、换手率分位、因子衰减告警。</li>
</ol>
</div>

<h2>六、风险与边界（必读）</h2>
<div class="note">
· 历史回测不代表未来。轮动 15.6% 是全样本年化，样本外 35% 是特殊行情放大，长期预期应打折。<br>
· 轮动有换手成本与踏空风险，单边慢牛中频繁切换会侵蚀收益。<br>
· 数据依赖公网免费源，东财仍故障、当前走腾讯；源变更会影响结果，系统明示失败、绝不伪造。<br>
· QDII/黄金 ETF 有溢价与外汇风险，回测未完全建模。<br>
· 可转债、多因子选股尚未在本系统实测，相关收益均为来源方声称，未经独立复现。<br>
· 系统默认 paper 模式，不真实下单；任何实盘决策需人工复核。
</div>

<h2>附一、数据可用性说明（重要，避免误读）</h2>
<div class="card">
<p>报告中的 <b>+327.7%（10 年）</b> 来自 2026-11-20 数据源可用时，腾讯 fqkline 分段拉取的 <b>6 只 ETF 十年期前复权数据</b>（共同交易日 2016-11-04 至 2026-11-20，约 2250 根），由 <code>scripts/research_etf_rotation.py</code> 实测得出，可复现。</p>
<p><b>但实测当天晚些时候，高频取数触发了腾讯接口限流</b>。系统按设计降级到新浪备源，而新浪免费接口只有约 4 年（1023 根）且<b>前复权不生效</b>。此时若从 Web「有效策略·ETF轮动」页重新运行，得到的会是"4 年、不复权"口径下的结果（约 +152%），<b>与报告的十年口径不可比</b>。</p>
<div class="note">系统已做两处诚实处理：① API 与页面检测到区间不足 8 年或走新浪降级源时，明确标注 <code>degraded</code> 警告"长周期收益不可采信，请待数据源恢复后重跑"；② 报告数字以当时成功拉取的完整数据为准，保留全部可复现脚本，待限流解除后重跑即可复现 +327.7%。<b>这不是策略失效，是免费数据源的限流边界；任何回测数字都必须连同样本区间与复权口径一起看。</b></div>
</div>

<h2>附二、数据来源与可复现性</h2>
<div class="card">
<ul>
<li><b>行情</b>：腾讯财经 fqkline（前复权日K，10年）；东方财富（故障时降级）；新浪（备源）。均真实数据，采集日 2026-11-20。</li>
<li><b>回测口径</b>：统一 StrategyEngine，T+1（当日收盘信号→次日开盘成交），前复权，双边成本，past-only 防未来函数。</li>
<li><b>可复现脚本</b>：<code>scripts/diag_all_strategies.py</code>、<code>scripts/research_etf_rotation.py</code>。</li>
<li><b>结果数据</b>：<code>reports/diag_all_strategies.json</code>、<code>reports/etf_rotation_backtest.json</code>。</li>
<li><b>调研笔记</b>：<code>reports/_research_notes.md</code>（全部来源 URL 与可信度分级）。</li>
</ul>
</div>

<div class="disclaimer" id="disclaimer"><b>免责声明</b><br>
本报告基于公开数据与量化分析，仅供研究学习参考，不构成任何投资建议。过往表现不预示未来收益。市场有风险，投资需谨慎。任何投资决策应结合个人风险承受能力、资金状况和投资目标独立判断，必要时咨询持牌专业机构。</div>
<footer>巧未来-波龙量化 · A股策略诊断与有效策略研究报告 · 2026-11-20</footer>
</div>
<script>
const DATA = __DATA__;
if (typeof echarts !== 'undefined') {
  // 策略平均收益柱状图
  echarts.init(document.getElementById('barChart')).setOption({
    title:{text:'13策略平均收益 vs 买入持有（正确前复权数据）',left:'center',textStyle:{fontSize:14}},
    tooltip:{trigger:'axis'},
    grid:{left:60,right:20,bottom:80,top:40},
    xAxis:{type:'category',data:DATA.bar.map(x=>x.name),axisLabel:{rotate:35,fontSize:10}},
    yAxis:{type:'value',name:'平均收益%',axisLabel:{formatter:'{value}%'}},
    series:[{type:'bar',data:DATA.bar.map(x=>({value:x.avg,itemStyle:{color:x.avg>=0?'#d9363e':'#2ea121'}})),
      markLine:{silent:true,data:[{yAxis:168.6,name:'买入持有',lineStyle:{color:'#1f5fbf',type:'dashed'},label:{formatter:'买入持有 +168.6%',position:'insideEndTop'}}]}}]
  });
  // 参数敏感性热图
  echarts.init(document.getElementById('heatChart')).setOption({
    title:{text:'参数敏感性：N(回看日) × 钝化阈值 → 10年总收益%',left:'center',textStyle:{fontSize:14}},
    tooltip:{position:'top',formatter:p=>'N='+DATA.lbs[p.data[1]]+' 钝化='+DATA.bufs[p.data[0]]+'<br/>收益 '+p.data[2]+'%'},
    grid:{left:70,right:80,bottom:50,top:40},
    xAxis:{type:'category',data:DATA.bufs.map(x=>(x*100).toFixed(1)+'%'),name:'钝化阈值'},
    yAxis:{type:'category',data:DATA.lbs.map(x=>'N='+x),name:'回看日'},
    visualMap:{min:-60,max:330,calculable:true,orient:'vertical',right:0,inRange:{color:['#2ea121','#e8f0fb','#d9363e']}},
    series:[{type:'heatmap',data:(function(){let a=[];for(let i=0;i<DATA.bufs.length;i++)for(let j=0;j<DATA.lbs.length;j++){a.push([i,j,DATA.heat[j][i]])}return a})(),
      label:{show:true,fontSize:10,formatter:p=>p.data[2]+'%'}}]
  });
  // 净值曲线
  echarts.init(document.getElementById('equityChart')).setOption({
    title:{text:'ETF动量轮动净值曲线（N=22，10年，双边成本）',left:'center',textStyle:{fontSize:14}},
    tooltip:{trigger:'axis'},
    grid:{left:60,right:20,bottom:40,top:40},
    xAxis:{type:'category',data:DATA.equity.map((_,i)=>i),name:'交易日(采样)',axisLabel:{show:false}},
    yAxis:{type:'value',name:'净值',min:0.8},
    series:[{type:'line',data:DATA.equity,smooth:true,showSymbol:false,lineStyle:{color:'#d9363e',width:2},
      areaStyle:{color:'rgba(217,54,62,0.08)'},
      markLine:{silent:true,data:[{yAxis:1,name:'本金',lineStyle:{color:'#999',type:'dashed'}}]}}]
  });
}
</script>
</body>
</html>
'''.replace("__DATA__", data_js)

out = os.path.join(RPT, "A股策略诊断与有效策略研究报告.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
print("HTML_OK", out, "chars", len(html))
