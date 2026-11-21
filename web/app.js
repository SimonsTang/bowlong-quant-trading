/* 巧未来-波龙量化 · 前端交互（零依赖） */
const $ = id => document.getElementById(id);
const MODE_LABELS = {
  backtest: 'BACKTEST · 仅研究回测',
  paper: 'PAPER · 模拟/校验，不产生真实委托',
  live: 'LIVE · 真实报单模式',
};
const modeLabel = m => MODE_LABELS[m] || '';
let strategies = [], selectedStrategy = 'dual_ma', selectedParams = {};
let equityData = null, klineData = null;
let currentPeriod = '1d', currentCode = '600519';
// K线视图：count=当前显示根数，offset=右端向前偏移的根数（0表示最新）
let klineView = {count: 60, offset: 0};
let klineMaParams = [5, 10, 20];
const MA_COLORS = ['#f0a020', '#a78bfa', '#4dd0e1'];
let lastResult = null; // 最近一次运行结果，供仪表盘结果回报窗口展示
let lastSelectionPayload = null; // 最近一次选股原始结果，供「送入一条龙」复用
let selTimer = null;             // 选股超时提示定时器
let selPct = 5;                  // 选股进度（单调递增，阶段切换不回退）
let lastOptimizeResult = null;   // 最近一次寻优结果，供「应用参数」回写

// ---------- 导航 ----------
const titles = {dashboard:'总览仪表盘',market:'实时行情',multimarket:'多市场品种',strategy:'策略库',selector:'全市场选股',rotation:'有效策略·ETF轮动',backtest:'回测中心',pipeline:'全链路工作流',compliance:'风控与合规',ai:'AI 助手',config:'系统配置'};
document.querySelectorAll('.nav-item').forEach(el => {
  el.onclick = () => {
    document.querySelectorAll('.nav-item').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.page').forEach(x => x.classList.remove('active'));
    el.classList.add('active');
    $('page-' + el.dataset.page).classList.add('active');
    $('page-title').textContent = titles[el.dataset.page];
    if (el.dataset.page === 'compliance') loadCompliance();
    if (el.dataset.page === 'multimarket') mmLoadInstruments();
    if (el.dataset.page === 'selector') initSelectorStrategies();
    if (el.dataset.page === 'rotation' && !window._rotLoaded) runRotation();
    if (el.dataset.page === 'config' && typeof initConfig === 'function') initConfig();
  };
});

// ---------- 初始化 ----------
async function init() {
  setInterval(() => { $('clock').textContent = new Date().toLocaleTimeString('zh-CN'); }, 1000);
  $('clock').textContent = new Date().toLocaleTimeString('zh-CN');
  try {
    const st = await (await fetch('/api/status')).json();
    $('contract').textContent = st.engine_contract;
    $('m-contract').textContent = st.engine_contract;
    $('m-ai').textContent = st.cloud_ai ? '已接入' : '本地降级';
    $('m-ai-model').textContent = st.cloud_ai ? st.model : '配置 QIAO_API_KEY 接入云端LLM';
    $('ai-source').textContent = st.cloud_ai ? st.model : '本地降级';
    $('side-ai').textContent = st.cloud_ai ? st.model : '本地降级';
    if (!st.cloud_ai) $('ai-dot').classList.add('warn');
    $('mode-badge').textContent = st.market_mode;
    // 从配置中心读取真实模式（backtest / paper / live）
    fetch('/api/config/status').then(r => r.json()).then(cs => {
      $('mode-badge').textContent = modeLabel(cs.mode) || st.market_mode;
      $('mode-badge').className = cs.mode === 'live' ? 'badge' : 'badge green';
      $('mode-badge').style.color = cs.mode === 'live' ? 'var(--up)' : '';
      $('mode-badge').style.borderColor = cs.mode === 'live' ? 'var(--up)' : '';
      if (typeof updateConfigBadge === 'function') updateConfigBadge(cs);
    }).catch(() => {});
  } catch(e) {}
  try {
    strategies = await (await fetch('/api/strategies')).json();
    $('m-strategies').textContent = strategies.length + ' 个';
    const opts = strategies.map(s => `<option value="${s.name}">${s.display}</option>`).join('');
    ['bt-strategy','pl-strategy','combo-strategy','opt-strategy'].forEach(id => {
      const el = $(id); if (!el) return;
      el.innerHTML = opts;
      el.value = selectedStrategy;
      // 任何页面的策略下拉框改变，都同步为当前策略库选中项，保证参数面板一致
      el.onchange = () => { selectedStrategy = el.value; syncStrategySelection(); renderParams(); };
    });
  } catch(e) {
    $('sys-hint').innerHTML = '⚠ 后端服务未连接：请先在命令行运行 <b>python web/server.py</b>，然后刷新本页。所有功能依赖本地服务。';
    $('sys-hint').style.color = 'var(--up)';
  }
  if (typeof initSelectorStrategies === 'function') initSelectorStrategies();
  renderStrategies();
  loadEvents();
  subscribeSSE();
  loadHealth();
  loadLastResult();
  // 首次使用引导（异步，不阻塞主界面）
  if (typeof maybeShowOnboarding === 'function') {
    fetch('/api/config/status').then(r => r.json()).then(st => maybeShowOnboarding(st)).catch(() => {});
  }
}

// ---------- 恢复持久化的最近结果 ----------
async function loadLastResult(force) {
  try {
    const saved = await (await fetch('/api/last_result')).json();
    if (force) lastResult = null;
    if (!saved || !saved.kind || lastResult) return;
    const d = saved.data;
    if (saved.kind === 'backtest') {
      lastResult = {kind:'回测', title:`${d.code} · ${d.strategy}`, summary:d.summary,
                    equity:d.equity, timestamp:saved.ts};
    } else if (saved.kind === 'select') {
      lastResult = {kind:'选股', title:`全市场选股 · 选出${d.picks.length}只`, picks:d.picks,
                    universe:d.universe_size, timestamp:saved.ts};
    } else if (saved.kind === 'compare') {
      const ok = d.results.filter(x=>!x.error);
      if (!ok.length) return;
      lastResult = {kind:'对比', title:`${d.code} · ${ok.length}策略对比`, top:ok[0], results:ok, timestamp:saved.ts};
    } else if (saved.kind === 'pipeline') {
      lastResult = {kind:'全链路', title:`${d.code} · ${d.strategy}`, summary:d.summary, timestamp:saved.ts};
    } else if (saved.kind === 'portfolio') {
      lastResult = {kind:'组合回测', title:d.title || `${(d.codes||[]).length}只标的组合`,
                    summary:d.summary, equity:d.equity, timestamp:saved.ts};
    } else if (saved.kind === 'selection_pipeline') {
      lastResult = {kind:'选股一条龙', title:`${d.selector_strategy} · ${(d.selection&&d.selection.picks||[]).length}只标的`,
                    summary:d.portfolio && d.portfolio.summary, timestamp:saved.ts};
    }
    renderResultReport();
  } catch(e) {}
}

// ---------- 数据源健康监控 ----------
async function loadHealth() {
  $('health-panel').innerHTML = '<div class="subtext">探测三源连通性…</div>';
  try {
    const r = await (await fetch('/api/health')).json();
    $('health-panel').innerHTML = r.sources.map(s => `
      <div class="card" style="padding:12px">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span style="font-weight:500">${esc(s.name)}</span>
          <span class="badge ${s.ok?'green':''}" style="${s.ok?'':'color:var(--up)'}">${s.ok?'● 在线':'● 离线'}</span>
        </div>
        <div class="subtext" style="margin-top:8px">${s.ok?`现价 ${s.price} · 延迟 ${s.latency_ms}ms`:esc(s.error)}</div>
        <div class="subtext">检测于 ${esc(r.checked_at)}</div>
      </div>`).join('');
    const okN = r.sources.filter(s => s.ok).length;
    $('side-src').textContent = `${okN}/${r.sources.length} 源在线`;
    $('side-src').style.color = okN === r.sources.length ? '' : 'var(--up)';
  } catch(e) { $('health-panel').innerHTML = `<div class="subtext">检测失败: ${e}</div>`; }
}

// ---------- 渲染策略库 ----------
function renderStrategies() {
  $('strategy-list').innerHTML = strategies.map(s => `
    <div class="strategy-card ${s.name===selectedStrategy?'selected':''}" data-name="${s.name}">
      <div class="name">${s.display}</div>
      <div style="font-size:10px;color:var(--accent2)">${s.category_label} · ${s.name}</div>
      <div class="desc">${s.desc}</div>
      <div style="font-size:10px;color:var(--muted)">来源：${s.source}</div>
    </div>`).join('');
  document.querySelectorAll('.strategy-card').forEach(el => {
    el.onclick = () => {
      selectedStrategy = el.dataset.name;
      syncStrategySelection();
      renderParams();
    };
  });
  renderParams();
}
// 策略库选中项 → 所有使用交易策略的地方（回测/对比/组合/寻优/全链路）
function syncStrategySelection() {
  document.querySelectorAll('#strategy-list .strategy-card').forEach(x =>
    x.classList.toggle('selected', x.dataset.name === selectedStrategy));
  ['bt-strategy','pl-strategy','combo-strategy','opt-strategy'].forEach(id => {
    if ($(id)) $(id).value = selectedStrategy;
  });
}
function renderParams() {
  const s = strategies.find(x => x.name === selectedStrategy);
  if (!s) return;
  $('param-panel').innerHTML = `<div style="width:100%;font-size:12px;color:var(--muted);margin-bottom:6px">
    ${s.display} 可调参数：</div>` + s.params.map(p => `
    <div class="field" style="width:150px"><label>${p.desc} (${p.name})</label>
      <input type="number" id="param-${p.name}" value="${p.default}" step="${p.step}" min="${p.low}" max="${p.high}"></div>`).join('');
}
function collectParams() {
  const s = strategies.find(x => x.name === selectedStrategy);
  if (!s) return {};
  const out = {};
  s.params.forEach(p => { out[p.name] = parseFloat($('param-' + p.name).value); });
  return out;
}

// ---------- 行情 ----------
async function fetchQuote(code) {
  code = code || $('mkt-code').value.trim();
  $('mkt-code').value = code;
  currentCode = code;
  try {
    const q = await (await fetch('/api/quote?code=' + code)).json();
    if (q.error) { $('quote-cards').innerHTML = `<div class="card"><div class="subtext">${q.error}</div></div>`; return; }
    const cls = q.change_pct >= 0 ? 'up' : 'down';
    $('quote-cards').innerHTML = `
      <div class="card"><h3>${q.name} ${q.code}</h3><div class="metric ${cls}">${q.price.toFixed(2)}</div><div class="subtext ${cls}">${q.change_pct>=0?'+':''}${q.change_pct.toFixed(2)}%</div></div>
      <div class="card"><h3>今开 / 昨收</h3><div class="metric small">${q.open.toFixed(2)} / ${q.prev_close.toFixed(2)}</div><div class="subtext">数据源 ${q.source}</div></div>
      <div class="card"><h3>最高 / 最低</h3><div class="metric small">${q.high.toFixed(2)} / ${q.low.toFixed(2)}</div><div class="subtext">真实盘中数据</div></div>
      <div class="card"><h3>成交额 / 时间</h3><div class="metric small">${(q.amount/1e8).toFixed(2)}亿</div><div class="subtext">${q.ts}</div></div>`;
    await loadKline(code, currentPeriod);
    await loadF10(code);
  } catch(e) { console.error(e); }
}

// ---------- 多周期K线 ----------
async function switchPeriod(period) {
  currentPeriod = period;
  document.querySelectorAll('.period-btn').forEach(b => b.classList.toggle('active', b.dataset.period === period));
  await loadKline(currentCode, period);
}
async function loadKline(code, period) {
  try {
    const kd = await (await fetch(`/api/kline?code=${code}&period=${period}`)).json();
    if (kd.error) { $('kline-info').textContent = kd.error; return; }
    klineData = kd.rows;
    klineView.offset = 0;
    klineView.count = Math.min(60, klineData.length);
    syncMaParams();
    drawKline('kline-chart', klineData);
    updateKlineInfo();
  } catch(e) { $('kline-info').textContent = 'K线加载失败: ' + e; }
}

// ---------------- K线交互：均线参数 / 方向键缩放平移 ----------------
function syncMaParams() {
  klineMaParams = [1,2,3].map(i => {
    const el = $('ma-' + i);
    const v = el ? parseInt(el.value, 10) : [5,10,20][i-1];
    return Math.max(2, Math.min(120, isNaN(v) ? [5,10,20][i-1] : v));
  });
}
function onMaParamChange() {
  syncMaParams();
  if (klineData && klineData.length > 1) drawKline('kline-chart', klineData);
}
function resetKlineView() {
  klineView.count = Math.min(60, (klineData || []).length || 60);
  klineView.offset = 0;
  drawKline('kline-chart', klineData);
  updateKlineInfo();
}
function visibleKlineSlice(rows) {
  const total = rows.length;
  const count = Math.max(10, Math.min(total, klineView.count));
  const offset = Math.max(0, Math.min(total - count, klineView.offset));
  klineView.count = count; klineView.offset = offset;
  const end = total - offset;
  return rows.slice(Math.max(0, end - count), end);
}
function updateKlineInfo() {
  if (!klineData || !klineData.length) return;
  const pname = {'1d':'日K','1w':'周K','1M':'月K','60m':'60分钟','30m':'30分钟','5m':'5分钟'}[currentPeriod] || currentPeriod;
  const vis = visibleKlineSlice(klineData);
  $('kline-info').textContent = `${pname} · 显示 ${vis.length}/${klineData.length}根 · `
    + `${vis[0].date} 至 ${vis[vis.length-1].date} · MA ${klineMaParams.join('/')}`;
}
document.addEventListener('keydown', e => {
  if (!klineData || !$('page-market') || !$('page-market').classList.contains('active')) return;
  const tag = (e.target && e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
  if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)) return;
  e.preventDefault();
  const total = klineData.length;
  if (e.key === 'ArrowUp') klineView.count = Math.round(klineView.count * 0.8);
  if (e.key === 'ArrowDown') klineView.count = Math.round(klineView.count * 1.25) + 1;
  if (e.key === 'ArrowLeft') klineView.offset += Math.max(1, Math.round(klineView.count * 0.2));
  if (e.key === 'ArrowRight') klineView.offset -= Math.max(1, Math.round(klineView.count * 0.2));
  klineView.count = Math.max(10, Math.min(total, klineView.count));
  klineView.offset = Math.max(0, Math.min(total - klineView.count, klineView.offset));
  drawKline('kline-chart', klineData);
  updateKlineInfo();
});

// ---------- F10 基本信息 ----------
async function loadF10(code) {
  $('f10-content').innerHTML = '<div class="subtext" style="padding:10px">F10 数据加载中…</div>';
  try {
    const [f10, val] = await Promise.all([
      fetch('/api/f10?code=' + code).then(r => r.json()),
      fetch('/api/valuation?code=' + code).then(r => r.json()),
    ]);
    if (f10.error || val.error) { $('f10-content').innerHTML = `<div class="subtext">F10加载失败: ${f10.error||val.error}</div>`; return; }
    const kv = (k,v) => `<div class="kv"><span class="k">${k}</span><span>${v||'-'}</span></div>`;
    const vcls = val.change_pct >= 0 ? 'up' : 'down';
    $('f10-content').innerHTML = `
      <div class="grid g2" style="gap:16px">
        <div>
          <div class="section-title" style="font-size:12px">公司概况</div>
          ${kv('公司全称', f10.org_name)}${kv('英文名', f10.org_name_en)}
          ${kv('所属市场', f10.market)}${kv('板块', f10.board)}
          ${kv('行业分类', f10.industry)}${kv('证监会行业', f10.industry_csrc)}
          ${kv('董事长', f10.chairman)}${kv('总经理', f10.president)}
          ${kv('法人代表', f10.legal_person)}${kv('董秘', f10.secretary)}
          ${kv('注册资本(万)', f10.reg_capital_wan)}${kv('员工人数', f10.employees)}
          ${kv('省份', f10.province)}${kv('地址', f10.address)}
          ${kv('官网', f10.website)}${kv('会计师事务所', f10.account_firm)}
        </div>
        <div>
          <div class="section-title" style="font-size:12px">估值与交易</div>
          ${kv('现价', '<span class="'+vcls+'">'+val.price+' ('+(val.change_pct>=0?'+':'')+val.change_pct+'%)</span>')}
          ${kv('PE(动态)', val.pe_dynamic)}${kv('PE(静态)', val.pe_static)}
          ${kv('PE(TTM)', val.pe_ttm)}${kv('市净率PB', val.pb)}
          ${kv('总市值(亿)', val.market_cap_yi)}${kv('流通市值(亿)', val.float_cap_yi)}
          ${kv('换手率', val.turnover_pct+'%')}${kv('振幅', val.amplitude_pct+'%')}
          ${kv('成交量(手)', val.volume)}${kv('成交额(元)', val.amount)}
          ${kv('外盘', val.outer_vol)}${kv('内盘', val.inner_vol)}
          <div class="section-title" style="font-size:12px;margin-top:12px">公司简介</div>
          <div class="subtext" style="line-height:1.7;max-height:130px;overflow:auto">${esc(f10.profile)}</div>
          <div class="section-title" style="font-size:12px;margin-top:10px">经营范围</div>
          <div class="subtext" style="line-height:1.7;max-height:100px;overflow:auto">${esc(f10.business)}</div>
        </div>
      </div>`;
  } catch(e) { $('f10-content').innerHTML = `<div class="subtext">F10加载失败: ${e}</div>`; }
}

// ---------- 回测 ----------
async function runBacktest() {
  const code = $('bt-code').value.trim();
  const strategy = $('bt-strategy').value;
  if (strategy !== selectedStrategy) { selectedStrategy = strategy; syncStrategySelection(); renderParams(); }
  const params = collectParams();
  const btn = document.querySelector('#page-backtest button[onclick="runBacktest()"]');
  if (btn) btn.disabled = true;
  $('bt-metrics').innerHTML = '<div class="card"><div class="subtext">回测计算中，请观察实时运行窗口…</div></div>';
  try {
    const r = await (await fetch('/api/backtest', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({code, strategy, params})})).json();
    if (r.error) { $('bt-metrics').innerHTML = `<div class="card"><div class="subtext" style="color:var(--up)">回测失败: ${esc(r.error)}</div></div>`; return; }
    const s = r.summary;
    const cards = [
      ['总收益', (s.total_return*100).toFixed(2)+'%', s.total_return>=0?'up':'down'],
      ['年化收益', (s.annual_return*100).toFixed(2)+'%', s.annual_return>=0?'up':'down'],
      ['最大回撤', (s.max_drawdown*100).toFixed(2)+'%', 'down'],
      ['夏普比率', s.sharpe, ''],
      ['卡玛比率', s.calmar, ''],
      ['胜率', (s.win_rate*100).toFixed(1)+'%', ''],
      ['盈亏比', s.profit_factor, ''],
      ['交易对数', s.trade_pairs, ''],
    ];
    $('bt-metrics').innerHTML = cards.map(c => `<div class="card"><h3>${c[0]}</h3><div class="metric small ${c[2]}">${c[1]}</div></div>`).join('');
    equityData = r.equity;
    drawLine('equity-chart', r.equity, '#00c6a7');
    $('trades-table').querySelector('tbody').innerHTML = r.trades.map(t => `
      <tr><td>${t.date}</td><td class="${t.side==='buy'?'up':'down'}">${t.side==='buy'?'买入':'卖出'}</td>
      <td>${t.price.toFixed(2)}</td><td>${t.volume}</td><td>${t.fee.toFixed(2)}</td></tr>`).join('');
    // 同步到仪表盘结果回报窗口
    lastResult = {kind:'回测', title:`${code} · ${strategies.find(x=>x.name===strategy)?.display||strategy}`,
                  summary:s, equity:r.equity, timestamp:new Date().toLocaleTimeString('zh-CN')};
    renderResultReport();
  } catch(e) { $('bt-metrics').innerHTML = `<div class="card"><div class="subtext" style="color:var(--up)">回测请求失败: ${esc(e)}</div></div>`; }
  if (btn) btn.disabled = false;
}
async function runRobustness() {
  const code = $('bt-code').value.trim(), strategy = $('bt-strategy').value;
  $('robust-result').textContent = '检验中…';
  try {
    const r = await (await fetch('/api/robustness', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({code, strategy, params:collectParams()})})).json();
    if (r.error) { $('robust-result').textContent = r.error; return; }
    $('robust-result').innerHTML = `<div class="grid g4" style="margin-bottom:10px">
      <div class="card"><h3>稳健分(0.6中位+0.4最差)</h3><div class="metric small ${r.score>0?'up':'down'}">${r.score}</div></div>
      <div class="card"><h3>中位数收益</h3><div class="metric small">${(r.median*100).toFixed(2)}%</div></div>
      <div class="card"><h3>最差段收益</h3><div class="metric small down">${(r.worst*100).toFixed(2)}%</div></div>
      <div class="card"><h3>正收益段</h3><div class="metric small">${r.positive_segments}/${r.total_segments}</div></div>
    </div><table><thead><tr><th>段</th><th>收益</th><th>回撤</th><th>夏普</th></tr></thead><tbody>${
      r.details.map(d=>`<tr><td>第${d.segment}段</td><td class="${d.total_return>=0?'up':'down'}">${(d.total_return*100).toFixed(2)}%</td><td>${(d.max_drawdown*100).toFixed(2)}%</td><td>${d.sharpe}</td></tr>`).join('')
    }</tbody></table>`;
  } catch(e) { $('robust-result').textContent = '检验失败: ' + e; }
}

// ---------- 全市场选股（完整闭合） ----------
// ---------- 选股策略选择 ----------
let selectorStrategies = [], selectedSelector = 'multi_factor';
async function initSelectorStrategies() {
  if (selectorStrategies.length) return;
  try {
    selectorStrategies = await (await fetch('/api/selector-strategies')).json();
    const opts = selectorStrategies.map(s => `<option value="${s.name}">${esc(s.display)}</option>`).join('');
    if ($('sp-strategy')) {
      $('sp-strategy').innerHTML = opts;
      $('sp-strategy').value = selectedSelector;
      $('sp-strategy').onchange = e => { selectedSelector = e.target.value; showSelectorDetail(selectedSelector); renderSelectorParams(selectedSelector); updateSelectorButtonLabel(); };
    }
    renderSelectorStrategies();
  } catch(e) {
    const box = $('selector-strategy-list');
    if (box) box.innerHTML = '<div class="subtext" style="color:var(--up)">选股策略列表加载失败，请刷新页面或检查服务</div>';
  }
}
function renderSelectorStrategies() {
  $('selector-strategy-list').innerHTML = selectorStrategies.map(s => `
    <div class="strategy-card ${s.name===selectedSelector?'selected':''}" data-name="${s.name}" onclick="selectSelector('${s.name}')">
      <div class="name">${esc(s.display)}</div>
      <div style="font-size:10px;color:var(--accent2)">${esc(s.angle)}</div>
      <div class="desc">${esc(s.desc)}</div>
      <div style="font-size:10px;color:var(--muted)">${s.needs_history?'需历史K线':'仅快照'} · ${esc(s.theory)}</div>
      <button class="btn ghost" style="margin-top:8px;padding:3px 8px;font-size:10px"
        onclick="event.stopPropagation();selectSelector('${s.name}');runSelector()">▶ 用此策略选股</button>
    </div>`).join('');
  showSelectorDetail(selectedSelector);
  renderSelectorParams(selectedSelector);
  updateSelectorButtonLabel();
}
function selectSelector(name) {
  selectedSelector = name;
  document.querySelectorAll('#selector-strategy-list .strategy-card').forEach(el =>
    el.classList.toggle('selected', el.dataset.name === name));
  if ($('sp-strategy')) $('sp-strategy').value = name;  // 与「选股一条龙」保持同步
  showSelectorDetail(name);
  renderSelectorParams(name);
  updateSelectorButtonLabel();
}

// 按所选策略动态渲染专属参数（不再使用固定一套参数）
function renderSelectorParams(name) {
  const box = $('sel-strategy-params');
  const s = selectorStrategies.find(x => x.name === name);
  if (!box || !s) return;
  const ps = s.params || [];
  box.innerHTML = ps.length ? ps.map(p => `
    <div class="field" title="${esc(p.tip || '')}">
      <label>${esc(p.label)}</label>
      <input type="number" data-key="${p.key}" value="${p.default}"
             step="${p.step}" min="${p.min}" max="${p.max}">
      <div class="subtext" style="font-size:10px">${esc(p.tip || '')}</div>
    </div>`).join('') : '<div class="subtext">该策略无需额外参数，直接用真实快照因子打分</div>';
  const tag = $('sel-param-tag');
  if (tag) tag.textContent = `${s.display} · ${ps.length} 个专属参数`;
  const fw = $('sel-fetch-wrap');
  if (fw) fw.style.display = s.needs_history ? '' : 'none';
}
function collectSelectorParams() {
  const out = {};
  document.querySelectorAll('#sel-strategy-params input[data-key]').forEach(el => {
    const v = parseFloat(el.value);
    if (!isNaN(v)) out[el.dataset.key] = v;
  });
  return out;
}
function setSelStatus(text, color) {
  const el = $('sel-status');
  if (el) { el.textContent = text; el.style.color = color || 'var(--muted)'; }
}
function updateSelectorButtonLabel() {
  const s = selectorStrategies.find(x => x.name === selectedSelector);
  const btn = $('sel-btn');
  if (btn) btn.textContent = `▶ 执行【${s ? s.display : selectedSelector}】选股`;
}
function showSelectorDetail(name) {
  const s = selectorStrategies.find(x => x.name === name);
  if (!s) return;
  $('sel-strategy-current').textContent = s.display;
  $('selector-strategy-detail').innerHTML = `<b>选股角度：</b>${esc(s.angle)}　|　<b>所需真实数据：</b>${esc(s.needed)}　|　<b>理论依据：</b>${esc(s.theory)}`;
}

async function runSelector() {
  const top_n = parseInt($('sel-topn').value);
  const momentum_fetch_n = parseInt($('sel-fetchn').value);
  const min_amount = parseFloat($('sel-minamt').value);
  const strategy_params = collectSelectorParams();
  const sinfo = selectorStrategies.find(x => x.name === selectedSelector);
  $('sel-btn').disabled = true;
  selPct = 5;
  $('sel-progress').style.width = '5%';
  setSelStatus(`正在启动【${sinfo ? sinfo.display : selectedSelector}】…`, 'var(--accent2)');
  $('sel-table').querySelector('tbody').innerHTML = '<tr><td colspan="8" class="subtext">全市场扫描中，请观察下方状态与运行日志…</td></tr>';
  clearTimeout(selTimer);
  selTimer = setTimeout(() => {
    if ($('sel-btn').disabled) {
      $('sel-btn').disabled = false;
      setSelStatus('选股超过 5 分钟仍未完成，请查看运行日志；可重试或检查数据源', 'var(--up)');
    }
  }, 300000);
  try {
    const res = await fetch('/api/select', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({strategy:selectedSelector, top_n, momentum_fetch_n,
                            min_amount, strategy_params})});
    const d = await res.json();
    if (!res.ok || d.error) throw new Error(d.error || ('HTTP ' + res.status));
    setSelStatus(`已启动，正在拉取全市场真实快照…（${sinfo ? sinfo.display : selectedSelector}）`, 'var(--accent2)');
  } catch(e) {
    clearTimeout(selTimer);
    $('sel-btn').disabled = false;
    $('sel-progress').style.width = '0%';
    const msg = '选股启动失败: ' + e;
    setSelStatus(msg, 'var(--up)');
    $('sel-table').querySelector('tbody').innerHTML =
      `<tr><td colspan="8" class="subtext" style="color:var(--up)">${esc(msg)}</td></tr>`;
  }
}
function renderSelectResult(d) {
  $('sel-btn').disabled = false;
  $('sel-progress').style.width = '100%';
  const fo = d.filtered_out || {};
  const sname = (d.config && d.config.strategy) || selectedSelector;
  const sinfo = selectorStrategies.find(x => x.name === sname);
  const src = (d.config && d.config.data_source) || {};
  const sp = (d.config && d.config.strategy_params) || {};
  const spText = Object.entries(sp).map(([k, v]) => `${k}=${v}`).join('，');
  const warns = d.warnings || [];
  $('sel-summary').innerHTML = `
    <div class="card"><h3>选股策略</h3><div class="metric small" style="font-size:15px">${esc(sinfo?sinfo.display:sname)}</div><div class="subtext">${esc(sinfo?sinfo.angle:'')}${spText ? '<br>参数：' + esc(spText) : ''}</div></div>
    <div class="card"><h3>全市场标的</h3><div class="metric small">${d.universe_size}</div><div class="subtext">${esc(src.source || '真实数据')}${src.stale ? ' · 缓存快照' : ''}</div></div>
    <div class="card"><h3>入选 / 过滤</h3><div class="metric small"><span class="up">${d.picks.length}</span> / ${Object.values(fo).reduce((a,b)=>a+b,0)}</div><div class="subtext">策略过滤 ${fo.strategy_filter||0}</div></div>
    <div class="card"><h3>运行时间</h3><div class="metric small" style="font-size:15px">${d.timestamp}</div><div class="subtext">因子明细可追溯</div></div>
    ${warns.map(w => `<div class="card" style="grid-column:1/-1;color:var(--up)">⚠ ${esc(w)}</div>`).join('')}`;
  $('sel-table').querySelector('tbody').innerHTML = d.picks.map((p,i) => {
    const factors = Object.entries(p.factors||{}).map(([k,v])=>`${k}:${v}`).join(' / ');
    return `<tr><td>${i+1}</td><td>${p.code}</td><td>${esc(p.name)}</td><td>${p.price.toFixed(2)}</td>
    <td class="up">${p.score.toFixed(3)}</td>
    <td class="subtext" style="max-width:340px">${esc(factors)}</td>
    <td class="down">${((d.weights&&d.weights[p.code]||0)*100).toFixed(1)}%</td>
    <td class="subtext">${esc(p.reason)}</td></tr>`;
  }).join('');
  lastResult = {kind:'选股', title:`${sinfo?sinfo.display:sname} · 选出${d.picks.length}只`, picks:d.picks,
                universe:d.universe_size, timestamp:d.timestamp};
  lastSelectionPayload = d;
  if ($('sel-to-pipe-btn')) $('sel-to-pipe-btn').disabled = false;
  renderResultReport();
}

// 把本次选股结果原样送入「选股一条龙」，不再重新扫描全市场
function sendSelectionToPipeline() {
  if (!lastSelectionPayload || !lastSelectionPayload.picks || !lastSelectionPayload.picks.length) {
    alert('请先执行一次选股'); return;
  }
  if ($('sp-strategy')) $('sp-strategy').value = selectedSelector;
  if ($('sp-topn')) $('sp-topn').value = lastSelectionPayload.picks.length;
  goPage('pipeline');
  runSelectionPipeline(lastSelectionPayload);
}

// ---------- 多策略对比分析 ----------
async function runCompare() {
  const code = $('cmp-code').value.trim();
  $('cmp-btn').disabled = true;
  $('compare-result').innerHTML = '<div class="subtext">多策略并列回测中，请稍候…</div>';
  try {
    const r = await (await fetch('/api/compare', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({code})})).json();
    const ok = r.results.filter(x => !x.error);
    if (!ok.length) { $('compare-result').innerHTML = `<div class="subtext">对比失败</div>`; $('cmp-btn').disabled = false; return; }
    // 并列绩效表
    const table = `<table><thead><tr><th>排名</th><th>策略</th><th>总收益</th><th>年化</th><th>最大回撤</th><th>夏普</th><th>卡玛</th><th>胜率</th><th>交易数</th></tr></thead><tbody>${
      ok.map((x,i) => `<tr><td>${i+1}</td><td><span class="tag">${esc(x.display)}</span></td>
        <td class="${x.summary.total_return>=0?'up':'down'}">${(x.summary.total_return*100).toFixed(1)}%</td>
        <td>${(x.summary.annual_return*100).toFixed(1)}%</td>
        <td class="down">${(x.summary.max_drawdown*100).toFixed(1)}%</td>
        <td class="up">${x.summary.sharpe}</td><td>${x.summary.calmar}</td>
        <td>${(x.summary.win_rate*100).toFixed(0)}%</td><td>${x.summary.trade_pairs}</td></tr>`).join('')
    }</tbody></table>`;
    // 多曲线对比（归一化净值）
    const series = ok.slice(0,6).map((x,idx) => ({
      data: x.equity, color: ['#2f81f7','#00c6a7','#f0a020','#a78bfa','#ff6b7a','#4dd0e1'][idx],
      name: x.display,
    }));
    $('compare-result').innerHTML = `
      <div class="grid g3" style="margin-bottom:12px">
        <div class="card"><h3>最优策略(夏普)</h3><div class="metric small up">${esc(ok[0].display)}</div><div class="subtext">夏普 ${ok[0].summary.sharpe}</div></div>
        <div class="card"><h3>参与对比</h3><div class="metric small">${ok.length} 个策略</div><div class="subtext">同一标的 · 同一成本口径</div></div>
        <div class="card"><h3>对比标的</h3><div class="metric small">${code}</div><div class="subtext">真实历史数据</div></div>
      </div>
      ${table}
      <div class="section-title" style="margin-top:16px">净值曲线对比（归一化）</div>
      <div class="chart-wrap"><canvas id="compare-chart"></canvas></div>
      <div class="subtext" style="margin-top:8px">图例: ${series.map(s=>`<span style="color:${s.color}">■</span> ${esc(s.name)}`).join(' &nbsp; ')}</div>`;
    drawMultiLine('compare-chart', series);
    lastResult = {kind:'对比', title:`${code} · ${ok.length}策略对比`, top:ok[0], results:ok,
                  timestamp:new Date().toLocaleTimeString('zh-CN')};
    renderResultReport();
  } catch(e) { $('compare-result').innerHTML = `<div class="subtext">对比失败: ${e}</div>`; }
  $('cmp-btn').disabled = false;
}

// ---------- 多标的组合回测 ----------
async function runPortfolio() {
  const codes = $('combo-codes').value.trim();
  $('combo-btn').disabled = true;
  $('combo-result').innerHTML = '<div class="subtext">组合回测计算中，请观察实时运行窗口…</div>';
  try {
    const d = await (await fetch('/api/portfolio', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({codes, strategy:$('combo-strategy').value,
        signal_mode:$('combo-mode').value, rebalance:$('combo-rebalance').value})})).json();
    if (d.error) { $('combo-result').innerHTML = `<div class="subtext">失败: ${esc(d.error)}</div>`; }
    else renderPortfolioResult(d);
  } catch(e) { $('combo-result').innerHTML = `<div class="subtext">失败: ${e}</div>`; }
  $('combo-btn').disabled = false;
}
function renderPortfolioResult(d) {
  const s = d.summary || {};
  const cls = v => v>=0?'up':'down';
  const table = `<table><thead><tr><th>标的</th><th>期末权重</th><th>累计贡献(元)</th><th>相关性(对首位)</th></tr></thead><tbody>${
    d.codes.map(c => `<tr><td>${esc(c)}</td>
      <td>${(((d.weights[c]||[]).slice(-1)[0]||0)*100).toFixed(1)}%</td>
      <td class="${(d.contributions[c]||0)>=0?'up':'down'}">${(d.contributions[c]||0).toFixed(0)}</td>
      <td>${d.correlation[d.codes[0]] && d.correlation[d.codes[0]][c] !== undefined ? d.correlation[d.codes[0]][c] : '-'}</td></tr>`).join('')
  }</tbody></table>`;
  $('combo-result').innerHTML = `
    <div class="grid g4" style="margin-bottom:12px">
      <div class="card"><h3>组合总收益</h3><div class="metric small ${cls(s.total_return)}">${(s.total_return*100).toFixed(2)}%</div></div>
      <div class="card"><h3>最大回撤</h3><div class="metric small down">${(s.max_drawdown*100).toFixed(2)}%</div></div>
      <div class="card"><h3>夏普 / 卡玛</h3><div class="metric small">${s.sharpe} / ${s.calmar}</div></div>
      <div class="card"><h3>平均仓位 / 调仓</h3><div class="metric small">${(d.avg_exposure*100).toFixed(1)}% / ${d.rebalances}次</div></div>
    </div>
    <div class="chart-wrap" style="height:180px"><canvas id="combo-chart"></canvas></div>
    <div class="section-title" style="margin-top:14px">成分明细</div>${table}`;
  drawLine('combo-chart', d.equity, '#2f81f7');
  lastResult = {kind:'组合回测', title:`${d.codes.length}只标的组合 · ${d.rebalances}次调仓`,
                summary:s, equity:d.equity, timestamp:new Date().toLocaleTimeString('zh-CN')};
  renderResultReport();
}

// ---------- 参数自动寻优 ----------
async function runOptimize() {
  $('opt-btn').disabled = true;
  $('opt-result').innerHTML = '<div class="subtext">参数网格评估中，K段折外检验耗时较长，请观察实时日志…</div>';
  try {
    const r = await (await fetch('/api/optimize', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({code:$('opt-code').value.trim(), strategy:$('opt-strategy').value,
        k:parseInt($('opt-k').value), max_combinations:parseInt($('opt-max').value),
        objective:$('opt-objective').value, top_n:10})})).json();
    if (r.error) { $('opt-result').innerHTML = `<div class="subtext">失败: ${esc(r.error)}</div>`; $('opt-btn').disabled = false; return; }
    pollOptimize();
  } catch(e) { $('opt-result').innerHTML = `<div class="subtext">失败: ${e}</div>`; $('opt-btn').disabled = false; }
}
async function pollOptimize() {
  if (window.__optTimer) clearInterval(window.__optTimer);
  let ticks = 0;
  window.__optTimer = setInterval(async () => {
    ticks++;
    try {
      const d = await (await fetch('/api/optimize/result')).json();
      if (d && d.grid_size) { clearInterval(window.__optTimer); window.__optTimer = null;
        renderOptimizeResult(d); $('opt-btn').disabled = false; }
    } catch(e) {}
    if (ticks > 180) { clearInterval(window.__optTimer); window.__optTimer = null; $('opt-btn').disabled = false;
      $('opt-result').innerHTML = '<div class="subtext" style="color:var(--up)">寻优超过 6 分钟未返回，请查看实时日志；可减小「组合上限」后重试。</div>'; }
  }, 2000);
}
function renderOptimizeResult(d) {
  const rows = (d.top||[]).map((x,i) => `<tr>
    <td>${i+1}</td><td>${Object.entries(x.params||{}).map(([k,v])=>`${k}=${v}`).join(' · ')}</td>
    <td class="up">${(x.robustness*100).toFixed(2)}%</td>
    <td>${(x.oos_median*100).toFixed(1)}%</td><td class="${x.oos_worst>=0?'':'down'}">${(x.oos_worst*100).toFixed(1)}%</td>
    <td>${x.positive_segments}/${x.total_segments}</td>
    <td class="${x.in_sample_return>=0?'up':'down'}">${(x.in_sample_return*100).toFixed(1)}%</td>
    <td>${x.in_sample_sharpe}</td></tr>`).join('');
  $('opt-result').innerHTML = `
    <div class="grid g4" style="margin-bottom:12px">
      <div class="card"><h3>最优参数</h3><div class="metric small">${Object.entries((d.best&&d.best.params)||{}).map(([k,v])=>`${k}=${v}`).join(' · ')}</div></div>
      <div class="card"><h3>折外稳健分</h3><div class="metric small up">${((d.best&&d.best.robustness)||0).toFixed(4)}</div><div class="subtext">0.6中位 + 0.4最差</div></div>
      <div class="card"><h3>搜索组合</h3><div class="metric small">${d.grid_size}</div><div class="subtext">${d.strategy}</div></div>
      <div class="card"><h3>耗时</h3><div class="metric small">${d.elapsed_sec}s</div><div class="subtext">${esc(d.note||'')}</div></div>
    </div>
    <table><thead><tr><th>#</th><th>参数</th><th>稳健分</th><th>段中位</th><th>最差段</th><th>正段</th><th>样本内收益</th><th>样本内夏普</th></tr></thead><tbody>${rows}</tbody></table>
    <div style="margin-top:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <button class="btn ghost" onclick="applyOptimizedParams()">应用最优参数到策略库/回测</button>
      <span class="subtext">应用后可在「回测中心」复核；建议再做一次稳健性检验。</span>
    </div>`;
  lastOptimizeResult = d;
}
// 把寻优得到的最优参数写回策略库参数面板
function applyOptimizedParams() {
  if (!lastOptimizeResult || !lastOptimizeResult.best) return;
  const strategy = lastOptimizeResult.strategy;
  if (strategies.some(s => s.name === strategy)) {
    selectedStrategy = strategy; syncStrategySelection(); renderParams();
  }
  const params = lastOptimizeResult.best.params || {};
  Object.entries(params).forEach(([k, v]) => {
    const el = $('param-' + k);
    if (el) el.value = v;
  });
  $('param-usage').innerHTML = `✓ 已应用 ${esc(strategy)} 的最优参数：${Object.entries(params).map(([k,v])=>`${k}=${v}`).join(' · ')}。请到「回测中心」复核。`;
  $('param-usage').style.color = 'var(--up)';
}

// ---------- 选股一条龙 ----------
async function runSelectionPipeline(preset) {
  $('sp-btn').disabled = true;
  $('sp-result').innerHTML = `<div class="subtext">${preset?'复用已选结果，正在组合回测与风控…':'全市场选股与组合回测进行中，请观察实时运行窗口…'}</div>`;
  try {
    const r = await (await fetch('/api/selection-pipeline', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({selector_strategy:$('sp-strategy').value || 'multi_factor',
        top_n:parseInt($('sp-topn').value), rebalance:$('sp-rebalance').value,
        momentum_fetch_n:parseInt($('sp-fetchn').value), selection:preset || null})})).json();
    if (r.error) { $('sp-result').innerHTML = `<div class="subtext">失败: ${esc(r.error)}</div>`; $('sp-btn').disabled = false; return; }
    pollSelectionPipeline();
  } catch(e) { $('sp-result').innerHTML = `<div class="subtext">失败: ${e}</div>`; $('sp-btn').disabled = false; }
}
async function pollSelectionPipeline() {
  if (window.__spTimer) clearInterval(window.__spTimer);
  let ticks = 0;
  window.__spTimer = setInterval(async () => {
    ticks++;
    try {
      const d = await (await fetch('/api/selection-pipeline/result')).json();
      if (d && d.orders) { clearInterval(window.__spTimer); window.__spTimer = null;
        renderSelectionPipelineResult(d); $('sp-btn').disabled = false; }
    } catch(e) {}
    if (ticks > 240) { clearInterval(window.__spTimer); window.__spTimer = null; $('sp-btn').disabled = false;
      $('sp-result').innerHTML = '<div class="subtext" style="color:var(--up)">运行超过 8 分钟未返回，请查看左侧实时运行窗口中的错误日志；可重试或减小入选数量。</div>'; }
  }, 2000);
}
function renderSelectionPipelineResult(d) {
  const p = d.portfolio && d.portfolio.summary || {};
  const rc = d.risk || {}, cc = d.compliance || {};
  const steps = (d.steps||[]).map(s=>`<div class="kv"><span>›</span><span>${esc(s)}</span></div>`).join('');
  const orders = (d.orders||[]).map(o=>`<tr><td>${esc(o.code)}</td><td>${esc(o.side)}</td>
    <td>${o.volume}</td><td>${o.price}</td><td>${esc(o.status)}</td><td class="subtext">${esc(o.note)}</td></tr>`).join('');
  $('sp-result').innerHTML = `
    <div class="grid g4" style="margin-bottom:12px">
      <div class="card"><h3>组合收益</h3><div class="metric small ${p.total_return>=0?'up':'down'}">${((p.total_return||0)*100).toFixed(2)}%</div></div>
      <div class="card"><h3>最大回撤</h3><div class="metric small down">${((p.max_drawdown||0)*100).toFixed(2)}%</div></div>
      <div class="card"><h3>组合稳健分</h3><div class="metric small">${((d.robustness||{}).score||0).toFixed(4)}</div></div>
      <div class="card"><h3>风控 / 合规</h3><div class="metric small" style="font-size:15px">${rc.pass?'通过':'拦截'} / ${cc.pass?'通过':'未过'}</div></div>
    </div>
    <div class="section-title">流水线步骤</div>${steps}
    <div class="section-title" style="margin-top:14px">实盘意图（VALIDATED_ONLY · 未报单）</div>
    <table><thead><tr><th>标的</th><th>方向</th><th>数量</th><th>参考价</th><th>状态</th><th>说明</th></tr></thead><tbody>${orders||'<tr><td colspan="6" class="subtext">无可执行意图（风控或合规未通过）</td></tr>'}</tbody></table>
    <div class="subtext" style="margin-top:10px">${esc(d.disclaimer||'')}</div>`;
  if (p.total_return !== undefined) {
    lastResult = {kind:'选股一条龙', title:`${d.selector_strategy} · ${(d.selection&&d.selection.picks||[]).length}只标的组合`,
      summary:p, timestamp:new Date().toLocaleTimeString('zh-CN')};
    renderResultReport();
  }
}

// ---------- 结果回报窗口 ----------
function renderResultReport() {
  if (!lastResult) return;
  const box = $('result-report');
  const s = lastResult.summary;
  if (s) {
    const cls = v => v>=0?'up':'down';
    box.innerHTML = `
      <div class="result-hero">
        <span class="result-kind">${esc(lastResult.kind)}</span>
        <span class="subtext">${esc(lastResult.title)}</span>
        <span class="subtext" style="margin-left:auto">${esc(lastResult.timestamp)}</span>
        <span class="big ${cls(s.total_return)}">${(s.total_return*100).toFixed(2)}%</span>
        <span class="subtext">总收益</span>
      </div>
      <div class="result-grid">
        ${[['年化收益',(s.annual_return*100).toFixed(2)+'%',cls(s.annual_return)],
           ['最大回撤',(s.max_drawdown*100).toFixed(2)+'%','down'],
           ['夏普比率',s.sharpe,'up'],['卡玛比率',s.calmar,''],
           ['胜率',(s.win_rate*100).toFixed(1)+'%',''],['盈亏比',s.profit_factor,''],
           ['交易对数',s.trade_pairs,''],['最终权益',s.final_equity,'']]
          .map(c=>`<div class="result-item"><div class="k">${c[0]}</div><div class="v ${c[2]}">${c[1]}</div></div>`).join('')}
      </div>
      ${lastResult.equity ? `<div class="chart-wrap" style="height:160px;margin-top:12px"><canvas id="report-chart"></canvas></div>` : ''}`;
    if (lastResult.equity) drawLine('report-chart', lastResult.equity, '#2f81f7');
  } else if (lastResult.picks) {
    box.innerHTML = `
      <div class="result-hero"><span class="result-kind">${esc(lastResult.kind)}</span>
        <span class="subtext">${esc(lastResult.title)}</span><span class="subtext" style="margin-left:auto">${esc(lastResult.timestamp)}</span></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        ${lastResult.picks.slice(0,8).map((p,i)=>`<div class="result-item" style="min-width:130px">
          <div class="k">#${i+1} ${esc(p.name)} ${p.code}</div>
          <div class="v up" style="font-size:15px">${p.score.toFixed(3)}</div>
          <div class="subtext">现价 ${p.price.toFixed(2)} · PE ${p.factors.pe}</div></div>`).join('')}
      </div>`;
  } else if (lastResult.top) {
    const t = lastResult.top.summary;
    box.innerHTML = `
      <div class="result-hero"><span class="result-kind">${esc(lastResult.kind)}</span>
        <span class="subtext">${esc(lastResult.title)}</span>
        <span class="big up">${esc(lastResult.top.display)}</span><span class="subtext">最优策略</span></div>
      <div class="result-grid">
        ${[['最优总收益',(t.total_return*100).toFixed(2)+'%','up'],['最优夏普',t.sharpe,'up'],
           ['参与策略',lastResult.results.length,''],['最大回撤',(t.max_drawdown*100).toFixed(2)+'%','down']]
          .map(c=>`<div class="result-item"><div class="k">${c[0]}</div><div class="v ${c[2]}">${c[1]}</div></div>`).join('')}
      </div>`;
  }
}
async function refreshLastResult() {
  await loadLastResult(true);
  if (!lastResult) $('result-report').innerHTML =
    '<div class="subtext" style="text-align:center;padding:20px">尚无服务端保存的运行结果。前往「回测中心」「全市场选股」或「全链路工作流」运行后，结果将自动汇总显示在这里。</div>';
}

// ---------- 全链路 ----------
async function runPipeline() {
  const code = $('pl-code').value.trim(), strategy = $('pl-strategy').value;
  if (strategy !== selectedStrategy) { selectedStrategy = strategy; syncStrategySelection(); renderParams(); }
  const btn = document.querySelector('#page-pipeline button[onclick="runPipeline()"]');
  if (btn) btn.disabled = true;
  $('pl-steps').textContent = '流水线启动中，请观察左侧实时运行窗口…';
  try {
    const r = await (await fetch('/api/pipeline', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({code, strategy, params:collectParams()})})).json();
    if (r.error) { $('pl-steps').innerHTML = `<div class="subtext" style="color:var(--up)">启动失败: ${esc(r.error)}</div>`; }
  } catch(e) { $('pl-steps').innerHTML = `<div class="subtext" style="color:var(--up)">启动失败: ${esc(e)}</div>`; }
}

// ---------- 合规 ----------
async function loadCompliance() {
  try {
    const resp = await (await fetch('/api/compliance')).json();
    const logs = resp.logs || resp;  // 兼容新旧格式
    $('audit-table').querySelector('tbody').innerHTML = logs.map(l => `
      <tr><td>${l.ts}</td><td>${l.code}</td><td>${l.side}</td><td>${l.volume}</td>
      <td>${l.amount}</td><td class="${l.decision==='PASS'?'down':'up'}">${l.decision}</td>
      <td>${(l.reasons||[]).join('; ')||'-'}</td></tr>`).join('');
    const risk = await (await fetch('/api/risk')).json();
    $('guard-count').textContent = risk.strategies.length + ' 个策略受监控';
    const cs = await (await fetch('/api/config/status')).json();
    const el = $('compliance-mode');
    if (el) {
      el.textContent = modeLabel(cs.mode) || cs.mode;
      el.style.color = cs.mode === 'live' ? 'var(--up)' : 'var(--down)';
    }
  } catch(e) {}
}

// ---------- AI ----------
async function chat() {
  const q = $('chat-input').value.trim();
  if (!q) return;
  $('chat-input').value = '';
  const msgs = $('chat-msgs');
  msgs.insertAdjacentHTML('beforeend', `<div class="msg user">${esc(q)}</div>`);
  msgs.insertAdjacentHTML('beforeend', `<div class="msg ai typing" id="typing">思考中…</div>`);
  msgs.scrollTop = msgs.scrollHeight;
  $('chat-btn').disabled = true;
  try {
    const r = await (await fetch('/ai/chat', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({question:q})})).json();
    $('typing').remove();
    const tc = (r.tool_calls||[]).map(c=>`\n[工具 ${c.tool}]`).join('');
    msgs.insertAdjacentHTML('beforeend', `<div class="msg ai">${esc(r.answer)}${esc(tc)}</div>`);
  } catch(e) {
    $('typing').remove();
    msgs.insertAdjacentHTML('beforeend', `<div class="msg ai">请求失败: ${e}</div>`);
  }
  $('chat-btn').disabled = false;
  msgs.scrollTop = msgs.scrollHeight;
}

// ---------- SSE 实时日志 ----------
function subscribeSSE() {
  const es = new EventSource('/api/stream');
  es.onmessage = e => {
    try { handleEvent(JSON.parse(e.data)); } catch(err) {}
  };
}
function handleEvent(ev) {
  const line = `<div class="logline ${ev.type}"><span class="t">[${ev.ts||''}]</span> ${esc(ev.msg||ev.stage||'')}</div>`;
  appendLog('dash-log', line);
  appendLog('pl-log', line);
  if (ev.type === 'progress') {
    const pct = ev.total > 0 ? Math.round(ev.step / ev.total * 100) : 0;
    if (ev.stage === 'pipeline') $('pl-progress').style.width = pct + '%';
    else if (ev.stage === 'select') {
      selPct = Math.max(selPct, Math.min(98, pct));
      $('sel-progress').style.width = selPct + '%';
      setSelStatus(`运行中：${ev.msg || ''}`, 'var(--accent2)');
    }
    else if (ev.stage === 'optimize') $('opt-progress').style.width = pct + '%';
    else if (ev.stage === 'selection_pipeline') $('sp-progress').style.width = pct + '%';
    else if (ev.stage === 'portfolio') $('dash-progress').style.width = pct + '%';
    else $('dash-progress').style.width = pct + '%';
  }
  if (ev.type === 'select_start') setSelStatus(ev.msg || '选股已启动', 'var(--accent2)');
  if (ev.type === 'select_error') {
    clearTimeout(selTimer);
    if ($('sel-btn')) $('sel-btn').disabled = false;
    $('sel-progress').style.width = '0%';
    setSelStatus('选股失败：' + (ev.error || ev.msg || '未知错误'), 'var(--up)');
    $('sel-table').querySelector('tbody').innerHTML =
      `<tr><td colspan="8" class="subtext" style="color:var(--up)">选股失败：${esc(ev.error || ev.msg || '未知错误')}。请查看运行日志或检查数据源。</td></tr>`;
  }
  if (ev.type === 'select_result') {
    clearTimeout(selTimer);
    selPct = 100;
    setSelStatus('选股完成，结果已生成', 'var(--accent2)');
    renderSelectResult(ev.data);
  }
  if (ev.type === 'combo_result') renderPortfolioResult(ev.data);
  if (ev.type === 'optimize_result') { renderOptimizeResult(ev.data); $('opt-btn').disabled = false; }
  if (ev.type === 'selection_result') { renderSelectionPipelineResult(ev.data); $('sp-btn').disabled = false; }
  if (ev.type === 'log' && ev.level === 'error') {
    if ($('sel-btn') && $('sel-btn').disabled) $('sel-btn').disabled = false;
    if ($('opt-btn') && $('opt-btn').disabled) $('opt-btn').disabled = false;
    if ($('sp-btn') && $('sp-btn').disabled) $('sp-btn').disabled = false;
    const pb = document.querySelector('#page-pipeline button[onclick="runPipeline()"]');
    if (pb) pb.disabled = false;
  }
  if (ev.type === 'result') {
    const d = ev.data;
    $('pl-steps').innerHTML = `<div class="subtext">✅ 全链路完成 · ${d.code} / ${d.strategy}</div>` +
      (d.steps||[]).map(s=>`<div class="kv"><span>›</span><span>${esc(s)}</span></div>`).join('') +
      `<div class="kv" style="margin-top:8px"><span class="k">AI复盘</span></div>
       <div class="subtext" style="white-space:pre-wrap">${esc((d.ai_review&&d.ai_review.answer)||'')}</div>`;
    $('pl-progress').style.width = '100%';
    const pb = document.querySelector('#page-pipeline button[onclick="runPipeline()"]');
    if (pb) pb.disabled = false;
    if (d.summary) {
      lastResult = {kind:'全链路', title:`${d.code} · ${d.strategy}`, summary:d.summary,
                    timestamp:new Date().toLocaleTimeString('zh-CN')};
      renderResultReport();
    }
  }
}
function appendLog(id, html) {
  const box = $(id);
  if (!box) return;
  box.insertAdjacentHTML('beforeend', html);
  while (box.children.length > 200) box.removeChild(box.firstChild);
  box.scrollTop = box.scrollHeight;
}
async function loadEvents() {
  try {
    const evs = await (await fetch('/api/events')).json();
    evs.forEach(ev => handleEvent(ev));
  } catch(e) {}
}

// ---------- Canvas 图表 ----------
function drawLine(canvasId, data, color) {
  const cv = $(canvasId); if (!cv || !data || data.length < 2) return;
  const rect = cv.parentElement.getBoundingClientRect();
  cv.width = rect.width * devicePixelRatio; cv.height = rect.height * devicePixelRatio;
  const ctx = cv.getContext('2d'); ctx.scale(devicePixelRatio, devicePixelRatio);
  const w = rect.width, h = rect.height, pad = 30;
  ctx.clearRect(0,0,w,h);
  const mn = Math.min(...data), mx = Math.max(...data), range = (mx-mn)||1;
  // 网格
  ctx.strokeStyle = '#1f2b3d'; ctx.lineWidth = 1;
  for (let i=0;i<=4;i++){ const y=pad+(h-2*pad)*i/4; ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(w-10,y);ctx.stroke(); }
  // 曲线
  ctx.beginPath(); ctx.strokeStyle = color; ctx.lineWidth = 2;
  data.forEach((v,i)=>{ const x=pad+(w-pad-10)*i/(data.length-1); const y=pad+(h-2*pad)*(1-(v-mn)/range);
    i?ctx.lineTo(x,y):ctx.moveTo(x,y); });
  ctx.stroke();
  // 填充
  ctx.lineTo(pad+(w-pad-10), h-pad); ctx.lineTo(pad, h-pad); ctx.closePath();
  ctx.fillStyle = color+'22'; ctx.fill();
  ctx.fillStyle='#7d8ca3'; ctx.font='11px sans-serif';
  ctx.fillText(mx.toFixed(0), 2, pad); ctx.fillText(mn.toFixed(0), 2, h-pad);
}
function maSeries(closes, period) {
  const out = []; let sum = 0;
  for (let i = 0; i < closes.length; i++) {
    sum += closes[i];
    if (i >= period) sum -= closes[i - period];
    out.push(i >= period - 1 ? sum / period : null);
  }
  return out;
}
function drawKline(canvasId, allRows) {
  const cv = $(canvasId); if (!cv || !allRows || allRows.length < 2) return;
  const rect = cv.parentElement.getBoundingClientRect();
  if (rect.width < 10 || rect.height < 10) return;
  cv.width = rect.width * devicePixelRatio; cv.height = rect.height * devicePixelRatio;
  const ctx = cv.getContext('2d'); ctx.scale(devicePixelRatio, devicePixelRatio);
  const w = rect.width, h = rect.height;
  const left = 52, right = 16, topPad = 18, bottomPad = 26;
  const volH = Math.max(56, h * 0.22), gap = 20;
  const priceBottom = h - bottomPad - volH - gap;
  const priceH = priceBottom - topPad;
  const volTop = priceBottom + gap, volBottom = h - bottomPad;
  ctx.clearRect(0, 0, w, h);

  const rows = visibleKlineSlice(allRows);
  const n = rows.length;
  // 价格范围取可见区高低价，并留 4% 余量；同时纳入均线值避免出界
  let lo = Math.min(...rows.map(r => r.low));
  let hi = Math.max(...rows.map(r => r.high));
  const closesAll = allRows.map(r => r.close);
  const mas = klineMaParams.map(p => maSeries(closesAll, p));
  const offset0 = allRows.length - n;
  mas.forEach(ms => {
    for (let i = offset0; i < allRows.length; i++) {
      const v = ms[i]; if (v == null) continue;
      lo = Math.min(lo, v); hi = Math.max(hi, v);
    }
  });
  const padRange = (hi - lo || hi * 0.02 || 1) * 0.04;
  lo -= padRange; hi += padRange;
  const range = hi - lo;
  const yPrice = v => topPad + priceH * (1 - (v - lo) / range);
  const maxVol = Math.max(...rows.map(r => r.volume || 0), 1);
  const step = (w - left - right) / n;
  const bodyW = Math.max(1, Math.min(14, step * 0.62));

  // 网格与价格刻度
  ctx.strokeStyle = '#1f2b3d'; ctx.lineWidth = 1;
  ctx.fillStyle = '#7d8ca3'; ctx.font = '11px sans-serif';
  for (let i = 0; i <= 4; i++) {
    const y = topPad + priceH * i / 4;
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(w - right, y); ctx.stroke();
    ctx.fillText((hi - range * i / 4).toFixed(2), 2, y + 4);
  }
  // 成交量分隔线与刻度
  ctx.beginPath(); ctx.moveTo(left, volTop - 6); ctx.lineTo(w - right, volTop - 6); ctx.stroke();
  ctx.fillText('VOL ' + (maxVol >= 1e8 ? (maxVol/1e8).toFixed(2)+'亿' : maxVol.toFixed(0)), 2, volTop + 10);

  // 蜡烛 + 成交量（红涨绿跌）
  rows.forEach((r, i) => {
    const x = left + step * i + step / 2;
    const up = r.close >= r.open;
    const color = up ? '#ff4d5e' : '#00b578';
    ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, yPrice(r.high)); ctx.lineTo(x, yPrice(r.low)); ctx.stroke();
    const y1 = yPrice(r.open), y2 = yPrice(r.close);
    const by = Math.min(y1, y2), bh = Math.max(1, Math.abs(y2 - y1));
    ctx.fillRect(x - bodyW / 2, by, bodyW, bh);
    const vh = Math.max(1, (volBottom - volTop) * ((r.volume || 0) / maxVol));
    ctx.globalAlpha = 0.55;
    ctx.fillRect(x - bodyW / 2, volBottom - vh, bodyW, vh);
    ctx.globalAlpha = 1;
  });

  // 三条可调均线（基于全历史前推，可见区只截取，不用未来数据）
  mas.forEach((ms, k) => {
    ctx.beginPath(); ctx.strokeStyle = MA_COLORS[k]; ctx.lineWidth = 1.6;
    let started = false;
    for (let i = offset0; i < allRows.length; i++) {
      const v = ms[i]; if (v == null) continue;
      const x = left + step * (i - offset0) + step / 2;
      const y = yPrice(v);
      if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
    }
    ctx.stroke();
  });

  // 日期与状态
  ctx.fillStyle = '#7d8ca3'; ctx.font = '11px sans-serif';
  ctx.fillText(rows[0].date, left, h - 8);
  ctx.fillText(rows[n - 1].date, Math.max(left, w - right - 72), h - 8);
}
function drawMultiLine(canvasId, series) {
  const cv = $(canvasId); if (!cv || !series.length) return;
  const rect = cv.parentElement.getBoundingClientRect();
  cv.width = rect.width*devicePixelRatio; cv.height=rect.height*devicePixelRatio;
  const ctx=cv.getContext('2d'); ctx.scale(devicePixelRatio,devicePixelRatio);
  const w=rect.width,h=rect.height,pad=34;
  ctx.clearRect(0,0,w,h);
  // 归一化：每条曲线以首值为基准换算成百分比
  const norm = series.map(s => ({...s, norm: s.data.map(v => v/s.data[0]-1)}));
  const all = norm.flatMap(s => s.norm);
  const mn=Math.min(...all), mx=Math.max(...all), range=(mx-mn)||1;
  ctx.strokeStyle='#1f2b3d';ctx.lineWidth=1;
  for(let i=0;i<=4;i++){const y=pad+(h-2*pad)*i/4;ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(w-10,y);ctx.stroke();}
  const maxLen=Math.max(...norm.map(s=>s.norm.length));
  norm.forEach(s=>{
    ctx.beginPath();ctx.strokeStyle=s.color;ctx.lineWidth=1.8;
    s.norm.forEach((v,i)=>{const x=pad+(w-pad-10)*i/(s.norm.length-1);const y=pad+(h-2*pad)*(1-(v-mn)/range);
      i?ctx.lineTo(x,y):ctx.moveTo(x,y);});
    ctx.stroke();
  });
  ctx.fillStyle='#7d8ca3';ctx.font='11px sans-serif';
  ctx.fillText((mx*100).toFixed(0)+'%',2,pad);ctx.fillText((mn*100).toFixed(0)+'%',2,h-pad);
}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

// ---------- 多市场品种 ETF/期货/期权 ----------
let mmInstruments = [], mmSelected = '';
async function mmLoadInstruments() {
  const kind = $('mm-kind').value;
  const box = $('mm-inst-list');
  box.textContent = '加载中…';
  try {
    const d = await (await fetch('/api/mm/instruments?kind=' + encodeURIComponent(kind))).json();
    if (d.error) { box.textContent = d.error; return; }
    mmInstruments = d.rows || [];
    const label = r => kind === 'futures' ? `${r.name} (${r.symbol})` :
      kind === 'etf' ? `${r.name} (${r.symbol})` : `${r.name} (${r.code})`;
    box.innerHTML = `<div style="font-size:11px;color:var(--muted);margin-bottom:6px">共 ${d.count} 个，显示前 ${mmInstruments.length} 个 · 点击选择</div>` +
      `<div style="max-height:150px;overflow:auto;display:flex;flex-wrap:wrap;gap:6px">` +
      mmInstruments.slice(0, 60).map((r, i) =>
        `<span class="badge ${i === 0 ? 'blue' : ''}" style="cursor:pointer" data-sym="${esc(r.symbol)}" onclick="mmSelect('${esc(r.symbol)}')">${esc(label(r))}</span>`
      ).join('') + `</div>`;
    if (mmInstruments.length) mmSelect(mmInstruments[0].symbol);
  } catch (e) { box.textContent = '加载失败: ' + e; }
}
async function mmSelect(sym) {
  mmSelected = sym;
  $('mm-inst-list').querySelectorAll('.badge').forEach(x =>
    x.classList.toggle('blue', x.dataset.sym === sym));
  try {
    const q = await (await fetch('/api/mm/quote?code=' + encodeURIComponent(sym))).json();
    if (q.error) { $('mm-quote').textContent = q.error; return; }
    $('mm-quote').innerHTML =
      `<div style="font-size:16px;color:var(--text)">${esc(q.name)} <span class="badge blue">${esc(q.asset_class)}</span></div>` +
      `<div style="margin-top:8px;line-height:1.9">最新价 <b style="color:var(--up)">${q.price}</b> · 涨跌 ${q.change_pct}% · 昨收 ${q.prev_close}<br>` +
      `开 ${q.open} · 高 ${q.high} · 低 ${q.low} · 成交量 ${q.volume.toLocaleString()}<br>` +
      `<span style="font-size:10px">数据源 ${esc(q.source)} · ${esc(q.ts)} · 真实快照</span></div>`;
    $('mm-cost-price').value = q.price;
  } catch (e) { $('mm-quote').textContent = '快照失败: ' + e; }
}
async function mmCalcCost() {
  if (!mmSelected) { $('mm-cost-result').textContent = '请先选择合约'; return; }
  const price = $('mm-cost-price').value, vol = $('mm-cost-volume').value;
  try {
    const d = await (await fetch(`/api/mm/cost?code=${encodeURIComponent(mmSelected)}&price=${price}&volume=${vol}`)).json();
    if (d.error) { $('mm-cost-result').textContent = d.error; return; }
    $('mm-cost-result').innerHTML =
      `<b>${esc(d.asset_class)} · ${esc(d.name)}</b><br>名义金额 ${fmtN(d.notional)} · 手续费 ${fmtN(d.commission)} · 印花税 ${fmtN(d.tax)}` +
      `<br>保证金占用 ${fmtN(d.margin)} · 权利金 ${fmtN(d.premium)}`;
  } catch (e) { $('mm-cost-result').textContent = '测算失败: ' + e; }
}
async function mmRunBacktest() {
  if (!mmSelected) { $('mm-bt-result').textContent = '请先选择合约'; return; }
  $('mm-bt-result').textContent = '回测进行中…';
  try {
    const d = await (await fetch('/api/mm/backtest', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({code:mmSelected, fast:parseInt($('mm-fast').value)||5,
        slow:parseInt($('mm-slow').value)||20, cash:1000000})})).json();
    if (d.error) { $('mm-bt-result').textContent = d.error; return; }
    $('mm-bt-result').innerHTML =
      `<b>${esc(d.name)} [${esc(d.asset_class)}]</b> · ${d.bars}根真实K线 · 交易 ${d.trades} 次 · ` +
      `总收益 <b style="color:${d.total_return>=0?'var(--up)':'var(--down)'}">${d.total_return}%</b> · ` +
      `最大回撤 ${d.max_drawdown}% · 期末 ${fmtN(d.final_equity)}` +
      `<div style="font-size:10px;color:var(--muted);margin-top:4px">${esc((d.notes||[]).join('；'))}</div>`;
    const eq = await (await fetch('/api/mm/kline?code=' + encodeURIComponent(mmSelected))).json();
    if (eq.rows) drawMMKline(eq.rows);
  } catch (e) { $('mm-bt-result').textContent = '回测失败: ' + e; }
}
function drawMMKline(rows) {
  const cv = $('mm-chart'); if (!cv || !rows || rows.length < 2) return;
  const rect = cv.parentElement.getBoundingClientRect();
  cv.width = rect.width*devicePixelRatio; cv.height = rect.height*devicePixelRatio;
  const ctx = cv.getContext('2d'); ctx.scale(devicePixelRatio,devicePixelRatio);
  const w=rect.width,h=rect.height,pad=36;
  ctx.clearRect(0,0,w,h);
  const n=Math.min(rows.length,300), data=rows.slice(-n);
  const closes=data.map(r=>r.close), mn=Math.min(...closes), mx=Math.max(...closes), range=(mx-mn)||1;
  ctx.strokeStyle='#1f2b3d';ctx.lineWidth=1;
  for(let i=0;i<=4;i++){const y=pad+(h-2*pad-70)*i/4;ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(w-10,y);ctx.stroke();}
  const step=(w-pad-10)/n;
  data.forEach((r,i)=>{
    const x=pad+step*i+step/2;
    const up=r.close>=r.open;
    ctx.strokeStyle=up?'#ff4d5e':'#00b578';ctx.fillStyle=ctx.strokeStyle;
    ctx.beginPath();ctx.moveTo(x,pad+(h-2*pad-70)*(1-(r.high-mn)/range));
    ctx.lineTo(x,pad+(h-2*pad-70)*(1-(r.low-mn)/range));ctx.stroke();
    const y1=pad+(h-2*pad-70)*(1-(Math.max(r.open,r.close)-mn)/range);
    const y2=pad+(h-2*pad-70)*(1-(Math.min(r.open,r.close)-mn)/range);
    ctx.fillRect(x-step*0.3,y1,Math.max(1,step*0.6),Math.max(1,y2-y1));
  });
  ctx.fillStyle='#7d8ca3';ctx.font='11px sans-serif';
  ctx.fillText(mx.toFixed(3),2,pad);ctx.fillText(mn.toFixed(3),2,h-90);
  ctx.fillText(data[0].date,pad,h-10);ctx.fillText(data[n-1].date,w-80,h-10);
}
function fmtN(v){return Number(v||0).toLocaleString(undefined,{maximumFractionDigits:2});}

// ---------- 有效策略：ETF 动量轮动 ----------
let _rotData = null;
async function runRotation(force=false){
  const status = $('rot-status'), btn = $('rot-btn');
  const lookback = parseInt(($('rot-lookback')||{}).value||'22');
  const buffer = parseFloat(($('rot-buffer')||{}).value||'0');
  if(btn) btn.disabled = true;
  if(status) { status.style.color='var(--accent2)'; status.textContent='正在拉取真实数据并回测（首次约 10-30 秒，结果缓存1小时）…'; }
  try{
    const resp = await fetch('/api/etf-rotation',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({lookback,buffer,force:!!force})});
    const d = await resp.json();
    if(d.error){ if(status){status.style.color='#ff6b6b';status.textContent='运行失败: '+d.error;} return; }
    _rotData = d;
    window._rotLoaded = true;
    renderRotation(d);
    if(d.summary.data_quality && d.summary.data_quality!=='ok'){
      if(status){ status.style.color='#ffb648'; status.textContent='⚠ 数据降级('+d.summary.data_quality+')：'+d.summary.quality_note+' · 实测10年结果见研究报告'; }
    } else if(status){ status.style.color='var(--down)'; status.textContent='回测完成 · '+d.summary.range[0]+' ~ '+d.summary.range[1]+' · '+d.summary.n_years+'年 · 数据源缓存1小时'; }
  }catch(e){ if(status){status.style.color='#ff6b6b';status.textContent='请求失败: '+e;} }
  finally{ if(btn) btn.disabled=false; }
}
function renderRotation(d){
  const s=d.summary, bh=d.buy_hold;
  const pct=v=>(v*100).toFixed(1)+'%';
  const kpis=$('rot-kpis');
  if(kpis){
    kpis.innerHTML=[
      ['轮动总收益',pct(s.total),'up'],['年化收益',pct(s.ann),'up'],
      ['最大回撤',pct(s.mdd),'down'],['夏普比率',s.sharpe.toFixed(2),''],
      ['买入持有',pct(bh.total),''],['持有回撤',pct(bh.mdd),'down'],
      ['回测跨度',s.n_years+'年',''],['动量参数','N='+s.lookback,'']
    ].map(([l,v,c])=>'<div class="card" style="padding:14px"><div class="subtext">'+l+'</div><div class="metric '+(c||'')+'" style="font-size:20px;margin-top:4px">'+v+'</div></div>').join('');
  }
  // 参数敏感性表
  const grid=$('rot-grid');
  if(grid && d.grid && d.grid.length){
    const lbs=[...new Set(d.grid.map(x=>x.lookback))].sort((a,b)=>a-b);
    const bufs=[...new Set(d.grid.map(x=>x.buffer))].sort((a,b)=>a-b);
    let h='<table><thead><tr><th>N\\钝化</th>'+bufs.map(b=>'<th>'+(b*100).toFixed(1)+'%</th>').join('')+'</tr></thead><tbody>';
    for(const lb of lbs){
      h+='<tr><td><b>'+lb+'</b></td>';
      for(const buf of bufs){
        const cell=d.grid.find(x=>x.lookback===lb&&Math.abs(x.buffer-buf)<1e-9);
        const v=cell?cell.total*100:0;
        const col=v>0?'#ff6b6b':'#00b578';
        const alpha=Math.min(0.28,Math.abs(v)/330*0.28+0.04);
        h+='<td style="background:rgba('+(v>0?'255,107,107':'0,181,120')+','+alpha.toFixed(2)+')">'+v.toFixed(1)+'%</td>';
      }
      h+='</tr>';
    }
    grid.innerHTML=h+'</tbody></table>';
  }
  // 标的池
  const pool=$('rot-pool');
  if(pool){ pool.innerHTML=Object.entries(d.pool||{}).map(([c,n])=>c+' '+n).join('　·　'); }
  // 净值曲线
  drawRotationChart(d.equity||[]);
}
function drawRotationChart(equity){
  const cv=$('rot-chart'); if(!cv||!equity.length) return;
  const dpr=window.devicePixelRatio||1, w=cv.clientWidth, h=cv.clientHeight;
  cv.width=w*dpr; cv.height=h*dpr;
  const ctx=cv.getContext('2d'); ctx.scale(dpr,dpr);
  ctx.clearRect(0,0,w,h);
  const pad=44, mn=Math.min(...equity,1), mx=Math.max(...equity,1.1), range=(mx-mn)||1;
  const X=i=>pad+(w-pad-14)*i/(equity.length-1);
  const Y=v=>pad+(h-2*pad)*(1-(v-mn)/range);
  // 网格与本金线
  ctx.strokeStyle='#2a3446';ctx.lineWidth=1;
  for(let i=0;i<=4;i++){const y=pad+(h-2*pad)*i/4;ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(w-14,y);ctx.stroke();}
  ctx.strokeStyle='#5b6472';ctx.setLineDash([4,4]);
  ctx.beginPath();ctx.moveTo(pad,Y(1));ctx.lineTo(w-14,Y(1));ctx.stroke();ctx.setLineDash([]);
  // 净值线
  ctx.strokeStyle='#ff4d5e';ctx.lineWidth=2;ctx.beginPath();
  equity.forEach((v,i)=>{ i?ctx.lineTo(X(i),Y(v)):ctx.moveTo(X(i),Y(v)); });
  ctx.stroke();
  // 渐变填充
  const g=ctx.createLinearGradient(0,pad,0,h-pad);
  g.addColorStop(0,'rgba(255,77,94,0.22)');g.addColorStop(1,'rgba(255,77,94,0)');
  ctx.lineTo(X(equity.length-1),h-pad);ctx.lineTo(pad,h-pad);ctx.closePath();ctx.fillStyle=g;ctx.fill();
  ctx.fillStyle='#7d8ca3';ctx.font='11px sans-serif';
  ctx.fillText(mx.toFixed(2),4,pad+4);ctx.fillText(mn.toFixed(2),4,h-pad);
}

init();
