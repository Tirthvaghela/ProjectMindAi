"""User notifications — always delivered in-app; emailed too if SMTP is configured.

Mirrors nlp/ai_assistant.py's trade-off: the core behaviour (a notification a
user can see on their next visit) works with zero configuration, and the
optional integration (real email delivery) layers on top without ever being
required to run the app.
"""

from __future__ import annotations

import logging
import smtplib
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Optional

import config
from db import client as db

log = logging.getLogger(__name__)


def notify(
    user_id: str,
    type_: str,
    title: str,
    body: str,
    team_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> None:
    """Store an in-app notification, then attempt email delivery if configured.

    Email failure never raises — a notification the user can already see
    in-app must not be lost because an SMTP call failed.
    """
    db.notifications().insert_one(
        {
            "notification_id": str(uuid.uuid4()),
            "user_id": user_id,
            "type": type_,
            "title": title,
            "body": body,
            "team_id": team_id,
            "project_id": project_id,
            "read": False,
            "created_at": datetime.now(timezone.utc),
        }
    )

    if config.SMTP_ENABLED:
        _send_email(user_id, title, body)


def _send_email(user_id: str, title: str, body: str) -> None:
    user = db.users().find_one({"user_id": user_id}, {"_id": 0, "email": 1})
    if not user:
        return

    message = EmailMessage()
    message["Subject"] = f"ProjectMind AI — {title}"
    message["From"] = config.SMTP_FROM
    message["To"] = user["email"]
    message.set_content(body)

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(message)
    except Exception:  # noqa: BLE001
        # The in-app notification already succeeded; a broken mail server
        # should degrade to "no email today", not break the feature.
        log.exception("Failed to send notification email to %s", user["email"])
