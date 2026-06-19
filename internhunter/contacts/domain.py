from __future__ import annotations

import re
from dataclasses import dataclass

# Aggregator / ATS / social hosts that are never a company's own email domain.
_NON_COMPANY = {
    "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "smartrecruiters.com",
    "recruitee.com", "personio.com", "breezy.hr", "applytojob.com", "bamboohr.com",
    "jobvite.com", "zohorecruit.com", "dover.com", "rippling-ats.com", "myworkdayjobs.com",
    "icims.com", "ultipro.com", "adp.com", "paylocity.com", "linkedin.com", "indeed.com",
    "glassdoor.com", "github.com", "google.com", "facebook.com", "twitter.com", "x.com",
    "youtube.com", "crunchbase.com", "wellfound.com", "angel.co", "themuse.com",
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")

# Bound DNS lookups so a slow/hostile authoritative nameserver can't stall a worker.
_DNS_TIMEOUT = 5.0


def _strip_www(domain: str) -> str:
    return domain[4:] if domain.startswith("www.") else domain


@dataclass
class ResolvedDomain:
    domain: str | None
    confidence: float  # 0–1
    source: str


def _clean(name: str | None) -> str:
    if not name:
        return ""
    return _SLUG_RE.sub("", name.lower())


def candidate_domains(name: str | None, slug: str | None) -> list[str]:
    bases = []
    for raw in (slug, _clean(name)):
        c = _clean(raw)
        if c and c not in bases:
            bases.append(c)
    out: list[str] = []
    for base in bases:
        for tld in (".com", ".io", ".ai", ".co"):
            out.append(base + tld)
    return out


def is_company_domain(domain: str | None) -> bool:
    if not domain:
        return False
    d = _strip_www(domain.lower())
    return not any(d == bad or d.endswith("." + bad) for bad in _NON_COMPANY)


def mx_host(domain: str) -> str | None:
    """Lowest-preference MX exchange host (dnspython; None if dep/lookup fails)."""
    try:
        import dns.resolver

        answers = dns.resolver.resolve(domain, "MX", lifetime=_DNS_TIMEOUT)
        ranked = sorted(answers, key=lambda r: r.preference)
        return str(ranked[0].exchange).rstrip(".").lower() if ranked else None
    except Exception:
        return None


def classify_provider(mx: str | None) -> str:
    """Map an MX host to its mail provider: microsoft | google | other | unknown."""
    if not mx:
        return "unknown"
    m = mx.lower()
    if m.endswith("mail.protection.outlook.com") or "outlook.com" in m:
        return "microsoft"
    if m.endswith("google.com") or m.endswith("googlemail.com") or "aspmx" in m:
        return "google"
    return "other"


def has_mx(domain: str) -> bool:
    """True if the domain publishes MX records (dnspython; False if dep/lookup fails)."""
    return mx_host(domain) is not None


def provider_from_spf(txt: str) -> str | None:
    """Map an SPF TXT record to its real mail backend (sees through gateway MX)."""
    t = txt.lower()
    if not t.startswith("v=spf1"):
        return None
    if "include:spf.protection.outlook.com" in t:
        return "microsoft"
    if "include:_spf.google.com" in t or "include:_spf.google" in t:
        return "google"
    return None


def _spf_provider(domain: str) -> str | None:
    try:
        import dns.resolver

        for rr in dns.resolver.resolve(domain, "TXT", lifetime=_DNS_TIMEOUT):
            txt = "".join(
                s.decode("utf-8", "ignore") if isinstance(s, bytes) else str(s)
                for s in rr.strings
            )
            result = provider_from_spf(txt)
            if result:
                return result
    except Exception:
        return None
    return None


def _autodiscover_provider(domain: str) -> str | None:
    try:
        import dns.resolver

        ans = dns.resolver.resolve(f"autodiscover.{domain}", "CNAME", lifetime=_DNS_TIMEOUT)
        target = str(ans[0].target).rstrip(".").lower()
        if "outlook.com" in target:
            return "microsoft"
    except Exception:
        return None
    return None


def classify_provider_deep(domain: str, mx: str | None = None) -> str:
    """Provider classification that de-cloaks gateway/vanity MX (Mimecast, Proofpoint,
    Barracuda, etc.) via SPF/Autodiscover DNS — so the M365 verifier fires on the many
    real M365/Google tenants hidden behind an email-security gateway."""
    resolved_mx = mx if mx is not None else mx_host(domain)
    base = classify_provider(resolved_mx)
    if base in ("microsoft", "google"):
        return base
    return _spf_provider(domain) or _autodiscover_provider(domain) or base


def resolve_domain(
    name: str | None,
    slug: str,
    known_domain: str | None = None,
    check_mx: bool = True,
) -> ResolvedDomain:
    """Best company email domain + confidence, using only free/offline signals.

    Priority: a real domain already on the job rows > an MX-validated guess > a bare
    slug fallback (low confidence so downstream never *trusts* a wrong domain).
    """
    if known_domain and is_company_domain(known_domain):
        return ResolvedDomain(_strip_www(known_domain.lower()), 1.0, "job_metadata")

    candidates = candidate_domains(name, slug)
    if check_mx:
        for candidate in candidates:
            if has_mx(candidate):
                return ResolvedDomain(candidate, 0.7, "mx_validated")

    fallback = candidates[0] if candidates else None
    return ResolvedDomain(fallback, 0.3, "slug_fallback")
