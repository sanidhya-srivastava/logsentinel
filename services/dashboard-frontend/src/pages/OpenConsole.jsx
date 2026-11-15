import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Play, Search, Settings, Square, Terminal } from 'lucide-react';
import { fetchDashboardSnapshot, ingestLog } from '../api/client';

const clusters = [
  ['local-compose', 'localhost:8002'],
  ['staging-cluster', 'us-west-2'],
  ['prod-cluster-01', 'us-east-1'],
];

const tabs = ['Raw Stream', 'Anomalies', 'Live Metrics'];

const OpenConsole = () => {
  const [activeTab, setActiveTab] = useState(tabs[0]);
  const [activeCluster, setActiveCluster] = useState(clusters[0][0]);
  const [running, setRunning] = useState(true);
  const [query, setQuery] = useState('');
  const [command, setCommand] = useState('');
  const [snapshot, setSnapshot] = useState(null);
  const [history, setHistory] = useState([
    'connected to dashboard-backend (:8002) — type "help" for commands',
  ]);

  const inFlightRef = useRef(false);

  const loadSnapshot = useCallback(async (forceFresh = false) => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      const data = await fetchDashboardSnapshot({ forceFresh, logLimit: 100, anomalyLimit: 50 });
      setSnapshot(data);
    } finally {
      inFlightRef.current = false;
    }
  }, []);

  useEffect(() => {
    loadSnapshot(false);
    if (!running) return undefined;
    const timer = setInterval(() => loadSnapshot(false), 3000);
    return () => clearInterval(timer);
  }, [running, loadSnapshot]);

  const visibleLines = useMemo(() => {
    const normalized = query.toLowerCase().trim();
    const source =
      activeTab === 'Anomalies'
        ? (snapshot?.anomalies || []).map((a) => ({
            id: a.id,
            time: a.detectedAt ? new Date(a.detectedAt).toLocaleTimeString('en-US', { hour12: false }) : '--:--:--',
            level: a.level.toUpperCase(),
            service: a.service,
            msg: `${a.message} (score: ${Number(a.score).toFixed(3)})`,
            anomaly: true,
          }))
        : snapshot?.logs || [];

    return source.filter((line) => {
      if (!normalized) return true;
      return `${line.level} ${line.service} ${line.msg}`.toLowerCase().includes(normalized);
    });
  }, [activeTab, query, snapshot]);

  const appendHistory = (entry) => {
    setHistory((current) => [entry, ...current].slice(0, 8));
  };

  const runCommand = async (event) => {
    event.preventDefault();
    const raw = command.trim();
    if (!raw) return;
    setCommand('');
    appendHistory(raw);

    const [cmd, ...args] = raw.split(/\s+/);
    const lower = cmd.toLowerCase();

    if (lower === 'help') {
      appendHistory('commands: help | status | refresh | clear | filter <text> | ingest <service> <level> <message>');
    } else if (lower === 'clear') {
      setHistory([]);
    } else if (lower === 'refresh') {
      await loadSnapshot(true);
      appendHistory('refreshed snapshot from backend (:8002)');
    } else if (lower === 'filter') {
      setQuery(args.join(' '));
      appendHistory(`filter set to "${args.join(' ')}"`);
    } else if (lower === 'status') {
      const checks = snapshot?.health?.checks
        ? Object.entries(snapshot.health.checks).map(([k, v]) => `${k}=${v}`).join(', ')
        : 'backend offline';
      appendHistory(`health: ${snapshot?.health?.status || 'offline'} (${checks})`);
    } else if (lower === 'ingest') {
      const [service = 'console-app', level = 'INFO', ...msgParts] = args;
      const message = msgParts.join(' ') || 'Log submitted from OpenConsole';
      try {
        const res = await ingestLog({ service, level, message });
        appendHistory(`accepted log_id=${res.log_id}`);
        setTimeout(() => loadSnapshot(true), 1200);
      } catch (err) {
        appendHistory(`ingest failed: ${err.message}`);
      }
    } else {
      appendHistory(`unknown command "${cmd}" — try "help"`);
    }
  };

  const stats = snapshot?.stats;
  const statusText = !snapshot?.reachable
    ? 'Offline'
    : running
      ? `Connected · ${new Date(snapshot.lastUpdated).toLocaleTimeString()}`
      : 'Paused';

  return (
    <section className="console-page">
      <div className="console-shell">
        <aside className="console-sidebar">
          <div className="panel-head">
            <h2>
              <Terminal size={20} /> Console
            </h2>
            <button className="icon-button" type="button" aria-label="Refresh console" onClick={() => loadSnapshot(true)}>
              <Settings size={17} />
            </button>
          </div>

          <div className="search-box" style={{ marginBottom: 16 }}>
            <Search size={16} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter stream" />
          </div>

          <div className="cluster-list">
            {clusters.map(([name, region]) => (
              <button
                className={`cluster-button ${activeCluster === name ? 'active' : ''}`}
                key={name}
                type="button"
                onClick={() => setActiveCluster(name)}
              >
                <strong>{name}</strong>
                <span>{region}</span>
              </button>
            ))}
          </div>
        </aside>

        <main className="console-main">
          <div className="console-topbar">
            <div className="tab-list">
              {tabs.map((tab) => (
                <button
                  className={`tab-button ${activeTab === tab ? 'active' : ''}`}
                  key={tab}
                  type="button"
                  onClick={() => setActiveTab(tab)}
                >
                  {tab}
                </button>
              ))}
            </div>
            <div className="row-actions">
              <span className="status-pill">{statusText}</span>
              <button className="pill-button" type="button" onClick={() => setRunning((value) => !value)}>
                {running ? <Square size={16} /> : <Play size={16} />}
                {running ? 'Pause stream' : 'Resume stream'}
              </button>
            </div>
          </div>

          <div className="terminal-window">
            <div className="terminal-intro">
              [SYS] LogSentinel Console · target cluster: {activeCluster}<br />
              [SYS] Backend (:8002): {snapshot?.reachable ? snapshot?.health?.status || 'connected' : 'offline'}<br />
              [SYS] ES: {snapshot?.health?.checks?.elasticsearch ?? 'unknown'} | DB: {snapshot?.health?.checks?.database ?? 'unknown'} | Cache: {snapshot?.health?.checks?.cache ?? 'unknown'}<br />
              [SYS] ML Engine (:8001): {snapshot?.modelStatus ? `${snapshot.modelStatus.model_type} (${snapshot.modelStatus.n_estimators} trees)` : 'offline'}<br />
              [SYS] Current view: {activeTab}
            </div>

            {activeTab === 'Live Metrics' ? (
              <div className="metric-grid">
                <div className="metric-card"><span className="metric-label">Logs / min</span><span className="metric-value">{Number(stats?.logs_last_minute ?? 0).toLocaleString()}</span></div>
                <div className="metric-card"><span className="metric-label">Logs (1h)</span><span className="metric-value">{Number(stats?.logs_last_hour ?? 0).toLocaleString()}</span></div>
                <div className="metric-card"><span className="metric-label">Anomaly rate</span><span className="metric-value">{Number(stats?.anomaly_rate_percent ?? 0)}%</span></div>
                <div className="metric-card"><span className="metric-label">Total alerts</span><span className="metric-value">{Number(stats?.total_anomalies ?? 0).toLocaleString()}</span></div>
              </div>
            ) : visibleLines.length === 0 ? (
              <div className="terminal-line">
                <span className="log-time">[--:--:--]</span>
                <strong className="level-info">INFO</strong>
                <span>system</span>
                <span>
                  {snapshot?.reachable
                    ? 'No matching events yet. Run: ingest demo-app ERROR "Timeout on payment gateway"'
                    : 'Waiting for dashboard-backend (:8002)...'}
                </span>
                <span />
              </div>
            ) : (
              visibleLines.map((line) => (
                <div className="terminal-line" key={`${line.id}-${line.time}`}>
                  <span className="log-time">[{line.time}]</span>
                  <strong className={`level-${line.level.toLowerCase()}`}>{line.level}</strong>
                  <span>{line.service}</span>
                  <span>{line.msg}</span>
                  {line.anomaly ? <span className="mini-chip">DETECTED</span> : <span />}
                </div>
              ))
            )}

            <div className="terminal-intro" style={{ marginTop: 24 }}>
              {history.map((item, idx) => (
                <div key={`${idx}-${item}`}><span className="prompt">$</span> {item}</div>
              ))}
            </div>
          </div>

          <form className="console-command" onSubmit={runCommand}>
            <span className="prompt">logsentinel$</span>
            <input
              className="console-input"
              value={command}
              onChange={(event) => setCommand(event.target.value)}
              placeholder='help, status, refresh, filter <text>, or ingest <svc> <LVL> <msg>'
            />
            <button className="pill-button primary" type="submit">Run</button>
          </form>
        </main>
      </div>
    </section>
  );
};

export default OpenConsole;
