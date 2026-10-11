/* ===== ตัวช่วยร่วมของทุกหน้า ===== */
const KEYS = ["ก", "ข", "ค", "ง", "จ"];

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {}, credentials: "same-origin" };
  if (opts.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  let res;
  try { res = await fetch(path, init); }
  catch (e) { throw new ApiError("เชื่อมต่อเซิร์ฟเวอร์ไม่ได้ กรุณาตรวจสอบอินเทอร์เน็ต", 0); }
  let data = null;
  try { data = await res.json(); } catch (_) { /* ไม่ใช่ JSON */ }
  if (!res.ok) {
    if (res.status === 401 && !opts.noRedirect) {
      location.href = "/login.html?expired=1";
      throw new ApiError("session หมดอายุ", 401);
    }
    throw new ApiError((data && data.error) || `เกิดข้อผิดพลาด (${res.status})`, res.status);
  }
  return data;
}
class ApiError extends Error { constructor(m, status) { super(m); this.status = status; } }

function toast(msg, type = "") {
  let box = document.getElementById("toasts");
  if (!box) { box = document.createElement("div"); box.id = "toasts"; document.body.appendChild(box); }
  const t = document.createElement("div");
  t.className = "toast " + type;
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

function fmtDate(ts) {
  if (!ts) return "-";
  return new Date(ts * 1000).toLocaleString("th-TH", { dateStyle: "medium", timeStyle: "short" });
}
function fmtPct(p) { return p == null ? "-" : Number(p).toFixed(1) + "%"; }

/* ---- ธีม ---- */
function applyTheme() {
  const t = localStorage.getItem("theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  document.documentElement.dataset.theme = t;
}
function toggleTheme() {
  const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem("theme", t);
  applyTheme();
}
applyTheme();

/* ---- Modal ---- */
function openModal(html, { dismissable = true } = {}) {
  const back = document.createElement("div");
  back.className = "modal-back";
  back.innerHTML = `<div class="modal" role="dialog" aria-modal="true">${html}</div>`;
  if (dismissable) back.addEventListener("click", e => { if (e.target === back) back.remove(); });
  document.body.appendChild(back);
  return back;
}
function confirmBox(title, message, okText = "ยืนยัน", danger = false) {
  return new Promise(resolve => {
    const m = openModal(`<h2>${esc(title)}</h2><div style="white-space:pre-line">${esc(message)}</div>
      <div class="modal-actions"><button class="btn ghost" id="c-no">ยกเลิก</button>
      <button class="btn ${danger ? "danger" : ""}" id="c-yes">${esc(okText)}</button></div>`);
    m.querySelector("#c-no").onclick = () => { m.remove(); resolve(false); };
    m.querySelector("#c-yes").onclick = () => { m.remove(); resolve(true); };
  });
}
function alertBox(title, message, okText = "ตกลง") {
  return new Promise(resolve => {
    const m = openModal(`<h2>${esc(title)}</h2><div style="white-space:pre-line;line-height:1.6">${esc(message)}</div>
      <div class="modal-actions"><button class="btn" id="a-ok" style="min-width:100px">${esc(okText)}</button></div>`);
    m.querySelector("#a-ok").onclick = () => { m.remove(); resolve(true); };
  });
}

/* ---- เปลี่ยนรหัสผ่าน ---- */
function changePasswordModal(forced = false) {
  const m = openModal(`<h2>${forced ? "กรุณาตั้งรหัสผ่านใหม่" : "เปลี่ยนรหัสผ่าน"}</h2>
    ${forced ? '<div class="alert info">บัญชีนี้ใช้รหัสผ่านเริ่มต้น กรุณาเปลี่ยนก่อนใช้งาน</div>' : ""}
    <div id="pw-err"></div>
    <div class="field"><label>รหัสผ่านเดิม</label><input type="password" id="pw-old" autocomplete="current-password"></div>
    <div class="field"><label>รหัสผ่านใหม่ (อย่างน้อย 6 ตัวอักษร)</label><input type="password" id="pw-new" autocomplete="new-password"></div>
    <div class="field"><label>ยืนยันรหัสผ่านใหม่</label><input type="password" id="pw-new2" autocomplete="new-password"></div>
    <div class="modal-actions">${forced ? "" : '<button class="btn ghost" id="pw-cancel">ยกเลิก</button>'}
    <button class="btn" id="pw-ok">บันทึก</button></div>`, { dismissable: !forced });
  const cancel = m.querySelector("#pw-cancel");
  if (cancel) cancel.onclick = () => m.remove();
  m.querySelector("#pw-ok").onclick = async () => {
    const box = m.querySelector("#pw-err");
    const n1 = m.querySelector("#pw-new").value, n2 = m.querySelector("#pw-new2").value;
    if (n1 !== n2) { box.innerHTML = '<div class="alert error">รหัสผ่านใหม่ทั้งสองช่องไม่ตรงกัน</div>'; return; }
    try {
      await api("/api/change-password", { method: "POST", body: { old_password: m.querySelector("#pw-old").value, new_password: n1 } });
      m.remove();
      toast("เปลี่ยนรหัสผ่านเรียบร้อย", "success");
    } catch (e) { box.innerHTML = `<div class="alert error">${esc(e.message)}</div>`; }
  };
}

/* ---- เริ่มหน้าที่ต้องล็อกอิน ---- */
let HEARTBEAT = null;
async function initPage(active, { adminOnly = false } = {}) {
  const me = await api("/api/me");
  if (adminOnly && me.user.role !== "admin") { location.href = "/home.html"; throw new Error("forbidden"); }
  renderTopbar(me.user, active);
  // heartbeat เพื่อบอกเซิร์ฟเวอร์ว่ายังใช้งานอยู่ (ใช้ตรวจการล็อกอินซ้อน)
  clearInterval(HEARTBEAT);
  HEARTBEAT = setInterval(() => api("/api/heartbeat", { method: "POST" }).catch(() => {}), 30000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) api("/api/heartbeat", { method: "POST" }).catch(() => {});
  });
  if (me.user.must_change_password) changePasswordModal(true);
  return me;
}

function renderTopbar(user, active) {
  const links = [["home", "/home.html", "หน้าหลัก"]];
  if (user.role === "admin") links.push(["admin", "/admin.html", "ผู้ดูแลระบบ"]);
  const bar = document.createElement("header");
  bar.className = "topbar";
  bar.innerHTML = `<div class="topbar-inner">
    <a class="brand" href="/home.html"><span class="brand-logo">✚</span><span>ฝึกสอบพยาบาล</span></a>
    <nav class="nav" aria-label="เมนูหลัก">${links.map(l => `<a href="${l[1]}" class="${l[0] === active ? "active" : ""}">${l[2]}</a>`).join("")}</nav>
    <span class="spacer"></span>
    <div class="userchip"><span class="avatar">${esc((user.display_name || "?").charAt(0).toUpperCase())}</span>
      <span class="hide-sm">${esc(user.display_name)}</span></div>
    <button class="btn ghost sm" id="btn-theme" title="สลับโหมดมืด/สว่าง" aria-label="สลับธีม">🌓</button>
    <button class="btn ghost sm" id="btn-pw">รหัสผ่าน</button>
    <button class="btn secondary sm" id="btn-logout">ออกจากระบบ</button></div>`;
  document.body.prepend(bar);
  bar.querySelector("#btn-theme").onclick = toggleTheme;
  bar.querySelector("#btn-pw").onclick = () => changePasswordModal(false);
  bar.querySelector("#btn-logout").onclick = logout;
}

async function logout() {
  try { await api("/api/logout", { method: "POST", noRedirect: true }); } catch (_) { /* ignore */ }
  location.href = "/login.html";
}
