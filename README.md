# InternHunter

Self-hosted internship discovery engine. It polls company ATS boards **directly** across 24 platforms in 3 tiers, grows its board registry automatically, ranks roles against your profile locally, **reads each posting to filter out spam/ghost/low-quality listings**, and **finds outreach contacts (recruiters, hiring managers) with verified emails** — surfacing rare/fresh internships that aggregators miss.

No third-party job-board API. No paywall. Your machine, your data, the companies' own endpoints.

## Why

Most internship aggregators scrape the same large boards and miss the long tail of small/rare company boards. InternHunter goes to the source — the ATS each company actually uses — fingerprints new boards from Common Crawl, sitemaps, SearXNG, HN "Who is hiring", **certificate-transparency careers-subdomain enumeration (crt.sh)**, and **schema.org `JobPosting` harvesting**, on a daily schedule. It dedupes dual-posted roles, scores everything by fit, freshness, and rarity, and runs a **local-LLM quality pass** so real rare-and-fresh roles float to the top while slop sinks. Then, for the companies behind those roles, it discovers the people worth contacting and infers/verifies their emails — all $0 and self-hosted.

## 60-second quickstart

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

internhunter init-db
internhunter poll --ats greenhouse,lever,ashby     # pull live internships into SQLite
internhunter serve                                 
```

Or with Docker (app + SearXNG):

```bash
cp .env.example .env
docker compose up --build
```

## Coverage (24 platforms, 3 tiers)

| Tier | Transport | Platforms |
|---|---|---|
| **A** — keyless JSON | httpx | Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, Personio, Pinpoint |
| **B** — public HTML/JSON | httpx | BreezyHR, BambooHR, Jobvite, JazzHR, Zoho Recruit, Dover, Rippling, Gem, Comeet, Teamtailor |
| **C** — JSON/XML probe + stealth browser | httpx / Playwright / CloakBrowser | Workday, iCIMS, Oracle Cloud, ADP, UltiPro/UKG, Paylocity |

## Commands

```bash
internhunter init-db                                   # create the SQLite schema
internhunter poll --ats greenhouse,lever               # poll registry boards for those ATSs
internhunter poll --ats workday --board <tenant/site> --dc wd5   # poll one ad-hoc board
internhunter registry stats                            # board counts per ATS
internhunter detect <careers-url>                      # fingerprint a URL -> ats/token
internhunter discover --method common_crawl --ats greenhouse     # grow the registry
internhunter discover --method hackernews              # boards from HN "Who is hiring"
internhunter discover --method searxng --url http://localhost:8888
internhunter discover --method crtsh --url acme.com    # custom-domain careers via cert transparency
internhunter discover --method jsonld --url https://acme.com/careers  # schema.org JobPosting
internhunter discover --method wayback                 # Wayback Machine CDX (2nd keyless index)
internhunter discover --method similar                 # embedding-based "companies like the ones you win on"
internhunter discover --method edgar                   # SEC Form D — just-funded startups (+ officer leads)
internhunter discover --method github_code             # opt-in: GitHub code search for ATS tokens (needs GITHUB_TOKEN, off by default)
internhunter discover-all                              # run every cheap channel + reresolve + grow registry (also scheduled daily)
internhunter reresolve                                 # recover real boards from unresolved 'listing' jobs (also runs in discover-all)
internhunter score                                     # local fit + freshness + rarity -> discovery score
internhunter score-quality                             # LLM reads borderline jobs -> legitimacy verdict (anti-slop)
internhunter find-contacts --limit 50                  # find recruiters/hiring contacts + emails per company
internhunter find-contacts --company acme --methods searxng,github --verify
internhunter serve                                     # FastAPI + HTMX dashboard
```

### What grows coverage & filters slop

- **Scheduled discovery** (`discover-all`, daily) keeps the board registry full automatically — the biggest coverage lever, since the engine already polls 24 ATS platforms but the registry was only grown by manual runs. Channels: Common Crawl (paginated), urlscan, HN, broadened SearXNG dorks (all ATS × niche keywords), expanded GitHub list ingestion, **crt.sh** custom-domain careers enumeration, and **JSON-LD `JobPosting`** harvesting. The daily run also **reresolves** unrecognized `listing` jobs back into real boards, and an **opt-in GitHub code-search** channel (needs `GITHUB_TOKEN`, off by default) harvests ATS tokens at scale.
- **Anti-slop quality reading** scores every job with free heuristics at ingest (ghost/agency/MLM/content-free/evergreen flags + a per-job `sightings` open-duration log), then an LLM reads only the *borderline* jobs (`score-quality`) and assigns a legitimacy verdict. The dashboard hides confirmed slop by default (toggle to show — **nothing is ever deleted**), and notifications skip it.

The dashboard is sortable by **discovery score**, **fit**, freshness, deadline, and more, with substring/ATS/remote filters and CSV export. A **Contacts** view lists discovered people per company with confidence-labelled emails and its own CSV export.

## Contacts (self-hosted, $0)

`find-contacts` enriches the companies behind discovered internships with outreach contacts — recruiters, hiring/eng managers, and a few engineers — and a best-effort email for each, using only self-hosted methods (no paid APIs):

- **People** — SearXNG LinkedIn-profile dorking (zero ban risk) + GitHub org members/commit authors; optional company team pages and StaffSpy (aggressive, needs a burner LinkedIn cookie).
- **Emails** — published/scraped addresses (including `/.well-known/security.txt` and RDAP registrant records), real GitHub commit emails (via the `.patch` trick), email-format inference from same-domain samples, size-aware priors, and recruiting aliases (`careers@`, `university@`).
- **Confidence** — every email is scored 0–100 and labelled `verified` / `probable` / `guessed` from honest signals: DNS **MX / SPF / DMARC** checks, **OpenPGP keyserver** confirmation, GitHub, Gravatar, `holehe`, and **catch-all detection**. Live SMTP verification is wired but **off by default** (the typical residential host blocks outbound port 25); the HTTPS/DNS-based signals (`--verify`) work regardless.

Config via `INTERNHUNTER_*` env vars: `CONTACTS_METHODS`, `CONTACTS_MAX_PER_COMPANY`, `GITHUB_TOKEN` (lifts the GitHub rate limit), `VERIFY_EMAILS`, `LLM_BASE_URL` (local llama.cpp for role classification; falls back to a keyword heuristic). Install extras with `pip install -e ".[contacts]"` (or `".[contacts,contacts-aggressive]"` for StaffSpy).

## How it works

```
sources/{tier_a,tier_b,tier_c}/   one Source per ATS, registered via @register_source
core/fetch.py                     async httpx: shared client, semaphores, retry/backoff, on-disk cache, robots gate
core/browser.py                   BrowserFactory: Playwright <-> CloakBrowser, lazy + injectable
core/normalize.py + internship_filter.py   normalize fields, classify internships (title-anchored, precision-tuned)
core/dedup.py                     exact (url_hash) + fuzzy (company+title+location) collapse of dual-posted roles
discovery/                        fingerprint detection + Common Crawl / sitemap / SearXNG / HN discoverers + registry merge
match/                            sentence-transformers embeddings, cosine fit, rarity/freshness -> discovery score
llm/                              deep-scoring via `claude -p` (headless) or the Anthropic API (when ANTHROPIC_API_KEY is set)
notify/                           Discord / ntfy / email / RSS on new high-fit + deadline-approaching roles
scheduler.py                      APScheduler per-ATS cadence (Tier A frequent, Tier C slow)
web/                              FastAPI + HTMX dashboard
registry/boards.jsonl             committed, community-contributable seed registry
```

The registry is **self-growing**: discoverers fingerprint new boards from Common Crawl, sitemaps, SearXNG, and HN, dedupe by `(ats, token)`, and append to `boards.jsonl` + the `boards` table.

## LLM deep-scoring

Local ranking (sentence-transformers) handles every job for free. For the top-K, optional LLM deep-scoring adds a 0–100 fit, matched/missing requirements, and a short rationale. It defaults to the **headless `claude -p` CLI** and automatically uses the **Anthropic API** (`claude-opus-4-8`) when `ANTHROPIC_API_KEY` is set. Responses are cached on disk by input hash.

## Development

```bash
pip install -e ".[dev]"
ruff check internhunter tests
mypy internhunter
pytest -q
```

Conventions: Python 3.12+, async, fully typed (mypy strict), pydantic v2, no comments/docstrings in source. Every poller ships with a saved fixture and a test.

## Contributing

- **Add an ATS** — implement a `Source` subclass under `sources/tier_*`, decorate with `@register_source`, add a fixture + test mirroring `sources/tier_a/recruitee.py`.
- **Add a discoverer** — implement a function returning `list[Detection]` under `discovery/`, feed it through `discovery/merge.py`. a
- **Contribute boards** — append real `(ats, token)` lines to `registry/boards.jsonl`; CI validates uniqueness and known ATSs.

## License

MIT.
