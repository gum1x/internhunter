# InternHunter

Self-hosted internship discovery engine. It polls company ATS boards **directly** across 20 platforms in 3 tiers, maintains a self-growing registry of boards, ranks roles against your profile locally, and surfaces rare/fresh internships that aggregators miss.

No third-party job-board API. No paywall. Your machine, your data, the companies' own endpoints.

## Why

Most internship aggregators scrape the same large boards and miss the long tail of small/rare company boards. InternHunter goes to the source — the ATS each company actually uses — fingerprints new boards from Common Crawl, sitemaps, SearXNG, and HN "Who is hiring", dedupes dual-posted roles, and scores everything by fit, freshness, and rarity so the rare-and-fresh roles float to the top.

## 60-second quickstart

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

internhunter init-db
internhunter poll --ats greenhouse,lever,ashby     # pull live internships into SQLite
internhunter serve                                 # dashboard at http://127.0.0.1:8000
```

Or with Docker (app + SearXNG):

```bash
cp .env.example .env
docker compose up --build
```

## Coverage (20 platforms, 3 tiers)

| Tier | Transport | Platforms |
|---|---|---|
| **A** — keyless JSON | httpx | Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, Personio |
| **B** — public HTML/JSON | httpx | BreezyHR, BambooHR, Jobvite, JazzHR, Zoho Recruit, Dover, Rippling, Gem |
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
internhunter score                                     # local fit + freshness + rarity -> discovery score
internhunter serve                                     # FastAPI + HTMX dashboard
```

The dashboard is sortable by **discovery score**, **fit**, freshness, deadline, and more, with substring/ATS/remote filters and CSV export.

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
- **Add a discoverer** — implement a function returning `list[Detection]` under `discovery/`, feed it through `discovery/merge.py`.
- **Contribute boards** — append real `(ats, token)` lines to `registry/boards.jsonl`; CI validates uniqueness and known ATSs.

## License

MIT.
