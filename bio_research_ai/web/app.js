/* ── JSOMICS Frontend ────────────────────────────────────────────
   Multi-omics Research Console
   Supabase auth · Query history · Ingest · LLM analysis
─────────────────────────────────────────────────────────────── */

const state = {
  report: null,
  activeTab: "overview",
  activePanel: "query",
  user: null,
  session: null,
  supabase: null,
  config: null,
  settings: {
    apiKey: sessionStorage.getItem("jsomicsApiKey") || "",
    llmProvider: localStorage.getItem("jsomicsLlmProvider") || "openai",
    ncbiEmail: localStorage.getItem("jsomicsNcbiEmail") || "",
  },
  graph: { nodes: [], edges: [], hover: null },
};

const refs = {};

// ── Boot ──────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  bindRefs();
  bindEvents();
  await loadConfig();
  await initSupabase();
  checkHealth();
  renderEmpty();
  applySettingsToForm();
});

// ── DOM refs ──────────────────────────────────────────────────────
function bindRefs() {
  const ids = [
    "researchForm", "query", "disease", "mode", "evidenceLevel", "searchDepth",
    "maxResults", "inlineEvidence", "apiKey", "apiKeyRow",
    "runButton", "sampleButton", "clearButton",
    "healthStatus", "resultStatus", "llmBadge", "metrics", "tabContent",
    "authModal", "closeAuthModal", "authButton",
    "loginEmail", "loginPassword", "loginButton", "authError",
    "authSignup", "authLogin",
    "signupName", "signupEmail", "signupPassword", "signupButton", "signupError",
    "settingsModal", "closeSettingsModal", "closeSettingsCancel", "settingsButton", "saveSettings",
    "settingsApiKey", "toggleApiKey", "settingsLlmProvider", "settingsNcbiEmail",
    "settingsUserStatus", "settingsPlan", "settingsQuota",
    "ingestModal", "closeIngestModal", "ingestButton",
    "pubmedQuery", "pubmedDisease", "pubmedLimit", "pubmedResult", "runPubmedIngest",
    "keggKeyword", "keggLimit", "keggResult", "runKeggIngest",
    "ingestStatus", "storeStatusContent", "refreshStoreStatus",
    "historyPanel", "historyList", "refreshHistoryButton",
    "queryPanel", "toastContainer",
  ];
  ids.forEach(id => { refs[id] = document.getElementById(id); });
  refs.tabs = Array.from(document.querySelectorAll(".tab"));
  refs.panelTabs = Array.from(document.querySelectorAll(".panel-tab"));
  refs.authTabs = Array.from(document.querySelectorAll("[data-auth-tab]"));
  refs.ingestTabs = Array.from(document.querySelectorAll("[data-ingest-tab]"));
  refs.omicsChecks = Array.from(document.querySelectorAll(".omics-check input[type='checkbox']"));
}

// ── Config ────────────────────────────────────────────────────────
async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    if (res.ok) state.config = await res.json();
  } catch {
    // backend not available yet
  }
}

// ── Supabase auth ─────────────────────────────────────────────────
async function initSupabase() {
  const cfg = state.config;
  if (!cfg?.supabase_url || !cfg?.supabase_anon_key) return;
  if (typeof window.supabase === "undefined") return;
  try {
    state.supabase = window.supabase.createClient(cfg.supabase_url, cfg.supabase_anon_key);
    state.supabase.auth.onAuthStateChange((_event, session) => {
      state.session = session;
      state.user = session?.user ?? null;
      updateAuthUI();
    });
    const { data: { session } } = await state.supabase.auth.getSession();
    state.session = session;
    state.user = session?.user ?? null;
    updateAuthUI();
  } catch (err) {
    console.warn("Supabase init failed:", err);
  }
}

function updateAuthUI() {
  const user = state.user;
  if (user) {
    refs.authButton.textContent = user.email?.split("@")[0] || "Account";
    refs.apiKeyRow.classList.remove("visible");
    loadQueryHistory();
    loadUserProfile();
  } else {
    refs.authButton.textContent = "Sign In";
    refs.apiKeyRow.classList.toggle("visible", !state.settings.apiKey);
    refs.historyList.innerHTML = '<p class="muted-text">Sign in to view your query history.</p>';
  }
}

async function login() {
  const email = refs.loginEmail.value.trim();
  const password = refs.loginPassword.value;
  if (!email || !password) { showAuthError("loginError", "Email and password required."); return; }
  refs.loginButton.disabled = true;
  refs.loginButton.textContent = "Signing in…";
  try {
    const { error } = await state.supabase.auth.signInWithPassword({ email, password });
    if (error) throw error;
    hideModal("authModal");
    toast("Signed in successfully", "success");
  } catch (err) {
    showAuthError("authError", err.message || "Sign-in failed.");
  } finally {
    refs.loginButton.disabled = false;
    refs.loginButton.textContent = "Sign In";
  }
}

async function signup() {
  const name = refs.signupName.value.trim();
  const email = refs.signupEmail.value.trim();
  const password = refs.signupPassword.value;
  if (!email || !password) { showAuthError("signupError", "Email and password required."); return; }
  if (password.length < 8) { showAuthError("signupError", "Password must be at least 8 characters."); return; }
  refs.signupButton.disabled = true;
  refs.signupButton.textContent = "Creating account…";
  try {
    const { error } = await state.supabase.auth.signUp({
      email, password,
      options: { data: { full_name: name || email.split("@")[0] } },
    });
    if (error) throw error;
    hideModal("authModal");
    toast("Account created! Check your email to confirm.", "success");
  } catch (err) {
    showAuthError("signupError", err.message || "Sign-up failed.");
  } finally {
    refs.signupButton.disabled = false;
    refs.signupButton.textContent = "Create Account";
  }
}

async function logout() {
  if (!state.supabase) return;
  await state.supabase.auth.signOut();
  state.user = null;
  state.session = null;
  updateAuthUI();
  toast("Signed out", "info");
}

function showAuthError(refId, message) {
  const el = refs[refId] || document.getElementById(refId);
  if (!el) return;
  el.textContent = message;
  el.classList.remove("hidden");
}

// ── Auth headers helper ───────────────────────────────────────────
function getAuthHeaders() {
  const headers = { "Content-Type": "application/json" };
  if (state.session?.access_token) {
    headers["Authorization"] = `Bearer ${state.session.access_token}`;
  } else if (state.settings.apiKey) {
    headers["X-API-Key"] = state.settings.apiKey;
  } else {
    const key = refs.apiKey?.value.trim();
    if (key) {
      headers["X-API-Key"] = key;
      sessionStorage.setItem("jsomicsApiKey", key);
      state.settings.apiKey = key;
    }
  }
  return headers;
}

// ── Settings ──────────────────────────────────────────────────────
async function loadUserProfile() {
  if (!state.session) return;
  try {
    const res = await fetch("/v1/users/me", { headers: getAuthHeaders() });
    if (!res.ok) return;
    const data = await res.json();
    refs.settingsUserStatus.textContent = data.email || "Signed in";
    refs.settingsPlan.textContent = data.plan || "free";
    refs.settingsPlan.className = `pill ${data.plan === "lab" ? "blue" : data.plan === "researcher" ? "green" : ""}`;
    refs.settingsQuota.textContent = `${data.api_calls_today} / ${data.daily_limit} today`;
  } catch {
    // silent
  }
}

function applySettingsToForm() {
  refs.settingsApiKey.value = state.settings.apiKey;
  refs.settingsLlmProvider.value = state.settings.llmProvider;
  refs.settingsNcbiEmail.value = state.settings.ncbiEmail;
  if (state.settings.apiKey) {
    refs.apiKeyRow.classList.add("visible");
    refs.apiKey.value = state.settings.apiKey;
  }
}

function saveSettings() {
  const key = refs.settingsApiKey.value.trim();
  const provider = refs.settingsLlmProvider.value;
  const ncbi = refs.settingsNcbiEmail.value.trim();
  state.settings.apiKey = key;
  state.settings.llmProvider = provider;
  state.settings.ncbiEmail = ncbi;
  if (key) sessionStorage.setItem("jsomicsApiKey", key);
  localStorage.setItem("jsomicsLlmProvider", provider);
  localStorage.setItem("jsomicsNcbiEmail", ncbi);
  if (!state.user) {
    refs.apiKey.value = key;
    refs.apiKeyRow.classList.toggle("visible", !!key);
  }
  hideModal("settingsModal");
  toast("Settings saved", "success");
}

// ── Query history ─────────────────────────────────────────────────
async function loadQueryHistory() {
  if (!state.session) return;
  refs.historyList.innerHTML = '<p class="muted-text">Loading history…</p>';
  try {
    const res = await fetch("/v1/users/me/history?limit=30", { headers: getAuthHeaders() });
    if (!res.ok) throw new Error("Failed to load history");
    const data = await res.json();
    renderHistory(data.history || []);
  } catch {
    refs.historyList.innerHTML = '<p class="muted-text">Could not load history.</p>';
  }
}

function renderHistory(items) {
  if (!items.length) {
    refs.historyList.innerHTML = '<p class="muted-text">No queries yet. Run your first analysis.</p>';
    return;
  }
  refs.historyList.innerHTML = items.map(item => {
    const date = new Date(item.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    const modalities = (item.modalities || []).join(", ") || "—";
    const count = item.result_count != null ? `${item.result_count} results` : "";
    return `
      <div class="history-item" data-query="${escapeAttr(item.query)}" role="button" tabindex="0">
        <span class="history-item-query">${escapeHtml(item.query)}</span>
        <span class="history-item-meta">
          <span>${escapeHtml(date)}</span>
          ${count ? `<span>${escapeHtml(count)}</span>` : ""}
        </span>
      </div>
    `;
  }).join("");

  refs.historyList.querySelectorAll(".history-item").forEach(el => {
    el.addEventListener("click", () => rerunQuery(el.dataset.query));
    el.addEventListener("keydown", e => { if (e.key === "Enter") rerunQuery(el.dataset.query); });
  });
}

function rerunQuery(query) {
  refs.query.value = query;
  switchPanel("query");
  toast("Query loaded — press Run Analysis", "info");
}

// ── Ingest ────────────────────────────────────────────────────────
async function ingestPubmed() {
  const query = refs.pubmedQuery.value.trim();
  if (!query) { toast("Enter a PubMed search query", "error"); return; }
  const disease = refs.pubmedDisease.value.trim() || null;
  const limit = parseInt(refs.pubmedLimit.value || "25", 10);
  refs.runPubmedIngest.disabled = true;
  refs.runPubmedIngest.textContent = "Fetching…";
  hideIngestResult("pubmedResult");
  try {
    const res = await fetch("/v1/ingest/pubmed", {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({ query, disease, limit }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Ingest failed");
    showIngestResult("pubmedResult", `Ingested ${data.ingested} PubMed records.`, "success");
    toast(`${data.ingested} PubMed records added`, "success");
  } catch (err) {
    showIngestResult("pubmedResult", err.message, "error");
  } finally {
    refs.runPubmedIngest.disabled = false;
    refs.runPubmedIngest.textContent = "Fetch PubMed";
  }
}

async function ingestKegg() {
  const keyword = refs.keggKeyword.value.trim();
  if (!keyword) { toast("Enter a KEGG disease keyword", "error"); return; }
  const limit = parseInt(refs.keggLimit.value || "20", 10);
  refs.runKeggIngest.disabled = true;
  refs.runKeggIngest.textContent = "Fetching…";
  hideIngestResult("keggResult");
  try {
    const res = await fetch("/v1/ingest/kegg", {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({ disease_keyword: keyword, limit }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Ingest failed");
    showIngestResult("keggResult", `Ingested ${data.ingested} KEGG pathway records.`, "success");
    toast(`${data.ingested} KEGG records added`, "success");
  } catch (err) {
    showIngestResult("keggResult", err.message, "error");
  } finally {
    refs.runKeggIngest.disabled = false;
    refs.runKeggIngest.textContent = "Fetch KEGG";
  }
}

async function loadStoreStatus() {
  refs.storeStatusContent.innerHTML = '<p class="muted-text">Loading…</p>';
  try {
    const res = await fetch("/v1/ingest/status", { headers: getAuthHeaders() });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed");
    const rows = Object.entries(data.by_source || {}).map(([src, count]) =>
      `<div class="store-row"><span>${escapeHtml(src)}</span><strong>${escapeHtml(String(count))}</strong></div>`
    ).join("") || '<p class="muted-text">No records ingested yet.</p>';
    refs.storeStatusContent.innerHTML = `
      <div class="store-row"><strong>Total Records</strong><strong>${escapeHtml(String(data.total_records))}</strong></div>
      <div class="store-row"><span>Plan</span><span>${escapeHtml(data.user_plan || "—")}</span></div>
      <h3 style="margin:10px 0 6px; font-size:12px; font-weight:700; color:var(--muted); text-transform:uppercase">By Source</h3>
      ${rows}
    `;
  } catch (err) {
    refs.storeStatusContent.innerHTML = `<p class="muted-text">${escapeHtml(err.message)}</p>`;
  }
}

function showIngestResult(refId, msg, type) {
  const el = refs[refId] || document.getElementById(refId);
  if (!el) return;
  el.textContent = msg;
  el.className = `ingest-result ${type}`;
}

function hideIngestResult(refId) {
  const el = refs[refId] || document.getElementById(refId);
  if (el) el.className = "ingest-result hidden";
}

// ── Health check ──────────────────────────────────────────────────
async function checkHealth() {
  try {
    const res = await fetch("/health");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const payload = await res.json();
    refs.healthStatus.textContent = `API ${payload.environment}`;
    refs.healthStatus.className = "status-chip";
  } catch {
    refs.healthStatus.textContent = "API unavailable";
    refs.healthStatus.className = "status-chip error";
  }
}

// ── Research query ────────────────────────────────────────────────
async function onSubmit(event) {
  event.preventDefault();
  const hasAuth = state.session || state.settings.apiKey || refs.apiKey?.value.trim();
  if (!hasAuth) {
    toast("Sign in or enter an API key to run analysis", "error");
    showModal("authModal");
    return;
  }
  setBusy(true);
  setResultStatus("Running", "warning");
  refs.llmBadge.classList.add("hidden");

  try {
    const payload = buildRequestPayload();
    const res = await fetch("/v1/research", {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify(payload),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);

    state.report = body;
    state.activeTab = "overview";
    updateTabs();
    renderMetrics(body);
    renderActiveTab();
    setResultStatus(body.provenance?.from_cache ? "Cached" : "Loaded", "");

    if (body.provenance?.llm_enabled) {
      refs.llmBadge.textContent = `LLM: ${body.provenance.llm_provider || "AI"}`;
      refs.llmBadge.classList.remove("hidden");
    }

    if (state.session) {
      setTimeout(loadQueryHistory, 1500);
    }
  } catch (err) {
    setResultStatus("Error", "error");
    refs.tabContent.innerHTML = `
      <div class="empty-state">
        <strong>Request failed</strong>
        <span>${escapeHtml(err.message)}</span>
      </div>
    `;
  } finally {
    setBusy(false);
  }
}

function buildRequestPayload() {
  const omics = refs.omicsChecks.filter(c => c.checked).map(c => c.value);
  const inlineEvidence = parseInlineEvidence();
  return {
    query: refs.query.value.trim(),
    disease: refs.disease.value.trim() || null,
    mode: refs.mode.value,
    evidence_level: refs.evidenceLevel.value,
    search_depth: refs.searchDepth.value,
    max_results: Number(refs.maxResults.value || 10),
    omics: omics.length ? omics : ["literature", "biomarkers", "pathways", "drug_targets"],
    inline_evidence: inlineEvidence,
  };
}

function parseInlineEvidence() {
  const value = refs.inlineEvidence.value.trim();
  if (!value || value === "[]") return [];
  try {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) throw new Error("Must be a JSON array.");
    return parsed;
  } catch (err) {
    throw new Error(`Inline evidence: ${err.message}`);
  }
}

function loadSample() {
  refs.query.value = "Key biomarkers, dysregulated pathways, and therapeutic targets in NSCLC";
  refs.disease.value = "NSCLC";
  refs.mode.value = "drug_targets";
  refs.evidenceLevel.value = "medium";
  refs.searchDepth.value = "quick";
  refs.maxResults.value = "10";
  refs.omicsChecks.forEach(c => {
    c.checked = ["literature", "biomarkers", "pathways", "drug_targets"].includes(c.value);
  });
  refs.inlineEvidence.value = JSON.stringify([
    {
      source: "pubmed", source_id: "PMID:20",
      title: "EGFR therapeutic evidence",
      text: "EGFR activating mutation drives MAPK signaling pathway. Osimertinib is an approved inhibitor of EGFR kinase domain.",
      url: "https://pubmed.ncbi.nlm.nih.gov/", year: 2024,
    },
    {
      source: "pubmed", source_id: "PMID:21",
      title: "KRAS pathway evidence",
      text: "KRAS activates MAPK signaling pathway in lung cancer. Sotorasib inhibits KRAS in treatment-resistant disease.",
      url: "https://pubmed.ncbi.nlm.nih.gov/", year: 2023,
    },
  ], null, 2);
}

function clearWorkspace() {
  refs.researchForm.reset();
  refs.omicsChecks.forEach(c => {
    c.checked = ["literature", "biomarkers", "pathways", "drug_targets"].includes(c.value);
  });
  applySettingsToForm();
  state.report = null;
  state.activeTab = "overview";
  updateTabs();
  renderEmpty();
  setResultStatus("Idle", "");
  refs.llmBadge.classList.add("hidden");
}

function setBusy(isBusy) {
  refs.runButton.disabled = isBusy;
  refs.runButton.textContent = isBusy ? "Running…" : "Run Analysis";
}

function setResultStatus(text, tone) {
  refs.resultStatus.textContent = text;
  refs.resultStatus.className = tone ? `status-chip ${tone}` : "status-chip subtle";
}

// ── Panel navigation ──────────────────────────────────────────────
function switchPanel(panelName) {
  state.activePanel = panelName;
  refs.panelTabs.forEach(t => t.classList.toggle("active", t.dataset.panel === panelName));
  refs.queryPanel.classList.toggle("hidden", panelName !== "query");
  refs.historyPanel.classList.toggle("hidden", panelName !== "history");
  if (panelName === "history" && state.session) loadQueryHistory();
}

// ── Tab navigation ────────────────────────────────────────────────
function updateTabs() {
  refs.tabs.forEach(tab => tab.classList.toggle("active", tab.dataset.tab === state.activeTab));
}

// ── Results rendering ─────────────────────────────────────────────
function renderEmpty() {
  refs.metrics.innerHTML = metricMarkup("--", "0", "0", "0");
  refs.tabContent.innerHTML = `
    <div class="empty-state">
      <strong>No report loaded</strong>
      <span>Run a query to populate the workspace.</span>
    </div>
  `;
}

function renderMetrics(report) {
  refs.metrics.innerHTML = metricMarkup(
    report.confidence_overall || "--",
    String(report.evidence?.length || 0),
    String(report.unified_references?.length || 0),
    String(report.drug_targets?.length || 0),
  );
}

function metricMarkup(confidence, evidence, references, targets) {
  return `
    <article><span>Confidence</span><strong>${escapeHtml(confidence)}</strong></article>
    <article><span>Evidence</span><strong>${escapeHtml(evidence)}</strong></article>
    <article><span>References</span><strong>${escapeHtml(references)}</strong></article>
    <article><span>Targets</span><strong>${escapeHtml(targets)}</strong></article>
  `;
}

function renderActiveTab() {
  if (!state.report) { renderEmpty(); return; }
  const report = state.report;
  const tab = state.activeTab;
  if (tab === "overview")    renderOverview(report);
  else if (tab === "targets")     renderTargets(report.drug_targets || []);
  else if (tab === "biomarkers")  renderBiomarkers(report.biomarkers || []);
  else if (tab === "pathways")    renderPathways(report.pathways || []);
  else if (tab === "literature")  renderLiterature(report.literature_findings || []);
  else if (tab === "evidence")    renderEvidence(report.evidence || []);
  else if (tab === "provenance")  renderProvenance(report.provenance || {});
  else if (tab === "json")        renderJson(report);
}

function renderOverview(report) {
  refs.tabContent.innerHTML = `
    <div class="overview-grid">
      <div class="summary-panel">
        <section class="callout">
          <h3>Executive Summary</h3>
          <p>${escapeHtml(report.executive_summary || report.answer || "No summary available.")}</p>
          <div class="finding-meta" style="margin-top:10px">
            ${pill(report.confidence_overall || "low", "green")}
            ${(report.agents_invoked || []).map(a => pill(a, "blue")).join("")}
          </div>
        </section>
        ${renderListCallout("Cross-Omics Insights", report.cross_agent_insights || [], "")}
        ${renderListCallout("Limitations", report.limitations || [], "warning")}
        ${renderListCallout("Suggested Next Queries", report.suggested_next_queries || [], "")}
        ${report.disclaimer ? `<section class="callout danger"><p style="font-size:12px">${escapeHtml(report.disclaimer)}</p></section>` : ""}
      </div>
      <section class="network-panel">
        <div class="network-header">
          <h3>Evidence Network</h3>
          <span>${escapeHtml(String((report.knowledge_graph_triples || []).length))} relationships</span>
        </div>
        <canvas id="networkCanvas" height="300"></canvas>
        <span class="canvas-note" id="canvasNote">Hover over a node to inspect relationships.</span>
      </section>
    </div>
  `;
  setupNetwork(report.knowledge_graph_triples || []);
}

function renderListCallout(title, values, tone) {
  if (!values.length) return "";
  return `
    <section class="callout ${tone}">
      <h3>${escapeHtml(title)}</h3>
      <ul class="compact-list">
        ${values.map(item => `<li>${escapeHtml(item)}</li>`).join("")}
      </ul>
    </section>
  `;
}

function renderTargets(items) {
  if (!items.length) { renderNoRows("No drug target leads returned."); return; }
  refs.tabContent.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Gene / Protein</th>
            <th>Class</th>
            <th>Score</th>
            <th>Subscores</th>
            <th>Drugs</th>
            <th>Rationale</th>
          </tr>
        </thead>
        <tbody>
          ${items.map(item => `
            <tr>
              <td>
                <strong>${escapeHtml(item.gene)}</strong>
                ${item.protein ? `<br><span style="color:var(--muted);font-size:11px">${escapeHtml(item.protein)}</span>` : ""}
                ${item.uniprot_id ? `<br><span class="pill subtle" style="margin-top:3px">${escapeHtml(item.uniprot_id)}</span>` : ""}
              </td>
              <td>${escapeHtml(item.target_class)}</td>
              <td><strong>${numberCell(item.total_score)}</strong></td>
              <td>
                <div class="pill-row">
                  ${pill(`G ${fmt(item.genetic_score)}`, "blue")}
                  ${pill(`B ${fmt(item.biological_score)}`, "green")}
                  ${pill(`D ${fmt(item.druggability_score)}`, "amber")}
                  ${pill(`C ${fmt(item.clinical_score)}`, "")}
                </div>
              </td>
              <td>${drugPills(item.existing_drugs || [])}</td>
              <td style="max-width:200px">${escapeHtml(item.rationale)}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderBiomarkers(items) {
  if (!items.length) { renderNoRows("No biomarker candidates returned."); return; }
  refs.tabContent.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Biomarker</th>
            <th>Type</th>
            <th>Direction</th>
            <th>Score</th>
            <th>Confidence</th>
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          ${items.map(item => `
            <tr>
              <td><strong>${escapeHtml(item.name)}</strong></td>
              <td>${escapeHtml(item.marker_type)}</td>
              <td>${directionPill(item.direction)}</td>
              <td>${numberCell(item.score)}</td>
              <td>${confidencePill(item.confidence)}</td>
              <td>${evidencePills(item.evidence || [])}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderPathways(items) {
  if (!items.length) { renderNoRows("No pathway signals returned."); return; }
  refs.tabContent.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Pathway</th>
            <th>ID</th>
            <th>Source</th>
            <th>Score</th>
            <th>Confidence</th>
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          ${items.map(item => `
            <tr>
              <td><strong>${escapeHtml(item.name)}</strong></td>
              <td><span class="pill">${escapeHtml(item.pathway_id)}</span></td>
              <td>${escapeHtml(item.source)}</td>
              <td>${numberCell(item.score)}</td>
              <td>${confidencePill(item.confidence)}</td>
              <td>${evidencePills(item.evidence || [])}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderLiterature(items) {
  if (!items.length) { renderNoRows("No literature findings returned."); return; }
  refs.tabContent.innerHTML = `
    <div class="finding-list">
      ${items.map(item => `
        <article class="finding">
          <div class="finding-meta">
            ${pill(item.consensus || "unknown", "")}
            ${pill(`Grade: ${item.evidence_grade || "?"}`, item.evidence_grade === "A" ? "green" : item.evidence_grade === "B" ? "blue" : "amber")}
          </div>
          <p>${escapeHtml(item.finding)}</p>
          <div class="finding-meta">
            ${(item.genes || []).map(g => pill(g, "green")).join("")}
            ${(item.drugs || []).map(d => pill(d, "amber")).join("")}
            ${(item.pathways || []).map(p => pill(p, "blue")).join("")}
            ${(item.diseases || []).map(d => pill(d, "")).join("")}
          </div>
          ${item.supporting_evidence?.length ? `
            <div class="finding-meta" style="margin-top:6px">
              ${item.supporting_evidence.slice(0, 4).map(e =>
                e.url ? `<a href="${escapeAttr(safeUrl(e.url))}" target="_blank" rel="noopener" class="pill blue">${escapeHtml(e.source_id)}</a>`
                      : `<span class="pill blue">${escapeHtml(e.source_id)}</span>`
              ).join("")}
            </div>
          ` : ""}
        </article>
      `).join("")}
    </div>
  `;
}

function renderEvidence(items) {
  if (!items.length) { renderNoRows("No evidence records returned."); return; }
  refs.tabContent.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Source</th>
            <th>ID</th>
            <th>Title</th>
            <th>Year</th>
            <th>Quality</th>
          </tr>
        </thead>
        <tbody>
          ${items.map(item => `
            <tr>
              <td>${escapeHtml(item.source)}</td>
              <td>${sourceIdLink(item)}</td>
              <td style="max-width:260px">${escapeHtml(item.title)}</td>
              <td>${escapeHtml(String(item.year || ""))}</td>
              <td>${qualityPill(item.quality)}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderProvenance(prov) {
  const agentRows = Object.entries(prov.agent_status || {}).map(([agent, status]) => {
    const ms = prov.agent_timings_ms?.[agent];
    const tone = status === "done" ? "green" : status === "timeout" ? "amber" : "red";
    return `
      <div class="provenance-row">
        <span class="provenance-label">${escapeHtml(agent)}</span>
        <span class="provenance-value">
          ${pill(status, tone)}
          ${ms != null ? `<span style="margin-left:6px;color:var(--muted);font-size:11px">${escapeHtml(String(ms))}ms</span>` : ""}
        </span>
      </div>
    `;
  }).join("");

  refs.tabContent.innerHTML = `
    <div class="provenance-grid">
      <div class="provenance-card">
        <h3>Run Info</h3>
        ${provRow("Generated by", prov.generated_by)}
        ${provRow("Environment", prov.environment)}
        ${provRow("Evidence records", String(prov.evidence_records ?? "—"))}
        ${provRow("Took", prov.took_ms != null ? `${prov.took_ms}ms` : "—")}
        ${provRow("From cache", prov.from_cache ? "Yes" : "No")}
        ${provRow("Data path", prov.data_path || "configured repository")}
        ${provRow("LLM enabled", prov.llm_enabled ? `Yes (${prov.llm_provider || "unknown"})` : "No")}
        ${prov.omics?.length ? provRow("Omics layers", prov.omics.join(", ")) : ""}
      </div>
      ${agentRows ? `<div class="provenance-card"><h3>Agent Status</h3>${agentRows}</div>` : ""}
      ${prov.errors?.length ? `
        <div class="provenance-card">
          <h3>Errors</h3>
          ${prov.errors.map(e => `<div class="provenance-row"><span class="provenance-value" style="color:var(--red)">${escapeHtml(e)}</span></div>`).join("")}
        </div>
      ` : ""}
      ${prov.sources?.length ? `
        <div class="provenance-card">
          <h3>Data Sources</h3>
          <div class="pill-row">${prov.sources.map(s => pill(s, "")).join("")}</div>
        </div>
      ` : ""}
    </div>
  `;
}

function provRow(label, value) {
  return `
    <div class="provenance-row">
      <span class="provenance-label">${escapeHtml(label)}</span>
      <span class="provenance-value">${escapeHtml(String(value ?? "—"))}</span>
    </div>
  `;
}

function renderJson(report) {
  refs.tabContent.innerHTML = `
    <div class="json-panel">
      <pre>${escapeHtml(JSON.stringify(report, null, 2))}</pre>
    </div>
  `;
}

function renderNoRows(message) {
  refs.tabContent.innerHTML = `
    <div class="empty-state">
      <strong>No data</strong>
      <span>${escapeHtml(message)}</span>
    </div>
  `;
}

// ── Knowledge graph ───────────────────────────────────────────────
function setupNetwork(triples) {
  const canvas = document.getElementById("networkCanvas");
  const note = document.getElementById("canvasNote");
  if (!canvas) return;
  const graph = buildGraph(triples);
  state.graph = { ...graph, hover: null };
  let rafId;
  const redraw = () => { cancelAnimationFrame(rafId); rafId = requestAnimationFrame(() => drawGraph(canvas, note)); };
  redraw();
  window.addEventListener("resize", redraw, { passive: true });
  canvas.addEventListener("pointermove", e => {
    const rect = canvas.getBoundingClientRect();
    state.graph.hover = findNodeAt(e.clientX - rect.left, e.clientY - rect.top);
    redraw();
  });
  canvas.addEventListener("pointerleave", () => { state.graph.hover = null; redraw(); });
}

function buildGraph(triples) {
  const nodeMap = new Map();
  const edges = [];
  triples.forEach(triple => {
    [triple.subject, triple.object].forEach(name => {
      if (!nodeMap.has(name)) nodeMap.set(name, { id: name, label: name, degree: 0, x: 0, y: 0 });
      nodeMap.get(name).degree += 1;
    });
    edges.push({ source: triple.subject, target: triple.object, predicate: triple.predicate, confidence: triple.confidence });
  });
  return { nodes: Array.from(nodeMap.values()), edges };
}

function drawGraph(canvas, note) {
  const ctx = canvas.getContext("2d");
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const W = rect.width, H = rect.height;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, W, H);

  const { nodes, edges, hover } = state.graph;
  if (!nodes.length) {
    ctx.fillStyle = "#5d6966";
    ctx.font = "13px system-ui";
    ctx.fillText("No knowledge graph relationships returned.", 16, 28);
    if (note) note.textContent = "No relationships available.";
    return;
  }
  positionNodes(nodes, W, H);
  edges.forEach(edge => {
    const s = nodes.find(n => n.id === edge.source);
    const t = nodes.find(n => n.id === edge.target);
    if (s && t) drawEdge(ctx, s, t, edge, hover && (hover.id === s.id || hover.id === t.id));
  });
  nodes.forEach(node => drawNode(ctx, node, hover?.id === node.id));
  if (note) {
    if (hover) {
      const related = edges.filter(e => e.source === hover.id || e.target === hover.id);
      note.textContent = `${hover.label}: ${related.length} relationship${related.length === 1 ? "" : "s"}`;
    } else {
      note.textContent = "Hover over a node to inspect relationships.";
    }
  }
}

function positionNodes(nodes, W, H) {
  const cx = W / 2, cy = H / 2;
  const r = Math.max(70, Math.min(W, H) * 0.33);
  nodes.forEach((n, i) => {
    const angle = (Math.PI * 2 * i / nodes.length) - Math.PI / 2;
    n.x = cx + Math.cos(angle) * r;
    n.y = cy + Math.sin(angle) * r;
  });
}

function drawEdge(ctx, s, t, edge, active) {
  ctx.save();
  ctx.strokeStyle = active ? "#2563eb" : "#c3d0cc";
  ctx.lineWidth = active ? 2 : 1.2;
  ctx.beginPath();
  ctx.moveTo(s.x, s.y);
  ctx.lineTo(t.x, t.y);
  ctx.stroke();
  if (active) {
    const midX = (s.x + t.x) / 2, midY = (s.y + t.y) / 2;
    ctx.fillStyle = "#1d4ed8";
    ctx.font = "11px system-ui";
    ctx.fillText(edge.predicate, midX + 4, midY - 4);
  }
  ctx.restore();
}

function drawNode(ctx, node, active) {
  const r = Math.max(14, Math.min(26, 11 + node.degree * 2));
  ctx.save();
  ctx.beginPath();
  ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
  ctx.fillStyle = active ? "#0f766e" : "#e7f7f3";
  ctx.strokeStyle = active ? "#0f766e" : "#8fc9bf";
  ctx.lineWidth = active ? 2.5 : 1.5;
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = active ? "#ffffff" : "#17211f";
  ctx.font = "700 11px system-ui";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(shortLabel(node.label), node.x, node.y);
  ctx.restore();
}

function findNodeAt(x, y) {
  return state.graph.nodes.find(n => {
    const r = Math.max(14, Math.min(26, 11 + n.degree * 2));
    return Math.hypot(n.x - x, n.y - y) <= r + 4;
  });
}

// ── Modal helpers ─────────────────────────────────────────────────
function showModal(id) {
  const el = refs[id] || document.getElementById(id);
  if (el) el.classList.remove("hidden");
}

function hideModal(id) {
  const el = refs[id] || document.getElementById(id);
  if (el) el.classList.add("hidden");
}

function switchIngestTab(tabName) {
  refs.ingestTabs.forEach(t => t.classList.toggle("active", t.dataset.ingestTab === tabName));
  const forms = { pubmed: "ingestPubmed", kegg: "ingestKegg", status: "ingestStatus" };
  Object.entries(forms).forEach(([key, formId]) => {
    const el = document.getElementById(formId);
    if (el) el.classList.toggle("hidden", key !== tabName);
  });
  if (tabName === "status") loadStoreStatus();
}

function switchAuthTab(tabName) {
  refs.authTabs.forEach(t => t.classList.toggle("active", t.dataset.authTab === tabName));
  refs.authLogin.classList.toggle("hidden", tabName !== "login");
  refs.authSignup.classList.toggle("hidden", tabName !== "signup");
  refs.authError.classList.add("hidden");
}

// ── Toast ─────────────────────────────────────────────────────────
function toast(message, type = "info") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  refs.toastContainer.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ── Event bindings ────────────────────────────────────────────────
function bindEvents() {
  refs.researchForm.addEventListener("submit", onSubmit);
  refs.sampleButton.addEventListener("click", loadSample);
  refs.clearButton.addEventListener("click", clearWorkspace);
  refs.refreshHistoryButton.addEventListener("click", loadQueryHistory);

  refs.tabs.forEach(tab => tab.addEventListener("click", () => {
    state.activeTab = tab.dataset.tab;
    updateTabs();
    renderActiveTab();
  }));

  refs.panelTabs.forEach(tab => tab.addEventListener("click", () => switchPanel(tab.dataset.panel)));

  // Auth
  refs.authButton.addEventListener("click", () => {
    if (state.user) logout();
    else showModal("authModal");
  });
  refs.closeAuthModal.addEventListener("click", () => hideModal("authModal"));
  refs.authModal.addEventListener("click", e => { if (e.target === refs.authModal) hideModal("authModal"); });
  refs.loginButton.addEventListener("click", login);
  refs.signupButton.addEventListener("click", signup);
  refs.authTabs.forEach(t => t.addEventListener("click", () => switchAuthTab(t.dataset.authTab)));
  refs.loginPassword.addEventListener("keydown", e => { if (e.key === "Enter") login(); });
  refs.signupPassword.addEventListener("keydown", e => { if (e.key === "Enter") signup(); });

  // Settings
  refs.settingsButton.addEventListener("click", () => {
    applySettingsToForm();
    if (state.session) loadUserProfile();
    showModal("settingsModal");
  });
  refs.closeSettingsModal.addEventListener("click", () => hideModal("settingsModal"));
  refs.closeSettingsCancel.addEventListener("click", () => hideModal("settingsModal"));
  refs.settingsModal.addEventListener("click", e => { if (e.target === refs.settingsModal) hideModal("settingsModal"); });
  refs.saveSettings.addEventListener("click", saveSettings);
  refs.toggleApiKey.addEventListener("click", () => {
    const isPassword = refs.settingsApiKey.type === "password";
    refs.settingsApiKey.type = isPassword ? "text" : "password";
    refs.toggleApiKey.textContent = isPassword ? "Hide" : "Show";
  });

  // Ingest
  refs.ingestButton.addEventListener("click", () => showModal("ingestModal"));
  refs.closeIngestModal.addEventListener("click", () => hideModal("ingestModal"));
  refs.ingestModal.addEventListener("click", e => { if (e.target === refs.ingestModal) hideModal("ingestModal"); });
  refs.ingestTabs.forEach(t => t.addEventListener("click", () => switchIngestTab(t.dataset.ingestTab)));
  refs.runPubmedIngest.addEventListener("click", ingestPubmed);
  refs.runKeggIngest.addEventListener("click", ingestKegg);
  refs.refreshStoreStatus.addEventListener("click", loadStoreStatus);

  // Keyboard: close modals on Escape
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") {
      ["authModal", "settingsModal", "ingestModal"].forEach(id => hideModal(id));
    }
  });
}

// ── Utility helpers ───────────────────────────────────────────────
function shortLabel(value) {
  return value.length <= 10 ? value : `${value.slice(0, 9)}…`;
}

function fmt(value) {
  const n = Number(value);
  return Number.isNaN(n) ? "—" : n.toFixed(2);
}

function numberCell(value) {
  const n = Number(value);
  if (Number.isNaN(n)) return escapeHtml(String(value || ""));
  return escapeHtml(n % 1 === 0 ? String(n) : n.toFixed(2));
}

function directionPill(dir) {
  if (!dir) return '<span class="pill subtle">N/A</span>';
  const tone = dir === "up" || dir.includes("up") ? "red" : dir === "down" || dir.includes("down") ? "blue" : "";
  return pill(dir, tone);
}

function confidencePill(value) {
  const n = Number(value);
  if (Number.isNaN(n)) return escapeHtml(String(value || "—"));
  const tone = n >= 0.7 ? "green" : n >= 0.4 ? "amber" : "red";
  return pill(n.toFixed(2), tone);
}

function qualityPill(quality) {
  if (!quality) return '<span class="pill subtle">—</span>';
  const tone = quality === "high" ? "green" : quality === "medium" ? "blue" : "subtle";
  return pill(quality, tone);
}

function drugPills(drugs) {
  if (!drugs.length) return '<span class="pill subtle">none listed</span>';
  return `<div class="pill-row">${drugs.map(d => pill(`${d.name} (${d.stage})`, "amber")).join("")}</div>`;
}

function evidencePills(evidence) {
  if (!evidence.length) return '<span class="pill subtle">none</span>';
  const shown = evidence.slice(0, 4);
  const rest = evidence.length > 4 ? `<span class="pill subtle">+${evidence.length - 4}</span>` : "";
  return `<div class="pill-row">${shown.map(e =>
    e.url ? `<a href="${escapeAttr(safeUrl(e.url))}" target="_blank" rel="noopener" class="pill blue">${escapeHtml(e.source_id)}</a>`
          : `<span class="pill blue">${escapeHtml(e.source_id)}</span>`
  ).join("")}${rest}</div>`;
}

function sourceIdLink(item) {
  const url = safeUrl(item.url);
  return url
    ? `<a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.source_id)}</a>`
    : escapeHtml(item.source_id);
}

function safeUrl(value) {
  try {
    const url = new URL(String(value || ""), window.location.origin);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch { return ""; }
}

function pill(text, tone) {
  return `<span class="pill ${tone || ""}">${escapeHtml(String(text))}</span>`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}
