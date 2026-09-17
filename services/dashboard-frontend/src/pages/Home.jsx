import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Activity, ArrowRight, BarChart3, ShieldCheck, Terminal } from 'lucide-react';

const heroStats = [
  ['10k/s', 'Target ingest throughput'],
  ['< 30s', 'Anomaly alert latency goal'],
  ['5%', 'Isolation Forest contamination'],
];

const pulseMetrics = [
  ['Logs / second', '42.40'],
  ['Anomaly rate', '1.87%'],
  ['Logs last hour', '152,640'],
  ['Total anomalies', '286'],
];

const pulseLogs = [
  ['ERROR', 'auth-service: Database connection timeout after 5000ms'],
  ['WARN', 'payment-service: Retry storm detected against upstream billing provider'],
  ['INFO', 'gateway: Steady request flow observed across the last rolling window'],
];

const Home = () => (
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
          <span className="status-pill">Operational</span>
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
          {pulseLogs.map(([level, message]) => (
            <div className="log-pill" key={message}>
              <span className={`badge ${level.toLowerCase()}`}>{level}</span>
              <span>{message}</span>
            </div>
          ))}
        </div>

        <div className="hero-stats">
          <div className="stat-tile">
            <ShieldCheck size={20} />
            <span className="stat-label">Security posture</span>
            <span className="stat-value">Clean</span>
          </div>
          <div className="stat-tile">
            <BarChart3 size={20} />
            <span className="stat-label">Model confidence</span>
            <span className="stat-value">97.4%</span>
          </div>
        </div>
      </motion.div>
    </div>
  </section>
);

export default Home;
