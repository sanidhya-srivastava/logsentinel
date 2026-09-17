const fallbackStats = {
  log_rate_per_second: 42.4,
  logs_last_hour: 152640,
  anomaly_rate_percent: 1.87,
  total_anomalies: 286,
};

const fallbackLogs = [
  {
    "@timestamp": "2026-04-17T07:22:15Z",
    service: "auth-service",
    level: "ERROR",
    message: "Database connection timeout after 5000ms",
  },
  {
    "@timestamp": "2026-04-17T07:21:44Z",
    service: "payment-service",
    level: "WARN",
    message: "Retry storm detected against upstream billing provider",
  },
  {
    "@timestamp": "2026-04-17T07:21:09Z",
    service: "gateway",
    level: "INFO",
    message: "Steady request flow observed across the last rolling window",
  },
  {
    "@timestamp": "2026-04-17T07:20:31Z",
    service: "ml-engine",
    level: "INFO",
    message: "Anomaly model scored processed batch successfully",
  },
];

const fallbackAnomalies = [
  {
    service: "auth-service",
    level: "ERROR",
    score: -0.84,
    message: "Repeated timeout burst from authentication workload",
    detected_at: "2026-04-17T07:20:10Z",
  },
  {
    service: "payment-service",
    level: "WARN",
    score: -0.62,
    message: "Latency spike exceeded learned baseline",
    detected_at: "2026-04-17T07:14:02Z",
  },
];

const pipelineNodes = [
  ["Ingest", "FastAPI validates and enriches raw logs."],
  ["Kafka", "Raw and processed topics keep the stream decoupled."],
  ["Processor", "Events are structured and indexed into Elasticsearch."],
  ["ML", "Isolation Forest scores processed log feature vectors."],
  ["Alerts", "Anomalies persist and route to responders."],
];

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

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Request failed for ${url}`);
  return response.json();
}

async function loadDashboardData() {
  try {
    const [stats, logs, anomalies] = await Promise.all([
      getJson("/stats"),
      getJson("/logs?size=120"),
      getJson("/anomalies?size=8"),
    ]);
    return {
      stats,
      logs: logs.items || [],
      anomalies: anomalies.items || [],
    };
  } catch (error) {
    return {
      stats: fallbackStats,
      logs: fallbackLogs,
      anomalies: fallbackAnomalies,
    };
  }
}

function renderLanding(stats, logs) {
  const mappings = [
    ["landing-log-rate", stats.log_rate_per_second?.toFixed?.(2) ?? "0.00"],
    ["landing-anomaly-rate", `${stats.anomaly_rate_percent ?? 0}%`],
    ["landing-log-hour", numberFormat(stats.logs_last_hour)],
    ["landing-total-anomalies", numberFormat(stats.total_anomalies)],
  ];

  mappings.forEach(([id, value]) => {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  });

  const stream = document.getElementById("landing-stream");
  if (!stream) return;
  stream.innerHTML = safeSlice(logs, 3)
    .map(
      (log) => `
        <div class="mini-log">
          <strong class="table-level ${levelClass(log.level)}">${log.level || "INFO"}</strong>
          ${log.service || "service"}: ${log.message || "No message"}
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
  const max = top[0]?.[1] || 1;
  container.innerHTML = top
    .map(
      ([service, count]) => `
        <div class="bar-row">
          <span>${service}</span>
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
  container.innerHTML = levels
    .map(
      ([level, count]) =>
        `<span class="pill"><strong>${level}</strong> ${count} events</span>`
    )
    .join("");
}

function renderLogs(logs) {
  const table = document.getElementById("logs-table");
  if (!table) return;
  table.innerHTML = safeSlice(logs, 10)
    .map(
      (log) => `
        <tr>
          <td>${new Date(log["@timestamp"] || log.timestamp || Date.now()).toLocaleString()}</td>
          <td>${log.service || "unknown"}</td>
          <td><span class="table-level ${levelClass(log.level)}">${log.level || "INFO"}</span></td>
          <td>${log.message || "No message available"}</td>
        </tr>
      `
    )
    .join("");
}

function renderAnomalies(anomalies) {
  const container = document.getElementById("anomaly-list");
  if (!container) return;
  container.innerHTML = safeSlice(anomalies, 6)
    .map(
      (item) => `
        <article class="feed-item">
          <strong>${item.service || "unknown"} <span class="table-level ${levelClass(item.level)}">${item.level || "ALERT"}</span></strong>
          <div>${item.message || "No anomaly message"}</div>
          <small class="muted">Score: ${item.score ?? "n/a"} | ${new Date(item.detected_at || Date.now()).toLocaleString()}</small>
        </article>
      `
    )
    .join("");
}

function renderPipeline() {
  const container = document.getElementById("pipeline-grid");
  if (!container) return;
  container.innerHTML = pipelineNodes
    .map(
      ([title, description]) => `
        <article class="pipeline-node">
          <span>${title}</span>
          <h3>${title}</h3>
          <p>${description}</p>
        </article>
      `
    )
    .join("");
}

function renderStats(stats) {
  const entries = [
    ["stat-log-rate", stats.log_rate_per_second?.toFixed?.(2) ?? "0.00"],
    ["stat-logs-hour", numberFormat(stats.logs_last_hour)],
    ["stat-anomaly-rate", `${stats.anomaly_rate_percent ?? 0}%`],
    ["stat-total-anomalies", numberFormat(stats.total_anomalies)],
  ];
  entries.forEach(([id, value]) => {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  });
}

async function init() {
  const page = document.body.dataset.page;
  const data = await loadDashboardData();

  if (page === "landing") {
    renderLanding(data.stats, data.logs);
    return;
  }

  if (page === "dashboard") {
    renderStats(data.stats);
    renderBars(data.logs, "service-bars");
    renderPills(data.logs);
    renderLogs(data.logs);
    renderAnomalies(data.anomalies);
    renderPipeline();
  }
}

init();
