# LogSentinel — Agile Product Backlog

**Project:** LogSentinel — Cloud-Native AI Log Monitoring & Anomaly Detection Platform
**Version:** 1.0.0
**Last Updated:** 2025-01-01
**Methodology:** Scrum — 2-week sprints
**Story Point Scale:** Fibonacci (1, 2, 3, 5, 8, 13)

---

## Backlog Summary

| Sprint | Focus | Stories | Total Points |
|--------|-------|---------|-------------|
| Sprint 1 | Project Setup & Infrastructure Foundation | 12 | 47 |
| Sprint 2 | Log Ingestion API & Kafka Pipeline | 11 | 45 |
| Sprint 3 | Log Processor & Elasticsearch | 10 | 42 |
| Sprint 4 | ML Engine — Training & Inference API | 12 | 51 |
| Sprint 5 | Alert Service & Notification Channels | 10 | 38 |
| Sprint 6 | Dashboard Backend & Grafana | 11 | 40 |
| Sprint 7 | Kubernetes, Helm & CI/CD Pipeline | 13 | 55 |
| Sprint 8 | Testing, Performance & Hardening | 12 | 48 |
| **Total** | | **91** | **366** |

---

## Epic Overview

| Epic ID | Epic Name | Description |
|---------|-----------|-------------|
| EP-1 | Project Foundation | Repo setup, scaffolding, local dev environment |
| EP-2 | Log Ingestion API | FastAPI service to receive and publish logs |
| EP-3 | Kafka Streaming Pipeline | Kafka topics, producers, consumers |
| EP-4 | Log Processing | Clean, structure, and index log data |
| EP-5 | ML Anomaly Detection | Train, serve, and consume Isolation Forest model |
| EP-6 | Alerting | Deduplicate and route anomaly alerts |
| EP-7 | Dashboard & Observability | Backend API, Grafana, Prometheus |
| EP-8 | Infrastructure as Code | Terraform, Kubernetes, Helm |
| EP-9 | CI/CD Pipeline | GitHub Actions build, test, deploy |
| EP-10 | Testing & Quality | Unit, integration, load tests |
| EP-11 | Security Hardening | Secrets management, network policies, IAM |
| EP-12 | Documentation | PRD, README, API docs, runbooks |

---

## Full Backlog

### SPRINT 1 — Project Setup & Infrastructure Foundation

| Story ID | Epic | User Story | Acceptance Criteria | Priority | Points | Status |
|----------|------|-----------|---------------------|----------|--------|--------|
| US-001 | EP-1 | As a developer, I want the full project directory structure scaffolded so I can start building services immediately | All directories from the spec exist; README.md is present; Makefile has `make help` working | P0 | 3 | Done |
| US-002 | EP-1 | As a developer, I want a root `requirements.txt` with all dependencies pinned so everyone has a consistent environment | All packages listed with pinned versions; `pip install -r requirements.txt` succeeds without errors | P0 | 2 | Done |
| US-003 | EP-1 | As a developer, I want an `env.example` file documenting all environment variables so onboarding is self-service | Every env var used across all services is documented with description and example value | P0 | 2 | Done |
| US-004 | EP-1 | As a DevOps engineer, I want a Makefile with `make up`, `make down`, `make build`, `make test` so I can operate the platform with single commands | All documented make targets work; `make help` prints a formatted help table | P0 | 3 | Done |
| US-005 | EP-3 | As a platform engineer, I want Kafka and Zookeeper running locally via Docker Compose so developers can produce and consume messages | `docker compose up` starts Kafka on port 9092; topics `raw-logs`, `processed-logs`, `anomaly-alerts` auto-created; Kafka UI accessible | P0 | 5 | Done |
| US-006 | EP-7 | As an SRE, I want Prometheus and Grafana running locally via Docker Compose so I can view metrics during development | Prometheus scrapes at least one target; Grafana loads at `localhost:3000`; admin login works | P0 | 5 | Done |
| US-007 | EP-4 | As a developer, I want Elasticsearch running locally via Docker Compose so logs can be indexed and searched | Elasticsearch healthy at `localhost:9200`; `_cluster/health` returns `green` or `yellow` | P0 | 3 | Done |
| US-008 | EP-6 | As a developer, I want PostgreSQL and Redis running locally via Docker Compose so the alert service has storage available | PostgreSQL accepts connections; Redis responds to PING; both included in health check target | P0 | 3 | Done |
| US-009 | EP-1 | As a developer, I want a full `docker-compose.yml` wiring all services so the entire platform starts with one command | All 5 microservices, Kafka, Elasticsearch, PostgreSQL, Redis, Prometheus, Grafana start; health checks pass | P0 | 8 | Done |
| US-010 | EP-12 | As a new team member, I want a comprehensive README.md with architecture diagram, quick start, and API reference so I can understand the system in under 30 minutes | README includes: overview, architecture ASCII diagram, quick start steps, API reference, Makefile reference | P1 | 3 | Done |
| US-011 | EP-12 | As a product stakeholder, I want a PRD document covering all functional and non-functional requirements so project scope is clearly defined | PRD covers all 12 sections; all FRs and NFRs documented; data models included | P1 | 5 | Done |
| US-012 | EP-12 | As the engineering team, I want an Agile backlog with all user stories so sprint planning is structured | All 91 user stories written with AC, priority, and story points | P1 | 5 | Done |

---

### SPRINT 2 — Log Ingestion API & Kafka Pipeline

| Story ID | Epic | User Story | Acceptance Criteria | Priority | Points | Status |
|----------|------|-----------|---------------------|----------|--------|--------|
| US-013 | EP-2 | As a client application, I want to POST a log entry to `/ingest` and receive a 202 response so I know the log was accepted | POST with valid JSON returns 202; response includes `log_id` and `status: accepted`; invalid JSON returns 422 | P0 | 5 | Done |
| US-014 | EP-2 | As a client application, I want to POST up to 100 log entries in a single `/ingest/batch` request so I can send logs efficiently | Batch up to 100 entries returns 202; entries exceeding 100 return 422; response includes `accepted` and `rejected` counts | P0 | 5 | Done |
| US-015 | EP-2 | As a developer, I want Pydantic models to validate all log entry fields so malformed logs are rejected before reaching Kafka | Missing required fields return 422 with field-level error details; extra fields are allowed; `level` must be one of defined enum values | P0 | 3 | Done |
| US-016 | EP-3 | As the log ingestion service, I want to publish validated log entries to the Kafka `raw-logs` topic so downstream consumers can process them | Each valid ingest call results in a message on `raw-logs`; Kafka publish failures are caught and return 503; messages are JSON-serialized | P0 | 5 | Done |
| US-017 | EP-2 | As an SRE, I want the ingestion API to expose a `GET /health` endpoint so Kubernetes can probe its liveness and readiness | `/health` returns 200 with JSON `{status: healthy, kafka: connected, timestamp: ...}` within 100ms | P0 | 2 | Done |
| US-018 | EP-2 | As an SRE, I want the ingestion API to expose Prometheus metrics at `/metrics` so I can monitor request rates and latencies | `/metrics` returns valid Prometheus text format; includes `http_requests_total`, `http_request_duration_seconds`, `logs_ingested_total` | P0 | 3 | Done |
| US-019 | EP-2 | As a DevOps engineer, I want a multi-stage Dockerfile for the ingestion API so the production image is small and secure | Dockerfile has builder and runtime stages; final image < 200MB; runs as non-root user; `docker build` succeeds | P0 | 3 | Done |
| US-020 | EP-2 | As a developer, I want structured JSON logging in the ingestion API so logs are machine-parseable | All log output is valid JSON; includes fields: `timestamp`, `level`, `service`, `message`, `trace_id`; configurable via `LOG_LEVEL` env var | P1 | 2 | Done |
| US-021 | EP-2 | As a developer, I want the ingestion API to auto-assign a UUID `log_id` and `ingested_at` timestamp to each log entry so downstream services have a unique identifier | Every published Kafka message contains `log_id` (UUID v4) and `ingested_at` (ISO 8601 UTC) | P1 | 2 | Done |
| US-022 | EP-3 | As a platform engineer, I want Kafka topics to be automatically created on startup so no manual setup is required | `raw-logs`, `processed-logs`, `anomaly-alerts` topics exist with 3 partitions and replication factor 1 after `make up` | P0 | 3 | Done |
| US-023 | EP-2 | As a developer, I want a Kafka connection that reconnects automatically on failure so the ingestion API is resilient | After Kafka restart, ingestion API reconnects within 30 seconds; failed publish returns 503 not 500 | P1 | 5 | Done |
| US-024 | EP-2 | As a security engineer, I want the ingestion API to validate request payload size so oversized payloads are rejected | Payloads > 1MB return 413; individual messages > 10KB return 422 | P2 | 2 | Todo |

---

### SPRINT 3 — Log Processor & Elasticsearch

| Story ID | Epic | User Story | Acceptance Criteria | Priority | Points | Status |
|----------|------|-----------|---------------------|----------|--------|--------|
| US-025 | EP-4 | As a platform engineer, I want a Kafka consumer service that reads from `raw-logs` and processes each message so downstream analytics are possible | Consumer starts, connects to Kafka, and processes messages from `raw-logs`; confirmed via logs showing consumed offsets | P0 | 5 | Done |
| US-026 | EP-4 | As a data analyst, I want log levels normalized to a standard enum so queries are consistent | All level values mapped to `DEBUG`, `INFO`, `WARN`, `ERROR`, `CRITICAL`; unknown values default to `INFO` with a warning logged | P0 | 2 | Done |
| US-027 | EP-4 | As the ML engine, I want structured feature vectors extracted from each log so the model can perform inference | Each processed log includes `features` dict with all 6 fields: `hour_of_day`, `response_time_ms`, `error_code`, `log_level_encoded`, `request_count_last_60s`, `service_id_encoded` | P0 | 5 | Done |
| US-028 | EP-4 | As an SRE, I want processed logs indexed in Elasticsearch so I can search them via Kibana or the dashboard API | Each processed log is indexed in `logsentinel-logs-YYYY.MM.DD`; index mapping includes all fields with correct types | P0 | 5 | Done |
| US-029 | EP-4 | As the ML engine, I want processed log events published to the `processed-logs` Kafka topic so the ML engine can consume them | Every successfully processed message is published to `processed-logs` with feature vectors included | P0 | 3 | Done |
| US-030 | EP-4 | As a platform engineer, I want the log processor to maintain a per-service rolling 60-second request count so the `request_count_last_60s` feature is accurate | Rolling counter uses a sliding window; counts are accurate within ±5%; Redis used for distributed state | P1 | 8 | Done |
| US-031 | EP-4 | As a platform engineer, I want the log processor to handle malformed Kafka messages without crashing so uptime is maintained | Malformed messages are logged as errors and skipped; consumer offset is still committed; service continues running | P0 | 3 | Done |
| US-032 | EP-4 | As a DevOps engineer, I want a multi-stage Dockerfile for the log processor | Dockerfile builds successfully; image < 200MB; non-root user | P0 | 2 | Done |
| US-033 | EP-4 | As a data engineer, I want Elasticsearch index templates created on startup so all log documents have consistent field mappings | Index template applied for `logsentinel-logs-*` with correct field types; `@timestamp` field is a `date` type | P1 | 3 | Done |
| US-034 | EP-4 | As a platform engineer, I want service names encoded to integers on the fly so new services are automatically supported | Service names are encoded using a label encoder; unknown services get a new integer ID; mapping is persisted to Redis | P1 | 5 | Done |

---

### SPRINT 4 — ML Engine — Training & Inference API

| Story ID | Epic | User Story | Acceptance Criteria | Priority | Points | Status |
|----------|------|-----------|---------------------|----------|--------|--------|
| US-035 | EP-5 | As an ML engineer, I want a `ml/train.py` script that generates synthetic training data and trains an Isolation Forest model so a model file is available for the ML engine | Script generates 50,000 synthetic log feature vectors; trains IsolationForest with contamination=0.05; saves `isolation_forest.joblib` and `scaler.joblib` to `ml/models/` | P0 | 8 | Done |
| US-036 | EP-5 | As an ML engineer, I want a `ml/evaluate.py` script that reports precision, recall, F1, and confusion matrix so model quality is quantified | Script loads model and test data; outputs metrics to stdout and `ml/models/evaluation_report.json`; F1 ≥ 0.77 on synthetic test set | P0 | 5 | Done |
| US-037 | EP-5 | As a client service, I want to POST feature vectors to `/predict` and receive an anomaly score and classification so real-time inference is possible | POST with valid feature vector returns `{score: float, is_anomaly: bool, prediction: int}`; response in < 200ms | P0 | 5 | Done |
| US-038 | EP-5 | As a client service, I want to POST a batch of feature vectors to `/predict/batch` so I can run efficient batch inference | POST up to 500 feature vectors; returns list of predictions in same order; response in < 500ms for 100 entries | P1 | 3 | Done |
| US-039 | EP-5 | As an SRE, I want `GET /model/status` to return model metadata so I can verify which model version is loaded | Response includes: `model_type`, `n_estimators`, `contamination`, `trained_at`, `feature_count`, `status` | P0 | 3 | Done |
| US-040 | EP-5 | As a platform engineer, I want the ML engine to consume from `processed-logs` and run inference on each log entry so anomalies are detected automatically | ML engine consumer is active; each processed log is scored; inference latency logged as metric | P0 | 5 | Done |
| US-041 | EP-5 | As an alert system, I want detected anomalies published to `anomaly-alerts` Kafka topic so the alert service can pick them up | Only entries with `prediction == -1` are published; published message includes `anomaly_score`, original log fields, and `detected_at` timestamp | P0 | 5 | Done |
| US-042 | EP-5 | As an SRE, I want the ML engine to expose Prometheus metrics including `anomalies_detected_total` and `model_inference_duration_seconds` | `/metrics` includes at minimum: `anomalies_detected_total`, `model_inference_duration_seconds`, `http_requests_total` | P0 | 3 | Done |
| US-043 | EP-5 | As a DevOps engineer, I want a multi-stage Dockerfile for the ML engine that includes the model file | Model file copied into final image; runs as non-root; image < 500MB | P0 | 3 | Done |
| US-044 | EP-5 | As an ML engineer, I want a Jupyter notebook in `ml/notebooks/` demonstrating the full training and evaluation workflow so experiments are reproducible | Notebook runs end-to-end without errors; includes data generation, feature engineering, training, and evaluation cells with visualizations | P1 | 5 | Done |
| US-045 | EP-5 | As a developer, I want the ML model to be loaded once at startup and reused across requests so inference latency is minimized | Model object is a singleton loaded at application startup; not re-loaded per request; startup logs confirm model loaded | P0 | 3 | Done |
| US-046 | EP-5 | As a platform engineer, I want the ML engine to gracefully handle missing or invalid feature values by using default values so the consumer doesn't crash | Missing features default to 0; invalid types are cast or defaulted; malformed records are logged and skipped | P1 | 3 | Done |

---

### SPRINT 5 — Alert Service & Notification Channels

| Story ID | Epic | User Story | Acceptance Criteria | Priority | Points | Status |
|----------|------|-----------|---------------------|----------|--------|--------|
| US-047 | EP-6 | As a platform engineer, I want an alert service that consumes from `anomaly-alerts` and processes each alert so notifications can be sent | Service starts, connects to Kafka, consumes from `anomaly-alerts`, logs each consumed alert | P0 | 5 | Done |
| US-048 | EP-6 | As an SRE, I want duplicate alerts deduplicated using Redis so I am not spammed with repeated notifications for the same issue | Duplicate alerts (same service + error_code + 1-hour window) are suppressed; Redis key expires after TTL; dedup events are logged | P0 | 5 | Done |
| US-049 | EP-6 | As an SRE, I want to receive Slack notifications for detected anomalies so I am alerted immediately | Slack webhook is called with formatted message; message includes service name, level, anomaly score, timestamp, and message excerpt; HTTP 200 returned from Slack | P0 | 5 | Done |
| US-050 | EP-6 | As an SRE, I want to receive email notifications for detected anomalies so I have a persistent alert record | Email sent via SMTP with HTML formatting; includes all alert details; delivery confirmed via SMTP response code | P0 | 5 | Done |
| US-051 | EP-6 | As a data analyst, I want all alerts (including deduplicated ones) persisted to PostgreSQL so I can query historical anomaly trends | Every alert written to `alerts` table with all fields; deduplicated flag set correctly; `created_at` timestamp auto-assigned | P0 | 5 | Done |
| US-052 | EP-6 | As an SRE, I want failed notifications retried up to 3 times with exponential backoff so transient failures don't result in missed alerts | Failed Slack/email calls retry 3 times; wait times: 1s, 2s, 4s; after 3 failures, error is logged and alert is marked failed in DB | P1 | 3 | Done |
| US-053 | EP-6 | As a DevOps engineer, I want Slack and email notifications independently toggleable via env vars so I can disable a channel without code changes | `SLACK_ENABLED=false` skips Slack; `SMTP_ENABLED=false` skips email; both can be disabled simultaneously | P1 | 2 | Done |
| US-054 | EP-6 | As a developer, I want a multi-stage Dockerfile for the alert service | Builds successfully; non-root user; image < 200MB | P0 | 2 | Done |
| US-055 | EP-6 | As an SRE, I want alert severity categorized as CRITICAL, HIGH, MEDIUM, LOW based on anomaly score and log level so I can prioritize response | Severity mapping: `CRITICAL` when score < -0.3 and level=CRITICAL; `HIGH` when score < -0.2 or level=ERROR; otherwise `MEDIUM`/`LOW` | P2 | 3 | Todo |
| US-056 | EP-6 | As an SRE, I want Prometheus metrics on the alert service tracking `alerts_sent_total` and `alerts_deduplicated_total` | `/metrics` (internal port) includes `alerts_sent_total{channel}`, `alerts_deduplicated_total`, `alert_processing_duration_seconds` | P1 | 3 | Done |

---

### SPRINT 6 — Dashboard Backend & Grafana

| Story ID | Epic | User Story | Acceptance Criteria | Priority | Points | Status |
|----------|------|-----------|---------------------|----------|--------|--------|
| US-057 | EP-7 | As a developer, I want `GET /logs` to return paginated, filterable logs from Elasticsearch so I can query log history | Returns paginated results with `page`, `size`, `total`, `items`; supports filters: `level`, `service`, `start`, `end`; max page size 100 | P0 | 5 | Done |
| US-058 | EP-7 | As an SRE, I want `GET /anomalies` to return a paginated list of detected anomalies from PostgreSQL so I can review anomaly history | Returns anomalies ordered by `detected_at` descending; supports time range and service filters; includes `anomaly_score` field | P0 | 5 | Done |
| US-059 | EP-7 | As a Grafana operator, I want `GET /stats` to return aggregate stats including log rate and anomaly rate so I can build summary panels | Returns: `logs_last_minute`, `logs_last_hour`, `anomalies_last_hour`, `anomaly_rate_percent`, `top_services`; response < 500ms | P0 | 5 | Done |
| US-060 | EP-7 | As a developer, I want stats responses cached in Redis for 10 seconds so Grafana's frequent polling doesn't overload Elasticsearch | Cache TTL is 10 seconds; cache miss triggers fresh query; cache hit logged at DEBUG level | P1 | 3 | Done |
| US-061 | EP-7 | As an SRE, I want Prometheus metrics from the dashboard backend including request rate and latency | `/metrics` includes standard FastAPI Prometheus metrics; no additional custom metrics required for v1 | P0 | 2 | Done |
| US-062 | EP-7 | As a DevOps engineer, I want a multi-stage Dockerfile for the dashboard backend | Builds successfully; non-root user; image < 200MB | P0 | 2 | Done |
| US-063 | EP-7 | As an SRE, I want a Grafana dashboard for log ingestion rate so I can see how many logs are being received per second | Dashboard panel shows `logs_ingested_total` rate over time; configurable time range; deployed via provisioning JSON | P0 | 5 | Done |
| US-064 | EP-7 | As an SRE, I want a Grafana dashboard for anomaly detection count over time so I can spot anomaly clusters | Panel shows `anomalies_detected_total` as time series; separate breakdown by service; deployed via provisioning | P0 | 5 | Done |
| US-065 | EP-7 | As an SRE, I want a Grafana dashboard for service health (up/down) and pod counts so I have operational visibility | Panels show service up/down status from Prometheus; pod count from kube-state-metrics; auto-provisions on container start | P1 | 3 | Done |
| US-066 | EP-7 | As an SRE, I want a Prometheus scrape configuration covering all services so metrics are collected automatically | `prometheus.yml` includes scrape targets for all 3 FastAPI services + kafka-exporter + node-exporter; scrape interval 15s | P0 | 3 | Done |
| US-067 | EP-7 | As an operator, I want Grafana datasources provisioned automatically so no manual datasource setup is needed after `make up` | Prometheus datasource is auto-configured via `provisioning/datasources/datasource.yml`; Grafana starts with datasource ready | P0 | 2 | Done |

---

### SPRINT 7 — Kubernetes, Helm & CI/CD Pipeline

| Story ID | Epic | User Story | Acceptance Criteria | Priority | Points | Status |
|----------|------|-----------|---------------------|----------|--------|--------|
| US-068 | EP-8 | As a DevOps engineer, I want a `logsentinel` Kubernetes namespace so all resources are logically isolated | `kubectl apply -f infra/kubernetes/namespace.yaml` creates the namespace; all other manifests target this namespace | P0 | 1 | Done |
| US-069 | EP-8 | As a DevOps engineer, I want Kubernetes Deployment manifests for all 5 services with resource limits and health probes so pods are reliably scheduled | Each deployment has: `requests` and `limits` for CPU and memory; `livenessProbe` and `readinessProbe`; `replicas: 2` minimum | P0 | 8 | Done |
| US-070 | EP-8 | As a DevOps engineer, I want Kubernetes Service manifests for all 5 services so pods are reachable within the cluster | ClusterIP services for all internal services; LoadBalancer for ingestion API and dashboard backend | P0 | 3 | Done |
| US-071 | EP-8 | As a DevOps engineer, I want ConfigMaps for all services containing non-sensitive environment config so configuration is decoupled from image builds | ConfigMaps contain Kafka bootstrap, Elasticsearch host, Redis host, and other non-secret values; all deployments reference them | P0 | 3 | Done |
| US-072 | EP-8 | As a security engineer, I want Kubernetes Secrets for all sensitive values so passwords and API keys are not in ConfigMaps | Secrets created for: DB password, Redis password, Slack webhook, SMTP credentials; deployments reference them via `secretKeyRef` | P0 | 3 | Done |
| US-073 | EP-8 | As a platform engineer, I want HPA manifests for all 5 services with min=2, max=10 replicas at 70% CPU so services auto-scale | HPA targets each deployment; `minReplicas: 2`, `maxReplicas: 10`; `averageUtilization: 70` for CPU; `kubectl get hpa` shows targets | P0 | 5 | Done |
| US-074 | EP-8 | As a DevOps engineer, I want an NGINX Ingress manifest routing external traffic to ingestion API and dashboard backend so they are accessible from outside the cluster | Ingress routes `api.logsentinel.example.com` → ingestion API; `dashboard.logsentinel.example.com` → dashboard backend; TLS termination configured | P1 | 5 | Done |
| US-075 | EP-8 | As a DevOps engineer, I want PersistentVolumeClaims for Elasticsearch and PostgreSQL so data survives pod restarts | PVCs created with `ReadWriteOnce` access mode; 10Gi for Elasticsearch; 5Gi for PostgreSQL; bound to StorageClass | P0 | 3 | Done |
| US-076 | EP-8 | As a DevOps engineer, I want a Helm chart for the full platform so I can deploy to any Kubernetes cluster with a single command | `helm install logsentinel infra/helm/logsentinel` deploys all resources; `helm lint` passes without errors | P1 | 8 | Done |
| US-077 | EP-9 | As a developer, I want a GitHub Actions workflow that runs lint and tests on every push and pull request so code quality is enforced | Workflow triggers on `push` and `pull_request` to `main`; runs `flake8`, `black --check`, `pytest`; uploads coverage report | P0 | 5 | Done |
| US-078 | EP-9 | As a DevOps engineer, I want GitHub Actions to build and push Docker images tagged with the commit SHA so every commit has a traceable image | Workflow builds all 5 service images; tags with `${{ github.sha }}`; pushes to Docker Hub or ECR; only on `main` branch | P0 | 5 | Done |
| US-079 | EP-9 | As a DevOps engineer, I want GitHub Actions to deploy to the Kubernetes cluster after a successful image push so deployments are automated | Workflow runs `kubectl set image` or `helm upgrade`; verifies rollout with `kubectl rollout status`; posts success/failure to PR | P0 | 5 | Done |
| US-080 | EP-8 | As a DevOps engineer, I want Terraform configuration to provision the full AWS infrastructure so cloud setup is reproducible | `terraform apply` creates EKS cluster, VPC, RDS, ElastiCache, S3, IAM roles; all in < 15 minutes | P1 | 8 | Done |

---

### SPRINT 8 — Testing, Performance & Hardening

| Story ID | Epic | User Story | Acceptance Criteria | Priority | Points | Status |
|----------|------|-----------|---------------------|----------|--------|--------|
| US-081 | EP-10 | As a developer, I want unit tests for the ingestion API covering all endpoints and validation logic so regressions are caught | Tests cover: valid ingest, batch ingest, invalid payload (422), health endpoint, Kafka failure (503); coverage ≥ 80% | P0 | 5 | Done |
| US-082 | EP-10 | As a developer, I want unit tests for the ML engine covering predict endpoint and model loading so model regressions are caught | Tests cover: valid prediction, batch prediction, model status endpoint, invalid feature vector; coverage ≥ 80% | P0 | 5 | Done |
| US-083 | EP-10 | As a developer, I want unit tests for the log processor covering feature extraction and log normalization | Tests cover: level normalization, feature extraction with all edge cases, malformed message handling; coverage ≥ 80% | P0 | 5 | Done |
| US-084 | EP-10 | As a developer, I want unit tests for the alert service covering deduplication logic and notification formatting | Tests cover: dedup with Redis mock, Slack payload formatting, email formatting, PostgreSQL insert; coverage ≥ 80% | P0 | 5 | Done |
| US-085 | EP-10 | As a developer, I want unit tests for the dashboard backend covering all three query endpoints | Tests cover: `/logs` filtering and pagination, `/anomalies` time range filter, `/stats` aggregation; coverage ≥ 80% | P0 | 3 | Done |
| US-086 | EP-10 | As a platform engineer, I want integration tests using Testcontainers that spin up real Kafka, Elasticsearch, and Redis so end-to-end flows are validated | Integration tests cover: ingest → Kafka → processor → Elasticsearch; processor → ML → anomaly-alerts; all use real containers | P1 | 8 | Done |
| US-087 | EP-10 | As a performance engineer, I want a Locust load test that simulates 500 concurrent users sending logs so throughput and latency baselines are established | Locust file targets POST `/ingest`; runs 500 users at 10 spawn/sec for 60 seconds; median latency < 100ms; error rate < 1% | P1 | 5 | Done |
| US-088 | EP-11 | As a security engineer, I want `bandit` security scanning added to the CI pipeline so Python security issues are flagged before merge | `bandit -r services/` runs in CI; HIGH severity findings cause pipeline failure; MEDIUM findings produce warnings | P1 | 2 | Done |
| US-089 | EP-8 | As a DevOps engineer, I want a `docker-compose.prod.yml` with production-grade settings (no volume mounts, resource limits, restart