from __future__ import annotations

import os

# Pure-DNS signals about a domain's mail setup. Unlike SMTP RCPT (which needs port 25,
# blocked on this host), MX/SPF/DMARC lookups are plain DNS and always work over UDP/53.
# They don't prove a single mailbox exists, but they confirm the domain accepts mail and
# how seriously it's configured — useful priors for scoring guessed addresses. The
# catch-all probe is the one piece that does need SMTP, so it reuses verify_smtp and
# degrades to None when unavailable.


def _txt_records(name: str) -> list[str]:
    try:
        import dns.resolver

        answers = dns.resolver.resolve(name, "TXT")
    except Exception:
        return []
    out: list[str] = []
    for rr in answers:
        try:
            # dnspython TXT rdata joins multi-string records via .strings (bytes chunks)
            chunks = getattr(rr, "strings", None)
            if chunks is not None:
                out.append(b"".join(chunks).decode("utf-8", "replace"))
            else:
                out.append(str(rr).strip('"'))
        except Exception:
            continue
    return out


def mx_hosts(domain: str) -> list[str]:
    """MX exchange hostnames, lowest preference first. Empty on none/NXDOMAIN/error."""
    try:
        import dns.resolver

        answers = dns.resolver.resolve(domain, "MX")
    except Exception:
        return []
    ranked = sorted(answers, key=lambda r: r.preference)
    return [str(r.exchange).rstrip(".") for r in ranked]


def has_spf(domain: str) -> bool:
    """True if the domain publishes an SPF record (TXT containing ``v=spf1``)."""
    return any("v=spf1" in txt.lower() for txt in _txt_records(domain))


def has_dmarc(domain: str) -> bool:
    """True if ``_dmarc.{domain}`` publishes a DMARC policy (``v=DMARC1``)."""
    return any("v=dmarc1" in txt.lower() for txt in _txt_records(f"_dmarc.{domain}"))


async def is_catch_all(domain: str, smtp_host: str) -> bool | None:
    """Probe whether the domain accepts mail for any address (catch-all).

    Sends RCPT for a guaranteed-nonexistent random local-part via the existing
    verify_smtp mechanism. Returns True if accepted (catch-all), False if rejected,
    and None when it cannot be determined (no smtp_host, port 25 blocked, greylisting,
    or any failure). Never raises.
    """
    if not smtp_host:
        return None

    from internhunter.contacts.email import verify_smtp as smtp

    hosts = smtp._mx_hosts(domain)
    if not hosts:
        return None

    rand = os.urandom(8).hex()
    fake = f"zz-nonexistent-{rand}@{domain}"
    code = smtp._probe(hosts[0], "verify@example.com", fake, 12.0)
    if code is None:
        return None
    if 200 <= code < 300:
        return True
    if code in (550, 551, 553):
        return False
    return None  # 4xx greylist / other -> undetermined
