# =============================================================================
# LogSentinel — Architecture Diagram (ASCII) & Security/Scalability Notes
# =============================================================================

# LogSentinel System Architecture

```
                              ┌─────────────────────────────────────────────────────────┐
                              │                     EXTERNAL SOURCES                      │
                              │    Applications │ Microservices │ Kubernetes Pods         │
                              └──────────────────────────┬──────────────────────────────────┘
                                                         │ HTTP / Fluentd forward
                                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                     INGESTION LAYER                                              │
│  ┌─────────────────────────────────┐    ┌──────────────────────────────────┐                     │
│  │    Log Collector (Fluentd)       │───▶│  Log Ingestion API (FastAPI)      │                     │
│  │  - Docker container logs         │    │  - POST /ingest                   │                     │
│  │  - Syslog input (port 5140)      │    │  - POST /ingest/batch             │                     │
│  │  - HTTP push (port 9880)         │    │  - GET  /health, /metrics         │                     │
│  │  - Buffered with retry           │    │  - Prometheus metrics             │                     │
│  └─────────────────────────────────┘    └──────────────┬───────────────────┘                     │
└─────────────────────────────────────────────────────────┼───────────────────────────────────────┘
                                                          │ Kafka: raw-logs topic
                                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 DATA PIPELINE LAYER                                              │
│  ┌─────────────────────────────┐                                                                 │
│  │     Apache Kafka + ZooKeeper │                                                                 │
│  │  Topics:                     │                                                                 │
│  │  ├── raw-logs (3 partitions) │                                                                 │
│  │  ├── processed-logs (3 part.)│                                                                 │
│  │  └── anomaly-alerts (1 part.)│                                                                 │
│  └──────┬──────────────┬────────┘                                                                 │
│         │ consume       │ consume                                                                  │
│         ▼               ▼                                                                          │
│  ┌──────────────┐  ┌──────────────────────────────────────────────────────┐                       │
│  │ Log Processor│  │             ML Engine (FastAPI + Isolation Forest)    │                       │
│  │ (consumer)   │  │  - Consumes processed-logs                            │                       │
│  │ - Parse logs │  │  - Feature: hour_of_day, response_time_ms,            │                       │
│  │ - Extract    │  │    error_code, log_level_encoded,                     │                       │
│  │   features   │  │    request_count_last_60s, service_id_encoded         │                       │
│  │ - Store to ES│  │  - Score each log (contamination=5%)                  │                       │
│  │ - Publish    │  │  - POST /predict, GET /model/status                   │                       │
│  │   processed  │  │  - Publishes to anomaly-alerts topic                  │                       │
│  └──────────────┘  └──────────────────────────┬───────────────────────────┘                       │
└─────────────────────────────────────────────────┼───────────────────────────────────────────────┘
                                                  │ Kafka: anomaly-alerts topic
                                                  ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   ALERTING LAYER                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────┐    │
│  │                          Alert Service (Kafka Consumer)                                  │    │
│  │  ┌─────────────────┐  ┌──────────────────────┐  ┌─────────────────────────────────────┐ │    │
│  │  │  Redis           │  │  Alert Deduplication │  │  Notifications                       │ │    │
│  │  │  (dedup window) │──│  (5-min window)       │  │  - Slack Webhook (Block Kit)         │ │    │
│  │  └─────────────────┘  └──────────────────────┘  │  - Email (SMTP/STARTTLS, HTML)       │ │    │
│  │                                                   └─────────────────────────────────────┘ │    │
│  │  Stores alert history in PostgreSQL (alerts table)                                         │    │
│  └─────────────────────────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                              STORAGE LAYER                                                       │
│  ┌────────────────────────────┐  ┌──────────────────────────┐  ┌───────────────────────────┐   │
│  │ Elasticsearch               │  │ PostgreSQL                │  │ Redis                     │   │
│  │ - Structured log index      │  │ - Alert history table     │  │ - Alert deduplication     │   │
│  │ - logsentinel-logs-*        │  │ - Anomaly metadata        │  │ - Dashboard stats cache   │   │
│  │ - Full-text search          │  │ - User/Config data        │  │ - TTL: 5–10 seconds       │   │
│  │ - Time-series queries       │  │                           │  │                           │   │
│  └────────────────────────────┘  └──────────────────────────┘  └───────────────────────────┘   │
│                                             ▲                                                    │
│  ┌───────────────────────────────────────────┘                                                   │
│  │ AWS S3 (ml/models archive, log backups, terraform state)                                      │
└──┴───────────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                              OBSERVABILITY LAYER                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ Prometheus ──scrapes──▶ All FastAPI /metrics + Kafka exporter + Node exporter + ES/PG/Redis │  │
│  │      ↓ evaluates                                                                             │  │
│  │ Alertmanager ──routes──▶ PagerDuty / Slack / Email                                          │  │
│  │ Grafana (Dashboards): Log rate, Anomaly count, Service health, CPU/memory, Kafka lag        │  │
│  └────────────────────────────────────────────────────────────────────────────────────────────┘  │
│  Dashboard Backend (FastAPI): GET /logs, /anomalies, /stats (cached via Redis)                   │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                              INFRASTRUCTURE LAYER (AWS)                                           │
│  EKS Cluster ─── Namespace: logsentinel ─── NGINX Ingress Controller                             │
│  Each service: Deployment (2+ replicas) + Service + ConfigMap + HPA (2–10 replicas)             │
│  PVCs: Elasticsearch (50Gi gp3), PostgreSQL (20Gi gp3), ML Models (5Gi gp3)                    │
│  Terraform: VPC + Subnets + EKS + ECR + S3 + Secrets Manager + IAM/IRSA                        │
│  Helm Chart: Full stack deployment with dependency management                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Security Design

### Authentication & Authorization
- **AWS IAM + IRSA**: Pods use service account→IAM role binding (no env-var secrets)
- **Kubernetes Secrets**: Sensitive values stored as K8s Secrets, not in ConfigMaps
- **AWS Secrets Manager**: Production secrets fetched at deploy time via External Secrets Operator
- **No hardcoded credentials**: All secrets templated via env vars / K8s Secrets

### Network Security
- **NGINX Ingress TLS termination**: HTTPS enforced on all external endpoints
- **ClusterIP services**: Internal services only accessible within the cluster
- **Rate limiting**: 100 req/s per client on ingestion endpoint via NGINX annotation
- **Container isolation**: All containers run as non-root (UID 1001)
- **ReadOnlyRootFilesystem**: Containers write only to mounted volumes

### Data Security
- **S3 SSE**: All S3 objects encrypted with AES-256
- **PostgreSQL TLS**: Connections use SSL in production
- **Elasticsearch TLS**: X-Pack security enabled in production
- **Kafka SASL**: SASL_SSL supported via env vars (disabled in dev)

### Secrets Management Flow
```
AWS Secrets Manager → External Secrets Operator → K8s Secret → Pod ENV
```

---

## Scalability Design

### Horizontal Scaling
- **All services**: HPA with min=2, max=10 replicas on CPU/memory thresholds
- **Kafka partitions**: 3 partitions for raw-logs and processed-logs → 3 concurrent consumers
- **Elasticsearch**: Multi-node cluster for production (replication factor=2+)
- **Redis**: Redis Sentinel or Cluster for HA in production

### Throughput Targets
| Metric                       | Target        |
|------------------------------|---------------|
| Log ingestion rate           | 10,000 logs/s |
| End-to-end latency (p95)     | < 500ms       |
| Anomaly detection latency    | < 1s          |
| Alert notification latency   | < 5s          |

### Performance Optimizations
- **Kafka batching**: Producers batch messages (linger.ms=5, batch.size=16KB)  
- **Elasticsearch bulk indexing**: Log processor uses bulk API for writes
- **Redis caching**: Dashboard /stats cached 10s to avoid ES thundering herd
- **Connection pooling**: asyncpg pools (5 conns), ES lazy connection reuse
- **Multi-stage Docker builds**: Runtime images ~40% smaller, faster pull/start

---

## Risk Analysis

| Risk                                  | Likelihood | Impact | Mitigation                                          |
|---------------------------------------|------------|--------|-----------------------------------------------------|
| Kafka partition lag (backpressure)    | Medium     | High   | HPA on consumers, Kafka lag alert rule              |
| Elasticsearch disk full               | Medium     | High   | ILM policy, disk space alert, 50Gi PVC              |
| ML model drift (false positive rate)  | High       | Medium | Re-training pipeline, model versioning in S3        |
| Alert notification failure (SMTP/Slack)| Low       | Medium | Retry with exponential backoff, Redis dedup window  |
| Single Kafka broker failure           | Low        | High   | Multi-broker in production, ISR=2                   |
| PostgreSQL data loss                  | Low        | High   | PVC with gp3 + daily PITR backups                  |
| Redis cache eviction                  | Medium     | Low    | Fallback to direct DB/ES query on cache miss        |
| Container OOM kill                    | Medium     | Medium | Memory limits + Java heap settings for ES/Kafka     |
| ECR pull rate limit                   | Low        | Medium | imagePullPolicy: IfNotPresent in steady state        |
| Secrets leakage via Git               | Low        | Critical | gitignore .env, pre-commit hooks, secrets scanning |
