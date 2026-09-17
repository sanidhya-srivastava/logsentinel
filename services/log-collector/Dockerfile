# =============================================================================
# LogSentinel — Log Collector Service
# Lightweight Fluentd-based log collector container
# =============================================================================
FROM fluent/fluentd:v1.16-debian-1 AS collector

LABEL maintainer="LogSentinel Team <team@logsentinel.io>" \
      org.opencontainers.image.title="LogSentinel Log Collector" \
      org.opencontainers.image.description="Fluentd log collector for LogSentinel" \
      org.opencontainers.image.version="1.0.0"

# Switch to root to install gems
USER root

# Install Fluentd gem plugins
RUN gem install \
        fluent-plugin-elasticsearch \
        fluent-plugin-kafka \
        fluent-plugin-rewrite-tag-filter \
        fluent-plugin-record-modifier \
        fluent-plugin-concat \
        fluent-plugin-prometheus \
        --no-document

# Create directories for config, buffers, and pos files
RUN mkdir -p /fluentd/etc /fluentd/buffer /fluentd/pos /fluentd/log \
    && chown -R fluent:fluent /fluentd

# Copy Fluentd configuration
COPY fluent.conf /fluentd/etc/fluent.conf

# Health check: verify Fluentd HTTP monitor plugin is responding
HEALTHCHECK \
    --interval=30s \
    --timeout=10s \
    --start-period=15s \
    --retries=3 \
    CMD curl -f http://localhost:24220/api/plugins.json || exit 1

# Switch back to non-root fluent user
USER fluent

# Expose Fluentd ports
EXPOSE 9880  # HTTP input
EXPOSE 5140  # Syslog input (UDP)
EXPOSE 24224 # Fluentd forward protocol
EXPOSE 24220 # Fluentd metrics/monitor

# Use the config file we copied
ENTRYPOINT ["tini", "--", "fluentd"]
CMD ["-c", "/fluentd/etc/fluent.conf", "-p", "/fluentd/plugins"]
