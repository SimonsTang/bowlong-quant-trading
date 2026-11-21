/* 巧未来-波龙量化 · 配置中心前端（schema 驱动动态表单） */
let cfgSchema = {}, cfgValues = {}, cfgCurrentGroup = 'ai';

const GROUP_LABELS = {
  system: '系统', ai: '🤖 AI 接口', data: '📊 数据源', backtest: '🧪 回测',
  risk: '🛡 风控', compliance: '📋 合规', execution: '⚡ 执行',
  selector: '🎯 选股', notify: '🔔 通知',
};

async function initConfig() {
  try {
    const r = await (await fetch('/api/config')).json();
    cfgSchema = r.schema;
    cfgValues = r.values;
    renderConfigTabs();
    renderConfigGroup(cfgCurrentGroup);
    renderConfigChecks(r.status);
    updateConfigBadge(r.status);
    maybeShowOnboarding(r.status);
  } catch (e) {
    $('config-form').innerHTML = `<div class="subtext">配置加载失败: ${e}</div>`;
  }
}

function renderConfigTabs() {
  $('config-tabs').innerHTML = Object.keys(cfgSchema).map(g =>
    `<button class="config-tab ${g === cfgCurrentGroup ? 'active' : ''}" data-group="${g}"
      onclick="switchConfigGroup('${g}')">${GROUP_LABELS[g] || g}</button>`).join('');
}

function cacheCurrentGroup() {
  // 切页前把当前页输入缓存起来，避免切换分类后未保存的修改被静默丢弃
  const fields = cfgSchema[cfgCurrentGroup] || {};
  if (!cfgValues[cfgCurrentGroup]) cfgValues[cfgCurrentGroup] = {};
  for (const key of Object.keys(fields)) {
    const el = $('cfg-' + cfgCurrentGroup + '-' + key);
    if (!el) continue;
    const spec = fields[key];
    if (spec.secret && String(el.value).includes('*')) continue;  // 保留原值，不缓存脱敏串
    let v = el.value;
    if (spec.type === 'int') v = parseInt(v);
    else if (spec.type === 'float') v = parseFloat(v);
    else if (spec.type === 'bool') v = v === 'true';
    cfgValues[cfgCurrentGroup][key] = v;
  }
}
function switchConfigGroup(g) {
  if (g === cfgCurrentGroup) return;
  cacheCurrentGroup();
  cfgCurrentGroup = g;
  document.querySelectorAll('.config-tab').forEach(t => t.classList.toggle('active', t.dataset.group === g));
  renderConfigGroup(g);
}

function renderConfigGroup(group) {
  const fields = cfgSchema[group] || {};
  const vals = cfgValues[group] || {};
  const html = Object.entries(fields).map(([key, spec]) => {
    const v = vals[key] !== undefined ? vals[key] : spec.default;
    let control;
    if (spec.options) {
      control = `<select id="cfg-${group}-${key}">${spec.options.map(o =>
        `<option value="${o}" ${String(o) === String(v) ? 'selected' : ''}>${o}</option>`).join('')}</select>`;
    } else if (spec.type === 'bool') {
      control = `<select id="cfg-${group}-${key}">
        <option value="true" ${v ? 'selected' : ''}>启用</option>
        <option value="false" ${!v ? 'selected' : ''}>禁用</option></select>`;
    } else if (spec.secret) {
      control = `<div class="config-row-inline">
        <input type="password" id="cfg-${group}-${key}" value="${esc(String(v))}" autocomplete="new-password">
        <button class="secret-toggle" onclick="toggleSecret('cfg-${group}-${key}',this)">显示</button></div>`;
    } else {
      const t = spec.type === 'int' || spec.type === 'float' ? 'number' : 'text';
      const stepAttr = spec.type === 'float' ? 'step="any"' : '';
      control = `<input type="${t}" id="cfg-${group}-${key}" value="${esc(String(v))}" ${stepAttr}>`;
    }
    // AI 分组加测试连接按钮
    const extra = (group === 'ai' && key === 'api_key') ?
      `<button class="btn ghost" style="margin-top:8px;font-size:11px" onclick="testAIConfig()">测试连接</button>
       <div id="ai-test-result"></div>` : '';
    return `<div class="config-field">
      <div class="label">${spec.secret ? '🔒 ' : ''}${esc(key)}</div>
      <div class="desc">${esc(spec.desc)}${spec.min !== undefined ? ` (范围 ${spec.min}~${spec.max !== undefined ? spec.max : '∞'})` : ''}</div>
      ${control}${extra}
    </div>`;
  }).join('');
  $('config-form').innerHTML = `<div class="config-grid">${html || '<div class="subtext">无配置项</div>'}</div>`;
}

function toggleSecret(id, btn) {
  const el = $(id);
  if (el.type === 'password') { el.type = 'text'; btn.textContent = '隐藏'; }
  else { el.type = 'password'; btn.textContent = '显示'; }
}

function collectConfig() {
  // 以缓存值为底，当前页 DOM 覆盖；这样跨分类的修改不会丢失
  const out = JSON.parse(JSON.stringify(cfgValues || {}));
  // 脱敏值绝不能回写，否则会覆盖真实密钥
  for (const [group, fields] of Object.entries(cfgSchema)) {
    for (const [key, spec] of Object.entries(fields)) {
      if (spec.secret && out[group] && typeof out[group][key] === 'string' && out[group][key].includes('*')) {
        delete out[group][key];
      }
    }
  }
  for (const group of Object.keys(cfgSchema)) {
    if (!out[group]) out[group] = {};
    for (const [key, spec] of Object.entries(cfgSchema[group])) {
      const el = $('cfg-' + group + '-' + key);
      if (!el) continue;
      if (spec.secret && String(el.value).includes('*')) continue;  // 未修改的脱敏密钥
      let v = el.value;
      if (spec.type === 'int') v = parseInt(v);
      else if (spec.type === 'float') v = parseFloat(v);
      else if (spec.type === 'bool') v = v === 'true';
      out[group][key] = v;
    }
  }
  return out;
}

async function saveConfig() {
  const values = collectConfig();
  // 实盘模式风险确认：防止误切
  if (values.system && values.system.mode === 'live') {
    const needBroker = !values.execution.qmt_path || !values.execution.account_id;
    const msg = needBroker
      ? '⚠️ 您正在切换到【实盘模式】，但 QMT 路径或账户ID 尚未配置，实盘下单会失败。\n\n确定继续吗？'
      : '⚠️ 您正在切换到【实盘模式】，保存后系统将允许真实报单。\n\n请确认：\n1. 已完成券商 miniQMT 开通\n2. 已用模拟账号充分验证策略\n3. 风控与合规参数已设置合理\n\n确定继续吗？';
    if (!confirm(msg)) return;
  }
  const btn = $('config-save-btn');
  btn.disabled = true;
  $('config-msg').innerHTML = '<div class="subtext">保存中…</div>';
  try {
    const r = await (await fetch('/api/config', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({values})})).json();
    if (r.ok) {
      $('config-msg').innerHTML = `<div class="config-msg-ok">✓ 配置已保存并热更新，无需重启。当前模式：${esc(r.status.mode)}</div>`;
      cfgValues = (await (await fetch('/api/config')).json()).values;
      renderConfigChecks(r.status);
      updateConfigBadge(r.status);
      // 同步顶栏模式提示
      $('mode-badge').textContent = (typeof modeLabel === 'function' && modeLabel(r.status.mode))
        || (r.status.mode === 'live' ? 'LIVE · 真实报单模式' : 'VALIDATE · 不产生真实委托');
      $('mode-badge').className = r.status.mode === 'live' ? 'badge' : 'badge green';
    } else {
      $('config-msg').innerHTML = `<div class="config-msg-err">保存失败: ${esc(r.error)}</div>`;
    }
  } catch (e) { $('config-msg').innerHTML = `<div class="config-msg-err">保存失败: ${e}</div>`; }
  btn.disabled = false;
}

async function testAIConfig() {
  const box = $('ai-test-result');
  box.innerHTML = '<div class="test-result">测试中…</div>';
  const test = {
    api_key: $('cfg-ai-api_key').value,
    base_url: $('cfg-ai-base_url').value,
    model: $('cfg-ai-model').value,
  };
  try {
    const r = await (await fetch('/api/config/test', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({config: test})})).json();
    box.innerHTML = r.ok
      ? `<div class="test-result ok">✓ 连接成功 · 模型 ${esc(r.model)} · 回复: ${esc(r.reply)}</div>`
      : `<div class="test-result bad">✗ 连接失败: ${esc(r.error)}</div>`;
  } catch (e) { box.innerHTML = `<div class="test-result bad">测试失败: ${e}</div>`; }
}

async function resetConfig() {
  if (!confirm('确定恢复所有配置为默认值？此操作不可撤销。')) return;
  try {
    const r = await (await fetch('/api/config/reset', {method: 'POST'})).json();
    cfgValues = r.values;
    renderConfigGroup(cfgCurrentGroup);
    const st = await (await fetch('/api/config/status')).json();
    renderConfigChecks(st);
    updateConfigBadge(st);
    $('config-msg').innerHTML = '<div class="config-msg-ok">✓ 已恢复默认配置</div>';
  } catch (e) { $('config-msg').innerHTML = `<div class="config-msg-err">${e}</div>`; }
}

function renderConfigChecks(st) {
  if (!st || !st.checks) return;
  $('config-mode-badge').textContent = '当前模式: ' + st.mode;
  $('config-checks').innerHTML = st.checks.map(c => `
    <div class="check-item ${c.ok ? 'ok' : 'bad'}">
      <div class="icon">${c.ok ? '✓' : '!'}</div>
      <div><div class="ci-name">${esc(c.item)}</div><div class="ci-hint">${esc(c.hint)}</div></div>
    </div>`).join('');
}

function updateConfigBadge(st) {
  const badge = $('config-badge');
  if (!badge) return;
  badge.textContent = st.ready ? '已完成' : '待配置';
  badge.className = st.ready ? 'badge green' : 'badge';
  badge.style.fontSize = '9px';
  badge.style.marginLeft = 'auto';
}

function goPage(name) {
  const nav = document.querySelector(`.nav-item[data-page="${name}"]`);
  if (nav) nav.click();
}

// ---------- 首次使用引导 ----------
async function maybeShowOnboarding(status) {
  if (localStorage.getItem('qiao_onboarded') === '1') return;
  if (status && status.ready) return;  // 配置完整则不打扰
  const st = status || await (await fetch('/api/config/status')).json();
  $('onboarding-checks').innerHTML =
    (st.checks || []).map(c => `<div class="check-item ${c.ok ? 'ok' : 'bad'}" style="margin-bottom:8px">
      <div class="icon">${c.ok ? '✓' : '!'}</div>
      <div><div class="ci-name">${esc(c.item)}</div><div class="ci-hint">${esc(c.hint)}</div></div>
    </div>`).join('') +
    `<div class="onboarding-hint">建议先完成配置：接入云端 AI 获得自然语言分析能力（不配置也可用本地工具直答）。所有数据均为真实行情，回测绝不使用随机数。</div>`;
  $('onboarding').style.display = 'flex';
}
function dismissOnboarding() {
  localStorage.setItem('qiao_onboarded', '1');
  $('onboarding').style.display = 'none';
}
function goConfigFromOnboarding() {
  dismissOnboarding();
  goPage('config');
}
