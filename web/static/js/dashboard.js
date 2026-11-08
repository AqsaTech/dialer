import { api, tokens, refreshTokens, logout, goToLogin, $, el, toast } from "./api.js";

if (!tokens.get()) goToLogin();

const FINAL = new Set(["missed", "rejected", "ended", "failed", "delivered", "received"]);
const state = { numbers: [], logs: [], nextBefore: null, active: null, incoming: null };
const incomingModal = new bootstrap.Modal("#incomingModal");

// ---------- helpers
const display = $("#display");
const numberId = () => Number($("#numberSelect").value);
const fmtDuration = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
const numberLabel = (id) => {
  const n = state.numbers.find((x) => x.id === id);
  return n ? (n.label ? `${n.label} (${n.phone_number})` : n.phone_number) : "";
};

// ---------- numbers and keypad
function renderNumbers() {
  const sel = $("#numberSelect");
  sel.replaceChildren(...state.numbers.map((n) => {
    const o = el("option", "", n.label ? `${n.label}  ${n.phone_number}` : n.phone_number);
    o.value = n.id;
    return o;
  }));
  const none = state.numbers.length === 0;
  $("#dialBtn").disabled = none;
  $("#smsBtn").disabled = none;
  if (none) toast("No numbers are assigned to you yet. Ask your administrator.", "warning");
}

document.querySelectorAll(".key[data-digit]").forEach((k) =>
  k.addEventListener("click", () => {
    const d = k.dataset.digit;
    if (d === "+" && display.value.length > 0) return;
    display.value += d;
  }));
$("#backspace").addEventListener("click", () => { display.value = display.value.slice(0, -1); });
display.addEventListener("input", () => { display.value = display.value.replace(/[^\d+\s\-()]/g, ""); });

$("#dialBtn").addEventListener("click", async () => {
  const to = display.value.trim();
  if (!to) return;
  try {
    const r = await api("/calls/dial", { method: "POST", body: { number_id: numberId(), to } });
    setActive({ id: r.log_id, who: to, status: "queued" });
  } catch (err) { toast(err.message, "danger"); }
});

$("#smsBtn").addEventListener("click", async () => {
  const to = display.value.trim();
  const body = $("#smsBody").value.trim();
  if (!to || !body) { toast("Enter a number and a message first.", "warning"); return; }
  try {
    await api("/sms/send", { method: "POST", body: { number_id: numberId(), to, body } });
    $("#smsBody").value = "";
    toast("Text queued", "success");
  } catch (err) { toast(err.message, "danger"); }
});

// ---------- active call bar
function setActive(call) {
  state.active = call;
  const bar = $("#activeCall");
  bar.classList.toggle("d-none", !call);
  if (call) {
    $("#activeWho").textContent = call.who;
    $("#activeStatus").textContent = call.status;
  }
}
$("#hangupBtn").addEventListener("click", async () => {
  if (!state.active) return;
  try { await api(`/calls/${state.active.id}/hangup`, { method: "POST" }); }
  catch (err) { toast(err.message, "danger"); }
});

// ---------- incoming call popup
function showIncoming(log) {
  if (state.incoming) return;
  state.incoming = log;
  $("#callerNumber").textContent = log.remote_number;
  $("#callerLine").textContent = `to ${numberLabel(log.number_id)}`;
  incomingModal.show();
}
async function answerOrReject(action) {
  const log = state.incoming;
  if (!log) return;
  try {
    await api(`/calls/${log.id}/${action}`, { method: "POST" });
    if (action === "answer") setActive({ id: log.id, who: log.remote_number, status: "answering" });
  } catch (err) { toast(err.message, "danger"); }
  state.incoming = null;
  incomingModal.hide();
}
$("#answerBtn").addEventListener("click", () => answerOrReject("answer"));
$("#rejectBtn").addEventListener("click", () => answerOrReject("reject"));

// ---------- history
const matchesFilter = (l) =>
  (!$("#fType").value || l.type === $("#fType").value) &&
  (!$("#fDirection").value || l.direction === $("#fDirection").value);

function statusClass(s) {
  if (["answered", "sent", "delivered", "received", "ended"].includes(s)) return "text-bg-success";
  if (["missed", "failed", "rejected"].includes(s)) return "text-bg-danger";
  return "text-bg-secondary";
}

function renderLogs() {
  const rows = state.logs.map((l) => {
    const tr = el("tr");
    tr.append(el("td", "small text-nowrap", new Date(l.created_at).toLocaleString()));
    tr.append(el("td", "", `${l.direction === "inbound" ? "In" : "Out"} ${l.type === "call" ? "call" : "text"}`));
    const numTd = el("td");
    const pick = el("button", "btn btn-link p-0", l.remote_number);
    pick.addEventListener("click", () => { display.value = l.remote_number; });
    numTd.append(pick);
    tr.append(numTd);
    const st = el("td");
    st.append(el("span", `badge ${statusClass(l.status)}`, l.status));
    tr.append(st);
    const detail = l.type === "sms" ? l.body : (l.duration_seconds != null ? fmtDuration(l.duration_seconds) : "");
    tr.append(el("td", "log-body", detail));
    return tr;
  });
  $("#logRows").replaceChildren(...rows);
  $("#emptyLogs").classList.toggle("d-none", state.logs.length > 0);
  $("#moreBtn").classList.toggle("d-none", state.nextBefore === null);
}

async function loadLogs(reset) {
  const q = new URLSearchParams({ limit: "30" });
  if ($("#fType").value) q.set("type", $("#fType").value);
  if ($("#fDirection").value) q.set("direction", $("#fDirection").value);
  if (!reset && state.nextBefore) q.set("before_id", state.nextBefore);
  const page = await api(`/logs?${q}`);
  state.logs = reset ? page.items : state.logs.concat(page.items);
  state.nextBefore = page.next_before_id;
  renderLogs();
}
$("#fType").addEventListener("change", () => loadLogs(true));
$("#fDirection").addEventListener("change", () => loadLogs(true));
$("#moreBtn").addEventListener("click", () => loadLogs(false));

function upsertLog(log) {
  const i = state.logs.findIndex((l) => l.id === log.id);
  if (i >= 0) state.logs[i] = log;
  else if (matchesFilter(log)) state.logs.unshift(log);
  renderLogs();
}

// ---------- live events
function onEvent(msg) {
  const log = msg.log;
  switch (msg.event) {
    case "ready":
      setLive(true);
      break;
    case "incoming_call":
      upsertLog(log);
      showIncoming(log);
      break;
    case "call_status":
      upsertLog(log);
      if (state.incoming && state.incoming.id === log.id && log.status !== "ringing") {
        state.incoming = null;
        incomingModal.hide();
      }
      if (state.active && state.active.id === log.id) {
        if (FINAL.has(log.status)) setActive(null);
        else setActive({ ...state.active, status: log.status });
      } else if (log.direction === "inbound" && log.status === "answered") {
        setActive({ id: log.id, who: log.remote_number, status: "answered" });
      }
      if (log.status === "failed") toast("The call could not be placed.", "danger");
      break;
    case "incoming_sms":
      upsertLog(log);
      toast(`New text from ${log.remote_number}`, "info");
      break;
    case "sms_status":
      upsertLog(log);
      if (log.status === "failed") toast("A text could not be sent.", "danger");
      break;
  }
}

let ws = null;
let retry = 0;
let pingTimer = null;

function setLive(on) {
  $("#liveDot").className = `status-dot ${on ? "on" : "off"}`;
  $("#liveText").textContent = on ? "Live" : "Reconnecting";
  if (on) retry = 0;
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/events`);
  ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token: tokens.get().access_token }));
  ws.onmessage = (e) => { if (e.data !== "pong") onEvent(JSON.parse(e.data)); };
  ws.onclose = async (e) => {
    clearInterval(pingTimer);
    setLive(false);
    let delay = Math.min(1000 * 2 ** retry++, 15000);
    if (e.code === 4401) {
      // The access token expired or was revoked. Get a fresh one, or go back to sign in.
      try { await refreshTokens(); delay = 200; } catch { goToLogin(); return; }
    }
    setTimeout(connect, delay);
  };
  clearInterval(pingTimer);
  pingTimer = setInterval(() => { if (ws.readyState === WebSocket.OPEN) ws.send("ping"); }, 30000);
}

// ---------- start
$("#logoutBtn").addEventListener("click", logout);

(async function init() {
  try {
    const me = await api("/auth/me");
    $("#who").textContent = me.username;
    if (me.role === "admin") $("#adminLink").classList.remove("d-none");
    state.numbers = await api("/numbers");
    renderNumbers();
    await loadLogs(true);
    connect();
  } catch (err) {
    toast(err.message, "danger");
  }
})();
