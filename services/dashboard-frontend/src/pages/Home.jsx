import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Activity, ArrowRight, BarChart3, ShieldCheck, Terminal } from 'lucide-react';
import { fetchDashboardSnapshot } from '../api/client';

const heroStats = [
  ['10k/s', 'Target ingest throughput'],
  ['< 30s', 'Anomaly alert latency goal'],
  ['5%', 'Isolation Forest contamination'],
];

const Home = () => {
  const [snapshot, setSnapshot] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const data = await fetchDashboardSnapshot({ logLimit: 3, anomalyLimit: 3 });
        if (!cancelled) setSnapshot(data);
      } catch {
        // Ignore transient polling failures
      }
    };
    load();
    const timer = setInterval(load, 4000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const stats = snapshot?.stats;
  const logs = snapshot?.logs ?? [];
  const statusLabel = !snapshot?.reachable
    ? 'Backend Offline'
    : snapshot?.health?.status === 'degraded'
      ? 'Degraded'
      : 'Operational';

  const pulseMetrics = [
    ['Logs / second', Number(stats?.log_rate_per_second ?? 0).toFixed(2)],
    ['Anomaly rate', `${Number(stats?.anomaly_rate_percent ?? 0)}%`],
    ['Logs last hour', Number(stats?.logs_last_hour ?? 0).toLocaleString()],
    ['Total anomalies', Number(stats?.total_anomalies ?? 0).toLocaleString()],
  ];

  const modelLabel = snapshot?.modelStatus
    ? `${snapshot.modelStatus.model_type} (${snapshot.modelStatus.n_estimators} trees)`
    : 'Awaiting ML engine';

  return (
    <section className="hero">
      <div className="container hero-grid">
        <motion.div
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
        >
          <p className="eyebrow">Cloud-native AI observability</p>
          <h1>Detect the log patterns that break systems before users feel them.</h1>
          <p className="hero-copy">
            LogSentinel ingests logs in real time, streams them through Kafka,
            scores anomalies with Isolation Forest, and surfaces live service
            health in a single operations dashboard.
          </p>

          <div className="hero-actions">
            <Link className="pill-button primary" to="/dashboard">
              Launch Dashboard
              <Activity size={18} />
            </Link>
            <Link className="pill-button" to="/features">
              Explore Platform
              <ArrowRight size={18} />
            </Link>
            <Link className="pill-button" to="/console">
              Open Console
              <Terminal size={18} />
            </Link>
          </div>

          <div className="hero-stats">
            {heroStats.map(([value, label]) => (
              <div className="stat-tile" key={label}>
                <span className="stat-value">{value}</span>
                <span className="stat-label">{label}</span>
              </div>
            ))}
          </div>
        </motion.div>

        <motion.div
          className="pulse-card"
          initial={{ opacity: 0, scale: 0.96 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.65, delay: 0.12 }}
        >
          <div className="panel-head">
            <h2>Live platform pulse</h2>
            <span className="status-pill">{statusLabel}</span>
          </div>

          <div className="metric-grid">
            {pulseMetrics.map(([label, value]) => (
              <div className="metric-card" key={label}>
                <span className="metric-label">{label}</span>
                <span className="metric-value">{value}</span>
              </div>
            ))}
          </div>

          <div className="log-stack">
            {logs.length === 0 ? (
              <div className="log-pill">
                <span className="badge info">INFO</span>
                <span>
                  {snapshot?.reachable
                    ? 'Waiting for incoming logs on POST /ingest (:8000)'
                    : 'Start dashboard-backend (:8002) to stream live pulse data'}
                </span>
              </div>
            ) : (
              logs.slice(0, 3).map((log) => (
                <div className="log-pill" key={log.id}>
                  <span className={`badge ${log.level.toLowerCase()}`}>{log.level}</span>
                  <span>{log.service}: {log.msg}</span>
                </div>
              ))
            )}
          </div>

          <div className="hero-stats">
            <div className="stat-tile">
              <ShieldCheck size={20} />
              <span className="stat-label">Backend status</span>
              <span className="stat-value">{statusLabel}</span>
            </div>
            <div className="stat-tile">
              <BarChart3 size={20} />
              <span className="stat-label">ML Model</span>
              <span className="stat-value">{modelLabel}</span>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
};

export default Home;
