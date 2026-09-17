FROM jenkins/jenkins:lts

USER root

# Install Docker CLI
RUN rm -rf /var/lib/apt/lists/* && apt-get clean && \
    apt-get update -o Acquire::Retries=5 && apt-get install -y --fix-missing \
    apt-transport-https \
    build-essential \
    ca-certificates \
    curl \
    git \
    gnupg \
    libpq-dev \
    lsb-release \
    make \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv && \
    rm -rf /var/lib/apt/lists/*
    
RUN curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
RUN echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
RUN apt-get update && apt-get install -y docker-ce-cli docker-compose-plugin

# Install kubectl
RUN curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    chmod +x kubectl && \
    mv kubectl /usr/local/bin/

# Install Helm
RUN curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Jenkins bootstrap scripts
COPY infra/jenkins/init.groovy.d/ /usr/share/jenkins/ref/init.groovy.d/

# Jenkins plugins required for pipeline jobs
COPY infra/jenkins/plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt

# Create symlink for python3 as python
RUN ln -sf /usr/bin/python3 /usr/bin/python

# Add jenkins user to docker group
RUN (getent group docker || groupadd -g 999 docker) && usermod -aG docker jenkins

USER jenkins
