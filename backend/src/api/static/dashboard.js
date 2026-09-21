/* KARTA Cockpit — vanilla JS (S4-02): XSS-safe (textContent), WS-live, без npm. */
"use strict";

let TOKEN = localStorage.getItem("karta_token") || localStorage.getItem("onchain_token") || "";
let USERNAME = localStorage.getItem("karta_user") || localStorage.getItem("onchain_user") || "";
let AGENTS = [];
let SELECTED = null;
let WS = null;
let WS_RETRY = null;

if (TOKEN) { showDashboard(); }

/* ── API / UI helpers ─────────────────────────────────────────────── */
function api(url, opts = {}) {
  opts.headers = opts.headers || {};
  if (TOKEN) opts.headers["Authorization"] = "Bearer " + TOKEN;
  if (opts.body && typeof opts.body === "object" && !(opts.body instanceof FormData)) {
    opts.body = JSON.stringify(opts.body);
    opts.headers["Content-Type"] = "application/json";
  }
  return fetch(url, opts).then((r) => r.json().catch(() => ({ error: r.statusText })));
}

function toast(msg, type = "info") {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast " + type;
  setTimeout(() => el.classList.add("show"), 10);
  setTimeout(() => el.classList.remove("show"), 3200);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function fmtTime(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("ru-RU", { hour12: false }); } catch (e) { return iso; }
}

function statusBadge(status) {
  const b = el("span", "badge status-" + status, status);
  return b;
}

function riskBadge(level) {
  return el("span", "badge risk-" + (level || "medium"), "risk: " + (level || "—"));
}

function confBar(confidence) {
  const wrap = el("span", "conf-bar");
  const fill = el("span");
  const value = Math.max(0, Math.min(1, Number(confidence) || 0));
  fill.style.width = (value * 100).toFixed(0) + "%";
  wrap.appendChild(fill);
  return wrap;
}

/* ── Auth ─────────────────────────────────────────────────────────── */
function switchAuth(tab) {
  document.querySelectorAll(".auth-tab").forEach((t) => t.classList.remove("active"));
  document.querySelectorAll(".auth-form").forEach((f) => f.classList.remove("active"));
  if (tab === "login") {
    document.querySelectorAll(".auth-tab")[0].classList.add("active");
    document.getElementById("login-form").classList.add("active");
  } else {
    document.querySelectorAll(".auth-tab")[1].classList.add("active");
    document.getElementById("register-form").classList.add("active");
  }
}

async function doLogin() {
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("login-password").value.trim();
  const err = document.getElementById("login-error");
  if (!username || !password) { err.textContent = "Заполните все поля"; return; }
  err.textContent = "Вход…";
  const res = await api("/api/v1/auth/token", { method: "POST", body: { username, password } });
  if (res.access_token) {
    TOKEN = res.access_token; USERNAME = username;
    localStorage.setItem("karta_token", TOKEN);
    localStorage.setItem("karta_user", USERNAME);
    showDashboard();
  } else {
    err.textContent = res.detail || "Ошибка входа";
  }
}

async function doRegister() {
  const username = document.getElementById("reg-username").value.trim();
  const password = document.getElementById("reg-password").value.trim();
  const err = document.getElementById("reg-error");
  if (!username || !password) { err.textContent = "Заполните все поля"; return; }
  err.textContent = "Регистрация…";
  const res = await api("/api/v1/auth/register", { method: "POST", body: { username, password } });
  if (res.id) {
    toast("Аккаунт создан — входим", "success");
    switchAuth("login");
    document.getElementById("login-username").value = username;
    document.getElementById("login-password").value = password;
    doLogin();
  } else {
    err.textContent = res.detail || "Ошибка регистрации";
  }
}

function doLogout() {
  if (WS) { WS.onclose = null; WS.close(); WS = null; }
  TOKEN = ""; USERNAME = ""; SELECTED = null;
  localStorage.removeItem("karta_token");
  localStorage.removeItem("karta_user");
  document.getElementById("dash-screen").style.display = "none";
  document.getElementById("auth-screen").style.display = "flex";
  hideTxPanel();
}

function showDashboard() {
  document.getElementById("auth-screen").style.display = "none";
  document.getElementById("dash-screen").style.display = "block";
  document.getElementById("dash-username").textContent = USERNAME;
  loadAgents();
  connectWS();
}

/* ── WebSocket (live) ─────────────────────────────────────────────── */
function setWsBadge(state) {
  const badge = document.getElementById("ws-status");
  badge.dataset.state = state;
  badge.textContent = state === "live" ? "WS LIVE" : "WS OFFLINE";
}

function connectWS() {
  if (!TOKEN) return;
  try {
    WS = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws?token=" + encodeURIComponent(TOKEN));
  } catch (e) { setWsBadge("offline"); return; }
  WS.onopen = () => setWsBadge("live");
  WS.onmessage = (event) => {
    let data = null;
    try { data = JSON.parse(event.data); } catch (e) { return; }
    handleWsEvent(data);
  };
  WS.onclose = () => {
    setWsBadge("offline");
    if (TOKEN) { clearTimeout(WS_RETRY); WS_RETRY = setTimeout(connectWS, 3000); }
  };
  WS.onerror = () => setWsBadge("offline");
}

function handleWsEvent(data) {
  if (data.type === "hello") { setWsBadge("live"); return; }
  if (data.type === "agent.status") {
    const agent = AGENTS.find((a) => a.id === data.agent_id);
    if (agent) { agent.status = data.status; renderAgents(); }
    if (SELECTED && SELECTED === data.agent_id) { renderStatusCard(); refreshPending(); }
    toast("Агент: " + data.status, data.status === "killed" ? "error" : "info");
    return;
  }
  if (data.type === "decision.proposed") {
    if (SELECTED && data.agent_id === SELECTED) refreshFeed();
    toast("Решение: " + data.action + " (уверенность " + Math.round((data.confidence || 0) * 100) + "%)", "info");
    return;
  }
  if (data.type === "action.scheduled") {
    if (SELECTED && data.agent_id === SELECTED) refreshPending();
    toast("Действие отложено (окно undo)", "info");
  }
}

/* ── Agents ───────────────────────────────────────────────────────── */
async function loadAgents() {
  const list = document.getElementById("agent-list");
  list.replaceChildren(el("div", "empty", "Загрузка…"));
  const res = await api("/api/v1/agents");
  AGENTS = res.agents || [];
  renderAgents();
  if (AGENTS.length && !SELECTED) selectAgent(AGENTS[0].id);
}

function renderAgents() {
  const list = document.getElementById("agent-list");
  list.replaceChildren();
  if (!AGENTS.length) {
    list.appendChild(el("div", "empty", "Пока нет агентов — создайте первого"));
    return;
  }
  AGENTS.forEach((agent) => {
    const row = el("div", "agent-row" + (SELECTED === agent.id ? " selected" : ""));
    const head = el("div", "name");
    head.appendChild(el("span", null, agent.name));
    head.appendChild(statusBadge(agent.status));
    row.appendChild(head);
    row.appendChild(el("div", "meta", "chain_id " + agent.chain_id + " · " + (agent.strategy || "default")));
    row.onclick = () => selectAgent(agent.id);

    const actions = el("div", "agent-actions");
    const startBtn = el("button", "btn small", "▶ Старт");
    startBtn.onclick = (e) => { e.stopPropagation(); agentAction(agent.id, "start"); };
    const stopBtn = el("button", "btn small ghost", "⏸ Стоп");
    stopBtn.onclick = (e) => { e.stopPropagation(); agentAction(agent.id, "stop"); };
    const killBtn = el("button", "btn small danger", "☠ Kill");
    killBtn.onclick = (e) => { e.stopPropagation(); killAgent(agent.id); };
    const goalBtn = el("button", "btn small ghost", "🎯 Цель");
    goalBtn.onclick = (e) => { e.stopPropagation(); showGoalModal(agent.id); };
    const txBtn = el("button", "btn small ghost", "📋 Tx");
    txBtn.onclick = (e) => { e.stopPropagation(); showTxPanel(agent.id); };
    actions.append(startBtn, stopBtn, killBtn, goalBtn, txBtn);
    row.appendChild(actions);
    list.appendChild(row);
  });
}

async function agentAction(agentId, action) {
  const res = await api("/api/v1/agents/" + agentId + "/" + action, { method: "POST" });
  if (res.id) { toast("Статус: " + res.status, "success"); await loadAgents(); }
  else { toast(res.detail || "Ошибка", "error"); }
}

async function killAgent(agentId) {
  if (!confirm("Экстренная остановка (hard kill). Продолжить?")) return;
  const res = await api("/api/v1/agents/" + agentId + "/kill-switch", { method: "POST", body: { reason: "cockpit" } });
  if (res.id) { toast("Kill switch: агент остановлен", "error"); await loadAgents(); }
  else { toast(res.detail || "Ошибка", "error"); }
}

function showCreateModal() { document.getElementById("create-modal").classList.add("show"); }
function hideCreateModal() { document.getElementById("create-modal").classList.remove("show"); }

async function createAgent() {
  const name = document.getElementById("new-name").value.trim();
  if (!name) { toast("Укажите имя", "error"); return; }
  const body = {
    name,
    description: document.getElementById("new-desc").value.trim(),
    strategy: document.getElementById("new-strategy").value,
    chain_id: Number(document.getElementById("new-chain").value),
  };
  const res = await api("/api/v1/agents", { method: "POST", body });
  if (res.id) {
    hideCreateModal();
    toast("Агент создан", "success");
    document.getElementById("new-name").value = "";
    await loadAgents();
    selectAgent(res.id);
  } else { toast(res.detail || "Ошибка", "error"); }
}

/* ── Goal ─────────────────────────────────────────────────────────── */
let GOAL_AGENT = null;
function showGoalModal(agentId) { GOAL_AGENT = agentId; document.getElementById("goal-modal").classList.add("show"); }
function hideGoalModal() { document.getElementById("goal-modal").classList.remove("show"); }
async function setGoal() {
  const goal = document.getElementById("goal-text").value.trim();
  if (!goal || !GOAL_AGENT) { toast("Введите цель", "error"); return; }
  const res = await api("/api/v1/agents/" + GOAL_AGENT + "/goal", { method: "POST", body: { goal } });
  if (res.id) { hideGoalModal(); toast("Цель поставлена", "success"); }
  else { toast(res.detail || "Ошибка", "error"); }
}

/* ── Selected agent: status / pending / feed / audit ──────────────── */
async function selectAgent(agentId) {
  SELECTED = agentId;
  document.getElementById("chat-preview").replaceChildren();
  document.getElementById("chat-result").replaceChildren();
  renderAgents();
  renderStatusCard();
  await Promise.all([refreshFeed(), refreshPending(), refreshAudit()]);
}

/* ── Chat-first intent (S4-03) ────────────────────────────────────── */
let CHAT_INTENT = null;

async function parseChat() {
  if (!SELECTED) { toast("Выберите агента", "error"); return; }
  const text = document.getElementById("chat-input").value.trim();
  if (!text) { toast("Введите задачу", "error"); return; }
  const preview = document.getElementById("chat-preview");
  preview.replaceChildren(el("div", "empty", "Разбираю…"));
  const res = await api("/api/v1/agents/" + SELECTED + "/intent", { method: "POST", body: { text } });
  if (!res.ok) {
    preview.replaceChildren(el("div", "empty", res.detail || res.error || "Ошибка разбора"));
    return;
  }
  CHAT_INTENT = res.intent;
  renderIntentPreview(res);
}

function renderIntentPreview(res) {
  const preview = document.getElementById("chat-preview");
  preview.replaceChildren();
  const intent = res.intent || {};
  const card = el("div", "intent-card");

  const head = el("div", "head");
  head.appendChild(el("span", "action", intent.action || "unknown"));
  head.appendChild(confBar(intent.confidence));
  head.appendChild(el("span", "time", intent.needs_clarification ? "нужны уточнения" : "готово к подтверждению"));
  card.appendChild(head);

  card.appendChild(el("div", "summary", intent.summary || "—"));
  card.appendChild(el("div", "params", JSON.stringify(intent.params || {}, null, 2)));

  const verdict = res.policy_verdict || {};
  const vline = el("div", "status-line");
  vline.appendChild(el("span", "muted", "Dharma (предварительно)"));
  const decision = verdict.decision || "unknown";
  const vbadge = el("span", "badge " + (decision === "allow" ? "risk-low" : decision === "deny" ? "risk-high" : "risk-medium"), "policy: " + decision);
  vline.appendChild(vbadge);
  card.appendChild(vline);
  if (verdict.reasons && verdict.reasons.length) {
    card.appendChild(el("div", "warn-list", "• " + verdict.reasons.join("\n• ")));
  }

  if ((intent.assumptions || []).length) {
    card.appendChild(el("div", "muted", "Допущения: " + intent.assumptions.join("; ")));
  }
  if ((intent.questions || []).length) {
    card.appendChild(el("div", "warn-list", "Уточните: " + intent.questions.join("; ")));
  }

  const actions = el("div", "intent-actions");
  if (!intent.needs_clarification) {
    const confirmBtn = el("button", "btn primary small", "Подтвердить");
    confirmBtn.onclick = () => confirmChat();
    actions.appendChild(confirmBtn);
  }
  const cancelBtn = el("button", "btn ghost small", "Отмена");
  cancelBtn.onclick = cancelChat;
  actions.appendChild(cancelBtn);
  card.appendChild(actions);
  preview.appendChild(card);
}

async function confirmChat() {
  if (!CHAT_INTENT || !SELECTED) return;
  const result = document.getElementById("chat-result");
  result.replaceChildren(el("div", "empty", "Исполняю (policy → simulation → …)…"));
  const res = await api("/api/v1/agents/" + SELECTED + "/intent/confirm",
                        { method: "POST", body: { action: CHAT_INTENT.action, params: CHAT_INTENT.params } });
  result.replaceChildren();
  if (res.detail && res.detail.errors === undefined && typeof res.detail === "string") {
    result.appendChild(el("div", "warn-list", res.detail));
    return;
  }
  const status = res.status || "unknown";
  const line = el("div", "status-line");
  line.appendChild(el("span", "action", "Результат"));
  line.appendChild(el("span", "badge " + (status === "confirmed" ? "risk-low" : status === "pending" ? "risk-medium" : "risk-high"), status));
  result.appendChild(line);
  if (res.tx_hash) result.appendChild(el("div", "params", "tx: " + res.tx_hash));
  if (res.error) result.appendChild(el("div", "warn-list", res.error));
  if (status === "pending") { refreshPending(); toast("Отложено в окно undo", "info"); }
}

function cancelChat() {
  CHAT_INTENT = null;
  document.getElementById("chat-preview").replaceChildren();
  document.getElementById("chat-result").replaceChildren();
}

function renderStatusCard() {
  const card = document.getElementById("status-card");
  const agent = AGENTS.find((a) => a.id === SELECTED);
  document.getElementById("status-agent-name").textContent = agent ? agent.name : "—";
  if (!agent) { card.replaceChildren(el("div", "empty", "Выберите агента")); return; }
  card.replaceChildren();
  const line1 = el("div", "status-line");
  line1.appendChild(el("span", "muted", "Статус"));
  line1.appendChild(statusBadge(agent.status));
  card.appendChild(line1);

  const line2 = el("div", "status-line");
  line2.appendChild(el("span", "muted", "Сеть"));
  line2.appendChild(el("span", "mono", "chain_id " + agent.chain_id));
  card.appendChild(line2);

  const line3 = el("div", "status-line");
  line3.appendChild(el("span", "muted", "Кошелёк"));
  line3.appendChild(el("span", "mono", agent.wallet_address || "не настроен"));
  card.appendChild(line3);

  const hb = el("button", "btn small ghost", "♥ Heartbeat");
  hb.onclick = async () => {
    const res = await api("/api/v1/agents/" + SELECTED + "/heartbeat", { method: "POST" });
    toast(res.status === "ok" ? "Heartbeat отправлен" : (res.detail || "Агент не запущен"),
          res.status === "ok" ? "success" : "error");
  };
  card.appendChild(hb);
}

async function refreshFeed() {
  const feed = document.getElementById("decisions-feed");
  if (!SELECTED) { feed.replaceChildren(el("div", "empty", "Выберите агента")); return; }
  const res = await api("/api/v1/agents/" + SELECTED + "/decisions?limit=30");
  const decisions = res.decisions || [];
  feed.replaceChildren();
  if (!decisions.length) { feed.appendChild(el("div", "empty", "Решений пока нет")); return; }
  decisions.forEach((d) => feed.appendChild(decisionCard(d)));
}

function decisionCard(d) {
  const card = el("div", "decision-card");
  const head = el("div", "head");
  head.appendChild(el("span", "action", d.action));
  head.appendChild(riskBadge(d.risk_level));
  head.appendChild(confBar(d.confidence));
  head.appendChild(el("span", "time", fmtTime(d.created_at)));
  card.appendChild(head);

  card.appendChild(el("div", "reasoning", (d.reasoning || "—")));

  const why = el("button", "why-btn", "Почему?");
  const details = el("div", "why-details");
  details.style.display = "none";
  const lines = [];
  lines.push("confidence: " + (d.confidence !== null && d.confidence !== undefined ? d.confidence : "—"));
  lines.push("status: " + (d.status || "—"));
  if (d.requires_approval) lines.push("requires_approval: true");
  if (d.policy_verdict) lines.push("policy_verdict: " + JSON.stringify(d.policy_verdict, null, 2));
  details.textContent = lines.join("\n");
  why.onclick = () => { details.style.display = details.style.display === "none" ? "block" : "none"; };
  card.append(why, details);
  return card;
}

async function refreshPending() {
  const list = document.getElementById("pending-list");
  const count = document.getElementById("pending-count");
  if (!SELECTED) { list.replaceChildren(el("div", "empty", "—")); count.textContent = "0"; return; }
  const res = await api("/api/v1/agents/" + SELECTED + "/pending");
  if (res.detail) { list.replaceChildren(el("div", "empty", res.detail)); count.textContent = "0"; return; }
  const items = res.pending || [];
  count.textContent = String(res.total || 0);
  list.replaceChildren();
  if (!items.length) { list.appendChild(el("div", "empty", "Нет отложенных действий")); return; }
  items.forEach((item) => {
    const row = el("div", "pending-item");
    const info = el("div");
    info.appendChild(el("div", null, item.action + " · до " + fmtTime(item.execute_after)));
    info.appendChild(el("div", "muted mono", "id " + item.id));
    row.appendChild(info);
    const cancel = el("button", "btn small danger", "Отменить");
    cancel.onclick = async () => {
      const res2 = await api("/api/v1/agents/" + SELECTED + "/pending/" + item.id + "/cancel", { method: "POST" });
      if (res2.status === "ok") { toast("Отменено", "success"); refreshPending(); }
      else { toast(res2.detail || "Ошибка", "error"); }
    };
    row.appendChild(cancel);
    list.appendChild(row);
  });
}

async function refreshAudit() {
  const list = document.getElementById("audit-list");
  const count = document.getElementById("audit-count");
  if (!SELECTED) { list.replaceChildren(el("div", "empty", "—")); count.textContent = "0"; return; }
  const res = await api("/api/v1/agents/" + SELECTED + "/audit?limit=100");
  if (res.detail) { list.replaceChildren(el("div", "empty", res.detail)); count.textContent = "0"; return; }
  const events = res.events || [];
  count.textContent = String(res.total || 0);
  list.replaceChildren();
  if (!events.length) { list.appendChild(el("div", "empty", "Событий пока нет")); return; }
  events.slice().reverse().forEach((e) => {
    const row = el("div", "audit-row");
    row.appendChild(el("span", "etype", e.event_type));
    row.appendChild(el("span", "hash", (e.hash || "").slice(0, 10) + "…"));
    const details = el("div", "audit-details");
    details.style.display = "none";
    details.textContent = JSON.stringify({ actor: e.actor, payload: e.payload, prev_hash: e.prev_hash, hash: e.hash, created_at: e.created_at }, null, 2);
    row.onclick = () => { details.style.display = details.style.display === "none" ? "block" : "none"; };
    list.append(row, details);
  });
}

/* ── Transactions drawer ──────────────────────────────────────────── */
async function showTxPanel(agentId) {
  document.getElementById("tx-panel").classList.add("show");
  const list = document.getElementById("tx-list");
  list.replaceChildren(el("div", "empty", "Загрузка…"));
  const res = await api("/api/v1/agents/" + agentId + "/transactions");
  const txs = res.transactions || [];
  list.replaceChildren();
  if (!txs.length) { list.appendChild(el("div", "empty", "Транзакций пока нет (исполнение — Phase 5)")); return; }
  txs.forEach((tx) => {
    const item = el("div", "audit-row");
    item.appendChild(el("span", "etype", tx.status + " · " + (tx.tx_hash || "—").slice(0, 14)));
    item.appendChild(el("span", "hash", tx.timestamp ? String(tx.timestamp).slice(0, 19) : ""));
    list.appendChild(item);
  });
}
function hideTxPanel() { document.getElementById("tx-panel").classList.remove("show"); }
