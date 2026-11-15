import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bell,
  Cpu,
  Database,
  Download,
  RefreshCcw,
  Search,
  Send,
  ShieldCheck,
  Terminal,
  Trash2,
} from 'lucide-react';
import { fetchDashboardSnapshot, ingestLog, runSinglePrediction } from '../api/client';

const POLL_MS = 4000;

const Kpi = ({ icon, label, value }) => (
  <div className="kpi">
    <div className="kpi-icon">{icon}</div>
    <span className="kpi-label">{label}</span>
    <span className="kpi-value">{value}</span>
  </div>
);

const AlertCard = ({ title, body, time, severity }) => (
  <article className="alert-card">
    <h3>
      <span>{title}</span>
      <span className={`level-${severity}`}>{severity.toUpperCase()}</span>
    </h3>
    <p>{body}</p>
    <div className="alert-meta">{time}</div>
  </article>
);

const Dashboard = () => {
  const [logs, setLogs] = useState([]);
  const [anomalies, setAnomalies] = useState([]);
  const [stats, setStats] = useState(null);
  const [health, setHealth] = useState(null);
  const [modelStatus, setModelStatus] = useState(null);
  const [reachable, setReachable] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSendingTest, setIsSendingTest] = useState(false);

  const [query, setQuery] = useState('');
  const [service, setService] = useState('all');
  const [onlyAnomalies, setOnlyAnomalies] = useState(false);
  const [isMlRunning, setIsMlRunning] = useState(false);
  const [mlResult, setMlResult] = useState(null);
  const [showStats, setShowStats] = useState(false);
  const [showFlow, setShowFlow] = useState(false);

  const inFlightRef = useRef(false);

  const refreshData = useCallback(async (forceFresh = false) => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    if (forceFresh) setIsRefreshing(true);
    try {
      const snapshot = await fetchDashboardSnapshot({ forceFresh, logLimit: 100, anomalyLimit: 20 });
      setReachable(snapshot.reachable);
      setStats(snapshot.stats);
      setHealth(snapshot.health);
      setModelStatus(snapshot.modelStatus);
      setLogs(snapshot.logs);
      setAnomalies(snapshot.anomalies);
      setLastUpdated(snapshot.lastUpdated);
    } finally {
      inFlightRef.current = false;
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    const poll = async () => {
      if (!active) return;
      await refreshData(false);
    };
    const initial = setTimeout(poll, 0);
    if (!autoRefresh) {
      return () => {
        active = false;
        clearTimeout(initial);
      };
    }
    const timer = setInterval(poll, POLL_MS);
    return () => {
      active = false;
      clearTimeout(initial);
      clearInterval(timer);
    };
  }, [autoRefresh, refreshData]);

  const services = useMemo(() => {
    const names = new Set();
    logs.forEach((l) => names.add(l.service));
    anomalies.forEach((a) => names.add(a.service));
    return ['all', ...Array.from(names).sort()];
  }, [logs, anomalies]);

  const filteredLogs = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return logs.filter((log) => {
      const matchesQuery = !normalized || `${log.service} ${log.level} ${log.msg}`.toLowerCase().includes(normalized);
      const matchesService = service === 'all' || log.service === service;
      const matchesAnomaly = !onlyAnomalies || log.anomaly;
      return matchesQuery && matchesService && matchesAnomaly;
    });
  }, [logs, onlyAnomalies, query, service]);

  const clearLogs = () => {
    setAutoRefresh(false);
    setLogs([]);
  };

  const exportLogs = () => {
    const payload = filteredLogs.map((log) => JSON.stringify(log)).join('\n');
    const blob = new Blob([payload], { type: 'application/x-ndjson' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'logsentinel-logs.ndjson';
    link.click();
    URL.revokeObjectURL(url);
  };

  const sendSampleLog = async () => {
    setIsSendingTest(true);
    try {
      const result = await ingestLog({
        service: 'demo-app',
        level: 'ERROR',
        message: `Live operator test spike at ${new Date().toLocaleTimeString()}`,
        response_time_ms: 4850,
        error_code: 503,
        host: 'dashboard-ui',
      });
      setMlResult({
        score: result.log_id,
        status: 'NORMAL',
        note: `Ingested test log (${result.log_id}) -> waiting for Kafka/ES indexing`,
      });
      setTimeout(() => refreshData(true), 1500);
    } catch (err) {
      setMlResult({
        score: 'N/A',
        status: 'ERROR',
        note: `Ingestion API (:8000) unreachable: ${err.message}`,
      });
    } finally {
      setIsSendingTest(false);
    }
  };

  const runMlInference = async () => {
    setIsMlRunning(true);
    setMlResult(null);
    try {
      const sample = filteredLogs[0] ?? null;
      const prediction = await runSinglePrediction(sample);
      setMlResult({
        score: Number(prediction.anomaly_score).toFixed(4),
        status: prediction.is_anomaly ? 'ANOMALY' : 'NORMAL',
        note: sample
          ? `Scored latest log from ${sample.service} (threshold ${prediction.threshold_used})`
          : `Scored synthetic spike vector (threshold ${prediction.threshold_used})`,
        timestamp: new Date().toISOString(),
      });
    } catch (err) {
      setMlResult({
        score: 'N/A',
        status: 'ERROR',
        note: `ML Engine (:8001) unreachable: ${err.message}`,
      });
    } finally {
      setIsMlRunning(false);
    }
  };

  const levelBreakdown = useMemo(() => {
    const levels = ['DEBUG', 'INFO', 'WARN', 'ERROR', 'CRITICAL'];
    const total = Math.max(logs.length, 1);
    return levels.map((lvl) => {
      const count = logs.filter((l) => l.level === lvl).length;
      return { label: lvl, count, pct: Math.round((count / total) * 100) };
    });
  }, [logs]);

  const serviceHealthSummary = useMemo(() => {
    if (!reachable) return 'Offline';
    const checks = health?.checks || {};
    const values = Object.values(checks);
    if (!values.length) return health?.status === 'healthy' ? 'Healthy' : 'Connected';
    const up = values.filter((v) => v === 'connected').length;
    return `${up}/${values.length} up`;
  }, [health, reachable]);

  const statusPillText = !reachable
    ? 'Offline'
    : autoRefresh
      ? `Live · ${lastUpdated ? new Date(lastUpdated).toLocaleTimeString() : 'polling'}`
      : 'Paused';

  return (
    <section className="page">
      <div className="container dashboard-grid">
        <header className="dashboard-header">
          <div>
            <p className="eyebrow">Dashboard</p>
            <h1>Operations Center</h1>
            <p>Real-time logs, anomaly scoring, service health, and alert context.</p>
          </div>
          <div className="row-actions">
            <button className="pill-button" type="button" onClick={() => setAutoRefresh((v) => !v)}>
              <Activity size={18} />
              {autoRefresh ? 'Live: ON' : 'Live: PAUSED'}
            </button>
            <button className="pill-button" type="button" onClick={exportLogs}>
              <Download size={18} />
              Export logs
            </button>
            <button
              className={`pill-button ${isMlRunning ? 'loading' : ''}`}
              type="button"
              onClick={runMlInference}
              disabled={isMlRunning}
            >
              <Cpu size={18} className={isMlRunning ? 'spin' : ''} />
              {isMlRunning ? 'Analyzing...' : 'Run ML Inference'}
            </button>
            <button className="pill-button" type="button" onClick={() => setShowFlow(true)}>
              <Activity size={18} />
              ML Flow
            </button>
            <button className="pill-button" type="button" onClick={() => setShowStats(true)}>
              <BarChart3 size={18} />
              ML Stats
            </button>
            <button className="pill-button" type="button" onClick={sendSampleLog} disabled={isSendingTest}>
              <Send size={18} />
              {isSendingTest ? 'Sending...' : 'Send test log'}
            </button>
            <button className="pill-button primary" type="button" onClick={() => refreshData(true)} disabled={isRefreshing}>
              <RefreshCcw size={18} className={isRefreshing ? 'spin' : ''} />
              {isRefreshing ? 'Refreshing...' : 'Refresh live data'}
            </button>
          </div>
        </header>

        {showStats && (
          <div className="modal-overlay" onClick={() => setShowStats(false)}>
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              className="modal-content"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="modal-header">
                <h2><BarChart3 size={24} /> Live ML &amp; Stream Statistics</h2>
                <button className="close-btn" onClick={() => setShowStats(false)}>×</button>
              </div>

              <div className="stats-grid-modal">
                <div className="stat-card-modal">
                  <span className="stat-label-modal">Anomaly Rate (1h)</span>
                  <span className="stat-value-modal text-green">{stats?.anomaly_rate_percent ?? 0}%</span>
                </div>
                <div className="stat-card-modal">
                  <span className="stat-label-modal">Anomalies (1h)</span>
                  <span className="stat-value-modal text-orange">{stats?.anomalies_last_hour ?? 0}</span>
                </div>
                <div className="stat-card-modal">
                  <span className="stat-label-modal">Contamination</span>
                  <span className="stat-value-modal text-blue">{modelStatus?.contamination ?? 'N/A'}</span>
                </div>
                <div className="stat-card-modal">
                  <span className="stat-label-modal">Trees / Features</span>
                  <span className="stat-value-modal">
                    {modelStatus ? `${modelStatus.n_estimators} / ${modelStatus.n_features}` : 'Offline'}
                  </span>
                </div>
              </div>

              <div className="chart-container-modal">
                <h3>Observed Severity Distribution (Current Window)</h3>
                <div className="mock-chart">
                  {levelBreakdown.map((item) => (
                    <div key={item.label} className="chart-bar-outer" title={`${item.label}: ${item.count}`}>
                      <div className="chart-bar" style={{ height: `${Math.max(item.pct, item.count ? 12 : 4)}%` }}>
                        <div className="bar-tooltip">{item.label}: {item.count}</div>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="chart-labels">
                  {levelBreakdown.map((item) => (
                    <span key={item.label}>{item.label}</span>
                  ))}
                </div>
              </div>

              <div className="model-info-footer">
                <div className="info-item">
                  <span className="info-label">Active Model:</span>
                  <span className="info-value">{modelStatus?.model_type ?? 'ML Engine Offline (:8001)'}</span>
                </div>
                <div className="info-item">
                  <span className="info-label">Last Training:</span>
                  <span className="info-value">{modelStatus?.trained_at ?? 'N/A'}</span>
                </div>
                <div className="info-item">
                  <span className="info-label">Threshold:</span>
                  <span className="info-value">{modelStatus?.anomaly_threshold ?? '0.0'}</span>
                </div>
              </div>
            </motion.div>
          </div>
        )}

        {showFlow && (
          <div className="modal-overlay" onClick={() => setShowFlow(false)}>
            <motion.div
              initial={{ opacity: 0, y: 50 }}
              animate={{ opacity: 1, y: 0 }}
              className="modal-content flow-modal"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="modal-header">
                <h2><Activity size={24} /> ML Pipeline Architecture</h2>
                <button className="close-btn" onClick={() => setShowFlow(false)}>×</button>
              </div>

              <div className="flow-viz-container">
                <div className="flow-path">
                  <div className="flow-step-node">
                    <div className="node-icon"><Database size={20} /></div>
                    <span>Ingest API</span>
                  </div>
                  <div className="flow-connector"></div>
                  <div className="flow-step-node accent">
                    <div className="node-icon"><Activity size={20} /></div>
                    <span>Kafka Stream</span>
                  </div>
                  <div className="flow-connector"></div>
                  <div className="flow-step-node highlight">
                    <div className="node-icon"><Cpu size={20} /></div>
                    <span>ML Engine</span>
                    <small>Isolation Forest</small>
                  </div>
                  <div className="flow-connector"></div>
                  <div className="flow-step-node alert">
                    <div className="node-icon"><AlertTriangle size={20} /></div>
                    <span>Alert Service</span>
                  </div>
                  <div className="flow-connector"></div>
                  <div className="flow-step-node">
                    <div className="node-icon"><Terminal size={20} /></div>
                    <span>Operator UI</span>
                  </div>
                </div>
              </div>

              <div className="flow-description">
                <p>
                  <strong>LogSentinel ML Flow</strong> validates logs on port 8000, streams via Kafka (
                  <code>raw-logs</code> → <code>processed-logs</code>), scores 6-feature vectors in{' '}
                  <code>ml-engine</code> (score &lt; 0.0 flags an anomaly), and publishes alerts to PostgreSQL
                  for this dashboard on port 8002.
                </p>
              </div>
            </motion.div>
          </div>
        )}

        {mlResult && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="ml-result-banner"
          >
            <div className="ml-result-content">
              <Cpu size={20} />
              <span>
                <strong>Result:</strong> Score/ID <strong>{mlResult.score}</strong> ·{' '}
                <span className={`status-tag ${mlResult.status.toLowerCase()}`}>{mlResult.status}</span>
                {mlResult.note ? ` — ${mlResult.note}` : ''}
              </span>
            </div>
            <button className="close-btn" onClick={() => setMlResult(null)}>×</button>
          </motion.div>
        )}

        <div className="kpi-grid">
          <Kpi icon={<Activity size={24} />} label="Ingestion rate" value={`${Number(stats?.log_rate_per_second ?? 0).toFixed(2)}/s`} />
          <Kpi icon={<ShieldCheck size={24} />} label="Service health" value={serviceHealthSummary} />
          <Kpi icon={<AlertTriangle size={24} />} label="Total anomalies" value={Number(stats?.total_anomalies ?? anomalies.length).toLocaleString()} />
          <Kpi icon={<Database size={24} />} label="Logs (last hour)" value={Number(stats?.logs_last_hour ?? logs.length).toLocaleString()} />
        </div>

        <div className="ops-grid">
          <section className="panel">
            <div className="panel-head">
              <h2>
                <Terminal size={20} /> System logs
              </h2>
              <div className="toolbar">
                <label className="search-box">
                  <Search size={16} />
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Search logs"
                    aria-label="Search logs"
                  />
                </label>
                <select className="select-input" value={service} onChange={(event) => setService(event.target.value)}>
                  {services.map((name) => (
                    <option key={name} value={name}>
                      {name === 'all' ? 'All services' : name}
                    </option>
                  ))}
                </select>
                <button className="icon-button" type="button" onClick={() => setOnlyAnomalies((value) => !value)} aria-label="Toggle anomalies">
                  <AlertTriangle size={17} color={onlyAnomalies ? 'var(--orange)' : 'currentColor'} />
                </button>
                <button className="icon-button" type="button" onClick={clearLogs} aria-label="Clear view and pause polling">
                  <Trash2 size={17} />
                </button>
              </div>
            </div>

            <div className="log-table" aria-live="polite">
              {filteredLogs.length === 0 ? (
                <div className="log-row">
                  <span>
                    {!reachable
                      ? 'Dashboard backend (:8002) is unreachable. Start backend services to view live logs.'
                      : 'No logs match the current filters or Elasticsearch has no logs yet.'}
                  </span>
                </div>
              ) : (
                filteredLogs.map((log) => (
                  <div className={`log-row ${log.anomaly ? 'anomaly' : ''}`} key={log.id}>
                    <span className="log-time">{log.time}</span>
                    <span className="log-service">[{log.service}]</span>
                    <strong className={`level-${log.level.toLowerCase()}`}>{log.level}</strong>
                    <span>{log.msg}</span>
                    {log.anomaly ? <span className="mini-chip">ANOMALY</span> : <span />}
                  </div>
                ))
              )}
            </div>
          </section>

          <aside className="panel">
            <div className="panel-head">
              <h2>
                <Bell size={20} /> Active alerts
              </h2>
              <span className="status-pill">{statusPillText}</span>
            </div>
            <div className="alert-list">
              {anomalies.length === 0 ? (
                <AlertCard
                  severity="info"
                  title={reachable ? 'No active alerts' : 'Backend disconnected'}
                  body={
                    reachable
                      ? 'PostgreSQL returned 0 anomaly alerts so far.'
                      : 'Connect dashboard-backend (:8002) and PostgreSQL to load alerts.'
                  }
                  time={lastUpdated ? new Date(lastUpdated).toLocaleTimeString() : 'waiting'}
                />
              ) : (
                anomalies.slice(0, 6).map((alert) => (
                  <AlertCard
                    key={alert.id}
                    severity={alert.severity}
                    title={`${alert.service} (${Number(alert.score).toFixed(3)})`}
                    body={alert.message}
                    time={alert.timeLabel}
                  />
                ))
              )}
            </div>
            <button
              className="pill-button"
              type="button"
              style={{ width: '100%', marginTop: 18 }}
              onClick={() => setOnlyAnomalies((v) => !v)}
            >
              {onlyAnomalies ? 'Show all logs' : 'Filter anomaly logs'}
            </button>
          </aside>
        </div>

        <section className="panel terminal-panel">
          <div className="panel-head">
            <h2><Terminal size={20} /> Real-time Live Stream</h2>
            <div className="terminal-dots">
              <span className="dot red"></span>
              <span className="dot yellow"></span>
              <span className="dot green"></span>
            </div>
          </div>
          <div className="terminal-body">
            {logs.length === 0 ? (
              <div className="terminal-line">
                <span className="term-prompt">user@logsentinel:~$</span>
                <span className="term-cmd">
                  {reachable ? 'tail -f /logs-*  # waiting for incoming logs...' : 'connect :8002  # backend offline'}
                </span>
              </div>
            ) : (
              logs.slice(0, 10).map((log, i) => (
                <div key={log.id} className="terminal-line" style={{ opacity: Math.max(0.35, 1 - i * 0.07) }}>
                  <span className="term-time">[{log.time}]</span>
                  <span className="term-prompt">user@logsentinel:~$</span>
                  <span className="term-cmd">ingest --service {log.service} --level {log.level}</span>
                  <div className="term-output">
                    <span className={`term-status ${log.level.toLowerCase()}`}>{log.level}</span>
                    <span>{log.msg}</span>
                    {log.anomaly && <span className="term-anomaly"> [!! ANOMALY DETECTED !!]</span>}
                  </div>
                </div>
              ))
            )}
            <div className="terminal-cursor">_</div>
          </div>
        </section>
      </div>
    </section>
  );
};

export default Dashboard;
