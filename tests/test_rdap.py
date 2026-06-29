from __future__ import annotations

import json

import httpx

from internhunter.contacts.email.rdap import rdap_emails

_URL = "https://rdap.org/domain/acme.com"


def _vcard(email: str) -> list:  # type: ignore[type-arg]
    return ["vcard", [["version", {}, "text", "4.0"], ["email", {}, "text", email]]]


async def test_rdap_emails_extracts_and_dedupes(fake_fetch_context) -> None:  # type: ignore[no-untyped-def]
    ctx = fake_fetch_context
    ctx.responses[_URL] = httpx.Response(
        200,
        text=json.dumps(
            {
                "entities": [
                    {
                        "roles": ["registrant"],
                        "vcardArray": _vcard("Owner@Acme.com"),
                        "entities": [
                            {
                                "roles": ["abuse"],
                                "vcardArray": _vcard("abuse@acme.com"),
                            }
                        ],
                    },
                    {"roles": ["technical"], "vcardArray": _vcard("owner@acme.com")},
                ]
            }
        ),
    )
    emails = await rdap_emails(ctx, "acme.com")
    # lowercased, nested entity walked, duplicate collapsed
    assert emails == ["owner@acme.com", "abuse@acme.com"]


async def test_rdap_emails_empty_on_404(fake_fetch_context) -> None:  # type: ignore[no-untyped-def]
    ctx = fake_fetch_context
    assert await rdap_emails(ctx, "acme.com") == []


async def test_rdap_emails_empty_when_no_contacts(fake_fetch_context) -> None:  # type: ignore[no-untyped-def]
    ctx = fake_fetch_context
    ctx.responses[_URL] = httpx.Response(
        200, text=json.dumps({"objectClassName": "domain", "entities": []})
    )
    assert await rdap_emails(ctx, "acme.com") == []


async def test_rdap_emails_filter_domain_drops_offdomain(fake_fetch_context) -> None:  # type: ignore[no-untyped-def]
    # RDAP exposes registrar/abuse contacts off the target domain; with a filter only
    # @acme.com survives so the company corpus isn't polluted.
    ctx = fake_fetch_context
    ctx.responses[_URL] = httpx.Response(
        200,
        text=json.dumps(
            {
                "entities": [
                    {"vcardArray": _vcard("owner@acme.com")},
                    {"vcardArray": _vcard("abuse@registrar.example")},
                    {"vcardArray": _vcard("privacy@whoisprivacy.com")},
                ]
            }
        ),
    )
    assert await rdap_emails(ctx, "acme.com", filter_domain="acme.com") == ["owner@acme.com"]
