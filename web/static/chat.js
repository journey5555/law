/* ── Tab switching ── */
const VALID_TABS = ["search", "prec", "chat", "scheduler", "ragtest", "unified", "notifications", "lawprec", "analysis", "keyword"];
let lawLoaded  = false;
let precLoaded = false;
let summarizeEnabled = false;

fetch("/api/health").then(r => r.json()).then(d => { summarizeEnabled = !!d.summarize_enabled; }).catch(() => {});

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
  if (name === "scheduler") {
    switchBatchSubTab(sessionStorage.getItem("batchSubTab") || "law");
  }
  if (name === "notifications") { loadNotifications(); }
  if (name === "ragtest") { loadRagtestLaws(); }
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
          `<button class="law-link-btn" data-law="${esc(c.lawName)}" data-jo="${c.joNum}" data-jo-sub="${c.joSub}" data-ho="${(c.hoNums||[]).join(",")}">
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
  const toolbar = summarizeText && summarizeEnabled
    ? `<div class="card-detail-toolbar"><button class="btn-summarize">AI 요약</button></div>`
    : "";

  container.innerHTML = toolbar + (html || '<div class="state-msg">상세 내용이 없습니다.</div>');

  container.querySelectorAll(".law-link-btn").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      openArticlePanel(btn.dataset.law, Number(btn.dataset.jo), Number(btn.dataset.joSub), btn.dataset.ho);
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
  let raw = String(refArticles || "");
  raw = raw.replace(/<([^>]{1,80}(?:법|령|규칙|예규|조례|지침|규정))>/g, "$1 ");
  const text = stripHtml(raw);
  const results = [];
  const seen = new Set();

  // 토큰 추출: 법령명, 제N조(의M), 제N항, 제N호
  const lawRe  = /(?:[가-힣]+(?:\s+|·))*[가-힣]+(?:법|령|규칙|예규|조례|지침|규정)/g;
  const joRe   = /제(\d+)조(?:의(\d+))?/g;
  const hangRe = /제(\d+)항/g;
  const hoRe   = /제(\d+)호/g;

  // 모든 토큰을 위치 기준으로 정렬
  const tokens = [];
  for (const m of text.matchAll(lawRe))  tokens.push({ type: "law",  pos: m.index, name: m[0].trim() });
  for (const m of text.matchAll(joRe))   tokens.push({ type: "jo",   pos: m.index, num: +m[1], sub: m[2] ? +m[2] : 0 });
  for (const m of text.matchAll(hangRe)) tokens.push({ type: "hang", pos: m.index, num: +m[1] });
  for (const m of text.matchAll(hoRe))   tokens.push({ type: "ho",   pos: m.index, num: +m[1] });
  tokens.sort((a, b) => a.pos - b.pos);

  let curLaw = "", curJo = 0, curJoSub = 0, curHangNums = [], curHoNums = [];

  function flush() {
    if (!curLaw || !curJo) return;
    let joText = `제${curJo}조${curJoSub ? `의${curJoSub}` : ""}`;
    if (curHangNums.length) joText += " " + curHangNums.map(h => `제${h}항`).join(", ");
    if (curHoNums.length)   joText += " " + curHoNums.map(h => `제${h}호`).join(", ");
    const key = `${curLaw}|${curJo}|${curJoSub}|${curHangNums}|${curHoNums}`;
    if (!seen.has(key)) {
      seen.add(key);
      results.push({ lawName: curLaw, joText, joNum: curJo, joSub: curJoSub, hoNums: [...curHoNums] });
    }
  }

  for (const tok of tokens) {
    if (tok.type === "law") {
      flush();
      curLaw = tok.name; curJo = 0; curJoSub = 0; curHangNums = []; curHoNums = [];
    } else if (tok.type === "jo") {
      flush();
      curJo = tok.num; curJoSub = tok.sub; curHangNums = []; curHoNums = [];
    } else if (tok.type === "hang") {
      curHangNums.push(tok.num);
    } else if (tok.type === "ho") {
      curHoNums.push(tok.num);
    }
  }
  flush();
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

async function openArticlePanel(lawName, joNum, joSub = 0, hoStr = "") {
  const hoFilter = hoStr ? hoStr.split(",").map(Number).filter(Boolean) : [];
  panelLawName.textContent = lawName;
  let titleText = `제${joNum}조${joSub ? `의${joSub}` : ""}`;
  if (hoFilter.length) titleText += " " + hoFilter.map(h => `제${h}호`).join(", ");
  panelJoTitle.textContent = titleText;
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

    panelContent.innerHTML = filterArticles(articles).map(art => buildArticleHtml(art, hoFilter)).join("");

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

function linkifyLawNames(bubble) {
  if (!ragtestLaws.length) return;
  for (const lawName of ragtestLaws) {
    const walker = document.createTreeWalker(bubble, NodeFilter.SHOW_TEXT);
    const nodes = [];
    let node;
    while ((node = walker.nextNode())) nodes.push(node);
    for (const textNode of nodes) {
      if (!textNode.textContent.includes(lawName)) continue;
      const parts = textNode.textContent.split(lawName);
      const frag = document.createDocumentFragment();
      parts.forEach((p, i) => {
        frag.appendChild(document.createTextNode(p));
        if (i < parts.length - 1) {
          const btn = document.createElement("button");
          btn.className = "law-ref-link";
          btn.dataset.lawName = lawName;
          btn.textContent = lawName;
          frag.appendChild(btn);
        }
      });
      textNode.parentNode.replaceChild(frag, textNode);
    }
  }
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

function buildArticleHtml(art, hoFilter = []) {
  const num   = art["조문번호"] || "";
  const title = art["조문제목"] || "";
  let rawHangs = art["항"];
  const hangs = Array.isArray(rawHangs) ? rawHangs : (rawHangs && typeof rawHangs === "object" ? [rawHangs] : []);

  let body = "";

  if (hangs.length > 0) {
    body = hangs.map(hang => {
      const hangContent = String(hang["항내용"] || "").trim();
      let rawHos = hang["호"];
      let hos = Array.isArray(rawHos) ? rawHos : (rawHos && typeof rawHos === "object" ? [rawHos] : []);
      // 호 필터가 있으면 해당 호만 표시
      if (hoFilter.length > 0 && hos.length > 0) {
        hos = hos.filter(ho => {
          const hoNum = parseInt(String(ho["호번호"] || "").replace(/\D/g, ""));
          return hoFilter.includes(hoNum);
        });
      }
      const hoHtml = hos.map(ho =>
        `<div class="ho-item">${esc(String(ho["호내용"] || "").trim())}</div>`
      ).join("");
      return `<div class="hang-item">${hangContent ? esc(hangContent) : ""}${hoHtml}</div>`;
    }).join("");
  }

  if (!body) {
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
   수집 관리 탭 — 서브탭 전환
   ════════════════════════════════ */
function switchBatchSubTab(sub) {
  document.querySelectorAll(".batch-sub-tab").forEach(b =>
    b.classList.toggle("active", b.dataset.sub === sub));
  document.getElementById("batch-sub-law").style.display  = sub === "law"  ? "flex" : "none";
  document.getElementById("batch-sub-prec").style.display = sub === "prec" ? "flex" : "none";
  sessionStorage.setItem("batchSubTab", sub);
  if (sub === "law")  { loadLawBatchConfig();  loadLawBatchLogs();  }
  if (sub === "prec") { loadPrecBatchConfig(); loadPrecBatchLogs(); }
}

document.querySelectorAll(".batch-sub-tab").forEach(btn =>
  btn.addEventListener("click", () => switchBatchSubTab(btn.dataset.sub)));

/* ════════════════════════════════
   법령 수집 탭 (Law Batch)
   ════════════════════════════════ */
const PAGE_SIZE = 10;
const LOG_PAGE_SIZE = 5;

function renderBatchPagination(containerId, total, page, pageSize, onPage) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const totalPages = Math.ceil(total / pageSize);
  if (totalPages <= 1) { el.innerHTML = ""; return; }

  // 현재 페이지 중심으로 최대 5개 번호 윈도우
  const WINDOW = 5;
  let start = Math.max(1, page - Math.floor(WINDOW / 2));
  let end   = start + WINDOW - 1;
  if (end > totalPages) { end = totalPages; start = Math.max(1, end - WINDOW + 1); }

  const pages = [];
  for (let i = start; i <= end; i++) pages.push(i);

  const btn = (p, label, disabled, active = false) =>
    `<button class="page-btn${active ? " active" : ""}" ${disabled ? "disabled" : ""} data-p="${p}">${label}</button>`;

  el.innerHTML =
    btn(1,           "«", page <= 1) +
    btn(page - 1,   "‹", page <= 1) +
    pages.map(p => btn(p, p, false, p === page)).join("") +
    btn(page + 1,   "›", page >= totalPages) +
    btn(totalPages, "»", page >= totalPages);

  el.querySelectorAll(".page-btn:not([disabled])").forEach(b =>
    b.addEventListener("click", () => onPage(+b.dataset.p)));
}

/* --- 법령 배치 --- */
let allLawBatchLaws = [], lawBatchLawPage = 1;
let allLawBatchLogs = [], lawBatchLogPage = 1;

async function loadLawBatchConfig() {
  try {
    const res  = await fetch("/api/batch/law/config");
    const data = await res.json();
    const el = document.getElementById("lawBatchRunTime");
    if (el) el.value = data.run_time || "02:00";
    allLawBatchLaws = data.laws || [];
    lawBatchLawPage = 1;
    renderLawBatchLawPage();
  } catch (e) {
    const el = document.getElementById("lawBatchLawList");
    if (el) el.innerHTML = `<div class="empty-msg">불러오기 실패: ${esc(e.message)}</div>`;
  }
}

function renderLawBatchLawPage() {
  const start = (lawBatchLawPage - 1) * PAGE_SIZE;
  const page  = allLawBatchLaws.slice(start, start + PAGE_SIZE);
  renderLawBatchLawList(page, allLawBatchLaws.length);
  renderBatchPagination("lawBatchLawPagination", allLawBatchLaws.length, lawBatchLawPage, PAGE_SIZE, p => {
    lawBatchLawPage = p; renderLawBatchLawPage();
  });
}

function renderLawBatchLawList(laws, total = laws.length) {
  const countEl = document.getElementById("lawBatchLawCount");
  if (countEl) countEl.textContent = total ? `${total}건` : "";
  const el = document.getElementById("lawBatchLawList");
  if (!el) return;
  if (!laws.length) {
    el.innerHTML = '<div class="empty-msg">수집 대상 법령이 없습니다.</div>';
    return;
  }
  el.innerHTML = laws.map(law => {
    const active   = law.active !== false;
    const uploaded = law.last_knowledge_upload ? law.last_knowledge_upload.slice(0, 16) : "-";
    const efDate   = law.last_enforcement_date || "-";
    const cls = !active ? "status-failed" : (law.last_knowledge_upload ? "status-success" : "status-pending");
    const txt = !active ? "폐지감지" : (law.last_knowledge_upload ? "수집완료" : "미수집");
    return `
      <div class="law-card${!active ? " law-card-inactive" : ""}">
        <div class="law-card-top">
          <span class="law-card-name">${esc(law.name)}</span>
          <div style="display:flex;align-items:center;gap:0.5rem">
            <span class="status-badge ${cls}">${txt}</span>
            <button class="btn-delete law-batch-law-del" data-name="${esc(law.name)}">삭제</button>
          </div>
        </div>
        <div class="law-card-meta">
          <span class="law-meta-item"><span class="law-meta-label">시행일자</span><span>${esc(efDate)}</span></span>
          <span class="law-meta-item"><span class="law-meta-label">최근 업로드</span><span>${esc(uploaded)}</span></span>
        </div>
      </div>`;
  }).join("");
  el.querySelectorAll(".law-batch-law-del").forEach(btn =>
    btn.addEventListener("click", () => deleteLawBatchLaw(btn.dataset.name)));
}

async function deleteLawBatchLaw(name) {
  if (!confirm(`"${name}"을(를) 수집 목록에서 삭제하시겠습니까?`)) return;
  try {
    const res = await fetch(`/api/batch/law/laws/${encodeURIComponent(name)}`, { method: "DELETE" });
    if (!res.ok) throw new Error("삭제 오류");
    const saved = lawBatchLawPage;
    const data  = await (await fetch("/api/batch/law/config")).json();
    const el = document.getElementById("lawBatchRunTime");
    if (el) el.value = data.run_time || "02:00";
    allLawBatchLaws = data.laws || [];
    lawBatchLawPage = Math.min(saved, Math.max(1, Math.ceil(allLawBatchLaws.length / PAGE_SIZE)));
    renderLawBatchLawPage();
  } catch (e) { alert(`삭제 실패: ${e.message}`); }
}

document.getElementById("saveLawBatchTimeBtn")?.addEventListener("click", async () => {
  const t = document.getElementById("lawBatchRunTime")?.value;
  if (!t) return;
  try {
    const res = await fetch("/api/batch/law/config/run-time", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_time: t }),
    });
    if (!res.ok) throw new Error("저장 오류");
    const savedEl = document.getElementById("lawBatchTimeSaved");
    if (savedEl) { savedEl.style.display = "inline"; setTimeout(() => { savedEl.style.display = "none"; }, 2000); }
  } catch (e) { alert(`저장 실패: ${e.message}`); }
});

document.getElementById("loadLawDefaultsBtn")?.addEventListener("click", async () => {
  if (!confirm("고용노동부 소관 법령 전체(약 142건)를 수집 목록에 추가합니다.")) return;
  const btn = document.getElementById("loadLawDefaultsBtn");
  btn.disabled = true; btn.textContent = "불러오는 중...";
  try {
    const res  = await fetch("/api/batch/law/laws/load-defaults", { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "오류");
    await loadLawBatchConfig();
    alert(`${data.added_count}건 추가되었습니다. (전체 ${data.total}건)`);
  } catch (e) { alert(`실패: ${e.message}`); }
  finally { btn.disabled = false; btn.textContent = "고용노동부 법령 전체 불러오기"; }
});

document.getElementById("runLawBatchNowBtn")?.addEventListener("click", async () => {
  if (!confirm("지금 바로 법령 수집 배치를 실행하시겠습니까?")) return;
  const btn = document.getElementById("runLawBatchNowBtn");
  const statusEl = document.getElementById("lawBatchRunStatus");
  btn.disabled = true; btn.textContent = "실행중...";
  if (statusEl) { statusEl.style.display = "block"; statusEl.textContent = "배치 실행 중입니다..."; statusEl.className = "batch-run-status running"; }
  try {
    const res  = await fetch("/api/batch/law/run", { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "실행 오류");
    if (statusEl) {
      statusEl.textContent = `완료: 전체 ${data.total}건, 변동 ${data.changed}건, 오류 ${data.errors}건 (${data.elapsed_sec || 0}초)`;
      statusEl.className = "batch-run-status done";
    }
    await loadLawBatchConfig(); await loadLawBatchLogs();
  } catch (e) {
    if (statusEl) { statusEl.textContent = `실패: ${e.message}`; statusEl.className = "batch-run-status error"; }
  } finally { btn.disabled = false; btn.textContent = "지금 실행"; }
});

document.getElementById("addLawBatchLawBtn")?.addEventListener("click", () => {
  const form = document.getElementById("addLawBatchLawForm");
  if (!form) return;
  form.style.display = form.style.display === "none" ? "flex" : "none";
  if (form.style.display === "flex") document.getElementById("lawBatchLawNameInput")?.focus();
});
document.getElementById("cancelAddLawBatchLawBtn")?.addEventListener("click", () => {
  const form = document.getElementById("addLawBatchLawForm");
  if (form) form.style.display = "none";
  const inp = document.getElementById("lawBatchLawNameInput");
  if (inp) inp.value = "";
});
document.getElementById("confirmAddLawBatchLawBtn")?.addEventListener("click", async () => {
  const inp  = document.getElementById("lawBatchLawNameInput");
  const name = inp?.value.trim();
  if (!name) { inp?.focus(); return; }
  try {
    const res  = await fetch("/api/batch/law/laws", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ names: [name] }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "추가 오류");
    const form = document.getElementById("addLawBatchLawForm");
    if (form) form.style.display = "none";
    if (inp) inp.value = "";
    const d2 = await (await fetch("/api/batch/law/config")).json();
    const timeEl = document.getElementById("lawBatchRunTime");
    if (timeEl) timeEl.value = d2.run_time || "02:00";
    allLawBatchLaws = d2.laws || [];
    lawBatchLawPage = Math.ceil(allLawBatchLaws.length / PAGE_SIZE) || 1;
    renderLawBatchLawPage();
  } catch (e) { alert(`추가 실패: ${e.message}`); }
});
document.getElementById("lawBatchLawNameInput")?.addEventListener("keydown", e => {
  if (e.key === "Enter")  document.getElementById("confirmAddLawBatchLawBtn")?.click();
  if (e.key === "Escape") document.getElementById("cancelAddLawBatchLawBtn")?.click();
});

async function loadLawBatchLogs() {
  const el = document.getElementById("lawBatchLogList");
  if (!el) return;
  try {
    const data = await (await fetch("/api/batch/law/logs")).json();
    allLawBatchLogs = data.logs || [];
    lawBatchLogPage = 1;
    renderLawBatchLogPage();
  } catch (e) { el.innerHTML = `<div class="empty-msg">불러오기 실패: ${esc(e.message)}</div>`; }
}

function renderLawBatchLogPage() {
  const start = (lawBatchLogPage - 1) * LOG_PAGE_SIZE;
  renderBatchLogList("lawBatchLogList", allLawBatchLogs.slice(start, start + LOG_PAGE_SIZE));
  renderBatchPagination("lawBatchLogPagination", allLawBatchLogs.length, lawBatchLogPage, LOG_PAGE_SIZE, p => {
    lawBatchLogPage = p; renderLawBatchLogPage();
  });
}

document.getElementById("refreshLawBatchLogsBtn")?.addEventListener("click", loadLawBatchLogs);

/* --- 판례 배치 (법령 목록은 법령 탭과 공유) --- */
let allPrecBatchLaws = [], precBatchLawPage = 1;
let allPrecBatchLogs = [], precBatchLogPage = 1;

async function loadPrecBatchConfig() {
  try {
    const res  = await fetch("/api/batch/prec/config");
    const data = await res.json();
    const el = document.getElementById("precBatchRunTime");
    if (el) el.value = data.run_time || "03:00";
    allPrecBatchLaws = data.laws || [];
    precBatchLawPage = 1;
    renderPrecBatchLawPage();
  } catch (e) {
    const el = document.getElementById("precBatchLawList");
    if (el) el.innerHTML = `<div class="empty-msg">불러오기 실패: ${esc(e.message)}</div>`;
  }
}

function renderPrecBatchLawPage() {
  const start = (precBatchLawPage - 1) * PAGE_SIZE;
  const page  = allPrecBatchLaws.slice(start, start + PAGE_SIZE);
  renderPrecBatchLawList(page, allPrecBatchLaws.length);
  renderBatchPagination("precBatchLawPagination", allPrecBatchLaws.length, precBatchLawPage, PAGE_SIZE, p => {
    precBatchLawPage = p; renderPrecBatchLawPage();
  });
}

function renderPrecBatchLawList(laws, total = laws.length) {
  const countEl = document.getElementById("precBatchLawCount");
  if (countEl) {
    const totalPrecs    = allPrecBatchLaws.reduce((s, l) => s + (Number(l.last_prec_count)  || 0), 0);
    const totalUploaded = allPrecBatchLaws.reduce((s, l) => s + (Number(l.uploaded_count) || 0), 0);
    countEl.textContent = totalPrecs
      ? `총 ${totalPrecs.toLocaleString()}건 · 업로드 ${totalUploaded.toLocaleString()}건`
      : (total ? `${total}개 법령` : "");
  }
  const el = document.getElementById("precBatchLawList");
  if (!el) return;
  if (!laws.length) {
    el.innerHTML = '<div class="empty-msg">수집 대상 법령이 없습니다.</div>';
    return;
  }
  el.innerHTML = laws.map(law => {
    const cnt      = law.last_prec_count != null ? `${Number(law.last_prec_count).toLocaleString()}건` : "-";
    const uploaded = law.last_prec_knowledge_upload ? law.last_prec_knowledge_upload.slice(0, 16) : "-";
    const upCnt    = law.uploaded_count != null ? Number(law.uploaded_count).toLocaleString() : "0";
    const totalCnt  = Number(law.last_prec_count) || 0;
    const uploadCnt = Number(law.uploaded_count) || 0;
    const cls = !law.last_prec_knowledge_upload ? "status-pending"
              : uploadCnt >= totalCnt ? "status-success" : "status-failed";
    const txt = !law.last_prec_knowledge_upload ? "미수집"
              : uploadCnt >= totalCnt ? "수집완료" : "수집중";
    return `
      <div class="law-card">
        <div class="law-card-top">
          <span class="law-card-name">${esc(law.name)}</span>
          <div style="display:flex;align-items:center;gap:0.5rem">
            <span class="status-badge ${cls}">${txt}</span>
            <button class="btn-delete prec-batch-law-del" data-name="${esc(law.name)}">삭제</button>
          </div>
        </div>
        <div class="law-card-meta">
          <span class="law-meta-item"><span class="law-meta-label">총 판례</span><span>${cnt}</span></span>
          <span class="law-meta-item"><span class="law-meta-label">Knowledge 업로드</span><span>${upCnt}건</span></span>
          <span class="law-meta-item"><span class="law-meta-label">최근 수집</span><span>${esc(uploaded)}</span></span>
        </div>
      </div>`;
  }).join("");
  el.querySelectorAll(".prec-batch-law-del").forEach(btn =>
    btn.addEventListener("click", () => deletePrecBatchLaw(btn.dataset.name)));
}

async function deletePrecBatchLaw(name) {
  if (!confirm(`"${name}"을(를) 판례 수집 목록에서 삭제하시겠습니까?`)) return;
  try {
    const res = await fetch(`/api/batch/prec/laws/${encodeURIComponent(name)}`, { method: "DELETE" });
    if (!res.ok) throw new Error("삭제 오류");
    await loadPrecBatchConfig();
  } catch (e) { alert(`삭제 실패: ${e.message}`); }
}

document.getElementById("addPrecBatchLawBtn")?.addEventListener("click", () => {
  const form = document.getElementById("addPrecBatchLawForm");
  form.style.display = form.style.display === "none" ? "flex" : "none";
  if (form.style.display === "flex") document.getElementById("precBatchLawNameInput")?.focus();
});

document.getElementById("cancelAddPrecBatchLawBtn")?.addEventListener("click", () => {
  const form = document.getElementById("addPrecBatchLawForm");
  if (form) form.style.display = "none";
});

document.getElementById("confirmAddPrecBatchLawBtn")?.addEventListener("click", async () => {
  const input = document.getElementById("precBatchLawNameInput");
  const name  = input?.value.trim();
  if (!name) return;
  try {
    const res = await fetch("/api/batch/prec/laws", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ names: [name] }),
    });
    if (!res.ok) throw new Error("추가 실패");
    input.value = "";
    const form = document.getElementById("addPrecBatchLawForm");
    if (form) form.style.display = "none";
    await loadPrecBatchConfig();
  } catch (e) { alert(`추가 실패: ${e.message}`); }
});

document.getElementById("savePrecBatchTimeBtn")?.addEventListener("click", async () => {
  const t = document.getElementById("precBatchRunTime")?.value;
  if (!t) return;
  try {
    const res = await fetch("/api/batch/prec/config/run-time", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_time: t }),
    });
    if (!res.ok) throw new Error("저장 오류");
    const savedEl = document.getElementById("precBatchTimeSaved");
    if (savedEl) { savedEl.style.display = "inline"; setTimeout(() => { savedEl.style.display = "none"; }, 2000); }
  } catch (e) { alert(`저장 실패: ${e.message}`); }
});

let precBatchPollTimer = null;

function startPrecBatchPolling() {
  stopPrecBatchPolling();
  precBatchPollTimer = setInterval(async () => {
    try {
      const res = await fetch("/api/batch/prec/status");
      const data = await res.json();
      if (!data.running) {
        stopPrecBatchPolling();
        const btn = document.getElementById("runPrecBatchNowBtn");
        const cancelBtn = document.getElementById("cancelPrecBatchBtn");
        const statusEl = document.getElementById("precBatchRunStatus");
        if (btn) { btn.disabled = false; btn.textContent = "지금 실행"; }
        if (cancelBtn) cancelBtn.style.display = "none";
        if (statusEl) { statusEl.textContent = "배치 완료"; statusEl.className = "batch-run-status done"; }
        await loadPrecBatchConfig();
        await loadPrecBatchLogs();
      } else {
        await loadPrecBatchConfig();
      }
    } catch {}
  }, 10000);
}

function stopPrecBatchPolling() {
  if (precBatchPollTimer) { clearInterval(precBatchPollTimer); precBatchPollTimer = null; }
}

document.getElementById("runPrecBatchNowBtn")?.addEventListener("click", async () => {
  if (!confirm("지금 바로 판례 수집 배치를 실행하시겠습니까? 백그라운드에서 실행됩니다.")) return;
  const btn = document.getElementById("runPrecBatchNowBtn");
  const cancelBtn = document.getElementById("cancelPrecBatchBtn");
  const statusEl = document.getElementById("precBatchRunStatus");
  try {
    const res  = await fetch("/api/batch/prec/run", { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "실행 오류");
    btn.disabled = true; btn.textContent = "실행중...";
    if (cancelBtn) cancelBtn.style.display = "inline-flex";
    if (statusEl) { statusEl.style.display = "block"; statusEl.textContent = "백그라운드에서 실행 중입니다."; statusEl.className = "batch-run-status running"; }
    startPrecBatchPolling();
  } catch (e) {
    if (statusEl) { statusEl.style.display = "block"; statusEl.textContent = `실패: ${e.message}`; statusEl.className = "batch-run-status error"; }
  }
});

document.getElementById("cancelPrecBatchBtn")?.addEventListener("click", async () => {
  try {
    await fetch("/api/batch/prec/cancel", { method: "POST" });
    const statusEl = document.getElementById("precBatchRunStatus");
    if (statusEl) { statusEl.textContent = "중지 요청됨 — 현재 배치 완료 후 중단됩니다."; statusEl.className = "batch-run-status error"; }
  } catch (e) { alert(`중지 실패: ${e.message}`); }
});

async function loadPrecBatchLogs() {
  const el = document.getElementById("precBatchLogList");
  if (!el) return;
  try {
    const data = await (await fetch("/api/batch/prec/logs")).json();
    allPrecBatchLogs = data.logs || [];
    precBatchLogPage = 1;
    renderPrecBatchLogPage();
  } catch (e) { el.innerHTML = `<div class="empty-msg">불러오기 실패: ${esc(e.message)}</div>`; }
}

function renderPrecBatchLogPage() {
  const start = (precBatchLogPage - 1) * LOG_PAGE_SIZE;
  renderBatchLogList("precBatchLogList", allPrecBatchLogs.slice(start, start + LOG_PAGE_SIZE));
  renderBatchPagination("precBatchLogPagination", allPrecBatchLogs.length, precBatchLogPage, LOG_PAGE_SIZE, p => {
    precBatchLogPage = p; renderPrecBatchLogPage();
  });
}

document.getElementById("refreshPrecBatchLogsBtn")?.addEventListener("click", loadPrecBatchLogs);

document.getElementById("hardDeleteBtn")?.addEventListener("click", async () => {
  const input = document.getElementById("hardDeleteInput");
  const resultEl = document.getElementById("hardDeleteResult");
  const id = input?.value.trim();
  if (!id) return;
  if (!confirm(`Datasource "${id}"를 영구 삭제합니다.\n벡터 데이터 포함 복구 불가능합니다. 계속하시겠습니까?`)) return;
  resultEl.style.display = "block";
  resultEl.textContent = "삭제 중...";
  resultEl.className = "batch-run-status running";
  try {
    const res = await fetch(`/api/knowledge/hard-delete/${encodeURIComponent(id)}`, { method: "DELETE" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "삭제 실패");
    resultEl.textContent = `삭제 완료: ${id}`;
    resultEl.className = "batch-run-status done";
    input.value = "";
  } catch (e) {
    resultEl.textContent = `실패: ${e.message}`;
    resultEl.className = "batch-run-status error";
  }
});

/* --- 공통 로그 렌더러 --- */
function renderBatchLogList(listId, logs) {
  const el = document.getElementById(listId);
  if (!el) return;
  if (!logs.length) {
    el.innerHTML = '<div class="empty-msg">배치 실행 이력이 없습니다.</div>';
    return;
  }
  el.innerHTML = logs.map(log => {
    const errors  = log.errors || 0;
    const cls     = errors > 0 ? "status-failed" : "status-success";
    const label   = errors > 0 ? "오류있음" : "완료";
    const elapsed = log.elapsed_sec != null ? `${log.elapsed_sec}초` : "";
    const allResults   = log.results || [];
    const errorItems   = allResults.filter(r => r.status === "error");
    const changedItems = allResults.filter(r => r.status !== "error" && r.status !== "비활성" && r.message !== "변동없음");
    const errorDetail  = errorItems.map(r =>
      `<span class="batch-log-result-item batch-log-err">⚠ ${esc(r.name)}: ${esc(r.message || r.status)}</span>`
    ).join("");
    const changedDetail = changedItems.slice(0, 5).map(r =>
      `<span class="batch-log-result-item batch-log-ok">${esc(r.name)}: ${esc(r.message || r.status)}</span>`
    ).join("");
    const more   = changedItems.length > 5 ? `<span class="batch-log-more">수집 완료 외 ${changedItems.length - 5}건</span>` : "";
    const detail = errorDetail + changedDetail;
    return `
      <div class="log-item">
        <div class="log-item-header">
          <span class="status-badge ${cls}">${label}</span>
          <span class="log-time">${esc(log.started_at || "-")}</span>
          <span class="log-count">전체 ${log.total}건 &middot; 변동 ${log.changed}건 &middot; 오류 ${errors}건</span>
          ${elapsed ? `<span class="log-elapsed">${esc(elapsed)}</span>` : ""}
        </div>
        ${detail || more ? `<div class="batch-log-results">${detail}${more}</div>` : ""}
      </div>`;
  }).join("");
}

loadNotifications();

/* ════════════════════════════════
   RAG 테스트 탭
   ════════════════════════════════ */

let ragtestLaws = [];
let ragtestLawPage = 1;

async function loadRagtestLaws() {
  const listEl = document.getElementById("ragtestLawList");
  if (!listEl) return;
  listEl.innerHTML = '<div class="empty-msg"><span class="spinner"></span> 불러오는 중...</div>';
  try {
    const res  = await fetch("/api/test/laws");
    const data = await res.json();
    ragtestLaws = data.laws || [];
    ragtestLawPage = 1;
    renderRagtestLawPage();
  } catch {
    listEl.innerHTML = '<div class="empty-msg state-msg error">불러오기 실패</div>';
  }
}

function renderRagtestLawPage() {
  const listEl = document.getElementById("ragtestLawList");
  if (!listEl) return;
  if (!ragtestLaws.length) {
    listEl.innerHTML = '<div class="empty-msg">수집 관리 탭에서 법령을 먼저 추가하세요.</div>';
    renderBatchPagination("ragtestLawPagination", 0, 1, PAGE_SIZE, () => {});
    return;
  }
  const start = (ragtestLawPage - 1) * PAGE_SIZE;
  const page  = ragtestLaws.slice(start, start + PAGE_SIZE);
  listEl.innerHTML = page.map(name => `
    <div class="law-card">
      <div class="law-card-top">
        <span class="law-card-name">${esc(name)}</span>
      </div>
      <div class="law-card-actions">
        <button class="btn-secondary ragtest-collect-btn" data-law="${esc(name)}" data-type="law">법령 수집</button>
        <button class="btn-secondary ragtest-collect-btn" data-law="${esc(name)}" data-type="prec">판례 수집</button>
      </div>
    </div>
  `).join("");
  listEl.querySelectorAll(".ragtest-collect-btn").forEach(btn => {
    btn.addEventListener("click", () => ragtestCollect(btn.dataset.law, btn.dataset.type));
  });
  renderBatchPagination("ragtestLawPagination", ragtestLaws.length, ragtestLawPage, PAGE_SIZE, p => {
    ragtestLawPage = p; renderRagtestLawPage();
  });
}

function ragtestAppendLog(message, status) {
  const logEl = document.getElementById("ragtestLog");
  if (!logEl) return;
  const line = document.createElement("div");
  line.className = "ragtest-log-line";
  line.innerHTML = `<span class="ragtest-log-dot ${esc(status || "start")}"></span><span>${esc(message)}</span>`;
  logEl.appendChild(line);
  logEl.parentElement.scrollTop = logEl.parentElement.scrollHeight;
}

async function ragtestCollect(lawName, type) {
  const escapedName = CSS.escape(lawName);
  const btns = document.querySelectorAll(`.ragtest-collect-btn[data-law="${escapedName}"]`);
  btns.forEach(b => { b.disabled = true; });
  const logEl = document.getElementById("ragtestLog");
  if (logEl) {
    const sep = document.createElement("div");
    sep.className = "ragtest-log-sep";
    sep.textContent = `── ${lawName} ${type === "law" ? "법령" : "판례"} 수집`;
    logEl.appendChild(sep);
  }
  try {
    const res = await fetch(`/api/test/collect/${type}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({law_name: lawName}),
    });
    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const raw = line.slice(6).trim();
        if (raw === "[DONE]") break;
        try { const msg = JSON.parse(raw); ragtestAppendLog(msg.message, msg.status); } catch {}
      }
    }
  } catch (e) {
    ragtestAppendLog(`연결 오류: ${e.message}`, "error");
  } finally {
    btns.forEach(b => { b.disabled = false; });
  }
}

document.getElementById("ragtestRefreshBtn")?.addEventListener("click", loadRagtestLaws);
document.getElementById("ragtestClearLogBtn")?.addEventListener("click", () => {
  const logEl = document.getElementById("ragtestLog");
  if (logEl) logEl.innerHTML = "";
});

const ragtestChatEl  = document.getElementById("ragtestChat");
const ragtestWelcome = document.getElementById("ragtestWelcome");
const ragtestForm    = document.getElementById("ragtestForm");
const ragtestInput   = document.getElementById("ragtestInput");
const ragtestBtn     = document.getElementById("ragtestBtn");
let ragtestBusy = false;
const rtSendIcon = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 19V5M5 12l7-7 7 7"/></svg>`;

function ragtestAppendMsg(role, text, loading = false) {
  if (ragtestWelcome && ragtestWelcome.parentElement) ragtestWelcome.remove();
  const wrap   = document.createElement("div");
  wrap.className = `message ${role}`;
  const label  = document.createElement("div");
  label.className = "message-label";
  label.textContent = role === "user" ? "나" : "AI";
  const bubble = document.createElement("div");
  bubble.className = `bubble${loading ? " loading" : ""}`;
  bubble.textContent = text;
  wrap.append(label, bubble);
  ragtestChatEl.appendChild(wrap);
  ragtestChatEl.scrollTop = ragtestChatEl.scrollHeight;
  return bubble;
}

async function ragtestSend(message) {
  message = message.trim();
  if (!message || ragtestBusy) return;
  ragtestInput.value = "";
  ragtestInput.style.height = "auto";
  ragtestBusy = true;
  ragtestBtn.disabled = true;
  ragtestInput.disabled = true;
  ragtestBtn.innerHTML = '<div class="chat-btn-spinner"></div>';
  ragtestAppendMsg("user", message);
  const bubble = ragtestAppendMsg("assistant", "", true);
  bubble.innerHTML = '<span class="typing-dots"><span></span><span></span><span></span></span>';
  try {
    const res = await fetch("/api/test/chat/stream", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({message}),
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || "스트리밍 오류");
    }
    bubble.classList.remove("loading");
    bubble.textContent = "";
    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const raw = line.slice(6).trim();
        if (raw === "[DONE]") break;
        try {
          const data = JSON.parse(raw);
          if (data.error) throw new Error(data.error);
          if (data.token) { bubble.textContent += data.token; ragtestChatEl.scrollTop = ragtestChatEl.scrollHeight; }
        } catch (e) { if (e.message && e.message !== "Unexpected end of JSON input") throw e; }
      }
    }
    linkifyCaseNums(bubble);
    linkifyLawNames(bubble);
  } catch (e) {
    bubble.classList.remove("loading");
    bubble.closest(".message").classList.add("error");
    bubble.textContent = e.message || "요청 중 오류가 발생했습니다.";
  } finally {
    ragtestBusy = false;
    ragtestBtn.disabled = false;
    ragtestBtn.innerHTML = rtSendIcon;
    ragtestInput.disabled = false;
    ragtestInput.focus();
  }
}

ragtestForm?.addEventListener("submit", e => { e.preventDefault(); ragtestSend(ragtestInput.value); });
ragtestInput?.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ragtestSend(ragtestInput.value); }
});
ragtestInput?.addEventListener("input", () => {
  ragtestInput.style.height = "auto";
  ragtestInput.style.height = Math.min(ragtestInput.scrollHeight, 160) + "px";
});

ragtestChatEl?.addEventListener("click", async e => {
  const precBtn = e.target.closest(".prec-link");
  if (precBtn && !precBtn.disabled) {
    const caseNo  = precBtn.dataset.no;
    const origTxt = precBtn.textContent;
    precBtn.disabled  = true;
    precBtn.textContent = "검색 중…";
    try {
      const res  = await fetch(`/api/prec/search?q=${encodeURIComponent(caseNo)}&display=3`);
      const data = await res.json();
      const prec = (data.precs || []).find(p => (p["사건번호"] || "").includes(caseNo)) || (data.precs || [])[0];
      if (!prec) { alert(`"${caseNo}" 판례를 찾을 수 없습니다.`); return; }
      openDetailPage("prec", prec["판례정보일련번호"] || prec["판례일련번호"], prec["사건명"] || caseNo);
    } catch {
      alert("판례 조회 중 오류가 발생했습니다.");
    } finally {
      precBtn.disabled  = false;
      precBtn.textContent = origTxt;
    }
    return;
  }

  const lawBtn = e.target.closest(".law-ref-link");
  if (lawBtn && !lawBtn.disabled) {
    const lawName = lawBtn.dataset.lawName;
    const origTxt = lawBtn.textContent;
    lawBtn.disabled = true;
    lawBtn.textContent = "검색 중…";
    try {
      const res  = await fetch(`/api/law/search?q=${encodeURIComponent(lawName)}&display=5`);
      const data = await res.json();
      const laws = data.laws || [];
      const law  = laws.find(l => l["법령명한글"] === lawName) || laws[0];
      if (!law) { alert(`"${lawName}" 법령을 찾을 수 없습니다.`); return; }
      openDetailPage("law", String(law["법령ID"]), law["법령명한글"] || lawName);
    } catch {
      alert("법령 조회 중 오류가 발생했습니다.");
    } finally {
      lawBtn.disabled = false;
      lawBtn.textContent = origTxt;
    }
  }
});

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

/* ════════════════════════════════
   판례 분석 탭
   ════════════════════════════════ */
const analysisForm      = document.getElementById("analysisForm");
const analysisInput     = document.getElementById("analysisInput");
const analysisBtn       = document.getElementById("analysisBtn");
const analysisResult    = document.getElementById("analysisResult");
const analysisAiText    = document.getElementById("analysisAiText");
const analysisPrecBlock = document.getElementById("analysisPrecBlock");
const analysisPrecCards = document.getElementById("analysisPrecCards");

let analysisBusy = false;

async function runAnalysis(question) {
  if (!question.trim() || analysisBusy) return;
  analysisBusy = true;
  analysisBtn.disabled = true;
  analysisBtn.textContent = "분석 중...";

  analysisResult.style.display = "none";
  analysisAiText.textContent = "";
  analysisPrecCards.innerHTML = "";

  try {
    analysisPrecCards.innerHTML = '<div class="state-msg"><span class="spinner"></span>판례 검색 중...</div>';
    analysisResult.style.display = "block";

    // 에이전트 스트리밍 호출
    const res = await fetch("/api/lawprec/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: question }),
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || "에이전트 오류");
    }

    analysisAiText.textContent = "";
    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    outer: while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop() || "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const payload = line.slice(6).trim();
        if (payload === "[DONE]") break outer;
        try {
          const d = JSON.parse(payload);
          if (d.error) throw new Error(d.error);
          if (d.token) analysisAiText.textContent += d.token;
        } catch (e) {
          if (e.message !== "Unexpected end of JSON input") throw e;
        }
      }
    }

    // JSON 파싱: [{case_no, prec_id}, ...]
    let precList = [];
    try {
      const raw = analysisAiText.textContent.trim();
      const jsonStr = raw.slice(raw.indexOf("["), raw.lastIndexOf("]") + 1);
      precList = JSON.parse(jsonStr);
    } catch { precList = []; }

    // prec_id 기준 중복 제거
    const seen = new Set();
    precList = precList.filter(item => {
      const id = item.prec_id || item.case_no || "";
      if (!id || seen.has(id)) return false;
      seen.add(id);
      return true;
    });

    if (precList.length === 0) {
      analysisPrecCards.innerHTML = '<div class="state-msg">AI 응답에서 사건번호를 찾을 수 없습니다.</div>';
    } else {
      analysisPrecCards.innerHTML = `<div class="state-msg"><span class="spinner"></span>판례 ${precList.length}건 조회 중...</div>`;

      const cards = (await Promise.all(
        precList.map(async item => {
          const precId = item.prec_id || item.case_no;
          if (!precId) return null;
          try {
            const dr     = await fetch(`/api/prec/${encodeURIComponent(precId)}`);
            const detail = await dr.json();
            // meta는 detail에서 조합
            const meta = {
              "사건번호": detail.case_no || item.case_no || "",
              "사건명":   detail.case_name || "",
              "법원명":   detail.court || "",
              "선고일자": detail.date || "",
              "판례정보일련번호": precId,
            };
            return { meta, detail };
          } catch { return null; }
        })
      )).filter(Boolean);

      analysisPrecCards.innerHTML = "";
      cards.forEach(({ meta, detail }, idx) =>
        analysisPrecCards.appendChild(buildAnalysisPrecCard(meta, detail, idx + 1))
      );
    }

  } catch (err) {
    analysisPrecCards.innerHTML = `<div class="state-msg">${err.message || "오류가 발생했습니다."}</div>`;
  } finally {
    analysisBusy = false;
    analysisBtn.disabled = false;
    analysisBtn.textContent = "분석";
  }
}

function buildAnalysisPrecCard(meta, detail, index) {
  const card    = document.createElement("div");
  card.className = "analysis-prec-card";

  const caseNo   = meta["사건번호"] || "";
  const caseName = detail.case_name || meta["사건명"] || caseNo;
  const court    = meta["법원명"] || "";
  const date     = String(meta["선고일자"] || "");
  const rawSummary = detail.summary ? stripHtml(detail.summary) : "";
  const summary  = rawSummary.length > 220 ? rawSummary.slice(0, 220) + "…" : rawSummary;

  let refHtml = "";
  if (detail.ref_articles) {
    const citations = extractCitations(detail.ref_articles);
    if (citations.length) {
      refHtml = `<div class="analysis-prec-refs">
        <div class="analysis-prec-refs-label">참조조문</div>
        <div class="law-links">${citations.map(c =>
          `<button class="law-link-btn" data-law="${esc(c.lawName)}" data-jo="${c.joNum}" data-jo-sub="${c.joSub}" data-ho="${(c.hoNums||[]).join(",")}">${esc(c.lawName)} ${esc(c.joText)}</button>`
        ).join("")}</div>
      </div>`;
    }
  }

  card.innerHTML = `
    <div class="analysis-prec-card-header">
      ${court ? `<span class="analysis-prec-court">${esc(court)}</span>` : ""}
      ${date  ? `<span class="analysis-prec-date">${esc(date)}</span>` : ""}
    </div>
    <div class="analysis-prec-card-body">
      <div class="analysis-prec-caseno">${index != null ? `<span class="analysis-prec-index">${index}</span>` : ""}${esc(caseNo)}</div>
      <div class="analysis-prec-name">${esc(caseName)}</div>
      ${summary ? `<div class="analysis-prec-summary">${esc(summary)}</div>` : ""}
    </div>
    ${refHtml}
    <div class="analysis-prec-card-footer">
      <button class="analysis-prec-detail-btn">전체 보기</button>
    </div>`;

  card.querySelectorAll(".law-link-btn").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      openArticlePanel(btn.dataset.law, Number(btn.dataset.jo), Number(btn.dataset.joSub), btn.dataset.ho);
    });
  });

  const precId = meta["판례정보일련번호"] || meta["판례일련번호"];
  card.querySelector(".analysis-prec-detail-btn").addEventListener("click", () => {
    closePanel();
    openDetailPage("prec", precId, caseName);
  });

  return card;
}

analysisForm.addEventListener("submit", e => {
  e.preventDefault();
  runAnalysis(analysisInput.value);
});

analysisInput.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); runAnalysis(analysisInput.value); }
});

analysisInput.addEventListener("input", () => {
  analysisInput.style.height = "auto";
  analysisInput.style.height = Math.min(analysisInput.scrollHeight, 200) + "px";
});

document.querySelectorAll(".analysis-chip").forEach(chip => {
  chip.addEventListener("click", () => {
    analysisInput.value = chip.dataset.msg;
    analysisInput.style.height = "auto";
    analysisInput.style.height = Math.min(analysisInput.scrollHeight, 200) + "px";
    runAnalysis(chip.dataset.msg);
  });
});


/* ════════════════════════════════
   키워드 검색 테스트 탭
   ════════════════════════════════ */
const keywordForm      = document.getElementById("keywordForm");
const keywordInput     = document.getElementById("keywordInput");
const keywordBtn       = document.getElementById("keywordBtn");
const keywordExtracted = document.getElementById("keywordExtracted");
const keywordTags      = document.getElementById("keywordTags");
const keywordResult    = document.getElementById("keywordResult");
const keywordPrecCards = document.getElementById("keywordPrecCards");

let keywordBusy = false;
let keywordAllCards = [];
let keywordPage = 1;
const KEYWORD_PAGE_SIZE = 5;

async function runKeywordSearch(question) {
  if (!question.trim() || keywordBusy) return;
  keywordBusy = true;
  keywordBtn.disabled = true;
  keywordBtn.textContent = "추출 중...";

  keywordExtracted.style.display = "none";
  keywordTags.innerHTML = "";
  keywordResult.style.display = "none";
  keywordPrecCards.innerHTML = "";

  try {
    // 1단계: 키워드 추출 (invoke)
    const res = await fetch("/api/keyword/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: question }),
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || "키워드 추출 오류");
    }
    const resData = await res.json();

    let extracted = {};
    try {
      const raw = (resData.content || "").trim();
      const jsonStr = raw.slice(raw.indexOf("{"), raw.lastIndexOf("}") + 1);
      extracted = JSON.parse(jsonStr);
    } catch { throw new Error("키워드 추출 결과를 파싱할 수 없습니다."); }

    const topic   = extracted.topic || "";
    const hypo    = extracted.hypothesis || "";
    let queries = extracted.queries || [];

    // 키워드 태그 표시
    keywordTags.innerHTML =
      (topic ? `<span class="keyword-tag"><span class="keyword-tag-label">T</span>${esc(topic)}</span>` : "") +
      (hypo  ? `<span class="keyword-tag"><span class="keyword-tag-label">H</span>${esc(hypo)}</span>` : "") +
      queries.map(q => `<span class="keyword-tag"><span class="keyword-tag-label">Q</span>${esc(q)}</span>`).join("");
    keywordExtracted.style.display = "flex";

    // 조사·시점 표현 제거
    const NOISE = /\s*(전|후|시|중|때|의|에|을|를|이|가|은|는|로|과|와|및)\s*/g;
    queries = queries.map(q => q.replace(NOISE, " ").trim()).filter(q => q.length >= 2);

    if (queries.length === 0) {
      keywordResult.style.display = "block";
      keywordPrecCards.innerHTML = '<div class="state-msg">추출된 검색어가 없습니다.</div>';
      return;
    }

    // 2단계: hypothesis 본문 검색 + queries 판례명 검색 (병렬)
    keywordBtn.textContent = "검색 중...";
    keywordResult.style.display = "block";
    keywordPrecCards.innerHTML = '<div class="state-msg"><span class="spinner"></span>판례 검색 중...</div>';

    const searchPromises = [];
    // 원본 질문 → 본문 검색 (search=2)
    searchPromises.push(
      fetch(`/api/prec/search?q=${encodeURIComponent(question)}&display=15&search=2`)
        .then(r => r.ok ? r.json() : { precs: [] })
        .then(d => d.precs || [])
        .catch(() => [])
    );
    // hypothesis → 본문 검색 (search=2)
    if (hypo && hypo !== question) {
      searchPromises.push(
        fetch(`/api/prec/search?q=${encodeURIComponent(hypo)}&display=15&search=2`)
          .then(r => r.ok ? r.json() : { precs: [] })
          .then(d => d.precs || [])
          .catch(() => [])
      );
    }
    // topic + queries 중복 제거 후 판례명 검색 (search=1)
    const searchTerms = [...new Set([topic, ...queries].filter(Boolean))];
    for (const q of searchTerms) {
      searchPromises.push(
        fetch(`/api/prec/search?q=${encodeURIComponent(q)}&display=15`)
          .then(r => r.ok ? r.json() : { precs: [] })
          .then(d => d.precs || [])
          .catch(() => [])
      );
    }
    const searchResults = await Promise.all(searchPromises);

    // 합산 + 중복 제거 (판례ID 없는 항목 제외)
    const seen = new Set();
    const allPrecs = [];
    for (const precs of searchResults) {
      for (const p of precs) {
        const pid = String(p["판례정보일련번호"] || p["판례일련번호"] || p["판례ID"] || "");
        if (pid && pid !== "undefined" && pid !== "null" && !seen.has(pid)) {
          seen.add(pid);
          allPrecs.push(p);
        }
      }
    }

    if (allPrecs.length === 0) {
      keywordPrecCards.innerHTML = '<div class="state-msg">검색 결과가 없습니다.</div>';
      return;
    }

    // 3단계: 상세 조회
    keywordPrecCards.innerHTML = `<div class="state-msg"><span class="spinner"></span>판례 ${allPrecs.length}건 상세 조회 중...</div>`;

    const cards = (await Promise.all(
      allPrecs.map(async meta => {
        let precId = meta["판례정보일련번호"] || meta["판례일련번호"] || meta["판례ID"];
        try {
          // precId 없으면 사건번호로 재검색
          if (!precId) {
            const caseNo = meta["사건번호"] || meta["사건명"] || "";
            if (!caseNo) return null;
            const sr = await fetch(`/api/prec/search?q=${encodeURIComponent(caseNo)}&display=3`);
            const sd = await sr.json();
            const found = (sd.precs || []).find(p => (p["사건번호"] || "").includes(caseNo)) || sd.precs?.[0];
            if (!found) return null;
            precId = found["판례정보일련번호"] || found["판례일련번호"];
            if (!precId) return null;
            Object.assign(meta, found);
          }
          const dr     = await fetch(`/api/prec/${encodeURIComponent(precId)}`);
          const detail = await dr.json();
          return { meta, detail };
        } catch { return null; }
      })
    )).filter(Boolean);

    keywordAllCards = cards;
    keywordPage = 1;
    renderKeywordPage();

  } catch (err) {
    keywordResult.style.display = "block";
    keywordPrecCards.innerHTML = `<div class="state-msg">${esc(err.message || "오류가 발생했습니다.")}</div>`;
  } finally {
    keywordBusy = false;
    keywordBtn.disabled = false;
    keywordBtn.textContent = "검색";
  }
}

function renderKeywordPage() {
  const start = (keywordPage - 1) * KEYWORD_PAGE_SIZE;
  const page  = keywordAllCards.slice(start, start + KEYWORD_PAGE_SIZE);
  keywordPrecCards.innerHTML = "";
  page.forEach(({ meta, detail }, idx) =>
    keywordPrecCards.appendChild(buildAnalysisPrecCard(meta, detail, start + idx + 1))
  );
  renderBatchPagination("keywordPagination", keywordAllCards.length, keywordPage, KEYWORD_PAGE_SIZE, p => {
    keywordPage = p;
    renderKeywordPage();
    keywordPrecCards.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

keywordForm.addEventListener("submit", e => {
  e.preventDefault();
  runKeywordSearch(keywordInput.value);
});

keywordInput.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); runKeywordSearch(keywordInput.value); }
});

keywordInput.addEventListener("input", () => {
  keywordInput.style.height = "auto";
  keywordInput.style.height = Math.min(keywordInput.scrollHeight, 200) + "px";
});
