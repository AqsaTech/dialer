import { api, tokens, logout, goToLogin, $, el, toast } from "./api.js";

if (!tokens.get()) goToLogin();

const state = { users: [], gateways: [], numbers: [] };

function actionBtn(text, cls, onClick) {
  const b = el("button", `btn btn-sm ${cls}`, text);
  b.addEventListener("click", async () => {
    b.disabled = true;
    try { await onClick(); } catch (err) { toast(err.message, "danger"); }
    b.disabled = false;
  });
  return b;
}
function fillSelect(select, pairs) {
  const keep = select.value; // the page refreshes itself, so keep what the admin picked
  select.replaceChildren(...pairs.map(([value, text]) => { const o = el("option", "", text); o.value = value; return o; }));
  if (pairs.some(([v]) => String(v) === keep)) select.value = keep;
}
const cell = (child) => { const td = el("td"); td.append(child); return td; };
const when = (iso) => (iso ? new Date(iso).toLocaleString() : "Never");
const badge = (on) => el("span", `badge ${on ? "text-bg-success" : "text-bg-secondary"}`, on ? "Active" : "Disabled");

// ---------- users
function renderUsers() {
  $("#userRows").replaceChildren(...state.users.map((u) => {
    const tr = el("tr");
    tr.append(el("td", "", u.username), el("td", "", u.email), el("td", "", u.role), cell(badge(u.is_active)));
    const actions = el("td", "d-flex gap-2");
    actions.append(
      actionBtn(u.is_active ? "Disable" : "Enable", "btn-outline-secondary", async () => {
        await api(`/admin/users/${u.id}/active`, { method: "PATCH", body: { is_active: !u.is_active } });
        await loadAll();
      }),
      actionBtn("Set password", "btn-outline-warning", async () => {
        const pw = prompt(`New password for ${u.username} (10+ characters, letters and digits):`);
        if (!pw) return;
        await api(`/admin/users/${u.id}/password`, { method: "POST", body: { new_password: pw } });
        toast("Password updated. The user was signed out.", "success");
      }),
    );
    tr.append(actions);
    return tr;
  }));
  const active = state.users.filter((u) => u.is_active);
  fillSelect($("#nUser"), active.map((u) => [u.id, u.username]));
}

$("#userForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/admin/users", { method: "POST", body: {
      username: $("#uName").value, email: $("#uEmail").value, password: $("#uPass").value, role: $("#uRole").value,
    } });
    e.target.reset();
    toast("User created", "success");
    await loadAll();
  } catch (err) { toast(err.message, "danger"); }
});

// ---------- gateways
function renderGateways() {
  $("#gwRows").replaceChildren(...state.gateways.map((g) => {
    const tr = el("tr");
    tr.append(el("td", "", g.name));
    const conn = el("td");
    conn.append(el("span", `status-dot ${g.online ? "on" : "off"}`), document.createTextNode(g.online ? "Online" : "Offline"));
    tr.append(conn, el("td", "small", when(g.last_seen_at)), cell(badge(g.is_active)));
    const actions = el("td", "d-flex gap-2");
    actions.append(
      actionBtn("New key", "btn-outline-warning", async () => {
        if (!confirm(`Create a new key for ${g.name}? The old key stops working immediately.`)) return;
        showKey(await api(`/admin/gateways/${g.id}/rotate-key`, { method: "POST" }));
      }),
      actionBtn(g.is_active ? "Disable" : "Enable", "btn-outline-secondary", async () => {
        await api(`/admin/gateways/${g.id}/active`, { method: "PATCH", body: { is_active: !g.is_active } });
        await loadAll();
      }),
    );
    tr.append(actions);
    return tr;
  }));
  fillSelect($("#nGw"), state.gateways.map((g) => [g.id, g.name]));
}

function showKey(gw) {
  $("#keyValue").textContent = gw.api_key;
  $("#keyBox").classList.remove("d-none");
}

$("#gwForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    showKey(await api("/admin/gateways", { method: "POST", body: { name: $("#gName").value } }));
    e.target.reset();
    await loadAll();
  } catch (err) { toast(err.message, "danger"); }
});

// ---------- numbers
function renderNumbers() {
  const userName = (id) => state.users.find((u) => u.id === id)?.username ?? `#${id}`;
  const gwName = (id) => state.gateways.find((g) => g.id === id)?.name ?? `#${id}`;
  $("#numRows").replaceChildren(...state.numbers.map((n) => {
    const tr = el("tr");
    tr.append(el("td", "", n.phone_number), el("td", "", userName(n.user_id)), el("td", "", gwName(n.gateway_id)),
      el("td", "", `SIM ${n.sim_slot + 1}`), el("td", "", n.label ?? ""), cell(badge(n.is_active)));
    tr.append(cell(actionBtn(n.is_active ? "Disable" : "Enable", "btn-outline-secondary", async () => {
      await api(`/admin/numbers/${n.id}`, { method: "PATCH", body: { is_active: !n.is_active } });
      await loadAll();
    })));
    return tr;
  }));
}

$("#numForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/admin/numbers", { method: "POST", body: {
      user_id: Number($("#nUser").value), gateway_id: Number($("#nGw").value),
      phone_number: $("#nPhone").value, sim_slot: Number($("#nSlot").value),
      label: $("#nLabel").value.trim() || null,
    } });
    $("#nPhone").value = ""; $("#nLabel").value = "";
    toast("Number assigned", "success");
    await loadAll();
  } catch (err) { toast(err.message, "danger"); }
});

// ---------- start
async function loadAll() {
  [state.users, state.gateways, state.numbers] = await Promise.all([
    api("/admin/users"), api("/admin/gateways"), api("/admin/numbers"),
  ]);
  renderUsers(); renderGateways(); renderNumbers();
}

$("#logoutBtn").addEventListener("click", logout);

(async function init() {
  try {
    const me = await api("/auth/me");
    if (me.role !== "admin") { location.href = "/dashboard"; return; }
    await loadAll();
    setInterval(() => loadAll().catch(() => {}), 15000); // keeps the online/offline dots fresh
  } catch (err) { toast(err.message, "danger"); }
})();
