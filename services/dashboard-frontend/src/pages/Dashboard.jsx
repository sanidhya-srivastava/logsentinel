import { useMemo, useState } from 'react';
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
  ShieldCheck,
  Terminal,
  Trash2,
} from 'lucide-react';

const seedLogs = [
  { id: 1, time: '19:23:01', service: 'auth-api', level: 'INFO', msg: 'User login successful for user_842', anomaly: false },
  { id: 2, time: '19:23:04', service: 'payment-svc', level: 'ERROR', msg: 'Stripe API timeout after 10s', anomaly: true },
  { id: 3, time: '19:23:05', service: 'gateway', level: 'WARN', msg: 'High latency detected on /v1/ingest', anomaly: false },
  { id: 4, time: '19:23:10', service: 'db-master', level: 'INFO', msg: 'Replica lag synchronized', anomaly: false },
  { id: 5, time: '19:23:12', service: 'ml-engine', level: 'INFO', msg: 'Inference batch complete for 2,000 records', anomaly: false },
  { id: 6, time: '19:23:15', service: 'alert-mgr', level: 'ERROR', msg: 'Slack webhook failed with 403 Forbidden', anomaly: true },
  { id: 7, time: '19:23:18', service: 'checkout', level: 'WARN', msg: 'Retry storm detected against billing provider', anomaly: true },
  { id: 8, time: '19:23:22', service: 'edge-proxy', level: 'INFO', msg: 'GET /api/v1/health returned 200', anomaly: false },
];

const services = ['all', 'auth-api', 'payment-svc', 'gateway', 'db-master', 'ml-engine', 'alert-mgr', 'checkout', 'edge-proxy'];

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
  const [logs, setLogs] = useState(seedLogs);
  const [query, setQuery] = useState('');
  const [service, setService] = useState('all');
  const [onlyAnomalies, setOnlyAnomalies] = useState(false);
  const [isMlRunning, setIsMlRunning] = useState(false);
  const [mlResult, setMlResult] = useState(null);
  const [showStats, setShowStats] = useState(false);
  const [showFlow, setShowFlow] = useState(false);

  const filteredLogs = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return logs.filter((log) => {
      const matchesQuery = !normalized || `${log.service} ${log.level} ${log.msg}`.toLowerCase().includes(normalized);
      const matchesService = service === 'all' || log.service === service;
      const matchesAnomaly = !onlyAnomalies || log.anomaly;
      return matchesQuery && matchesService && matchesAnomaly;
    });
  }, [logs, onlyAnomalies, query, service]);

  const addLiveLog = () => {
    const pool = [
      ['gateway', 'INFO', 'Steady request flow observed across rolling window', false],
      ['auth-api', 'ERROR', 'Session validator rejected expired signing key', true],
      ['ml-engine', 'INFO', 'Anomaly batch scored in 18ms', false],
      ['payment-svc', 'WARN', 'Upstream billing p95 latency crossed 800ms', true],
    ];
    const [nextService, level, msg, anomaly] = pool[Math.floor(Math.random() * pool.length)];
    const now = new Date().toLocaleTimeString('en-US', { hour12: false });
    setLogs((current) => [{ id: Date.now(), time: now, service: nextService, level, msg, anomaly }, ...current].slice(0, 40));
  };

  const clearLogs = () => setLogs([]);
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

  const runMlInference = () => {
    setIsMlRunning(true);
    setMlResult(null);
    setTimeout(() => {
      setIsMlRunning(false);
      setMlResult({
        score: (0.85 + Math.random() * 0.14).toFixed(4),
        status: Math.random() > 0.9 ? 'ANOMALY' : 'NORMAL',
        timestamp: new Date().toISOString(),
      });
      addLiveLog();
    }, 2000);
  };

  const anomalyCount = logs.filter((log) => log.anomaly).length;

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
            <button className="pill-button primary" type="button" onClick={addLiveLog}>
              <RefreshCcw size={18} />
              Pull live event
            </button>
          </div>
        </header>

        {showStats && (
          <div className="modal-overlay" onClick={() => setShowStats(false)}>
            <motion.div 
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              className="modal-content"
              onClick={e => e.stopPropagation()}
            >
              <div className="modal-header">
                <h2><BarChart3 size={24} /> ML Flow Statistics</h2>
                <button className="close-btn" onClick={() => setShowStats(false)}>×</button>
              </div>
              
              <div className="stats-grid-modal">
                <div className="stat-card-modal">
                  <span className="stat-label-modal">Model Accuracy</span>
                  <span className="stat-value-modal text-green">98.2%</span>
                </div>
                <div className="stat-card-modal">
                  <span className="stat-label-modal">Precision</span>
                  <span className="stat-value-modal text-orange">94.5%</span>
                </div>
                <div className="stat-card-modal">
                  <span className="stat-label-modal">Recall</span>
                  <span className="stat-value-modal text-blue">91.8%</span>
                </div>
                <div className="stat-card-modal">
                  <span className="stat-label-modal">F1 Score</span>
                  <span className="stat-value-modal">0.931</span>
                </div>
              </div>
              
              <div className="chart-container-modal">
                <h3>Anomaly Distribution (Last 24h)</h3>
                <div className="mock-chart">
                  {[30, 45, 25, 60, 40, 85, 50, 65, 35, 20, 55, 45].map((h, i) => (
                    <div key={i} className="chart-bar-outer">
                      <div className="chart-bar" style={{ height: `${h}%` }}>
                        <div className="bar-tooltip">{h}%</div>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="chart-labels">
                  <span>00:00</span>
                  <span>08:00</span>
                  <span>16:00</span>
                  <span>23:59</span>
                </div>
              </div>

              <div className="model-info-footer">
                <div className="info-item">
                  <span className="info-label">Active Model:</span>
                  <span className="info-value">IsolationForest-v2.4-stable</span>
                </div>
                <div className="info-item">
                  <span className="info-label">Last Training:</span>
                  <span className="info-value">2026-04-27 09:12 UTC</span>
                </div>
                <div className="info-item">
                  <span className="info-label">Dataset Size:</span>
                  <span className="info-value">1.2M records</span>
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
              onClick={e => e.stopPropagation()}
            >
              <div className="modal-header">
                <h2><Activity size={24} /> ML Pipeline Architecture</h2>
                <button className="close-btn" onClick={() => setShowFlow(false)}>×</button>
              </div>
              
              <div className="flow-viz-container">
                <div className="flow-path">
                  <div className="flow-step-node">
                    <div className="node-icon"><Database size={20} /></div>
                    <span>Log Source</span>
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
                    <span>Anomaly Alert</span>
                  </div>
                  <div className="flow-connector"></div>
                  <div className="flow-step-node">
                    <div className="node-icon"><Terminal size={20} /></div>
                    <span>Operator UI</span>
                  </div>
                </div>
              </div>

              <div className="flow-description">
                <p>The <strong>LogSentinel ML Flow</strong> processes logs in micro-batches. Each log is vectorised and scored against a baseline model. If a log's isolation score exceeds the <strong>0.85 threshold</strong>, it's immediately flagged as an anomaly and routed to the Active Alerts panel.</p>
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
              <span><strong>ML Insight:</strong> Last batch scored <strong>{mlResult.score}</strong>. Result: 
                <span className={`status-tag ${mlResult.status.toLowerCase()}`}> {mlResult.status}</span>
              </span>
            </div>
            <button className="close-btn" onClick={() => setMlResult(null)}>×</button>
          </motion.div>
        )}

        <div className="kpi-grid">
          <Kpi icon={<Activity size={24} />} label="Ingestion rate" value="850/s" />
          <Kpi icon={<ShieldCheck size={24} />} label="Service health" value="99.9%" />
          <Kpi icon={<AlertTriangle size={24} />} label="Active anomalies" value={anomalyCount} />
          <Kpi icon={<Database size={24} />} label="Total records" value="152,640" />
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
                <button className="icon-button" type="button" onClick={clearLogs} aria-label="Clear logs">
                  <Trash2 size={17} />
                </button>
              </div>
            </div>

            <div className="log-table" aria-live="polite">
              {filteredLogs.length === 0 ? (
                <div className="log-row">
                  <span>No logs match the current filters.</span>
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
              <span className="status-pill">Live</span>
            </div>
            <div className="alert-list">
              <AlertCard severity="error" title="Potential brute force" body="Multiple failed logins from the same network block." time="2m ago" />
              <AlertCard severity="warn" title="High consumer lag" body="Kafka consumer lag exceeded 50,000 records on raw-logs." time="15m ago" />
              <AlertCard severity="info" title="Model refreshed" body="Isolation Forest baseline updated with the latest rolling dataset." time="1h ago" />
            </div>
            <button className="pill-button" type="button" style={{ width: '100%', marginTop: 18 }}>
              View alert history
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
            {logs.slice(0, 10).map((log, i) => (
              <div key={log.id} className="terminal-line" style={{ opacity: 1 - i * 0.1 }}>
                <span className="term-time">[{log.time}]</span>
                <span className="term-prompt">user@logsentinel:~$</span>
                <span className="term-cmd">ingest --service {log.service} --level {log.level}</span>
                <div className="term-output">
                  <span className={`term-status ${log.level.toLowerCase()}`}>{log.level}</span>
                  <span>{log.msg}</span>
                  {log.anomaly && <span className="term-anomaly"> [!! ANOMALY DETECTED !!]</span>}
                </div>
              </div>
            ))}
            <div className="terminal-cursor">_</div>
          </div>
        </section>
      </div>
    </section>
  );
};

export default Dashboard;
