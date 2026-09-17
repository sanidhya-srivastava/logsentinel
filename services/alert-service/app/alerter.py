"""
LogSentinel — Alert Service: Alert Router + Notifiers
======================================================
Contains:
  - BaseNotifier       : abstract base class for all notification channels
  - AlertRouter        : routes an alert through all enabled notifiers
  - SlackNotifier      : sends formatted Slack webhook messages
  - EmailNotifier      : sends HTML email via SMTP
  - (imported by main.py)

Usage:
    router = AlertRouter(notifiers=[SlackNotifier(...), EmailNotifier(...)])
    channels_sent = await router.send(alert_dict)
"""

import asyncio
import logging
import smtplib
import ssl
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import aiohttp
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Severity helper
# ---------------------------------------------------------------------------


def _severity_from_alert(alert: dict[str, Any]) -> str:
    """
    Derive a human-readable severity label from anomaly_score + log level.

    CRITICAL : score < -0.3  AND  level in (CRITICAL, ERROR)
    HIGH      : score < -0.2  OR   level == ERROR
    MEDIUM    : score < -0.1
    LOW       : everything else
    """
    score = float(alert.get("anomaly_score", 0.0))
    level = (alert.get("level") or "UNKNOWN").upper()

    if score < -0.3 and level in ("CRITICAL", "ERROR"):
        return "CRITICAL"
    if score < -0.2 or level == "ERROR":
        return "HIGH"
    if score < -0.1:
        return "MEDIUM"
    return "LOW"


_SEVERITY_EMOJI: dict[str, str] = {
    "CRITICAL": ":rotating_light:",
    "HIGH": ":red_circle:",
    "MEDIUM": ":large_yellow_circle:",
    "LOW": ":large_blue_circle:",
}

_SEVERITY_COLOR: dict[str, str] = {
    "CRITICAL": "#FF0000",
    "HIGH": "#FF6600",
    "MEDIUM": "#FFCC00",
    "LOW": "#36A64F",
}


# ---------------------------------------------------------------------------
# Base Notifier
# ---------------------------------------------------------------------------


class BaseNotifier(ABC):
    """Abstract base class for notification channel implementations."""

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """Short identifier for this channel (e.g. 'slack', 'email')."""

    @property
    @abstractmethod
    def is_enabled(self) -> bool:
        """True if this notifier is configured and enabled."""

    @abstractmethod
    async def send(self, alert: dict[str, Any]) -> bool:
        """
        Send a notification for the given alert.

        Args:
            alert: The anomaly alert dict from Kafka.

        Returns:
            True if notification was sent successfully, False otherwise.
        """


# ---------------------------------------------------------------------------
# Alert Router
# ---------------------------------------------------------------------------


class AlertRouter:
    """
    Routes an alert through all registered notification channels.

    Calls each notifier's send() method concurrently using asyncio.gather.
    Failed notifiers are logged but do not block other notifiers.

    Args:
        notifiers: List of BaseNotifier implementations to route alerts through.
    """

    def __init__(self, notifiers: list[BaseNotifier]) -> None:
        self._notifiers = [n for n in notifiers if n is not None]
        enabled = [n.channel_name for n in self._notifiers if n.is_enabled]
        logger.info(
            "AlertRouter initialised",
            extra={
                "total_notifiers": len(self._notifiers),
                "enabled_channels": enabled,
            },
        )

    async def send(self, alert: dict[str, Any]) -> list[str]:
        """
        Send the alert through all enabled notifiers concurrently.

        Args:
            alert: The anomaly alert dict.

        Returns:
            List of channel names that successfully sent the notification.
        """
        enabled_notifiers = [n for n in self._notifiers if n.is_enabled]

        if not enabled_notifiers:
            logger.warning(
                "No notification channels enabled — alert not sent",
                extra={"alert_id": alert.get("alert_id")},
            )
            return []

        # Send to all channels concurrently
        results = await asyncio.gather(
            *[self._try_send(n, alert) for n in enabled_notifiers],
            return_exceptions=True,
        )

        successful_channels: list[str] = []
        for notifier, result in zip(enabled_notifiers, results):
            if isinstance(result, Exception):
                logger.error(
                    "Notifier raised unexpected exception",
                    extra={
                        "channel": notifier.channel_name,
                        "alert_id": alert.get("alert_id"),
                        "error": str(result),
                    },
                )
            elif result is True:
                successful_channels.append(notifier.channel_name)

        return successful_channels

    async def _try_send(self, notifier: BaseNotifier, alert: dict[str, Any]) -> bool:
        """Wrapper that catches all exceptions from a single notifier."""
        try:
            return await notifier.send(alert)
        except Exception as exc:
            logger.error(
                "Notifier send() raised exception",
                extra={
                    "channel": notifier.channel_name,
                    "alert_id": alert.get("alert_id"),
                    "error": str(exc),
                },
                exc_info=True,
            )
            return False


# ---------------------------------------------------------------------------
# Slack Notifier
# ---------------------------------------------------------------------------


class SlackNotifier(BaseNotifier):
    """
    Sends formatted Slack webhook messages for anomaly alerts.

    Uses the Slack Block Kit API to produce rich, readable notifications
    with color-coded severity, service info, and anomaly score.

    Retries failed webhook calls with exponential backoff (up to max_retries).

    Args:
        webhook_url:           Slack incoming webhook URL.
        channel:               Slack channel name (e.g. "#alerts").
        username:              Bot display name.
        icon_emoji:            Bot icon emoji (e.g. ":shield:").
        enabled:               Whether this notifier is active.
        max_retries:           Number of retry attempts on transient failure.
        retry_backoff_seconds: Base wait time between retries (doubles each retry).
    """

    def __init__(
        self,
        webhook_url: str,
        channel: str = "#logsentinel-alerts",
        username: str = "LogSentinel Bot",
        icon_emoji: str = ":shield:",
        enabled: bool = True,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        self._webhook_url = webhook_url
        self._channel = channel
        self._username = username
        self._icon_emoji = icon_emoji
        self._enabled = enabled
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds

    @property
    def channel_name(self) -> str:
        return "slack"

    @property
    def is_enabled(self) -> bool:
        return (
            self._enabled
            and bool(self._webhook_url)
            and "PLACEHOLDER" not in self._webhook_url
        )

    async def send(self, alert: dict[str, Any]) -> bool:
        """Send a Slack message for the given alert."""
        payload = self._build_payload(alert)
        alert_id = alert.get("alert_id", "unknown")

        try:
            await self._post_with_retry(payload)
            logger.info(
                "Slack notification sent",
                extra={
                    "alert_id": alert_id,
                    "channel": self._channel,
                    "service": alert.get("service"),
                },
            )
            return True
        except Exception as exc:
            logger.error(
                "Slack notification failed after retries",
                extra={
                    "alert_id": alert_id,
                    "error": str(exc),
                },
            )
            return False

    def _build_payload(self, alert: dict[str, Any]) -> dict[str, Any]:
        """Build the Slack Block Kit webhook payload for the alert."""
        severity = _severity_from_alert(alert)
        emoji = _SEVERITY_EMOJI.get(severity, ":warning:")
        color = _SEVERITY_COLOR.get(severity, "#FFCC00")

        service = alert.get("service", "unknown")
        level = alert.get("level", "UNKNOWN")
        message = alert.get("message", "")[:200]
        score = round(float(alert.get("anomaly_score", 0.0)), 4)
        detected_at = alert.get("detected_at", datetime.now(timezone.utc).isoformat())
        alert_id = alert.get("alert_id", "N/A")
        response_time = alert.get("response_time_ms")
        error_code = alert.get("error_code")

        # Format detected_at for display
        try:
            datetime.fromisoformat(detected_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass

        # Build attachments (fallback for clients that don't support blocks)
        fields = [
            {"title": "Service", "value": f"`{service}`", "short": True},
            {"title": "Level", "value": level, "short": True},
            {"title": "Anomaly Score", "value": str(score), "short": True},
            {"title": "Severity", "value": severity, "short": True},
        ]
        if response_time is not None:
            fields.append(
                {"title": "Response Time", "value": f"{response_time}ms", "short": True}
            )
        if error_code is not None:
            fields.append(
                {"title": "Error Code", "value": str(error_code), "short": True}
            )

        return {
            "username": self._username,
            "icon_emoji": self._icon_emoji,
            "channel": self._channel,
            "text": f"{emoji} *Anomaly Detected* — `{service}` [{severity}]",
            "attachments": [
                {
                    "color": color,
                    "fallback": f"[{severity}] Anomaly in {service}: {message}",
                    "title": f"{emoji} LogSentinel Anomaly Alert [{severity}]",
                    "title_link": "",
                    "text": f"*Message:* {message}",
                    "fields": fields,
                    "footer": f"LogSentinel | Alert ID: {alert_id[:8]}...",
                    "footer_icon": (
                        "https://platform.slack-edge.com/img/"
                        "default_application_icon.png"
                    ),
                    "ts": int(datetime.now(timezone.utc).timestamp()),
                }
            ],
        }

    @retry(
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def _post_with_retry(self, payload: dict[str, Any]) -> None:
        """POST the payload to Slack with automatic retry on transient errors."""
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                self._webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as response:
                response_text = await response.text()
                if response.status != 200:
                    raise aiohttp.ClientResponseError(
                        request_info=response.request_info,
                        history=response.history,
                        status=response.status,
                        message=(
                            f"Slack webhook returned {response.status}: "
                            f"{response_text}"
                        ),
                    )
                if response_text != "ok":
                    logger.warning(
                        "Slack webhook returned non-ok response",
                        extra={"response": response_text[:200]},
                    )


# ---------------------------------------------------------------------------
# Email Notifier
# ---------------------------------------------------------------------------


class EmailNotifier(BaseNotifier):
    """
    Sends HTML email notifications for anomaly alerts via SMTP.

    Supports STARTTLS (port 587) and direct SSL/TLS (port 465).
    Email is sent synchronously in a thread pool executor to avoid
    blocking the asyncio event loop.

    Retries failed sends with exponential backoff (up to max_retries).

    Args:
        smtp_host:             SMTP server hostname.
        smtp_port:             SMTP server port.
        username:              SMTP authentication username.
        password:              SMTP authentication password.
        from_email:            Sender email address.
        from_name:             Sender display name.
        to_emails:             List of recipient email addresses.
        use_tls:               If True, use STARTTLS on port 587.
        enabled:               Whether this notifier is active.
        max_retries:           Number of retry attempts on transient failure.
        retry_backoff_seconds: Base wait time between retries.
    """

    def __init__(
        self,
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 587,
        username: str | None = None,
        password: str | None = None,
        from_email: str = "logsentinel@example.com",
        from_name: str = "LogSentinel",
        to_emails: list[str] | None = None,
        use_tls: bool = True,
        enabled: bool = True,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._username = username
        self._password = password
        self._from_email = from_email
        self._from_name = from_name
        self._to_emails = to_emails or []
        self._use_tls = use_tls
        self._enabled = enabled
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds

    @property
    def channel_name(self) -> str:
        return "email"

    @property
    def is_enabled(self) -> bool:
        return (
            self._enabled
            and bool(self._username)
            and bool(self._password)
            and bool(self._to_emails)
            and bool(self._smtp_host)
        )

    async def send(self, alert: dict[str, Any]) -> bool:
        """Send an email notification for the given alert."""
        alert_id = alert.get("alert_id", "unknown")

        try:
            subject, html_body = self._build_email(alert)
            # Run SMTP in a thread pool executor so it doesn't block the event loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._send_smtp_with_retry,
                subject,
                html_body,
            )
            logger.info(
                "Email notification sent",
                extra={
                    "alert_id": alert_id,
                    "to": self._to_emails,
                    "service": alert.get("service"),
                },
            )
            return True
        except Exception as exc:
            logger.error(
                "Email notification failed after retries",
                extra={"alert_id": alert_id, "error": str(exc)},
            )
            return False

    def _build_email(self, alert: dict[str, Any]) -> tuple[str, str]:
        """Build the email subject line and HTML body."""
        severity = _severity_from_alert(alert)
        service = alert.get("service", "unknown")
        level = alert.get("level", "UNKNOWN")
        message = alert.get("message", "")[:500]
        score = round(float(alert.get("anomaly_score", 0.0)), 4)
        detected_at = alert.get("detected_at", datetime.now(timezone.utc).isoformat())
        alert_id = alert.get("alert_id", "N/A")
        response_time = alert.get("response_time_ms", "N/A")
        error_code = alert.get("error_code", "N/A")
        host = alert.get("host", "N/A")

        # Format time
        try:
            dt = datetime.fromisoformat(detected_at.replace("Z", "+00:00"))
            display_time = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except (ValueError, AttributeError):
            display_time = detected_at

        subject = f"[LogSentinel] [{severity}] Anomaly Detected in {service}"

        color = _SEVERITY_COLOR.get(severity, "#FFCC00")

        html_body = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>LogSentinel Alert</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif;
             background-color: #f4f4f4;">
  <table width="100%" cellpadding="0" cellspacing="0"
      style="background-color: #f4f4f4; padding: 20px;">
    <tr>
      <td>
        <table width="600" cellpadding="0" cellspacing="0" align="center"
               style="background-color: #ffffff; border-radius: 8px;
                      box-shadow: 0 2px 4px rgba(0,0,0,0.1); overflow: hidden;">

          <!-- Header -->
          <tr>
            <td style="background-color: {color}; padding: 20px 30px; text-align: center;">
              <h1 style="color: #ffffff; margin: 0; font-size: 22px;">
                🛡️ LogSentinel Anomaly Alert
              </h1>
              <p style="color: rgba(255,255,255,0.9); margin: 5px 0 0 0; font-size: 14px;">
                Severity: <strong>{severity}</strong>
              </p>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding: 30px;">
              <table width="100%" cellpadding="8" cellspacing="0">
                <tr>
                  <td style="font-weight: bold; color: #555; width: 160px;">Service</td>
                  <td style="font-family: monospace; background: #f0f0f0;
                             padding: 4px 8px; border-radius: 4px;">{service}</td>
                </tr>
                <tr>
                  <td style="font-weight: bold; color: #555;">Level</td>
                  <td><strong>{level}</strong></td>
                </tr>
                <tr>
                  <td style="font-weight: bold; color: #555;">Anomaly Score</td>
                  <td style="font-family: monospace;">{score}</td>
                </tr>
                <tr>
                  <td style="font-weight: bold; color: #555;">Response Time</td>
                  <td>{response_time} ms</td>
                </tr>
                <tr>
                  <td style="font-weight: bold; color: #555;">Error Code</td>
                  <td>{error_code}</td>
                </tr>
                <tr>
                  <td style="font-weight: bold; color: #555;">Host</td>
                  <td style="font-family: monospace;">{host}</td>
                </tr>
                <tr>
                  <td style="font-weight: bold; color: #555;">Detected At</td>
                  <td>{display_time}</td>
                </tr>
                <tr>
                  <td style="font-weight: bold; color: #555;">Alert ID</td>
                  <td style="font-family: monospace; font-size: 12px;">{alert_id}</td>
                </tr>
              </table>

              <!-- Message block -->
              <div style="margin-top: 20px; padding: 15px; background-color: #fff8f0;
                          border-left: 4px solid {color}; border-radius: 4px;">
                <p style="margin: 0 0 6px 0; font-weight: bold; color: #555;">Log Message:</p>
                <p style="margin: 0; font-family: monospace; font-size: 13px;
                          color: #333; word-break: break-word;">{message}</p>
              </div>

              <!-- Action notice -->
              <div style="margin-top: 24px; padding: 12px; background-color: #f8f9fa;
                          border-radius: 4px; text-align: center;">
                <p style="margin: 0; font-size: 13px; color: #666;">
                  Please investigate this anomaly in your Grafana dashboard.
                  If this alert is expected, consider tuning the ML model threshold.
                </p>
              </div>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color: #f8f9fa; padding: 15px 30px;
                       text-align: center; border-top: 1px solid #eee;">
              <p style="margin: 0; font-size: 12px; color: #999;">
                This alert was generated automatically by LogSentinel.
                <br>To unsubscribe, update your SMTP_TO_EMAILS configuration.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
        return subject, html_body

    def _send_smtp_with_retry(self, subject: str, html_body: str) -> None:
        """
        Send the email via SMTP with retry logic.
        This runs synchronously in a thread pool executor.
        """
        last_exc: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                self._do_send_smtp(subject, html_body)
                return  # Success — exit retry loop
            except (smtplib.SMTPException, OSError, ConnectionRefusedError) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    import time

                    wait = self._retry_backoff_seconds * (2 ** (attempt - 1))
                    logger.warning(
                        f"SMTP send attempt {attempt} failed — retrying in {wait}s",
                        extra={"error": str(exc), "attempt": attempt},
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        f"SMTP send failed after {self._max_retries} attempts",
                        extra={"error": str(exc)},
                    )

        if last_exc:
            raise last_exc

    def _do_send_smtp(self, subject: str, html_body: str) -> None:
        """Perform the actual SMTP send (synchronous)."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{self._from_name} <{self._from_email}>"
        msg["To"] = ", ".join(self._to_emails)
        msg["X-Mailer"] = "LogSentinel Alert Service 1.0"

        # Attach HTML part
        html_part = MIMEText(html_body, "html", "utf-8")
        msg.attach(html_part)

        if self._use_tls:
            # STARTTLS (port 587)
            with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
                if self._username and self._password:
                    smtp.login(self._username, self._password)
                smtp.sendmail(
                    self._from_email,
                    self._to_emails,
                    msg.as_string(),
                )
        else:
            # Direct SSL (port 465)
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                self._smtp_host, self._smtp_port, context=context, timeout=30
            ) as smtp:
                if self._username and self._password:
                    smtp.login(self._username, self._password)
                smtp.sendmail(
                    self._from_email,
                    self._to_emails,
                    msg.as_string(),
                )
