# =============================================================================
# LogSentinel — Makefile
# =============================================================================

.PHONY: help up down build test lint train evaluate health logs deploy \
        k8s-apply helm-install clean test-unit test-integration test-load \
        push format check-env terraform-init terraform-plan terraform-apply

# Default target
.DEFAULT_GOAL := help

# -----------------------------------------------------------------------------
# Variables
# -----------------------------------------------------------------------------
COMPOSE_FILE        := docker-compose.yml
COMPOSE_PROD_FILE   := docker-compose.prod.yml
DOCKER_REGISTRY     ?= your-dockerhub-username
IMAGE_TAG           ?= latest
NAMESPACE           := logsentinel
HELM_RELEASE        := logsentinel
HELM_CHART_PATH     := infra/helm/logsentinel
K8S_MANIFESTS_DIR   := infra/kubernetes
TERRAFORM_DIR       := infra/terraform
PYTHON              ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PIP                 ?= $(if $(wildcard .venv/bin/pip),.venv/bin/pip,pip3)
SERVICES            := log-ingestion-api log-processor ml-engine alert-service dashboard-backend

# Colors for output
RED     := \033[0;31m
GREEN   := \033[0;32m
YELLOW  := \033[1;33m
BLUE    := \033[0;34m
CYAN    := \033[0;36m
RESET   := \033[0m

# -----------------------------------------------------------------------------
# Help
# -----------------------------------------------------------------------------
help: ## Show this help message
	@echo ""
	@echo "$(CYAN)╔══════════════════════════════════════════════════════════╗$(RESET)"
	@echo "$(CYAN)║        LogSentinel — AI Log Monitoring Platform          ║$(RESET)"
	@echo "$(CYAN)╚══════════════════════════════════════════════════════════╝$(RESET)"
	@echo ""
	@echo "$(YELLOW)Usage:$(RESET) make $(BLUE)<target>$(RESET)"
	@echo ""
	@echo "$(YELLOW)Local Development:$(RESET)"
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*?##/ { printf "  $(BLUE)%-22s$(RESET) %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@echo ""

# -----------------------------------------------------------------------------
# Local Development (Docker Compose)
# -----------------------------------------------------------------------------
up: check-env ## Start all services locally via Docker Compose
	@echo "$(GREEN)▶ Starting LogSentinel services...$(RESET)"
	docker compose -f $(COMPOSE_FILE) up -d
	@echo "$(GREEN)✔ All services started. Run 'make health' to verify.$(RESET)"

up-build: check-env ## Build images and start all services
	@echo "$(GREEN)▶ Building and starting LogSentinel services...$(RESET)"
	docker compose -f $(COMPOSE_FILE) up -d --build

down: ## Stop all services
	@echo "$(YELLOW)▶ Stopping LogSentinel services...$(RESET)"
	docker compose -f $(COMPOSE_FILE) down
	@echo "$(YELLOW)✔ All services stopped.$(RESET)"

down-volumes: ## Stop all services and remove volumes (DATA LOSS)
	@echo "$(RED)▶ Stopping services and removing volumes...$(RESET)"
	docker compose -f $(COMPOSE_FILE) down -v
	@echo "$(RED)✔ All services and volumes removed.$(RESET)"

logs: ## Tail logs from all services
	docker compose -f $(COMPOSE_FILE) logs -f

logs-ingestion: ## Tail logs from log-ingestion-api only
	docker compose -f $(COMPOSE_FILE) logs -f log-ingestion-api

logs-processor: ## Tail logs from log-processor only
	docker compose -f $(COMPOSE_FILE) logs -f log-processor

logs-ml: ## Tail logs from ml-engine only
	docker compose -f $(COMPOSE_FILE) logs -f ml-engine

logs-alert: ## Tail logs from alert-service only
	docker compose -f $(COMPOSE_FILE) logs -f alert-service

logs-dashboard: ## Tail logs from dashboard-backend only
	docker compose -f $(COMPOSE_FILE) logs -f dashboard-backend

restart: ## Restart all services
	@echo "$(YELLOW)▶ Restarting services...$(RESET)"
	docker compose -f $(COMPOSE_FILE) restart

ps: ## Show running containers
	docker compose -f $(COMPOSE_FILE) ps

# -----------------------------------------------------------------------------
# Health Checks
# -----------------------------------------------------------------------------
health: ## Check health of all service endpoints
	@echo "$(CYAN)▶ Checking service health...$(RESET)"
	@echo ""
	@curl -sf http://localhost:8000/health > /dev/null 2>&1 \
		&& echo "$(GREEN)  ✔ log-ingestion-api  → http://localhost:8000/health$(RESET)" \
		|| echo "$(RED)  ✘ log-ingestion-api  → UNREACHABLE$(RESET)"
	@curl -sf http://localhost:8001/health > /dev/null 2>&1 \
		&& echo "$(GREEN)  ✔ ml-engine          → http://localhost:8001/health$(RESET)" \
		|| echo "$(RED)  ✘ ml-engine          → UNREACHABLE$(RESET)"
	@curl -sf http://localhost:8002/health > /dev/null 2>&1 \
		&& echo "$(GREEN)  ✔ dashboard-backend  → http://localhost:8002/health$(RESET)" \
		|| echo "$(RED)  ✘ dashboard-backend  → UNREACHABLE$(RESET)"
	@curl -sf http://localhost:9090/-/healthy > /dev/null 2>&1 \
		&& echo "$(GREEN)  ✔ prometheus         → http://localhost:9090$(RESET)" \
		|| echo "$(RED)  ✘ prometheus         → UNREACHABLE$(RESET)"
	@curl -sf http://localhost:3000/api/health > /dev/null 2>&1 \
		&& echo "$(GREEN)  ✔ grafana            → http://localhost:3000$(RESET)" \
		|| echo "$(RED)  ✘ grafana            → UNREACHABLE$(RESET)"
	@curl -sf http://localhost:9200/_cluster/health > /dev/null 2>&1 \
		&& echo "$(GREEN)  ✔ elasticsearch      → http://localhost:9200$(RESET)" \
		|| echo "$(RED)  ✘ elasticsearch      → UNREACHABLE$(RESET)"
	@echo ""

# -----------------------------------------------------------------------------
# Docker Build & Push
# -----------------------------------------------------------------------------
build: ## Build all Docker images
	@echo "$(BLUE)▶ Building all Docker images...$(RESET)"
	@for service in $(SERVICES); do \
		echo "$(BLUE)  Building $$service...$(RESET)"; \
		docker build -t $(DOCKER_REGISTRY)/logsentinel-$$service:$(IMAGE_TAG) \
			services/$$service/ || exit 1; \
	done
	@echo "$(GREEN)✔ All images built successfully.$(RESET)"

build-service: ## Build a single service: make build-service SERVICE=ml-engine
	@echo "$(BLUE)▶ Building $(SERVICE)...$(RESET)"
	docker build -t $(DOCKER_REGISTRY)/logsentinel-$(SERVICE):$(IMAGE_TAG) \
		services/$(SERVICE)/
	@echo "$(GREEN)✔ $(SERVICE) built successfully.$(RESET)"

push: ## Push all Docker images to registry
	@echo "$(BLUE)▶ Pushing Docker images to $(DOCKER_REGISTRY)...$(RESET)"
	@for service in $(SERVICES); do \
		echo "$(BLUE)  Pushing $$service...$(RESET)"; \
		docker push $(DOCKER_REGISTRY)/logsentinel-$$service:$(IMAGE_TAG) || exit 1; \
	done
	@echo "$(GREEN)✔ All images pushed.$(RESET)"

push-service: ## Push a single service image: make push-service SERVICE=ml-engine
	docker push $(DOCKER_REGISTRY)/logsentinel-$(SERVICE):$(IMAGE_TAG)

# -----------------------------------------------------------------------------
# Code Quality
# -----------------------------------------------------------------------------
lint: ## Run flake8 + black linting checks
	@echo "$(CYAN)▶ Running linters...$(RESET)"
	@$(PIP) install flake8 black isort --quiet
	@echo "$(CYAN)  Running black (format check)...$(RESET)"
	$(PYTHON) -m black --check --diff services/ ml/ tests/
	@echo "$(CYAN)  Running flake8...$(RESET)"
	$(PYTHON) -m flake8 services/ ml/ tests/ \
		--max-line-length=100 \
		--exclude=__pycache__,.venv,.venv-ci,node_modules,migrations \
		--ignore=E203,W503
	@echo "$(CYAN)  Running isort (import sort check)...$(RESET)"
	$(PYTHON) -m isort --profile black --check-only --diff services/ ml/ tests/
	@echo "$(GREEN)✔ All lint checks passed.$(RESET)"

format: ## Auto-format code with black + isort
	@echo "$(CYAN)▶ Formatting code...$(RESET)"
	$(PYTHON) -m black services/ ml/ tests/
	$(PYTHON) -m isort --profile black services/ ml/ tests/
	@echo "$(GREEN)✔ Code formatted.$(RESET)"

# -----------------------------------------------------------------------------
# Testing
# -----------------------------------------------------------------------------
install-test-deps: ## Install test dependencies
	$(PYTHON) -m pip install pytest pytest-cov pytest-asyncio httpx testcontainers locust --quiet

test: install-test-deps ## Run all tests with coverage report
	@echo "$(CYAN)▶ Running all tests...$(RESET)"
	$(PYTHON) -m pytest tests/ \
		--cov=services \
		--cov-report=term-missing \
		--cov-report=xml:coverage.xml \
		--cov-report=html:htmlcov \
		-v \
		--tb=short
	@echo "$(GREEN)✔ Tests completed.$(RESET)"

test-unit: install-test-deps ## Run unit tests only
	@echo "$(CYAN)▶ Running unit tests...$(RESET)"
	$(PYTHON) -m pytest tests/unit/ -v --tb=short
	@echo "$(GREEN)✔ Unit tests completed.$(RESET)"

test-integration: install-test-deps ## Run integration tests (requires Docker)
	@echo "$(CYAN)▶ Running integration tests...$(RESET)"
	$(PYTHON) -m pytest tests/integration/ -v --tb=short -m integration
	@echo "$(GREEN)✔ Integration tests completed.$(RESET)"

test-load: ## Run Locust load tests against local services
	@echo "$(CYAN)▶ Starting Locust load test...$(RESET)"
	@echo "$(YELLOW)  Open http://localhost:8089 in your browser to configure the test.$(RESET)"
	locust -f tests/load/locustfile.py --host=http://localhost:8000

test-load-headless: ## Run load test headlessly (1 min, 50 users, 5 spawn rate)
	locust -f tests/load/locustfile.py \
		--host=http://localhost:8000 \
		--headless \
		--users=50 \
		--spawn-rate=5 \
		--run-time=60s \
		--html=tests/load/report.html

# -----------------------------------------------------------------------------
# Machine Learning
# -----------------------------------------------------------------------------
install-ml-deps: ## Install ML dependencies
	$(PIP) install scikit-learn pandas numpy joblib jupyter --quiet

train: install-ml-deps ## Train the Isolation Forest anomaly detection model
	@echo "$(CYAN)▶ Training Isolation Forest model...$(RESET)"
	$(PYTHON) ml/train.py
	@echo "$(GREEN)✔ Model trained and saved to ml/models/$(RESET)"

evaluate: install-ml-deps ## Evaluate the trained model
	@echo "$(CYAN)▶ Evaluating model...$(RESET)"
	$(PYTHON) ml/evaluate.py
	@echo "$(GREEN)✔ Evaluation complete. Check ml/models/evaluation_report.json$(RESET)"

notebook: ## Start Jupyter notebook server for ML experiments
	@echo "$(CYAN)▶ Starting Jupyter notebook...$(RESET)"
	jupyter notebook ml/notebooks/

# -----------------------------------------------------------------------------
# Kubernetes
# -----------------------------------------------------------------------------
k8s-namespace: ## Create the logsentinel namespace
	kubectl apply -f $(K8S_MANIFESTS_DIR)/namespace.yaml

k8s-apply: k8s-namespace ## Apply all Kubernetes manifests
	@echo "$(BLUE)▶ Applying Kubernetes manifests...$(RESET)"
	kubectl apply -f $(K8S_MANIFESTS_DIR)/secrets/
	kubectl apply -f $(K8S_MANIFESTS_DIR)/configmaps/
	kubectl apply -f $(K8S_MANIFESTS_DIR)/deployments/
	kubectl apply -f $(K8S_MANIFESTS_DIR)/services/
	kubectl apply -f $(K8S_MANIFESTS_DIR)/hpa/
	kubectl apply -f $(K8S_MANIFESTS_DIR)/ingress.yaml
	@echo "$(GREEN)✔ All manifests applied.$(RESET)"

k8s-delete: ## Delete all Kubernetes resources
	@echo "$(RED)▶ Deleting Kubernetes resources...$(RESET)"
	kubectl delete namespace $(NAMESPACE) --ignore-not-found
	@echo "$(RED)✔ Namespace and all resources deleted.$(RESET)"

k8s-status: ## Show status of all pods in logsentinel namespace
	@echo "$(CYAN)▶ Pod status in namespace $(NAMESPACE):$(RESET)"
	kubectl get pods -n $(NAMESPACE) -o wide
	@echo ""
	kubectl get services -n $(NAMESPACE)
	@echo ""
	kubectl get hpa -n $(NAMESPACE)

k8s-rollout: ## Watch rolling update status for all deployments
	@for service in $(SERVICES); do \
		echo "$(CYAN)  Checking $$service rollout...$(RESET)"; \
		kubectl rollout status deployment/$$service -n $(NAMESPACE) || true; \
	done

k8s-logs: ## Stream logs from all pods in namespace
	kubectl logs -l app.kubernetes.io/part-of=logsentinel \
		-n $(NAMESPACE) --all-containers=true -f

# -----------------------------------------------------------------------------
# Helm
# -----------------------------------------------------------------------------
helm-deps: ## Update Helm chart dependencies
	helm dependency update $(HELM_CHART_PATH)

helm-lint: ## Lint the Helm chart
	@echo "$(CYAN)▶ Linting Helm chart...$(RESET)"
	helm lint $(HELM_CHART_PATH)

helm-dry-run: ## Dry-run Helm install to validate templates
	helm install $(HELM_RELEASE) $(HELM_CHART_PATH) \
		--namespace $(NAMESPACE) \
		--create-namespace \
		--dry-run \
		--debug

helm-install: helm-deps ## Install LogSentinel via Helm
	@echo "$(BLUE)▶ Installing LogSentinel via Helm...$(RESET)"
	helm upgrade --install $(HELM_RELEASE) $(HELM_CHART_PATH) \
		--namespace $(NAMESPACE) \
		--create-namespace \
		--values $(HELM_CHART_PATH)/values.yaml \
		--wait \
		--timeout 10m
	@echo "$(GREEN)✔ Helm install complete.$(RESET)"

helm-uninstall: ## Uninstall LogSentinel Helm release
	helm uninstall $(HELM_RELEASE) -n $(NAMESPACE) --ignore-not-found

helm-upgrade: ## Upgrade existing Helm release
	helm upgrade $(HELM_RELEASE) $(HELM_CHART_PATH) \
		--namespace $(NAMESPACE) \
		--values $(HELM_CHART_PATH)/values.yaml \
		--wait

# -----------------------------------------------------------------------------
# Terraform (AWS Infrastructure)
# -----------------------------------------------------------------------------
terraform-init: ## Initialize Terraform
	@echo "$(BLUE)▶ Initializing Terraform...$(RESET)"
	cd $(TERRAFORM_DIR) && terraform init

terraform-plan: ## Plan Terraform changes
	@echo "$(BLUE)▶ Planning Terraform changes...$(RESET)"
	cd $(TERRAFORM_DIR) && terraform plan -var-file=terraform.tfvars -out=tfplan

terraform-apply: ## Apply Terraform changes
	@echo "$(BLUE)▶ Applying Terraform changes...$(RESET)"
	cd $(TERRAFORM_DIR) && terraform apply tfplan

terraform-destroy: ## Destroy all Terraform-managed infrastructure (DANGER)
	@echo "$(RED)▶ Destroying infrastructure — ARE YOU SURE? This is irreversible!$(RESET)"
	cd $(TERRAFORM_DIR) && terraform destroy -var-file=terraform.tfvars

terraform-output: ## Show Terraform outputs
	cd $(TERRAFORM_DIR) && terraform output

# -----------------------------------------------------------------------------
# Full Deployment
# -----------------------------------------------------------------------------
deploy: build push k8s-apply k8s-rollout ## Full deploy: build → push → k8s apply
	@echo "$(GREEN)✔ Deployment complete!$(RESET)"
	@make k8s-status

deploy-prod: ## Deploy to production using prod compose
	@echo "$(BLUE)▶ Deploying to production...$(RESET)"
	docker compose -f $(COMPOSE_PROD_FILE) up -d --build
	@echo "$(GREEN)✔ Production deployment complete.$(RESET)"

# -----------------------------------------------------------------------------
# Send test log
# -----------------------------------------------------------------------------
send-test-log: ## Send a test log entry to the ingestion API
	@echo "$(CYAN)▶ Sending test log entry...$(RESET)"
	curl -s -X POST http://localhost:8000/ingest \
		-H "Content-Type: application/json" \
		-d '{"service":"test-service","level":"ERROR","message":"Database connection timeout after 5000ms","response_time_ms":5000.0,"error_code":503,"host":"test-host-001","request_count_last_60s":42}' \
		| python3 -m json.tool
	@echo ""

send-bulk-logs: ## Send 100 test log entries for load testing
	@echo "$(CYAN)▶ Sending 100 bulk log entries...$(RESET)"
	@for i in $$(seq 1 100); do \
		curl -s -X POST http://localhost:8000/ingest \
			-H "Content-Type: application/json" \
			-d "{\"service\":\"bulk-test\",\"level\":\"INFO\",\"message\":\"Bulk log entry $$i\",\"response_time_ms\":$$((RANDOM % 500)),\"error_code\":200}" \
			> /dev/null; \
	done
	@echo "$(GREEN)✔ 100 log entries sent.$(RESET)"

# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------
check-env: ## Check that required environment variables and tools are present
	@echo "$(CYAN)▶ Checking environment...$(RESET)"
	@command -v docker > /dev/null 2>&1 \
		&& echo "$(GREEN)  ✔ docker$(RESET)" \
		|| (echo "$(RED)  ✘ docker not found$(RESET)"; exit 1)
	@command -v docker compose > /dev/null 2>&1 \
		&& echo "$(GREEN)  ✔ docker compose$(RESET)" \
		|| (echo "$(RED)  ✘ docker compose not found$(RESET)"; exit 1)
	@command -v python3 > /dev/null 2>&1 \
		&& echo "$(GREEN)  ✔ python3$(RESET)" \
		|| echo "$(YELLOW)  ⚠ python3 not found$(RESET)"
	@test -f .env \
		&& echo "$(GREEN)  ✔ .env file present$(RESET)" \
		|| (echo "$(YELLOW)  ⚠ .env not found — copying from .env.example$(RESET)"; \
		    test -f .env.example && cp .env.example .env || echo "$(RED)  ✘ .env.example not found$(RESET)")

install-deps: ## Install all Python dependencies
	$(PIP) install -r requirements.txt

install-dev-deps: ## Install development + test dependencies
	$(PIP) install -r requirements.txt
	$(PIP) install flake8 black isort pytest pytest-cov pytest-asyncio httpx \
		testcontainers locust jupyter --quiet

setup: install-dev-deps check-env ## Full local dev setup
	@echo "$(GREEN)✔ Dev environment ready. Run 'make up' to start services.$(RESET)"

clean: down ## Remove containers, networks, and dangling images
	@echo "$(RED)▶ Cleaning up Docker resources...$(RESET)"
	docker compose -f $(COMPOSE_FILE) rm -f
	docker image prune -f
	docker network prune -f
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name "coverage.xml" -delete 2>/dev/null || true
	@echo "$(RED)✔ Cleanup complete.$(RESET)"

clean-all: down-volumes clean ## Remove EVERYTHING including volumes (DATA LOSS)
	docker system prune -af --volumes
	@echo "$(RED)✔ Full cleanup complete. All data removed.$(RESET)"

version: ## Show versions of key tools
	@echo "$(CYAN)Tool Versions:$(RESET)"
	@docker --version 2>/dev/null || echo "docker: not found"
	@docker compose version 2>/dev/null || echo "docker compose: not found"
	@kubectl version --client --short 2>/dev/null || echo "kubectl: not found"
	@helm version --short 2>/dev/null || echo "helm: not found"
	@terraform --version 2>/dev/null | head -1 || echo "terraform: not found"
	@python3 --version 2>/dev/null || echo "python3: not found"
