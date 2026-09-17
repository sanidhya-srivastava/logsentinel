"""
LogSentinel — Alert Service: Slack Notifier (re-export)
========================================================
The full SlackNotifier implementation lives in app/alerter.py.
This module re-exports it so imports like:
    from app.notifiers.slack_notifier import SlackNotifier
work correctly alongside the package __init__.py.
"""

from app.alerter import SlackNotifier

__all__ = ["SlackNotifier"]
