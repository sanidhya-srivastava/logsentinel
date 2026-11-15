const POLL_INTERVAL_MS = 4000;

const emptyStats = {
  log_rate_per_second: 0,
  logs_last_hour: 0,
  anomaly_rate_percent: 0,
  total_anomalies: 0,
};

const pipelineNodes = [
  ["Ingest", "FastAPI validates and enriches raw logs on :8000."],
  ["Kafka", "raw-logs, processed-logs, and anomaly-alerts decouple stages."],
  ["Processor", "Feature extraction + Elasticsearch indexing into logs-*."],
  ["ML Engine", "Isolation Forest scores vectors in real time on :8001."],
  ["Alerts", "Deduplicates in Redis, stores in PostgreSQL, routes notifications."],
];

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function numberFormat(value) {
  return new Intl.NumberFormat().format(Number(value || 0));
}

function levelClass(level) {
  const normalized = String(level || "INFO").toLowerCase();
  if (normalized.includes("critical")) return "level-critical";
  if (normalized.includes("error")) return "level-error";
  if (normalized.includes("warn")) return "level-warn";
  return "level-info";
}

function safeSlice(items, size) {
  return Array.isArray(items) ? items.slice(0, size) : [];
}

async function getJson(url, allowErrorJson = false) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok && !allowErrorJson) {
    throw new Error(`HTTP ${response.status} for ${url}`);
  }
  return response.json();
}

async function loadDashboardData(forceFresh = false) {
  const statsUrl = forceFresh ? "/stats?nocache=true" : "/stats";
  const [statsRes, logsRes, anomaliesRes, healthRes] = await Promise.allSettled([
    getJson(statsUrl),
    getJson("/logs?size=100"),
    getJson("/anomalies?size=10"),
    getJson("/health", true),
  ]);

  const reachable =
    statsRes.status === "fulfilled" ||
    logsRes.status === "fulfilled" ||
    anomaliesRes.status === "fulfilled" ||
    healthRes.status === "fulfilled";

  return {
    reachable,
    health: healthRes.status === "fulfilled" ? healthRes.value : null,
    stats: statsRes.status === "fulfilled" ? statsRes.value : emptyStats,
    logs: logsRes.status === "fulfilled" ? logsRes.value.items || [] : [],
    anomalies: anomaliesRes.status === "fulfilled" ? anomaliesRes.value.items || [] : [],
  };
}

function updateStatusBadge(elementId, data) {
  const badge = document.getElementById(elementId);
  if (!badge) return;
  const now = new Date().toLocaleTimeString();

  if (!data.reachable) {
    badge.textContent = "Backend Offline";
    badge.style.background = "var(--red, #ef4444)";
    badge.style.color = "#fff";
    return;
  }

  const healthStatus = data.health?.status;
  if (healthStatus === "degraded") {
    const checks = data.health?.checks || {};
    const down = Object.entries(checks)
      .filter(([, state]) => state !== "connected")
      .map(([name]) => name);
    badge.textContent = down.length ? `Degraded (${down.join(", ")})` : `Live · ${now}`;
    badge.style.background = "var(--amber, #f59e0b)";
    badge.style.color = "#111";
    return;
  }

  badge.textContent = `Live · ${now}`;
  badge.style.background = "var(--green, #4ade80)";
  badge.style.color = "#0e120e";
}

function renderLanding(data) {
  const { stats, logs } = data;
  updateStatusBadge("landing-status", data);

  const mappings = [
    ["landing-log-rate", Number(stats.log_rate_per_second || 0).toFixed(2)],
    ["landing-anomaly-rate", `${Number(stats.anomaly_rate_percent || 0)}%`],
    ["landing-log-hour", numberFormat(stats.logs_last_hour)],
    ["landing-total-anomalies", numberFormat(stats.total_anomalies)],
  ];

  mappings.forEach(([id, value]) => {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  });

  const stream = document.getElementById("landing-stream");
  if (!stream) return;

  if (!logs.length) {
    stream.innerHTML = `<div class="mini-log">Waiting for live logs in Elasticsearch...</div>`;
    return;
  }

  stream.innerHTML = safeSlice(logs, 3)
    .map(
      (log) => `
        <div class="mini-log">
          <strong class="table-level ${levelClass(log.level)}">${escapeHtml(log.level || "INFO")}</strong>
          ${escapeHtml(log.service || "service")}: ${escapeHtml(log.message || "No message")}
        </div>
      `
    )
    .join("");
}

function aggregateBy(items, key) {
  const counts = {};
  items.forEach((item) => {
    const label = item?.[key] || "unknown";
    counts[label] = (counts[label] || 0) + 1;
  });
  return Object.entries(counts).sort((a, b) => b[1] - a[1]);
}

function renderBars(items, targetId) {
  const container = document.getElementById(targetId);
  if (!container) return;
  const top = aggregateBy(items, "service").slice(0, 6);
  if (!top.length) {
    container.innerHTML = `<div class="muted">No service activity in this window yet.</div>`;
    return;
  }
  const max = top[0]?.[1] || 1;
  container.innerHTML = top
    .map(
      ([service, count]) => `
        <div class="bar-row">
          <span>${escapeHtml(service)}</span>
          <div class="bar-track"><div class="bar-fill" style="width:${(count / max) * 100}%"></div></div>
          <strong>${count}</strong>
        </div>
      `
    )
    .join("");
}

function renderPills(items) {
  const container = document.getElementById("level-pills");
  if (!container) return;
  const levels = aggregateBy(items, "level");
  if (!levels.length) {
    container.innerHTML = `<span class="pill"><strong>IDLE</strong> 0 events</span>`;
    return;
  }
  container.innerHTML = levels
    .map(
      ([level, count]) =>
        `<span class="pill"><strong>${escapeHtml(level)}</strong> ${count} events</span>`
    )
    .join("");
}

function renderLogs(logs) {
  const table = document.getElementById("logs-table");
  if (!table) return;
  if (!logs.length) {
    table.innerHTML = `<tr><td colspan="4" class="muted">No logs indexed yet. Send events to POST http://localhost:8000/ingest.</td></tr>`;
    return;
  }
  table.innerHTML = safeSlice(logs, 15)
    .map(
      (log) => `
        <tr>
          <td>${escapeHtml(new Date(log["@timestamp"] || log.timestamp || Date.now()).toLocaleString())}</td>
          <td>${escapeHtml(log.service || "unknown")}</td>
          <td><span class="table-level ${levelClass(log.level)}">${escapeHtml(log.level || "INFO")}</span></td>
          <td>${escapeHtml(log.message || "No message available")}</td>
        </tr>
      `
    )
    .join("");
}

function renderAnomalies(anomalies) {
  const container = document.getElementById("anomaly-list");
  if (!container) return;
  if (!anomalies.length) {
    container.innerHTML = `<div class="muted">No anomaly alerts recorded yet.</div>`;
    return;
  }
  container.innerHTML = safeSlice(anomalies, 6)
    .map((item) => {
      const score = item.anomaly_score ?? item.score;
      const formattedScore = typeof score === "number" ? score.toFixed(3) : score ?? "n/a";
      return `
        <article class="feed-item">
          <strong>${escapeHtml(item.service || "unknown")} <span class="table-level ${levelClass(item.level)}">${escapeHtml(item.level || "ALERT")}</span></strong>
          <div>${escapeHtml(item.message || "No anomaly message")}</div>
          <small class="muted">Score: ${escapeHtml(formattedScore)} | ${escapeHtml(new Date(item.detected_at || Date.now()).toLocaleString())}</small>
        </article>
      `;
    })
    .join("");
}

function renderPipeline() {
  const container = document.getElementById("pipeline-grid");
  if (!container) return;
  container.innerHTML = pipelineNodes
    .map(
      ([title, description]) => `
        <article class="pipeline-node">
          <span>${escapeHtml(title)}</span>
          <h3>${escapeHtml(title)}</h3>
          <p>${escapeHtml(description)}</p>
        </article>
      `
    )
    .join("");
}

function renderStats(stats) {
  const entries = [
    ["stat-log-rate", Number(stats.log_rate_per_second || 0).toFixed(2)],
    ["stat-logs-hour", numberFormat(stats.logs_last_hour)],
    ["stat-anomaly-rate", `${Number(stats.anomaly_rate_percent || 0)}%`],
    ["stat-total-anomalies", numberFormat(stats.total_anomalies)],
  ];
  entries.forEach(([id, value]) => {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  });
}

let inFlight = false;

async function refreshPage(page, forceFresh = false) {
  if (inFlight) return;
  inFlight = true;
  try {
    const data = await loadDashboardData(forceFresh);
    if (page === "landing") {
      renderLanding(data);
    } else if (page === "dashboard") {
      updateStatusBadge("live-status-pill", data);
      renderStats(data.stats);
      renderBars(data.logs, "service-bars");
      renderPills(data.logs);
      renderLogs(data.logs);
      renderAnomalies(data.anomalies);
    }
  } finally {
    inFlight = false;
  }
}

async function init() {
  const page = document.body.dataset.page;
  if (page === "dashboard") {
    renderPipeline();
    const refreshBtn = document.getElementById("refresh-dashboard-btn");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", () => refreshPage(page, true));
    }
  }

  await refreshPage(page, false);
  setInterval(() => refreshPage(page, false), POLL_INTERVAL_MS);
}

init();
