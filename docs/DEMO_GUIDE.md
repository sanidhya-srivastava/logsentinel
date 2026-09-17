# 🎓 Review-2 Demo Guide: Implementation & Engineering

Use this guide for your presentation to your sir. It maps your work directly to the Review-2 deliverables.

## 1. Application / Pipeline Implementation
**What to show:** The multi-service architecture working in harmony.
- **Action:** Open the [Kafka UI](http://localhost:8090).
- **Explanation:** "Our architecture uses a decoupled event-driven pipeline. Logs are ingested via FastAPI, published to **Kafka**, and processed asynchronously. This ensures high availability even if the database is temporarily slow."

## 2. Data Ingestion & Processing
**What to show:** Swagger UI and live data flow.
- **Action:** Open [Ingestion API Swagger](http://localhost:8000/docs) and execute a `POST /ingest` call.
- **Explanation:** "We use **Pydantic** for strict schema validation at the door. Once accepted, logs are enriched with metadata and sent through the pipeline for indexing into **Elasticsearch**."

## 3. ML / AI Model Integration
**What to show:** The Anomaly detection in action.
- **Action:** Open [Grafana](http://localhost:3000) and point to the "Anomalies Detected" panel.
- **Explanation:** "We've integrated an **Isolation Forest** (Unsupervised ML) model. It analyzes log patterns (latency, error codes, service frequency) in real-time to detect zero-day attacks or system failures without needing predefined rules."

## 4. CI/CD, Containers & Orchestration
**What to show:** Docker and Kubernetes readiness.
- **Action:** Show the 16 containers running in your terminal (`docker compose ps`) and open the `infra/kubernetes/` folder.
- **Explanation:** "The entire stack is containerized with **Docker**. We have a full **Kubernetes** orchestration setup (manifests/Helm) ready for cloud deployment, and **GitHub Actions** for automated CI/CD."

## 5. Secure Coding Practices
**What to show:** The code/Dockerfiles.
- **Action:** Open `services/log-ingestion-api/Dockerfile`.
- **Explanation:** 
  - "We use **multi-stage builds** to keep production images lean."
  - "Containers run as **non-root users** to prevent privilege escalation."
  - "We follow **12-factor app** principles, handling all secrets via environment variables."

---

### 💡 Pro-Tip for the Demo:
Run this command in a side terminal to show "live logs" scrolling during the demo:
```bash
docker compose logs -f log-ingestion-api log-processor ml-engine
```
