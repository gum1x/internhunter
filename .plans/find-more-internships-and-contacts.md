# Plan: Find way more internships and contacts

## Goal & constraints

Increase both (a) internship/board coverage and (b) recruiter/hiring-manager contacts per company — **raw volume *and* long-tail/relevant depth** — while expanding sector breadth.

**Hard constraint (unchanged project ethos):** $0, keyless, self-hosted. No paid APIs, no *required* API keys. Anything needing even a free token (GitHub code search, USAJOBS) must be **optional behind a config flag**, defaulting off, so the core stays truly keyless.

Success is measured per phase below with a concrete check. Each item traces to "more/better internships or contacts."

---

## Current state (verified, not assumed)

**Discovery** — 14 channels, all keyless: `common_crawl`, `wayback`, `urlscan`, `crt_sh`, `jsonld`, `sitemap`, `hackernews`, `searxng` (self-hosted), `yc`, `vc`, `edgar`, `similar`, `internship_lists`, `job_apis`. Registry = append-only `internhunter/registry/boards.jsonl` + DB `Board` rows, grown via `merge_boards()`.

- `internship_lists.py` **already** ingests the big SimplifyJobs `Summer2026` `listings.json` + 5 sibling repos AND already extracts ATS tokens into the registry (`board_refs()`, lines 121–146). **Not a quick win — already done.**
- 20 ATS platforms fingerprinted; **only ~6 have live boards** in the registry (Greenhouse 95, Lever 40, Ashby 20, the rest ≤2). The bottleneck is breadth of *discovered tokens*, not poller count.
- `sectors.yaml` is **scoring-only** — it does NOT drive discovery. Discovery is breadth-first/blind. So "more sectors" = more scoring categories, not more crawling.

**Known gaps in `fingerprint.py`:**
- No patterns for **Pinpoint** (`*.pinpointhq.com`), **Teamtailor**, **Comeet**.
- `jobs.smartrecruiters.com/{token}` (non-API host) falls through to `None` (lines 88–96) — only `api.smartrecruiters.com/.../companies/{token}` is detected. Likely losing real boards.
- **Paylocity** is fingerprinted (`_PATH_FIRST_ATS`, line 150) but has **no poller** (`tier_c/paylocity.py` missing) → discovered boards can't be polled. **Taleo** is a stub.

**Contacts** — people sources: `ats_raw`, `github_people`, `searxng_people`, `staffspy_people` (needs LinkedIn cookie), `team_pages` (needs LLM), `registries` (npm/PyPI). Email: `harvest`, `infer`, `permute`, `priors`, `finder`. Verify: `github`, `gravatar`, `holehe`, `m365`, `smtp` (disabled — port 25). Final cap **8 contacts/company**.

---

## Phase 1 — Close discovery gaps that lose boards we already see (highest ROI, lowest effort)

| # | Change | Files | Why it adds internships |
|---|---|---|---|
| 1.1 | Add `jobs.smartrecruiters.com/{token}` detection (fall-through case) | `discovery/fingerprint.py` `_detect_smartrecruiters` | We crawl SmartRecruiters URLs but drop the common non-API host → recovering them adds boards for an ATS we already poll. |
| 1.2 | Implement **Paylocity poller** | new `sources/tier_c/paylocity.py` + register in `tier_c/__init__.py` | Boards already discovered but unpollable today. Pure conversion of existing discoveries into live jobs. |
| 1.3 | Broaden `reresolve` reach | `discovery/reresolve.py` | Jobs stored as `ats='listing'` (host didn't fingerprint) are dead weight; reresolving recovers real boards from lists/HN/crawl we already fetched. Confirm it runs in `discover-all`. |

**Verify:** `internhunter registry stats` board count rises after `discover-all`; `internhunter poll --ats paylocity` returns jobs from a known Paylocity board; count of `ats='listing'` jobs drops after `reresolve`.

---

## Phase 2 — Add net-new keyless ATS platforms (more boards from sources we don't see today)

Each new platform = fingerprint pattern + poller + add host to the crawl/index dorks. All keyless.

| # | Platform | Endpoint (keyless) | Files |
|---|---|---|---|
| 2.1 | **Pinpoint** | `https://{sub}.pinpointhq.com/postings.json` | `fingerprint.py` (+`.pinpointhq.com` subdomain), new `sources/tier_a/pinpoint.py`, add host to `common_crawl.py`/`wayback.py`/`urlscan.py` pattern lists |
| 2.2 | **Comeet** | public career site `comeet.com/jobs/{uid}/...`; harvest `uid`+`token` from page HTML → `careers-api/2.0/company/{uid}/positions?token=` | `fingerprint.py`, new `sources/tier_b/comeet.py` |
| 2.3 | **Teamtailor** | API needs key → **scrape public career-site embedded JSON** instead | `fingerprint.py`, new `sources/tier_b/teamtailor.py` (HTML/JSON-in-page) |

Recommended order: **Pinpoint first** (cleanest keyless JSON), then Comeet, then Teamtailor (most fragile — HTML scrape).

**Verify:** for each, a hand-picked known board polls to ≥1 job; `discover --method common_crawl --ats pinpoint` finds tokens.

---

## Phase 3 — More token harvesting into the registry (volume + long tail)

| # | Change | Files | Notes |
|---|---|---|---|
| 3.1 | Add per-ATS **Common Crawl CDX wildcard** sweeps for the new hosts (3.x) + any missing existing hosts | `discovery/common_crawl.py` patterns | Already the workhorse; just extend host list to new ATS. $0/keyless. |
| 3.2 | **Optional** GitHub code-search token harvester behind a config flag (default off) | new `discovery/github_code.py`, `config/settings.py` flag | Searches `boards.greenhouse.io`, `jobs.lever.co`, `.recruitee.com/api/offers`, etc. in public repos → thousands of tokens. **Needs a free PAT → flag-gated to preserve keyless default.** |

**Verify:** registry grows measurably after a sweep; flag off = no GitHub calls (assert in a test).

> **Sector breadth note:** "more sectors" is a `sectors.yaml` change (scoring), independent of crawling. Add the new sector keyword groups there + reflect in `profile.yaml` targets. Small, separate change — fold in if the user wants new industries ranked, but it does not change what's discovered.

---

## Phase 4 — More & better contacts (keyless people/email seeds)

### 4a. New people/email seed sources (additive, cheap, keyless)

| # | Source | Method | Files |
|---|---|---|---|
| 4.1 | **GitHub `.patch` real-email trick** | append `.patch` to a public commit URL → author email in header (works even when API hides it) | extend `contacts/people/github_people.py` or `contacts/email/harvest.py` |
| 4.2 | **security.txt** | GET `https://{domain}/.well-known/security.txt` → real contact email + often the format convention | new harvest path in `contacts/email/harvest.py` |
| 4.3 | **RDAP/WHOIS** | `https://rdap.org/domain/{domain}` → registrant/abuse email (best on smaller/older domains) | new tiny module under `contacts/email/` |
| 4.4 | **OpenPGP keyserver** | `keys.openpgp.org/vks/v1/by-email/...` and by-name → verified name↔email pairs (great pattern seeds) | new tiny module |

These feed the existing `infer`/`finder` pipeline as known-good `(name,email)` pairs → better pattern locking, not just more raw guesses.

### 4b. Verification layer to cut false positives (quality)

| # | Signal | Method | Files |
|---|---|---|---|
| 4.5 | **MX gate** | dnspython MX query; no MX → invalid, skip work | new `contacts/email/verify_dns.py` |
| 4.6 | **Catch-all detection** | RCPT a random `zz-{rand}@domain`; accepted → mark domain accept-all/unverifiable (biggest FP source, ~30% of domains) | `verify_dns.py` / extend `verify_smtp.py` |
| 4.7 | **SPF/DMARC presence** | TXT lookups → confidence *signal* (well-managed domain) | `verify_dns.py`, wire into `score.py` |

### 4c. Volume knobs (config, near-zero code)

- Raise `contacts_max_per_company` (8 → e.g. 16) and default `contacts_methods` to include `team,registries`. Expose per-company cap in settings. (`config/settings.py`, `contacts/runner.py`)

**Verify:** on a test company with a known email format, 4.1–4.4 produce ≥1 verified ground-truth pair and the inferred template locks; catch-all test domain gets flagged `accept-all`; raising the cap yields more persisted `Contact` rows.

---

## Explicitly out of scope (respecting the $0/keyless ethos)

- Paid contact DBs / email-finders (Hunter, RocketReach, Snov, Clearbit), Crunchbase API, Teamtailor API key, USAJOBS key, jorb.ai (it's a competitor SaaS, no integration surface).
- LinkedIn graph walking beyond existing StaffSpy (ban risk, needs session).
- Any speculative abstraction/config not needed by the above.

## Suggested sequencing

1. **Phase 1** (gap-fill, fastest payoff) → 2. **Phase 2.1 Pinpoint** → 3. **Phase 4a + 4b** (contacts) → 4. **Phase 2.2/2.3, Phase 3** as appetite allows.

Phases are independent; each can ship and be verified on its own.
