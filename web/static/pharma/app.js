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
function showLoading(msg = "처리 중...") {
  $("loadingMsg").textContent = msg;
  $("loadingOverlay").style.display = "flex";
}
function hideLoading() { $("loadingOverlay").style.display = "none"; }

let _successTimer;
function showSuccess(msg) {
  $("successMsg").textContent = msg;
  $("successOverlay").style.display = "flex";
  clearTimeout(_successTimer);
  _successTimer = setTimeout(() => { $("successOverlay").style.display = "none"; }, 2000);
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
const PAGES = ["dashboard", "drugs", "results", "alerts", "gmailtest", "upload"];
function switchTab(tab) {
  document.querySelectorAll(".nav-tab").forEach(el => el.classList.toggle("active", el.dataset.tab === tab));
  PAGES.forEach(p => $(`page-${p}`).classList.toggle("active", p === tab));
  if (tab === "dashboard") loadDashboard();
  if (tab === "drugs")     loadDrugs();
  if (tab === "results")   loadResults();
  if (tab === "alerts")    loadAlerts();
  if (tab === "gmailtest") refreshWatchStatus();
  if (tab === "upload")    { loadAttachments(); loadHistory(); }
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
  $("notifBtn").style.display = connected && ("Notification" in window) ? "" : "none";
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

/* ── Gmail API 테스트 ─────────────────────────────────── */
function setGmailQuery(q) {
  $("gmailTestQuery").value = q;
}

async function runGmailTest() {
  const q = $("gmailTestQuery").value.trim();
  const max = parseInt($("gmailTestMax").value) || 10;
  if (!q) { toast("검색어를 입력하세요"); return; }

  const btn = $("gmailTestBtn");
  btn.disabled = true;
  btn.textContent = "검색 중...";
  $("gmailTestStatus").textContent = "";
  $("gmailTestResults").innerHTML = "";

  try {
    const data = await api("GET", `/api/test/search?q=${encodeURIComponent(q)}&max_results=${max}`);
    $("gmailTestStatus").textContent = `${data.count}건 조회됨`;
    if (!data.emails.length) {
      $("gmailTestResults").innerHTML = `<div class="empty-state"><p>결과 없음</p></div>`;
      return;
    }
    $("gmailTestResults").innerHTML = data.emails.map(m => `
      <div class="card" style="margin-bottom:10px;padding:14px">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
          <div style="font-weight:600;font-size:14px">${esc(m.subject || "(제목 없음)")}</div>
          <div style="font-size:12px;color:var(--text-muted);white-space:nowrap">${esc(m.date)}</div>
        </div>
        <div style="font-size:12px;color:var(--text-muted);margin:4px 0">${esc(m.sender)}</div>
        ${m.attachments && m.attachments.length ? `<div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap">${m.attachments.map(a => `<span onclick="previewAttachment('${esc(m.id)}','${esc(a.attachment_id)}','${esc(a.mime_type)}','${esc(a.filename)}')" style="font-size:11px;background:#e8f0fe;color:#1a73e8;padding:2px 8px;border-radius:10px;cursor:pointer">📎 ${esc(a.filename)} (${a.size ? Math.round(a.size/1024)+'KB' : '-'})</span>`).join("")}</div>` : ""}
        ${m.body ? `<div style="font-size:13px;color:var(--text-body);margin-top:8px;white-space:pre-wrap;max-height:120px;overflow:auto;background:var(--bg-muted,#f5f5f5);padding:8px;border-radius:4px">${esc(m.body.slice(0, 500))}${m.body.length > 500 ? "…" : ""}</div>` : ""}
      </div>`).join("");
  } catch (e) {
    $("gmailTestStatus").textContent = `오류: ${e.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "검색";
  }
}

$("gmailTestQuery").addEventListener("keydown", e => { if (e.key === "Enter") runGmailTest(); });

/* ── Excel 생성 ───────────────────────────────────────── */
async function generateExcel() {
  const raw = $("excelJson").value.trim();
  const status = $("excelStatus");
  if (!raw) { toast("JSON을 입력하세요"); return; }
  let body;
  try { body = JSON.parse(raw); }
  catch { status.textContent = "JSON 파싱 오류"; status.style.color = "red"; return; }

  status.textContent = "생성 중...";
  status.style.color = "var(--text-muted)";
  try {
    const r = await fetch(`${BASE}/api/excel/generate`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    if (!r.ok) { const e = await r.json(); throw new Error(e.detail || `HTTP ${r.status}`); }
    const blob = await r.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = `${body.document_id || "지출결의서"}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
    status.textContent = "✓ 다운로드 완료";
    status.style.color = "var(--success, #2e7d32)";
  } catch (e) {
    status.textContent = `오류: ${e.message}`;
    status.style.color = "red";
  }
}

/* ── 원본 + Excel 검토 모달 ──────────────────────────── */
let _reviewData     = null;
let _reviewDocId    = null;
let _reviewFilename = null;
let _attachPage     = 0;
let _attachAll      = [];
const _ATTACH_PAGE_SIZE = 10;

function openReviewModal() {
  const raw = $("excelJson").value.trim();
  if (!raw) { toast("JSON을 먼저 입력하세요"); return; }
  try { _reviewData = JSON.parse(raw); } catch { toast("JSON 파싱 오류"); return; }
  _renderReviewForm(_reviewData);
  $("reviewSendSubject").value = `지출결의서 ${_reviewData.document_id || ""}`.trim();
  openModal("reviewModal");
}

function loadReviewPdf(input) {
  if (!input.files.length) return;
  const url = URL.createObjectURL(input.files[0]);
  $("reviewPdfFrame").src = url;
}

function _field(label, value, path, type="text") {
  return `<div class="form-group" style="margin-bottom:8px">
    <label class="form-label" style="font-size:11px;margin-bottom:2px">${esc(label)}</label>
    <input type="${type}" class="form-control" style="font-size:13px" data-path="${path}" value="${esc(String(value ?? ""))}" />
  </div>`;
}

function _renderReviewForm(data) {
  const d = data;
  const v = d.vendor || {};
  const p = d.payment || {};
  const t = d.total || {};
  const items = d.items || [];

  let itemsHtml = `<div style="font-size:12px;font-weight:600;margin:12px 0 6px">품목</div>`;
  items.forEach((it, i) => {
    itemsHtml += `<div style="background:var(--bg-muted,#f5f5f5);padding:8px;border-radius:4px;margin-bottom:6px">
      <div style="display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:6px">
        ${_field("품목명", it.name, `items.${i}.name`)}
        ${_field("수량", it.quantity, `items.${i}.quantity`)}
        ${_field("단가", it.unit_price, `items.${i}.unit_price`, "number")}
        ${_field("금액", it.amount, `items.${i}.amount`, "number")}
      </div>
      ${_field("비고", it.remark, `items.${i}.remark`)}
    </div>`;
  });
  itemsHtml += `<button class="btn btn-ghost btn-sm" onclick="addReviewItem()">+ 품목 추가</button>`;

  $("reviewForm").innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
      ${_field("문서번호", d.document_id, "document_id")}
      ${_field("작성일자", d.created_date, "created_date")}
      ${_field("작성부서", d.department, "department")}
      ${_field("계약번호", d.contract_no, "contract_no")}
    </div>
    ${_field("프로젝트명", d.project_name, "project_name")}
    <div style="font-size:12px;font-weight:600;margin:12px 0 6px">공급업체</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
      ${_field("업체명", v.company_name, "vendor.company_name")}
      ${_field("사업자등록번호", v.business_registration_no, "vendor.business_registration_no")}
      ${_field("대표자", v.representative, "vendor.representative")}
      ${_field("연락처", v.contact, "vendor.contact")}
      ${_field("계좌번호", v.account_no, "vendor.account_no")}
      ${_field("지급방법", p.method, "payment.method")}
      ${_field("지급예정일", p.scheduled_date, "payment.scheduled_date")}
    </div>
    ${itemsHtml}
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px">
      ${_field("합계금액", t.amount, "total.amount", "number")}
      ${_field("합계(한글)", t.amount_korean, "total.amount_korean")}
    </div>
    ${_field("적요", d.description, "description")}
    ${_field("비고", d.remark, "remark")}
  `;

  // 입력값 변경 시 _reviewData 동기화
  $("reviewForm").querySelectorAll("input").forEach(inp => {
    inp.addEventListener("input", () => _syncReviewField(inp.dataset.path, inp.value));
  });
}

function _syncReviewField(path, value) {
  const keys = path.split(".");
  let obj = _reviewData;
  for (let i = 0; i < keys.length - 1; i++) {
    const k = isNaN(keys[i]) ? keys[i] : parseInt(keys[i]);
    obj = obj[k];
  }
  const last = keys[keys.length - 1];
  const k = isNaN(last) ? last : parseInt(last);
  obj[k] = isNaN(value) || value === "" ? value : Number(value);
}

function addReviewItem() {
  _reviewData.items = _reviewData.items || [];
  _reviewData.items.push({name:"", quantity:"", unit_price:0, amount:0, remark:""});
  _renderReviewForm(_reviewData);
}

async function reviewDownload() {
  if (!_reviewData) return;
  const r = await fetch(`${BASE}/api/excel/generate`, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(_reviewData),
  });
  if (!r.ok) { toast("Excel 생성 오류"); return; }
  const blob = await r.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${_reviewData.document_id || "지출결의서"}.xlsx`;
  a.click();
}

async function reviewSend() {
  const to = $("reviewSendTo").value.trim();
  const subject = $("reviewSendSubject").value.trim();
  if (!to) { toast("수신자 이메일을 입력하세요"); return; }
  $("reviewStatus").textContent = "발송 중...";
  try {
    await api("POST", "/api/excel/send", {
      to, subject: subject || "지출결의서", body: "지출결의서를 첨부합니다.", data: _reviewData,
    });
    // 이력 저장
    await fetch(`${BASE}/api/history`, {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ doc_id: _reviewDocId, filename: _reviewFilename,
        sent_to: to, subject: subject || "지출결의서", data: _reviewData }),
    });
    showSuccess(`메일 발송 완료\n${to}`);
    loadHistory();
    setTimeout(() => closeModal("reviewModal"), 2000);
  } catch (e) {
    $("reviewStatus").textContent = `오류: ${e.message}`;
  }
}

async function testDedupContent() {
  const sel    = $("dedupContentSelect");
  const result = $("dedupContentResult");
  if (!sel.value) { toast("발송 이력을 선택하세요"); return; }
  result.style.display = "none";

  // 선택한 이력의 extracted_json 가져오기
  const res  = await fetch(`${BASE}/api/history`);
  const { history } = await res.json();
  const entry = history.find(h => h.id === sel.value);
  if (!entry) { toast("이력을 찾을 수 없습니다"); return; }

  let data;
  try { data = JSON.parse(entry.extracted_json || "{}"); } catch { data = {}; }

  const r    = await fetch(`${BASE}/api/dedup/content-check`, {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({ data }),
  });
  const resp = await r.json();
  if (!r.ok) { toast(resp.detail || "오류"); return; }

  const FIELD_LABEL = { document_id:"문서번호", company_name:"업체명", amount:"금액", created_date:"작성일자" };
  const targetRows = Object.entries(resp.target)
    .map(([k,v]) => `<tr><td style="color:var(--text-muted);padding:2px 8px 2px 0">${FIELD_LABEL[k]||k}</td><td><strong>${esc(v||"-")}</strong></td></tr>`).join("");

  if (resp.duplicate) {
    const matchRows = resp.matches.map(m => `
      <div style="padding:8px;border:1px solid #ff9800;border-radius:4px;margin-top:6px;font-size:12px">
        <strong>${esc(m.filename||m.doc_id)}</strong> · ${esc(m.sent_at)}<br>
        일치 필드: <span style="color:#e65100">${m.matched_fields.map(f=>FIELD_LABEL[f]||f).join(", ")}</span> (${m.match_count}개)
      </div>`).join("");
    result.style.background = "#fff3e0";
    result.style.border     = "1px solid #ff9800";
    result.innerHTML = `<strong>⚠ 유사 문서 감지 (${resp.matches.length}건)</strong>
      <table style="margin:8px 0;font-size:12px">${targetRows}</table>${matchRows}`;
  } else {
    result.style.background = "#e8f5e9";
    result.style.border     = "1px solid #4caf50";
    result.innerHTML = `<strong>✓ 중복 없음</strong>
      <table style="margin-top:8px;font-size:12px">${targetRows}</table>`;
  }
  result.style.display = "block";
}

async function testDedup() {
  const fileInput = $("dedupFile");
  const result    = $("dedupResult");
  if (!fileInput.files.length) { toast("파일을 선택하세요"); return; }
  result.style.display = "none";
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  try {
    const res  = await fetch(`${BASE}/api/dedup/check`, { method: "POST", body: fd });
    const data = await res.json();
    if (data.duplicate) {
      result.style.background = "#fff3e0";
      result.style.border     = "1px solid #ff9800";
      result.innerHTML = `<strong>⚠ 중복 파일 감지</strong><br>
        SHA-256: <code style="font-size:11px">${data.sha256}</code><br>
        기존 doc_id: <strong>${esc(data.existing.doc_id)}</strong><br>
        저장일시: ${esc(data.existing.saved_at)}`;
    } else {
      result.style.background = "#e8f5e9";
      result.style.border     = "1px solid #4caf50";
      result.innerHTML = `<strong>✓ 신규 파일</strong><br>
        SHA-256: <code style="font-size:11px">${data.sha256}</code>`;
    }
    result.style.display = "block";
  } catch (e) {
    toast("오류: " + e.message);
  }
}

async function testOcr() {
  const fileInput = $("ocrTestFile");
  const status    = $("ocrTestStatus");
  const result    = $("ocrTestResult");
  if (!fileInput.files.length) { toast("파일을 선택하세요"); return; }
  status.textContent = "전송 중...";
  result.style.display = "none";
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  try {
    const res = await fetch(`${BASE}/api/ocr/test`, { method: "POST", body: fd });
    let data;
    try { data = await res.json(); } catch { data = { status: res.status, response: await res.text() }; }
    status.style.color = res.ok ? "var(--success)" : "var(--danger)";
    status.textContent = res.ok ? `응답 수신 (${data.status})` : `실패 (${data.status ?? res.status})`;
    result.textContent = typeof data.response === "string" ? data.response : JSON.stringify(data.response, null, 2);
    result.style.display = "block";
  } catch (e) {
    status.style.color = "var(--danger)";
    status.textContent = "오류: " + e.message;
  }
}

async function loadHistory() {
  const el = $("sendHistory");
  if (!el) return;
  const res = await fetch(`${BASE}/api/history`);
  const { history } = await res.json();

  // 2차 중복 체크 select 채우기
  const sel = $("dedupContentSelect");
  if (sel) {
    sel.innerHTML = '<option value="">— 선택 —</option>' +
      history.map(h => `<option value="${h.id}">[${esc(h.sent_at)}] ${esc(h.filename || h.doc_id)}</option>`).join("");
  }

  if (!history.length) { el.innerHTML = '<div style="color:var(--text-muted);font-size:13px">발송 이력이 없습니다.</div>'; return; }
  el.innerHTML = `<table style="width:100%;font-size:12px;border-collapse:collapse">
    <thead><tr style="background:var(--bg-muted,#f5f5f5)">
      <th style="padding:6px;text-align:left">파일명</th>
      <th style="padding:6px;text-align:left">수신자</th>
      <th style="padding:6px;text-align:left">제목</th>
      <th style="padding:6px;text-align:left">발송일시</th>
    </tr></thead>
    <tbody>${history.map(h => `<tr style="border-top:1px solid var(--border)">
      <td style="padding:6px">${esc(h.filename || h.doc_id)}</td>
      <td style="padding:6px">${esc(h.sent_to)}</td>
      <td style="padding:6px">${esc(h.subject || "")}</td>
      <td style="padding:6px;white-space:nowrap">${esc(h.sent_at)}</td>
    </tr>`).join("")}</tbody>
  </table>`;
}

async function sendExcel() {
  const raw = $("excelJson").value.trim();
  const to  = $("excelSendTo").value.trim();
  const status = $("excelStatus");
  if (!raw)  { toast("JSON을 먼저 입력하세요"); return; }
  if (!to)   { toast("수신자 이메일을 입력하세요"); return; }
  let data;
  try { data = JSON.parse(raw); } catch { status.textContent = "JSON 파싱 오류"; status.style.color = "red"; return; }

  status.textContent = "발송 중...";
  status.style.color = "var(--text-muted)";
  try {
    const r = await api("POST", "/api/excel/send", {
      to,
      subject: `지출결의서 ${data.document_id || ""}`.trim(),
      body: "지출결의서를 첨부합니다.",
      data,
    });
    status.textContent = `✓ 발송 완료 → ${to}`;
    status.style.color = "var(--success, #2e7d32)";
    toast("메일 발송 완료");
  } catch (e) {
    status.textContent = `오류: ${e.message}`;
    status.style.color = "red";
  }
}

/* ── 수신 첨부파일 목록 + 추출 ─────────────────────────── */
async function importFromKnowledge() {
  toast("Knowledge에서 불러오는 중...");
  const res = await fetch(`${BASE}/api/attachments/import`, { method: "POST" });
  const data = await res.json();
  if (res.ok) {
    toast(`${data.imported}건 추가됨`);
    loadAttachments();
  } else {
    toast("불러오기 실패: " + (data.detail || ""));
  }
}

async function loadAttachments() {
  const el = $("attachmentList");
  if (!el) return;
  el.textContent = "로딩 중...";
  await fetch(`${BASE}/api/attachments/sync`, { method: "POST" });
  const res = await fetch("/pharma/api/attachments");
  const { attachments } = await res.json();
  _attachAll = attachments || [];
  _attachPage = 0;
  _renderAttachPage();
}

function _renderAttachPage() {
  const el = $("attachmentList");
  if (!el) return;
  if (!_attachAll.length) { el.textContent = "저장된 첨부파일이 없습니다."; return; }
  const total = _attachAll.length;
  const totalPages = Math.ceil(total / _ATTACH_PAGE_SIZE);
  const start = _attachPage * _ATTACH_PAGE_SIZE;
  const page  = _attachAll.slice(start, start + _ATTACH_PAGE_SIZE);
  el.innerHTML = page.map(a => `
    <div style="display:flex;align-items:center;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border)">
      <div>
        <div style="font-weight:500;color:var(--text)">${esc(a.filename)}</div>
        <div style="font-size:11px;color:var(--text-muted)">${esc(a.doc_id)} · ${esc(a.saved_at)}</div>
      </div>
      <button class="btn btn-outline" style="padding:4px 10px;font-size:12px;white-space:nowrap"
        onclick="extractAttachment('${esc(a.doc_id)}', '${a.filename.replace(/'/g,"\\'")}')">추출</button>
    </div>`).join("")
  + (totalPages > 1 ? `
    <div style="display:flex;align-items:center;justify-content:center;gap:8px;margin-top:10px;font-size:13px">
      <button class="btn btn-ghost btn-sm" onclick="_attachGoPage(${_attachPage-1})" ${_attachPage===0?"disabled":""}>&#8249;</button>
      <span style="color:var(--text-muted)">${_attachPage+1} / ${totalPages}</span>
      <button class="btn btn-ghost btn-sm" onclick="_attachGoPage(${_attachPage+1})" ${_attachPage===totalPages-1?"disabled":""}>&#8250;</button>
    </div>` : "");
}

function _attachGoPage(p) {
  const totalPages = Math.ceil(_attachAll.length / _ATTACH_PAGE_SIZE);
  _attachPage = Math.max(0, Math.min(p, totalPages - 1));
  _renderAttachPage();
}

async function extractAttachment(docId, filename) {
  showLoading("문서 추출 중...");
  try {
    const res = await fetch("/pharma/api/extract", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ document_id: docId }),
    });
    if (!res.ok) throw new Error(await res.text());
    const resp = await res.json();
    const data = resp.extracted || resp;

    // 2차 중복 체크
    hideLoading();
    const dupRes  = await fetch(`${BASE}/api/dedup/content-check`, {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ data }),
    });
    if (dupRes.ok) {
      const dupData = await dupRes.json();
      if (dupData.duplicate) {
        const LABEL = { document_id:"문서번호", company_name:"업체명", amount:"금액", created_date:"작성일자" };
        const top   = dupData.matches[0];
        const fields = top.matched_fields.map(f => LABEL[f] || f).join(", ");
        const go = confirm(
          `⚠ 유사 문서가 발송 이력에 있습니다.\n\n` +
          `파일: ${top.filename || top.doc_id}\n` +
          `발송일: ${top.sent_at}\n` +
          `일치 필드: ${fields}\n\n` +
          `계속 진행하시겠습니까?`
        );
        if (!go) return;
      }
    }

    _reviewDocId    = docId;
    _reviewFilename = filename || docId;
    _reviewData     = data;
    _renderReviewForm(data);
    $("reviewSendSubject").value = `지출결의서 ${data.document_id || ""}`.trim();
    $("reviewPdfFrame").src = `/pharma/api/attachment/local?filename=${encodeURIComponent(docId)}`;
    openModal("reviewModal");
  } catch (e) {
    hideLoading();
    toast("추출 실패: " + e.message);
  }
}

/* ── 문서 업로드 ──────────────────────────────────────── */
async function uploadDoc() {
  const docId = $("uploadDocId").value.trim();
  const repoId = $("uploadRepoId").value.trim();
  const fileInput = $("uploadFile");
  const status = $("uploadStatus");

  if (!docId) { toast("Document ID를 입력하세요"); return; }
  if (!fileInput.files.length) { toast("파일을 선택하세요"); return; }

  const btn = $("uploadBtn");
  btn.disabled = true;
  btn.textContent = "업로드 중...";
  status.textContent = "업로드 중...";
  status.style.color = "var(--text-muted)";

  const form = new FormData();
  form.append("document_id", docId);
  form.append("repo_id", repoId);
  form.append("file", fileInput.files[0]);

  try {
    const r = await fetch(`${BASE}/api/upload`, { method: "POST", body: form });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    status.textContent = `✓ 업로드 완료: ${data.file_name}`;
    status.style.color = "var(--success, #2e7d32)";
    toast("업로드 완료");
    fileInput.value = "";
  } catch (e) {
    status.textContent = `오류: ${e.message}`;
    status.style.color = "red";
  } finally {
    btn.disabled = false;
    btn.textContent = "업로드";
  }
}

function previewAttachment(messageId, attachmentId, mimeType, filename) {
  const url = `${BASE}/api/attachment?message_id=${encodeURIComponent(messageId)}&attachment_id=${encodeURIComponent(attachmentId)}&mime_type=${encodeURIComponent(mimeType)}&filename=${encodeURIComponent(filename)}`;
  $("attachModalTitle").textContent = filename;
  $("attachDownloadBtn").href = url;
  $("attachDownloadBtn").setAttribute("download", filename);

  let preview = "";
  if (mimeType.startsWith("image/")) {
    preview = `<img src="${url}" style="max-width:100%;max-height:70vh;object-fit:contain;display:block;margin:auto" />`;
  } else if (mimeType === "application/pdf") {
    preview = `<iframe src="${url}" style="width:100%;height:70vh;border:none"></iframe>`;
  } else {
    preview = `<div style="text-align:center;padding:40px;font-size:14px">미리보기를 지원하지 않는 파일 형식입니다.<br><br><a href="${url}" download="${esc(filename)}" style="color:#1a73e8">다운로드</a></div>`;
  }
  $("attachPreviewContent").innerHTML = preview;
  openModal("attachModal");
}

/* ── Watch 상태 UI ───────────────────────────────────── */
let _watchSSE = null;

function _startWatchPoll() {
  if (_watchSSE) return;
  _watchSSE = new EventSource(`${BASE}/api/pubsub/stream`);
  _watchSSE.onmessage = e => {
    if (e.data === "connected") return;
    try {
      const m = JSON.parse(e.data);
      // Gmail 테스트 탭 패널에도 표시
      const container = $("pullTestResults");
      if (container) {
        container.innerHTML = `
          <div class="card" style="margin-top:8px;padding:12px;border-left:3px solid var(--primary,#1a73e8)">
            <div style="font-weight:600;font-size:14px">${esc(m.subject || "(제목 없음)")}</div>
            <div style="font-size:12px;color:var(--text-muted);margin:4px 0">${esc(m.sender)} · ${esc(m.date)}</div>
            ${m.body ? `<div style="font-size:13px;margin-top:6px;white-space:pre-wrap;max-height:100px;overflow:auto">${esc(m.body.slice(0,300))}${m.body.length>300?"…":""}</div>` : ""}
          </div>` + container.innerHTML;
      }
      // 어느 탭에서든 토스트 알림
      toast(`📬 새 메일: ${m.subject || "(제목 없음)"}`);
      // 수신 첨부파일 목록 자동 새로고침
      loadAttachments();
    } catch {}
  };
  _watchSSE.onerror = () => {
    // 연결 끊기면 5초 후 재연결
    _watchSSE = null;
    setTimeout(_startWatchPoll, 5000);
  };
}
function _stopWatchPoll() {
  if (_watchSSE) { _watchSSE.close(); _watchSSE = null; }
}


async function refreshWatchStatus() {
  try {
    const s = await api("GET", "/api/watch/status");
    const el = $("watchStatusText");
    if (!el) return;
    if (s.active) {
      el.innerHTML = `✅ <strong>Watch 활성</strong> — 만료: ${s.expiration} (남은 시간: ${s.remaining_h}h)`;
    } else {
      el.textContent = "⚪ Watch 비활성 — PUBSUB_PROJECT_ID 설정 후 시작 가능";
    }
  } catch {}
}

async function watchStart() {
  const btn = $("watchStartBtn");
  btn.disabled = true;
  btn.textContent = "시작 중...";
  try {
    await api("POST", "/api/watch/start");
    toast("Gmail watch 시작됨");
    _startWatchPoll();
    refreshWatchStatus();
  } catch (e) {
    toast(`오류: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Watch 시작";
  }
}

async function watchStop() {
  const btn = $("watchStopBtn");
  btn.disabled = true;
  btn.textContent = "중지 중...";
  try {
    await api("POST", "/api/watch/stop");
    toast("Gmail watch 중지됨");
    _stopWatchPoll();
    refreshWatchStatus();
  } catch (e) {
    toast(`오류: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Watch 중지";
  }
}

/* ── 브라우저 푸시 알림 ───────────────────────────────── */
let _pollTimer = null;
let _seenAlertIds = new Set();
let _notifOn = false;

function _updateNotifBtn() {
  const btn = $("notifBtn");
  if (!btn) return;
  btn.textContent = _notifOn ? "🔔 알림 켜짐" : "🔕 알림 꺼짐";
  btn.style.background = _notifOn ? "var(--primary, #1a73e8)" : "";
  btn.style.color = _notifOn ? "#fff" : "";
}

async function _pollNewAlerts() {
  try {
    const data = await api("GET", "/api/alerts");
    for (const a of data.alerts) {
      if (a.read || _seenAlertIds.has(a.id)) continue;
      _seenAlertIds.add(a.id);
      if (Notification.permission === "granted") {
        new Notification(`💊 ${a.drug_name || "Pharma Monitor"}`, {
          body: a.message,
          tag:  a.id,
        });
      }
    }
    // 뱃지 갱신
    const unread = data.alerts.filter(a => !a.read).length;
    $("alertBadge").textContent = unread;
    $("alertBadge").style.display = unread ? "" : "none";
  } catch {}
}

function _startPolling() {
  _pollTimer = setInterval(_pollNewAlerts, 30_000);
  _pollNewAlerts();
}
function _stopPolling() {
  clearInterval(_pollTimer);
  _pollTimer = null;
}

async function toggleNotif() {
  if (!("Notification" in window)) { toast("이 브라우저는 알림을 지원하지 않습니다"); return; }
  if (!_notifOn) {
    const perm = await Notification.requestPermission();
    if (perm !== "granted") { toast("알림 권한이 거부되었습니다"); return; }
    _notifOn = true;
    _startPolling();
    toast("브라우저 알림이 활성화되었습니다");
  } else {
    _notifOn = false;
    _stopPolling();
    toast("브라우저 알림이 비활성화되었습니다");
  }
  _updateNotifBtn();
}

$("notifBtn").addEventListener("click", toggleNotif);

/* ── 초기화 ────────────────────────────────────────────── */
(async function init() {
  await refreshOAuthStatus();
  _startWatchPoll();
  loadDashboard();
  const params = new URLSearchParams(location.search);
  if (params.get("connected") === "1") {
    toast("Gmail 계정이 연결되었습니다 ✓");
    history.replaceState({}, "", BASE);
  }
  // 기존 알림 ID를 이미 읽은 것으로 초기화 (시작 시 과거 알림 중복 방지)
  try {
    const data = await api("GET", "/api/alerts");
    data.alerts.forEach(a => _seenAlertIds.add(a.id));
  } catch {}
})();
