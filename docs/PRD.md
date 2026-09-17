# LogSentinel — Product Requirements Document (PRD)

**Version:** 1.0.0
**Status:** Approved
**Last Updated:** 2025-01-01
**Owner:** LogSentinel Engineering Team

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Goals & Objectives](#3-goals--objectives)
4. [Scope](#4-scope)
5. [Stakeholders](#5-stakeholders)
6. [User Personas](#6-user-personas)
7. [Functional Requirements](#7-functional-requirements)
8. [Non-Functional Requirements](#8-non-functional-requirements)
9. [System Architecture Overview](#9-system-architecture-overview)
10. [Data Models](#10-data-models)
11. [API Specifications](#11-api-specifications)
12. [ML Model Requirements](#12-ml-model-requirements)
13. [Infrastructure Requirements](#13-infrastructure-requirements)
14. [Security Requirements](#14-security-requirements)
15. [Observability Requirements](#15-observability-requirements)
16. [Constraints & Assumptions](#16-constraints--assumptions)
17. [Risks](#17-risks)
18. [Milestones & Timeline](#18-milestones--timeline)
19. [Success Metrics](#19-success-metrics)
20. [Glossary](#20-glossary)

---

## 1. Executive Summary

**LogSentinel** is a cloud-native, AI-powered log monitoring and anomaly detection platform designed to ingest, process, and analyze application logs at scale in real time. It automatically identifies abnormal system behaviors using machine learning, alerts operations teams before outages occur, and provides a rich monitoring dashboard for full system observability.

The platform is built as a collection of loosely coupled microservices deployed on Kubernetes, backed by a streaming data pipeline powered by Apache Kafka, and leverages an Isolation Forest ML model to detect anomalies with a 5% contamination threshold.

LogSentinel transforms raw, unstructured log streams into actionable intelligence, reducing mean time to detection (MTTD) for production incidents by providing automated, real-time anomaly alerts instead of relying on manual log inspection.

---

## 2. Problem Statement

### Current State (Pain Points)

Modern distributed systems generate millions of log lines per day across dozens of microservices. Operations teams face the following challenges:

| Problem | Business Impact |
|---|---|
| Manual log inspection is slow and error-prone | Incidents are detected hours after they begin |
| Log data is siloed across services | No unified view of system health |
| Alert fatigue from threshold-based monitors | Critical alerts are missed in the noise |
| No historical anomaly tracking | Post-mortems are incomplete |
| Scaling log collection is operationally expensive | Engineering time wasted on tooling, not product |
| No ML-driven anomaly detection | Pattern-based anomalies (not threshold violations) go undetected |

### Target State

LogSentinel provides:

- **Unified ingestion** of logs from any service via a REST API or Fluentd agent
- **Real-time streaming** processing through Kafka
- **Automated ML-powered** anomaly detection (Isolation Forest)
- **Instant alerting** via Slack and Email on detected anomalies
- **Centralized dashboards** in Grafana showing system health, anomaly trends, and service status
- **Scalable, cloud-native** infrastructure on Kubernetes/AWS that scales automatically with log volume

---

## 3. Goals & Objectives

### Primary Goals

1. **Detect anomalies automatically** in log streams without manual threshold configuration
2. **Alert operations teams** within 30 seconds of anomaly detection
3. **Process at least 10,000 logs/second** at peak load with horizontal scaling
4. **Achieve 95%+ uptime** for all core services
5. **Reduce MTTD** (Mean Time to Detect) from hours to under 60 seconds

### Secondary Goals

1. Provide a queryable log search API backed by Elasticsearch
2. Offer historical anomaly trend analysis via Grafana dashboards
3. Support pluggable alerting channels (Slack, Email — extensible to PagerDuty)
4. Enable ML model retraining on fresh log data without service downtime
5. Provide Prometheus metrics for all services for operational visibility

### Non-Goals (Out of Scope for v1.0)

- Log-based security threat detection (SIEM functionality)
- User authentication / authorization for the API (internal use only in v1)
- Support for Windows Event Logs
- Real-time log streaming UI (terminal viewer)
- Automatic remediation / self-healing actions

---

## 4. Scope

### In Scope

| Component | Description |
|---|---|
| Log Ingestion API | FastAPI REST endpoint to receive logs |
| Log Processor | Kafka consumer for log cleaning and feature extraction |
| ML Engine | Isolation Forest model training, inference, and Kafka integration |
| Alert Service | Anomaly alert deduplication and routing (Slack + Email) |
| Dashboard Backend | Query API for Grafana and potential frontend |
| Kafka Pipeline | Raw logs → processed logs → anomaly alerts topics |
| Elasticsearch | Indexed log storage and search |
| PostgreSQL | Alert history, metadata storage |
| Redis | Alert deduplication cache |
| Prometheus + Grafana | Metrics collection and dashboards |
| Docker + Kubernetes | Containerization and orchestration |
| Terraform | AWS infrastructure provisioning |
| GitHub Actions CI/CD | Automated build, test, and deployment pipeline |

### Out of Scope

- Mobile application
- Multi-tenant SaaS features
- Billing or subscription management
- Log encryption at the application layer (handled at infrastructure layer)
- Browser-based log viewer UI (Grafana used instead)

---

## 5. Stakeholders

| Stakeholder | Role | Interest |
|---|---|---|
| Engineering Team | Builders | Deliver the platform on time with quality |
| Platform / DevOps Team | Operators | Deploy, maintain, and scale the platform |
| Site Reliability Engineers (SREs) | Primary Users | Use dashboards and alerts for incident response |
| Development Teams | Log Producers | Integrate their services with the log ingestion API |
| Engineering Manager | Sponsor | Track delivery milestones and ROI |
| Security Team | Reviewers | Ensure secrets management and access control compliance |

---

## 6. User Personas

### Persona 1 — Alex, Site Reliability Engineer

- **Goal:** Get alerted immediately when a service behaves abnormally
- **Pain point:** Spends 30+ minutes searching logs manually during incidents
- **Uses:** Grafana dashboards, Slack alerts, anomaly history API
- **Success:** Receives a Slack notification within 30 seconds of an anomaly; drills into Grafana for context

### Persona 2 — Priya, Backend Developer

- **Goal:** Verify her service is operating normally after a deployment
- **Workflow:** Pushes a deploy → checks Grafana for log rate changes and error spikes
- **Uses:** Dashboard Backend API (`GET /logs`, `GET /stats`), Grafana
- **Success:** Log ingestion rate for her service is visible in real time on the dashboard

### Persona 3 — Marcus, DevOps Engineer

- **Goal:** Maintain and scale the platform; ensure CI/CD pipeline is green
- **Uses:** Kubernetes manifests, Helm charts, GitHub Actions, Terraform
- **Success:** Full deployment completes in under 10 minutes; K8s pods auto-scale under load

### Persona 4 — Fatima, ML Engineer

- **Goal:** Retrain and evaluate the anomaly detection model on new data
- **Uses:** `ml/train.py`, `ml/evaluate.py`, Jupyter notebooks
- **Success:** Retraining completes in < 5 minutes; new model is deployed without downtime

---

## 7. Functional Requirements

### FR-1: Log Ingestion API

| ID | Requirement | Priority |
|---|---|---|
| FR-1.1 | The system SHALL expose a `POST /ingest` endpoint to receive individual log entries as JSON | P0 |
| FR-1.2 | The system SHALL expose a `POST /ingest/batch` endpoint to receive up to 100 log entries in a single request | P0 |
| FR-1.3 | The system SHALL validate all incoming log entries using Pydantic models, rejecting malformed requests with HTTP 422 | P0 |
| FR-1.4 | The system SHALL publish validated logs to the Kafka `raw-logs` topic | P0 |
| FR-1.5 | The system SHALL expose a `GET /health` endpoint returning service health status | P0 |
| FR-1.6 | The system SHALL expose a `GET /metrics` endpoint with Prometheus metrics | P0 |
| FR-1.7 | The system SHALL respond to `POST /ingest` within 200ms at the 99th percentile under normal load | P1 |
| FR-1.8 | The system SHALL assign a unique `log_id` (UUID) to each ingested log entry | P1 |
| FR-1.9 | The system SHALL add a server-side `ingested_at` timestamp to each log entry | P1 |

### FR-2: Log Processor

| ID | Requirement | Priority |
|---|---|---|
| FR-2.1 | The processor SHALL consume messages from the Kafka `raw-logs` topic | P0 |
| FR-2.2 | The processor SHALL parse and normalize log levels (DEBUG, INFO, WARN, ERROR, CRITICAL) | P0 |
| FR-2.3 | The processor SHALL extract structured features: `hour_of_day`, `response_time_ms`, `error_code`, `log_level_encoded`, `service_id_encoded` | P0 |
| FR-2.4 | The processor SHALL index structured logs into Elasticsearch index `logsentinel-logs` | P0 |
| FR-2.5 | The processor SHALL publish processed log documents to the Kafka `processed-logs` topic | P0 |
| FR-2.6 | The processor SHALL handle malformed messages gracefully, logging errors without crashing | P0 |
| FR-2.7 | The processor SHALL maintain a rolling count of requests per service per 60-second window | P1 |

### FR-3: ML Engine

| ID | Requirement | Priority |
|---|---|---|
| FR-3.1 | The ML engine SHALL load a pre-trained Isolation Forest model on startup | P0 |
| FR-3.2 | The ML engine SHALL consume from the Kafka `processed-logs` topic and score each entry | P0 |
| FR-3.3 | The ML engine SHALL publish entries scoring as anomalies (score = -1) to `anomaly-alerts` topic | P0 |
| FR-3.4 | The ML engine SHALL expose a `POST /predict` endpoint for synchronous single-entry inference | P0 |
| FR-3.5 | The ML engine SHALL expose a `GET /model/status` endpoint reporting model metadata | P0 |
| FR-3.6 | The ML engine SHALL expose a `POST /predict/batch` endpoint for batch inference | P1 |
| FR-3.7 | The ML engine SHALL return inference results within 100ms at the 99th percentile | P1 |
| FR-3.8 | The ML engine SHALL support hot-reload of a newly trained model without restart | P2 |

### FR-4: Alert Service

| ID | Requirement | Priority |
|---|---|---|
| FR-4.1 | The alert service SHALL consume from the Kafka `anomaly-alerts` topic | P0 |
| FR-4.2 | The alert service SHALL deduplicate alerts using Redis, suppressing duplicates within a configurable TTL (default: 1 hour) | P0 |
| FR-4.3 | The alert service SHALL send Slack notifications via webhook for each unique anomaly | P0 |
| FR-4.4 | The alert service SHALL send Email notifications via SMTP for each unique anomaly | P0 |
| FR-4.5 | The alert service SHALL persist all alerts (including duplicates) to PostgreSQL | P0 |
| FR-4.6 | Each Slack alert SHALL include: service name, log level, anomaly score, timestamp, and message excerpt | P1 |
| FR-4.7 | The alert service SHALL retry failed notifications up to 3 times with exponential backoff | P1 |
| FR-4.8 | The alert service SHALL support per-channel enable/disable via environment variables | P1 |

### FR-5: Dashboard Backend

| ID | Requirement | Priority |
|---|---|---|
| FR-5.1 | The backend SHALL expose `GET /logs` with pagination, filtering by `level`, `service`, and time range | P0 |
| FR-5.2 | The backend SHALL expose `GET /anomalies` with pagination and time range filtering | P0 |
| FR-5.3 | The backend SHALL expose `GET /stats` returning log rate, anomaly rate, and per-service counts | P0 |
| FR-5.4 | The backend SHALL expose `GET /health` for liveness checks | P0 |
| FR-5.5 | The backend SHALL support Grafana Simple JSON datasource protocol | P1 |
| FR-5.6 | The backend SHALL cache `GET /stats` responses in Redis for 10 seconds | P1 |

---

## 8. Non-Functional Requirements

### Performance

| ID | Requirement |
|---|---|
| NFR-P1 | The ingestion API SHALL handle 10,000 logs/second at steady state |
| NFR-P2 | The ingestion API `POST /ingest` p99 latency SHALL be < 200ms |
| NFR-P3 | Kafka consumer lag SHALL not exceed 10,000 messages under normal load |
| NFR-P4 | ML inference latency SHALL be < 100ms per entry (p99) |
| NFR-P5 | Elasticsearch indexing SHALL complete within 5 seconds of log ingestion |
| NFR-P6 | End-to-end anomaly alert latency (ingest → Slack notification) SHALL be < 30 seconds |

### Scalability

| ID | Requirement |
|---|---|
| NFR-S1 | All services SHALL be horizontally scalable via Kubernetes HPA |
| NFR-S2 | HPA SHALL scale from minimum 2 to maximum 10 replicas based on CPU utilization (target: 70%) |
| NFR-S3 | Kafka topics SHALL have a minimum of 3 partitions to enable parallel consumption |
| NFR-S4 | Elasticsearch SHALL be configured with 1 primary shard and 1 replica per index |

### Reliability

| ID | Requirement |
|---|---|
| NFR-R1 | All services SHALL achieve 99.5% uptime SLA |
| NFR-R2 | All services SHALL implement liveness and readiness probes in Kubernetes |
| NFR-R3 | All Kafka consumers SHALL use manual offset commit to prevent message loss |
| NFR-R4 | Kafka consumer errors SHALL trigger automatic retry with exponential backoff |
| NFR-R5 | Database connections SHALL use connection pooling with automatic reconnection |

### Maintainability

| ID | Requirement |
|---|---|
| NFR-M1 | All services SHALL follow PEP8 coding standards, enforced by flake8 and black |
| NFR-M2 | Unit test coverage SHALL be ≥ 80% for all service modules |
| NFR-M3 | All configuration SHALL be externalised via environment variables (12-factor app) |
| NFR-M4 | Every service SHALL emit structured JSON logs with correlation IDs |
| NFR-M5 | All Docker images SHALL be multi-stage builds based on python:3.11-slim |

### Portability

| ID | Requirement |
|---|---|
| NFR-PT1 | The full platform SHALL run locally via a single `make up` command using Docker Compose |
| NFR-PT2 | The platform SHALL deploy to any Kubernetes cluster (not AWS-specific) |

---

## 9. System Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                          LogSentinel Data Flow                                 │
│                                                                                │
│   [App A] ──┐                                                                  │
│   [App B] ──┼──► POST /ingest ──► [Log Ingestion API] ──► [Kafka: raw-logs]   │
│   [App C] ──┘       (FastAPI)            │                       │             │
│   [Fluentd]─────────────────────────────┘          ┌────────────▼──────────┐  │
│                                                     │    Log Processor      │  │
│                                                     │  (Kafka Consumer)     │  │
│                                                     └────────┬──────┬───────┘  │
│                                                              │      │           │
│                                                   [Elasticsearch] [Kafka:      │
│                                                   (log storage)   processed]   │
│                                                              │      │           │
│                                                   ┌──────────┘  ┌──▼──────────┐│
│                                                   │Dashboard    │  ML Engine  ││
│                                                   │Backend      │(Iso. Forest)││
│                                                   │(FastAPI)    └──────┬──────┘│
│                                                   │                   │        │
│                                            [Grafana]       [Kafka: anomalies]  │
│                                         [Prometheus]                 │         │
│                                                              ┌───────▼───────┐ │
│                                                              │ Alert Service │ │
│                                                              │ Redis│PgSQL   │ │
│                                                              │ Slack│Email   │ │
│                                                              └───────────────┘ │
└────────────────────────────────────────────────────────────────────────────────┘
```

### Component Interaction Summary

| From | To | Protocol | Topic/Endpoint |
|---|---|---|---|
| Client Apps | Log Ingestion API | HTTP/REST | `POST /ingest` |
| Log Ingestion API | Kafka | Kafka Producer | `raw-logs` |
| Log Processor | Kafka | Kafka Consumer | `raw-logs` |
| Log Processor | Elasticsearch | HTTP | `logsentinel-logs` index |
| Log Processor | Kafka | Kafka Producer | `processed-logs` |
| ML Engine | Kafka | Kafka Consumer | `processed-logs` |
| ML Engine | Kafka | Kafka Producer | `anomaly-alerts` |
| Alert Service | Kafka | Kafka Consumer | `anomaly-alerts` |
| Alert Service | Redis | TCP | Deduplication cache |
| Alert Service | PostgreSQL | TCP | Alert persistence |
| Alert Service | Slack | HTTPS | Webhook |
| Alert Service | SMTP Server | SMTP/TLS | Email |
| Dashboard Backend | Elasticsearch | HTTP | Log queries |
| Dashboard Backend | PostgreSQL | TCP | Anomaly queries |
| Grafana | Dashboard Backend | HTTP | Grafana datasource |
| Prometheus | All FastAPI services | HTTP | `GET /metrics` |

---

## 10. Data Models

### LogEntry (Input to Ingestion API)

```json
{
  "log_id": "uuid-auto-generated",
  "service": "auth-service",
  "host": "pod-abc123",
  "level": "ERROR",
  "message": "Database connection timeout after 5000ms",
  "response_time_ms": 5000.0,
  "error_code": 503,
  "timestamp": "2024-01-15T03:22:14.512Z",
  "ingested_at": "2024-01-15T03:22:14.600Z",
  "metadata": {
    "trace_id": "abc123",
    "user_id": "optional"
  }
}
```

### ProcessedLog (Kafka: processed-logs)

```json
{
  "log_id": "uuid",
  "service": "auth-service",
  "host": "pod-abc123",
  "level": "ERROR",
  "message": "Database connection timeout after 5000ms",
  "response_time_ms": 5000.0,
  "error_code": 503,
  "timestamp": "2024-01-15T03:22:14.512Z",
  "features": {
    "hour_of_day": 3,
    "response_time_ms": 5000.0,
    "error_code": 503,
    "log_level_encoded": 3,
    "request_count_last_60s": 1245,
    "service_id_encoded": 2
  }
}
```

### AnomalyAlert (Kafka: anomaly-alerts / PostgreSQL)

```json
{
  "alert_id": "uuid",
  "log_id": "uuid",
  "service": "auth-service",
  "level": "ERROR",
  "message": "Database connection timeout after 5000ms",
  "anomaly_score": -0.312,
  "features": { ... },
  "detected_at": "2024-01-15T03:22:15.100Z",
  "notification_sent": true,
  "notification_channels": ["slack", "email"],
  "deduplicated": false
}
```

### PostgreSQL: alerts Table

```sql
CREATE TABLE alerts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    log_id      UUID NOT NULL,
    alert_id    UUID NOT NULL UNIQUE,
    service     VARCHAR(255) NOT NULL,
    level       VARCHAR(20) NOT NULL,
    message     TEXT,
    anomaly_score FLOAT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    slack_sent  BOOLEAN DEFAULT FALSE,
    email_sent  BOOLEAN DEFAULT FALSE,
    deduplicated BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 11. API Specifications

### Log Ingestion API — `http://localhost:8000`

| Method | Path | Description | Request Body | Response |
|---|---|---|---|---|
| POST | `/ingest` | Ingest a single log entry | `LogEntry` JSON | `202 Accepted` + `{log_id, status}` |
| POST | `/ingest/batch` | Ingest up to 100 log entries | `List[LogEntry]` JSON | `202 Accepted` + `{accepted, rejected}` |
| GET | `/health` | Service health check | — | `200 OK` + health object |
| GET | `/metrics` | Prometheus metrics | — | Prometheus text format |
| GET | `/docs` | Swagger UI | — | HTML |

### ML Engine API — `http://localhost:8001`

| Method | Path | Description | Request Body | Response |
|---|---|---|---|---|
| POST | `/predict` | Predict anomaly for one entry | `FeatureVector` JSON | `200 OK` + `{score, is_anomaly}` |
| POST | `/predict/batch` | Batch prediction | `List[FeatureVector]` | `200 OK` + list of results |
| GET | `/model/status` | Model metadata and health | — | `200 OK` + model info |
| GET | `/health` | Service health | — | `200 OK` |
| GET | `/metrics` | Prometheus metrics | — | Prometheus text format |

### Dashboard Backend API — `http://localhost:8002`

| Method | Path | Description | Query Params | Response |
|---|---|---|---|---|
| GET | `/logs` | Paginated log search | `page, size, level, service, start, end` | `200 OK` + paginated logs |
| GET | `/anomalies` | List anomalies | `page, size, start, end, service` | `200 OK` + paginated anomalies |
| GET | `/stats` | System statistics | `window_minutes` | `200 OK` + stats object |
| GET | `/health` | Service health | — | `200 OK` |
| GET | `/metrics` | Prometheus metrics | — | Prometheus text format |

---

## 12. ML Model Requirements

### Algorithm Selection

| Algorithm | Rationale |
|---|---|
| **Isolation Forest** (Primary) | Unsupervised; no labeled anomaly data required; handles high-dimensional sparse anomalies; efficient at scale |
| One-Class SVM (Fallback) | Available as alternative if Isolation Forest F1 drops below 0.80 |

### Feature Engineering

| Feature | Source | Transformation |
|---|---|---|
| `hour_of_day` | `timestamp` | `timestamp.hour` (0–23) |
| `response_time_ms` | Log field | Min-max scaled |
| `error_code` | Log field | Integer; 200=0, 4xx=1, 5xx=2, 0=3 |
| `log_level_encoded` | `level` field | DEBUG=0, INFO=1, WARN=2, ERROR=3, CRITICAL=4 |
| `request_count_last_60s` | Rolling counter | Per-service sliding window |
| `service_id_encoded` | `service` field | Label-encoded dictionary |

### Model Configuration

```yaml
algorithm: IsolationForest
n_estimators: 100
contamination: 0.05
max_samples: auto
max_features: 1.0
bootstrap: false
random_state: 42
```

### Model Performance Requirements

| Metric | Minimum Threshold |
|---|---|
| Precision | ≥ 0.80 |
| Recall | ≥ 0.75 |
| F1-Score | ≥ 0.77 |
| Inference latency (p99) | < 100ms |
| Training time on 100k samples | < 5 minutes |

### Model Lifecycle

1. **Training:** `ml/train.py` — generates `isolation_forest.joblib` + `scaler.joblib`
2. **Evaluation:** `ml/evaluate.py` — outputs metrics to `ml/models/evaluation_report.json`
3. **Deployment:** Model file mounted into ML Engine container via volume or S3 download on startup
4. **Retraining:** Triggered manually or via CI/CD on new training data; rolling deployment handles cutover

---

## 13. Infrastructure Requirements

### AWS Resources

| Resource | Type | Configuration |
|---|---|---|
| EKS Cluster | Kubernetes | v1.28, 3 nodes, t3.medium |
| EC2 Node Group | Auto Scaling Group | min=2, max=10, t3.medium |
| S3 Bucket | Object Storage | SSE-S3, versioning enabled |
| RDS PostgreSQL | Managed DB | v15, db.t3.medium, Multi-AZ |
| ElastiCache Redis | Managed Cache | Redis 7, cache.t3.micro |
| VPC | Networking | 2 public + 2 private subnets |
| NAT Gateway | Networking | 1 per AZ |
| Route53 | DNS | A record → Load Balancer |
| ACM | TLS Certificates | Wildcard cert for domain |
| Secrets Manager | Secret Storage | All credentials stored here |
| IAM | Access Control | Least-privilege roles |

### Kubernetes Resources per Service

| Resource | Configuration |
|---|---|
| Deployment | 2 replicas minimum; rolling update strategy |
| Service | ClusterIP (internal); LoadBalancer (ingress services) |
| ConfigMap | Non-sensitive environment config |
| Secret | Sensitive values (DB passwords, API keys) |
| HPA | min=2, max=10 replicas, CPU target=70% |
| ResourceQuota | Requests: 100m CPU / 128Mi RAM; Limits: 500m CPU / 512Mi RAM |
| Liveness Probe | HTTP GET `/health`, initial delay 30s, period 10s |
| Readiness Probe | HTTP GET `/health`, initial delay 15s, period 5s |
| PodDisruptionBudget | minAvailable: 1 |

---

## 14. Security Requirements

| ID | Requirement | Implementation |
|---|---|---|
| SEC-1 | No hardcoded credentials anywhere in code | Environment variables + AWS Secrets Manager |
| SEC-2 | All inter-service communication within VPC | Kubernetes ClusterIP services |
| SEC-3 | External traffic via HTTPS only | NGINX Ingress + cert-manager (Let's Encrypt) |
| SEC-4 | Container images run as non-root user | `USER nonroot` in Dockerfile |
| SEC-5 | Container images use minimal base | `python:3.11-slim` |
| SEC-6 | S3 bucket encrypted at rest | SSE-S3 encryption enabled |
| SEC-7 | Database credentials rotated every 90 days | AWS Secrets Manager rotation |
| SEC-8 | IAM policies follow least-privilege principle | Scoped role per service |
| SEC-9 | Kubernetes Secrets for sensitive K8s config | Base64-encoded K8s Secrets, not ConfigMaps |
| SEC-10 | Dependency vulnerability scanning in CI/CD | `bandit` + `safety` in GitHub Actions |
| SEC-11 | Kafka topics accessible only within cluster | No external Kafka exposure |
| SEC-12 | Network policies restrict pod-to-pod traffic | Kubernetes NetworkPolicy applied |

---

## 15. Observability Requirements

### Metrics (Prometheus)

All FastAPI services MUST expose the following Prometheus metrics:

| Metric | Type | Description |
|---|---|---|
| `http_requests_total` | Counter | HTTP request count by method, path, status |
| `http_request_duration_seconds` | Histogram | Request latency distribution |
| `logs_ingested_total` | Counter | Total logs received by ingestion API |
| `kafka_publish_success_total` | Counter | Successful Kafka publishes |
| `kafka_publish_error_total` | Counter | Failed Kafka publishes |
| `anomalies_detected_total` | Counter | Total anomalies detected by ML engine |
| `alerts_sent_total` | Counter | Alerts sent by alert service (by channel) |
| `model_inference_duration_seconds` | Histogram | ML inference latency |
| `active_kafka_consumers` | Gauge | Number of active Kafka consumer connections |

### Grafana Dashboards

| Dashboard | Key Panels |
|---|---|
| Log Ingestion | Logs/sec rate, HTTP latency, error rate, Kafka publish lag |
| Anomaly Detection | Anomaly count/rate, score distribution, top anomalous services |
| Alert History | Alerts by severity, by service, Slack/Email sent counts |
| Service Health | Up/down status, pod count, restart count |
| Infrastructure | CPU/memory per pod, node resource usage |
| Kafka Pipeline | Consumer lag per topic, message throughput, partition distribution |

### Logging

- All services emit **structured JSON logs** via `python-json-logger`
- Log fields: `timestamp`, `level`, `service`, `trace_id`, `message`, `extra`
- Log levels configurable via `LOG_LEVEL` environment variable
- Logs collected by Fluentd and forwarded to Elasticsearch

### Distributed Tracing

- `trace_id` field propagated through all Kafka messages
- Correlated across all services via request context

---

## 16. Constraints & Assumptions

### Constraints

1. The platform must run on Python 3.11+ only
2. All external services (Kafka, Elasticsearch, etc.) are managed via Docker Compose locally and Helm/K8s in production
3. GitHub Actions is the only supported CI/CD system in v1
4. AWS is the only supported cloud provider in v1
5. Model files must be kept under 500MB for container image size limits

### Assumptions

1. Application teams will instrument their services to POST logs to the ingestion API or configure Fluentd agents
2. AWS credentials are available via IAM instance roles in production (no long-lived keys)
3. Log volume is estimated at 1,000–10,000 logs/second at peak
4. Anomaly rate is assumed to be approximately 5% of total log volume
5. A labeled ground-truth dataset is NOT required — Isolation Forest is trained unsupervised
6. Developers have Docker and Docker Compose installed locally

---

## 17. Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-1 | High false-positive anomaly rate confuses operators | Medium | High | Tune contamination parameter; add feedback loop in v2 |
| R-2 | Kafka consumer lag grows unbounded under spike | Medium | High | HPA scaling; increase partition count; dead-letter queue |
| R-3 | Elasticsearch disk fills up | Low | High | Index lifecycle management (ILM); log rotation policy |
| R-4 | ML model drift over time | Medium | Medium | Schedule periodic retraining; monitor prediction distribution |
| R-5 
