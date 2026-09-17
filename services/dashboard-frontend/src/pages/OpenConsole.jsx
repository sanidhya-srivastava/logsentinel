import { useMemo, useState } from 'react';
import { Play, Search, Settings, Square, Terminal } from 'lucide-react';

const clusters = [
  ['prod-cluster-01', 'us-east-1'],
  ['staging-cluster', 'us-west-2'],
  ['dev-sandbox', 'ap-south-1'],
];

const lines = [
  { time: '19:35:01', level: 'INFO', service: 'auth', msg: 'User authenticated with session token', anomaly: false },
  { time: '19:35:04', level: 'DEBUG', service: 'ingest', msg: 'Buffer flush complete for 1,250 records', anomaly: false },
  { time: '19:35:08', level: 'ERROR', service: 'db', msg: 'Query execution timeout after 5000ms', anomaly: true },
  { time: '19:35:10', level: 'INFO', service: 'gateway', msg: 'GET /api/v1/health returned 200 OK', anomaly: false },
  { time: '19:35:12', level: 'INFO', service: 'ml', msg: 'Inference latency 12ms with score -0.021', anomaly: false },
  { time: '19:35:15', level: 'WARN', service: 'billing', msg: 'Retry storm detected against upstream provider', anomaly: true },
];

const tabs = ['Raw Stream', 'Anomalies', 'Live Metrics'];

const OpenConsole = () => {
  const [activeTab, setActiveTab] = useState(tabs[0]);
  const [activeCluster, setActiveCluster] = useState(clusters[0][0]);
  const [running, setRunning] = useState(true);
  const [query, setQuery] = useState('');
  const [command, setCommand] = useState('');
  const [history, setHistory] = useState(['logsentinel status --cluster prod-cluster-01']);

  const visibleLines = useMemo(() => {
    const normalized = query.toLowerCase().trim();
    return lines.filter((line) => {
      const matchesTab = activeTab !== 'Anomalies' || line.anomaly;
      const matchesQuery = !normalized || `${line.level} ${line.service} ${line.msg}`.toLowerCase().includes(normalized);
      return matchesTab && matchesQuery;
    });
  }, [activeTab, query]);

  const runCommand = (event) => {
    event.preventDefault();
    if (!command.trim()) return;
    setHistory((current) => [`${command.trim()}`, ...current].slice(0, 5));
    setCommand('');
  };

  return (
    <section className="console-page">
      <div className="console-shell">
        <aside className="console-sidebar">
          <div className="panel-head">
            <h2>
              <Terminal size={20} /> Console
            </h2>
            <button className="icon-button" type="button" aria-label="Console settings">
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
              <span className="status-pill">{running ? 'Connected' : 'Paused'}</span>
              <button className="pill-button" type="button" onClick={() => setRunning((value) => !value)}>
                {running ? <Square size={16} /> : <Play size={16} />}
                {running ? 'Pause stream' : 'Resume stream'}
              </button>
            </div>
          </div>

          <div className="terminal-window">
            <div className="terminal-intro">
              [SYS] LogSentinel Core v1.0.0 initialized<br />
              [SYS] Active cluster: {activeCluster}<br />
              [SYS] Kafka bootstrap servers connected at kafka:9092<br />
              [SYS] Isolation Forest model loaded with contamination 0.05<br />
              [SYS] Current view: {activeTab}
            </div>

            {activeTab === 'Live Metrics' ? (
              <div className="metric-grid">
                <div className="metric-card"><span className="metric-label">Consumer lag</span><span className="metric-value">1,204</span></div>
                <div className="metric-card"><span className="metric-label">Inference p95</span><span className="metric-value">22ms</span></div>
                <div className="metric-card"><span className="metric-label">Error rate</span><span className="metric-value">0.42%</span></div>
                <div className="metric-card"><span className="metric-label">Alert queue</span><span className="metric-value">7</span></div>
              </div>
            ) : (
              visibleLines.map((line) => (
                <div className="terminal-line" key={`${line.time}-${line.service}-${line.msg}`}>
                  <span className="log-time">[{line.time}]</span>
                  <strong className={`level-${line.level.toLowerCase()}`}>{line.level}</strong>
                  <span>{line.service}</span>
                  <span>{line.msg}</span>
                  {line.anomaly ? <span className="mini-chip">DETECTED</span> : <span />}
                </div>
              ))
            )}

            <div className="terminal-intro" style={{ marginTop: 24 }}>
              {history.map((item) => (
                <div key={item}><span className="prompt">$</span> {item}</div>
              ))}
            </div>
          </div>

          <form className="console-command" onSubmit={runCommand}>
            <span className="prompt">logsentinel$</span>
            <input
              className="console-input"
              value={command}
              onChange={(event) => setCommand(event.target.value)}
              placeholder="run query, tail service, or inspect anomaly"
            />
            <button className="pill-button primary" type="submit">Run</button>
          </form>
        </main>
      </div>
    </section>
  );
};

export default OpenConsole;
