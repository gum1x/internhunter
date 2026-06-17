from __future__ import annotations

import internhunter.contacts.email.verify_dns as vdns


class _FakeMX:
    def __init__(self, preference: int, exchange: str) -> None:
        self.preference = preference
        self.exchange = exchange


class _FakeTXT:
    def __init__(self, text: str) -> None:
        self.strings = [text.encode("utf-8")]


def test_mx_hosts_sorted_by_preference(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import dns.resolver

    def fake_resolve(name: str, rtype: str):  # type: ignore[no-untyped-def]
        assert rtype == "MX"
        return [_FakeMX(20, "mx2.acme.com."), _FakeMX(10, "mx1.acme.com.")]

    monkeypatch.setattr(dns.resolver, "resolve", fake_resolve)
    assert vdns.mx_hosts("acme.com") == ["mx1.acme.com", "mx2.acme.com"]


def test_mx_hosts_empty_on_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import dns.resolver

    def boom(name: str, rtype: str):  # type: ignore[no-untyped-def]
        raise RuntimeError("NXDOMAIN")

    monkeypatch.setattr(dns.resolver, "resolve", boom)
    assert vdns.mx_hosts("nope.invalid") == []


def test_has_spf_true_and_false(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import dns.resolver

    def with_spf(name: str, rtype: str):  # type: ignore[no-untyped-def]
        return [_FakeTXT("v=spf1 include:_spf.google.com ~all")]

    monkeypatch.setattr(dns.resolver, "resolve", with_spf)
    assert vdns.has_spf("acme.com") is True

    def no_spf(name: str, rtype: str):  # type: ignore[no-untyped-def]
        return [_FakeTXT("google-site-verification=abc")]

    monkeypatch.setattr(dns.resolver, "resolve", no_spf)
    assert vdns.has_spf("acme.com") is False


def test_has_dmarc_queries_underscore_subdomain(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import dns.resolver

    seen: list[str] = []

    def fake_resolve(name: str, rtype: str):  # type: ignore[no-untyped-def]
        seen.append(name)
        return [_FakeTXT("v=DMARC1; p=reject")]

    monkeypatch.setattr(dns.resolver, "resolve", fake_resolve)
    assert vdns.has_dmarc("acme.com") is True
    assert seen == ["_dmarc.acme.com"]


async def test_is_catch_all_none_without_smtp_host() -> None:
    assert await vdns.is_catch_all("acme.com", "") is None


async def test_is_catch_all_none_when_probe_unreachable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import internhunter.contacts.email.verify_smtp as smtp

    monkeypatch.setattr(smtp, "_mx_hosts", lambda d: ["mx.acme.com"])
    monkeypatch.setattr(smtp, "_probe", lambda *a, **k: None)
    assert await vdns.is_catch_all("acme.com", "mx.acme.com") is None


async def test_is_catch_all_true_when_fake_accepted(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import internhunter.contacts.email.verify_smtp as smtp

    monkeypatch.setattr(smtp, "_mx_hosts", lambda d: ["mx.acme.com"])
    monkeypatch.setattr(smtp, "_probe", lambda *a, **k: 250)
    assert await vdns.is_catch_all("acme.com", "mx.acme.com") is True


async def test_is_catch_all_false_when_fake_rejected(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import internhunter.contacts.email.verify_smtp as smtp

    monkeypatch.setattr(smtp, "_mx_hosts", lambda d: ["mx.acme.com"])
    monkeypatch.setattr(smtp, "_probe", lambda *a, **k: 550)
    assert await vdns.is_catch_all("acme.com", "mx.acme.com") is False
