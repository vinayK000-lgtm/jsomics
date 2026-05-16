const state = {
  report: null,
  activeTab: "overview",
  graph: {
    nodes: [],
    edges: [],
    hover: null,
  },
};

const refs = {};

document.addEventListener("DOMContentLoaded", () => {
  bindRefs();
  bindEvents();
  seedLocalDefaults();
  checkHealth();
  renderEmpty();
});

function bindRefs() {
  refs.form = document.getElementById("researchForm");
  refs.query = document.getElementById("query");
  refs.disease = document.getElementById("disease");
  refs.apiKey = document.getElementById("apiKey");
  refs.mode = document.getElementById("mode");
  refs.evidenceLevel = document.getElementById("evidenceLevel");
  refs.maxResults = document.getElementById("maxResults");
  refs.inlineEvidence = document.getElementById("inlineEvidence");
  refs.runButton = document.getElementById("runButton");
  refs.sampleButton = document.getElementById("sampleButton");
  refs.clearButton = document.getElementById("clearButton");
  refs.healthStatus = document.getElementById("healthStatus");
  refs.resultStatus = document.getElementById("resultStatus");
  refs.metrics = document.getElementById("metrics");
  refs.tabContent = document.getElementById("tabContent");
  refs.tabs = Array.from(document.querySelectorAll(".tab"));
}

function bindEvents() {
  refs.form.addEventListener("submit", onSubmit);
  refs.sampleButton.addEventListener("click", loadSample);
  refs.clearButton.addEventListener("click", clearWorkspace);
  refs.tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      state.activeTab = tab.dataset.tab;
      updateTabs();
      renderActiveTab();
    });
  });
}

function seedLocalDefaults() {
  refs.apiKey.value = localStorage.getItem("bioResearchApiKey") || "";
  if (["localhost", "127.0.0.1"].includes(window.location.hostname) && !refs.apiKey.value) {
    refs.apiKey.value = "local-dev-key";
  }
}

async function checkHealth() {
  try {
    const response = await fetch("/health");
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    refs.healthStatus.textContent = payload.auth_enabled
      ? `API ${payload.environment} - auth on`
      : `API ${payload.environment} - auth off`;
    refs.healthStatus.className = "status-chip";
  } catch (error) {
    refs.healthStatus.textContent = "API unavailable";
    refs.healthStatus.className = "status-chip error";
  }
}

async function onSubmit(event) {
  event.preventDefault();
  setBusy(true);
  setResultStatus("Running", "warning");

  try {
    const payload = buildRequestPayload();
    const headers = { "Content-Type": "application/json" };
    const apiKey = refs.apiKey.value.trim();
    if (apiKey) {
      headers["X-API-Key"] = apiKey;
      localStorage.setItem("bioResearchApiKey", apiKey);
    }

    const response = await fetch("/v1/research", {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(body.detail || `Request failed with HTTP ${response.status}`);
    }

    state.report = body;
    state.activeTab = "overview";
    updateTabs();
    renderMetrics(body);
    renderActiveTab();
    setResultStatus("Loaded", "");
  } catch (error) {
    setResultStatus("Error", "error");
    refs.tabContent.innerHTML = `
      <div class="empty-state">
        <strong>Request failed</strong>
        <span>${escapeHtml(error.message)}</span>
      </div>
    `;
  } finally {
    setBusy(false);
  }
}

function buildRequestPayload() {
  return {
    query: refs.query.value.trim(),
    disease: refs.disease.value.trim() || null,
    mode: refs.mode.value,
    evidence_level: refs.evidenceLevel.value,
    max_results: Number(refs.maxResults.value || 10),
    inline_evidence: parseInlineEvidence(),
  };
}

function parseInlineEvidence() {
  const value = refs.inlineEvidence.value.trim();
  if (!value) {
    return [];
  }
  const parsed = JSON.parse(value);
  if (!Array.isArray(parsed)) {
    throw new Error("Inline evidence must be a JSON array.");
  }
  return parsed;
}

function loadSample() {
  refs.query.value = "Key biomarkers, dysregulated pathways, and therapeutic targets in NSCLC";
  refs.disease.value = "NSCLC";
  refs.mode.value = "drug_targets";
  refs.evidenceLevel.value = "medium";
  refs.maxResults.value = "10";
  refs.inlineEvidence.value = JSON.stringify(
    [
      {
        source: "pubmed",
        source_id: "PMID:20",
        title: "EGFR therapeutic evidence",
        text:
          "EGFR activating mutation drives MAPK signaling pathway. " +
          "Osimertinib is an approved inhibitor of EGFR kinase domain in a clinical trial.",
        url: "https://pubmed.ncbi.nlm.nih.gov/",
        year: 2024,
      },
      {
        source: "pubmed",
        source_id: "PMID:21",
        title: "KRAS pathway evidence",
        text:
          "KRAS activates MAPK signaling pathway in lung cancer. " +
          "Sotorasib inhibits KRAS in treatment-resistant disease.",
        url: "https://pubmed.ncbi.nlm.nih.gov/",
        year: 2023,
      },
    ],
    null,
    2,
  );
}

function clearWorkspace() {
  refs.form.reset();
  seedLocalDefaults();
  state.report = null;
  state.activeTab = "overview";
  updateTabs();
  renderEmpty();
  setResultStatus("Idle", "");
}

function setBusy(isBusy) {
  refs.runButton.disabled = isBusy;
  refs.runButton.textContent = isBusy ? "Running" : "Run Analysis";
}

function setResultStatus(text, tone) {
  refs.resultStatus.textContent = text;
  refs.resultStatus.className = tone ? `status-chip ${tone}` : "status-chip subtle";
}

function updateTabs() {
  refs.tabs.forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === state.activeTab);
  });
}

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
  if (!state.report) {
    renderEmpty();
    return;
  }

  const report = state.report;
  if (state.activeTab === "overview") {
    renderOverview(report);
  } else if (state.activeTab === "targets") {
    renderTargets(report.drug_targets || []);
  } else if (state.activeTab === "biomarkers") {
    renderBiomarkers(report.biomarkers || []);
  } else if (state.activeTab === "pathways") {
    renderPathways(report.pathways || []);
  } else if (state.activeTab === "literature") {
    renderLiterature(report.literature_findings || []);
  } else if (state.activeTab === "evidence") {
    renderEvidence(report.evidence || []);
  } else if (state.activeTab === "json") {
    renderJson(report);
  }
}

function renderOverview(report) {
  refs.tabContent.innerHTML = `
    <div class="overview-grid">
      <div class="summary-panel">
        <section class="callout">
          <h3>Executive Summary</h3>
          <p>${escapeHtml(report.executive_summary || report.answer || "")}</p>
          <div class="finding-meta">
            ${pill(report.confidence_overall || "low", "green")}
            ${(report.agents_invoked || []).map((item) => pill(item, "blue")).join("")}
          </div>
        </section>
        ${renderListCallout("Cross-Agent Insights", report.cross_agent_insights || [], "")}
        ${renderListCallout("Caveats", report.caveats || [], "warning")}
        ${renderListCallout("Next Queries", report.suggested_next_queries || [], "")}
      </div>
      <section class="network-panel">
        <div class="network-header">
          <h3>Evidence Network</h3>
          <span>${escapeHtml(String((report.knowledge_graph_triples || []).length))} relationships</span>
        </div>
        <canvas id="networkCanvas" height="330"></canvas>
        <span class="canvas-note" id="canvasNote">Hover over a node to inspect relationships.</span>
      </section>
    </div>
  `;
  setupNetwork(report.knowledge_graph_triples || []);
}

function renderListCallout(title, values, tone) {
  if (!values.length) {
    return "";
  }
  return `
    <section class="callout ${tone}">
      <h3>${escapeHtml(title)}</h3>
      <ul class="compact-list">
        ${values.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ul>
    </section>
  `;
}

function renderTargets(items) {
  if (!items.length) {
    renderNoRows("No drug target leads returned.");
    return;
  }
  refs.tabContent.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Gene</th>
            <th>Class</th>
            <th>Total</th>
            <th>Scores</th>
            <th>Existing Drugs</th>
            <th>Rationale</th>
          </tr>
        </thead>
        <tbody>
          ${items
            .map(
              (item) => `
                <tr>
                  <td><strong>${escapeHtml(item.gene)}</strong></td>
                  <td>${escapeHtml(item.target_class)}</td>
                  <td>${numberCell(item.total_score)}</td>
                  <td>
                    <div class="pill-row">
                      ${pill(`G ${item.genetic_score}`, "blue")}
                      ${pill(`B ${item.biological_score}`, "green")}
                      ${pill(`D ${item.druggability_score}`, "amber")}
                      ${pill(`C ${item.clinical_score}`, "")}
                    </div>
                  </td>
                  <td>${drugPills(item.existing_drugs || [])}</td>
                  <td>${escapeHtml(item.rationale)}</td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderBiomarkers(items) {
  if (!items.length) {
    renderNoRows("No biomarker candidates returned.");
    return;
  }
  refs.tabContent.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Direction</th>
            <th>Score</th>
            <th>Confidence</th>
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          ${items
            .map(
              (item) => `
                <tr>
                  <td><strong>${escapeHtml(item.name)}</strong></td>
                  <td>${escapeHtml(item.marker_type)}</td>
                  <td>${escapeHtml(item.direction || "not specified")}</td>
                  <td>${numberCell(item.score)}</td>
                  <td>${numberCell(item.confidence)}</td>
                  <td>${evidencePills(item.evidence || [])}</td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderPathways(items) {
  if (!items.length) {
    renderNoRows("No pathway signals returned.");
    return;
  }
  refs.tabContent.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>ID</th>
            <th>Source</th>
            <th>Score</th>
            <th>Confidence</th>
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          ${items
            .map(
              (item) => `
                <tr>
                  <td><strong>${escapeHtml(item.name)}</strong></td>
                  <td>${escapeHtml(item.pathway_id)}</td>
                  <td>${escapeHtml(item.source)}</td>
                  <td>${numberCell(item.score)}</td>
                  <td>${numberCell(item.confidence)}</td>
                  <td>${evidencePills(item.evidence || [])}</td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderLiterature(items) {
  if (!items.length) {
    renderNoRows("No literature findings returned.");
    return;
  }
  refs.tabContent.innerHTML = `
    <div class="finding-list">
      ${items
        .map(
          (item) => `
            <article class="finding">
              <h3>${escapeHtml(item.consensus)} evidence, grade ${escapeHtml(item.evidence_grade)}</h3>
              <p>${escapeHtml(item.finding)}</p>
              <div class="finding-meta">
                ${(item.genes || []).map((value) => pill(value, "green")).join("")}
                ${(item.drugs || []).map((value) => pill(value, "amber")).join("")}
                ${(item.pathways || []).map((value) => pill(value, "blue")).join("")}
              </div>
            </article>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderEvidence(items) {
  if (!items.length) {
    renderNoRows("No evidence records returned.");
    return;
  }
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
          ${items
            .map(
              (item) => `
                <tr>
                  <td>${escapeHtml(item.source)}</td>
                  <td>${item.url ? `<a href="${escapeAttr(item.url)}">${escapeHtml(item.source_id)}</a>` : escapeHtml(item.source_id)}</td>
                  <td>${escapeHtml(item.title)}</td>
                  <td>${escapeHtml(String(item.year || ""))}</td>
                  <td>${escapeHtml(item.quality)}</td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
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
      <strong>No rows</strong>
      <span>${escapeHtml(message)}</span>
    </div>
  `;
}

function setupNetwork(triples) {
  const canvas = document.getElementById("networkCanvas");
  const note = document.getElementById("canvasNote");
  if (!canvas) {
    return;
  }
  const graph = buildGraph(triples);
  state.graph = { ...graph, hover: null };
  const redraw = () => drawGraph(canvas, note);
  redraw();
  window.addEventListener("resize", redraw, { passive: true });
  canvas.addEventListener("pointermove", (event) => {
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    state.graph.hover = findNodeAt(x, y);
    drawGraph(canvas, note);
  });
  canvas.addEventListener("pointerleave", () => {
    state.graph.hover = null;
    drawGraph(canvas, note);
  });
}

function buildGraph(triples) {
  const nodeMap = new Map();
  const edges = [];
  triples.forEach((triple) => {
    [triple.subject, triple.object].forEach((name) => {
      if (!nodeMap.has(name)) {
        nodeMap.set(name, {
          id: name,
          label: name,
          degree: 0,
          x: 0,
          y: 0,
        });
      }
      nodeMap.get(name).degree += 1;
    });
    edges.push({
      source: triple.subject,
      target: triple.object,
      predicate: triple.predicate,
      confidence: triple.confidence,
    });
  });
  return { nodes: Array.from(nodeMap.values()), edges };
}

function drawGraph(canvas, note) {
  const context = canvas.getContext("2d");
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * ratio));
  canvas.height = Math.max(1, Math.floor(rect.height * ratio));
  context.setTransform(ratio, 0, 0, ratio, 0, 0);

  const width = rect.width;
  const height = rect.height;
  context.clearRect(0, 0, width, height);
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, width, height);

  const { nodes, edges, hover } = state.graph;
  if (!nodes.length) {
    context.fillStyle = "#5d6966";
    context.font = "13px system-ui";
    context.fillText("No knowledge graph relationships returned.", 18, 30);
    if (note) {
      note.textContent = "No relationships available.";
    }
    return;
  }

  positionNodes(nodes, width, height);

  edges.forEach((edge) => {
    const source = nodes.find((node) => node.id === edge.source);
    const target = nodes.find((node) => node.id === edge.target);
    if (!source || !target) {
      return;
    }
    const active = hover && (hover.id === source.id || hover.id === target.id);
    drawEdge(context, source, target, edge, active);
  });

  nodes.forEach((node) => drawNode(context, node, hover && hover.id === node.id));

  if (note) {
    if (hover) {
      const related = edges.filter((edge) => edge.source === hover.id || edge.target === hover.id);
      note.textContent = `${hover.label}: ${related.length} relationship${related.length === 1 ? "" : "s"}`;
    } else {
      note.textContent = "Hover over a node to inspect relationships.";
    }
  }
}

function positionNodes(nodes, width, height) {
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.max(76, Math.min(width, height) * 0.34);
  nodes.forEach((node, index) => {
    const angle = (Math.PI * 2 * index) / nodes.length - Math.PI / 2;
    node.x = centerX + Math.cos(angle) * radius;
    node.y = centerY + Math.sin(angle) * radius;
  });
}

function drawEdge(context, source, target, edge, active) {
  context.save();
  context.strokeStyle = active ? "#2563eb" : "#b8c5c1";
  context.lineWidth = active ? 2.4 : 1.4;
  context.beginPath();
  context.moveTo(source.x, source.y);
  context.lineTo(target.x, target.y);
  context.stroke();

  const midX = (source.x + target.x) / 2;
  const midY = (source.y + target.y) / 2;
  if (active) {
    context.fillStyle = "#1d4ed8";
    context.font = "11px system-ui";
    context.fillText(edge.predicate, midX + 5, midY - 5);
  }
  context.restore();
}

function drawNode(context, node, active) {
  const radius = Math.max(16, Math.min(28, 13 + node.degree * 2));
  context.save();
  context.beginPath();
  context.arc(node.x, node.y, radius, 0, Math.PI * 2);
  context.fillStyle = active ? "#0f766e" : "#e7f7f3";
  context.strokeStyle = active ? "#0f766e" : "#8fc9bf";
  context.lineWidth = active ? 3 : 1.5;
  context.fill();
  context.stroke();

  context.fillStyle = active ? "#ffffff" : "#17211f";
  context.font = "700 12px system-ui";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(shortLabel(node.label), node.x, node.y);
  context.restore();
}

function findNodeAt(x, y) {
  return state.graph.nodes.find((node) => {
    const radius = Math.max(16, Math.min(28, 13 + node.degree * 2));
    const dx = node.x - x;
    const dy = node.y - y;
    return Math.sqrt(dx * dx + dy * dy) <= radius + 4;
  });
}

function shortLabel(value) {
  if (value.length <= 10) {
    return value;
  }
  return `${value.slice(0, 9)}...`;
}

function numberCell(value) {
  const numeric = Number(value);
  if (Number.isNaN(numeric)) {
    return escapeHtml(String(value || ""));
  }
  return escapeHtml(numeric.toFixed(numeric % 1 === 0 ? 0 : 2));
}

function drugPills(drugs) {
  if (!drugs.length) {
    return '<span class="pill">none listed</span>';
  }
  return `
    <div class="pill-row">
      ${drugs.map((drug) => pill(`${drug.name} (${drug.stage})`, "amber")).join("")}
    </div>
  `;
}

function evidencePills(evidence) {
  if (!evidence.length) {
    return '<span class="pill">none</span>';
  }
  return `
    <div class="pill-row">
      ${evidence.map((item) => pill(item.source_id, "blue")).join("")}
    </div>
  `;
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
