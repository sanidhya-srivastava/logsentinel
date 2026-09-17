import { Link } from 'react-router-dom';
import { Activity, Code2, ShieldCheck, Terminal } from 'lucide-react';

const groups = [
  {
    title: 'Product',
    links: [
      ['Features', '/features'],
      ['Workflow', '/workflow'],
      ['Security', '/security'],
      ['Dashboard', '/dashboard'],
    ],
  },
  {
    title: 'Resources',
    links: [
      ['API Docs', '/api-docs'],
      ['Open Console', '/console'],
      ['Live Metrics', '/dashboard'],
      ['Incident Review', '/console'],
    ],
  },
  {
    title: 'Operations',
    links: [
      ['Kafka Ingest', '/workflow'],
      ['Anomaly Model', '/features'],
      ['Alert Routing', '/security'],
      ['Health Checks', '/api-docs'],
    ],
  },
];

const Footer = () => (
  <footer className="footer">
    <div className="container">
      <div className="footer-grid">
        <div>
          <Link to="/" className="brand">
            <span className="brand-dot" aria-hidden="true" />
            <span>LogSentinel</span>
          </Link>
          <p>
            Cloud-native log ingestion, anomaly scoring, alert routing, and
            operator workflows in one real-time dashboard.
          </p>
          <div className="row-actions">
            <Link className="icon-button" to="/dashboard" aria-label="Dashboard">
              <Activity size={18} />
            </Link>
            <Link className="icon-button" to="/security" aria-label="Security">
              <ShieldCheck size={18} />
            </Link>
            <Link className="icon-button" to="/console" aria-label="Console">
              <Terminal size={18} />
            </Link>
            <a className="icon-button" href="https://github.com/Arnazz10/logsentinel" aria-label="Source repository">
              <Code2 size={18} />
            </a>
          </div>
        </div>

        {groups.map((group) => (
          <div key={group.title}>
            <h4>{group.title}</h4>
            <div className="footer-links">
              {group.links.map(([label, to]) => (
                <Link key={label} to={to}>
                  {label}
                </Link>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="footer-bottom">
        <span>2026 LogSentinel Platform. Built for live service operations.</span>
        <span>All systems operational</span>
      </div>
    </div>
  </footer>
);

export default Footer;
