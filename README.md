# InternHunter

Self-hosted internship discovery engine. It polls company ATS boards **directly** across 24 platforms in 3 tiers, grows its board registry automatically, ranks roles against your profile locally, **reads each posting to filter out spam/ghost/low-quality listings**, and **finds outreach contacts (recruiters, hiring managers) with verified emails**, surfacing rare/fresh internships that aggregators miss.

No third-party job-board API. No paywall. Your machine, your data, the companies' own endpoints.

**7,537 internships discovered so far.**

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

## Coverage (29 ATS platforms, 3 tiers + external listings)

| Tier | Transport | Platforms |
|---|---|---|
| **A** — keyless JSON | httpx | Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, Personio, Pinpoint |
| **B** — public HTML/JSON | httpx | BreezyHR, BambooHR, Jobvite, JazzHR, Zoho Recruit, Dover, Rippling, Gem, Comeet, Teamtailor |
| **C** — JSON/XML probe + stealth browser | httpx / Playwright / CloakBrowser | Workday, iCIMS, Oracle Cloud, ADP, UltiPro/UKG, Paylocity, Eightfold, Phenom, SuccessFactors, Taleo, NEOGOV |

Beyond company ATS boards, **external-listing ingestors** pull roles the aggregators surface and
recover the real ATS board behind each apply link where it exists (`reresolve` upgrades the rest):

| Source | Access | Notes |
|---|---|---|
| **LinkedIn** | keyless guest jobs API | rate-limited; personal single-user use |
| **USAJobs** (federal) | **keyless** (public HTML, no API key) | Pathways / student-trainee internships |
| **Big-company sites** | keyless JSON careers APIs | Google, Amazon, Microsoft, Apple, Netflix (extensible) |
| **University portals** | public-page JSON-LD harvest | recovers employer/ATS boards schools expose publicly |
| **Google Jobs** | approximated via JSON-LD + SearXNG | no direct SERP scraping |
| **Indeed** | keyless (stealth browser, **no login**) | on by default; full scrape, best-effort/bot-walled |
| **Bluesky** | keyless AT-Protocol post search | unauthenticated `searchPosts`; internship chatter |
| **Reddit** | keyless public `.json` | r/internships, r/csMajors, … |
| **EURES** | keyless EU public job search | large non-US / EU coverage |
| **Idealist** | keyless JSON-LD harvest | nonprofit / mission-driven internships |
| **Handshake** | **requires a university login session** | the one exception — no public/no-login feed exists; inert unless you supply your own session |
| **Simplify / community lists** | keyless GitHub JSON | already ingested via `--source github` |

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
internhunter discover --method greenhouse_frontier     # walk Greenhouse's GLOBAL job-id space (novel)
internhunter discover --method crt_bulk                # cert-transparency: EVERY company on a subdomain ATS (novel)
internhunter discover --method board_resolve           # DNS CNAME of careers.<co> -> ATS board
internhunter discover --method web_data_commons        # bulk schema.org JobPosting (set WEB_DATA_COMMONS_URL; off by default)
internhunter discover --method wayback                 # Wayback Machine CDX (2nd keyless index)
internhunter discover --method similar                 # embedding-based "companies like the ones you win on"
internhunter discover --method edgar                   # SEC Form D — just-funded startups (+ officer leads)
internhunter discover --method github_code             # opt-in: GitHub code search for ATS tokens (needs GITHUB_TOKEN, off by default)
internhunter discover-all                              # run every cheap channel + reresolve + grow registry (also scheduled daily)
internhunter reresolve                                 # recover real boards from unresolved 'listing' jobs (also runs in discover-all)
internhunter score                                     # local fit + freshness + rarity -> discovery score
internhunter score-quality                             # LLM reads borderline jobs -> legitimacy verdict (anti-slop)
internhunter ingest --source linkedin                  # LinkedIn keyless guest jobs API
internhunter ingest --source usajobs                   # federal internships, keyless (no API key)
internhunter ingest --source bigco                     # big-company custom careers APIs (Google/Amazon/MS/Apple/Netflix)
internhunter ingest --source university                # harvest ATS boards behind public university career pages
internhunter ingest --source google_jobs               # approximate Google Jobs via JSON-LD + SearXNG (needs SEARXNG_URL)
internhunter ingest --source bluesky                   # keyless AT-Protocol post search
internhunter ingest --source reddit                    # keyless r/internships etc. (.json)
internhunter ingest --source eures                     # keyless EU public job search
internhunter ingest --source idealist                  # keyless nonprofit internships (JSON-LD)
internhunter ingest --source indeed                    # keyless stealth-browser full scrape (no login; on by default)
internhunter ingest --source handshake                 # needs a saved Handshake login session (else inert)
internhunter ingest --source all                       # every keyless ingestor incl. indeed (skips login-only handshake)
internhunter ingest --source oflc --url <lca.xlsx>     # DOL OFLC LCA tech-hiring filings -> verified HR contacts + signal
internhunter ingest --source sbir                      # SBIR/STTR awards -> funded tech-firm contacts + signal
internhunter find-contacts --limit 50                  # find recruiters/hiring contacts + emails per company
internhunter find-contacts --company acme --methods searxng,github --verify
internhunter find-contacts --company acme --methods gov_disclosure --verify  # government-filing contacts
internhunter serve                                     # FastAPI + HTMX dashboard
```

### What grows coverage & filters slop

- **Scheduled discovery** (`discover-all`, daily) keeps the board registry full automatically — the biggest coverage lever, since the engine already polls 24 ATS platforms but the registry was only grown by manual runs. Channels: Common Crawl (paginated), urlscan, HN, broadened SearXNG dorks (all ATS × niche keywords), expanded GitHub list ingestion, **crt.sh** custom-domain careers enumeration, and **JSON-LD `JobPosting`** harvesting. The daily run also **reresolves** unrecognized `listing` jobs back into real boards, and an **opt-in GitHub code-search** channel (needs `GITHUB_TOKEN`, off by default) harvests ATS tokens at scale. `discover-all` additionally runs the keyless **external-listing ingestors** (LinkedIn guest API, keyless USAJobs, big-company careers APIs, public university-page harvest, Google-Jobs-via-JSON-LD, a keyless Indeed browser scrape, plus **Bluesky / Reddit / EURES / Idealist**) so roles posted only on the aggregators get pulled too — each fails soft and feeds any recovered ATS board into the registry. None of these require a login. Two novel **ground-truth** discovery channels also run: **`crt_bulk`** (one certificate-transparency query per subdomain-ATS surfaces *every* company on it) and **`board_resolve`** (DNS CNAME of `careers.<company>` → its ATS); a heavier **`web_data_commons`** bulk schema.org JobPosting harvest is available off by default. Only **Handshake** stays out of the automatic run: its student postings are gated behind a university SSO login, so it's inert unless you supply a saved session. Bot-walled sources fall back to a browser **TLS fingerprint** (`curl_cffi`, install `".[stealth]"`) — keyless, no proxies; the Indeed full-scrape can still hit IP rate limits at scale (set `HTTP_PROXY` or lower `INDEED_MAX_PAGES`).
- **Anti-slop quality reading** scores every job with free heuristics at ingest (ghost/agency/MLM/content-free/evergreen flags + a per-job `sightings` open-duration log), then an LLM reads only the *borderline* jobs (`score-quality`) and assigns a legitimacy verdict. The dashboard hides confirmed slop by default (toggle to show — **nothing is ever deleted**), and notifications skip it.

The dashboard is sortable by **discovery score**, **fit**, freshness, deadline, and more, with substring/ATS/remote filters and CSV export. A **Contacts** view lists discovered people per company with confidence-labelled emails and its own CSV export.

### Two novel ingestion mechanisms

Rather than scrape yet another third-party board, two channels exploit ground truth the field ignores:

- **Greenhouse global job-ID frontier** (`discover --method greenhouse_frontier`). Greenhouse job IDs are a single global monotonic counter, and `boards.greenhouse.io/embed/job_app?token={id}` 301-redirects with the company's board token injected as `for=`. Walking the recent ID frontier is **one primitive that ingests brand-new postings within ~an hour, discovers boards/companies never in the registry, and ranks by freshness** — all keyless. A checkpoint (`DiscoveryRun`) keeps each incremental run cheap (the high-water mark only advances over IDs that were *definitively* resolved, so a transient 429/5xx never silently skips a fresh posting); only the first run walks a full `GREENHOUSE_FRONTIER_WINDOW` (hard-capped by `GREENHOUSE_FRONTIER_MAX_WINDOW`). Runs on its own scheduler toggle (`ENABLE_GREENHOUSE_FRONTIER`). **Note:** this intentionally bypasses robots on the embed host and is a more aggressive access pattern than polling one board — throttle and set `HTTP_PROXY` if you hit IP-level rate limiting.
- **Government hiring-disclosure intelligence** (`ingest --source oflc|perm|sbir`). Employers that sponsor skilled workers must publish **DOL OFLC LCA/PERM** filings; **SBIR/STTR** awards list funded tech firms. Both carry **real, government-verified employer contact emails** (employer POC / SBIR PI) — no guessing, no SMTP. Ingest filters to tech SOC codes (`15-11xx`/`15-12xx`), stores them as `DisclosureLead`s read by the **opt-in** `gov_disclosure` contacts method (→ `verified`/`probable` via MX + provenance), and records a per-company "actively-hires-tech" signal that gives a small discovery-score boost. We deliberately **do not harvest third-party immigration-attorney emails** as contacts (not hiring contacts; GDPR/relevance) — attorney-only filings still count toward the company signal, just without a personal contact. `gov_disclosure` is not in the default `contacts_methods`: these are personal addresses, so provenance is stored (`email_source=gov:*`) and you should mind GDPR/CAN-SPAM before any outreach. OFLC files (a data.gov `.xlsx`, often `.zip`-wrapped) are streamed to disk; pass one via `--url` or `INTERNHUNTER_OFLC_LCA_URL` (dol.gov 403s plain bots — set `DISCLOSURE_USER_AGENT`). SBIR is keyless and joins `ingest --source all`. Install the parser extra with `pip install -e ".[disclosure]"`.

## Contacts (self-hosted, $0)

`find-contacts` enriches the companies behind discovered internships with outreach contacts — recruiters, hiring/eng managers, and a few engineers — and a best-effort email for each, using only self-hosted methods (no paid APIs):

- **People** — SearXNG LinkedIn-profile dorking (zero ban risk) + GitHub org members/commit authors, **GitLab** public members, and **`git_commits`** (bare-clone a company's top repos and walk full history for verified `@domain` author emails); optional company team pages and StaffSpy (aggressive, needs a burner LinkedIn cookie).
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

Conventions: Python 3.12+, async, fully typed (mypy strict), pydantic v2. Keep comments minimal — a docstring on a non-obvious public function or ORM model, and comments that explain *why* (not *what*), in line with the existing `core/`/`contacts/` code. Every poller ships with a saved fixture and a test.

## Contributing

- **Add an ATS** — implement a `Source` subclass under `sources/tier_*`, decorate with `@register_source`, add a fixture + test mirroring `sources/tier_a/recruitee.py`.
- **Add a discoverer** — implement a function returning `list[Detection]` under `discovery/`, feed it through `discovery/merge.py`. a
- **Contribute boards** — append real `(ats, token)` lines to `registry/boards.jsonl`; CI validates uniqueness and known ATSs.

## License

MIT.
