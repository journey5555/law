/* ── 유틸 ─────────────────────────────────────────────── */
const BASE = "/pharma";
const $ = id => document.getElementById(id);
let _toastTimer;
function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove("show"), 3000);
}
function fmtDate(s) {
  if (!s) return "-";
  const d = new Date(s.replace(" ", "T"));
  if (isNaN(d)) return s;
  return d.toLocaleDateString("ko-KR") + " " + d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}
async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(BASE + path, opts);
  if (r.status === 204) return null;
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

/* ── 탭 ───────────────────────────────────────────────── */
const PAGES = ["dashboard", "drugs", "results", "alerts"];
function switchTab(tab) {
  document.querySelectorAll(".nav-tab").forEach(el => el.classList.toggle("active", el.dataset.tab === tab));
  PAGES.forEach(p => $(`page-${p}`).classList.toggle("active", p === tab));
  if (tab === "dashboard") loadDashboard();
  if (tab === "drugs")     loadDrugs();
  if (tab === "results")   loadResults();
  if (tab === "alerts")    loadAlerts();
}
document.querySelectorAll(".nav-tab").forEach(el => {
  el.addEventListener("click", () => switchTab(el.dataset.tab));
});

/* ── Gmail 상태 ────────────────────────────────────────── */
let _isConnected = false;
async function refreshOAuthStatus() {
  const { connected } = await api("GET", "/api/oauth/status");
  _isConnected = connected;
  $("gmailDot").className = "gmail-dot" + (connected ? " connected" : "");
  $("gmailStatusText").textContent = connected ? "Gmail 연결됨" : "Gmail 미연결";
  $("gmailConnectBtn").style.display = connected ? "none" : "";
  $("syncBtn").style.display = connected ? "" : "none";
  $("dashboardConnectBanner").style.display = connected ? "none" : "";
}
$("gmailConnectBtn").addEventListener("click", () => { location.href = BASE + "/oauth/login"; });
$("syncBtn").addEventListener("click", async () => {
  $("syncBtn").disabled = true;
  $("syncBtn").textContent = "동기화 중…";
  try {
    const { synced } = await api("POST", "/api/sync");
    toast(`${synced}건 새 메일을 수집했습니다`);
    loadDashboard();
  } catch (e) {
    toast("동기화 실패: " + e.message);
  } finally {
    $("syncBtn").disabled = false;
    $("syncBtn").textContent = "동기화";
  }
});

/* ── 대시보드 ─────────────────────────────────────────── */
async function loadDashboard() {
  const data = await api("GET", "/api/stats");
  $("statTotal").textContent    = data.total_drugs;
  $("statReceived").textContent = data.received;
  $("statOverdue").textContent  = data.overdue;
  $("statPending").textContent  = data.pending;
  $("statResults").textContent  = data.total_results;
  $("statAlerts").textContent   = data.unread_alerts;

  const rr = $("recentResultsList");
  if (!data.recent_results.length) {
    rr.innerHTML = '<div class="empty-state"><p>수신 이력이 없습니다</p></div>';
  } else {
    rr.innerHTML = data.recent_results.map(r => `
      <div class="recent-item">
        <div><div class="recent-drug">${esc(r.drug_name||"")}</div><div class="recent-subject">${esc(r.subject||"")}</div></div>
        <div class="recent-date">${fmtDate(r.received_at)}</div>
      </div>`).join("");
  }

  const alerts = await api("GET", "/api/alerts");
  const unread = alerts.alerts.filter(a => !a.read).slice(0, 5);
  const al = $("dashAlertList");
  if (!unread.length) {
    al.innerHTML = '<div class="empty-state"><p>미확인 알림이 없습니다</p></div>';
  } else {
    al.innerHTML = unread.map(a => `
      <div class="alert-item ${a.alert_type === 'overdue' ? 'overdue' : 'unread'}">
        <div class="alert-icon">${a.alert_type === 'overdue' ? '⚠️' : '📧'}</div>
        <div class="alert-body"><div class="alert-msg">${esc(a.message)}</div><div class="alert-time">${fmtDate(a.created_at)}</div></div>
      </div>`).join("");
  }
  updateAlertBadge(data.unread_alerts);
}

function updateAlertBadge(n) {
  $("alertBadge").textContent = n;
  $("alertBadge").style.display = n > 0 ? "" : "none";
}

/* ── 약품 관리 ────────────────────────────────────────── */
let _drugs = [];
async function loadDrugs() {
  const data = await api("GET", "/api/drugs");
  _drugs = data.drugs;
  renderDrugs();
  populateDrugFilter();
}

function statusLabel(s) {
  if (s === "received") return '<span class="status-badge status-received">수신 완료</span>';
  if (s === "overdue")  return '<span class="status-badge status-overdue">미수신</span>';
  return '<span class="status-badge status-pending">대기 중</span>';
}

function renderDrugs() {
  const list = $("drugList");
  if (!_drugs.length) {
    list.innerHTML = '<div class="empty-state"><p>등록된 약품이 없습니다<br>+ 약품 추가 버튼으로 추가하세요</p></div>';
    return;
  }
  list.innerHTML = _drugs.map(d => `
    <div class="drug-card">
      <div class="drug-card-body">
        <div class="drug-name">${esc(d.name)} ${statusLabel(d.status)}</div>
        ${d.description ? `<div class="drug-desc">${esc(d.description)}</div>` : ""}
        <div class="drug-meta">
          <div class="drug-meta-item"><span class="drug-meta-label">예상일: </span><span class="drug-meta-value">${d.expected_date || "-"}</span></div>
          <div class="drug-meta-item"><span class="drug-meta-label">수신 메일: </span><span class="drug-meta-value">${d.result_count}건</span></div>
          ${d.sender_filter ? `<div class="drug-meta-item"><span class="drug-meta-label">발신자: </span><span class="drug-meta-value">${esc(d.sender_filter)}</span></div>` : ""}
          ${d.keyword_filter ? `<div class="drug-meta-item"><span class="drug-meta-label">키워드: </span><span class="drug-meta-value">${esc(d.keyword_filter)}</span></div>` : ""}
        </div>
      </div>
      <div class="drug-card-actions">
        <button class="btn btn-outline btn-sm" onclick="openEditDrug('${d.id}')">수정</button>
        <button class="btn btn-danger btn-sm" onclick="deleteDrug('${d.id}', '${esc(d.name)}')">삭제</button>
      </div>
    </div>`).join("");
}

$("addDrugBtn").addEventListener("click", () => openAddDrug());

function openAddDrug() {
  $("drugId").value = "";
  $("drugModalTitle").textContent = "약품 추가";
  ["drugName","drugDesc","drugExpected","drugSender","drugKeyword"].forEach(id => $( id).value = "");
  openModal("drugModal");
}

function openEditDrug(id) {
  const d = _drugs.find(x => x.id === id);
  if (!d) return;
  $("drugId").value      = id;
  $("drugModalTitle").textContent = "약품 수정";
  $("drugName").value    = d.name || "";
  $("drugDesc").value    = d.description || "";
  $("drugExpected").value = d.expected_date || "";
  $("drugSender").value  = d.sender_filter || "";
  $("drugKeyword").value = d.keyword_filter || "";
  openModal("drugModal");
}

$("saveDrugBtn").addEventListener("click", async () => {
  const id   = $("drugId").value;
  const name = $("drugName").value.trim();
  if (!name) { toast("약품명을 입력해 주세요"); return; }
  const body = {
    name,
    description:    $("drugDesc").value.trim() || null,
    expected_date:  $("drugExpected").value || null,
    sender_filter:  $("drugSender").value.trim() || null,
    keyword_filter: $("drugKeyword").value.trim() || null,
  };
  try {
    if (id) {
      await api("PUT", `/api/drugs/${id}`, body);
      toast("수정되었습니다");
    } else {
      await api("POST", "/api/drugs", body);
      toast("추가되었습니다");
    }
    closeDrugModal();
    loadDrugs();
  } catch (e) {
    toast("저장 실패: " + e.message);
  }
});

async function deleteDrug(id, name) {
  if (!confirm(`'${name}'을(를) 삭제하시겠습니까?\n관련 수신 이력과 알림도 함께 삭제됩니다.`)) return;
  try {
    await api("DELETE", `/api/drugs/${id}`);
    toast("삭제되었습니다");
    loadDrugs();
    loadDashboard();
  } catch (e) {
    toast("삭제 실패: " + e.message);
  }
}

function closeDrugModal() { closeModal("drugModal"); }

/* ── 수신 이력 ────────────────────────────────────────── */
let _results = [];
async function loadResults(drugId = "") {
  const url = drugId ? `/api/results?drug_id=${drugId}` : "/api/results";
  const data = await api("GET", url);
  _results = data.results;
  renderResults();
  $("resultCount").textContent = `총 ${_results.length}건`;
}

function renderResults() {
  const list = $("resultList");
  if (!_results.length) {
    list.innerHTML = '<div class="empty-state"><p>수신 이력이 없습니다</p></div>';
    return;
  }
  list.innerHTML = _results.map(r => `
    <div class="result-card" onclick="openEmailDetail('${r.id}')">
      <div class="result-header">
        <div class="result-subject">${esc(r.subject||"(제목 없음)")}</div>
        <div class="result-date">${fmtDate(r.received_at)}</div>
      </div>
      <div class="result-meta">
        <span class="result-drug">${esc(r.drug_name||"")}</span> · ${esc(r.sender||"")}
      </div>
    </div>`).join("");
}

$("resultDrugFilter").addEventListener("change", e => loadResults(e.target.value));

function populateDrugFilter() {
  const sel = $("resultDrugFilter");
  const cur = sel.value;
  sel.innerHTML = '<option value="">전체 약품</option>' +
    _drugs.map(d => `<option value="${d.id}" ${d.id === cur ? "selected" : ""}>${esc(d.name)}</option>`).join("");
}

async function openEmailDetail(id) {
  try {
    const r = await api("GET", `/api/results/${id}`);
    $("emailModalTitle").textContent = esc(r.subject || "(제목 없음)");
    $("emailDetailMeta").innerHTML = `
      <div class="detail-meta-row"><span>약품: </span>${esc(r.drug_name||"")}</div>
      <div class="detail-meta-row"><span>발신자: </span>${esc(r.sender||"")}</div>
      <div class="detail-meta-row"><span>수신일: </span>${fmtDate(r.received_at)}</div>`;
    $("emailDetailBody").textContent = r.raw_body || "(내용 없음)";
    openModal("emailModal");
  } catch (e) {
    toast("불러오기 실패: " + e.message);
  }
}
function closeEmailModal() { closeModal("emailModal"); }

/* ── 알림 ─────────────────────────────────────────────── */
async function loadAlerts() {
  const data = await api("GET", "/api/alerts");
  renderAlerts(data.alerts);
  updateAlertBadge(data.alerts.filter(a => !a.read).length);
}

function renderAlerts(alerts) {
  const list = $("alertList");
  if (!alerts.length) {
    list.innerHTML = '<div class="empty-state"><p>알림이 없습니다</p></div>';
    return;
  }
  list.innerHTML = alerts.map(a => `
    <div class="alert-item ${!a.read ? (a.alert_type === 'overdue' ? 'overdue' : 'unread') : ''}">
      <div class="alert-icon">${a.alert_type === 'overdue' ? '⚠️' : '📧'}</div>
      <div class="alert-body">
        <div class="alert-msg">${esc(a.message)}</div>
        <div class="alert-time">${fmtDate(a.created_at)}</div>
      </div>
      <div class="alert-actions">
        ${!a.read ? `<button class="btn btn-ghost btn-sm" onclick="markRead('${a.id}')">읽음</button>` : ""}
        <button class="btn btn-ghost btn-sm" onclick="deleteAlert('${a.id}')">삭제</button>
      </div>
    </div>`).join("");
}

async function markRead(id) {
  await api("POST", `/api/alerts/${id}/read`);
  loadAlerts();
}

$("readAllBtn").addEventListener("click", async () => {
  await api("POST", "/api/alerts/read-all");
  toast("전체 읽음 처리했습니다");
  loadAlerts();
});

async function deleteAlert(id) {
  await api("DELETE", `/api/alerts/${id}`);
  loadAlerts();
}

/* ── 모달 헬퍼 ────────────────────────────────────────── */
function openModal(id) {
  const sw = window.innerWidth - document.documentElement.clientWidth;
  document.body.style.overflow = "hidden";
  document.body.style.paddingRight = `${sw}px`;
  $(id).classList.add("open");
}
function closeModal(id) {
  $(id).classList.remove("open");
  document.body.style.overflow = "";
  document.body.style.paddingRight = "";
}
document.querySelectorAll(".modal-backdrop").forEach(el => {
  el.addEventListener("click", e => {
    if (e.target === el) {
      el.classList.remove("open");
      document.body.style.overflow = "";
      document.body.style.paddingRight = "";
    }
  });
});

/* ── XSS 방지 ─────────────────────────────────────────── */
function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

/* ── 초기화 ────────────────────────────────────────────── */
(async function init() {
  await refreshOAuthStatus();
  loadDashboard();
  const params = new URLSearchParams(location.search);
  if (params.get("connected") === "1") {
    toast("Gmail 계정이 연결되었습니다 ✓");
    history.replaceState({}, "", BASE);
  }
})();
