/* ── Tab switching ── */
const VALID_TABS = ["search", "prec", "chat", "scheduler", "unified", "notifications", "lawprec"];
let lawLoaded  = false;
let precLoaded = false;

function switchTab(name) {
  if (!VALID_TABS.includes(name)) name = "search";
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
  const tab   = document.querySelector(`.tab[data-tab="${name}"]`);
  const panel = document.getElementById(`tab-${name}`);
  if (tab)   tab.classList.add("active");
  if (panel) panel.classList.add("active");
  window.scrollTo(0, 0);
  if (name === "search" && !lawLoaded)  { lawLoaded = true;  search(""); }
  if (name === "prec"   && !precLoaded) { precLoaded = true; searchPrec(""); }
  if (name === "scheduler")     { loadLaws(); loadLogs(); }
  if (name === "notifications") { loadNotifications(); }
}

document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    window.location.hash = tab.dataset.tab;
  });
});

window.addEventListener("hashchange", () => {
  switchTab(location.hash.slice(1));
});

// 새로고침 시 hash로 탭 복원
switchTab(location.hash.slice(1) || "search");

/* ════════════════════════════════
   법령 검색 탭 (국가법령 API)
   ════════════════════════════════ */
const searchForm  = document.getElementById("searchForm");
const searchInput = document.getElementById("searchInput");
const searchBtn   = document.getElementById("searchBtn");
const resultsEl   = document.getElementById("results");

let lawCurrentQuery  = "";
let lawCurrentPage   = 1;
let lawCurrentSearch = 1;
const LAW_PAGE_SIZE  = 10;

const searchTypeBtns = document.querySelectorAll(".search-type-btn");
searchTypeBtns.forEach(btn => {
  btn.addEventListener("click", () => {
    searchTypeBtns.forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    lawCurrentSearch = Number(btn.dataset.search);
    if (lawCurrentQuery) search(lawCurrentQuery, 1);
  });
});

async function search(query, page = 1) {
  const q = query.trim();
  lawCurrentQuery = q;
  lawCurrentPage  = page;
  if (q) searchInput.value = q;
  searchBtn.disabled = true;

  setResults('<div class="state-msg"><span class="spinner"></span>불러오는 중...</div>');

  try {
    const url = q
      ? `/api/law/search?q=${encodeURIComponent(q)}&display=${LAW_PAGE_SIZE}&page=${page}&search=${lawCurrentSearch}`
      : `/api/law/search?display=${LAW_PAGE_SIZE}&page=${page}`;
    const res  = await fetch(url);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "검색 오류");
    renderResults(data);
  } catch (err) {
    setResults(`<div class="state-msg error">${err.message}</div>`);
  } finally {
    searchBtn.disabled = false;
  }
}

function renderResults(data) {
  const laws = data.laws || [];
  if (laws.length === 0) {
    const msg = data.keyword ? `"${esc(data.keyword)}" 검색 결과가 없습니다.` : "검색 결과가 없습니다.";
    setResults(`<div class="state-msg">${msg}</div>`);
    return;
  }

  const totalPages = Math.ceil(data.total_cnt / LAW_PAGE_SIZE);
  const label = data.keyword ? `"${esc(data.keyword)}"` : "전체 법령";
  const header = `<div class="results-header">
    총 <strong>${Number(data.total_cnt).toLocaleString()}</strong>건 &nbsp;·&nbsp; ${label}
  </div>`;

  setResults(header + laws.map(buildCard).join("") + buildPagination(lawCurrentPage, totalPages, "law"));

  resultsEl.querySelectorAll(".law-card").forEach(card => {
    card.addEventListener("click", () => toggleCard(card));
  });
  resultsEl.querySelectorAll(".page-btn[data-tab='law']").forEach(btn => {
    btn.addEventListener("click", () => search(lawCurrentQuery, Number(btn.dataset.page)));
  });
}

function buildCard(law) {
  const name = law["법령명한글"] || law["법령명"] || "(이름 없음)";
  const id   = law["법령ID"] || "";
  const dept = law["소관부처명"] || "";
  const date = fmtDate(law["시행일자"] || law["공포일자"] || "");
  const kind = law["법령구분명"] || law["법종구분명"] || "";

  return `
    <div class="law-card" data-id="${esc(id)}">
      <div class="card-main">
        <div class="card-left">
          <div class="card-title">${esc(name)}</div>
          <div class="card-meta">
            ${dept ? `<span>${esc(dept)}</span>` : ""}
            ${date ? `<span>시행 ${esc(date)}</span>` : ""}
            ${kind ? `<span class="badge">${esc(kind)}</span>` : ""}
          </div>
        </div>
        <div class="card-arrow">›</div>
      </div>
      <div class="card-detail hidden"></div>
    </div>`;
}

async function toggleCard(card) {
  const detail = card.querySelector(".card-detail");
  if (!detail.classList.contains("hidden")) {
    detail.classList.add("hidden");
    card.classList.remove("expanded");
    return;
  }
  card.classList.add("expanded");
  detail.classList.remove("hidden");
  if (detail.dataset.loaded) return;

  detail.innerHTML = '<div class="state-msg"><span class="spinner"></span>조문 불러오는 중...</div>';
  try {
    const res  = await fetch(`/api/law/${encodeURIComponent(card.dataset.id)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "조회 오류");
    renderArticles(detail, data);
    detail.dataset.loaded = "1";
  } catch (err) {
    detail.innerHTML = `<div class="state-msg error">${err.message}</div>`;
  }
}

function renderArticles(container, data) {
  const articles = filterArticles(data.articles || []);
  if (articles.length === 0) {
    container.innerHTML = '<div class="state-msg">조문 정보가 없습니다.</div>';
    return;
  }
  container.innerHTML = articles.map(buildArticleHtml).join("");
}

function setResults(html) { resultsEl.innerHTML = html; }

searchForm.addEventListener("submit", e => { e.preventDefault(); search(searchInput.value); });
document.querySelectorAll(".chip:not(.chat-chip)").forEach(btn => {
  btn.addEventListener("click", () => search(btn.dataset.q));
});
searchInput.focus();


/* ════════════════════════════════
   판례 검색 탭 (국가법령 API)
   ════════════════════════════════ */
const precForm    = document.getElementById("precForm");
const precInput   = document.getElementById("precInput");
const precBtn     = document.getElementById("precBtn");
const precResults = document.getElementById("precResults");

let precCurrentQuery = "";
let precCurrentPage  = 1;
const PREC_PAGE_SIZE = 10;

async function searchPrec(query, page = 1) {
  const q = query.trim();
  precCurrentQuery = q;
  precCurrentPage  = page;
  if (q) precInput.value = q;
  precBtn.disabled = true;

  precResults.innerHTML = '<div class="state-msg"><span class="spinner"></span>불러오는 중...</div>';

  try {
    const url = q
      ? `/api/prec/search?q=${encodeURIComponent(q)}&display=${PREC_PAGE_SIZE}&page=${page}`
      : `/api/prec/search?display=${PREC_PAGE_SIZE}&page=${page}`;
    const res  = await fetch(url);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "검색 오류");
    renderPrecResults(data);
  } catch (err) {
    precResults.innerHTML = `<div class="state-msg error">${err.message}</div>`;
  } finally {
    precBtn.disabled = false;
  }
}

let precActiveFilter = "전체";

function renderPrecResults(data) {
  const precs = data.precs || [];
  if (precs.length === 0) {
    const msg = data.keyword ? `"${esc(data.keyword)}" 검색 결과가 없습니다.` : "검색 결과가 없습니다.";
    precResults.innerHTML = `<div class="state-msg">${msg}</div>`;
    return;
  }

  const totalPages = Math.ceil(data.total_cnt / PREC_PAGE_SIZE);
  const precLabel = data.keyword ? `"${esc(data.keyword)}"` : "전체 판례";
  const header = `<div class="results-header">
    총 <strong>${Number(data.total_cnt).toLocaleString()}</strong>건 &nbsp;·&nbsp; ${precLabel}
  </div>`;

  const courtFilter = buildCourtFilter(precs);
  const cards = precs.map(buildPrecCard).join("");
  const pagination = buildPagination(precCurrentPage, totalPages, "prec");

  precResults.innerHTML = header + courtFilter + `<div id="precCards">${cards}</div>` + pagination;

  applyCourtFilter(precActiveFilter);

  precResults.querySelectorAll(".court-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      precResults.querySelectorAll(".court-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      precActiveFilter = btn.dataset.court;
      applyCourtFilter(precActiveFilter);
    });
  });

  precResults.querySelectorAll(".law-card").forEach(card => {
    card.addEventListener("click", () => togglePrecCard(card));
  });
  precResults.querySelectorAll(".page-btn[data-tab='prec']").forEach(btn => {
    btn.addEventListener("click", () => {
      precActiveFilter = "전체";
      searchPrec(precCurrentQuery, Number(btn.dataset.page));
    });
  });
}

function buildCourtFilter(precs) {
  const courtOrder = ["대법원", "고등법원", "지방법원", "행정법원", "가정법원", "특허법원", "헌법재판소"];
  const counts = {};

  precs.forEach(p => {
    const full = p["법원명"] || "기타";
    const group = courtOrder.find(c => full.includes(c)) || "기타";
    counts[group] = (counts[group] || 0) + 1;
  });

  const available = courtOrder.filter(c => counts[c]).concat(counts["기타"] ? ["기타"] : []);
  if (available.length <= 1) return "";

  const total = precs.length;
  const btns = [
    `<button class="court-btn ${precActiveFilter === "전체" ? "active" : ""}" data-court="전체">전체 <span class="court-count">${total}</span></button>`,
    ...available.map(c =>
      `<button class="court-btn ${precActiveFilter === c ? "active" : ""}" data-court="${esc(c)}">${esc(c)} <span class="court-count">${counts[c]}</span></button>`
    ),
  ].join("");

  return `<div class="court-filter">${btns}</div>`;
}

function applyCourtFilter(filter) {
  const courtOrder = ["대법원", "고등법원", "지방법원", "행정법원", "가정법원", "특허법원", "헌법재판소"];
  document.querySelectorAll("#precCards .law-card").forEach(card => {
    if (filter === "전체") {
      card.style.display = "";
      return;
    }
    const court = card.dataset.court || "";
    const group = courtOrder.find(c => court.includes(c)) || "기타";
    card.style.display = group === filter ? "" : "none";
  });
}

function buildPrecCard(prec) {
  const id       = prec["판례정보일련번호"] || prec["판례일련번호"] || "";
  const name     = prec["사건명"] || "(사건명 없음)";
  const caseNo   = prec["사건번호"] || "";
  const court    = prec["법원명"] || "";
  const date     = fmtDate(prec["선고일자"] || "");
  const caseType = prec["사건종류명"] || "";
  const judgeType = prec["판결유형"] || "";

  return `
    <div class="law-card" data-id="${esc(id)}" data-court="${esc(court)}">
      <div class="card-main">
        <div class="card-left">
          <div class="card-title">${esc(name)}</div>
          <div class="card-meta">
            ${caseNo ? `<span>${esc(caseNo)}</span>` : ""}
            ${court  ? `<span>${esc(court)}</span>`  : ""}
            ${date   ? `<span>${esc(date)}</span>`   : ""}
            ${caseType  ? `<span class="badge">${esc(caseType)}</span>`  : ""}
            ${judgeType ? `<span class="badge badge-gray">${esc(judgeType)}</span>` : ""}
          </div>
        </div>
        <div class="card-arrow">›</div>
      </div>
      <div class="card-detail hidden"></div>
    </div>`;
}

async function togglePrecCard(card) {
  const detail = card.querySelector(".card-detail");
  if (!detail.classList.contains("hidden")) {
    detail.classList.add("hidden");
    card.classList.remove("expanded");
    return;
  }
  card.classList.add("expanded");
  detail.classList.remove("hidden");
  if (detail.dataset.loaded) return;

  detail.innerHTML = '<div class="state-msg"><span class="spinner"></span>판례 불러오는 중...</div>';
  try {
    const res  = await fetch(`/api/prec/${encodeURIComponent(card.dataset.id)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "조회 오류");
    renderPrecDetail(detail, data);
    detail.dataset.loaded = "1";
  } catch (err) {
    detail.innerHTML = `<div class="state-msg error">${err.message}</div>`;
  }
}

function renderPrecDetail(container, data) {
  const sections = [
    { label: "판시사항", value: data.issues    },
    { label: "판결요지", value: data.summary   },
    { label: "참조판례", value: data.ref_cases },
  ];

  let html = sections
    .filter(s => s.value && s.value.trim())
    .map(s => `
      <div class="article">
        <div class="article-header">${esc(s.label)}</div>
        <div class="article-content">${esc(stripHtml(s.value))}</div>
      </div>`)
    .join("");

  if (data.ref_articles && data.ref_articles.trim()) {
    const citations = extractCitations(data.ref_articles);
    const citHtml = citations.length
      ? `<div class="law-links">${citations.map(c =>
          `<button class="law-link-btn" data-law="${esc(c.lawName)}" data-jo="${c.joNum}" data-jo-sub="${c.joSub}">
            ${esc(c.lawName)} ${esc(c.joText)}
          </button>`).join("")}</div>`
      : "";

    html += `
      <div class="article">
        <div class="article-header">참조조문</div>
        <div class="article-content">${esc(stripHtml(data.ref_articles))}</div>
        ${citHtml}
      </div>`;
  }

  if (!html && data.content?.trim()) {
    html = `<div class="article">
      <div class="article-header">판례 전문</div>
      <div class="article-content">${esc(stripHtml(data.content))}</div>
    </div>`;
  }

  const summarizeText = [data.issues, data.summary].filter(Boolean).join("\n").trim();
  const toolbar = summarizeText
    ? `<div class="card-detail-toolbar"><button class="btn-summarize">AI 요약</button></div>`
    : "";

  container.innerHTML = toolbar + (html || '<div class="state-msg">상세 내용이 없습니다.</div>');

  container.querySelectorAll(".law-link-btn").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      openArticlePanel(btn.dataset.law, Number(btn.dataset.jo), Number(btn.dataset.joSub));
    });
  });

  const summarizeBtn = container.querySelector(".btn-summarize");
  if (summarizeBtn) {
    summarizeBtn.addEventListener("click", async e => {
      e.stopPropagation();
      summarizeBtn.disabled = true;
      summarizeBtn.innerHTML = '<span class="spinner" style="width:11px;height:11px;margin-right:5px;vertical-align:middle"></span>요약 중...';
      container.querySelector(".summary-box")?.remove();
      container.querySelector(".summary-error")?.remove();
      try {
        const res = await fetch("/api/summarize", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: summarizeText }),
        });
        const result = await res.json();
        if (!res.ok) throw new Error(result.detail || "요약 오류");
        const box = document.createElement("div");
        box.className = "summary-box";
        box.innerHTML = `<div class="summary-box-header">✦ AI 요약</div>${esc(result.summary)}`;
        summarizeBtn.closest(".card-detail-toolbar").insertAdjacentElement("afterend", box);
        summarizeBtn.textContent = "다시 요약";
      } catch (err) {
        const errEl = document.createElement("div");
        errEl.className = "state-msg error summary-error";
        errEl.style.fontSize = "0.82rem";
        errEl.textContent = err.message;
        summarizeBtn.closest(".card-detail-toolbar").insertAdjacentElement("afterend", errEl);
        summarizeBtn.textContent = "AI 요약";
      } finally {
        summarizeBtn.disabled = false;
      }
    });
  }
}

function extractCitations(refArticles) {
  // 국가법령정보센터 API는 법령명을 <민법>, <도로교통법> 형식 태그로 표시함
  // stripHtml 전에 이를 "민법 ", "도로교통법 "으로 변환
  let raw = String(refArticles || "");
  raw = raw.replace(/<([^>]{1,50}(?:법|령|규칙|예규|조례|지침|규정))>/g, "$1 ");
  const text = stripHtml(raw);
  const results = [];
  const seen = new Set();
  let currentLaw = "";

  // 두 가지 패턴을 교대로 매칭:
  // 1) 법령명 + 제N조  →  법령명 갱신
  // 2) 제N조 단독      →  직전 법령명 이어받기
  const re = /((?:[가-힣]+\s)*[가-힣]+(?:법|령|규칙|예규|조례|지침))\s*제(\d+)조(?:의(\d+))?|제(\d+)조(?:의(\d+))?/g;

  for (const m of text.matchAll(re)) {
    let joNum, joSub;

    if (m[1]) {
      // 법령명 + 제N조
      currentLaw = m[1].trim();
      joNum = parseInt(m[2]);
      joSub = m[3] ? parseInt(m[3]) : 0;
    } else {
      // 제N조 단독 — 이전 법령 이어받기
      if (!currentLaw) continue;
      joNum = parseInt(m[4]);
      joSub = m[5] ? parseInt(m[5]) : 0;
    }

    if (!joNum) continue;
    const joText = `제${joNum}조${joSub ? `의${joSub}` : ""}`;
    const key = `${currentLaw}|${joNum}|${joSub}`;
    if (seen.has(key)) continue;
    seen.add(key);
    results.push({ lawName: currentLaw, joText, joNum, joSub });
  }
  return results;
}


/* ── Article panel ── */
const panelEl      = document.getElementById("articlePanel");
const panelClose   = document.getElementById("panelClose");
const panelContent = document.getElementById("panelContent");
const panelLawName = document.getElementById("panelLawName");
const panelJoTitle = document.getElementById("panelJoTitle");

function openPanel() {
  panelEl.classList.add("open");
}

function closePanel() {
  panelEl.classList.remove("open");
}

panelClose.addEventListener("click", closePanel);

async function openArticlePanel(lawName, joNum, joSub = 0) {
  panelLawName.textContent = lawName;
  panelJoTitle.textContent = `제${joNum}조${joSub ? `의${joSub}` : ""}`;
  panelContent.innerHTML = '<div class="state-msg"><span class="spinner"></span>불러오는 중...</div>';
  openPanel();
  history.pushState({ panelOpen: true }, "");

  try {
    const url = `/api/law/article?law_name=${encodeURIComponent(lawName)}&jo=${joNum}&jo_sub=${joSub}`;
    const res  = await fetch(url);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "조회 오류");

    const articles = data.articles || [];
    if (articles.length === 0) {
      panelContent.innerHTML = '<div class="state-msg">조문 내용이 없습니다.</div>';
      return;
    }

    panelLawName.textContent = data.searched_law_name || lawName;

    panelContent.innerHTML = filterArticles(articles).map(buildArticleHtml).join("");

  } catch (err) {
    panelContent.innerHTML = `<div class="state-msg error">${err.message}</div>`;
  }
}

function stripHtml(str) {
  return String(str || "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .trim();
}

precForm.addEventListener("submit", e => { e.preventDefault(); searchPrec(precInput.value); });
document.querySelectorAll(".prec-chip").forEach(btn => {
  btn.addEventListener("click", () => searchPrec(btn.dataset.q));
});


/* ════════════════════════════════
   법령 상담 탭 (플랫폼 API)
   ════════════════════════════════ */
const chatForm  = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");
const chatBtn   = document.getElementById("chatBtn");
const chatEl    = document.getElementById("chat");
const welcomeEl = document.getElementById("welcome");

let chatBusy = false;

function appendMessage(role, text, { loading = false, error = false } = {}) {
  if (welcomeEl) welcomeEl.remove();

  const wrap   = document.createElement("div");
  wrap.className = `message ${role}${error ? " error" : ""}`;

  const label  = document.createElement("div");
  label.className = "message-label";
  label.textContent = role === "user" ? "나" : "에이전트";

  const bubble = document.createElement("div");
  bubble.className = `bubble${loading ? " loading" : ""}`;
  bubble.textContent = text;

  wrap.append(label, bubble);
  chatEl.appendChild(wrap);
  chatEl.scrollTop = chatEl.scrollHeight;
  return bubble;
}

async function sendMessage(text) {
  const message = text.trim();
  if (!message || chatBusy) return;

  appendMessage("user", message);
  chatInput.value = "";
  chatInput.style.height = "auto";
  chatBusy = true;
  chatBtn.disabled = true;
  chatInput.disabled = true;

  const bubble = appendMessage("assistant", "", { loading: true });
  bubble.innerHTML = '<span class="typing-dots"><span></span><span></span><span></span></span>';

  const sendIcon = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 19V5M5 12l7-7 7 7"/></svg>`;
  chatBtn.innerHTML = '<div class="chat-btn-spinner"></div>';

  try {
    await streamChat(message, bubble);
  } catch (err) {
    bubble.classList.remove("loading");
    bubble.closest(".message").classList.add("error");
    bubble.textContent = err.message || "요청 중 오류가 발생했습니다.";
  } finally {
    chatBusy = false;
    chatBtn.disabled = false;
    chatBtn.innerHTML = sendIcon;
    chatInput.disabled = false;
    chatInput.focus();
  }
}

async function streamChat(message, bubble) {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "스트리밍 오류");
  }

  bubble.classList.remove("loading");
  bubble.textContent = "";

  const reader  = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const payload = line.slice(6).trim();
      if (payload === "[DONE]") return;
      try {
        const data = JSON.parse(payload);
        if (data.error) throw new Error(data.error);
        if (data.token) {
          bubble.textContent += data.token;
          chatEl.scrollTop = chatEl.scrollHeight;
        }
      } catch (e) {
        if (e.message && e.message !== "Unexpected end of JSON input") throw e;
      }
    }
  }
}

const CASE_NUM_RE = /(\d{4}[가-힣]+\d+)/g;

function linkifyCaseNums(bubble) {
  const text = bubble.textContent;
  CASE_NUM_RE.lastIndex = 0;
  if (!CASE_NUM_RE.test(text)) return;
  CASE_NUM_RE.lastIndex = 0;
  const parts = text.split(CASE_NUM_RE);
  bubble.innerHTML = parts.map((p, i) =>
    i % 2 === 1
      ? `<button class="prec-link" data-no="${esc(p)}">${esc(p)}</button>`
      : esc(p)
  ).join("");
}


chatForm.addEventListener("submit", e => { e.preventDefault(); sendMessage(chatInput.value); });

chatInput.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); chatForm.requestSubmit(); }
});

chatInput.addEventListener("input", () => {
  chatInput.style.height = "auto";
  chatInput.style.height = `${Math.min(chatInput.scrollHeight, 120)}px`;
});

document.querySelectorAll(".chat-chip").forEach(btn => {
  btn.addEventListener("click", () => sendMessage(btn.dataset.msg));
});


/* ── Pagination ── */
function buildPagination(current, total, tab) {
  if (total <= 1) return "";

  const WINDOW = 2;
  const start  = Math.max(1, current - WINDOW);
  const end    = Math.min(total, current + WINDOW);

  let html = '<div class="pagination">';

  html += `<button class="page-btn" data-tab="${tab}" data-page="${current - 1}"
    ${current === 1 ? "disabled" : ""}>‹ 이전</button>`;

  if (start > 1) {
    html += `<button class="page-btn" data-tab="${tab}" data-page="1">1</button>`;
    if (start > 2) html += `<span class="page-ellipsis">…</span>`;
  }

  for (let p = start; p <= end; p++) {
    html += `<button class="page-btn ${p === current ? "active" : ""}"
      data-tab="${tab}" data-page="${p}">${p}</button>`;
  }

  if (end < total) {
    if (end < total - 1) html += `<span class="page-ellipsis">…</span>`;
    html += `<button class="page-btn" data-tab="${tab}" data-page="${total}">${total}</button>`;
  }

  html += `<button class="page-btn" data-tab="${tab}" data-page="${current + 1}"
    ${current === total ? "disabled" : ""}>다음 ›</button>`;

  html += "</div>";
  return html;
}


/* ── Article renderer ── */
function filterArticles(articles) {
  // 조문여부가 "조문"인 것만, 중복 조문키 제거
  const seen = new Set();
  return articles.filter(art => {
    if (art["조문여부"] && art["조문여부"] !== "조문") return false;
    const key = art["조문키"] || `${art["조문번호"]}_${art["조문시행일자"]}`;
    if (seen.has(key)) return false;
    seen.add(key);
    const hasContent = Array.isArray(art["항"]) && art["항"].length > 0
      || String(art["조문내용"] || "").trim().length > 0;
    return hasContent;
  });
}

function buildArticleHtml(art) {
  const num   = art["조문번호"] || "";
  const title = art["조문제목"] || "";
  const hangs = Array.isArray(art["항"]) ? art["항"] : [];

  let body = "";

  if (hangs.length > 0) {
    body = hangs.map(hang => {
      const hangContent = String(hang["항내용"] || "").trim();
      const hos = Array.isArray(hang["호"]) ? hang["호"] : [];
      const hoHtml = hos.map(ho =>
        `<div class="ho-item">${esc(String(ho["호내용"] || "").trim())}</div>`
      ).join("");
      return `<div class="hang-item">${esc(hangContent)}${hoHtml}</div>`;
    }).join("");
  } else {
    let content = String(art["조문내용"] || "").trim();
    const headerPattern = new RegExp(`^제${num}조(?:\\([^)]+\\))?\\s*`);
    content = content.replace(headerPattern, "").trim();
    if (content) body = `<div class="hang-item">${esc(content)}</div>`;
  }

  return `
    <div class="article">
      <div class="article-header">제${esc(num)}조${title ? `(${esc(title)})` : ""}</div>
      ${body}
    </div>`;
}


/* ════════════════════════════════
   수집 관리 탭 (Scheduler)
   ════════════════════════════════ */
const lawList        = document.getElementById("lawList");
const logList        = document.getElementById("logList");
const addLawBtn      = document.getElementById("addLawBtn");
const refreshLogsBtn = document.getElementById("refreshLogsBtn");
const lawModal       = document.getElementById("lawModal");
const modalTitle     = document.getElementById("modalTitle");
const modalLawName   = document.getElementById("modalLawName");
const modalCollectType = document.getElementById("modalCollectType");
const modalInterval  = document.getElementById("modalInterval");
const modalSave      = document.getElementById("modalSave");
const modalCancel    = document.getElementById("modalCancel");
const modalClose     = document.getElementById("modalClose");
const lawNameDropdown = document.getElementById("lawNameDropdown");
const daySelector    = document.getElementById("daySelector");
const dayLabel       = document.getElementById("dayLabel");
const weekdayPicker  = document.getElementById("weekdayPicker");
const monthdayPicker = document.getElementById("monthdayPicker");
const modalHour      = document.getElementById("modalHour");
const modalMinute    = document.getElementById("modalMinute");

// 날짜 선택 옵션 초기화 (1~31일)
for (let d = 1; d <= 31; d++) {
  const opt = document.createElement("option");
  opt.value = String(d);
  opt.textContent = `${d}일`;
  monthdayPicker.appendChild(opt);
}

// 시간 선택 옵션 초기화 (0~23시)
for (let h = 0; h < 24; h++) {
  const opt = document.createElement("option");
  opt.value = String(h).padStart(2, "0");
  opt.textContent = `${String(h).padStart(2, "0")}시`;
  if (h === 9) opt.selected = true;
  modalHour.appendChild(opt);
}

let editingLawId = null;
let selectedDay   = null;
let acTimer       = null;

const STATUS_LABEL = { idle: "대기", running: "실행중", success: "완료", failed: "실패" };

function fmtScheduleInterval(interval, day, time) {
  const t = time ? ` ${time}` : "";
  if (interval === "daily")   return `매일${t}`;
  if (interval === "weekly")  return day ? `매주 ${day}요일${t}` : `매주${t}`;
  if (interval === "monthly") return day ? `매월 ${day}일${t}` : `매월${t}`;
  return interval;
}

/* ── 페이지네이션 공통 ── */
const SCHED_LAW_PAGE_SIZE = 6;
const LOG_PAGE_SIZE = 10;

function renderPagination(container, total, page, pageSize, onPageChange) {
  const totalPages = Math.ceil(total / pageSize);
  if (totalPages <= 1) { container.innerHTML = ""; return; }

  const pages = [];
  for (let i = 1; i <= totalPages; i++) {
    if (i === 1 || i === totalPages || Math.abs(i - page) <= 2) {
      pages.push(i);
    } else if (pages[pages.length - 1] !== "…") {
      pages.push("…");
    }
  }

  container.innerHTML = `
    <button class="page-btn" data-page="${page - 1}" ${page <= 1 ? "disabled" : ""}>‹</button>
    ${pages.map(p => p === "…"
      ? `<span class="page-ellipsis">…</span>`
      : `<button class="page-btn ${p === page ? "active" : ""}" data-page="${p}">${p}</button>`
    ).join("")}
    <button class="page-btn" data-page="${page + 1}" ${page >= totalPages ? "disabled" : ""}>›</button>`;

  container.querySelectorAll(".page-btn:not([disabled])").forEach(btn =>
    btn.addEventListener("click", () => onPageChange(parseInt(btn.dataset.page)))
  );
}

/* ── 법령 목록 로드 ── */
let allLaws = [], lawPage = 1;

async function loadLaws() {
  try {
    const res  = await fetch("/api/scheduler/laws");
    const data = await res.json();
    allLaws = data.laws || [];
    lawPage = 1;
    renderLawPage();
  } catch (e) {
    lawList.innerHTML = `<div class="empty-msg">불러오기 실패: ${esc(e.message)}</div>`;
  }
}

function renderLawPage() {
  const start = (lawPage - 1) * SCHED_LAW_PAGE_SIZE;
  renderLawTable(allLaws.slice(start, start + SCHED_LAW_PAGE_SIZE));
  renderPagination(
    document.getElementById("lawPagination"),
    allLaws.length, lawPage, SCHED_LAW_PAGE_SIZE,
    p => { lawPage = p; renderLawPage(); }
  );
}

const COLLECT_TYPE_LABEL = { "전체": "법령+판례", "법령": "법령", "판례": "판례" };

function renderLawTable(laws) {
  if (!laws.length) {
    lawList.innerHTML = '<div class="empty-msg">등록된 법령이 없습니다.</div>';
    return;
  }
  lawList.innerHTML = laws.map(law => {
    const status      = law.status || "idle";
    const day         = law.day  || "";
    const time        = law.time || "09:00";
    const collectType = law.collect_type || "전체";
    return `
      <div class="law-card">
        <div class="law-card-top">
          <span class="law-card-name">${esc(law.name)}</span>
          <span class="status-badge status-${esc(status)}">${esc(STATUS_LABEL[status] || status)}</span>
        </div>
        <div class="law-card-meta">
          <span class="law-meta-item">
            <span class="law-meta-label">수집 대상</span>
            <span class="badge">${esc(COLLECT_TYPE_LABEL[collectType] || collectType)}</span>
          </span>
          <span class="law-meta-item">
            <span class="law-meta-label">주기</span>
            <span>${esc(fmtScheduleInterval(law.interval, day, time))}</span>
          </span>
        </div>
        <div class="law-card-meta">
          <span class="law-meta-item">
            <span class="law-meta-label">최근 수집</span>
            <span>${esc(law.last_run || "-")}</span>
          </span>
          <span class="law-meta-item">
            <span class="law-meta-label">다음 수집</span>
            <span>${esc(law.next_run || "-")}</span>
          </span>
        </div>
        <div class="law-card-actions">
          <button class="btn-run"    data-id="${esc(law.id)}" data-name="${esc(law.name)}">수집</button>
          <button class="btn-edit"   data-id="${esc(law.id)}" data-name="${esc(law.name)}" data-interval="${esc(law.interval)}" data-day="${esc(day)}" data-time="${esc(time)}" data-collect-type="${esc(collectType)}">편집</button>
          <button class="btn-delete" data-id="${esc(law.id)}" data-name="${esc(law.name)}">삭제</button>
        </div>
      </div>`;
  }).join("");

  lawList.querySelectorAll(".btn-run").forEach(btn =>
    btn.addEventListener("click", () => runLaw(btn.dataset.id, btn.dataset.name, btn)));
  lawList.querySelectorAll(".btn-edit").forEach(btn =>
    btn.addEventListener("click", () => openModal(btn.dataset.id, btn.dataset.name, btn.dataset.interval, btn.dataset.day || null, btn.dataset.time || "09:00", btn.dataset.collectType || "전체")));
  lawList.querySelectorAll(".btn-delete").forEach(btn =>
    btn.addEventListener("click", () => deleteLaw(btn.dataset.id, btn.dataset.name)));
}

async function runLaw(id, name, btn) {
  if (!confirm(`"${name}" 수집을 지금 실행하시겠습니까?`)) return;
  btn.disabled = true;
  btn.textContent = "실행중...";
  try {
    const res = await fetch(`/api/scheduler/laws/${id}/run`, { method: "POST" });
    const log = await res.json();
    if (!res.ok) throw new Error(log.detail || "실행 오류");
    await loadLaws();
    await loadLogs();
  } catch (e) {
    alert(`수집 실패: ${e.message}`);
    btn.disabled = false;
    btn.textContent = "수집";
  }
}

async function deleteLaw(id, name) {
  if (!confirm(`"${name}"을(를) 삭제하시겠습니까?`)) return;
  try {
    const res = await fetch(`/api/scheduler/laws/${id}`, { method: "DELETE" });
    if (!res.ok) {
      const d = await res.json();
      throw new Error(d.detail || "삭제 오류");
    }
    await loadLaws();
  } catch (e) {
    alert(`삭제 실패: ${e.message}`);
  }
}

/* ── 요일/날짜 선택 ── */
function updateDaySelector(interval, day) {
  if (interval === "weekly") {
    daySelector.style.display = "block";
    dayLabel.textContent = "요일 선택";
    weekdayPicker.style.display = "flex";
    monthdayPicker.style.display = "none";
    const target = day || "월";
    selectedDay = target;
    weekdayPicker.querySelectorAll(".weekday-btn").forEach(b =>
      b.classList.toggle("active", b.dataset.day === target));
  } else if (interval === "monthly") {
    daySelector.style.display = "block";
    dayLabel.textContent = "날짜 선택";
    weekdayPicker.style.display = "none";
    monthdayPicker.style.display = "block";
    const target = day || "1";
    selectedDay = target;
    monthdayPicker.value = target;
  } else {
    daySelector.style.display = "none";
    selectedDay = null;
  }
}

modalInterval.addEventListener("change", () => updateDaySelector(modalInterval.value, null));

weekdayPicker.querySelectorAll(".weekday-btn").forEach(btn =>
  btn.addEventListener("click", () => {
    weekdayPicker.querySelectorAll(".weekday-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    selectedDay = btn.dataset.day;
  }));

monthdayPicker.addEventListener("change", () => { selectedDay = monthdayPicker.value; });

/* ── 법령명 자동완성 ── */
modalLawName.addEventListener("input", () => {
  const q = modalLawName.value.trim();
  clearTimeout(acTimer);
  if (q.length < 1) { hideLawDropdown(); return; }
  acTimer = setTimeout(() => fetchLawSuggestions(q), 280);
});

async function fetchLawSuggestions(q) {
  try {
    const res  = await fetch(`/api/law/search?q=${encodeURIComponent(q)}&display=10`);
    const data = await res.json();
    showLawDropdown(data.laws || []);
  } catch { hideLawDropdown(); }
}

function showLawDropdown(laws) {
  if (!laws.length) { hideLawDropdown(); return; }
  lawNameDropdown.innerHTML = laws.map(law => {
    const name = law["법령명한글"] || law["법령명"] || "";
    return `<li class="autocomplete-item" data-name="${esc(name)}">${esc(name)}</li>`;
  }).join("");
  lawNameDropdown.style.display = "block";
  lawNameDropdown.querySelectorAll(".autocomplete-item").forEach(li =>
    li.addEventListener("click", () => {
      modalLawName.value = li.dataset.name;
      hideLawDropdown();
    }));
}

function hideLawDropdown() {
  lawNameDropdown.style.display = "none";
  lawNameDropdown.innerHTML = "";
}

document.addEventListener("click", e => {
  if (!e.target.closest(".autocomplete-wrap")) hideLawDropdown();
});

/* ── 모달 열기/닫기 ── */
function openModal(id = null, name = "", interval = "weekly", day = null, time = "09:00", collectType = "전체") {
  editingLawId = id;
  modalTitle.textContent = id ? "법령 편집" : "법령 추가";
  modalLawName.value = name;
  modalCollectType.value = collectType;
  modalInterval.value = interval;
  const [hh, mm] = (time || "09:00").split(":");
  modalHour.value   = String(parseInt(hh, 10)).padStart(2, "0");
  modalMinute.value = (["00","10","20","30","40","50"].includes(mm) ? mm : "00");
  hideLawDropdown();
  updateDaySelector(interval, day);
  const sw = window.innerWidth - document.documentElement.clientWidth;
  document.body.style.overflow = "hidden";
  document.body.style.paddingRight = `${sw}px`;
  lawModal.style.display = "flex";
  setTimeout(() => modalLawName.focus(), 30);
}

function closeModal() {
  lawModal.style.display = "none";
  document.body.style.overflow = "";
  document.body.style.paddingRight = "";
  editingLawId = null;
  hideLawDropdown();
}

modalClose.addEventListener("click", closeModal);
modalCancel.addEventListener("click", closeModal);
lawModal.addEventListener("click", e => { if (e.target === lawModal) closeModal(); });

modalSave.addEventListener("click", async () => {
  const name        = modalLawName.value.trim();
  const interval    = modalInterval.value;
  const day         = selectedDay || null;
  const time        = `${modalHour.value}:${modalMinute.value}`;
  const collectType = modalCollectType.value;
  if (!name) { modalLawName.focus(); return; }

  modalSave.disabled = true;
  try {
    const url    = editingLawId ? `/api/scheduler/laws/${editingLawId}` : "/api/scheduler/laws";
    const method = editingLawId ? "PUT" : "POST";
    const res    = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, interval, day, time, collect_type: collectType }),
    });
    if (!res.ok) {
      const d = await res.json();
      throw new Error(d.detail || "저장 오류");
    }
    closeModal();
    await loadLaws();
  } catch (e) {
    alert(`저장 실패: ${e.message}`);
  } finally {
    modalSave.disabled = false;
  }
});

addLawBtn.addEventListener("click", () => openModal());

/* ── 추천 법령 모달 ── */
const presetLawBtn        = document.getElementById("presetLawBtn");
const presetModal         = document.getElementById("presetModal");
const presetModalClose    = document.getElementById("presetModalClose");
const presetCancel        = document.getElementById("presetCancel");
const presetAdd           = document.getElementById("presetAdd");
const presetList          = document.getElementById("presetList");
const presetInterval      = document.getElementById("presetInterval");
const presetWeekdayPicker = document.getElementById("presetWeekdayPicker");
const presetMonthdayPicker= document.getElementById("presetMonthdayPicker");
const presetCountLabel    = document.getElementById("presetCount");
const presetHour          = document.getElementById("presetHour");
const presetMinute        = document.getElementById("presetMinute");

// 날짜 옵션 초기화
for (let d = 1; d <= 31; d++) {
  const opt = document.createElement("option");
  opt.value = String(d); opt.textContent = `${d}일`;
  presetMonthdayPicker.appendChild(opt);
}

// 시간 옵션 초기화
for (let h = 0; h < 24; h++) {
  const opt = document.createElement("option");
  opt.value = String(h).padStart(2, "0");
  opt.textContent = `${String(h).padStart(2, "0")}시`;
  if (h === 9) opt.selected = true;
  presetHour.appendChild(opt);
}

let presetSelectedDay = "월";
let presetSelectedNames = new Set();

presetInterval.addEventListener("change", () => {
  const iv = presetInterval.value;
  if (iv === "weekly") {
    presetWeekdayPicker.style.display = "flex";
    presetMonthdayPicker.style.display = "none";
    presetSelectedDay = presetWeekdayPicker.querySelector(".weekday-btn.active")?.dataset.day || "월";
  } else if (iv === "monthly") {
    presetWeekdayPicker.style.display = "none";
    presetMonthdayPicker.style.display = "block";
    presetSelectedDay = presetMonthdayPicker.value;
  } else {
    presetWeekdayPicker.style.display = "none";
    presetMonthdayPicker.style.display = "none";
    presetSelectedDay = null;
  }
});

presetWeekdayPicker.querySelectorAll(".weekday-btn").forEach(btn =>
  btn.addEventListener("click", () => {
    presetWeekdayPicker.querySelectorAll(".weekday-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    presetSelectedDay = btn.dataset.day;
  }));

presetMonthdayPicker.addEventListener("change", () => { presetSelectedDay = presetMonthdayPicker.value; });

function updatePresetCount() {
  const n = presetSelectedNames.size;
  presetCountLabel.textContent = n ? `${n}개 선택됨` : "";
}

async function openPresetModal() {
  presetSelectedNames.clear();
  try {
    const [pRes, lRes] = await Promise.all([
      fetch("/api/scheduler/presets"),
      fetch("/api/scheduler/laws"),
    ]);
    const { presets } = await pRes.json();
    const { laws }    = await lRes.json();
    const existing    = new Set((laws || []).map(l => l.name));

    const grouped = {};
    (presets || []).forEach(p => {
      if (!grouped[p.category]) grouped[p.category] = [];
      grouped[p.category].push(p);
    });

    presetList.innerHTML = Object.entries(grouped).map(([cat, items]) => `
      <div>
        <div class="preset-category-title">${esc(cat)}</div>
        <div class="preset-items">
          ${items.map(item => {
            const added = existing.has(item.name);
            return `<button type="button"
              class="preset-chip ${added ? "preset-chip-added" : ""}"
              data-name="${esc(item.name)}"
              ${added ? "disabled" : ""}>
              ${added ? "✓ " : ""}${esc(item.name)}
            </button>`;
          }).join("")}
        </div>
      </div>`).join("");

    presetList.querySelectorAll(".preset-chip:not(.preset-chip-added)").forEach(chip =>
      chip.addEventListener("click", () => {
        const name = chip.dataset.name;
        if (presetSelectedNames.has(name)) {
          presetSelectedNames.delete(name);
          chip.classList.remove("preset-chip-selected");
        } else {
          presetSelectedNames.add(name);
          chip.classList.add("preset-chip-selected");
        }
        updatePresetCount();
      }));

    updatePresetCount();
    const sw = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.overflow = "hidden";
    document.body.style.paddingRight = `${sw}px`;
    presetModal.style.display = "flex";
  } catch (e) {
    alert("추천 법령 목록을 불러오지 못했습니다.");
  }
}

function closePresetModal() {
  presetModal.style.display = "none";
  document.body.style.overflow = "";
  document.body.style.paddingRight = "";
  presetSelectedNames.clear();
}

presetLawBtn.addEventListener("click", openPresetModal);
presetModalClose.addEventListener("click", closePresetModal);
presetCancel.addEventListener("click", closePresetModal);
presetModal.addEventListener("click", e => { if (e.target === presetModal) closePresetModal(); });

presetAdd.addEventListener("click", async () => {
  if (!presetSelectedNames.size) { alert("선택된 법령이 없습니다."); return; }
  const interval = presetInterval.value;
  const day      = interval !== "daily" ? presetSelectedDay : null;
  const time     = `${presetHour.value}:${presetMinute.value}`;

  presetAdd.disabled = true;
  let success = 0;
  for (const name of presetSelectedNames) {
    try {
      const res = await fetch("/api/scheduler/laws", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, interval, day, time }),
      });
      if (res.ok) success++;
    } catch {}
  }
  presetAdd.disabled = false;
  closePresetModal();
  await loadLaws();
  if (success) alert(`${success}개 법령이 추가되었습니다.`);
});

/* ── 수집 이력 ── */
let allLogs = [], logPage = 1;

async function loadLogs() {
  try {
    const res  = await fetch("/api/scheduler/logs");
    const data = await res.json();
    allLogs = data.logs || [];
    logPage = 1;
    renderLogPage();
  } catch (e) {
    logList.innerHTML = `<div class="empty-msg">불러오기 실패: ${esc(e.message)}</div>`;
  }
}

function renderLogPage() {
  const start = (logPage - 1) * LOG_PAGE_SIZE;
  renderLogList(allLogs.slice(start, start + LOG_PAGE_SIZE));
  renderPagination(
    document.getElementById("logPagination"),
    allLogs.length, logPage, LOG_PAGE_SIZE,
    p => { logPage = p; renderLogPage(); }
  );
}

function renderLogList(logs) {
  if (!logs.length) {
    logList.innerHTML = '<div class="empty-msg">수집 이력이 없습니다.</div>';
    return;
  }
  logList.innerHTML = logs.map(log => {
    const status = log.status || "idle";
    const badge  = `<span class="status-badge status-${esc(status)}">${esc(STATUS_LABEL[status] || status)}</span>`;
    const time   = log.started_at ? log.started_at.replace("T", " ") : "-";
    const count  = log.count != null ? `<span class="log-count">${log.count}건</span>` : "";
    return `
      <div class="log-item">
        <div class="log-item-header">
          ${badge}
          <span class="log-law-name">${esc(log.law_name || "-")}</span>
          ${count}
          <span class="log-time">${esc(time)}</span>
        </div>
        ${log.message ? `<div class="log-message">${esc(log.message)}</div>` : ""}
      </div>`;
  }).join("");
}

refreshLogsBtn.addEventListener("click", loadLogs);

loadLaws();
loadLogs();
loadNotifications();

/* ════════════════════════════════
   법률판례질의 탭
   ════════════════════════════════ */
const lawprecChatEl   = document.getElementById("lawprecChat");
const lawprecWelcome  = document.getElementById("lawprecWelcome");
const lawprecForm     = document.getElementById("lawprecForm");
const lawprecInput    = document.getElementById("lawprecInput");
const lawprecBtn      = document.getElementById("lawprecBtn");

let lawprecBusy = false;

const lpSendIcon = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 19V5M5 12l7-7 7 7"/></svg>`;

function lpAppendMessage(role, text, { loading = false, error = false } = {}) {
  if (lawprecWelcome) lawprecWelcome.remove();

  const wrap = document.createElement("div");
  wrap.className = `message ${role}${error ? " error" : ""}`;

  const label = document.createElement("div");
  label.className = "message-label";
  label.textContent = role === "user" ? "나" : "법률판례 AI";

  const bubble = document.createElement("div");
  bubble.className = `bubble${loading ? " loading" : ""}`;
  bubble.textContent = text;

  wrap.append(label, bubble);
  lawprecChatEl.appendChild(wrap);
  lawprecChatEl.scrollTop = lawprecChatEl.scrollHeight;
  return bubble;
}

async function lpSendMessage(text) {
  const message = text.trim();
  if (!message || lawprecBusy) return;

  lpAppendMessage("user", message);
  lawprecInput.value = "";
  lawprecInput.style.height = "auto";
  lawprecBusy = true;
  lawprecBtn.disabled = true;
  lawprecInput.disabled = true;

  const bubble = lpAppendMessage("assistant", "", { loading: true });
  bubble.innerHTML = '<span class="typing-dots"><span></span><span></span><span></span></span>';
  lawprecBtn.innerHTML = '<div class="chat-btn-spinner"></div>';

  try {
    await lpStreamChat(message, bubble);
    linkifyCaseNums(bubble);
  } catch (err) {
    bubble.classList.remove("loading");
    bubble.closest(".message").classList.add("error");
    bubble.textContent = err.message || "요청 중 오류가 발생했습니다.";
  } finally {
    lawprecBusy = false;
    lawprecBtn.disabled = false;
    lawprecBtn.innerHTML = lpSendIcon;
    lawprecInput.disabled = false;
    lawprecInput.focus();
  }
}

async function lpStreamChat(message, bubble) {
  const res = await fetch("/api/lawprec/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "스트리밍 오류");
  }

  bubble.classList.remove("loading");
  bubble.textContent = "";

  const reader  = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const payload = line.slice(6).trim();
      if (payload === "[DONE]") return;
      try {
        const data = JSON.parse(payload);
        if (data.error) throw new Error(data.error);
        if (data.token) {
          bubble.textContent += data.token;
          lawprecChatEl.scrollTop = lawprecChatEl.scrollHeight;
        }
      } catch (e) {
        if (e.message && e.message !== "Unexpected end of JSON input") throw e;
      }
    }
  }
}

lawprecForm.addEventListener("submit", (e) => {
  e.preventDefault();
  lpSendMessage(lawprecInput.value);
});

lawprecInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    lpSendMessage(lawprecInput.value);
  }
});

lawprecInput.addEventListener("input", () => {
  lawprecInput.style.height = "auto";
  lawprecInput.style.height = Math.min(lawprecInput.scrollHeight, 160) + "px";
});

document.querySelectorAll(".lawprec-chip").forEach(chip => {
  chip.addEventListener("click", () => lpSendMessage(chip.dataset.msg));
});

lawprecChatEl.addEventListener("click", async (e) => {
  const btn = e.target.closest(".prec-link");
  if (!btn || btn.disabled) return;
  const caseNo = btn.dataset.no;
  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "검색 중…";
  try {
    const res  = await fetch(`/api/prec/search?q=${encodeURIComponent(caseNo)}&display=3`);
    const data = await res.json();
    const prec = (data.precs || []).find(p => (p["사건번호"] || "").includes(caseNo))
              || (data.precs || [])[0];
    if (!prec) { alert(`"${caseNo}" 판례를 찾을 수 없습니다.`); return; }
    const precId = prec["판례정보일련번호"] || prec["판례일련번호"];
    openDetailPage("prec", precId, prec["사건명"] || caseNo);
  } catch {
    alert("판례 조회 중 오류가 발생했습니다.");
  } finally {
    btn.disabled = false;
    btn.textContent = origText;
  }
});

/* ════════════════════════════════
   알림 탭
   ════════════════════════════════ */
const notifList       = document.getElementById("notifList");
const notifEmpty      = document.getElementById("notifEmpty");
const notifBadge      = document.getElementById("notifBadge");
const markAllReadBtn  = document.getElementById("markAllReadBtn");
const clearAllNotifsBtn = document.getElementById("clearAllNotifsBtn");
const notifSummaryEl  = document.getElementById("notifSummary");
const notifFiltersEl  = document.getElementById("notifFilters");

let notifAllData     = [];
let notifActiveFilter = "all";

async function loadNotifications() {
  try {
    const res  = await fetch("/api/notifications");
    const data = await res.json();
    renderNotifications(data.notifications || []);
  } catch { /* silent */ }
}

function formatNotifTime(dateStr) {
  if (!dateStr) return "";
  const now = new Date();
  const todayStr = now.toISOString().slice(0, 10);
  const yest = new Date(now); yest.setDate(yest.getDate() - 1);
  const yesterdayStr = yest.toISOString().slice(0, 10);
  const dStr = dateStr.slice(0, 10);
  const hm  = dateStr.slice(11, 16);
  if (dStr === todayStr) return hm;
  if (dStr === yesterdayStr) return `어제 ${hm}`;
  return `${dateStr.slice(5, 10).replace("-", "/")} ${hm}`;
}

function groupNotifsByDate(notifs) {
  const now = new Date();
  const todayStr = now.toISOString().slice(0, 10);
  const yest = new Date(now); yest.setDate(yest.getDate() - 1);
  const yesterdayStr = yest.toISOString().slice(0, 10);
  const groups = new Map();
  notifs.forEach(n => {
    const dStr = (n.created_at || "").slice(0, 10);
    let label = dStr === todayStr ? "오늘"
               : dStr === yesterdayStr ? "어제"
               : dStr ? dStr.slice(0, 7).replace("-", "년 ") + "월" : "이전";
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(n);
  });
  return groups;
}

function renderNotifSummaryAndFilters(notifs) {
  const TYPE_LABELS = { 개정: "개정", 신규: "신규", 판례: "판례", 실패: "실패", 삭제: "삭제" };

  if (!notifs.length) {
    notifSummaryEl.style.display = "none";
    notifFiltersEl.style.display = "none";
    return;
  }

  const counts = {}, unreadCounts = {};
  notifs.forEach(n => {
    counts[n.type] = (counts[n.type] || 0) + 1;
    if (!n.read) unreadCounts[n.type] = (unreadCounts[n.type] || 0) + 1;
  });
  const types = Object.keys(counts);

  notifSummaryEl.style.display = "flex";
  notifSummaryEl.innerHTML = types.map(type => {
    const unread = unreadCounts[type] || 0;
    const unreadBadge = unread > 0 ? `<span class="badge-unread">${unread} 미읽음</span>` : "";
    return `<div class="notif-summary-badge type-${type}">
      <span>${TYPE_LABELS[type] || type}</span>
      <span class="badge-count">${counts[type]}</span>
      ${unreadBadge}
    </div>`;
  }).join("");

  notifFiltersEl.style.display = "flex";
  notifFiltersEl.innerHTML = `<button class="notif-filter-btn${notifActiveFilter === "all" ? " active" : ""}" data-type="all">전체 ${notifs.length}</button>`
    + types.map(type =>
      `<button class="notif-filter-btn type-${type}${notifActiveFilter === type ? " active" : ""}" data-type="${type}">${TYPE_LABELS[type] || type} ${counts[type]}</button>`
    ).join("");

  notifFiltersEl.querySelectorAll(".notif-filter-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      notifActiveFilter = btn.dataset.type;
      renderNotifications(notifAllData);
    });
  });
}

function renderNotifications(notifs) {
  notifAllData = notifs;

  const unread = notifs.filter(n => !n.read).length;

  if (unread > 0) {
    notifBadge.textContent = unread > 99 ? "99+" : String(unread);
    notifBadge.style.display = "inline-flex";
  } else {
    notifBadge.style.display = "none";
  }

  const notifTab = document.querySelector('.tab[data-tab="notifications"]');
  notifTab.style.color = unread > 0 ? "#7ca3ff" : "";

  renderNotifSummaryAndFilters(notifs);

  const filtered = notifActiveFilter === "all" ? notifs : notifs.filter(n => n.type === notifActiveFilter);

  notifList.innerHTML = "";

  if (!filtered.length) {
    notifList.innerHTML = '<div class="empty-msg">알림이 없습니다.</div>';
    return;
  }

  const TYPE_LABELS = { 개정: "개정", 신규: "신규", 판례: "판례", 실패: "실패", 삭제: "삭제" };
  const groups = groupNotifsByDate(filtered);

  groups.forEach((groupNotifs, label) => {
    const groupEl = document.createElement("div");
    groupEl.className = "notif-group";
    groupEl.innerHTML = `<div class="notif-group-label">${label}</div>`;

    groupNotifs.forEach(n => {
      const card = document.createElement("div");
      card.className = `notif-card type-${n.type}${n.read ? "" : " unread"}`;
      card.dataset.id = n.id;

      const hasPreview = n.preview && (n.preview.rows?.length || n.preview.items?.length);
      const previewHtml = hasPreview ? buildPreviewHtml(n.preview) : "";

      card.innerHTML = `
        <div class="notif-card-top">
          <span class="notif-type-badge type-${n.type}">${TYPE_LABELS[n.type] || n.type}</span>
          <span class="notif-title">${esc(n.title)}</span>
          <div class="notif-card-meta">
            ${!n.read ? '<span class="notif-unread-dot"></span>' : ""}
            <span class="notif-time">${formatNotifTime(n.created_at)}</span>
            <button class="notif-delete-btn" title="삭제">✕</button>
          </div>
        </div>
        <div class="notif-desc">${esc(n.body)}</div>
        ${hasPreview ? `<button class="notif-preview-btn">▼ 자세히 보기</button>
        <div class="notif-preview" style="display:none">${previewHtml}</div>` : ""}
      `;

      if (hasPreview) {
        const btn   = card.querySelector(".notif-preview-btn");
        const panel = card.querySelector(".notif-preview");
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const open = panel.style.display === "none";
          panel.style.display = open ? "block" : "none";
          btn.textContent = open ? "▲ 접기" : "▼ 자세히 보기";
        });
      }

      card.addEventListener("click", async (e) => {
        if (e.target.closest(".notif-delete-btn") || e.target.closest(".notif-preview-btn")) return;
        if (n.read) return;
        await fetch(`/api/notifications/${n.id}/read`, { method: "POST" });
        n.read = true;
        card.classList.remove("unread");
        const dot = card.querySelector(".notif-unread-dot");
        if (dot) dot.remove();
        loadNotifications();
      });

      card.querySelector(".notif-delete-btn").addEventListener("click", async (e) => {
        e.stopPropagation();
        await fetch(`/api/notifications/${n.id}`, { method: "DELETE" });
        card.remove();
        loadNotifications();
      });

      groupEl.appendChild(card);
    });

    notifList.appendChild(groupEl);
  });
}

function buildPreviewHtml(preview) {
  if (preview.rows?.length) {
    const rows = preview.rows.map(r =>
      `<div class="notif-preview-row">
        <span class="notif-preview-label">${esc(r.label)}</span>
        <span class="notif-preview-value">${esc(r.value)}</span>
      </div>`
    ).join("");
    return `<div class="notif-preview-rows">${rows}</div>`;
  }
  if (preview.items?.length) {
    const items = preview.items.map(p =>
      `<div class="notif-preview-case">
        <div class="notif-case-name">${esc(p.name)}</div>
        <div class="notif-case-meta">${esc(p.no)} · ${esc(p.court)} · ${esc(p.date)}</div>
      </div>`
    ).join("");
    return `<div class="notif-preview-cases">${items}</div>`;
  }
  return "";
}

markAllReadBtn.addEventListener("click", async () => {
  await fetch("/api/notifications/read-all", { method: "POST" });
  loadNotifications();
});

clearAllNotifsBtn.addEventListener("click", async () => {
  if (!confirm("알림을 모두 삭제하시겠습니까?")) return;
  await fetch("/api/notifications", { method: "DELETE" });
  loadNotifications();
});


/* ════════════════════════════════
   전체화면 상세 페이지 (통합검색)
   ════════════════════════════════ */
const detailPage     = document.getElementById("detailPage");
const detailPageBack = document.getElementById("detailPageBack");
const detailPageTitle = document.getElementById("detailPageTitle");
const detailPageBody  = document.getElementById("detailPageBody");

detailPageBack.addEventListener("click", () => history.back());
document.addEventListener("keydown", e => { if (e.key === "Escape" && detailPage.classList.contains("open")) history.back(); });

// 상세 페이지 내부 내비게이션 스택
const _detailHistory = [];
let _detailCurrentPrecData = null;

window.addEventListener("popstate", () => {
  if (panelEl.classList.contains("open")) {
    closePanel();
    return;
  }
  if (!detailPage.classList.contains("open")) return;
  closeDetailPage();
});

function openDetailPage(type, id, title) {
  _detailHistory.length = 0;
  _detailCurrentPrecData = null;
  detailPageTitle.textContent = title;
  detailPageBody.innerHTML = '<div class="state-msg"><span class="spinner"></span>불러오는 중...</div>';
  detailPage.classList.add("open");
  history.pushState({ detailOpen: true }, "");
  window.scrollTo(0, 0);

  const url = type === "law"
    ? `/api/law/${encodeURIComponent(id)}`
    : `/api/prec/${encodeURIComponent(id)}`;

  fetch(url)
    .then(r => r.json())
    .then(data => {
      if (type === "law") {
        renderArticles(detailPageBody, data);
      } else {
        _detailCurrentPrecData = data;
        renderPrecDetail(detailPageBody, data);
      }
    })
    .catch(e => {
      detailPageBody.innerHTML = `<div class="state-msg error">${esc(e.message)}</div>`;
    });
}

function closeDetailPage() {
  detailPage.classList.remove("open");
  _detailHistory.length = 0;
  _detailCurrentPrecData = null;
}

async function pushDetailPage(lawName, joNum, joSub) {
  const prevTitle = detailPageTitle.textContent;
  const precData  = _detailCurrentPrecData;

  _detailHistory.push({
    title: prevTitle,
    restore: () => {
      _detailCurrentPrecData = precData;
      renderPrecDetail(detailPageBody, precData);
    },
  });
  history.pushState({ detailOpen: true, depth: _detailHistory.length }, "");

  const joText = `제${joNum}조${joSub ? `의${joSub}` : ""}`;
  detailPageTitle.textContent = `${lawName} ${joText}`;
  detailPageBody.innerHTML = '<div class="state-msg"><span class="spinner"></span>불러오는 중...</div>';

  try {
    const res  = await fetch(`/api/law/article?law_name=${encodeURIComponent(lawName)}&jo=${joNum}&jo_sub=${joSub}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "조회 오류");
    const articles = data.articles || [];
    detailPageTitle.textContent = data.searched_law_name || lawName;
    detailPageBody.innerHTML = articles.length
      ? filterArticles(articles).map(buildArticleHtml).join("")
      : '<div class="state-msg">조문 내용이 없습니다.</div>';
  } catch (e) {
    detailPageBody.innerHTML = `<div class="state-msg error">${esc(e.message)}</div>`;
  }
}

/* ════════════════════════════════
   통합 검색 탭
   ════════════════════════════════ */
const unifiedForm    = document.getElementById("unifiedForm");
const unifiedInput   = document.getElementById("unifiedInput");
const unifiedBtn     = document.getElementById("unifiedBtn");
const unifiedResults = document.getElementById("unifiedResults");

unifiedForm.addEventListener("submit", e => {
  e.preventDefault();
  const q = unifiedInput.value.trim();
  if (q) searchUnified(q);
});

async function searchUnified(q) {
  unifiedBtn.disabled = true;
  unifiedResults.innerHTML = '<div class="state-msg"><span class="spinner"></span>검색 중...</div>';

  try {
    const [lawRes, precRes] = await Promise.all([
      fetch(`/api/law/search?q=${encodeURIComponent(q)}&display=5`),
      fetch(`/api/prec/search?q=${encodeURIComponent(q)}&display=5`),
    ]);
    const [lawData, precData] = await Promise.all([lawRes.json(), precRes.json()]);
    renderUnifiedResults(q, lawData, precData);
  } catch (e) {
    unifiedResults.innerHTML = `<div class="state-msg error">${esc(e.message)}</div>`;
  } finally {
    unifiedBtn.disabled = false;
  }
}

function renderUnifiedResults(q, lawData, precData) {
  const laws  = lawData.laws  || [];
  const precs = precData.precs || [];

  if (!laws.length && !precs.length) {
    unifiedResults.innerHTML = `<div class="state-msg">"${esc(q)}" 검색 결과가 없습니다.</div>`;
    return;
  }

  const lawSection = laws.length ? `
    <div class="unified-section-header">
      <span class="unified-section-title">법령</span>
      <div class="unified-section-right">
        <span class="unified-section-count">${(lawData.total_cnt || 0).toLocaleString()}건</span>
        ${(lawData.total_cnt || 0) > 5 ? `<button class="unified-view-all-btn" data-type="law">전체보기 →</button>` : ""}
      </div>
    </div>
    <div class="unified-law-cards">${laws.map(l => buildCard(l)).join("")}</div>` : "";

  const precSection = precs.length ? `
    <div class="unified-section-header" style="${laws.length ? "margin-top:1.5rem" : ""}">
      <span class="unified-section-title">판례</span>
      <div class="unified-section-right">
        <span class="unified-section-count">${(precData.total_cnt || 0).toLocaleString()}건</span>
        ${(precData.total_cnt || 0) > 5 ? `<button class="unified-view-all-btn" data-type="prec">전체보기 →</button>` : ""}
      </div>
    </div>
    <div class="unified-prec-cards">${precs.map(p => buildPrecCard(p)).join("")}</div>` : "";

  unifiedResults.innerHTML = lawSection + precSection;

  unifiedResults.querySelectorAll(".unified-view-all-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      if (btn.dataset.type === "law") {
        searchInput.value = q;
        window.location.hash = "search";
        search(q);
      } else {
        precInput.value = q;
        window.location.hash = "prec";
        searchPrec(q);
      }
    });
  });

  unifiedResults.querySelectorAll(".unified-law-cards .law-card").forEach(card => {
    card.addEventListener("click", () =>
      openDetailPage("law", card.dataset.id, card.querySelector(".card-title")?.textContent || card.dataset.id)
    );
  });
  unifiedResults.querySelectorAll(".unified-prec-cards .law-card").forEach(card => {
    card.addEventListener("click", () =>
      openDetailPage("prec", card.dataset.id, card.querySelector(".card-title")?.textContent || card.dataset.id)
    );
  });
}

/* ── Shared utils ── */
function fmtDate(raw) {
  const s = String(raw || "").replace(/\D/g, "");
  if (s.length === 8) return `${s.slice(0,4)}.${s.slice(4,6)}.${s.slice(6,8)}`;
  return raw || "";
}

function esc(str) {
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
