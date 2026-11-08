import { api, $, toast } from "./api.js";

const token = new URLSearchParams(location.search).get("token");
if (!token) $("#resetForm").classList.add("d-none"), $("#noToken").classList.remove("d-none");

$("#resetForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/auth/reset-password", { method: "POST", body: { token, new_password: $("#newPassword").value } });
    $("#resetForm").classList.add("d-none");
    $("#done").classList.remove("d-none");
  } catch (err) {
    toast(err.message, "danger");
  }
});
