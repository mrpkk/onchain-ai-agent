/* KARTA Cockpit — vanilla JS (S4-02): XSS-safe (textContent), WS-live, без npm. */
"use strict";

let TOKEN = localStorage.getItem("karta_token") || localStorage.getItem("onchain_token") || "";
let USERNAME = localStorage.getItem("karta_user") || localStorage.getItem("onchain_user") || "";
let AGENTS = [];
let SELECTED = null;
let WS = null;
let WS_RETRY = null;

applyI18n();

function onLangChanged() {
  if (TOKEN) {
    renderAgents();
    renderStatusCard();
    if (SELECTED) { refreshFeed(); refreshPending(); refreshAudit(); refreshReport(); }
    refreshApprovals();
    refreshRicardian();
  }
}

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
  refreshApprovals();
  refreshRicardian();
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
    toast(t("toast.agent_status", { status: data.status }), data.status === "killed" ? "error" : "info");
    return;
  }
  if (data.type === "decision.proposed") {
    if (SELECTED && data.agent_id === SELECTED) refreshFeed();
    toast(t("toast.decision", { action: data.action, confidence: Math.round((data.confidence || 0) * 100) }), "info");
    return;
  }
  if (data.type === "approval.requested") {
    toast(t("toast.approval", { action: data.action || "…" }), "error");
    refreshApprovals();
    return;
  }
  if (data.type === "action.scheduled") {
    if (SELECTED && data.agent_id === SELECTED) refreshPending();
    toast(t("toast.scheduled"), "info");
  }
}

/* ── Agents ───────────────────────────────────────────────────────── */
async function loadAgents() {
  const list = document.getElementById("agent-list");
  list.replaceChildren(el("div", "empty", t("empty.loading")));
  const res = await api("/api/v1/agents");
  AGENTS = res.agents || [];
  renderAgents();
  if (AGENTS.length && !SELECTED) selectAgent(AGENTS[0].id);
  if (!AGENTS.length && !sessionStorage.getItem("karta_onb_dismissed")) startOnboarding();
}

function renderAgents() {
  const list = document.getElementById("agent-list");
  list.replaceChildren();
  if (!AGENTS.length) {
    list.appendChild(el("div", "empty", t("empty.no_agents")));
    return;
  }
  AGENTS.forEach((agent) => {
    const row = el("div", "agent-row" + (SELECTED === agent.id ? " selected" : ""));
    const head = el("div", "name");
    head.appendChild(el("span", null, agent.name));
    head.appendChild(statusBadge(agent.status));
    row.appendChild(head);
    row.appendChild(el("div", "meta", "chain_id " + agent.chain_id + " · " + (agent.strategy || "default")));
    const onchain = agent.config && agent.config.onchain;
    if (onchain && onchain.agent_id !== undefined) {
      const chips = el("div", "meta");
      chips.appendChild(el("span", "badge", "⛓ #" + onchain.agent_id + (onchain.verified ? " ✓" : "")));
      row.appendChild(chips);
    }
    row.onclick = () => selectAgent(agent.id);

    const actions = el("div", "agent-actions");
    const startBtn = el("button", "btn small", t("btn.start"));
    startBtn.onclick = (e) => { e.stopPropagation(); agentAction(agent.id, "start"); };
    const stopBtn = el("button", "btn small ghost", t("btn.stop"));
    stopBtn.onclick = (e) => { e.stopPropagation(); agentAction(agent.id, "stop"); };
    const killBtn = el("button", "btn small danger", t("btn.kill"));
    killBtn.onclick = (e) => { e.stopPropagation(); killAgent(agent.id); };
    const goalBtn = el("button", "btn small ghost", t("btn.goal"));
    goalBtn.onclick = (e) => { e.stopPropagation(); showGoalModal(agent.id); };
    const txBtn = el("button", "btn small ghost", t("btn.tx"));
    txBtn.onclick = (e) => { e.stopPropagation(); showTxPanel(agent.id); };
    const passportBtn = el("button", "btn small ghost", t("btn.passport"));
    passportBtn.onclick = (e) => { e.stopPropagation(); openRegistry(agent.id); };
    actions.append(startBtn, stopBtn, killBtn, goalBtn, txBtn, passportBtn);
    row.appendChild(actions);
    list.appendChild(row);
  });
}

async function agentAction(agentId, action) {
  const res = await api("/api/v1/agents/" + agentId + "/" + action, { method: "POST" });
  if (res.id) { toast(t("toast.status_prefix", { status: res.status }), "success"); await loadAgents(); }
  else { toast(res.detail || t("toast.error"), "error"); }
}

async function killAgent(agentId) {
  if (!confirm(t("confirm.kill"))) return;
  const res = await api("/api/v1/agents/" + agentId + "/kill-switch", { method: "POST", body: { reason: "cockpit" } });
  if (res.id) { toast(t("toast.kill_done"), "error"); await loadAgents(); }
  else { toast(res.detail || t("toast.error"), "error"); }
}

function showCreateModal() { document.getElementById("create-modal").classList.add("show"); }
function hideCreateModal() { document.getElementById("create-modal").classList.remove("show"); }

async function createAgent() {
  const name = document.getElementById("new-name").value.trim();
  if (!name) { toast(t("toast.enter_name"), "error"); return; }
  const body = {
    name,
    description: document.getElementById("new-desc").value.trim(),
    strategy: document.getElementById("new-strategy").value,
    chain_id: Number(document.getElementById("new-chain").value),
  };
  const res = await api("/api/v1/agents", { method: "POST", body });
  if (res.id) {
    hideCreateModal();
    toast(t("toast.created"), "success");
    document.getElementById("new-name").value = "";
    await loadAgents();
    selectAgent(res.id);
  } else { toast(res.detail || t("toast.error"), "error"); }
}

/* ── Goal ─────────────────────────────────────────────────────────── */
let GOAL_AGENT = null;
function showGoalModal(agentId) { GOAL_AGENT = agentId; document.getElementById("goal-modal").classList.add("show"); }
function hideGoalModal() { document.getElementById("goal-modal").classList.remove("show"); }
async function setGoal() {
  const goal = document.getElementById("goal-text").value.trim();
  if (!goal || !GOAL_AGENT) { toast(t("toast.enter_goal"), "error"); return; }
  const res = await api("/api/v1/agents/" + GOAL_AGENT + "/goal", { method: "POST", body: { goal } });
  if (res.id) { hideGoalModal(); toast(t("toast.goal_set"), "success"); }
  else { toast(res.detail || t("toast.error"), "error"); }
}

/* ── Selected agent: status / pending / feed / audit ──────────────── */
async function selectAgent(agentId) {
  SELECTED = agentId;
  document.getElementById("chat-preview").replaceChildren();
  document.getElementById("chat-result").replaceChildren();
  document.getElementById("policy-preview").replaceChildren();
  renderAgents();
  renderStatusCard();
  await Promise.all([refreshFeed(), refreshPending(), refreshAudit(), refreshReport()]);
}

/* ── Chat-first intent (S4-03) ────────────────────────────────────── */
let CHAT_INTENT = null;

async function parseChat() {
  if (!SELECTED) { toast(t("toast.select_agent"), "error"); return; }
  const text = document.getElementById("chat-input").value.trim();
  if (!text) { toast("Введите задачу", "error"); return; }
  const preview = document.getElementById("chat-preview");
  preview.replaceChildren(el("div", "empty", t("chat.parsing")));
  const res = await api("/api/v1/agents/" + SELECTED + "/intent", { method: "POST", body: { text } });
  if (!res.ok) {
    preview.replaceChildren(el("div", "empty", res.detail || res.error || t("chat.parse_error")));
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
  head.appendChild(el("span", "time", intent.needs_clarification ? t("chat.clarify") : t("chat.ready")));
  card.appendChild(head);

  card.appendChild(el("div", "summary", intent.summary || "—"));
  card.appendChild(el("div", "params", JSON.stringify(intent.params || {}, null, 2)));

  const verdict = res.policy_verdict || {};
  const vline = el("div", "status-line");
  vline.appendChild(el("span", "muted", t("label.policy_prelim")));
  const decision = verdict.decision || "unknown";
  const vbadge = el("span", "badge " + (decision === "allow" ? "risk-low" : decision === "deny" ? "risk-high" : "risk-medium"), "policy: " + decision);
  vline.appendChild(vbadge);
  card.appendChild(vline);
  if (verdict.reasons && verdict.reasons.length) {
    card.appendChild(el("div", "warn-list", "• " + verdict.reasons.join("\n• ")));
  }

  if ((intent.assumptions || []).length) {
    card.appendChild(el("div", "muted", t("label.assumptions") + ": " + intent.assumptions.join("; ")));
  }
  if ((intent.questions || []).length) {
    card.appendChild(el("div", "warn-list", t("label.clarify") + ": " + intent.questions.join("; ")));
  }

  const actions = el("div", "intent-actions");
  if (!intent.needs_clarification) {
    const confirmBtn = el("button", "btn primary small", t("btn.confirm"));
    confirmBtn.onclick = () => confirmChat();
    actions.appendChild(confirmBtn);
  }
  const cancelBtn = el("button", "btn ghost small", t("btn.cancel"));
  cancelBtn.onclick = cancelChat;
  actions.appendChild(cancelBtn);
  card.appendChild(actions);
  preview.appendChild(card);
}

async function confirmChat() {
  if (!CHAT_INTENT || !SELECTED) return;
  const result = document.getElementById("chat-result");
  result.replaceChildren(el("div", "empty", t("chat.executing")));
  const res = await api("/api/v1/agents/" + SELECTED + "/intent/confirm",
                        { method: "POST", body: { action: CHAT_INTENT.action, params: CHAT_INTENT.params } });
  result.replaceChildren();
  if (res.detail && res.detail.errors === undefined && typeof res.detail === "string") {
    result.appendChild(el("div", "warn-list", res.detail));
    return;
  }
  const status = res.status || "unknown";
  const line = el("div", "status-line");
  line.appendChild(el("span", "action", t("label.result")));
  line.appendChild(el("span", "badge " + (status === "confirmed" ? "risk-low" : status === "pending" ? "risk-medium" : "risk-high"), status));
  result.appendChild(line);
  if (res.tx_hash) result.appendChild(el("div", "params", t("chat.tx") + ": " + res.tx_hash));
  if (res.error) result.appendChild(el("div", "warn-list", res.error));
  if (status === "pending") { refreshPending(); toast(t("toast.intent_pending"), "info"); }
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
  if (!agent) { card.replaceChildren(el("div", "empty", t("empty.select_agent"))); return; }
  card.replaceChildren();
  const line1 = el("div", "status-line");
  line1.appendChild(el("span", "muted", t("label.status")));
  line1.appendChild(statusBadge(agent.status));
  card.appendChild(line1);

  const line2 = el("div", "status-line");
  line2.appendChild(el("span", "muted", t("label.network")));
  line2.appendChild(el("span", "mono", "chain_id " + agent.chain_id));
  card.appendChild(line2);

  const line3 = el("div", "status-line");
  line3.appendChild(el("span", "muted", t("label.wallet")));
  line3.appendChild(el("span", "mono", agent.wallet_address || t("label.wallet_missing")));
  card.appendChild(line3);

  const hb = el("button", "btn small ghost", t("btn.heartbeat"));
  hb.onclick = async () => {
    const res = await api("/api/v1/agents/" + SELECTED + "/heartbeat", { method: "POST" });
    toast(res.status === "ok" ? t("toast.heartbeat_ok") : (res.detail || t("toast.heartbeat_fail")),
          res.status === "ok" ? "success" : "error");
  };
  card.appendChild(hb);
}

async function refreshFeed() {
  const feed = document.getElementById("decisions-feed");
  if (!SELECTED) { feed.replaceChildren(el("div", "empty", t("empty.select_agent"))); return; }
  const res = await api("/api/v1/agents/" + SELECTED + "/decisions?limit=30");
  const decisions = res.decisions || [];
  feed.replaceChildren();
  if (!decisions.length) { feed.appendChild(el("div", "empty", t("empty.no_decisions"))); return; }
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

  const why = el("button", "why-btn", t("btn.why"));
  const details = el("div", "why-details");
  details.style.display = "none";
  const lines = [];
  lines.push("confidence: " + (d.confidence !== null && d.confidence !== undefined ? d.confidence : "—"));
  lines.push("status: " + (d.status || "—"));
  if (d.requires_approval) lines.push("requires_approval: true");
  if (d.policy_verdict) lines.push("policy_verdict: " + JSON.stringify(d.policy_verdict, null, 2));
  details.textContent = lines.join("\n");
  why.onclick = () => { details.style.display = details.style.display === "none" ? "block" : "none"; };

  const replay = el("button", "why-btn", t("btn.replay"));
  replay.style.marginLeft = "10px";
  const replayBox = el("div", "why-details");
  replayBox.style.display = "none";
  replay.onclick = async () => {
    if (replayBox.style.display === "none") {
      const r = await api("/api/v1/decisions/" + d.id);
      if (r.detail) { replayBox.textContent = r.detail; }
      else {
        const thenVerdict = r.then ? r.then.decision : "—";
        const nowVerdict = r.now ? r.now.decision : "—";
        replayBox.textContent = [
          t("replay.then") + ": " + thenVerdict,
          t("replay.now") + ": " + nowVerdict,
          r.verdict_changed ? t("replay.changed") : t("replay.unchanged"),
          r.note || "",
        ].join("\n");
      }
      replayBox.style.display = "block";
    } else {
      replayBox.style.display = "none";
    }
  };

  card.append(why, replay, details, replayBox);
  return card;
}

async function refreshPending() {
  const list = document.getElementById("pending-list");
  const count = document.getElementById("pending-count");
  if (!SELECTED) { list.replaceChildren(el("div", "empty", t("empty.none"))); count.textContent = "0"; return; }
  const res = await api("/api/v1/agents/" + SELECTED + "/pending");
  if (res.detail) { list.replaceChildren(el("div", "empty", res.detail)); count.textContent = "0"; return; }
  const items = res.pending || [];
  count.textContent = String(res.total || 0);
  list.replaceChildren();
  if (!items.length) { list.appendChild(el("div", "empty", t("empty.no_pending"))); return; }
  items.forEach((item) => {
    const row = el("div", "pending-item");
    const info = el("div");
    info.appendChild(el("div", null, item.action + " · до " + fmtTime(item.execute_after)));
    info.appendChild(el("div", "muted mono", "id " + item.id));
    row.appendChild(info);
    const cancel = el("button", "btn small danger", t("btn.cancel_pending"));
    cancel.onclick = async () => {
      const res2 = await api("/api/v1/agents/" + SELECTED + "/pending/" + item.id + "/cancel", { method: "POST" });
      if (res2.status === "ok") { toast(t("toast.cancelled"), "success"); refreshPending(); }
      else { toast(res2.detail || "Ошибка", "error"); }
    };
    row.appendChild(cancel);
    list.appendChild(row);
  });
}

async function refreshAudit() {
  const list = document.getElementById("audit-list");
  const count = document.getElementById("audit-count");
  if (!SELECTED) { list.replaceChildren(el("div", "empty", t("empty.none"))); count.textContent = "0"; return; }
  const res = await api("/api/v1/agents/" + SELECTED + "/audit?limit=100");
  if (res.detail) { list.replaceChildren(el("div", "empty", res.detail)); count.textContent = "0"; return; }
  const events = res.events || [];
  count.textContent = String(res.total || 0);
  list.replaceChildren();
  if (!events.length) { list.appendChild(el("div", "empty", t("empty.no_events"))); return; }
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

/* ── Onboarding (S4-04) ───────────────────────────────────────────── */
const TIER_INFO = {
  0: { name: "Demo", per_tx: 0.1, daily: 0.5 },
  1: { name: "Simulated", per_tx: 0.5, daily: 2.0 },
};
let ONB = { tier: 0, template: null };

function startOnboarding() {
  ONB = { tier: 0, template: null };
  document.getElementById("onb-goal").value = "";
  onbPickTier(0);
  onbStep(1);
  document.getElementById("onboarding-modal").classList.add("show");
}

function closeOnboarding() {
  document.getElementById("onboarding-modal").classList.remove("show");
  sessionStorage.setItem("karta_onb_dismissed", "1");
}

function onbStep(n) {
  [1, 2, 3].forEach((i) => {
    document.getElementById("onb-step-" + i).style.display = i === n ? "block" : "none";
  });
  if (n === 3) renderOnbLimits();
}

function onbPickTier(tier) {
  ONB.tier = tier;
  document.querySelectorAll("#onb-step-1 .onb-card[data-tier]").forEach((card) => {
    card.classList.toggle("selected", Number(card.dataset.tier) === tier);
  });
}

function onbPickTemplate(kind) {
  ONB.template = kind;
  document.querySelectorAll("#onb-step-2 .onb-card[data-tpl]").forEach((card) => {
    card.classList.toggle("selected", card.dataset.tpl === kind);
  });
  const goal = document.getElementById("onb-goal");
  if (kind === "gas") goal.value = t("onb.gas_goal");
  else if (kind === "balance") goal.value = t("onb.balance_goal");
}

function renderOnbLimits() {
  const info = TIER_INFO[ONB.tier] || TIER_INFO[0];
  document.getElementById("onb-limits-body").textContent = JSON.stringify({
    tier: ONB.tier,
    name: info.name,
    per_tx_eth: info.per_tx,
    daily_eth: info.daily,
    execution: "simulation (Phase 5 — реальное исполнение за STOP-GATE)",
  }, null, 2);
}

async function onbFinish() {
  const goal = document.getElementById("onb-goal").value.trim() || t("onb.default_goal");
  const res = await api("/api/v1/agents", {
    method: "POST",
    body: {
      name: t("onb.agent_name", { mode: (TIER_INFO[ONB.tier] || TIER_INFO[0]).name }),
      description: t("onb.desc"),
      strategy: "monitoring",
      chain_id: 11155111,
      tier: ONB.tier,
    },
  });
  if (!res.id) { toast(res.detail || "Ошибка создания", "error"); return; }
  await api("/api/v1/agents/" + res.id + "/goal", { method: "POST", body: { goal } });
  closeOnboarding();
  toast(t("onb.created", { mode: (TIER_INFO[ONB.tier] || TIER_INFO[0]).name }), "success");
  await loadAgents();
  selectAgent(res.id);
}

/* ── Approvals inbox (S4-05): web-путь тот же, что у Telegram ─────── */
async function refreshApprovals() {
  const list = document.getElementById("approvals-list");
  const count = document.getElementById("approvals-count");
  if (!list) return;
  const res = await api("/api/v1/approvals");
  if (res.detail) { list.replaceChildren(el("div", "empty", res.detail)); count.textContent = "0"; return; }
  const items = res.approvals || [];
  count.textContent = String(res.total || 0);
  list.replaceChildren();
  if (!items.length) { list.appendChild(el("div", "empty", t("empty.no_approvals"))); return; }
  items.forEach((item) => list.appendChild(approvalCard(item)));
}

function approvalCard(item) {
  const card = el("div", "decision-card");
  const head = el("div", "head");
  head.appendChild(el("span", "action", (item.agent_name || "") + " · " + (item.action || "—")));
  head.appendChild(el("span", "time", fmtTime(item.created_at)));
  card.appendChild(head);
  card.appendChild(el("div", "params", JSON.stringify(item.params || {}, null, 2)));
  if (item.reasoning) card.appendChild(el("div", "reasoning", item.reasoning));

  const actions = el("div", "intent-actions");
  const approveBtn = el("button", "btn primary small", t("btn.approve"));
  approveBtn.onclick = async () => {
    const r = await api("/api/v1/approvals/" + item.id + "/approve", { method: "POST" });
    if (r.detail || r.error) { toast(r.detail || r.error || t("toast.error"), "error"); return; }
    toast(r.executed ? t("toast.approved_exec") : t("toast.approved_recorded"), "success");
    refreshApprovals();
  };
  const rejectBtn = el("button", "btn danger small", t("btn.reject"));
  rejectBtn.onclick = async () => {
    const r = await api("/api/v1/approvals/" + item.id + "/reject", { method: "POST" });
    if (r.detail || r.error) { toast(r.detail || r.error || t("toast.error"), "error"); return; }
    toast(t("toast.rejected"), "info");
    refreshApprovals();
  };
  actions.append(approveBtn, rejectBtn);
  card.appendChild(actions);
  return card;
}

/* ── Intent→Guarantee: правило словами → патч политики (S4-10) ────── */
let POLICY_PREVIEW = null;

async function parsePolicyRule() {
  if (!SELECTED) { toast(t("toast.select_agent"), "error"); return; }
  const text = document.getElementById("policy-input").value.trim();
  if (!text) { toast(t("toast.enter_task"), "error"); return; }
  const box = document.getElementById("policy-preview");
  box.replaceChildren(el("div", "empty", t("chat.parsing")));
  const res = await api("/api/v1/agents/" + SELECTED + "/policy/from-text",
                        { method: "POST", body: { text } });
  if (!res.ok) {
    box.replaceChildren(el("div", "empty", res.detail || res.error || t("chat.parse_error")));
    return;
  }
  POLICY_PREVIEW = res;
  renderPolicyPreview(res);
}

function renderPolicyPreview(res) {
  const box = document.getElementById("policy-preview");
  box.replaceChildren();
  const card = el("div", "intent-card");
  card.appendChild(el("div", "summary", res.summary || "—"));
  if (res.needs_clarification) {
    card.appendChild(el("div", "warn-list", t("label.clarify") + ": " + (res.questions || []).join("; ")));
    box.appendChild(card);
    return;
  }
  card.appendChild(el("div", "params", JSON.stringify(res.patch || {}, null, 2)));
  if (res.dsl_yaml) card.appendChild(el("div", "params", res.dsl_yaml));
  (res.warnings || []).forEach((w) => card.appendChild(el("div", "warn-list", w)));

  const impact = el("div", "warn-list");
  card.appendChild(impact);

  const actions = el("div", "intent-actions");
  const simBtn = el("button", "btn ghost small", t("policy.simulate"));
  simBtn.onclick = () => simulatePolicyRule(impact);
  const applyBtn = el("button", "btn primary small", t("policy.apply"));
  applyBtn.onclick = () => applyPolicyRule();
  const cancelBtn = el("button", "btn ghost small", t("btn.cancel"));
  cancelBtn.onclick = () => { POLICY_PREVIEW = null; box.replaceChildren(); };
  actions.append(simBtn, applyBtn, cancelBtn);
  card.appendChild(actions);
  box.appendChild(card);
}

async function simulatePolicyRule(impactBox) {
  if (!POLICY_PREVIEW || !POLICY_PREVIEW.dsl_yaml || !SELECTED) return;
  impactBox.textContent = t("chat.parsing");
  const res = await api("/api/v1/agents/" + SELECTED + "/policy/simulate",
                        { method: "POST", body: { dsl_yaml: POLICY_PREVIEW.dsl_yaml } });
  if (res.detail) { impactBox.textContent = res.detail; return; }
  const s = res.summary || {};
  const lines = [t("policy.impact", { tightened: s.tightened || 0, relaxed: s.relaxed || 0, unchanged: s.unchanged || 0 })];
  (res.changes || []).slice(0, 5).forEach((c) => {
    lines.push("• " + c.action + ": " + c.before + " → " + c.after);
  });
  lines.push(res.note || "");
  impactBox.textContent = lines.join("\n");
}

async function applyPolicyRule() {
  if (!POLICY_PREVIEW || !POLICY_PREVIEW.dsl_yaml || !SELECTED) return;
  const res = await api("/api/v1/agents/" + SELECTED + "/policy",
                        { method: "PUT", body: { dsl_yaml: POLICY_PREVIEW.dsl_yaml } });
  if (res.id || res.version) {
    toast(t("policy.applied") + " · v" + res.version, "success");
    POLICY_PREVIEW = null;
    document.getElementById("policy-preview").replaceChildren();
    document.getElementById("policy-input").value = "";
  } else {
    toast(res.detail || t("toast.error"), "error");
  }
}

/* ── Reports / CSV export (S4-07) ─────────────────────────────────── */
async function refreshReport() {
  const box = document.getElementById("report-summary");
  if (!SELECTED) { box.replaceChildren(el("div", "empty", t("empty.none"))); return; }
  const res = await api("/api/v1/agents/" + SELECTED + "/reports/summary");
  if (res.detail) { box.replaceChildren(el("div", "empty", res.detail)); return; }
  const drift = await api("/api/v1/agents/" + SELECTED + "/drift");
  if (!drift.detail) res.drift = drift;
  box.replaceChildren();
  const lines = [
    [t("report.decisions"), res.decisions_count],
    [t("report.transactions"), res.transactions_count + " (" + t("report.confirmed") + ": " + res.transactions_confirmed + ")"],
    [t("report.gas"), res.gas_spent_eth],
  ];
  lines.forEach(([label, value]) => {
    const row = el("div", "status-line");
    row.appendChild(el("span", "muted", label));
    row.appendChild(el("span", "mono", String(value)));
    box.appendChild(row);
  });
  if (res.drift) {
    const dr = el("div", "status-line");
    dr.appendChild(el("span", "muted", t("report.drift")));
    const driftClass = res.drift.level === "stable" ? "risk-low" : res.drift.level === "watch" ? "risk-medium" : "risk-high";
    dr.appendChild(el("span", "badge " + driftClass, t("drift." + res.drift.level) + " · " + res.drift.drift_score));
    box.appendChild(dr);
    (res.drift.signals || []).forEach((sig) => {
      box.appendChild(el("div", "warn-list", "• " + sig.type + ": " + sig.detail));
    });
  }
  if (res.trust) {
    const tr = el("div", "status-line");
    tr.appendChild(el("span", "muted", t("report.autonomy")));
    tr.appendChild(el("span", "mono", res.trust.rung + " (" + (res.trust.rung_index + 1) + "/" + res.trust.ladder.length + ")"));
    box.appendChild(tr);
  }
  if (res.health) {
    const h = el("div", "status-line");
    h.appendChild(el("span", "muted", t("report.health")));
    const bandClass = res.health.band === "healthy" ? "risk-low" : res.health.band === "degraded" ? "risk-medium" : "risk-high";
    const badge = el("span", "badge " + bandClass, res.health.score + " · " + t("band." + res.health.band));
    h.appendChild(badge);
    box.appendChild(h);
    if (res.health.recommendation) box.appendChild(el("div", "warn-list", res.health.recommendation));
  }
  const pnl = el("div", "warn-list", t("report.pnl") + ": " + (res.pnl_available ? res.realized_pnl : (res.pnl_reason || t("label.no_price_data"))));
  box.appendChild(pnl);
}

async function downloadCsv(dataset) {
  if (!SELECTED) { toast(t("toast.select_agent"), "error"); return; }
  const resp = await fetch("/api/v1/agents/" + SELECTED + "/export.csv?dataset=" + dataset,
                           { headers: { Authorization: "Bearer " + TOKEN } });
  if (!resp.ok) { toast(t("toast.export_error"), "error"); return; }
  const blob = await resp.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "karta_" + dataset + ".csv";
  link.click();
  URL.revokeObjectURL(link.href);
  toast(t("toast.csv_done", { dataset }), "success");
}

/* ── Transactions drawer ──────────────────────────────────────────── */
async function showTxPanel(agentId) {
  document.getElementById("tx-panel").classList.add("show");
  const list = document.getElementById("tx-list");
  list.replaceChildren(el("div", "empty", t("empty.loading")));
  const res = await api("/api/v1/agents/" + agentId + "/transactions");
  const txs = res.transactions || [];
  list.replaceChildren();
  if (!txs.length) { list.appendChild(el("div", "empty", t("empty.no_tx"))); return; }
  txs.forEach((tx) => {
    const item = el("div", "audit-row");
    item.appendChild(el("span", "etype", tx.status + " · " + (tx.tx_hash || "—").slice(0, 14)));
    item.appendChild(el("span", "hash", tx.timestamp ? String(tx.timestamp).slice(0, 19) : ""));
    list.appendChild(item);
  });
}
function hideTxPanel() { document.getElementById("tx-panel").classList.remove("show"); }


/* ── Ricardian 2-of-3 (S6-03) ─────────────────────────────────────── */
async function refreshRicardian() {
  const list = document.getElementById("ric-list");
  if (!list) return;
  const wallet = document.getElementById("ric-wallet");
  const info = await api("/api/v1/ricardian/wallet");
  if (wallet && info && !info.error) {
    wallet.textContent = t("ric.signer") + ": " + (info.signer || t("ric.no_signer"));
  }
  const data = await api("/api/v1/ricardian/agreements");
  list.innerHTML = "";
  if (!data || data.error || !data.agreements) {
    list.appendChild(el("div", "empty", (data && data.detail) || t("ric.error")));
    return;
  }
  if (!data.agreements.length) {
    list.appendChild(el("div", "empty", t("ric.empty")));
    return;
  }
  data.agreements.forEach((a) => list.appendChild(ricCard(a)));
}

function ricCard(a) {
  const card = el("div", "decision-card");
  const head = el("div", "decision-head");
  head.appendChild(el("span", "badge", "#" + a.id + " · " + a.status));
  head.appendChild(el("span", "muted", "✔ " + a.sign_count + "/2"));
  card.appendChild(head);
  const ms = el("div", "muted");
  ms.style.fontSize = ".74rem";
  ms.textContent = (a.milestones || [])
    .map((m) => m.index + ". " + m.description + " — " + m.amount_wei +
      (m.completed ? " ✔" : m.disputed ? " ⚠" : ""))
    .join(" · ");
  card.appendChild(ms);
  const actions = el("div", "intent-actions");
  const signBtn = el("button", "btn small ghost", t("ric.sign"));
  signBtn.onclick = () => ricAction(a.id, "sign");
  const execBtn = el("button", "btn small ghost", t("ric.execute"));
  execBtn.onclick = () => {
    const payee = prompt(t("ric.payee_prompt"), "");
    if (payee) ricAction(a.id, "execute", 0, payee);
  };
  const dispBtn = el("button", "btn small ghost", t("ric.dispute"));
  dispBtn.onclick = () => ricAction(a.id, "dispute", 0);
  actions.append(signBtn, execBtn, dispBtn);
  card.appendChild(actions);
  return card;
}

async function ricAction(id, action, index = 0, payee = "") {
  let url = "/api/v1/ricardian/agreements/" + id + "/" + action;
  let body;
  if (action === "execute") {
    url = "/api/v1/ricardian/agreements/" + id + "/milestones/" + index + "/execute";
    body = { payee: payee };
  }
  if (action === "dispute") {
    url = "/api/v1/ricardian/agreements/" + id + "/milestones/" + index + "/dispute";
  }
  const res = await api(url, { method: "POST", body: body });
  if (res && res.tx_hash) {
    toast(t("ric.tx_ok") + " " + res.tx_hash.slice(0, 12) + "…", "success");
    refreshRicardian();
  } else {
    toast((res && res.detail) || t("ric.error"), "error");
  }
}

async function createRicardian() {
  const parties = (document.getElementById("ric-parties").value || "")
    .split(",").map((v) => v.trim()).filter(Boolean);
  const token = (document.getElementById("ric-token").value || "").trim();
  const lines = (document.getElementById("ric-milestones").value || "")
    .split("\n").map((v) => v.trim()).filter(Boolean);
  const milestones = lines.map((line) => {
    const parts = line.split("|").map((v) => v.trim());
    return { description: parts[0], amount_wei: parts[1], deadline: parseInt(parts[2], 10) };
  });
  if (!token || !milestones.length) {
    toast(t("ric.fill"), "error");
    return;
  }
  const res = await api("/api/v1/ricardian/agreements", {
    method: "POST",
    body: { parties: parties, token: token, milestones: milestones },
  });
  if (res && res.tx_hash) {
    toast(t("ric.created") + " #" + res.agreement_id, "success");
    refreshRicardian();
  } else {
    toast((res && res.detail) || t("ric.error"), "error");
  }
}


/* ── Паспорт агента / ERC-8004 (S6-01) ────────────────────────────── */
async function openRegistry(agentId) {
  const panel = document.getElementById("registry-panel");
  const body = document.getElementById("registry-body");
  panel.style.display = "block";
  body.replaceChildren(el("div", "empty", "…"));
  const data = await api("/api/v1/agents/" + agentId + "/registry");
  body.replaceChildren();
  if (!data || data.error) {
    body.appendChild(el("div", "empty", (data && data.detail) || t("ric.error")));
    return;
  }
  const badges = el("div", "intent-actions");
  (data.badges || []).forEach((b) => {
    const chip = el("span", "badge", t("badge." + b.id) + (b.value !== null && b.value !== undefined ? " " + b.value : ""));
    chip.dataset.state = b.tone === "success" ? "live" : undefined;
    badges.appendChild(chip);
  });
  body.appendChild(badges);
  const info = el("div", "muted");
  info.style.fontSize = ".74rem";
  if (data.onchain) {
    info.textContent = "#" + data.onchain.agent_id + " · " + data.onchain.name +
      " · rep " + data.onchain.reputation + (data.onchain.verified ? " · verified" : "") +
      " · " + data.onchain.metadata_uri;
  } else {
    info.textContent = t("registry.none");
  }
  body.appendChild(info);
  const actions = el("div", "intent-actions");
  if (!data.onchain) {
    const reg = el("button", "btn primary small", t("registry.register"));
    reg.onclick = () => registryAction(agentId, "register", "POST");
    actions.appendChild(reg);
  } else {
    if (!data.onchain.verified) {
      const ver = el("button", "btn small ghost", t("registry.verify"));
      ver.onclick = () => registryAction(agentId, "verify", "POST");
      actions.appendChild(ver);
    }
    const sync = el("button", "btn small ghost", t("registry.sync_rep"));
    sync.onclick = () => registryAction(agentId, "sync-reputation", "POST");
    actions.appendChild(sync);
  }
  body.appendChild(actions);
}

function hideRegistry() {
  document.getElementById("registry-panel").style.display = "none";
}

async function registryAction(agentId, action, method) {
  const res = await api("/api/v1/agents/" + agentId + "/registry" + (action === "register" ? "" : "/" + action), { method: method });
  if (res && res.tx_hash) {
    toast(t("ric.tx_ok") + " " + res.tx_hash.slice(0, 12) + "…", "success");
    loadAgents();
    openRegistry(agentId);
  } else {
    toast((res && res.detail) || t("ric.error"), "error");
  }
}
