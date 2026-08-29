const COLORS = {
  abxbus: "#71b7ff",
  abxpkg: "#c19aff",
  "abx-plugins": "#61d8d6",
  "abx-dl": "#f4c95d",
  archivebox: "#ff8b3d",
};

const METRICS = {
  duration: { title: "CI wall time", format: formatDuration, runValue: (run) => run.duration_ms },
  tests: { title: "Test executions", format: formatNumber, runValue: (run) => run.tests?.total },
  average: { title: "Average per test", format: formatDuration, runValue: (run) => run.tests?.avg_duration_ms },
  slowest: { title: "Slowest test", format: formatDuration, runValue: (run) => run.tests?.slowest?.duration_ms },
  pypi: { title: "PyPI wheel size", format: formatBytes, registry: "pypi" },
  dockerBuild: { title: "Docker build time", format: formatDuration, runValue: (run) => run.docker_build_ms },
  dockerSize: { title: "Docker compressed size", format: formatBytes, registry: "docker" },
  ttfi: { title: "Time to first import", format: formatDuration, runValue: (run) => run.ttfi_ms },
};

const state = {
  data: null,
  projects: new Set(Object.keys(COLORS)),
  branch: "all",
  status: "all",
  window: 30,
  metric: "duration",
  query: "",
  limit: 50,
};

const $ = (selector) => document.querySelector(selector);
const els = {
  projectPills: $("#projectPills"), branch: $("#branchSelect"), status: $("#statusSelect"),
  window: $("#windowSelect"), metric: $("#metricSelect"), search: $("#searchInput"),
  chart: $("#trendChart"), chartEmpty: $("#chartEmpty"), legend: $("#chartLegend"),
  body: $("#runsBody"), rowCount: $("#rowCount"), showMore: $("#showMore"),
  dialog: $("#runDialog"), jobs: $("#jobsList"), sync: $("#syncStatus"),
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
}

function safeUrl(value) {
  try { const url = new URL(value); return url.protocol === "https:" ? url.href : "#"; } catch { return "#"; }
}

function formatNumber(value) {
  if (value == null) return "—";
  return new Intl.NumberFormat("en", { notation: value >= 10000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(value);
}

function formatDuration(ms) {
  if (ms == null) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)}s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.round((ms % 60000) / 1000);
  return `${minutes}m ${seconds}s`;
}

function formatBytes(bytes) {
  if (bytes == null) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes, index = 0;
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
  return `${value.toFixed(index > 1 ? 1 : 0)}${units[index]}`;
}

function formatAge(value) {
  const delta = Math.max(0, Date.now() - new Date(value).getTime());
  const minutes = Math.floor(delta / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function formatDate(value) {
  if (!value) return "unknown";
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(new Date(value));
}

function statusClass(run) {
  if (run.status !== "completed") return "active";
  if (run.conclusion === "success") return "success";
  if (["cancelled", "skipped", "neutral"].includes(run.conclusion)) return "cancelled";
  return "failure";
}

function projectRecord(slug) { return state.data.projects.find((project) => project.slug === slug) || {}; }

function inWindow(date, days = state.window) {
  return new Date(date).getTime() >= Date.now() - days * 86400000;
}

function filteredRuns() {
  const query = state.query.toLowerCase();
  return state.data.runs.filter((run) => {
    if (!state.projects.has(run.project) || !inWindow(run.started_at)) return false;
    if (state.branch !== "all" && run.branch !== state.branch) return false;
    if (state.status !== "all" && statusClass(run) !== state.status) return false;
    if (query) {
      const haystack = [run.project, run.branch, run.title, run.workflow, ...(run.jobs || []).map((job) => job.name)].join(" ").toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });
}

function renderPills() {
  els.projectPills.innerHTML = state.data.projects.map((project) => `
    <button type="button" class="project-pill ${state.projects.has(project.slug) ? "active" : ""}"
      data-project="${escapeHtml(project.slug)}" style="--project-color:${COLORS[project.slug]}">${escapeHtml(project.slug)}</button>
  `).join("");
}

function renderBranches() {
  const current = state.branch;
  const branches = [...new Set(state.data.runs.filter((run) => state.projects.has(run.project)).map((run) => run.branch))].sort();
  els.branch.innerHTML = `<option value="all">All branches</option>${branches.map((branch) => `<option value="${escapeHtml(branch)}">${escapeHtml(branch)}</option>`).join("")}`;
  state.branch = branches.includes(current) ? current : "all";
  els.branch.value = state.branch;
}

function median(values) {
  const sorted = values.filter((value) => value != null).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function renderSummary(runs) {
  const latest = new Map();
  for (const run of runs) if (!latest.has(run.project) && run.status === "completed") latest.set(run.project, run);
  const healthy = [...latest.values()].filter((run) => run.conclusion === "success").length;
  $("#healthValue").textContent = `${healthy} / ${state.projects.size}`;
  $("#healthNote").textContent = healthy === state.projects.size ? "all selected projects green" : "latest completed runs";
  const tests = runs.reduce((sum, run) => sum + (run.tests?.total || 0), 0);
  $("#testsValue").textContent = formatNumber(tests);
  $("#testsNote").textContent = `${runs.filter((run) => run.tests?.total).length} runs with parsed counts`;
  $("#durationValue").textContent = formatDuration(median(runs.map((run) => run.duration_ms)));
  const expected = runs.reduce((sum, run) => sum + (run.tests?.jobs_expected || 0), 0);
  const reported = runs.reduce((sum, run) => sum + (run.tests?.jobs_reported || 0), 0);
  $("#coverageValue").textContent = expected ? `${Math.round(reported / expected * 100)}%` : "—";
  $("#coverageNote").textContent = `${formatNumber(reported)} / ${formatNumber(expected)} test jobs`;
}

function metricCell(value, formatter, title = "") {
  return value == null ? `<span class="missing" title="Not reported by this run">—</span>` : `<span title="${escapeHtml(title)}">${formatter(value)}</span>`;
}

function renderTable(runs) {
  els.rowCount.textContent = `${formatNumber(runs.length)} runs`;
  els.showMore.hidden = runs.length <= state.limit;
  const visible = runs.slice(0, state.limit);
  if (!visible.length) {
    els.body.innerHTML = `<tr><td colspan="11" class="empty-row">No CI runs match this slice.</td></tr>`;
    return;
  }
  els.body.innerHTML = visible.map((run) => {
    const project = projectRecord(run.project);
    const pypi = project.pypi || {};
    const docker = project.docker?.latest || {};
    const slowest = run.tests?.slowest;
    return `<tr data-run-id="${run.id}" tabindex="0">
      <td><div class="project-cell" style="--project-color:${COLORS[run.project]}"><span class="project-swatch"></span><span class="cell-stack"><strong>${escapeHtml(run.project)}</strong><small>${escapeHtml(run.branch)}</small></span></div></td>
      <td><span class="cell-stack"><span class="run-title" title="${escapeHtml(run.title)}">${escapeHtml(run.title)}</span><small>${escapeHtml(run.workflow)} · #${run.run_number || "?"} · ${formatDate(run.started_at)}</small></span></td>
      <td><span class="status ${statusClass(run)}">${escapeHtml(run.conclusion || run.status)}</span></td>
      <td><span class="cell-stack"><span>${metricCell(run.tests?.total, formatNumber)}</span><small class="coverage">${run.tests?.jobs_reported || 0}/${run.tests?.jobs_expected || 0} jobs</small></span></td>
      <td>${metricCell(run.duration_ms, formatDuration)}</td>
      <td>${metricCell(run.tests?.avg_duration_ms, formatDuration)}</td>
      <td>${metricCell(slowest?.duration_ms, formatDuration, slowest?.name)}</td>
      <td>${pypi.url ? `<a class="metric-link" href="${safeUrl(pypi.url)}" target="_blank" rel="noreferrer" onclick="event.stopPropagation()">${escapeHtml(pypi.version || "PyPI")} · ${formatBytes(pypi.wheel_size_bytes)}</a>` : `<span class="missing">—</span>`}</td>
      <td>${run.project === "abx-dl" || run.project === "archivebox" ? metricCell(run.docker_build_ms, formatDuration) : `<span class="missing">n/a</span>`}</td>
      <td>${project.docker?.url ? `<a class="metric-link" href="${safeUrl(project.docker.url)}" target="_blank" rel="noreferrer" onclick="event.stopPropagation()">${formatBytes(docker.compressed_size_bytes)}</a>` : `<span class="missing">n/a</span>`}</td>
      <td>${metricCell(run.ttfi_ms, formatDuration, "Reported ABX_EVALS import timing")}</td>
    </tr>`;
  }).join("");
}

function chartSeries(runs) {
  const metric = METRICS[state.metric];
  const series = {};
  for (const slug of state.projects) series[slug] = [];
  if (metric.registry === "pypi") {
    for (const slug of state.projects) {
      const releases = projectRecord(slug).pypi?.releases || [];
      series[slug] = releases.filter((item) => item.uploaded_at && inWindow(item.uploaded_at)).map((item) => ({ x: new Date(item.uploaded_at).getTime(), y: item.wheel_size_bytes, label: item.version })).filter((point) => point.y != null);
    }
  } else if (metric.registry === "docker") {
    for (const slug of state.projects) {
      const tags = projectRecord(slug).docker?.tags || [];
      series[slug] = tags.filter((item) => item.updated_at && inWindow(item.updated_at)).map((item) => ({ x: new Date(item.updated_at).getTime(), y: item.compressed_size_bytes, label: item.name })).filter((point) => point.y != null);
    }
  } else {
    for (const run of runs) {
      const value = metric.runValue(run);
      if (value != null) series[run.project].push({ x: new Date(run.started_at).getTime(), y: value, label: run.title });
    }
  }
  for (const slug of Object.keys(series)) series[slug].sort((a, b) => a.x - b.x);
  return series;
}

function renderChart(runs) {
  const metric = METRICS[state.metric];
  $("#trendTitle").textContent = metric.title;
  const series = chartSeries(runs);
  const points = Object.values(series).flat();
  els.chartEmpty.hidden = points.length > 0;
  els.legend.innerHTML = Object.entries(series).filter(([, values]) => values.length).map(([slug]) => `<span class="legend-item" style="--project-color:${COLORS[slug]}">${escapeHtml(slug)}</span>`).join("");

  const canvas = els.chart;
  const bounds = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(bounds.width * dpr));
  canvas.height = Math.max(1, Math.round(bounds.height * dpr));
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, bounds.width, bounds.height);
  if (!points.length) return;

  const pad = { top: 15, right: 18, bottom: 30, left: 64 };
  const width = bounds.width - pad.left - pad.right;
  const height = bounds.height - pad.top - pad.bottom;
  const minX = Math.min(...points.map((point) => point.x));
  const maxX = Math.max(...points.map((point) => point.x));
  const maxY = Math.max(...points.map((point) => point.y)) * 1.08 || 1;
  const x = (value) => pad.left + (value - minX) / (maxX - minX || 1) * width;
  const y = (value) => pad.top + height - value / maxY * height;

  ctx.font = '9px "DM Mono", monospace';
  ctx.fillStyle = "#616c79";
  ctx.strokeStyle = "#202936";
  ctx.lineWidth = 1;
  for (let index = 0; index <= 4; index += 1) {
    const value = maxY * index / 4;
    const lineY = y(value);
    ctx.beginPath(); ctx.moveTo(pad.left, lineY); ctx.lineTo(bounds.width - pad.right, lineY); ctx.stroke();
    ctx.fillText(metric.format(value), 2, lineY + 3);
  }
  const dateFormat = new Intl.DateTimeFormat("en", { month: "short", day: "numeric" });
  ctx.fillText(dateFormat.format(new Date(minX)), pad.left, bounds.height - 5);
  const maxLabel = dateFormat.format(new Date(maxX));
  ctx.fillText(maxLabel, bounds.width - pad.right - ctx.measureText(maxLabel).width, bounds.height - 5);

  for (const [slug, values] of Object.entries(series)) {
    if (!values.length) continue;
    ctx.strokeStyle = COLORS[slug]; ctx.fillStyle = COLORS[slug]; ctx.lineWidth = 2;
    ctx.beginPath(); values.forEach((point, index) => index ? ctx.lineTo(x(point.x), y(point.y)) : ctx.moveTo(x(point.x), y(point.y))); ctx.stroke();
    for (const point of values) { ctx.beginPath(); ctx.arc(x(point.x), y(point.y), 3, 0, Math.PI * 2); ctx.fill(); }
  }
}

function openRun(run) {
  $("#dialogProject").textContent = `${run.project.toUpperCase()} / ${run.branch}`;
  $("#dialogTitle").textContent = run.title;
  $("#dialogMeta").innerHTML = `${escapeHtml(run.workflow)} · run #${run.run_number || "?"} · ${formatDate(run.started_at)} · <a class="metric-link" href="${safeUrl(run.url)}" target="_blank" rel="noreferrer">Open on GitHub ↗</a>`;
  $("#dialogSummary").innerHTML = [
    ["Result", run.conclusion || run.status], ["CI wall time", formatDuration(run.duration_ms)],
    ["Measured tests", formatNumber(run.tests?.total)], ["Subjobs", formatNumber(run.jobs?.length || 0)],
  ].map(([label, value]) => `<div class="detail-stat"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
  els.jobs.innerHTML = (run.jobs || []).map((job) => {
    const excerpt = job.log_excerpt?.length ? `<pre class="log-excerpt">${escapeHtml(job.log_excerpt.join("\n"))}</pre>` : `<p class="muted">Compact log summary has not been collected yet. The full GitHub log remains available.</p>`;
    return `<details class="job">
      <summary><span class="job-name" title="${escapeHtml(job.name)}">${escapeHtml(job.name)}</span><span class="status ${job.conclusion === "success" ? "success" : job.conclusion === "failure" ? "failure" : "cancelled"}">${escapeHtml(job.conclusion || job.status)}</span><span class="job-tests">${job.tests?.total ? `${formatNumber(job.tests.total)} tests` : formatDuration(job.duration_ms)}</span></summary>
      <div class="job-body">
        <div class="step-list">${(job.steps || []).map((step) => `<div class="step"><span class="step-dot ${escapeHtml(step.conclusion || "")}"></span><span>${escapeHtml(step.name)}</span><span>${formatDuration(step.duration_ms)}</span></div>`).join("")}</div>
        ${excerpt}
        <div class="job-actions"><a href="${safeUrl(job.url)}" target="_blank" rel="noreferrer">Open full job log ↗</a></div>
      </div>
    </details>`;
  }).join("") || `<p class="empty-row">No subjobs reported for this run.</p>`;
  els.dialog.showModal();
}

function render() {
  const runs = filteredRuns();
  renderPills(); renderSummary(runs); renderTable(runs); renderChart(runs);
}

async function loadData({ silent = false } = {}) {
  if (!silent) els.sync.textContent = "Loading telemetry…";
  try {
    const response = await fetch(`./data.json?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.data = await response.json();
    els.sync.textContent = `Updated ${formatAge(state.data.generated_at)}`;
    $("#sourceNote").textContent = `${state.data.source} · ${state.data.collection?.http_requests || 0} reads`;
    renderBranches(); render();
  } catch (error) {
    els.sync.textContent = "Telemetry unavailable";
    if (!state.data) els.body.innerHTML = `<tr><td colspan="11" class="empty-row">Could not load data.json. Run the collector or try again shortly.</td></tr>`;
    console.error(error);
  }
}

els.projectPills.addEventListener("click", (event) => {
  const button = event.target.closest("[data-project]"); if (!button) return;
  const slug = button.dataset.project;
  state.projects.has(slug) ? state.projects.delete(slug) : state.projects.add(slug);
  if (!state.projects.size) state.projects.add(slug);
  state.limit = 50; renderBranches(); render();
});
els.branch.addEventListener("change", () => { state.branch = els.branch.value; state.limit = 50; render(); });
els.status.addEventListener("change", () => { state.status = els.status.value; state.limit = 50; render(); });
els.window.addEventListener("change", () => { state.window = Number(els.window.value); state.limit = 50; render(); });
els.metric.addEventListener("change", () => { state.metric = els.metric.value; renderChart(filteredRuns()); });
els.search.addEventListener("input", () => { state.query = els.search.value.trim(); state.limit = 50; render(); });
$("#resetFilters").addEventListener("click", () => {
  state.projects = new Set(Object.keys(COLORS)); state.branch = "all"; state.status = "all"; state.window = 30; state.metric = "duration"; state.query = ""; state.limit = 50;
  els.status.value = "all"; els.window.value = "30"; els.metric.value = "duration"; els.search.value = ""; renderBranches(); render();
});
els.showMore.addEventListener("click", () => { state.limit += 50; renderTable(filteredRuns()); });
els.body.addEventListener("click", (event) => { const row = event.target.closest("[data-run-id]"); if (row) openRun(state.data.runs.find((run) => String(run.id) === row.dataset.runId)); });
els.body.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) { const row = event.target.closest("[data-run-id]"); if (row) { event.preventDefault(); openRun(state.data.runs.find((run) => String(run.id) === row.dataset.runId)); } } });
$("#dialogClose").addEventListener("click", () => els.dialog.close());
els.dialog.addEventListener("click", (event) => { if (event.target === els.dialog) els.dialog.close(); });
$("#refreshButton").addEventListener("click", () => loadData());
window.addEventListener("resize", () => state.data && renderChart(filteredRuns()));

loadData();
setInterval(() => loadData({ silent: true }), 120000);
