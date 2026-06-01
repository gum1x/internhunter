from __future__ import annotations

import smtplib
from email.message import EmailMessage
from html import escape

from internhunter.core.db import Job


def _plain_line(job: Job) -> str:
    company = job.company or "unknown"
    return f"- {job.title} @ {company}: {job.canonical_url}"


def _html_item(job: Job) -> str:
    company = escape(job.company or "unknown")
    title = escape(job.title)
    url = escape(job.canonical_url)
    return f'<li><a href="{url}">{title}</a> @ {company}</li>'


def build_email(jobs: list[Job], sender: str, recipient: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = f"InternHunter: {len(jobs)} new internship match(es)"
    message["From"] = sender
    message["To"] = recipient

    plain = "\n".join([f"{len(jobs)} new internship match(es)", *(_plain_line(j) for j in jobs)])
    message.set_content(plain)

    items = "".join(_html_item(job) for job in jobs)
    html = f"<h2>{len(jobs)} new internship match(es)</h2><ul>{items}</ul>"
    message.add_alternative(html, subtype="html")
    return message


def send_email(
    message: EmailMessage,
    host: str,
    port: int,
    username: str | None = None,
    password: str | None = None,
) -> None:
    with smtplib.SMTP(host, port) as server:
        if username is not None and password is not None:
            server.login(username, password)
        server.send_message(message)
