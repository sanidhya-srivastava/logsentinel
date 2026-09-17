"""
LogSentinel — Alert Service: Email Notifier (re-export)
========================================================
The full EmailNotifier implementation lives in app/alerter.py.
This module re-exports it so imports like:
    from app.notifiers.email_notifier import EmailNotifier
work correctly alongside the package __init__.py.
"""

from app.alerter import EmailNotifier

__all__ = ["EmailNotifier"]
