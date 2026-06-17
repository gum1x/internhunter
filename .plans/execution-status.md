# Execution status — find more internships & contacts

Plan: `.plans/find-more-internships-and-contacts.md`

## Phase 1 — close discovery gaps (DONE — 323 tests pass)
- [x] 1.1 SmartRecruiters fall-through — **NO CHANGE NEEDED** (plan premise was a misread; line 96 already falls through to `_valid_token(parts[0])`; covered by tests).
- [x] 1.2 Paylocity poller — replaced a **bogus placeholder** (fabricated `/recruiting/v2/api/jobs` that 404s) with a working keyless poller reading `window.pageData` JSON from the board HTML. Live board returned 12 jobs. Test + fixture updated to the real HTML shape.
- [x] 1.3 reresolve — was NOT in `discover-all`; now wired in (`core/runner.py`, reported via `per_method["reresolve"]`), and per-run listing cap raised 200→2000.

## Phase 2/3/4 — IN PROGRESS ("go all")

### Wave 1 (DONE)
- [x] A: detection+crawl patterns for Pinpoint/Comeet/Teamtailor — fingerprint + common_crawl + urlscan (wayback derives hosts automatically). +3 fingerprint tests.
- [x] B: Pinpoint poller — keyless `{token}.pinpointhq.com/postings.json`, confirmed live. +test/fixture.
- [x] C: Comeet poller (inline `COMPANY_POSITIONS_DATA` JSON) + Teamtailor poller (public site + JSON-LD, key-gated API avoided). Both confirmed live. +tests/fixtures.
- [x] D: `email/verify_dns.py` (MX/SPF/DMARC + catch-all), `email/rdap.py`, `email/openpgp.py`. +14 tests. (pgp name-search not keyless → omitted.)
- [x] G: GitHub code-search channel, flag OFF by default, no-op without token. +3 tests.

### Wave 2 (DONE)
- [x] E: harvest_security_txt + GitHub `.patch` real-email + rdap/pgp folded into corpus & signals; `score.py` +mx/spf-dmarc/pgp/catch-all signals; cap 8→16; default methods += team,registries.

### Wave 3 (DONE)
- [x] Full suite **361 passed**, ruff clean, mypy clean. Registry now lists **24 ATS pollers** (paylocity now functional; +pinpoint, comeet, teamtailor).

## NOT COMMITTED — awaiting review.
