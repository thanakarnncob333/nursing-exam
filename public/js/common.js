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
  const btn = document.getElementById("btn-theme");
  if (btn) {
    btn.innerHTML = t === "dark" ? "☀️ <span class=\"hide-sm\">สว่าง</span>" : "🌙 <span class=\"hide-sm\">มืด</span>";
    btn.title = t === "dark" ? "เปลี่ยนเป็นโหมดสว่าง" : "เปลี่ยนเป็นโหมดมืด";
  }
}
function toggleTheme() {
  const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem("theme", t);
  applyTheme();
}
applyTheme();

/* ---- ตัวควบคุมขนาดฟอนต์ (Font Scale) ---- */
function initFontScale() {
  const saved = localStorage.getItem("exam_font_size") || "md";
  setFontScale(saved);
}
function setFontScale(size) {
  document.body.dataset.fontSize = size;
  localStorage.setItem("exam_font_size", size);
  document.querySelectorAll(".btn-font").forEach(b => {
    b.classList.toggle("active", b.dataset.size === size);
  });
}

/* ---- สมุดพกตารางค่าแล็บปกติฉุกเฉิน (Clinical Normal Labs Drawer) ---- */
const CLINICAL_LABS = [
  {
    category: "ก๊าซในเลือดแดง (ABG)",
    icon: "🫁",
    items: [
      { name: "pH", val: "7.35 – 7.45", note: "<7.35 กรด (Acidemia) / >7.45 ด่าง (Alkalemia)" },
      { name: "PaCO2", val: "35 – 45 mmHg", note: "ระบบหายใจ (Respiratory) : >45 เป็นกรด" },
      { name: "HCO3- (Bicarbonate)", val: "22 – 26 mEq/L", note: "ระบบเมแทบอลิซึม : <22 เป็นกรด" },
      { name: "PaO2", val: "80 – 100 mmHg", note: "ภาวะขาดออกซิเจนเมื่อ <80 mmHg" },
      { name: "SaO2", val: "≥ 95%", note: "SpO2 เป้าหมายผู้ป่วยทั่วไป" }
    ]
  },
  {
    category: "เกลือแร่ในเลือด (Serum Electrolytes)",
    icon: "⚡",
    items: [
      { name: "Potassium (K+)", val: "3.5 – 5.0 mEq/L", note: "สำคัญมาก! <3.0 หรือ >6.0 เสี่ยงหัวใจหยุดเต้น (Tall T / U wave)" },
      { name: "Sodium (Na+)", val: "135 – 145 mEq/L", note: "<135 เสี่ยงชักสมองบวม / >145 เสี่ยงขาดน้ำรุนแรง" },
      { name: "Chloride (Cl-)", val: "96 – 106 mEq/L", note: "รักษาสมดุลกรด-ด่างและน้ำ" },
      { name: "Total Calcium (Ca)", val: "8.5 – 10.5 mg/dL", note: "ต่ำทำให้เกิด Chvostek's & Trousseau's sign (มือเกร็งจีบ)" },
      { name: "Magnesium (Mg2+)", val: "1.5 – 2.5 mg/dL", note: "ระดับในการรักษา Pre-eclampsia: 4 – 7 mEq/L" },
      { name: "Phosphate (PO4)", val: "2.5 – 4.5 mg/dL", note: "แปรผกผันกับ Calcium" }
    ]
  },
  {
    category: "การทำงานของไตและน้ำตาล (Renal & Glycemic)",
    icon: "💧",
    items: [
      { name: "BUN", val: "10 – 20 mg/dL", note: "สูงบ่งชี้ภาวะขาดน้ำ (Dehydration) หรือไตวาย" },
      { name: "Serum Creatinine", val: "0.6 – 1.2 mg/dL", note: "ตัวบ่งชี้การทำงานของไตที่แม่นยำที่สุด" },
      { name: "eGFR", val: "> 90 mL/min/1.73m²", note: "<15 คือไตวายเรื้อรังระยะสุดท้าย (Stage 5)" },
      { name: "Fasting Blood Sugar (FBS)", val: "70 – 99 mg/dL", note: "≥ 126 mg/dL บ่งชี้โรคเบาหวาน" },
      { name: "HbA1c", val: "< 5.7%", note: "เป้าหมายผู้ป่วยเบาหวาน < 7.0%" }
    ]
  },
  {
    category: "โลหิตวิทยาและการแข็งตัวของเลือด (CBC & Coagulation)",
    icon: "🩸",
    items: [
      { name: "WBC", val: "5,000 – 10,000 /uL", note: ">10,000 ติดเชื้อแบคทีเรีย / <4,000 เสี่ยงติดเชื้อรุนแรง" },
      { name: "Platelets", val: "150,000 – 450,000 /uL", note: "<50,000 ระวังเลือดออก / <20,000 เสี่ยงเลือดออกในสมอง" },
      { name: "Hemoglobin (Hb)", val: "ชาย 14-18 / หญิง 12-16 g/dL", note: "<7.0 พิจารณาให้ PRC" },
      { name: "Hematocrit (Hct)", val: "ชาย 42-52% / หญิง 37-47%", note: "ประมาณ 3 เท่าของ Hb" },
      { name: "PT / INR", val: "INR 0.8 – 1.1", note: "เป้าหมายเมื่อได้ Warfarin คือ 2.0 – 3.0" },
      { name: "aPTT", val: "25 – 35 วินาที", note: "เป้าหมายเมื่อได้ Heparin คือ 1.5 – 2.5 เท่า (~50-70s)" }
    ]
  },
  {
    category: "สัญญาณชีพและดัชนีวิกฤต (Vital Signs & Critical Indices)",
    icon: "🩺",
    items: [
      { name: "ความดันโลหิต (BP)", val: "120/80 mmHg", note: "Mean Arterial Pressure (MAP) ควร ≥ 65 mmHg" },
      { name: "ชีพจร (HR)", val: "60 – 100 bpm", note: "<60 Bradycardia / >100 Tachycardia" },
      { name: "อัตราการหายใจ (RR)", val: "12 – 20 /min", note: ">24 หายใจเร็ว (Tachypnea)" },
      { name: "Urine Output ปกติ", val: "≥ 0.5 mL/kg/hr", note: "ผู้ใหญ่ทั่วไปอย่างน้อย ≥ 30 mL/hr" },
      { name: "Central Venous Pressure (CVP)", val: "2 – 8 mmHg (5-12 cmH2O)", note: "ประเมินปริมาณสารน้ำในหลอดเลือดดำใหญ่" },
      { name: "Glasgow Coma Scale (GCS)", val: "15 คะแนน (E4 V5 M6)", note: "≤ 8 คะแนนถือว่าโคม่าและเสี่ยงทางเดินหายใจอุดกั้น" }
    ]
  }
];

function openLabDrawer() {
  const existing = document.getElementById("clinical-lab-drawer");
  if (existing) { existing.classList.add("open"); return; }

  const drawer = document.createElement("div");
  drawer.id = "clinical-lab-drawer";
  drawer.className = "drawer-backdrop open";
  drawer.innerHTML = `
    <div class="drawer-panel">
      <div class="drawer-header">
        <div>
          <h3 style="margin:0;font-size:1.1rem;display:flex;align-items:center;gap:8px">
            <span>📋</span> ตารางค่าแล็บ & ดัชนีปกติทางคลินิก
          </h3>
          <div class="muted" style="font-size:.8rem;margin-top:2px">คู่มือค่าอ้างอิงสำหรับการสอบวิชาชีพการพยาบาล</div>
        </div>
        <button class="btn ghost sm" id="drawer-close" style="font-size:1.2rem;padding:4px 10px;line-height:1">✕</button>
      </div>
      <div style="padding:12px 20px 0 20px">
        <input type="text" id="lab-search" class="lab-search" placeholder="🔍 ค้นหาค่าแล็บ เช่น K+, ABG, INR, BUN, Urine..." autocomplete="off">
      </div>
      <div class="drawer-body" id="lab-body">
        ${renderLabCards("")}
      </div>
    </div>`;

  document.body.appendChild(drawer);

  function renderLabCards(query) {
    const q = query.trim().toLowerCase();
    let html = "";
    CLINICAL_LABS.forEach(cat => {
      const filtered = cat.items.filter(it => !q || it.name.toLowerCase().includes(q) || it.val.toLowerCase().includes(q) || it.note.toLowerCase().includes(q) || cat.category.toLowerCase().includes(q));
      if (!filtered.length) return;
      html += `
        <div class="lab-cat-card">
          <div class="lab-cat-title"><span>${cat.icon}</span> ${esc(cat.category)}</div>
          <table class="lab-table">
            ${filtered.map(it => `
              <tr>
                <td style="font-weight:600;width:38%">${esc(it.name)}</td>
                <td class="lab-val">${esc(it.val)}</td>
              </tr>
              <tr>
                <td colspan="2" style="font-size:.8rem;color:var(--muted);padding-top:0;padding-bottom:8px">
                  💡 ${esc(it.note)}
                </td>
              </tr>`).join("")}
          </table>
        </div>`;
    });
    return html || '<div class="empty">ไม่พบค่าแล็บที่ค้นหา</div>';
  }

  const searchInput = drawer.querySelector("#lab-search");
  const labBody = drawer.querySelector("#lab-body");
  searchInput.addEventListener("input", e => {
    labBody.innerHTML = renderLabCards(e.target.value);
  });

  const closeBtn = drawer.querySelector("#drawer-close");
  const closeDrawer = () => drawer.classList.remove("open");
  closeBtn.onclick = closeDrawer;
  drawer.onclick = e => { if (e.target === drawer) closeDrawer(); };
  document.addEventListener("keydown", e => { if (e.key === "Escape" && drawer.classList.contains("open")) closeDrawer(); }, { once: true });
}

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
  initFontScale();
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
    <button class="btn ghost sm" id="btn-top-labs" title="ดูตารางค่าแล็บปกติ" style="gap:4px">
      <span>📋</span> <span class="hide-sm">ค่าแล็บปกติ</span>
    </button>
    <div class="userchip"><span class="avatar">${esc((user.display_name || "?").charAt(0).toUpperCase())}</span>
      <span class="hide-sm">${esc(user.display_name)}</span></div>
    <button class="btn ghost sm" id="btn-theme" title="สลับโหมดมืด/สว่าง" aria-label="สลับธีม">🌓</button>
    <button class="btn ghost sm" id="btn-pw">รหัสผ่าน</button>
    <button class="btn secondary sm" id="btn-logout">ออกจากระบบ</button></div>`;
  document.body.prepend(bar);
  bar.querySelector("#btn-top-labs").onclick = openLabDrawer;
  bar.querySelector("#btn-theme").onclick = toggleTheme;
  bar.querySelector("#btn-pw").onclick = () => changePasswordModal(false);
  bar.querySelector("#btn-logout").onclick = logout;
  applyTheme();
}

async function logout() {
  try { await api("/api/logout", { method: "POST", noRedirect: true }); } catch (_) { /* ignore */ }
  location.href = "/login.html";
}

/* ---- ลงทะเบียน Service Worker สำหรับ PWA ---- */
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

