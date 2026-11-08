import { api, tokens, $, toast } from "./api.js";

async function enter() {
  const me = await api("/auth/me");
  location.href = me.role === "admin" ? "/panel" : "/dashboard";
}

if (tokens.get()) enter().catch(() => tokens.clear());

$("#loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.submitter;
  btn.disabled = true;
  try {
    const t = await api("/auth/login", {
      method: "POST",
      form: { username: $("#username").value, password: $("#password").value },
    });
    tokens.set(t);
    await enter();
  } catch (err) {
    toast(err.message, "danger");
  } finally {
    btn.disabled = false;
  }
});

$("#toggleForgot").addEventListener("click", () => $("#forgotBox").classList.toggle("d-none"));

$("#forgotForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const r = await api("/auth/forgot-password", { method: "POST", body: { email: $("#forgotEmail").value } });
    toast(r.message, "success");
  } catch (err) {
    toast(err.message, "danger");
  }
});
