from __future__ import annotations

import smtplib
from dataclasses import dataclass

# NOTE: outbound port 25 is blocked on the current host (tested), so this module is
# OFF by default (settings.smtp_verify_host == ""). It is wired and correct for a
# future port-25-capable relay; until then the pipeline relies on offline + holehe
# signals. Enable by setting INTERNHUNTER_SMTP_VERIFY_HOST.


@dataclass
class SmtpResult:
    valid: bool = False
    rejected: bool = False  # 550 -> mailbox does not exist
    catch_all: bool = False
    unknown: bool = True  # greylisted / could not determine


def _mx_hosts(domain: str) -> list[str]:
    try:
        import dns.resolver

        answers = dns.resolver.resolve(domain, "MX")
        ranked = sorted(answers, key=lambda r: r.preference)
        return [str(r.exchange).rstrip(".") for r in ranked]
    except Exception:
        return []


def _probe(mx: str, mail_from: str, rcpt: str, timeout: float) -> int | None:
    try:
        server = smtplib.SMTP(timeout=timeout)
        server.connect(mx, 25)
        server.helo("verify.local")
        server.docmd("MAIL FROM:", f"<{mail_from}>")
        code, _ = server.docmd("RCPT TO:", f"<{rcpt}>")
        server.quit()
        return code
    except (OSError, smtplib.SMTPException):
        return None


def verify_smtp(
    email: str,
    mail_from: str = "verify@example.com",
    timeout: float = 12.0,
) -> SmtpResult:
    """MX + catch-all probe + RCPT. Returns unknown on any network failure."""
    domain = email.split("@", 1)[1] if "@" in email else ""
    hosts = _mx_hosts(domain)
    if not hosts:
        return SmtpResult()
    mx = hosts[0]

    # Catch-all detection: does a guaranteed-fake address also get accepted?
    fake = f"zz9q7r-nonexistent-probe@{domain}"
    fake_code = _probe(mx, mail_from, fake, timeout)
    if fake_code is None:
        return SmtpResult()  # could not reach MX (e.g. port 25 blocked) -> unknown
    if 200 <= fake_code < 300:
        return SmtpResult(catch_all=True, unknown=False)

    code = _probe(mx, mail_from, email, timeout)
    if code is None:
        return SmtpResult()
    if 200 <= code < 300:
        return SmtpResult(valid=True, unknown=False)
    if code in (550, 551, 553):
        return SmtpResult(rejected=True, unknown=False)
    return SmtpResult()  # 4xx greylist / other -> unknown
