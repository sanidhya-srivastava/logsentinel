const DASHBOARD_BASE =
  import.meta.env.VITE_DASHBOARD_API_URL ||
  (import.meta.env.DEV ? '/api/dashboard' : 'http://localhost:8002');

const ML_BASE =
  import.meta.env.VITE_ML_API_URL ||
  (import.meta.env.DEV ? '/api/ml' : 'http://localhost:8001');

const INGEST_BASE =
  import.meta.env.VITE_INGEST_API_URL ||
  (import.meta.env.DEV ? '/api/ingest' : 'http://localhost:8000');

async function requestJson(url, options = {}, allowErrorJson = false) {
  const response = await fetch(url, {
    cache: 'no-store',
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  });
  if (!response.ok && !allowErrorJson) {
    let detail = `HTTP ${response.status}`;
    try {
      const errBody = await response.json();
      if (errBody?.detail) detail = `${detail}: ${errBody.detail}`;
    } catch {
      // Ignore non-JSON error bodies
    }
    throw new Error(detail);
  }
  return response.json();
}

export function formatShortTime(value) {
  const date = value ? new Date(value) : new Date();
  if (Number.isNaN(date.getTime())) return '--:--:--';
  return date.toLocaleTimeString('en-US', { hour12: false });
}

export function normalizeLog(item, index, anomalyLogIds = new Set()) {
  const rawTimestamp = item?.['@timestamp'] || item?.timestamp || item?.ingested_at;
  const level = String(item?.level || 'INFO').toUpperCase();
  const logId = item?.log_id;
  const isAnomaly =
    Boolean(item?.is_anomaly) ||
    (Boolean(logId) && anomalyLogIds.has(logId)) ||
    level === 'CRITICAL';

  return {
    id: logId || `${rawTimestamp || Date.now()}-${index}`,
    logId: logId || null,
    rawTimestamp,
    time: formatShortTime(rawTimestamp),
    service: String(item?.service || 'unknown'),
    level,
    msg: String(item?.message || ''),
    anomaly: isAnomaly,
    responseTimeMs: item?.response_time_ms ?? null,
    errorCode: item?.error_code ?? null,
    host: item?.host || null,
  };
}

export function normalizeAlert(item, index) {
  const score = item?.anomaly_score ?? item?.score;
  const level = String(item?.level || 'ERROR').toLowerCase();
  const detectedAt = item?.detected_at || item?.created_at || item?.timestamp;
  return {
    id: item?.alert_id || item?.id || `alert-${index}`,
    logId: item?.log_id || null,
    service: String(item?.service || 'unknown'),
    level,
    severity: level.includes('crit') || level.includes('err') ? 'error' : level.includes('warn') ? 'warn' : 'info',
    message: String(item?.message || 'Anomaly detected'),
    score: typeof score === 'number' ? score : Number(score ?? 0),
    detectedAt,
    timeLabel: detectedAt ? new Date(detectedAt).toLocaleString() : 'just now',
  };
}

export async function fetchDashboardSnapshot({ forceFresh = false, logLimit = 100, anomalyLimit = 20 } = {}) {
  const statsPath = forceFresh ? '/stats?nocache=true' : '/stats';
  const [statsRes, logsRes, anomaliesRes, healthRes, modelRes] = await Promise.allSettled([
    requestJson(`${DASHBOARD_BASE}${statsPath}`),
    requestJson(`${DASHBOARD_BASE}/logs?size=${Math.min(Math.max(logLimit, 1), 100)}`),
    requestJson(`${DASHBOARD_BASE}/anomalies?size=${Math.min(Math.max(anomalyLimit, 1), 100)}`),
    requestJson(`${DASHBOARD_BASE}/health`, {}, true),
    requestJson(`${ML_BASE}/model/status`, {}, true),
  ]);

  const reachable =
    statsRes.status === 'fulfilled' ||
    logsRes.status === 'fulfilled' ||
    anomaliesRes.status === 'fulfilled' ||
    healthRes.status === 'fulfilled';

  const anomaliesRaw = anomaliesRes.status === 'fulfilled' ? anomaliesRes.value.items || [] : [];
  const anomalies = anomaliesRaw.map(normalizeAlert);
  const anomalyLogIds = new Set(anomalies.map((a) => a.logId).filter(Boolean));

  const logsRaw = logsRes.status === 'fulfilled' ? logsRes.value.items || [] : [];
  const logs = logsRaw.map((item, idx) => normalizeLog(item, idx, anomalyLogIds));

  const modelStatus =
    modelRes.status === 'fulfilled' && modelRes.value?.status === 'loaded' ? modelRes.value : null;

  return {
    reachable,
    lastUpdated: new Date().toISOString(),
    stats: statsRes.status === 'fulfilled' ? statsRes.value : null,
    health: healthRes.status === 'fulfilled' ? healthRes.value : null,
    logs,
    totalLogs: logsRes.status === 'fulfilled' ? Number(logsRes.value.total || logs.length) : 0,
    anomalies,
    totalAnomalies: anomaliesRes.status === 'fulfilled' ? Number(anomaliesRes.value.total || anomalies.length) : 0,
    modelStatus,
  };
}

function encodeErrorCodeBucket(errorCode) {
  const code = Number(errorCode || 0);
  if (!code) return 0;
  if (code >= 200 && code < 300) return 1;
  if (code >= 300 && code < 400) return 2;
  if (code >= 400 && code < 500) return 3;
  if (code >= 500 && code < 600) return 4;
  return 5;
}

function encodeLogLevel(level) {
  const upper = String(level || 'INFO').toUpperCase();
  const map = { DEBUG: 0, INFO: 1, WARN: 2, WARNING: 2, ERROR: 3, CRITICAL: 4, FATAL: 4 };
  return map[upper] ?? 1;
}

export async function runSinglePrediction(logSample = null) {
  const ts = logSample?.rawTimestamp ? new Date(logSample.rawTimestamp) : new Date();
  const featureVector = logSample
    ? {
        hour_of_day: Number.isNaN(ts.getTime()) ? new Date().getUTCHours() : ts.getUTCHours(),
        response_time_ms: Number(logSample.responseTimeMs ?? (logSample.level === 'ERROR' ? 4500 : 120)),
        error_code: encodeErrorCodeBucket(logSample.errorCode ?? (logSample.level === 'ERROR' ? 503 : 200)),
        log_level_encoded: encodeLogLevel(logSample.level),
        request_count_last_60s: 25,
        service_id_encoded: Math.abs(
          Array.from(String(logSample.service || 'gateway')).reduce((acc, ch) => acc + ch.charCodeAt(0), 0)
        ) % 10,
      }
    : {
        hour_of_day: new Date().getUTCHours(),
        response_time_ms: 4800.0,
        error_code: 4,
        log_level_encoded: 3,
        request_count_last_60s: 1200,
        service_id_encoded: 1,
      };

  return requestJson(`${ML_BASE}/predict`, {
    method: 'POST',
    body: JSON.stringify(featureVector),
  });
}

export async function ingestLog({
  service = 'demo-app',
  level = 'INFO',
  message = 'Synthetic operator check event',
  response_time_ms = 120,
  error_code = 200,
  host = 'ui-console',
} = {}) {
  return requestJson(`${INGEST_BASE}/ingest`, {
    method: 'POST',
    body: JSON.stringify({
      service,
      level: String(level).toUpperCase(),
      message,
      response_time_ms,
      error_code,
      host,
    }),
  });
}
