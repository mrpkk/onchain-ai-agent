/* KARTA dashboard — vanilla JS, XSS-safe, без npm (S4-01). */

// ── State ──
let TOKEN = localStorage.getItem('onchain_token') || '';
let USERNAME = localStorage.getItem('onchain_user') || '';
let AGENTS = [];
let TX_AGENT_ID = '';

// ── Init ──
if (TOKEN) { showDashboard(); }

function api(url, opts={}) {
  opts.headers = opts.headers || {};
  if (TOKEN) opts.headers['Authorization'] = 'Bearer ' + TOKEN;
  if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof FormData)) {
    opts.body = JSON.stringify(opts.body);
    opts.headers['Content-Type'] = 'application/json';
  }
  return fetch(url, opts).then(r => r.json().catch(() => ({error:r.statusText})));
}

function toast(msg, type='info') {
  const t = document.getElementById('toast');
  t.textContent = msg; t.className = 'toast ' + type;
  setTimeout(() => t.classList.add('show'), 10);
  setTimeout(() => t.classList.remove('show'), 3000);
}

// ── Auth ──
function switchAuth(tab) {
  document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.auth-form').forEach(f => f.classList.remove('active'));
  if (tab==='login') {
    document.querySelector('.auth-tab').classList.add('active');
    document.getElementById('login-form').classList.add('active');
  } else {
    document.querySelectorAll('.auth-tab')[1].classList.add('active');
    document.getElementById('register-form').classList.add('active');
  }
}

async function doLogin() {
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value.trim();
  if (!username || !password) { document.getElementById('login-error').textContent = 'Заполните все поля'; return; }
  document.getElementById('login-error').textContent = '⏳ Вход...';
  const res = await api('/api/v1/auth/token', {method:'POST', body:{username, password}});
  if (res.access_token) {
    TOKEN = res.access_token; USERNAME = username;
    localStorage.setItem('onchain_token', TOKEN);
    localStorage.setItem('onchain_user', USERNAME);
    showDashboard();
  } else {
    document.getElementById('login-error').textContent = res.detail || 'Ошибка входа';
  }
}

async function doRegister() {
  const username = document.getElementById('reg-username').value.trim();
  const password = document.getElementById('reg-password').value.trim();
  if (!username || !password) { document.getElementById('reg-error').textContent = 'Заполните все поля'; return; }
  document.getElementById('reg-error').textContent = '⏳ Регистрация...';
  const res = await api('/api/v1/auth/register', {method:'POST', body:{username, password}});
  if (res.id) {
    toast('✅ Аккаунт создан! Теперь войдите.', 'success');
    switchAuth('login');
    document.getElementById('login-username').value = username;
    document.getElementById('login-password').value = password;
    doLogin();
  } else {
    document.getElementById('reg-error').textContent = res.detail || 'Ошибка регистрации';
  }
}

function doLogout() {
  TOKEN = ''; USERNAME = '';
  localStorage.removeItem('onchain_token');
  localStorage.removeItem('onchain_user');
  document.getElementById('dash-screen').style.display = 'none';
  document.getElementById('auth-screen').style.display = 'flex';
  hideTxPanel();
}

// ── Dashboard ──
function showDashboard() {
  document.getElementById('auth-screen').style.display = 'none';
  document.getElementById('dash-screen').style.display = 'block';
  document.getElementById('dash-username').textContent = '👤 ' + USERNAME;
  loadAgents();
}

async function loadAgents() {
  const list = document.getElementById('agent-list');
  list.innerHTML = '<div class="agent-empty">⏳ Загрузка агентов...</div>';
  const res = await api('/api/v1/agents');
  AGENTS = res.agents || [];
  renderAgents();
  updateStats();
}

function updateStats() {
  const total = AGENTS.length;
  const running = AGENTS.filter(a => a.status === 'running').length;
  const created = AGENTS.filter(a => a.status === 'created').length;
  const stopped = AGENTS.filter(a => a.status === 'stopped').length;
  const killed = AGENTS.filter(a => a.status === 'killed').length;
  document.getElementById('stat-total').textContent = total;
  document.getElementById('stat-running').textContent = running;
  document.getElementById('stat-created').textContent = created;
  document.getElementById('stat-stopped').textContent = stopped;
  document.getElementById('stat-killed').textContent = killed;
}

function statusColor(s) {
  return s==='running' ? '#3fb950' : s==='created' ? '#8b949e' : s==='stopped' ? '#d29922' : '#f85149';
}
function statusLabel(s) {
  return s==='running' ? '✅ Активен' : s==='created' ? '⏳ Создан' : s==='stopped' ? '⏸️ Остановлен' : '☠️ Убит';
}

function renderAgents() {
  const list = document.getElementById('agent-list');
  if (!AGENTS.length) {
    list.innerHTML = '<div class="agent-empty">🤖 Нет агентов. Создайте первого!</div>';
    return;
  }
  list.innerHTML = AGENTS.map(a => {
    const c = statusColor(a.status);
    const l = statusLabel(a.status);
    const isRunning = a.status === 'running';
    const isKilled = a.status === 'killed';
    return `<div class="agent-row">
      <div class="agent-info">
        <div class="name"><span class="status-dot" style="background:${c}"></span>${a.name}</div>
        <div class="meta">
          <span>${l}</span>
          <span>🔗 Chain ${a.chain_id}</span>
          <span>📋 ${a.strategy}</span>
          <span>⏱️ ${new Date(a.created_at).toLocaleString()}</span>
          ${a.goal ? '<span>🎯 ' + a.goal.slice(0, 40) + (a.goal.length>40?'...':'') + '</span>' : ''}
        </div>
      </div>
      <div class="agent-actions">
        ${!isRunning && !isKilled ? `<button class="start-btn" onclick="doAction('${a.id}','start')">▶️ Запустить</button>` : ''}
        ${isRunning ? `<button class="stop-btn" onclick="doAction('${a.id}','stop')">⏸️ Стоп</button>` : ''}
        ${!isKilled ? `<button class="kill-btn" onclick="doAction('${a.id}','kill')">☠️ Kill</button>` : ''}
        <button class="goal-btn" onclick="showGoalModal('${a.id}')">🎯 Цель</button>
        <button class="tx-btn" onclick="showTx('${a.id}')">📋 TX</button>
      </div>
    </div>`;
  }).join('');
}

async function doAction(id, action) {
  let url = `/api/v1/agents/${id}/${action}`;
  if (action === 'kill') { url = `/api/v1/agents/${id}/kill-switch`; }
  let body = undefined;
  if (action === 'kill') body = {reason:'Manual kill via dashboard'};
  const res = await api(url, {method:'POST', body});
  if (res.id) {
    toast(action === 'start' ? '✅ Агент запущен' : action === 'stop' ? '⏸️ Агент остановлен' : '☠️ Kill Switch активирован', 'success');
    loadAgents();
  } else {
    toast('❌ Ошибка: ' + (res.detail || JSON.stringify(res)), 'error');
  }
}

// ── Create Modal ──
function showCreateModal() {
  document.getElementById('create-modal').classList.add('show');
  document.getElementById('new-name').value = '';
  document.getElementById('new-desc').value = '';
  document.getElementById('new-strategy').value = 'default';
  document.getElementById('new-chain').value = '1';
  setTimeout(() => document.getElementById('new-name').focus(), 100);
}
function hideCreateModal() { document.getElementById('create-modal').classList.remove('show'); }

async function createAgent() {
  const name = document.getElementById('new-name').value.trim();
  const desc = document.getElementById('new-desc').value.trim();
  if (!name) { toast('Введите имя агента', 'error'); return; }
  const res = await api('/api/v1/agents', {method:'POST', body:{
    name,
    description: desc,
    strategy: document.getElementById('new-strategy').value,
    chain_id: parseInt(document.getElementById('new-chain').value),
    config: {}
  }});
  if (res.id) {
    toast('✅ Агент ' + name + ' создан!', 'success');
    hideCreateModal();
    loadAgents();
  } else {
    toast('❌ ' + (res.detail || 'Ошибка'), 'error');
  }
}

// ── Goal Modal ──
let GOAL_AGENT_ID = '';
function showGoalModal(id) {
  GOAL_AGENT_ID = id;
  document.getElementById('goal-modal').classList.add('show');
  document.getElementById('goal-text').value = '';
  document.getElementById('goal-context').value = '';
  const agent = AGENTS.find(a => a.id === id);
  if (agent && agent.goal) document.getElementById('goal-text').value = agent.goal;
  setTimeout(() => document.getElementById('goal-text').focus(), 100);
}
function hideGoalModal() { document.getElementById('goal-modal').classList.remove('show'); GOAL_AGENT_ID = ''; }

async function setGoal() {
  const goal = document.getElementById('goal-text').value.trim();
  if (!goal) { toast('Введите цель', 'error'); return; }
  const context = document.getElementById('goal-context').value.trim();
  const res = await api('/api/v1/agents/' + GOAL_AGENT_ID + '/goal', {method:'POST', body:{goal, context}});
  if (res.id) {
    toast('🎯 Цель поставлена!', 'success');
    hideGoalModal();
    loadAgents();
  } else {
    toast('❌ ' + (res.detail || 'Ошибка'), 'error');
  }
}

// ── Transaction Panel ──
async function showTx(agentId) {
  TX_AGENT_ID = agentId;
  document.getElementById('tx-panel').classList.add('show');
  const list = document.getElementById('tx-list');
  list.innerHTML = '<div class="tx-empty">⏳ Загрузка транзакций...</div>';
  const res = await api('/api/v1/agents/' + agentId + '/transactions');
  const txs = res.transactions || [];
  const agent = AGENTS.find(a => a.id === agentId);
  if (!txs.length) {
    list.innerHTML = '<div class="tx-empty">📭 Нет транзакций для ' + (agent ? agent.name : 'агента') + '</div>';
    return;
  }
  list.innerHTML = txs.map(tx => `
    <div class="tx-item">
      <div class="tx-type">${tx.type || 'unknown'}</div>
      <div class="tx-hash">${tx.hash || tx.tx_hash || '-'}</div>
      <div style="display:flex;gap:8px;align-items:center;margin-top:4px;">
        <span class="tx-status ${(tx.status||'pending')}">${tx.status || 'pending'}</span>
        <span class="tx-time">${tx.timestamp ? new Date(tx.timestamp).toLocaleString() : ''}</span>
      </div>
    </div>
  `).join('');
}

function hideTxPanel() { document.getElementById('tx-panel').classList.remove('show'); TX_AGENT_ID = ''; }

// ── Keyboard shortcuts ──
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    hideCreateModal(); hideGoalModal(); hideTxPanel();
  }
});
