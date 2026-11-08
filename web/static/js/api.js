const KEY = "dialer.tokens";

export const tokens = {
  get() { try { return JSON.parse(localStorage.getItem(KEY)); } catch { return null; } },
  set(t) { localStorage.setItem(KEY, JSON.stringify(t)); },
  clear() { localStorage.removeItem(KEY); },
};

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

function errorText(data) {
  if (!data) return "Something went wrong";
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map((e) => e.msg.replace(/^Value error, /, "")).join(". ");
  return "Something went wrong";
}

let refreshing = null;
export function refreshTokens() {
  if (refreshing) return refreshing;
  const t = tokens.get();
  if (!t) return Promise.reject(new ApiError(401, "Not signed in"));
  refreshing = fetch("/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: t.refresh_token }),
  })
    .then(async (r) => {
      if (!r.ok) throw new ApiError(401, "Session expired");
      tokens.set(await r.json());
    })
    .finally(() => { refreshing = null; });
  return refreshing;
}

export function goToLogin() {
  tokens.clear();
  location.href = "/";
}

export async function api(path, { method = "GET", body, form, retry = true } = {}) {
  const t = tokens.get();
  const headers = {};
  if (t) headers.Authorization = `Bearer ${t.access_token}`;
  let payload;
  if (form) payload = new URLSearchParams(form);
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }

  const r = await fetch(path, { method, headers, body: payload });
  if (r.status === 401 && retry && t) {
    try { await refreshTokens(); } catch { goToLogin(); throw new ApiError(401, "Session expired"); }
    return api(path, { method, body, form, retry: false });
  }
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new ApiError(r.status, errorText(data));
  return data;
}

export async function logout() {
  const t = tokens.get();
  try { await api("/auth/logout", { method: "POST", body: { refresh_token: t?.refresh_token ?? null }, retry: false }); } catch { /* already invalid */ }
  goToLogin();
}

// ---- tiny DOM helpers. Everything from the server is untrusted, so we only ever use textContent.
export const $ = (sel, root = document) => root.querySelector(sel);
export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

export function toast(message, kind = "dark") {
  let area = $(".toast-area");
  if (!area) { area = el("div", "toast-area"); document.body.append(area); }
  const t = el("div", `alert alert-${kind} shadow-sm mb-0`, message);
  t.setAttribute("role", "status");
  area.append(t);
  setTimeout(() => t.remove(), 5000);
}
