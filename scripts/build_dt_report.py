#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 dual_thrust_backtest.json 生成 HTML 研报（数据注入模板，避免手写JS数据出错）。
产出 reports/Dual_Thrust区间突破策略研究报告.html
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(ROOT, "reports")
DATA = json.load(open(os.path.join(REPORTS, "dual_thrust_backtest.json"), encoding="utf-8"))
CD = json.load(open(os.path.join(REPORTS, "_chartdata.json"), encoding="utf-8"))


def eq_points(ver):
    pts = CD["main"][ver]["equity"]
    return [[p[0], p[1] / 1_000_000] for p in pts]


# --- 图表数据 ---
chart = {
    "dates": [p[0] for p in CD["main"]["original"]["equity"]],
    "orig": [round(p[1], 2) for p in CD["main"]["original"]["equity"]],
    "trendstop": [round(p[1], 2) for p in CD["main"]["trendstop"]["equity"]],
    "buyhold": [round(p[1], 2) for p in CD["main"]["buy_hold"]["equity"]],
    "years": sorted(y for y, v in CD["main"]["original"]["yearly"].items()
                    if v is not None),
    "yearDT": [round(CD["main"]["original"]["yearly"][y] * 100, 2)
               for y in sorted(y for y, v in CD["main"]["original"]["yearly"].items() if v is not None)],
    "yearBH": [round(CD["main"]["buy_hold"]["yearly"][y] * 100, 2)
               for y in sorted(y for y, v in CD["main"]["buy_hold"]["yearly"].items() if v is not None)],
    "grid": CD["grid"],
    "cost": CD["cost"],
    "rows": CD["rows"],
}

DATA_JS = json.dumps(chart, ensure_ascii=False, separators=(",", ":"))

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dual Thrust 区间突破策略研究报告 · 巧未来-波龙量化</title>
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
.tldr ol{margin:8px 0;padding-left:24px}
.tldr li{margin:8px 0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:12px;margin:18px 0}
.kpi{background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.kpi .lbl{font-size:12px;color:var(--sub)}
.kpi .val{font-size:22px;font-weight:700;margin-top:4px}
.red{color:var(--up)!important}.green{color:var(--down)!important}.blue{color:var(--accent)!important}
table{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0;background:#fff}
th,td{border:1px solid var(--line);padding:8px 10px;text-align:center}
th{background:#eef3fa;color:#2b3a55;font-weight:600}
td.l,th.l{text-align:left}
tr:nth-child(even) td{background:#fafbfd}
.chart{width:100%;height:380px}
.note{background:var(--warnbg);border-left:4px solid var(--warn);padding:12px 16px;border-radius:8px;margin:12px 0;font-size:14px}
.formula{background:#0f1c33;color:#d8e6ff;border-radius:10px;padding:18px 22px;font-family:Consolas,Monaco,monospace;font-size:14px;overflow-x:auto}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:820px){.two{grid-template-columns:1fr}header h1{font-size:23px}}
.toggle{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;margin-bottom:8px}
.toggle button{border:0;background:#fff;padding:6px 14px;cursor:pointer;color:var(--sub);font-size:13px}
.toggle button.on{background:var(--accent);color:#fff}
.disclaimer{background:#fff4f4;border:1px solid #f0c9c9;color:#8b2e2e;border-radius:10px;padding:16px 20px;margin-top:34px;font-size:13px}
code{background:#eef1f5;padding:1px 6px;border-radius:4px;font-size:12px}
footer{text-align:center;color:var(--sub);font-size:12px;margin-top:30px}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Dual Thrust 区间突破策略研究报告</h1>
  <div class="meta">巧未来-波龙量化 · 报告日期 2026-11-20 · 数据截止 2026-11-20（东方财富真实前复权日K）</div>
</header>

<div class="card tldr">
<h2 style="margin-top:0;border:none;padding:0">〇、一页结论</h2>
<div class="kpis">
  <div class="kpi"><div class="lbl">沪深300ETF 原始版总收益</div><div class="val red">−12.49%</div></div>
  <div class="kpi"><div class="lbl">同期买入持有</div><div class="val red">+43.1%</div></div>
  <div class="kpi"><div class="lbl">原始版胜率</div><div class="val">34.0%</div></div>
  <div class="kpi"><div class="lbl">36组参数中位数收益</div><div class="val green">−3.4%</div></div>
  <div class="kpi"><div class="lbl">前视偏差虚高收益</div><div class="val red">+3258%</div></div>
  <div class="kpi"><div class="lbl">修复后真实收益</div><div class="val green">−12.49%</div></div>
</div>
<ol>
<li><b>策略本质</b>：用过去 N 日高低收构造自适应区间 <code>Range=Max(HH−LC,HC−LL)</code>，以今开 ± K×Range 设上下轨，上破做多、下破做空/反手。参数少、逻辑透明、区间随波动自动缩放。</li>
<li><b>收益结构</b>：经典实证中胜率多在 30–50%、盈亏比 1.3–4 倍，是"低胜率高盈亏比"的趋势捕捉器，不是稳定赚钱策略。</li>
<li><b>A股实测偏负面</b>：6 标的原始版全部跑输各自买入持有；沪深300ETF −12.49%，中证500ETF −49.7%；仅茅台/五粮液/中国平安为正但远不如持有。</li>
<li><b>改进有限</b>：加 5% 止损或 MA20 过滤把沪深300ETF 改善到 −1.2%~+6.5%，但 5 段折外仍仅 2/5 段为正。</li>
<li><b>参数决定成败</b>：最优 N10/K1=0.3/K2=0.7 为 +49%，最差 N3/K=0.3 为 −54.5%；<b>大 N、宽阈值、K2≥K1 更适配 A 股</b>。</li>
<li><b>成本吞噬收益</b>：滑点 0→0.2%，11 年累计收益从 +4.6% 掉到 −26.8%。</li>
<li><b>工程警示</b>：本次发现并修复回测引擎前视偏差（收盘信号用当日开盘成交），修复后收益从 +3258% 回落到 −12.49%。<b>任何回测结论先验证成交时序。</b></li>
</ol>
</div>

<div class="note"><b>落地判断</b>：A 股现货日线上，Dual Thrust 原版<b>不适合单独使用</b>；其价值在期货/商品多品种组合 + 趋势过滤 + 严格资金管理。在波龙系统中定位为"突破类策略插件 + 组合分量"，而非独立盈利系统。</div>

<h2>一、策略是什么：来源与核心思想</h2>
<div class="card">
<h3>1.1 历史出处</h3>
<p>Dual Thrust 由 Michael Chalek 于 20 世纪 80 年代开发，是海外经典日内趋势跟踪系统，曾被《Future Truth》杂志列入"最赚钱策略"之列（该荣誉原始评选口径难溯源，宜作历史注脚）。广泛用于股票、股指期货、商品期货、外汇市场。</p>
<h3>1.2 核心公式：区间自适应</h3>
<div class="formula">HH = 过去N日最高价的最高值     LC = 过去N日收盘价的最低值
HC = 过去N日收盘价的最高值     LL = 过去N日最低价的最低值

Range    = Max( HH − LC , HC − LL )
BuyLine  = 今日开盘价 + K1 × Range
SellLine = 今日开盘价 − K2 × Range     (K1/K2 可不对称)</div>
<p><b>为什么交叉配对？</b> <code>HH−LC</code> 度量多头冲高的极限空间，<code>HC−LL</code> 度量空头下砸的极限空间。取较大值让通道覆盖两方向极端波动，实现"大行情大突破、小行情小突破"。</p>
<p><b>为什么用开盘价作锚？</b> 开盘价是日内第一个已知价格，可把隔夜信息排除在区间判断外——这也是原版要求收盘平仓、不持仓过夜的原因。</p>
<table>
<tr><th>维度</th><th class="l">Dual Thrust</th><th class="l">海龟/唐奇安</th><th class="l">布林带</th></tr>
<tr><td>区间基准</td><td class="l">开盘价 ± K×复合Range</td><td class="l">前 N 日高/低点</td><td class="l">均线 ± σ</td></tr>
<tr><td>波动适应</td><td class="l">HH/LC/HC/LL 交叉配对</td><td class="l">仅高低点</td><td class="l">标准差</td></tr>
<tr><td>方向</td><td class="l">反转系统（反手）</td><td class="l">趋势跟随</td><td class="l">回归/突破</td></tr>
</table>
</div>

<h2>二、交易运行逻辑：逐日怎么跑</h2>
<div class="card">
<h3>2.1 原版规则（日内、可双向）</h3>
<ol>
<li><b>开盘</b>：用过去 N 日算 HH/LC/HC/LL 与 Range，定出今日上轨 BuyLine、下轨 SellLine。</li>
<li><b>无持仓</b>：上破上轨开多；下破下轨开空。</li>
<li><b>持多</b>：下破下轨 → 平多并同价反手开空。</li>
<li><b>持空</b>：上破上轨 → 平空并同价反手开多。</li>
<li><b>收盘</b>：清空所有仓位，不隔夜。</li>
</ol>
<p>原版没有独立止损，<b>反手即止损</b>——亏损被截断在下一个反向突破处。趋势行情中始终站对边；震荡中反复反手就是"左右挨耳光"，成本快速累积。</p>
<h3>2.2 A 股适配改造（本项目实现）</h3>
<table>
<tr><th>环节</th><th class="l">原版（期货日内）</th><th class="l">波龙 A 股日线版</th></tr>
<tr><td>区间计算</td><td class="l">过去 N 日，今开为锚</td><td class="l">过去 N 日（<b>不含当日</b>，防未来函数），今开为锚</td></tr>
<tr><td>信号确认</td><td class="l">盘中触及上下轨</td><td class="l"><b>收盘价</b>确认突破（过滤盘中假突破）</td></tr>
<tr><td>成交时点</td><td class="l">突破即刻</td><td class="l">T 日收盘信号 → <b>T+1 开盘成交</b></td></tr>
<tr><td>方向</td><td class="l">多空反手</td><td class="l"><b>只做多</b>；SELL 仅平多不开空</td></tr>
<tr><td>止损/过滤</td><td class="l">靠反手 / 无</td><td class="l">可选 5% 止损 + MA20 趋势过滤（默认关）</td></tr>
<tr><td>成本</td><td class="l">期货手续费</td><td class="l">佣金万2.5 + 印花税万5(卖) + 过户费万0.1 + 滑点</td></tr>
</table>
<h3>2.3 伪代码</h3>
<div class="formula">每日收盘后：
  past   = bars[i-N : i]              # 不含当日，防未来
  Range  = max(max(past.high)-min(past.close),
               max(past.close)-min(past.low))
  Buy    = bars[i].open + K1*Range
  Sell   = bars[i].open - K2*Range

  if 持仓 and stop&gt;0 and close &lt;= 信号价*(1-stop):  SELL(止损)
  elif close &gt;= Buy:
      if 趋势过滤 and close &lt; MA20:  HOLD
      else:                            BUY
  elif close &lt;= Sell and 持仓:       SELL
  else:                                 HOLD

下一交易日开盘：按信号成交（涨停不买、跌停不卖、100股整手）</div>
</div>

<h2>三、实测设计</h2>
<div class="card">
<p><b>数据</b>：东方财富 push2his 真实前复权日K，拉取于 2026-11-20。样本 6 标的，重叠区间 2016-01-04 ~ 2026-11-20。前复权早期个股出现非正价格（除权的数学结果），裁掉最后一个非正价格日之前的段，再经 OHLC 一致性校验。</p>
<table>
<tr><th>标的</th><th>代码</th><th>真实K线</th><th>区间</th></tr>
<tr><td>沪深300ETF</td><td>510300.SH</td><td>2643</td><td>2016-01-04~2026-11-20</td></tr>
<tr><td>中证500ETF</td><td>510500.SH</td><td>2643</td><td>2016-01-04~2026-11-20</td></tr>
<tr><td>沪深300指数</td><td>000300.SH</td><td>2643</td><td>2016-01-04~2026-11-20</td></tr>
<tr><td>贵州茅台</td><td>600519.SH</td><td>2459</td><td>2016-10-10~2026-11-20</td></tr>
<tr><td>五粮液</td><td>000858.SZ</td><td>2524</td><td>2016-06-30~2026-11-20</td></tr>
<tr><td>中国平安</td><td>601318.SH</td><td>2643</td><td>2016-01-04~2026-11-20</td></tr>
</table>
<div class="note"><b>重大工程发现：前视偏差修复</b>　旧引擎用"第 i 日收盘信号 + 第 i 日开盘价成交"，等于偷看当天。修正为"收盘信号 → 次日开盘成交"后，沪深300ETF 原始版收益从虚高的 <b class="red">+3258%</b>（年化38%、胜率86%、回撤仅−17%）回落到真实的 <b class="green">−12.49%</b>（年化−1.22%、胜率34%、回撤−43%）。<b>成交时序是所有回测结论的前提。</b></div>
<p><b>测试矩阵</b>：4 个策略版本（原始 / 趋势过滤 / 5%止损 / 趋势+止损）+ 买入持有；绩效含收益/回撤/夏普/卡玛/胜率/盈亏比；5 段等分折外（稳健分=0.6×中位+0.4×最差）；36 组参数网格；4 档滑点；双均线与海龟对照。</p>
</div>

<h2>四、实测结果</h2>
<div class="card">
<h3>4.1 净值曲线（沪深300ETF，归一化）</h3>
<div class="toggle" id="eqToggle"><button class="on" data-t="line">折线</button><button data-t="table">数据表</button></div>
<div id="eqChart" class="chart"></div>
<div id="eqTable" style="display:none;max-height:320px;overflow:auto"></div>
<p style="color:var(--sub);font-size:13px">数据来源：东方财富真实前复权日K，波龙统一引擎回测，取数 2026-11-20；含真实费用与 0.1% 滑点。</p>

<h3>4.2 分年度收益对比（沪深300ETF）</h3>
<div id="yearChart" class="chart" style="height:340px"></div>

<h3>4.3 各标的 × 各版本总收益</h3>
<div id="barChart" class="chart" style="height:420px"></div>
<table id="perfTable"></table>

<h3>4.4 五段折外稳健性（沪深300ETF 原始版）</h3>
<div id="foldChart" class="chart" style="height:320px"></div>
<p>稳健分 = 0.6×中位数 + 0.4×最差段 = <b class="green">−0.1279</b>，仅 2/5 段为正。贵州茅台 5% 止损版是唯一稳健分转正样本（+0.0719，4/5 段为正），但同期买入持有收益是它的 9 倍。</p>

<h3>4.5 参数敏感性（沪深300ETF，36 组）</h3>
<div id="gridChart" class="chart" style="height:360px"></div>
<p><b>规律</b>：① N 越大越好（10 日远好于 3 日）；② K 越大越好（宽阈值减少交易）；③ K2≥K1 更好（给向下突破更高门槛，适配 A 股"慢涨急跌"）。36 组仅 15 组为正，默认 N5/K0.5 落在中位数偏下。最优 +49% 与最差 −54.5% 相差 103 个百分点——<b>请选参数平面的平缓区，不要追尖峰</b>。</p>

<h3>4.6 成本敏感性</h3>
<div id="costChart" class="chart" style="height:320px"></div>
<p>每增加 0.05% 单边滑点，11 年累计收益蒸发约 9 个百分点。94 笔交易 × 双向 ≈ 188 次摩擦，成本线性累积。</p>

<h3>4.7 对照策略（沪深300ETF）</h3>
<table>
<tr><th>策略</th><th>总收益</th><th>年化</th><th>最大回撤</th><th>夏普</th><th>交易数</th></tr>
<tr><td class="l">Dual Thrust 原始</td><td class="green">−12.49%</td><td class="green">−1.22%</td><td class="green">−43.38%</td><td class="green">−0.151</td><td>94</td></tr>
<tr><td class="l">双均线(5,20)</td><td class="green">−20.0%</td><td class="green">−2.04%</td><td class="green">−44.8%</td><td class="green">−0.213</td><td>87</td></tr>
<tr><td class="l">海龟(20,10)</td><td class="red">+18.91%</td><td class="red">+1.61%</td><td>−26.47%</td><td>+0.031</td><td>40</td></tr>
<tr><td class="l"><b>买入持有</b></td><td class="red"><b>+43.1%</b></td><td class="red">+3.4%</td><td>−43.6%</td><td>0.166</td><td>0</td></tr>
</table>
</div>

<h2>五、文献实证对照（分层看证据）</h2>
<div class="card">
<p style="color:var(--sub);font-size:13px">以下为公开研报/媒体回测，各研究区间、成本、杠杆口径不一，<b>数字不可直接横比</b>，只作量级与方向参考；均为非一手来源，研报数字需核实原文。</p>
<h3>5.1 股指期货——证据最完整（何诚颖，2014-01~2015-09，409交易日，Wind数据）</h3>
<table>
<tr><th>指标</th><th>原始参数</th><th>参数优化</th><th>时变参数</th></tr>
<tr><td class="l">交易次数</td><td>135</td><td>199</td><td>197</td></tr>
<tr><td class="l">胜率</td><td>45.93%</td><td>43.22%</td><td>46.19%</td></tr>
<tr><td class="l">盈亏比</td><td>1.44</td><td>1.65</td><td>1.74</td></tr>
<tr><td class="l">累计利润</td><td>100.2万</td><td>138.0万</td><td>145.2万</td></tr>
<tr><td class="l">最大回撤</td><td class="green">−23.05%</td><td class="green">−14.79%</td><td class="green">−11.98%</td></tr>
</table>
<p>分阶段：震荡段（200日,+5.39%）原始胜率仅 <b>39.44%</b>；单边上涨段（153日,+117.1%）47.92%；股灾段（49日,−29.9%）68.75%。收益改善主要来自"平均单次亏损下降"而非胜率提升。</p>
<h3>5.2 商品期货组合——主流正面证据</h3>
<table>
<tr><th class="l">来源（口径）</th><th class="l">结果</th></tr>
<tr><td class="l">东方证券《国内商品期货常用日内CTA策略测试》2012–2016推进式</td><td class="l">累计+99.52%，年化17.32%，夏普1.383，回撤−8.84%，胜率57.46%；仅螺纹/橡胶/白糖等波动大品种仍有效</td></tr>
<tr><td class="l">湘财证券 CTA 跟踪周报，8品种组合，2016-01~2025-03</td><td class="l">年化32.22%，回撤11.44%，夏普1.90；ATR止损系数0.5+赔率2；2025-03进入回撤区间</td></tr>
<tr><td class="l">中信期货《国内商品期货日内策略初探》2022</td><td class="l">仅优化后的 DT/ATR/收盘价比例"表现尚可"；胜率约50%、盈亏比约1，组合卡玛比率&lt;1，交易费用占比大</td></tr>
<tr><td class="l">申万研报口径（新浪财经转载）</td><td class="l">统一参数原始年化近30%、回撤12%；分品种调参升至46%；加差异化止盈止损回撤降至17%；ATR过滤夏普1.94</td></tr>
</table>
<h3>5.3 A股指数/ETF 与其它市场——效果最弱</h3>
<table>
<tr><th class="l">来源（口径）</th><th class="l">结果</th></tr>
<tr><td class="l">回测宝：沪深300一年，日线，N=4,K=0.5,止损8%</td><td class="l">累计+2.87%，夏普0.28，回撤−10.62%，胜率46.7%</td></tr>
<tr><td class="l">申万宏源：多指数2010–2016，默认N=5,K=0.7</td><td class="l">多数指数一般或亏损；优化到N=13,K1=0.505,K2=0.460后沪深300年化10.4%、回撤6%、夏普0.821</td></tr>
<tr><td class="l">掘金量化示例：K=0.2 vs K=0.5，不同窗口</td><td class="l">同参数换窗口，年化从+52%变−24%——回测区间影响远大于参数</td></tr>
<tr><td class="l">50ETF期权实证 / 比特币2016日线</td><td class="l">期权样本外单日回撤超15%；比特币同期双均线+84.6%、海龟+94.4%，DT明显落后</td></tr>
</table>
<p style="color:var(--sub);font-size:12px">来源：财新博客何诚颖、同花顺SuperMind、东方证券研究所、湘财证券研究所、中信期货研究所、新浪财经研报频道、回测宝、掘金量化、BigQuant（检索于2026-11-20）。</p>
</div>

<h2>六、为什么在 A 股日线上失效：归因</h2>
<div class="card">
<ol>
<li><b>信号滞后是结构性代价</b>：收盘确认→次日开盘成交吃掉突破初始涨幅；跳空高开直接越轨，次日开盘买入等于买在高位。</li>
<li><b>震荡市反复反手</b>：A 股宽基长期宽幅震荡，94 笔交易中 66 笔亏损，成本+滑点持续磨损。</li>
<li><b>只做多限制下行保护</b>：原版靠反手做空在下跌中获利，A 股现货版只能离场，失去一半收益来源。</li>
<li><b>日线颗粒度不匹配</b>：Dual Thrust 原生是日内策略（今开锚定、盘中突破、收盘平仓），改为日线后逻辑内核被稀释。</li>
<li><b>趋势性个股是例外</b>：茅台/五粮液为正（但仍跑输买入持有），印证"策略适合趋势连续、流动性好的品种"。</li>
</ol>
<p><b>反面观点自检</b>：有人说"加趋势过滤和止损就能救活"。实测把沪深300ETF 从 −12.5% 改善到 +6.0%，但折外仍仅 2/5 段为正，同期买入持有 +43%。<b>改进能减亏，改变不了策略与标的的不匹配。</b></p>
</div>

<h2>七、落地建议（给波龙系统）</h2>
<div class="card">
<h3>7.1 定位</h3>
<p>❌ 不要把原版当 A 股现货独立盈利策略。✅ 定位为：①突破类策略插件（已接入，注册名 <code>dual_thrust</code>）；②多品种 CTA 组合的一个分量；③风控/趋势模块的信号源。</p>
<h3>7.2 若用于 A 股现货</h3>
<p>选稳健区而非默认尖峰：N=7~10，K1=0.5~0.7，K2≥K1，强制开 5% 止损 + MA20 过滤；即便如此也要接受长期跑输买入持有的可能。</p>
<h3>7.3 若用于期货/期权</h3>
<ul>
<li>用真正的日内分钟数据实现原版逻辑，而非日线近似。</li>
<li>处理主力换月、保证金、手续费口径；优先波动大、趋势连续的品种并做多品种等权组合。</li>
<li>加 ATR 止损（系数0.5）+ 赔率2止盈——这是文献中高绩效研究的共同前提。</li>
<li>成本按单边 fee 0.0002 + slip 0.0002 起步压力测试；单笔成本占预期盈利&gt;20% 的参数直接放弃。</li>
</ul>
<h3>7.4 工程纪律（本次最重要沉淀）</h3>
<ol>
<li><b>回测引擎成交时序必须独立验证</b>——本次前视偏差让收益虚高 3000+ 个百分点。建议把"信号日 vs 成交日"写成单元测试。</li>
<li>任何策略结论都要过 5 段折外 + 成本敏感性双关，只看全样本收益等于没看。</li>
<li>策略插件化注册，UI 可切换、参数可调、结果可追溯（数据契约哈希）。</li>
</ol>
</div>

<h2>八、交付物与复现</h2>
<div class="card">
<table>
<tr><th class="l">文件</th><th class="l">说明</th></tr>
<tr><td class="l"><code>core/strategy/breakout.py</code></td><td class="l">Dual Thrust 策略插件（趋势过滤/止损开关，已注册）</td></tr>
<tr><td class="l"><code>core/research/engine.py</code></td><td class="l">修复前视偏差：信号延迟一根 bar 到次日开盘成交</td></tr>
<tr><td class="l"><code>scripts/research_dual_thrust.py</code></td><td class="l">真实数据实测脚本（6标的/36参数/折外/成本）</td></tr>
<tr><td class="l"><code>reports/dual_thrust_backtest.json</code></td><td class="l">完整回测原始数据（含数据契约哈希）</td></tr>
<tr><td class="l"><code>reports/Dual_Thrust区间突破策略研究报告.md/.html</code></td><td class="l">本报告两个版本</td></tr>
</table>
<p>复现：<code>cd qiaoweilai-bowlong-quant &amp;&amp; python scripts/research_dual_thrust.py</code></p>
</div>

<div class="disclaimer"><b>免责声明</b>：以上内容基于公开数据和量化分析，仅供参考，不构成投资建议。市场有风险，投资需谨慎。任何投资决策应结合个人风险承受能力、资金状况和投资目标独立判断，必要时咨询持牌专业机构。过往表现不预示未来收益。</div>
<footer>巧未来-波龙量化 · Dual Thrust 研究报告 · 数据截止 2026-11-20</footer>
</div>

<script>
var D = __DATA__;
var RED = '#d9363e', GREEN = '#2ea121', BLUE = '#1f5fbf';
function mk(id, opt){ var el = document.getElementById(id); if(!el || typeof echarts==='undefined') return; var c = echarts.init(el); c.setOption(opt); window.addEventListener('resize', function(){c.resize();}); return c; }

// 净值曲线
mk('eqChart', {
  tooltip:{trigger:'axis'},
  legend:{data:['原始DT','趋势+止损','买入持有'],top:0},
  grid:{left:55,right:20,top:36,bottom:60},
  xAxis:{type:'category',data:D.dates,axisLabel:{interval:Math.floor(D.dates.length/8)}},
  yAxis:{type:'value',name:'净值(倍)',scale:true},
  series:[
    {name:'原始DT',type:'line',data:D.orig,showSymbol:false,lineStyle:{color:GREEN,width:2},itemStyle:{color:GREEN}},
    {name:'趋势+止损',type:'line',data:D.trendstop,showSymbol:false,lineStyle:{color:'#e6a23c',width:1.5},itemStyle:{color:'#e6a23c'}},
    {name:'买入持有',type:'line',data:D.buyhold,showSymbol:false,lineStyle:{color:BLUE,width:2},itemStyle:{color:BLUE},areaStyle:{color:'rgba(31,95,191,.06)'}}
  ]
});
// 净值数据表
(function(){
  var h='<table><tr><th>日期</th><th>原始DT</th><th>趋势+止损</th><th>买入持有</th></tr>';
  for(var i=0;i<D.dates.length;i++){h+='<tr><td>'+D.dates[i]+'</td><td>'+D.orig[i].toFixed(2)+'</td><td>'+D.trendstop[i].toFixed(2)+'</td><td>'+D.buyhold[i].toFixed(2)+'</td></tr>';}
  document.getElementById('eqTable').innerHTML=h+'</table>';
  var box=document.getElementById('eqToggle');
  box.addEventListener('click',function(e){
    if(e.target.tagName!=='BUTTON')return;
    var t=e.target.getAttribute('data-t');
    Array.prototype.forEach.call(box.children,function(b){b.className = (b===e.target)?'on':'';});
    document.getElementById('eqChart').style.display = t==='line'?'block':'none';
    document.getElementById('eqTable').style.display = t==='table'?'block':'none';
  });
})();
// 分年度
mk('yearChart',{
  tooltip:{trigger:'axis'},legend:{data:['原始DT','买入持有'],top:0},
  grid:{left:55,right:20,top:36,bottom:40},
  xAxis:{type:'category',data:D.years},
  yAxis:{type:'value',name:'收益(%)'},
  series:[
    {name:'原始DT',type:'bar',data:D.yearDT.map(function(v){return {value:v,itemStyle:{color:v>=0?RED:GREEN}};})},
    {name:'买入持有',type:'bar',data:D.yearBH.map(function(v){return {value:v,itemStyle:{color:v>=0?'#f3a6a9':'#8fd18a'}};})}
  ]
});
// 各标的各版本
var codes=[],names={};
D.rows.forEach(function(r){if(codes.indexOf(r.code)<0){codes.push(r.code);names[r.code]=r.name;}});
var vers=['original','trend','stop','trendstop','buy_hold'];
var vlabel={original:'原始',trend:'趋势过滤',stop:'5%止损',trendstop:'趋势+止损',buy_hold:'买入持有'};
var barSeries=vers.map(function(v){
  return {name:vlabel[v],type:'bar',data:codes.map(function(c){
    var f=D.rows.filter(function(r){return r.code===c&&r.ver===v;})[0];
    return f?{value:Math.round(f.ret*10000)/100,itemStyle:{color:f.ret>=0?RED:GREEN}}:0;
  })};
});
mk('barChart',{
  tooltip:{trigger:'axis'},legend:{data:vers.map(function(v){return vlabel[v];}),top:0},
  grid:{left:55,right:20,top:36,bottom:50},
  xAxis:{type:'category',data:codes.map(function(c){return names[c];})},
  yAxis:{type:'value',name:'总收益(%)'},
  series:barSeries
});
(function(){
  var h='<tr><th>标的</th><th>版本</th><th>总收益</th><th>年化</th><th>回撤</th><th>夏普</th><th>交易</th><th>胜率</th></tr>';
  D.rows.forEach(function(r){
    var ann=(Math.pow(1+r.ret,1/10.9)-1)*100;
    h+='<tr><td class="l">'+r.name+'</td><td>'+vlabel[r.ver]+'</td><td class="'+(r.ret>=0?'red':'green')+'">'+(r.ret*100).toFixed(1)+'%</td><td>'+ann.toFixed(1)+'%</td><td class="green">'+(r.mdd*100).toFixed(1)+'%</td><td>'+r.sharpe.toFixed(3)+'</td><td>'+r.trades+'</td><td>'+(r.win*100).toFixed(1)+'%</td></tr>';
  });
  document.getElementById('perfTable').innerHTML=h+'</table>';
})();
// 折外分段
var folds = __FOLDS__;
mk('foldChart',{
  tooltip:{trigger:'axis'},grid:{left:55,right:20,top:30,bottom:50},
  xAxis:{type:'category',data:folds.details.map(function(d){return d.start.slice(0,7)+'~'+d.end.slice(0,7);}),axisLabel:{rotate:18,fontSize:10}},
  yAxis:{type:'value',name:'段收益(%)'},
  series:[{type:'bar',data:folds.details.map(function(d){return {value:Math.round(d.ret*10000)/100,itemStyle:{color:d.ret>=0?RED:GREEN}};}),label:{show:true,position:'top',formatter:function(p){return p.value+'%';}}}]
});
// 参数网格：按 N 分组散点
var gD=D.grid.slice();
var ns=[3,5,7,10].map(function(n){return gD.filter(function(r){return r.N===n;});});
mk('gridChart',{
  tooltip:{trigger:'item',formatter:function(p){return 'N='+p.data[3]+' K1='+p.data[4]+' K2='+p.data[5]+'<br/>收益 '+p.data[2]+'%';}},
  legend:{data:['N=3','N=5','N=7','N=10'],top:0},
  grid:{left:55,right:20,top:36,bottom:45},
  xAxis:{type:'value',name:'K1'},yAxis:{type:'value',name:'收益(%)'},
  series:ns.map(function(arr,i){
    return {name:'N='+[3,5,7,10][i],type:'scatter',symbolSize:9,
      data:arr.map(function(r){return [r.K1,Math.round(r.total_return*10000)/100,r.total_return,r.N,r.K1,r.K2];}),
      itemStyle:{color:['#999','#e6a23c',BLUE,'#8b5cf6'][i]}};
  })
});
// 成本敏感性
mk('costChart',{
  tooltip:{trigger:'axis'},grid:{left:55,right:20,top:30,bottom:45},
  xAxis:{type:'category',data:D.cost.map(function(c){return (c.slippage*10000)/100+'%';})},
  yAxis:{type:'value',name:'总收益(%)'},
  series:[{type:'line',data:D.cost.map(function(c){return Math.round(c.total_return*10000)/100;}),smooth:false,
    lineStyle:{color:GREEN,width:2},itemStyle:{color:GREEN},label:{show:true,position:'top',formatter:'{c}%'}}]
});
</script>
</body>
</html>
"""

FOLDS = CD["main"]["original"]["fold5"]
html = HTML.replace("__DATA__", DATA_JS).replace("__FOLDS__", json.dumps(FOLDS, ensure_ascii=False, separators=(",", ":")))
out_path = os.path.join(REPORTS, "Dual_Thrust区间突破策略研究报告.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
# 抽取内联 JS 供语法校验
js = html.split("<script>", 1)[1].split("</script>", 1)[0]
with open(os.path.join(REPORTS, "_check.js"), "w", encoding="utf-8") as f:
    f.write(js)
print("[OK] HTML:", out_path)
print("[OK] JS 校验文件:", os.path.join(REPORTS, "_check.js"), "长度", len(js))
