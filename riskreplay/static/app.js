"use strict";

function bootRiskReplay() {
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));
  const pageSize = 12;
  const embeddedNode = $("#riskreplay-bundle");
  let embeddedReport = null;
  let embeddedError = null;
  if (embeddedNode) {
    try {
      embeddedReport = JSON.parse(embeddedNode.textContent);
      if (!embeddedReport || typeof embeddedReport !== "object" || !embeddedReport.run_id) throw new Error("The saved report has no run identity.");
    } catch (error) { embeddedError = error; }
  }
  const state = { report: null, runs: [], filter: "all", query: "", page: 0, selected: null, view: "review", detail: "trace", loading: 0 };
  const viewCopy = {
    review: ["Decision review", "Reconstruct the past. Understand what changed."],
    comparison: ["Policy comparison", "Changed decisions, evaluated on equivalent evidence."],
    models: ["Model evidence", "Chronological evaluation with explicit label support."],
    integrity: ["Integrity checks", "Verify the boundary between history and hindsight."],
  };

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }

  function icon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.classList.add("icon");
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", `#i-${name}`);
    svg.append(use);
    return svg;
  }

  const human = (value) => String(value ?? "Unavailable").replaceAll("_", " ");
  const numeric = (value) => typeof value === "number" && Number.isFinite(value);
  const number = (value, digits = 0) => numeric(value) ? value.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits }) : "—";
  const percent = (value, digits = 1) => numeric(value) ? `${number(value * 100, digits)}%` : "Unavailable";
  const score = (value) => numeric(value) ? value.toFixed(4) : "Unavailable";
  const shortHash = (value) => typeof value === "string" ? `${value.slice(0, 12)}…` : "Unavailable";
  const valueText = (value) => value == null ? "Unavailable" : typeof value === "object" ? JSON.stringify(value) : String(value);
  const decisions = () => Array.isArray(state.report?.decisions) ? state.report.decisions.filter((row) => row && typeof row === "object") : [];
  const changed = (row) => typeof row.changed === "boolean" ? row.changed : row.candidate_action != null && row.replayed_action != null && row.candidate_action !== row.replayed_action;

  function date(value, compact = false) {
    if (!value) return "Time unavailable";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return String(value);
    return parsed.toLocaleString("en-GB", {
      timeZone: "UTC", day: "2-digit", month: "short", ...(compact ? {} : { year: "numeric" }),
      hour: "2-digit", minute: "2-digit", ...(compact ? {} : { second: "2-digit" }),
    }).replace(",", " ·") + " UTC";
  }

  function statusPill(status) {
    const safe = ["matched", "mismatched", "incomplete", "passed", "failed", "warning"].includes(status) ? status : "unknown";
    return node("span", `status-pill status-${safe}`, human(status ?? "unknown"));
  }

  function actionElement(action, className = "") {
    const safe = ["approve", "decline", "review"].includes(action) ? action : "unavailable";
    return node("span", `action-${safe} ${className}`, action == null ? "Unavailable" : human(action));
  }

  async function fetchJSON(url) {
    if (embeddedNode) {
      if (embeddedError) throw new Error(`The saved report could not be read: ${embeddedError.message}`);
      if (url === "/api/runs") return { runs: [{ run_id: embeddedReport.run_id, created_at: embeddedReport.created_at, mode: embeddedReport.mode, summary: embeddedReport.summary }], unavailable: [], count: 1 };
      if (url === `/api/runs/${encodeURIComponent(embeddedReport.run_id)}`) return embeddedReport;
      const incidentPrefix = `/api/runs/${encodeURIComponent(embeddedReport.run_id)}/transactions/`;
      if (url.startsWith(incidentPrefix)) {
        const id = decodeURIComponent(url.slice(incidentPrefix.length));
        const row = embeddedReport.decisions?.find((item) => item.transaction_id === id);
        if (row) return row;
      }
      throw new Error("This artifact contains one saved run. The requested evidence is unavailable.");
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(url, { signal: controller.signal, headers: { Accept: "application/json" } });
      let body;
      try { body = await response.json(); } catch { throw new Error("The local server returned an unreadable response."); }
      if (!response.ok) throw new Error(body?.error?.message || `The request failed (${response.status}).`);
      return body;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("The local report request timed out. Check that the server is running.");
      if (error instanceof TypeError) throw new Error("The local report server is unavailable. Check the terminal and retry.");
      throw error;
    } finally { clearTimeout(timeout); }
  }

  function showGlobal(type, title, message, retry) {
    const target = $("#global-message");
    target.replaceChildren(type === "loading" ? node("span", "loader") : icon(type === "error" ? "alert" : "file"), node("h2", "", title), node("p", "", message));
    if (type === "empty") target.append(node("code", "", "make demo"));
    if (retry) {
      const button = node("button", "button button-light", "Try again");
      button.addEventListener("click", retry);
      target.append(button);
    }
    target.hidden = false;
    $("#report-content").hidden = true;
    $("#export-menu").hidden = true;
  }

  function updateURL() {
    if (embeddedNode) return;
    const params = new URLSearchParams();
    if (state.report?.run_id) params.set("run", state.report.run_id);
    if (state.view !== "review") params.set("view", state.view);
    if (state.selected) params.set("transaction", state.selected);
    history.replaceState(null, "", `${location.pathname}${params.size ? `?${params}` : ""}`);
  }

  async function loadRuns() {
    showGlobal("loading", "Loading local runs", "Reading persisted reports and their evidence.");
    $("#run-select").disabled = true;
    try {
      const payload = await fetchJSON("/api/runs");
      state.runs = Array.isArray(payload) ? payload : payload.runs || [];
      const unavailable = payload.unavailable || [];
      $("#partial-message").hidden = !unavailable.length;
      $("#partial-message").textContent = `${unavailable.length} persisted run${unavailable.length === 1 ? " is" : "s are"} unavailable. ${unavailable.map((item) => `${item.run_id}: ${item.reason}`).join(" ")}`;
      const selector = $("#run-select");
      selector.replaceChildren();
      if (!state.runs.length) {
        selector.append(node("option", "", "No saved runs"));
        showGlobal("empty", "Your first replay starts locally", "Generate the owned synthetic demonstration, then reload this page to inspect a persisted run.", loadRuns);
        return;
      }
      state.runs.forEach((run) => {
        const option = node("option", "", run.run_id);
        option.value = run.run_id;
        selector.append(option);
      });
      selector.disabled = false;
      const requested = new URLSearchParams(location.search).get("run");
      const selected = state.runs.find((run) => run.run_id === requested) || state.runs[0];
      selector.value = selected.run_id;
      await loadRun(selected.run_id, true);
    } catch (error) {
      showGlobal("error", "Unable to read local runs", error.message, loadRuns);
    }
  }

  async function loadRun(runId, initial = false) {
    const request = ++state.loading;
    showGlobal("loading", "Opening replay evidence", "Reading the report, decision traces, and evaluation artifacts.");
    try {
      const report = await fetchJSON(`/api/runs/${encodeURIComponent(runId)}`);
      if (request !== state.loading) return;
      state.report = report;
      state.filter = "all";
      state.query = "";
      state.page = 0;
      const params = new URLSearchParams(location.search);
      const requestedTransaction = initial ? params.get("transaction") : null;
      state.selected = decisions().some((row) => row.transaction_id === requestedTransaction) ? requestedTransaction : null;
      $("#transaction-search").value = "";
      $("#global-message").hidden = true;
      $("#report-content").hidden = false;
      $("#export-menu").hidden = false;
      renderOverview();
      renderDecisionTable();
      renderComparison();
      renderModels();
      renderIntegrity();
      setView(initial && viewCopy[params.get("view")] ? params.get("view") : state.view);
      ["json", "csv", "html"].forEach((format) => {
        const link = $(`#export-${format}`);
        link.href = embeddedNode ? { json: "report.json", csv: "decisions.csv", html: "report.html" }[format] : `/api/runs/${encodeURIComponent(runId)}/export?format=${format}`;
        link.setAttribute("download", "");
      });
      document.title = `RiskReplay · ${viewCopy[state.view][0]}`;
    } catch (error) {
      if (request === state.loading) showGlobal("error", "This run could not be opened", error.message, () => loadRun(runId));
    }
  }

  function renderOverview() {
    const report = state.report;
    const rows = decisions();
    const summary = report.summary || {};
    const total = summary.total ?? rows.length;
    const counts = Object.fromEntries(["matched", "mismatched", "incomplete"].map((status) => [status, summary[status] ?? rows.filter((row) => row.status === status).length]));
    const changedCount = summary.changed ?? rows.filter(changed).length;
    const metrics = [
      ["matched", "Matched", counts.matched, "check", `${number(counts.matched + counts.mismatched)} reconstructable decisions`],
      ["mismatched", "Mismatched", counts.mismatched, "compare", "Original decision differs from replay"],
      ["incomplete", "Incomplete", counts.incomplete, "alert", "Historical evidence is missing"],
      ["changed", "Candidate changes", changedCount, "replay", "Decision differences · outcomes may be unknown"],
    ];
    const grid = $("#summary-metrics");
    grid.replaceChildren();
    metrics.forEach(([kind, label, value, glyph, note]) => {
      const card = node("article", `metric-card ${kind}`);
      const top = node("div", "metric-top");
      top.append(node("span", "", label), icon(glyph));
      const metricValue = node("div", "metric-value", number(value));
      if (kind === "matched") metricValue.append(node("span", "metric-ratio", `/ ${number(total)}`));
      card.append(top, metricValue, node("p", "metric-bottom", note));
      grid.append(card);
    });
    const synthetic = report.mode === "owned_synthetic" || String(report.mode || "").includes("synthetic");
    $("#mode-label").textContent = embeddedNode ? "SAVED LOCAL RUN" : synthetic ? "OWNED SYNTHETIC DEMO" : human(report.mode || "MODE UNAVAILABLE").toUpperCase();
    $("#dataset-kind").textContent = synthetic ? "OWNED SYNTHETIC" : human(report.mode || "UNAVAILABLE").toUpperCase();
    $("#information-regime").textContent = report.information_regime ? valueText(report.information_regime) : "Information regime was not recorded. Interpret this run as incomplete evidence.";
    $("#evidence-heading").textContent = synthetic ? "Synthetic data. Real temporal boundaries." : "Historical evidence, explicit boundaries";
    $("#run-context-text").textContent = `${number(total)} decisions · ${number(summary.mature)} mature labels · ${number(summary.immature)} immature labels · ${number(summary.declined_unobserved)} declined outcomes · ${number(summary.unobserved)} other unobserved · ${number(summary.missing_state)} missing historical state · All times UTC`;
    $("#report-identity").textContent = `${report.run_id} · dataset ${shortHash(report.dataset_hash)}`;
    $("#report-identity").title = report.dataset_hash || "Dataset hash unavailable";
    $("#decision-count").textContent = number(rows.length);
    $("#count-all").textContent = number(rows.length);
    ["matched", "mismatched", "incomplete"].forEach((status) => { $(`#count-${status}`).textContent = number(rows.filter((row) => row.status === status).length); });
  }

  function filteredDecisions() {
    const priorities = { incomplete: 0, mismatched: 1, matched: 3 };
    return decisions().filter((row) => (state.filter === "all" || row.status === state.filter) && `${row.transaction_id} ${row.cohort || ""}`.toLowerCase().includes(state.query.toLowerCase()))
      .sort((a, b) => ((changed(a) && a.status === "matched" ? 2 : priorities[a.status] ?? 4) - (changed(b) && b.status === "matched" ? 2 : priorities[b.status] ?? 4)) || String(a.decision_time).localeCompare(String(b.decision_time)) || String(a.transaction_id).localeCompare(String(b.transaction_id)));
  }

  function renderDecisionTable() {
    const rows = filteredDecisions();
    const lastPage = Math.max(0, Math.ceil(rows.length / pageSize) - 1);
    state.page = Math.min(state.page, lastPage);
    if (!rows.some((row) => row.transaction_id === state.selected)) state.selected = rows[0]?.transaction_id ?? null;
    const visible = rows.slice(state.page * pageSize, (state.page + 1) * pageSize);
    const body = $("#decision-rows");
    body.replaceChildren();
    visible.forEach((row) => {
      const tr = node("tr", row.transaction_id === state.selected ? "selected" : "");
      tr.dataset.transaction = row.transaction_id;
      const idCell = node("td");
      const button = node("button", "transaction-link", row.transaction_id);
      button.setAttribute("aria-label", `Inspect transaction ${row.transaction_id}, ${human(row.status)}`);
      button.setAttribute("aria-pressed", String(row.transaction_id === state.selected));
      const meta = [numeric(row.amount) ? number(row.amount, 2) : null, row.cohort ? human(row.cohort) : date(row.decision_time, true)].filter(Boolean).join(" · ");
      idCell.append(button, node("div", "transaction-meta", meta));
      const actionCell = node("td");
      const pair = node("div", "action-pair");
      pair.append(actionElement(row.recorded_action), node("span", "action-arrow", "→"), actionElement(row.replayed_action));
      actionCell.append(pair);
      const statusCell = node("td");
      statusCell.append(statusPill(row.status));
      const candidateCell = node("td", "candidate-cell");
      candidateCell.append(actionElement(row.candidate_action));
      if (changed(row)) {
        const mark = node("span", "changed-indicator");
        mark.title = "Candidate action differs";
        mark.setAttribute("aria-label", "Candidate action differs");
        candidateCell.append(mark);
      }
      tr.append(idCell, actionCell, statusCell, candidateCell);
      tr.addEventListener("click", () => selectTransaction(row.transaction_id));
      body.append(tr);
    });
    $("#table-empty").hidden = rows.length > 0;
    $("#pagination-label").textContent = rows.length ? `${number(state.page * pageSize + 1)}–${number(Math.min((state.page + 1) * pageSize, rows.length))} of ${number(rows.length)} decisions` : "0 decisions";
    $("#page-prev").disabled = state.page === 0;
    $("#page-next").disabled = state.page >= lastPage;
    $$(".filter-tab").forEach((button) => {
      const active = button.dataset.filter === state.filter;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    renderIncident();
    updateURL();
  }

  function selectTransaction(id, navigate = false) {
    state.selected = id;
    if (navigate) {
      state.filter = "all";
      state.query = "";
      $("#transaction-search").value = "";
      state.page = Math.max(0, Math.floor(filteredDecisions().findIndex((row) => row.transaction_id === id) / pageSize));
      setView("review");
    }
    renderDecisionTable();
    if (navigate || matchMedia("(max-width: 1220px)").matches) $(".incident-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function sectionHeading(title, detail) {
    const header = node("div", "detail-section-heading");
    header.append(node("h3", "", title));
    if (detail) header.append(node("span", "", detail));
    return header;
  }

  function callout(title, message, evidence = false) {
    const box = node("div", `callout${evidence ? " evidence" : ""}`);
    const heading = node("div", "callout-title");
    heading.append(icon(evidence ? "info" : "alert"), node("span", "", title));
    box.append(heading, node("p", "", message));
    return box;
  }

  function renderIncident() {
    const row = decisions().find((item) => item.transaction_id === state.selected);
    $("#incident-empty").hidden = Boolean(row);
    $("#incident-content").hidden = !row;
    if (!row) return;
    $("#incident-id").textContent = row.transaction_id;
    $("#incident-status").replaceChildren(statusPill(row.status));
    $("#incident-meta").textContent = [numeric(row.amount) ? `Amount ${number(row.amount, 2)}` : null, row.cohort ? human(row.cohort) : null, human(row.label_status)].filter(Boolean).join(" · ");
    renderTrace(row);
    renderFeatures(row);
    renderTimeline(row);
    setDetail(state.detail, false);
  }

  function renderTrace(row) {
    const container = $("#incident-trace");
    container.replaceChildren();
    const cutoff = node("div", "cutoff-card");
    const time = node("time", "", row.decision_time ? String(row.decision_time).replace("T", " ").replace(/Z$/, " UTC") : "Time unavailable");
    if (row.decision_time) time.dateTime = row.decision_time;
    cutoff.append(node("span", "field-label", "Knowledge cutoff"), time, node("p", "", numeric(row.cutoff_seq) ? `Inclusive boundary: event_time ≤ decision_time and (available_at, delivery_seq) ≤ (decision_time, ${row.cutoff_seq}).` : "The delivery sequence is unavailable; the exact boundary for tied timestamps was not recorded."));
    const flow = node("div", "decision-flow");
    const recorded = node("div");
    recorded.append(node("span", "field-label", "Recorded"), actionElement(row.recorded_action, "flow-action"), node("span", "score-value", `Score ${score(row.original_score)}`));
    const replayed = node("div");
    replayed.append(node("span", "field-label", "Replayed"), actionElement(row.replayed_action, "flow-action"), node("span", "score-value", row.status === "incomplete" ? "Evidence incomplete" : "Original policy"));
    flow.append(recorded, icon("arrow"), replayed);
    const candidate = node("div", "candidate-strip");
    const candidateResult = node("div");
    candidateResult.append(node("span", "flow-action", human(row.candidate_action)), node("span", "score-value", `Score ${score(row.candidate_score)}`));
    candidate.append(node("div", "", "Candidate policy"), candidateResult);
    container.append(cutoff, flow, candidate);
    if (Array.isArray(row.missing) && row.missing.length) container.append(callout("Reconstruction is incomplete", row.missing.map(human).join(" · ")));
    if (row.first_divergence) container.append(callout("First consequential divergence", valueText(row.first_divergence), row.status !== "incomplete"));
    if (row.recorded_action === "decline" || String(row.label_status).includes("declined")) container.append(callout("Outcome under approval is unknown", "This recorded decline has no observed approval outcome. An action change does not establish recovered revenue or avoided fraud."));
    const explanation = Array.isArray(row.explanation) ? row.explanation : [];
    container.append(sectionHeading("Explanation trace", `${explanation.length} recorded steps`));
    const list = node("ol", "trace-list");
    explanation.forEach((item, index) => {
      const trace = typeof item === "string" ? { kind: "evidence", message: item } : item;
      const li = node("li", "trace-item");
      const copy = node("div");
      copy.append(node("span", "trace-kind", human(trace.kind)), node("p", "", trace.message || valueText(trace)));
      li.append(node("span", "trace-number", index + 1), copy);
      list.append(li);
    });
    if (!explanation.length) container.append(node("p", "feature-intro", "No explanation trace was persisted for this decision."));
    else container.append(list);
    const versions = row.versions || {};
    const grid = node("div", "version-grid");
    ["original_policy", "candidate_policy", "feature", "model", "rules"].forEach((key) => {
      const field = node("div");
      field.append(node("span", "field-label", human(key)), node("div", "version-value", valueText(versions[key])));
      grid.append(field);
    });
    container.append(grid);
  }

  function renderFeatures(row) {
    const container = $("#incident-features");
    container.replaceChildren(node("p", "feature-intro", "Reconstructed values at the original knowledge cutoff. Source IDs identify the events that contributed to each feature."));
    const entries = Object.entries(row.features || {});
    if (!entries.length) container.append(callout("Feature state unavailable", "No reconstructed feature values were persisted. Missing history is not replaced with current state."));
    entries.forEach(([key, value]) => {
      const block = node("div", "feature-item");
      const line = node("div", "feature-line");
      line.append(node("span", "feature-name", key), node("span", "feature-value", valueText(value)));
      const sources = row.provenance?.[key];
      block.append(line, node("p", "feature-source", Array.isArray(sources) && sources.length ? `Sources: ${sources.join(" · ")}` : "No contributing event IDs recorded."));
      container.append(block);
    });
  }

  function renderTimeline(row) {
    const container = $("#incident-timeline");
    container.replaceChildren(node("p", "timeline-intro", "Event time describes what happened. Availability time describes when it could be known. Delivery sequence breaks ties deterministically."));
    const items = Array.isArray(row.timeline) ? row.timeline : [];
    if (!items.length) { container.append(callout("Timeline unavailable", "No historical event timeline was persisted for this decision.")); return; }
    const list = node("ol", "timeline");
    items.forEach((event) => {
      const included = event.included === true;
      const item = node("li", `timeline-item${included ? "" : " excluded"}`);
      const header = node("div", "timeline-event-header");
      header.append(node("span", "timeline-event-title", human(event.event_type)), node("span", "timeline-inclusion", included ? "Included" : "Excluded"));
      const times = node("div", "timeline-times");
      times.append(node("span", "", "Event time"), node("time", "", date(event.event_time)), node("span", "", "Available"), node("time", "", date(event.available_at)), node("span", "", "Sequence"), node("span", "", valueText(event.delivery_seq)));
      item.append(header, node("p", "timeline-id", event.event_id), times, node("p", "timeline-reason", event.reason || "No inclusion reason recorded."));
      if (event.payload && Object.keys(event.payload).length) {
        const detail = node("details", "payload-details");
        detail.append(node("summary", "", "Inspect event payload"), node("pre", "", JSON.stringify(event.payload, null, 2)));
        item.append(detail);
      }
      list.append(item);
    });
    container.append(list);
  }

  function setDetail(detail, focus = false) {
    if (!["trace", "features", "timeline"].includes(detail)) detail = "trace";
    state.detail = detail;
    $$(".detail-tab").forEach((button) => {
      const active = button.dataset.detail === detail;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
      if (active && focus) button.focus();
    });
    ["trace", "features", "timeline"].forEach((name) => { $(`#incident-${name}`).hidden = detail !== name; });
  }

  function setView(view) {
    if (!viewCopy[view]) view = "review";
    state.view = view;
    $("#view-title").textContent = viewCopy[view][0];
    $("#view-description").textContent = viewCopy[view][1];
    $$(".nav-item").forEach((button) => {
      const active = button.dataset.view === view;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
    });
    Object.keys(viewCopy).forEach((name) => { $(`#view-${name}`).hidden = view !== name; });
    document.title = `RiskReplay · ${viewCopy[view][0]}`;
    if (state.report) updateURL();
  }

  function panel(title, description) {
    const block = node("section", "panel");
    const heading = node("div", "panel-heading");
    const copy = node("div");
    copy.append(node("h2", "", title));
    if (description) copy.append(node("p", "", description));
    heading.append(copy);
    block.append(heading);
    return block;
  }

  function dataTable(headers) {
    const wrapper = node("div", "table-scroll");
    const table = node("table", "data-table");
    const head = node("thead");
    const row = node("tr");
    headers.forEach((title) => { const th = node("th", "", title); th.scope = "col"; row.append(th); });
    head.append(row);
    const body = node("tbody");
    table.append(head, body);
    wrapper.append(table);
    return { wrapper, body };
  }

  function emptyPanel(title, message) {
    const block = node("div", "panel empty-panel");
    block.append(node("h2", "", title), node("p", "", message));
    return block;
  }

  function renderComparison() {
    const target = $("#comparison-content");
    const rows = decisions();
    target.replaceChildren();
    if (!rows.length) { target.append(emptyPanel("No policies to compare", "This run contains no decision records. Import and replay a valid dataset to inspect policy differences.")); return; }
    const cards = node("div", "two-columns");
    [["Recorded policies", "original_policy", "recorded_action"], ["Candidate policy", "candidate_policy", "candidate_action"]].forEach(([label, versionKey, key], index) => {
      const card = node("article", `panel policy-card${index ? " candidate-policy" : ""}`);
      const groups = new Map();
      rows.forEach((row) => {
        const identity = row.versions?.[versionKey] || null;
        if (!groups.has(identity)) groups.set(identity, []);
        groups.get(identity).push(row);
      });
      const identities = Array.from(groups.keys()).filter(Boolean);
      const artifactDetails = node("details", "payload-details");
      artifactDetails.append(node("summary", "", `Inspect ${number(identities.length)} version ${identities.length === 1 ? "identity" : "identities"}${groups.has(null) ? " and missing manifest references" : ""}`));
      groups.forEach((associated, identity) => {
        const artifact = node("div", "artifact-row");
        artifact.append(node("span", "field-label", `${number(associated.length)} associated decisions`), node("div", "hash-value", identity || "Policy manifest identity was not recorded."));
        const gaps = Array.from(new Set(associated.filter((row) => index ? row.candidate_action == null : row.status === "incomplete").flatMap((row) => Array.isArray(row.missing) ? row.missing : [])));
        if (gaps.length) artifact.append(node("p", "unknown-label", `Evidence gaps on associated decisions: ${gaps.join(" · ")}`));
        artifactDetails.append(artifact);
      });
      const summary = node("div", "policy-summary");
      ["approve", "review", "decline"].forEach((action) => {
        const item = node("div");
        item.append(node("strong", "", number(rows.filter((row) => row[key] === action).length)), node("span", "", human(action)));
        summary.append(item);
      });
      const versionTitle = identities.length > 1 ? `${number(identities.length)} recorded versions` : identities.length === 1 ? shortHash(identities[0]) : "Version unavailable";
      card.append(node("span", "field-label", label), node("h3", "", versionTitle), node("p", "", index ? "Executed against the historical information regime stated above." : "Original policy references for every decision, including archives with missing dependencies."), artifactDetails, summary);
      cards.append(card);
    });
    target.append(cards);
    const different = rows.filter(changed);
    const changedPanel = panel(`Changed actions · ${number(different.length)}`, "Decision differences do not identify outcomes under an alternative action.");
    changedPanel.classList.add("spaced-panel");
    const { wrapper, body } = dataTable(["Transaction", "Original → Candidate", "First divergence", "Evidence support"]);
    different.slice(0, 150).forEach((row) => {
      const tr = node("tr");
      const id = node("td");
      const link = node("button", "transaction-link", row.transaction_id);
      link.addEventListener("click", () => selectTransaction(row.transaction_id, true));
      id.append(link, node("div", "transaction-meta", human(row.cohort)));
      const action = node("td");
      const pair = node("div", "action-pair");
      pair.append(actionElement(row.replayed_action ?? row.recorded_action), node("span", "action-arrow", "→"), actionElement(row.candidate_action));
      action.append(pair);
      const evidence = node("td", row.recorded_action === "decline" ? "unknown-label" : "", row.recorded_action === "decline" ? "Approval outcome unknown" : human(row.label_status));
      tr.append(id, action, node("td", "trace-excerpt", valueText(row.first_divergence || "No consequential divergence explanation recorded.")), evidence);
      body.append(tr);
    });
    changedPanel.append(wrapper);
    if (!different.length) changedPanel.append(node("p", "table-note", "No changed actions were recorded in this run."));
    if (different.length > 150) changedPanel.append(node("p", "table-note", "Showing the first 150 changes. The JSON and CSV exports contain every decision."));
    target.append(changedPanel);
    const boundary = node("div", "callout comparison-boundary");
    const copy = node("div");
    copy.append(node("strong", "", "A policy difference is not a counterfactual outcome."), node("p", "", "Recorded declines usually do not reveal outcomes under approval. Observed labels and the generator's synthetic oracle remain separate. This report does not estimate recovered revenue or avoided fraud loss."));
    boundary.append(icon("info"), copy);
    target.append(boundary);
  }

  function renderModels() {
    const target = $("#model-content");
    const evaluation = state.report.evaluation;
    target.replaceChildren();
    if (!evaluation || !evaluation.models || !Object.keys(evaluation.models).length) {
      target.append(emptyPanel("Model evidence is unavailable", "No trained-model evaluation artifact was included in this run. Decision replay results remain inspectable; model quality cannot be inferred from replay agreement."));
      return;
    }
    const counts = evaluation.splits?.test || Object.values(evaluation.models)[0]?.metrics?.counts || {};
    const maturity = node("div", "maturity-grid");
    [
      ["Mature observed", counts.mature_observed, "Known labels; feature coverage checked separately"],
      ["Immature labels", counts.immature, "Not yet known at label cutoff"],
      ["Declined outcomes", counts.declined_unobserved, "Approval outcome is unknown"],
      ["Other unobserved", counts.unobserved, "No observed outcome available"],
      ["Held-out transactions", counts.total, "All test decisions, including unknowns"],
      ["Missing historical state", counts.missing_state, "Overlaps label status; excluded from model metrics"],
    ].forEach(([label, count, note]) => {
      const card = node("div", "maturity-card");
      card.append(node("span", "field-label", label), node("strong", "", number(count)), node("p", "", note));
      maturity.append(card);
    });
    target.append(maturity);
    const modelPanel = panel("Held-out model comparison", "Only mature observed labels with reconstructed features contribute to PR-AUC, calibration, precision, and recall.");
    const modelEntries = Object.entries(evaluation.models);
    if (evaluation.rules_baseline) modelEntries.unshift(["rules", evaluation.rules_baseline]);
    const { wrapper, body } = dataTable(["Model", "PR-AUC", "Avg. precision", "Brier score", "Review precision", "Review recall"]);
    modelEntries.forEach(([key, model]) => {
      const metrics = model.metrics || {};
      const review = metrics.review || {};
      const tr = node("tr");
      const modelCell = node("td");
      modelCell.append(node("div", "model-name", key === "gradient_boosted" ? "Gradient boosted" : key === "logistic" ? "Logistic baseline" : human(key)), node("div", "model-kind", key === "rules" ? "Fixed heuristic scores · uncalibrated" : "Trained on chronological data"));
      if (numeric(metrics.metric_n)) modelCell.append(node("div", "metric-note", `${number(metrics.metric_n)} / ${number(metrics.counts?.mature_observed ?? counts.mature_observed)} mature labels scored`));
      tr.append(modelCell);
      [metrics.pr_auc, metrics.average_precision, metrics.brier_score].forEach((value) => tr.append(node("td", "table-number", numeric(value) ? number(value, 4) : "Unavailable")));
      const precision = node("td", "table-number", percent(review.precision));
      precision.append(node("div", "metric-note", `${number(review.observed_fraud_selected)} / ${number(review.precision_denominator)} observed reviewed`));
      const recall = node("td", "table-number", percent(review.recall));
      recall.append(node("div", "metric-note", `${number(review.observed_fraud_selected)} / ${number(review.observed_fraud_denominator)} observed fraud`));
      tr.append(precision, recall);
      body.append(tr);
    });
    modelPanel.append(wrapper);
    const review = modelEntries[0]?.[1]?.metrics?.review || {};
    modelPanel.append(node("p", "table-note", `Fixed review capacity: ${percent(review.capacity_fraction, 0)} of all ${number(review.capacity_denominator_all_test_transactions)} test transactions (${number(review.capacity_slots_global)} slots). Precision covers reviewed transactions with observed mature labels; unknown selected outcomes are excluded from its denominator.`));
    target.append(modelPanel);
    const calibrationPanel = panel("Calibration evidence", "Persisted fitting status and held-out reliability on mature observed labels. Empty bins have no estimated fraud rate.");
    calibrationPanel.classList.add("spaced-panel");
    const calibrationList = node("div", "check-list");
    modelEntries.forEach(([key, model]) => {
      const block = node("article", "artifact-row");
      const name = key === "gradient_boosted" ? "Gradient boosted" : key === "logistic" ? "Logistic baseline" : human(key);
      block.append(node("h3", "model-name", name));
      const status = key === "rules" ? "Fixed heuristic scores; no probability calibration fitted. Brier score and reliability bins describe these score assignments." : model.calibration?.status || "Calibration status unavailable: no fitting record was persisted.";
      block.append(node("p", "model-kind", status));
      if (key !== "rules" && model.calibration) block.append(node("p", "metric-note", `Calibration labels used: ${number(model.calibration.n)} · Method: ${model.calibration.method || "None fitted"}`));
      const bins = model.metrics?.reliability_bins;
      if (!Array.isArray(bins) || !bins.length) {
        block.append(node("p", "metric-note", "Reliability bins unavailable: no held-out bin evidence was persisted."));
      } else {
        const detail = node("details", "payload-details");
        detail.append(node("summary", "", `Inspect ${number(bins.length)} reliability bins`));
        const { wrapper: binTable, body: binBody } = dataTable(["Score bin", "Mature labels", "Observed fraud", "Mean prediction", "Observed fraud rate"]);
        bins.forEach((bin) => {
          const tr = node("tr");
          const bounds = `[${number(bin.lower, 1)}, ${number(bin.upper, 1)}${bin.upper_inclusive ? "]" : ")"}`;
          tr.append(node("td", "table-number", bounds), node("td", "table-number", number(bin.count)), node("td", "table-number", number(bin.observed_fraud)), node("td", "table-number", numeric(bin.mean_prediction) ? number(bin.mean_prediction, 4) : "Unavailable"), node("td", "table-number", percent(bin.fraud_rate)));
          binBody.append(tr);
        });
        detail.append(binTable);
        block.append(detail);
      }
      calibrationList.append(block);
    });
    calibrationPanel.append(calibrationList);
    target.append(calibrationPanel);
    const columns = node("div", "two-columns spaced-panel");
    const splitPanel = panel("Chronological boundaries", "Training, validation, and final test are separate periods.");
    const splitList = node("ul", "split-list");
    ["train", "validation", "test"].forEach((name) => {
      const split = evaluation.splits?.[name] || {};
      const item = node("li");
      const content = node("div");
      content.append(node("div", "split-name", name), node("div", "split-dates", `${number(split.mature_observed)} mature observed · ${number(split.observed_fraud)} observed fraud`));
      if (numeric(split.missing_state)) content.append(node("div", "split-dates", `${number(split.missing_state)} missing historical state · excluded from fitting and scoring`));
      if (split.label_cutoff_inclusive) content.append(node("div", "split-dates", `Label cutoff: ${date(split.label_cutoff_inclusive)}`));
      item.append(content, node("span", "split-count", number(split.total)));
      splitList.append(item);
    });
    splitPanel.append(splitList);
    const artifactPanel = panel("Reproducible artifacts", "Dataset, feature, and trained model identities.");
    const artifacts = node("div", "artifact-list");
    [["Dataset", evaluation.dataset_hash || state.report.dataset_hash], ["Feature schema", evaluation.feature_schema_hash], ["Training code", evaluation.code_hash], ...Object.entries(evaluation.models).map(([name, model]) => [`${human(name)} artifact`, model.file_hash || model.artifact_hash]), ["Deterministic seed", evaluation.seed]].forEach(([label, value]) => {
      const item = node("div", "artifact-row");
      item.append(node("span", "field-label", label), node("div", "hash-value", valueText(value)));
      artifacts.append(item);
    });
    artifactPanel.append(artifacts);
    columns.append(splitPanel, artifactPanel);
    target.append(columns);
    renderCohorts(target, modelEntries);
    const assumptions = Array.isArray(evaluation.assumptions) ? evaluation.assumptions : [];
    if (assumptions.length) {
      const assumptionPanel = panel("Evaluation assumptions", "Interpret metrics within these evidence limits.");
      assumptionPanel.classList.add("spaced-panel");
      const list = node("ul", "assumptions-list");
      assumptions.forEach((item) => list.append(node("li", "", valueText(item))));
      assumptionPanel.append(list);
      target.append(assumptionPanel);
    }
  }

  function renderCohorts(target, entries) {
    const boosted = entries.find(([name]) => name === "gradient_boosted")?.[1];
    if (!boosted?.cohorts || !Object.keys(boosted.cohorts).length) return;
    const block = panel("Gradient-boosted model · cohort evidence", "Metrics use scored mature labels. Missing historical state overlaps label status and is excluded from scoring.");
    block.classList.add("spaced-panel");
    const { wrapper, body } = dataTable(["Cohort", "All transactions", "Mature observed", "Observed fraud", "PR-AUC", "Brier score"]);
    Object.entries(boosted.cohorts).forEach(([name, metrics]) => {
      const tr = node("tr");
      const population = node("td", "table-number", number(metrics.counts?.total));
      if (numeric(metrics.counts?.missing_state)) population.append(node("div", "metric-note", `${number(metrics.counts.missing_state)} missing state`));
      const mature = node("td", "table-number", number(metrics.counts?.mature_observed));
      if (numeric(metrics.metric_n)) mature.append(node("div", "metric-note", `${number(metrics.metric_n)} scored mature labels`));
      tr.append(node("td", "", human(name)), population, mature, node("td", "table-number", number(metrics.counts?.observed_fraud)), node("td", "table-number", numeric(metrics.pr_auc) ? number(metrics.pr_auc, 4) : "Unavailable"), node("td", "table-number", numeric(metrics.brier_score) ? number(metrics.brier_score, 4) : "Unavailable"));
      body.append(tr);
    });
    block.append(wrapper);
    target.append(block);
  }

  function renderIntegrity() {
    const target = $("#integrity-content");
    target.replaceChildren();
    const integrity = state.report.integrity || {};
    const checks = Array.isArray(integrity.checks) ? integrity.checks : [];
    if (!checks.length) { target.append(emptyPanel("Integrity evidence is unavailable", "No temporal-integrity checks were persisted. Their absence is not a passing result.")); return; }
    const isPassed = (check) => check.passed === true || ["passed", "pass"].includes(check.status);
    const isUnavailable = (check) => check.status === "unavailable" || check.passed === null;
    const passed = checks.filter(isPassed).length;
    const unavailable = checks.filter(isUnavailable).length;
    const failed = checks.length - passed - unavailable;
    const summary = node("div", `integrity-summary${failed ? " has-failures" : ""}`);
    const copy = node("div");
    copy.append(node("h2", "", failed ? `${number(failed)} integrity checks need attention` : unavailable ? "Some integrity evidence is unavailable" : "Historical knowledge boundaries verified"), node("p", "", `${number(passed)} of ${number(checks.length)} persisted checks passed.${unavailable ? ` ${number(unavailable)} unavailable.` : ""} These checks apply to this run and its recorded fixtures.`));
    summary.append(icon(failed ? "alert" : "shield"), copy);
    target.append(summary);
    const columns = node("div", "two-columns");
    const checkPanel = panel("Temporal invariants", "Evidence persisted alongside this replay run.");
    const list = node("div", "check-list");
    checks.forEach((check) => {
      const passed = isPassed(check);
      const unavailable = isUnavailable(check);
      const row = node("article", `check-row${passed || unavailable ? "" : " failed"}`);
      const glyph = node("span", "check-icon");
      glyph.append(icon(passed ? "check" : "alert"));
      const copy = node("div", "check-copy");
      copy.append(node("h3", "", human(check.name || check.id || check.check || "Temporal check")), node("p", "", valueText(check.message || check.description || check.detail || check.details || check.evidence || "No explanation was persisted.")));
      if (check.denominator != null || check.violations != null) copy.append(node("span", "check-count", `${number(check.violations ?? 0)} violations / ${number(check.denominator)} examined`));
      row.append(glyph, copy, statusPill(unavailable ? "unavailable" : passed ? "passed" : "failed"));
      list.append(row);
    });
    checkPanel.append(list);
    const metadataPanel = panel("Run identity & execution", "Configuration and measured local performance.");
    const metadata = node("div", "integrity-metadata");
    const performance = state.report.performance || {};
    const records = [
      ["Run", state.report.run_id], ["Created", date(state.report.created_at)], ["Operating mode", human(state.report.mode)],
      ["Seed", state.report.config?.seed ?? state.report.evaluation?.seed],
      ["Comparison throughput", numeric(performance.comparisons_per_second) ? `${number(performance.comparisons_per_second, 1)} decisions/s` : numeric(performance.throughput_per_second) ? `${number(performance.throughput_per_second, 1)} decisions/s` : numeric(performance.decisions_per_second) ? `${number(performance.decisions_per_second, 1)} decisions/s` : null],
      ["Elapsed", numeric(performance.elapsed_seconds ?? performance.seconds) ? `${number(performance.elapsed_seconds ?? performance.seconds, 3)} s` : null],
      ["Median latency", numeric(performance.latency_p50_ms) ? `${number(performance.latency_p50_ms, 3)} ms` : null],
      ["95th percentile latency", numeric(performance.latency_p95_ms) ? `${number(performance.latency_p95_ms, 3)} ms` : null],
      ["Hardware", performance.hardware || performance.platform],
    ];
    records.filter(([, value]) => value != null).forEach(([label, value]) => {
      const row = node("div", "metadata-pair");
      row.append(node("span", "", label), node("strong", "", valueText(value)));
      metadata.append(row);
    });
    const hash = node("div", "artifact-row");
    hash.append(node("span", "field-label", "Dataset content hash"), node("p", "hash-value", valueText(state.report.dataset_hash)));
    metadata.append(hash);
    metadataPanel.append(metadata);
    columns.append(checkPanel, metadataPanel);
    target.append(columns);
    const agreement = integrity.online_offline;
    if (agreement?.n) {
      target.append(callout("Independent feature agreement", `${number(agreement.matched)} / ${number(agreement.n)} streaming snapshots matched historical reconstruction before injected evidence defects. ${agreement.scope}`));
    }
    const baselines = Array.isArray(state.report.baselines) ? state.report.baselines : [];
    if (baselines.length) {
      const baselinePanel = panel("Replay baselines", "Current-state and event-time-only replays reveal different failure modes.");
      baselinePanel.classList.add("spaced-panel");
      const { wrapper, body } = dataTable(["Information regime", "Action agreement", "Feature agreement", "Incomplete", "Evidence / interpretation"]);
      baselines.forEach((baseline) => {
        const metrics = baseline.summary || baseline;
        const tr = node("tr");
        tr.append(node("td", "", human(baseline.name || baseline.regime || baseline.mode)), node("td", "table-number", `${number(metrics.action_matches ?? metrics.matched)} / ${number(metrics.n)} · ${percent(metrics.action_agreement)}`), node("td", "table-number", `${number(metrics.feature_matches)} / ${number(metrics.n)} · ${percent(metrics.feature_agreement)}`), node("td", "table-number", number(metrics.incomplete)), node("td", "trace-excerpt", valueText(baseline.description || baseline.information_regime || baseline.note || "See the JSON export for raw baseline evidence.")));
        body.append(tr);
      });
      baselinePanel.append(wrapper);
      target.append(baselinePanel);
    }
  }

  $("#run-select").addEventListener("change", (event) => loadRun(event.target.value));
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
  $("#view-integrity-link").addEventListener("click", () => setView("integrity"));
  $$(".filter-tab").forEach((button) => button.addEventListener("click", () => { state.filter = button.dataset.filter; state.page = 0; state.selected = null; renderDecisionTable(); }));
  $("#transaction-search").addEventListener("input", (event) => { state.query = event.target.value; state.page = 0; renderDecisionTable(); });
  $("#clear-filters").addEventListener("click", () => { state.filter = "all"; state.query = ""; state.page = 0; $("#transaction-search").value = ""; renderDecisionTable(); });
  $("#page-prev").addEventListener("click", () => { state.page -= 1; renderDecisionTable(); });
  $("#page-next").addEventListener("click", () => { state.page += 1; renderDecisionTable(); });
  $$(".detail-tab").forEach((button, index, buttons) => {
    button.addEventListener("click", () => setDetail(button.dataset.detail));
    button.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
      setDetail(buttons[next].dataset.detail, true);
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName) && state.view === "review" && state.report) { event.preventDefault(); $("#transaction-search").focus(); }
    if (event.key === "Escape") $("#export-menu").open = false;
  });
  document.addEventListener("click", (event) => { if (!$("#export-menu").contains(event.target)) $("#export-menu").open = false; });
  if (embeddedNode) {
    $(".brand").href = "inspector.html";
    $(".sidebar-bottom p").textContent = "Saved report artifact. Every decision keeps its evidence.";
  }
  loadRuns();
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bootRiskReplay, { once: true });
else bootRiskReplay();
