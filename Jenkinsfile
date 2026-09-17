pipeline {
    agent any

    options {
        timestamps()
        ansiColor('xterm')
        disableConcurrentBuilds()
        timeout(time: 30, unit: 'MINUTES')
    }

    environment {
        PYTHON_CI_IMAGE = "python:3.11-slim"
        HOST_REPO_PATH  = "/home/arnab/CODE/logsentinel"
        SERVICES        = "log-ingestion-api log-processor ml-engine alert-service dashboard-backend"
        DOCKER_HUB_CREDS = "docker-hub-creds"
    }

    stages {

        // ── 1. Checkout ──────────────────────────────────────────────
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        // ── 2. Lint & Unit Tests ─────────────────────────────────────
        stage('Lint & Test') {
            steps {
                sh """
                    set -eux
                    docker run --rm \\
                      -v "${HOST_REPO_PATH}":/workspace \\
                      -w /workspace \\
                      "${PYTHON_CI_IMAGE}" \\
                      bash -lc '
                        set -eux
                        rm -rf .venv-ci
                        python -m venv .venv-ci
                        . .venv-ci/bin/activate
                        python -m pip install --upgrade pip setuptools wheel
                        python -m pip install -r requirements.txt
                        python -m pip install flake8 black isort pytest pytest-cov pytest-asyncio httpx
                        black --check --diff services/ ml/ || true
                        flake8 services/ ml/ --max-line-length=100 \\
                          --exclude=__pycache__,.venv,.venv-ci,migrations \\
                          --ignore=E203,W503 || true
                        mkdir -p test-results
                        python -m pytest tests/unit/ -v --tb=short \\
                          --junitxml=test-results/unit-results.xml || true
                      '
                """
            }
            post {
                always {
                    junit testResults: 'test-results/unit-results.xml', allowEmptyResults: true
                    archiveArtifacts artifacts: 'test-results/**', allowEmptyArchive: true
                }
            }
        }

        // ── 3. Build Frontend ─────────────────────────────────────────
        stage('Build Frontend') {
            steps {
                sh """
                    set -eux
                    docker run --rm \\
                      -v "${HOST_REPO_PATH}/services/dashboard-frontend":/app \\
                      -w /app \\
                      node:20-alpine \\
                      sh -c 'npm ci && npm run build'
                """
            }
            post {
                success {
                    archiveArtifacts artifacts: 'services/dashboard-frontend/dist/**', allowEmptyArchive: true
                }
            }
        }

        // ── 4. Train ML Model (only when ml/** changes) ───────────────
        stage('Train ML Model') {
            when {
                anyOf {
                    changeset "ml/**"
                    changeset "services/ml-engine/**"
                    expression { return params.FORCE_TRAIN == true }
                }
            }
            steps {
                catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE') {
                    sh """
                        set -eux
                        docker run --rm \\
                          -v "${HOST_REPO_PATH}":/workspace \\
                          -w /workspace \\
                          "${PYTHON_CI_IMAGE}" \\
                          bash -lc '
                            set -eux
                            python -m venv .venv-ci
                            . .venv-ci/bin/activate
                            python -m pip install --upgrade pip setuptools wheel
                            python -m pip install -r requirements.txt
                            python ml/train.py
                          '
                    """
                }
            }
            post {
                success {
                    archiveArtifacts artifacts: 'ml/models/**', allowEmptyArchive: true
                }
            }
        }

        // ── 5. Docker Build & Push (main branch only) ─────────────────
        stage('Build & Push Docker Images') {
            when { branch 'main' }
            steps {
                catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE') {
                    script {
                        withCredentials([usernamePassword(
                            credentialsId: env.DOCKER_HUB_CREDS,
                            usernameVariable: 'DOCKER_USER',
                            passwordVariable: 'DOCKER_PASS'
                        )]) {
                            def services = env.SERVICES.split(' ')
                            def parallelStages = [:]
                            services.each { svc ->
                                def s = svc
                                parallelStages[s] = {
                                    sh """
                                        echo "${DOCKER_PASS}" | docker login -u "${DOCKER_USER}" --password-stdin
                                        docker build -t ${DOCKER_USER}/logsentinel-${s}:${BUILD_NUMBER} services/${s}/
                                        docker push ${DOCKER_USER}/logsentinel-${s}:${BUILD_NUMBER}
                                    """
                                }
                            }
                            parallel parallelStages
                        }
                    }
                }
            }
        }

        // ── 6. Health Check ───────────────────────────────────────────
        stage('Health Check') {
            when { branch 'main' }
            steps {
                catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE') {
                    sh """
                        set -eux
                        echo "Checking Log Ingestion API..."
                        curl -sf http://localhost:8000/health || echo "log-ingestion-api not reachable"
                        echo "Checking ML Engine..."
                        curl -sf http://localhost:8001/health || echo "ml-engine not reachable"
                        echo "Checking Dashboard Backend..."
                        curl -sf http://localhost:8002/health || echo "dashboard-backend not reachable"
                    """
                }
            }
        }
    }

    post {
        success {
            echo 'Pipeline completed successfully!'
        }
        failure {
            echo 'Pipeline failed. Check the logs above.'
        }
        always {
            cleanWs(cleanWhenAborted: true, cleanWhenFailure: false, cleanWhenSuccess: true)
        }
    }
}
