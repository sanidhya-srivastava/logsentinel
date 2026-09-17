import {
  Activity,
  ArrowRight,
  BellRing,
  Cpu,
  Database,
  GitBranch,
  KeyRound,
  Layers,
  LockKeyhole,
  Radio,
  ServerCog,
  ShieldCheck,
  Workflow as WorkflowIcon,
  Zap,
} from 'lucide-react';

const PageHeader = ({ title, subtitle }) => (
  <header className="page-header">
    <p className="eyebrow">LogSentinel platform</p>
    <h1>{title}</h1>
    <p>{subtitle}</p>
  </header>
);

const FeatureCard = ({ icon, title, desc }) => (
  <article className="feature-card">
    <span className="icon-box">{icon}</span>
    <h3>{title}</h3>
    <p>{desc}</p>
  </article>
);

const features = [
  [<Radio size={24} />, 'Live log ingestion', 'Stream single logs or batches into Kafka-backed ingestion with schema validation and service tagging.'],
  [<Cpu size={24} />, 'AI anomaly detection', 'Isolation Forest scoring flags unusual latency, error bursts, retry storms, and suspicious request shapes.'],
  [<BellRing size={24} />, 'Alert routing', 'Deduplicate anomalies and route critical events to Slack, email, PagerDuty, or your internal webhook.'],
  [<Activity size={24} />, 'Service health timeline', 'Track throughput, anomaly rate, error budget burn, and rolling service status from one console.'],
  [<Database size={24} />, 'Searchable retention', 'Persist structured logs for root cause analysis, audit review, and trend comparisons.'],
  [<Layers size={24} />, 'Operator dashboard', 'Correlate raw logs, scored anomalies, source clusters, and remediation actions without switching tools.'],
];

const workflow = [
  ['01', 'Collect', 'Agents, Fluent Bit, or the REST API submit structured service logs.'],
  ['02', 'Validate', 'The API normalizes severity, timestamps, host metadata, response time, and error codes.'],
  ['03', 'Stream', 'Kafka buffers validated events so processors can scale without dropping traffic.'],
  ['04', 'Score', 'The ML worker enriches records and scores anomalies against Isolation Forest baselines.'],
  ['05', 'Alert', 'Rules combine model output, severity, and service context before notifying responders.'],
  ['06', 'Investigate', 'Operators jump from anomalies to raw logs, related services, and API traces.'],
];

const security = [
  [<ShieldCheck size={24} />, 'Defense by default', 'TLS for transport, scoped API keys, service identity checks, and least-privilege deployment boundaries.'],
  [<LockKeyhole size={24} />, 'Sensitive data control', 'PII redaction hooks and retention policies keep logs useful without exposing secrets.'],
  [<KeyRound size={24} />, 'Keyed API access', 'Every ingestion endpoint is designed for API-key authentication and audit-friendly ownership.'],
  [<ServerCog size={24} />, 'Operational hardening', 'Health checks, rate limits, and alert deduplication reduce noisy failures during incidents.'],
];

export const Features = () => (
  <section className="page">
    <div className="container">
      <PageHeader
        title="Everything needed to see, score, and resolve log anomalies."
        subtitle="A complete operations surface for ingestion, machine-learning detection, live dashboards, and response workflows."
      />
      <div className="feature-grid">
        {features.map(([icon, title, desc]) => (
          <FeatureCard key={title} icon={icon} title={title} desc={desc} />
        ))}
      </div>
    </div>
  </section>
);

export const Workflow = () => (
  <section className="page">
    <div className="container">
      <PageHeader
        title="From raw service log to actionable incident."
        subtitle="LogSentinel keeps the pipeline clear: collect, validate, stream, score, alert, investigate."
      />
      <div className="workflow-list">
        {workflow.map(([num, title, desc]) => (
          <article className="workflow-step" key={title}>
            <span className="step-num">{num}</span>
            <div>
              <h3>{title}</h3>
              <p>{desc}</p>
            </div>
            <ArrowRight size={22} />
          </article>
        ))}
      </div>
    </div>
  </section>
);

export const Security = () => (
  <section className="page">
    <div className="container">
      <PageHeader
        title="Security controls for high-volume operational data."
        subtitle="LogSentinel is designed around protected ingestion, scoped access, safer retention, and reliable incident handling."
      />
      <div className="feature-grid">
        {security.map(([icon, title, desc]) => (
          <FeatureCard key={title} icon={icon} title={title} desc={desc} />
        ))}
      </div>
      <div className="workflow-list" style={{ marginTop: 24 }}>
        <article className="workflow-step">
          <span className="icon-box">
            <GitBranch size={24} />
          </span>
          <div>
            <h3>Recommended deployment path</h3>
            <p>
              Put ingestion behind your API gateway, issue per-service API keys,
              keep Kafka private, and expose the dashboard through your existing
              SSO boundary.
            </p>
          </div>
          <WorkflowIcon size={24} />
        </article>
        <article className="workflow-step">
          <span className="icon-box">
            <Zap size={24} />
          </span>
          <div>
            <h3>Incident response posture</h3>
            <p>
              Critical anomalies stay visible in the dashboard and console while
              alert webhooks carry the service, score, timestamp, and related log context.
            </p>
          </div>
          <ShieldCheck size={24} />
        </article>
      </div>
    </div>
  </section>
);
